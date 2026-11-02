"""可以安全回传给前端（JS 侧）的异常类型。

约定：``code`` 是稳定的机器可读标识，前端应当按它分支，而不是去解析
``message`` 文本（文本随时可能改、也随时可能被翻译）。
"""

from __future__ import annotations

from typing import Any


class CakeUIError(Exception):
    """所有 CakeUI 异常的基类。"""

    code = "error"

    def __init__(self, message: str, *, code: str | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        # 子类用类属性给出默认 code，调用方可以按需覆盖。
        if code is not None:
            self.code = code
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        """转成写进 JSON 信封的形状；``details`` 为空时干脆不带这个键。"""
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            payload["details"] = self.details
        return payload


class BadRequestError(CakeUIError):
    """桥接收到了无法解析、或结构不对的消息。"""

    code = "bad_request"


class CommandNotFoundError(CakeUIError):
    """``invoke`` 指定的命令没有注册过。"""

    code = "command_not_found"


class CommandValidationError(CakeUIError):
    """参数或返回值没通过 Pydantic 校验。"""

    code = "validation_error"


class ConfigError(CakeUIError):
    """``pyproject.toml`` 缺失或内容不合法。"""

    code = "config_error"


class BridgeError(CakeUIError):
    """JS 桥接文件缺失，或无法投递到窗口。"""

    code = "bridge_error"


class WindowNotReadyError(CakeUIError):
    """窗口还没加载完，就要求它做事。"""

    code = "window_not_ready"
