"""桥接层与命令路由共用的 JSON 工具。"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import enum
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def json_default(value: Any) -> Any:
    """把常见的 Python 对象转成 ``json.dumps`` 认识的形状。

    命令的返回值会直接穿过桥接层交给前端，所以这里覆盖的是「一个人写命令时
    很可能顺手返回」的那些类型：模型、dataclass、枚举、日期、Path、UUID……
    """
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, (Path, uuid.UUID)):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (set, frozenset)):
        return list(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    # 不认识的类型必须显式报错，否则会被静默写进日志或变成一个字符串。
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def dumps(value: Any) -> str:
    """紧凑序列化；``ensure_ascii=False`` 让中文在抓包时仍然可读。"""
    return json.dumps(value, default=json_default, ensure_ascii=False, separators=(",", ":"))


def js_string(value: str) -> str:
    """把一个 Python 字符串编码成 JS 字符串字面量。

    U+2028 / U+2029 在 JSON 字符串里合法，但在 JS 源码里历来非法，直接拼进
    ``evaluate_js`` 会让整段脚本语法错误，所以单独转义掉。
    """
    encoded = json.dumps(value, ensure_ascii=False)
    return encoded.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
