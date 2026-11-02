"""CakeUI：用 Python 写后端、用 Web 技术写界面的桌面应用框架。

不需要 Rust 工具链，也不强制打包步骤。窗口、命令、事件都由 Python 侧管理，
前端通过 ``invoke`` / ``listen`` / ``emit`` 与之通信。
"""

from __future__ import annotations

from collections.abc import Callable
from importlib import metadata
from typing import Any

from .app import App
from .commands import build_command_spec
from .config import BuildConfig, CakeUIConfig, find_pyproject, load_config
from .errors import (
    BadRequestError,
    BridgeError,
    CakeUIError,
    CommandNotFoundError,
    CommandValidationError,
    ConfigError,
    WindowNotReadyError,
)
from .resources import resource_path, resource_root, set_resource_root
from .window import Window

# 这里是包对外的门面：上面的名字导入进来就是为了让用户 `from cakeui import ...`。
# 写 __all__ 有两个实在的用处：类型检查器靠它认出"再导出"（否则每个名字都报
# reportUnusedImport），同时它就是公开 API 的清单。
__all__ = [
    "App",
    "BadRequestError",
    "BridgeError",
    "BuildConfig",
    "CakeUIConfig",
    "CakeUIError",
    "CommandNotFoundError",
    "CommandValidationError",
    "ConfigError",
    "Window",
    "WindowNotReadyError",
    "__version__",
    "command",
    "find_pyproject",
    "load_config",
    "resource_path",
    "resource_root",
    "set_resource_root",
]

try:
    __version__ = metadata.version("cakeui")
except metadata.PackageNotFoundError:  # 从源码 checkout 直接运行时没有包元数据
    __version__ = "0.1.0"


def command(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    validate_return: bool = True,
) -> Any:
    """把函数标记为 CakeUI 命令。

    模块级写法的意义在于：命令可以分散在 ``main.py`` 之外的模块里，最后再统一
    收集进 app::

        from cakeui import App, command

        @command
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        app = App(commands=[greet])

    装饰时就立刻构建 spec，所以注解写错会在 import 阶段直接报出来。
    """

    def mark(target: Callable[..., Any]) -> Callable[..., Any]:
        target.__cakeui_spec__ = build_command_spec(  # type: ignore[attr-defined]
            target, name=name, validate_return=validate_return
        )
        return target

    return mark if func is None else mark(func)
