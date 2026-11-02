"""``cakeui`` 命令的入口。"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import cakeui
from cakeui.config import load_config
from cakeui.errors import CakeUIError, ConfigError

from . import console, packages
from .build import plan_build, run_build
from .devserver import DevServer, detect_dev_command, refresh_bridge_module
from .packages import PackageManager
from .scaffold import DEFAULT_TEMPLATE, scaffold, template_names

DEV_URL_ENV = "CAKEUI_DEV_URL"
DEBUG_ENV = "CAKEUI_DEBUG"

PROG = "cakeui"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="创建和运行 CakeUI 桌面应用（Python 后端，Web 前端）。",
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {cakeui.__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    new = subparsers.add_parser("new", help="按模板创建一个新项目。")
    new.add_argument("name", help="项目名，例如 my-notes（小写，可以带连字符）。")
    new.add_argument(
        "--template",
        default=DEFAULT_TEMPLATE,
        metavar="NAME",
        help=(
            f"要脚手架的 Vite 模板（默认 {DEFAULT_TEMPLATE}）。"
            f"内置：{', '.join(template_names()) or 'none'}。"
            "其他合法的 Vite 模板名也可以直接用。"
        ),
    )
    new.add_argument(
        "--dir", default=None, metavar="PATH", help="创建到哪个目录（默认 ./<name>）。"
    )
    new.add_argument("--force", action="store_true", help="允许写入非空目录。")
    new.add_argument(
        "-p",
        "--package-manager",
        default=None,
        metavar="NAME",
        help=(
            "用来脚手架和安装的 JS 包管理器"
            f"（{', '.join(packages.names())}）。默认按 lockfile、启动它的 shell、"
            "最后 npm 的顺序推断。"
        ),
    )
    new.add_argument(
        "--no-install",
        action="store_true",
        help="生成文件后不执行 `uv sync` 和 JS 依赖安装。",
    )
    new.set_defaults(func=cmd_new)

    dev = subparsers.add_parser("dev", help="带着前端开发服务器运行应用。")
    dev.add_argument(
        "--url",
        default=None,
        metavar="URL",
        help="直接连一个已经跑着的开发服务器，而不是再起一个（例如 http://localhost:5173）。",
    )
    dev.add_argument(
        "--debug",
        action="store_true",
        help="打开 webview 调试面板，并输出更详细的桥接错误。",
    )
    dev.add_argument(
        "rest",
        nargs=argparse.REMAINDER,
        help="原样传给 Python 入口的额外参数（放在 `--` 之后）。",
    )
    dev.set_defaults(func=cmd_dev)

    info = subparsers.add_parser("info", help="打印解析后的项目配置。")
    info.set_defaults(func=cmd_info)

    build = subparsers.add_parser("build", help="构建前端并用 Nuitka 打包成可执行文件。")
    build.add_argument(
        "--mode",
        choices=["standalone", "onefile"],
        default=None,
        help="standalone 产出目录（启动快），onefile 产出单个文件；macOS 上两者都是 .app。",
    )
    build.add_argument(
        "--output-dir",
        default=None,
        metavar="PATH",
        help="产物输出目录（默认取 [tool.cakeui.build] output_dir）。",
    )
    build.add_argument(
        "--no-web",
        action="store_true",
        help="跳过前端构建，直接打包现有的 web/dist。",
    )
    build.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要执行的命令，不实际打包。",
    )
    build.set_defaults(func=cmd_build)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0

    try:
        return int(args.func(args) or 0)
    except CakeUIError as exc:  # 含 ScaffoldError 等全部子类
        console.error(exc.message)
        for line in _details_lines(exc):
            console.detail(line)
        return 1
    except KeyboardInterrupt:
        console.warn("已中断。")
        return 130


def cmd_new(args: argparse.Namespace) -> int:
    destination = Path(args.dir).expanduser() if args.dir else Path.cwd() / args.name
    destination = destination.resolve()

    manager = packages.get(args.package_manager) if args.package_manager else packages.detect()
    packages.ensure_available(manager)

    console.info(
        f"正在用 `{manager.name} create vite` 脚手架前端（{args.template}）→ {destination} …"
    )
    result = scaffold(
        args.name,
        destination,
        template=args.template,
        force=args.force,
        cakeui_requirement=f">={cakeui.__version__}",
        cakeui_source=_cakeui_local_source(),
        package_manager=manager,
    )

    console.success(f"已在 {destination} 创建 {args.name}")
    console.detail(f"template  {result.template}")
    console.detail(f"package   {manager.name}")
    console.detail(f"entry     {_display_path(result.entry)}")
    console.detail(f"bridge    {_display_path(result.bridge_files[0])}")

    python_ready = False
    web_ready = False
    if not args.no_install:
        python_ready = _run_install(["uv", "sync"], destination, "uv sync")
        web_ready = _install_web(result.web, manager)

    relative = _display_path(destination)
    steps = [f"cd {relative}"]
    if not python_ready:
        steps.append("uv sync")
    if not web_ready and (result.web / "package.json").is_file():
        steps.append(manager.install_hint("web"))
    steps.append(f"{PROG} dev")

    console.headline("接下来")
    console.bullet_list(steps)
    return 0


def _cakeui_local_source() -> Path | None:
    """如果运行时是从磁盘而不是 PyPI 安装的，找出它的 checkout 目录。"""
    location = getattr(cakeui, "__file__", None)
    if not location:
        return None

    for directory in Path(location).resolve().parents:
        candidate = directory / "pyproject.toml"
        if not candidate.is_file():
            continue
        try:
            data = tomllib.loads(candidate.read_text("utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if data.get("project", {}).get("name") == "cakeui":
            return directory

    # 从 wheel 装的：没有本地目录可以指向。
    return None


def _run_install(argv: list[str], cwd: Path, label: str) -> bool:
    """在 ``cwd`` 里跑一条安装命令；跑不了就返回 False，由调用方提示用户。"""
    if sys.stdin is not None and not sys.stdin.isatty():
        console.detail(f"不是终端，跳过 `{label}`。")
        return False

    executable = shutil.which(argv[0])
    if executable is None:
        console.detail(f"未找到 {argv[0]}，请手动安装依赖。")
        return False

    console.info(f"正在用 {argv[0]} 安装依赖 …")
    try:
        completed = subprocess.run([executable, *argv[1:]], cwd=cwd)
    except OSError as exc:
        console.detail(f"`{label}` 失败：{exc}")
        return False
    if completed.returncode != 0:
        console.detail(f"`{label}` 失败，请手动运行以查看错误。")
        return False
    return True


def _install_web(web: Path, manager: PackageManager) -> bool:
    """安装前端依赖；没有 package.json 或已经装过就直接算完成。"""
    if not (web / "package.json").is_file() or (web / "node_modules").is_dir():
        return True
    return _run_install(manager.install_argv(), web, f"{manager.name} install")


def cmd_dev(args: argparse.Namespace) -> int:
    config = load_config(Path.cwd())
    entry = config.entry_path
    if not entry.is_file():
        raise ConfigError(
            f"入口文件 {config.entry!r} 不存在。",
            details={"expected": str(entry)},
        )

    env = os.environ.copy()
    if args.debug:
        env[DEBUG_ENV] = "1"

    # `--url` 意味着"服务器已经在跑了"：绝不再起第二个。
    dev_command = None if args.url else detect_dev_command(config)
    server: DevServer | None = None
    try:
        if args.url:
            url = args.url
        elif dev_command is not None:
            refresh_bridge_module(config)
            server = DevServer(dev_command)
            console.info(f"Web: {dev_command.display}  (在 {_display_path(dev_command.cwd)})")
            server.start()
            url = server.wait_for_url(fallback=config.dev_url or os.environ.get(DEV_URL_ENV))
        else:
            url = config.dev_url or os.environ.get(DEV_URL_ENV)

        if url:
            env[DEV_URL_ENV] = url
            console.info(f"窗口: {url}")
        else:
            env.pop(DEV_URL_ENV, None)
            index = config.resolve_index_html()
            if index is not None:
                console.info(f"窗口: {index}")

        console.info(f"正在启动 {config.name} …")
        # argparse 的 REMAINDER 会把 `--` 本身也收进来，先滤掉。
        forwarded = [item for item in (args.rest or []) if item != "--"]
        command = [sys.executable, "-u", str(entry), *forwarded]
        try:
            return subprocess.run(command, cwd=config.root, env=env).returncode
        except OSError as exc:
            raise CakeUIError(f"无法启动 {entry}：{exc}") from exc
    finally:
        # 窗口拥有这个会话：窗口一关，开发服务器也跟着停。
        if server is not None:
            server.stop()


def cmd_build(args: argparse.Namespace) -> int:
    config = load_config(Path.cwd())
    plan = plan_build(
        config,
        mode=args.mode,
        output_dir=args.output_dir,
        build_web=not args.no_web,
    )

    console.headline(f"打包 {config.name}（{plan.mode}）")
    console.detail(f"root      {plan.cwd}")
    console.detail(f"entry     {plan.entry}")
    console.detail(f"web       {plan.web_assets}")
    console.detail(f"output    {plan.output_dir}")

    if plan.web_argv:
        console.info(f"前端构建：{' '.join(plan.web_argv)}")
    else:
        console.detail("没有 build 脚本，直接使用已有的前端产物。")

    console.info("Nuitka：")
    for line in plan.nuitka_argv[3:]:
        console.detail(line)

    if args.dry_run:
        console.warn("--dry-run：未执行任何命令。")
        return 0

    result = run_build(plan)
    console.success(f"已生成 {result.executable}")
    console.detail(f"运行 {_display_path(result.executable)}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    config = load_config(Path.cwd())
    index = config.resolve_index_html()

    console.headline(config.name)
    console.detail(f"root      {config.root}")
    console.detail(f"entry     {config.entry}  ->  {config.entry_path}")
    for field in ("web", "web_dist", "package_manager", "icon", "dev_url", "dev_command"):
        value = getattr(config, field)
        if value:
            console.detail(f"{field:<15} {value}")
    if config.icon:
        # 一个 icon 配置对应一整套文件，这里说清楚这台机器上实际会用哪一个。
        resolved = config.resolve_icon()
        console.detail(f"{'icon file':<15} {resolved if resolved else '(not found)'}")
    console.detail(f"index.html {'-> ' + str(index) if index else '(not found)'}")

    dev_command = detect_dev_command(config)
    if dev_command is not None:
        console.detail(f"dev       {dev_command.display}  ({dev_command.source})")

    console.detail(f"cakeui    {cakeui.__version__}")
    console.detail(f"python    {sys.version.split()[0]}")
    return 0


def _details_lines(exc: CakeUIError) -> list[str]:
    """把 ``details`` 拍平成几行给终端看，hint 永远排在最前面。"""
    details = exc.details
    if not details:
        return []

    if isinstance(details, dict):
        lines = []
        hint = details.get("hint")
        if isinstance(hint, str) and hint:
            lines.append(hint)
        lines += [f"{key}: {_render(value)}" for key, value in details.items() if key != "hint"]
        return lines
    if isinstance(details, (list, tuple)):
        return [_render(item) for item in details]
    return [str(details)]


def _render(value: object) -> str:
    """单个 detail 值的一行渲染。"""
    if isinstance(value, dict) and "message" in value:
        field = value.get("field", "")
        return f"{field}: {value['message']}" if field else str(value["message"])
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) or "(empty)"
    return str(value)


def _display_path(path: Path) -> str:
    """能相对当前目录显示就相对显示，否则用绝对路径。"""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
