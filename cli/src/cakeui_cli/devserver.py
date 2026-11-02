"""运行前端的开发服务器（Vite，或者项目自己声明的命令）。"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from cakeui.bridge import ensure_bridge_module
from cakeui.config import CakeUIConfig
from cakeui.errors import CakeUIError

from . import packages

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_URL = re.compile(r"https?://[^\s\"'<>)\]]+")


class DevServerError(CakeUIError):
    """开发服务器起不来，或者一直没报出地址。"""

    code = "dev_server_error"


@dataclass(frozen=True)
class DevCommand:
    """一条开发服务器命令，以及它该在哪个目录里跑。"""

    argv: list[str]
    cwd: Path
    source: str

    @property
    def display(self) -> str:
        return " ".join(self.argv)


def detect_dev_command(config: CakeUIConfig) -> DevCommand | None:
    """找出这个项目该怎么启动前端开发服务器。

    ``[tool.cakeui] dev_command`` 优先；否则用 ``web/package.json`` 里的
    ``dev`` 脚本，效果等同于 ``npm run dev``。
    """
    if config.dev_command:
        return DevCommand(shlex.split(config.dev_command), config.root, "config")
    return detect_package_script(config, "dev")


def detect_package_script(config: CakeUIConfig, script: str) -> DevCommand | None:
    """读取 ``web/package.json`` 里某个脚本对应的命令（``dev`` / ``build`` 共用）。"""
    web = config.web_path
    if web is None:
        return None

    package_json = web / "package.json"
    if not package_json.is_file():
        return None

    try:
        manifest = json.loads(package_json.read_text("utf-8"))
    except (OSError, ValueError):
        return None

    scripts = manifest.get("scripts")
    if not isinstance(scripts, dict) or not scripts.get(script):
        return None

    # 配置里记过包管理器就用它，否则按 lockfile / 当前 shell 推断。
    manager = packages.get(config.package_manager) if config.package_manager else None
    manager = manager or packages.detect(web, config.root)
    return DevCommand(manager.run_argv(script), web, "package.json")


def refresh_bridge_module(config: CakeUIConfig) -> list[Path]:
    """把生成的 ESM 桥接重写进打包器的源码目录。

    打包器模板是从源码目录 ``import "./cakeui.js"`` 的，所以运行时一升级，
    这份拷贝就得跟着刷新。
    """
    web = config.web_path
    if web is None:
        return []
    source_dir = web / "src"
    if not source_dir.is_dir():
        return []
    return ensure_bridge_module(source_dir)


class DevServer:
    """一个被监管的开发服务器进程，stdout 会被盯着找 URL。

    Vite 只有绑定端口之后才会打印地址，而且可能挑一个跟配置不同的端口，所以
    地址只能从输出里读，不能靠猜。
    """

    def __init__(self, command: DevCommand, *, echo: bool = True) -> None:
        self.command = command
        self.echo = echo
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._lines: list[str] = []
        self._url: str | None = None
        self._lock = threading.Lock()
        self._stopped = False

    # -- 生命周期 --------------------------------------------------------
    def start(self) -> None:
        executable = self.command.argv[0]
        if shutil.which(executable) is None:
            raise DevServerError(
                f"PATH 上找不到 {executable!r}。",
                details={
                    "command": self.command.display,
                    "hint": "请安装 Node.js，或设置 [tool.cakeui] dev_command。",
                },
            )

        try:
            self._process = subprocess.Popen(
                self.command.argv,
                cwd=self.command.cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                **_process_group_kwargs(),
            )
        except OSError as exc:
            raise DevServerError(
                f"无法启动 {self.command.display!r}：{exc}",
                details={"cwd": str(self.command.cwd)},
            ) from exc

        self._thread = threading.Thread(target=self._pump, name="cakeui-devserver", daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        """在后台线程里逐行读输出，顺便抓第一个本地地址。"""
        stream: IO[str] | None = self._process.stdout if self._process else None
        if stream is None:  # pragma: no cover - 防御性分支
            return
        for raw in stream:
            line = _ANSI.sub("", raw.rstrip("\r\n"))
            with self._lock:
                self._lines.append(line)
                if self._url is None:
                    found = _find_url(line)
                    if found:
                        self._url = found
            if self.echo and line.strip():
                print(f"  {line}", flush=True)

    # -- 查询 ------------------------------------------------------------
    @property
    def url(self) -> str | None:
        with self._lock:
            return self._url

    @property
    def output(self) -> str:
        with self._lock:
            return "\n".join(self._lines)

    def wait_for_url(self, timeout: float = 90.0, fallback: str | None = None) -> str:
        """阻塞到服务器打印出地址；进程提前死掉就带着输出报错。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.url:
                return self.url
            process = self._process
            if process is not None and process.poll() is not None and not self._thread_alive():
                return self._failure(fallback)
            time.sleep(0.05)
        if fallback:
            return fallback
        raise DevServerError(
            f"开发服务器 {timeout:.0f} 秒内没有打印出 URL。",
            details={"command": self.command.display, "output": self.output[-1500:]},
        )

    def _thread_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _failure(self, fallback: str | None) -> str:
        # 进程已经死了，但如果之前抓到过地址，就还能继续用。
        if fallback and self.url:
            return self.url
        raise DevServerError(
            f"开发服务器在就绪前就退出了（退出码 "
            f"{self._process.returncode if self._process else 'unknown'}）。",
            details={
                "command": self.command.display,
                "cwd": str(self.command.cwd),
                "output": self.output[-1500:] or "(no output)",
                "hint": "手动跑一遍这条命令可以看到完整错误。",
            },
        )

    # -- 收尾 ------------------------------------------------------------
    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        process = self._process
        if process is None or process.poll() is not None:
            return

        _terminate_tree(process)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - 子进程不响应
            process.kill()
            process.wait(timeout=5)

    def __enter__(self) -> DevServer:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


def _find_url(line: str) -> str | None:
    """优先取 Vite 在 ``Local:`` 下打印的环回地址。"""
    for match in _URL.finditer(line):
        url = match.group(0).rstrip(".,")
        host = url.split("://", 1)[-1]
        if host.startswith(("localhost", "127.0.0.1", "0.0.0.0", "[::1]")):
            return url
    return None


def _process_group_kwargs() -> dict[str, object]:
    """让开发服务器（及其派生进程）待在自己的进程组里。

    否则 Ctrl-C 会同时打到开发服务器和 Python 窗口，开发服务器自己的子进程
    还可能变成孤儿进程继续跑。
    """
    if os.name == "nt":  # pragma: no cover - Windows
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _terminate_tree(process: subprocess.Popen[str]) -> None:
    """整个进程组一起终止，而不是只杀父进程。"""
    if os.name == "nt":  # pragma: no cover - Windows
        process.terminate()
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):  # pragma: no cover - 已经没了
        process.terminate()
