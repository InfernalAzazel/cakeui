"""藏在 pywebview ``js_api`` 后面的 JSON 信封路由。

前端每次调用都是一条 ``{t: "invoke" | "emit", ...}`` 消息，这里返回
``{ok: true, data}`` 或 ``{ok: false, error}``。异常绝不外抛——跨越 pywebview
的线程边界之后没人能接住它。
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ._json import dumps
from .commands import CommandSpec, EventSpec, build_command_spec
from .errors import BadRequestError, CakeUIError, CommandNotFoundError

if TYPE_CHECKING:  # pragma: no cover
    from .window import Window


def ok(data: Any = None) -> str:
    return dumps({"ok": True, "data": data})


def fail(error: CakeUIError) -> str:
    return dumps({"ok": False, "error": error.to_dict()})


class Router:
    """命令与事件处理函数的注册表，外加消息分发。"""

    def __init__(self, *, debug: bool = False) -> None:
        self.debug = debug
        self._commands: dict[str, CommandSpec] = {}
        self._events: dict[str, list[EventSpec]] = {}

    # -- 注册 ------------------------------------------------------------
    def add_command(
        self,
        func: Callable[..., Any],
        *,
        name: str | None = None,
        validate_return: bool = True,
    ) -> CommandSpec:
        return self.add_spec(build_command_spec(func, name=name, validate_return=validate_return))

    def add_spec(self, spec: CommandSpec) -> CommandSpec:
        """登记一个已经建好的 spec（模块级 ``@command`` 用的是这条路径）。"""
        if spec.name in self._commands:
            raise ValueError(f"命令 {spec.name!r} 已经注册过了。")
        self._commands[spec.name] = spec
        return spec

    def add_event_handler(self, event: str, func: Callable[..., Any]) -> EventSpec:
        if not event or not isinstance(event, str):
            raise TypeError("事件名必须是非空字符串。")
        spec = EventSpec(event, func)
        self._events.setdefault(event, []).append(spec)
        return spec

    @property
    def command_names(self) -> list[str]:
        return sorted(self._commands)

    def get(self, name: str) -> CommandSpec | None:
        return self._commands.get(name)

    # -- 分发 ------------------------------------------------------------
    def handle(self, raw: str, window: Window | None = None) -> str:
        """JS 桥接唯一的入口，永远返回一个 JSON 信封。"""
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return fail(BadRequestError("桥接消息不是合法 JSON。"))

        if not isinstance(payload, dict):
            return fail(BadRequestError("桥接消息必须是 JSON 对象。"))

        kind = payload.get("t")
        try:
            if kind == "invoke":
                return self._handle_invoke(payload, window)
            if kind == "emit":
                return self._handle_emit(payload)
            raise BadRequestError(f"未知的桥接消息类型：{kind!r}。")
        except CakeUIError as exc:
            return fail(exc)
        except Exception as exc:  # 兜底：泄漏到 pywebview 里就没人处理了
            return fail(self._unexpected(exc))

    def _handle_invoke(self, payload: dict[str, Any], window: Window | None) -> str:
        cmd = payload.get("cmd")
        if not isinstance(cmd, str) or not cmd:
            raise BadRequestError("invoke 消息需要非空的 'cmd' 字符串。")

        spec = self._commands.get(cmd)
        if spec is None:
            raise CommandNotFoundError(
                f"没有名为 {cmd!r} 的已注册命令。",
                details={"available": self.command_names},
            )

        args = payload.get("args")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise BadRequestError(f"命令 {cmd!r} 的参数必须是 JSON 对象。")

        return ok(spec.call(args, window))

    def _handle_emit(self, payload: dict[str, Any]) -> str:
        event = payload.get("event")
        if not isinstance(event, str) or not event:
            raise BadRequestError("emit 消息需要非空的 'event' 字符串。")

        handlers = self._events.get(event, [])
        if not handlers:
            raise BadRequestError(
                f"事件 {event!r} 没有对应的 Python 处理函数。",
                details={"registered": sorted(self._events)},
            )

        # payload 先序列化一次，让每个处理函数都拿到干净的数据副本。
        raw_payload = dumps(payload.get("payload"))
        for handler in handlers:
            try:
                handler.call(raw_payload)
            except CakeUIError:
                raise
            except Exception as exc:
                raise CakeUIError(
                    f"事件 {event!r} 的处理函数抛出 {type(exc).__name__}：{exc}",
                    code="event_handler_error",
                ) from exc
        return ok(len(handlers))

    def _unexpected(self, exc: Exception) -> CakeUIError:
        # 只有 debug 模式才回传 traceback：生产环境不该把路径和源码带给前端。
        details: dict[str, Any] | None = None
        if self.debug:
            details = {"traceback": traceback.format_exc()}
        return CakeUIError(f"{type(exc).__name__}: {exc}", code="internal_error", details=details)
