"""终端输出的小工具。

刻意不依赖任何库：CLI 只应该依赖运行时本身，为了一个转圈动画把 Rich 拖进来
不值得。
"""

from __future__ import annotations

import os
import sys

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"


def _supports_color(stream) -> bool:
    """遵循 NO_COLOR / FORCE_COLOR 约定，其余情况看是不是终端。"""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


def _paint(text: str, *codes: str, stream=sys.stdout) -> str:
    if not _supports_color(stream):
        return text
    return "".join(codes) + text + _RESET


def headline(text: str) -> None:
    print(_paint(text, _BOLD), flush=True)


def info(text: str) -> None:
    print(f"{_paint('›', _CYAN)} {text}", flush=True)


def detail(text: str) -> None:
    print(_paint(f"  {text}", _DIM), flush=True)


def success(text: str) -> None:
    print(f"{_paint('✓', _GREEN)} {text}", flush=True)


def warn(text: str) -> None:
    print(f"{_paint('!', _YELLOW)} {text}", file=sys.stderr, flush=True)


def error(text: str) -> None:
    print(f"{_paint('✗', _RED)} {text}", file=sys.stderr, flush=True)


def bullet_list(items: list[str]) -> None:
    for item in items:
        print(_paint(f"  • {item}", _DIM), flush=True)
