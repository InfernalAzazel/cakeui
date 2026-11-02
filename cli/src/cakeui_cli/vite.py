"""用 Vite 官方脚手架生成前端，再把 CakeUI 合并进去。

交给 ``npm create vite`` 来做，框架代码就真的是上游的：Vue 项目就是 Vite 今天
发布的 Vue 模板，而不是我们维护的副本。CakeUI 只添加自己负责的部分（桥接文件、
类型声明、启动模块），并在入口文件里接一行 import。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from cakeui.errors import CakeUIError

from . import packages
from .packages import PackageManager

# 前端所在的目录名，本仓库和生成出来的项目都叫这个。
WEB_DIR = "web"

# index.html 里所有带 src 的 <script>，用来找 Vite 的入口模块。
_SCRIPT = re.compile(r"""<script[^>]*\bsrc=["']([^"']+)["']""", re.I)

BOOT_MARKER = "// cakeui:bridge"

# CakeUI 生成的文件统一放在前端源码的这个子目录里：桥接模块、类型声明和启动
# 模块都归它们自己，不和项目自己的代码混在 src/ 根上。
BRIDGE_DIR = Path("lib") / "cakeui"

# 启动模块相对入口文件的路径，用来生成 import 语句。
BOOT_SPECIFIER = (BRIDGE_DIR / "cakeui-boot").as_posix()


class ViteError(CakeUIError):
    """Vite 跑不起来，或者生成出来的项目不符合预期。"""

    code = "vite_error"


def create_vite(
    destination: Path,
    template: str,
    *,
    manager: PackageManager | None = None,
    timeout: float = 600.0,
) -> Path:
    """把 ``template`` 脚手架到 ``destination``（此时它还不应该存在）。

    ``manager`` 决定用哪个 ``create`` 来跑 Vite（默认 npm；pnpm / yarn / bun
    用法完全一样，只是会留下各自的 lockfile）。

    Vite 先在临时目录里运行，再把结果合并到目标位置：这样 ``--force`` 能正常
    工作，也绝不会撞上 Vite 自己的"目录非空"交互提示，因为这里是纯非交互的。
    """
    manager = manager or packages.get(packages.DEFAULT)
    packages.ensure_available(manager)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cakeui-vite-", dir=destination.parent) as workdir:
        scratch = Path(workdir)
        env = {**os.environ, "npm_config_yes": "true"}
        command = manager.create_argv(WEB_DIR, template)
        try:
            completed = subprocess.run(
                command,
                cwd=scratch,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ViteError(
                f"无法运行 `{manager.name} create`：{exc}",
                details={"command": " ".join(command)},
            ) from exc

        produced = scratch / WEB_DIR
        if completed.returncode != 0 or not produced.is_dir():
            raise ViteError(
                f"`{manager.name} create vite` 无法生成模板 {template!r}。",
                details={
                    "command": " ".join(command),
                    "output": _tail(completed.stdout + completed.stderr),
                    "hint": f"请确认 {template!r} 是一个合法的 Vite 模板名。",
                },
            )

        shutil.copytree(produced, destination, dirs_exist_ok=True)

    return destination


def find_entry(web: Path) -> Path | None:
    """找出 Vite 的 ``index.html`` 实际启动的那个模块。"""
    index = web / "index.html"
    if not index.is_file():
        return None
    try:
        html = index.read_text("utf-8")
    except OSError:
        return None

    for match in _SCRIPT.finditer(html):
        source = match.group(1).strip()
        # 跳过 CDN 之类的外部脚本，只认项目里的模块文件。
        if "://" in source or source.startswith("//"):
            continue
        candidate = web / source.lstrip("/")
        if candidate.is_file():
            return candidate
    return None


def attach_boot(entry: Path) -> bool:
    """在入口文件末尾追加对 CakeUI 启动模块的 import；改了内容则返回 True。

    追加一条副作用 import 是 CakeUI 对生成代码做的唯一改动：文件原有内容不会被
    重写，所以模板怎么变都不会冲突。
    """
    try:
        original = entry.read_text("utf-8")
    except OSError as exc:
        raise ViteError(f"无法读取 {entry}：{exc}") from exc

    if BOOT_MARKER in original:
        return False

    addition = (
        f"\n{BOOT_MARKER}: 由 CakeUI 添加；删掉这一行即解除与 CakeUI 的绑定。\n"
        f'import "./{BOOT_SPECIFIER}";\n'
    )
    entry.write_text(original.rstrip("\n") + "\n" + addition, "utf-8")
    return True


def _tail(text: str, limit: int = 2000) -> str:
    """错误信息里只带输出的最后一段，前面通常是进度条噪音。"""
    stripped = text.strip()
    return stripped[-limit:] if stripped else "(no output)"
