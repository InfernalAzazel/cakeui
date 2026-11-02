"""``cakeui build``：先构建前端，再用 Nuitka 把整个应用打成可执行文件。

分两步，和 ``cakeui dev`` 对称：

1. 跑 ``web/package.json`` 里的 ``build`` 脚本，产出 ``web/dist``；
2. 调 Nuitka，把 ``web/dist`` 和 ``pyproject.toml`` 一起塞进产物目录。

第 2 步的关键是"打包后应用怎么找到自己的资源"。实测（Nuitka 4.3）``standalone``、
``onefile`` 和 macOS ``.app`` 三种产物里 ``__file__`` 都落在产物目录内部，所以
``resource_root()`` 只要取包目录的父目录即可，见
:func:`cakeui.resources._nuitka_root`。``pyproject.toml`` 必须随包发布，否则
运行时 ``App.from_config()`` 找不到配置。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

from cakeui.config import CakeUIConfig
from cakeui.errors import CakeUIError

from .devserver import detect_package_script

# pywebview 不需要任何 --include-package / --include-package-data：Nuitka 4 自带
# ``pywebview`` 插件挑选当前平台的 ``webview.platforms.*``，内置包配置还会带上
# ``webview/js`` 与 ``webview/lib``（Windows 的 WebView2 也在里面）。自己再写
# ``--include-package=webview`` 反而会和插件的决策冲突，直接 FATAL：
#   Conflict between user and plugin decision for module 'webview.platforms.android'

# pywebview 的 cocoa 后端在 import 时依赖 pyobjc；这些都是运行时才会加载的。
DARWIN_INCLUDE = ("objc", "AppKit", "Foundation", "WebKit", "PyObjCTools")
# Windows 的 winforms 后端走 pythonnet。
WINDOWS_INCLUDE = ("clr",)

# cakeui 自己也会从包内读文件（_bridge.js / _bridge.mjs / _bridge.d.ts），
# 它们是包数据而不是模块，Nuitka 不会自动带上。漏了的话打包后的应用能启动，
# 但一建窗口就报 BridgeError: 打包好的 JS 桥接文件缺失。
RUNTIME_PACKAGE_DATA = ("--include-package-data=cakeui",)

_ARTIFACT_SUFFIXES = (".bin", ".exe")

Executor = Callable[[list[str], Path], int]


class BuildError(CakeUIError):
    """打包过程失败。"""

    code = "build_error"


@dataclass(frozen=True)
class BuildPlan:
    """一次打包要做的事：跑哪些命令、在哪个目录、产物在哪。"""

    mode: str
    cwd: Path
    output_dir: Path
    entry: Path
    web_assets: Path
    nuitka_argv: list[str]
    web_argv: list[str] | None = None
    web_cwd: Path | None = None


@dataclass(frozen=True)
class BuildResult:
    """打包结果。"""

    executable: Path
    output_dir: Path


def plan_build(
    config: CakeUIConfig,
    *,
    mode: str | None = None,
    output_dir: str | Path | None = None,
    build_web: bool = True,
) -> BuildPlan:
    """规划一次打包，不执行任何外部命令。

    独立成纯函数是为了能直接断言命令行：打包参数错了很难从失败日志里看出来。
    """
    selected_mode = mode or config.build.mode
    if selected_mode not in ("standalone", "onefile"):
        raise BuildError(
            f"未知的打包模式 {selected_mode!r}。",
            details={"available": ["standalone", "onefile"]},
        )

    # 相对路径一律相对项目根：Nuitka 在 config.root 下执行，这里提前对齐，
    # 免得从子目录调用 `cakeui build` 时"命令行里的目录"和"找产物的目录"不一致。
    out_dir = Path(output_dir).expanduser() if output_dir else Path(config.build.output_dir)
    if not out_dir.is_absolute():
        out_dir = config.root / out_dir
    web_assets = _web_assets(config)

    web = detect_package_script(config, "build") if build_web else None
    return BuildPlan(
        mode=selected_mode,
        cwd=config.root,
        output_dir=out_dir.resolve(),
        entry=config.entry_path,
        web_assets=web_assets,
        nuitka_argv=_nuitka_argv(config, selected_mode, out_dir, web_assets),
        web_argv=web.argv if web else None,
        web_cwd=web.cwd if web else None,
    )


def run_build(plan: BuildPlan, *, executor: Executor | None = None) -> BuildResult:
    """执行计划；``executor`` 可注入，测试因此不需要真的装 Nuitka。"""
    run = executor or _run

    if executor is None and find_spec("nuitka") is None:
        raise BuildError(
            "当前解释器里没有安装 Nuitka。",
            details={
                "interpreter": sys.executable,
                "hint": "pip install nuitka，或者装 cakeui-cli[build]。",
            },
        )

    if plan.web_argv and plan.web_cwd:
        if run(plan.web_argv, plan.web_cwd) != 0:
            raise BuildError(
                f"前端构建失败：{' '.join(plan.web_argv)}",
                details={"cwd": str(plan.web_cwd)},
            )
        if not (plan.web_assets / "index.html").is_file():
            raise BuildError(
                f"前端构建没有产出 {plan.web_assets / 'index.html'}。",
                details={"hint": "检查 [tool.cakeui] web_dist 和前端 build 脚本的输出目录。"},
            )

    if run(plan.nuitka_argv, plan.cwd) != 0:
        details: dict[str, object] = {
            "command": " ".join(plan.nuitka_argv),
            "cwd": str(plan.cwd),
        }
        if sys.platform == "darwin":
            details["hint"] = "macOS 上打包需要 Nuitka 4.0+（pyobjc 必须跑在 .app 里）。"
        raise BuildError("Nuitka 打包失败。", details=details)

    executable = find_executable(plan.output_dir, plan.entry.stem, plan.mode)
    if executable is None:
        raise BuildError(
            f"Nuitka 报告成功，但 {plan.output_dir} 里找不到可执行文件。",
            details={"hint": "检查 [tool.cakeui.build] extra_args 是否改了输出位置。"},
        )
    return BuildResult(executable=executable, output_dir=plan.output_dir)


def find_executable(output_dir: Path, stem: str, mode: str) -> Path | None:
    """在产物目录里找可执行文件。

    名字由 Nuitka 决定：macOS 普通产物多一个 ``.bin`` 后缀、``.app`` 里的
    二进制没有后缀，Windows 则是 ``.exe``。
    """
    if not output_dir.is_dir():
        return None

    # macOS 的 .app bundle 优先：standalone 和 onefile 两种模式都会产出它。
    candidates = [output_dir / f"{stem}.app" / "Contents" / "MacOS" / stem]
    candidates += [
        output_dir / stem,
        *(output_dir / f"{stem}{suffix}" for suffix in _ARTIFACT_SUFFIXES),
    ]
    if mode == "standalone":
        dist = output_dir / f"{stem}.dist"
        candidates += [dist / stem, *(dist / f"{stem}{suffix}" for suffix in _ARTIFACT_SUFFIXES)]
    return next((path for path in candidates if path.is_file()), None)


def _web_assets(config: CakeUIConfig) -> Path:
    """要打进包里的前端目录：有构建产物就用产物，否则用源码目录。"""
    for directory in config.web_candidates:
        if (directory / "index.html").is_file():
            return directory
    raise BuildError(
        "找不到可以打包的 index.html。",
        details={
            "searched": [str(directory) for directory in config.web_candidates] or "(none)",
            "hint": "先跑一次前端构建，或设置 [tool.cakeui] web_dist。",
        },
    )


def _nuitka_argv(config: CakeUIConfig, mode: str, out_dir: Path, web_assets: Path) -> list[str]:
    """拼出完整的 Nuitka 命令行。

    所有相对路径都以 ``config.root`` 为基准，:func:`run_build` 也在那里执行，
    这样用户在 ``[tool.cakeui.build]`` 里写相对路径时行为可预期。
    """
    root = config.root.resolve()
    web_relative = _relative(web_assets, root)
    icon = _require_icon(config)

    argv = [
        sys.executable,
        "-m",
        "nuitka",
        *_mode_args(mode),
        f"--output-dir={out_dir}",
        # 非交互：不加这个，Nuitka 会停下来问要不要下载 ccache / depends。
        "--assume-yes-for-downloads",
        # 前端资源按原相对路径落进产物目录，运行时 web_candidates 才找得到。
        f"--include-data-dir={web_relative}={web_relative}",
        # 运行时 App.from_config() 依赖它，没有它打包后的应用启动就失败。
        "--include-data-files=pyproject.toml=pyproject.toml",
        *RUNTIME_PACKAGE_DATA,
        *_icon_data_args(config, icon),
    ]
    argv += [f"--include-package={name}" for name in config.build.include_packages]
    argv += [f"--include-data-dir={_data_dir_spec(item)}" for item in config.build.include_data_dir]
    argv += _platform_args(config, icon)
    argv += config.build.extra_args
    # 入口放最后，和手敲 nuitka 命令的习惯一致。
    argv.append(config.entry)
    return argv


def _mode_args(mode: str) -> list[str]:
    """选择 Nuitka 的编译模式。

    macOS 上必须走 app bundle：pyobjc 的 ``AppKit`` / ``Foundation`` 只能在
    应用环境里工作，用 ``--standalone`` 会被 Nuitka 直接拒绝（FATAL）。
    ``app-dist`` / ``app`` 正是"macOS 打 .app，其他平台分别等同 standalone /
    onefile"。非 macOS 用传统开关，兼容更老的 Nuitka。
    """
    standalone = mode == "standalone"
    if sys.platform == "darwin":
        return ["--mode=app-dist" if standalone else "--mode=app"]
    return ["--standalone" if standalone else "--onefile"]


def _platform_args(config: CakeUIConfig, icon: Path | None) -> list[str]:
    """平台相关的开关：动态导入的包、图标、控制台窗口。"""
    argv: list[str] = []

    if sys.platform == "darwin":
        argv += [f"--include-package={name}" for name in DARWIN_INCLUDE]
        # macOS 现在总是打 .app bundle，所以图标可以正常挂上去。
        if icon is not None:
            argv.append(f"--macos-app-icon={icon}")
    elif sys.platform == "win32":
        argv += [f"--include-package={name}" for name in WINDOWS_INCLUDE]
        if not config.build.console:
            # 桌面应用默认不该弹出一个黑色控制台窗口。
            argv.append("--windows-disable-console")
        if icon is not None:
            argv.append(f"--windows-icon-from-ico={icon}")
    elif icon is not None:
        argv.append(f"--linux-icon={icon}")

    return argv


def _require_icon(config: CakeUIConfig) -> Path | None:
    """解析出这次打包要用的图标文件。

    配置了 ``icon`` 却找不到文件时在这里就失败：Nuitka 对缺失图标的报错很晚，
    而且不说是哪个路径，排查起来比直接提示候选路径费劲得多。
    """
    if not config.icon:
        return None

    found = config.resolve_icon()
    if found is None:
        raise BuildError(
            f"找不到图标文件：{config.icon}",
            details={
                "searched": [str(path) for path in config.icon_candidates()],
                "hint": "把图标放进项目里，或者删掉 [tool.cakeui] 的 icon。",
            },
        )
    return found


def _icon_data_args(config: CakeUIConfig, icon: Path | None) -> list[str]:
    """把图标文件原样放进产物。

    ``--macos-app-icon`` / ``--windows-icon-from-ico`` 只是让 Nuitka 把它嵌进
    bundle 和 exe；运行时 pywebview 要自己读这个文件（Linux 和开发模式都是），
    所以同一份文件还得按原来的相对路径落在产物目录里。
    """
    if icon is None:
        return []

    root = config.root.resolve()
    specs: list[str] = []
    seen: set[str] = set()
    # 顺序固定：先解析出来的那个，再补同名的其他格式（有就一起带上）。
    for path in [icon, *config.icon_candidates()]:
        if not path.is_file():
            continue
        relative = _relative(path, root)
        if Path(relative).is_absolute():
            continue  # 项目外的图标只能嵌进 bundle，运行时按绝对路径找不到
        if relative in seen:
            continue
        seen.add(relative)
        specs.append(f"--include-data-files={relative}={relative}")
    return specs


def _data_dir_spec(item: str) -> str:
    """``assets`` 和 ``assets=assets`` 都接受。"""
    return item if "=" in item else f"{item}={item}"


def _relative(path: Path, root: Path) -> str:
    """转成相对项目根的 POSIX 路径；做不到就退回绝对路径。"""
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _run(argv: list[str], cwd: Path) -> int:
    """跑一条外部命令，输出直接进终端（构建过程需要看得见）。"""
    executable = argv[0]
    # 用当前解释器跑 nuitka 时不需要查 PATH；前端命令（npm/pnpm…）必须存在。
    if executable != sys.executable and shutil.which(executable) is None:
        raise BuildError(
            f"PATH 上找不到 {executable!r}。",
            details={"command": " ".join(argv), "hint": "先安装前端依赖（见项目 README）。"},
        )

    try:
        return subprocess.run(argv, cwd=cwd).returncode
    except OSError as exc:
        raise BuildError(
            f"无法执行 {executable!r}：{exc}", details={"command": " ".join(argv)}
        ) from exc
