"""在开发环境和 Nuitka / PyInstaller 打包后定位资源文件。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_RESOURCE_ROOT = "CAKEUI_RESOURCE_ROOT"

# cakeui 包自己的目录。打包后它就在应用产物目录里面（<dist>/cakeui/），
# 所以父目录就是应用根目录，见 _nuitka_root。
_PACKAGE_DIR = Path(__file__).resolve().parent

# 由 set_resource_root 写入的显式覆盖值，优先级最高。
_override: Path | None = None


def set_resource_root(path: str | os.PathLike[str] | None) -> None:
    """强制指定 :func:`resource_path` 的解析基目录。

    传 ``None`` 表示清除覆盖。测试和"把资源放在打包目录之外"的应用用它。
    """
    global _override
    _override = None if path is None else Path(path).expanduser().resolve()


def _nuitka_root() -> Path | None:
    """Nuitka 会给每个编译过的模块注入 ``__compiled__``。

    打包后数据和代码一起放在产物目录里：

    - ``standalone``：``main.dist/``，因此 ``main.dist/cakeui/resources.py``；
    - ``onefile``：解压出来的临时目录，布局同样是 ``<临时目录>/cakeui/...``。

    两种情况都满足"包目录的父目录 = 应用根目录"，所以不用分别处理。
    注意不能用 ``__compiled__.containing_dir``：它指向 ``--output-dir``，
    而不是真正运行的产物目录。
    """
    if globals().get("__compiled__") is None:
        return None
    return _PACKAGE_DIR.parent


def _frozen_root() -> Path | None:
    """PyInstaller 打包后会设置 ``sys.frozen``。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        return Path(meipass).resolve() if meipass else Path(sys.executable).resolve().parent
    return None


def _development_root() -> Path:
    """源码运行时对项目根目录的最佳猜测：启动脚本所在目录。"""
    return program_dir() or Path.cwd().resolve()


def program_dir() -> Path | None:
    """启动脚本所在目录；``sys.argv[0]`` 不是脚本时返回 ``None``。

    ``python main.py`` 时是脚本目录，这样从任何 cwd 启动都能找到项目文件。
    """
    argv0 = sys.argv[0] if sys.argv else ""
    if not argv0:
        return None
    candidate = Path(argv0)
    if candidate.suffix == ".py" and candidate.is_file():
        return candidate.resolve().parent
    return None


def resource_root() -> Path:
    """返回资源解析所用的根目录。"""
    if _override is not None:
        return _override

    env = os.environ.get(ENV_RESOURCE_ROOT)
    if env:
        return Path(env).expanduser().resolve()

    # 打包环境优先于开发环境。
    for resolver in (_nuitka_root, _frozen_root):
        root = resolver()
        if root is not None:
            return root

    return _development_root()


def resource_path(relative: str | os.PathLike[str]) -> Path:
    """解析一个随应用发布的文件，例如 ``resource_path("assets/logo.png")``。

    返回绝对路径；传入绝对路径时原样返回，因此可以放心用在用户提供的路径上。
    """
    candidate = Path(relative).expanduser()
    if candidate.is_absolute():
        return candidate
    return (resource_root() / candidate).resolve()
