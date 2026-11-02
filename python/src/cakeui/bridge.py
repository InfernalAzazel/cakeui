"""把 JS 桥接文件放进用户项目里。

包内自带两份构建产物（由 ``js/`` 目录打包生成）：

``_bridge.js``
    IIFE 形式，设置 ``window.cakeui``。给没有构建步骤、直接加载本地
    ``index.html`` 的项目用。

``_bridge.mjs`` + ``_bridge.d.ts``
    给打包器用的 ESM 模块和类型声明，写进前端源码目录后
    ``import { invoke } from "./cakeui.js"`` 就能直接跑，不用先发 npm。
"""

from __future__ import annotations

from pathlib import Path

from .errors import BridgeError

BRIDGE_FILENAME = "cakeui.js"
BRIDGE_TYPES_FILENAME = "cakeui.d.ts"

# 包内的静态资源目录，和本文件同级。
_DIR = Path(__file__).resolve().parent
_REGENERATE_HINT = "在 js/ 目录里执行 `npm install && npm run build` 重新生成。"


def _read_asset(filename: str) -> str:
    """读包内的构建产物；缺了就报一个能指导操作的错。"""
    path = _DIR / filename
    try:
        return path.read_text("utf-8")
    except OSError as exc:
        raise BridgeError(
            f"打包好的 JS 桥接文件缺失：{filename}",
            details={"expected": str(path), "hint": _REGENERATE_HINT},
        ) from exc


def bridge_source() -> str:
    """IIFE 版桥接源码（会定义 ``window.cakeui``）。"""
    return _read_asset("_bridge.js")


def bridge_module_source() -> str:
    """ESM 版桥接源码（导出 ``invoke`` / ``listen`` / ``emit`` 等）。"""
    return _read_asset("_bridge.mjs")


def bridge_types_source() -> str:
    """配套的 ``.d.ts``，让生成的 ``cakeui.js`` 有完整类型。"""
    return _read_asset("_bridge.d.ts")


def _write_if_changed(target: Path, source: str) -> Path:
    """内容没变就不动文件，避免每次启动都污染版本控制和构建缓存。"""
    if target.is_file():
        try:
            if target.read_text("utf-8") == source:
                return target
        except OSError:
            pass  # 读不了就当作需要重写

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, "utf-8")
    except OSError as exc:
        raise BridgeError(
            f"无法写入 JS 桥接文件：{target}",
            details={"hint": "本地运行时，前端目录必须可写。"},
        ) from exc
    return target


def ensure_bridge_file(directory: str | Path) -> Path:
    """在本地 ``index.html`` 旁边写出 ``cakeui.js``，供 ``<script>`` 直接加载。

    必须是真实文件而不是注入脚本：pywebview 没有"文档开始前"的注入钩子，
    否则页面自己的脚本会先于桥接执行。
    """
    return _write_if_changed(Path(directory) / BRIDGE_FILENAME, bridge_source())


def ensure_bridge_module(directory: str | Path) -> list[Path]:
    """把 ESM 桥接和类型声明写进打包器的源码目录。

    两个文件都是生成的：``cakeui.js`` 是项目里 import 的模块，
    ``cakeui.d.ts`` 则是 TypeScript 解析 ``./cakeui.js`` 时用到的声明。
    """
    target_dir = Path(directory)
    return [
        _write_if_changed(target_dir / BRIDGE_FILENAME, bridge_module_source()),
        _write_if_changed(target_dir / BRIDGE_TYPES_FILENAME, bridge_types_source()),
    ]
