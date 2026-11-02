"""把带类型注解的 Python 函数变成受校验的桥接命令。"""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import types
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError, create_model

from .errors import CommandValidationError
from .window import Window

_MISSING = inspect.Parameter.empty


def _is_union(annotation: Any) -> bool:
    """``Union[A, B]`` 和 ``A | B`` 在运行期是两种不同对象，这里一起认。"""
    return get_origin(annotation) in (Union, types.UnionType)


def _is_window_annotation(annotation: Any) -> bool:
    """判断注解是否代表 ``Window``：``Window``、``"Window"``、``Window | None`` 都算。"""
    if annotation is Window or annotation == "Window":
        return True
    if _is_union(annotation):
        return any(_is_window_annotation(arg) for arg in get_args(annotation))
    return False


def _resolve_hints(func: Callable[..., Any], name: str) -> dict[str, Any]:
    """解析注解，失败时给一句能直接照做的提示。"""
    try:
        return get_type_hints(func)
    except Exception as exc:  # 前向引用会抛 NameError，怪注解会抛 TypeError
        raise TypeError(
            f"CakeUI 无法解析命令 {name!r} 的类型注解：{exc}。"
            "请把注解里用到的类型定义或导入在模块层级，保证声明命令的模块能解析到它。"
        ) from exc


def _field_from_parameter(param: inspect.Parameter, annotation: Any) -> tuple[Any, Any]:
    """把函数参数翻译成 Pydantic 的字段定义 ``(类型, 默认值)``。"""
    if param.default is _MISSING:
        return (annotation, ...)
    if param.default is None:
        # 这里必须用显式 Union 而不是 `annotation | None`：annotation 是运行期
        # 对象，并非所有 typing 构造都支持 `|` 运算符。
        return (Union[annotation, None], None)  # noqa: UP007
    return (annotation, param.default)


def build_command_spec(
    func: Callable[..., Any],
    *,
    name: str | None = None,
    validate_return: bool = True,
) -> CommandSpec:
    """构造（顺带校验）一个命令的桥接契约。"""
    if not callable(func):
        raise TypeError(f"@command 需要可调用对象，收到的是 {type(func).__name__}。")
    if inspect.isclass(func):
        raise TypeError("@command 不能用在类上。")

    command_name = name or getattr(func, "__name__", "")
    if not command_name or not command_name.replace("_", "").isalnum():
        raise TypeError(f"命令名 {command_name!r} 不合法：只能用字母、数字和下划线。")

    hints = _resolve_hints(func, command_name)
    signature = inspect.signature(func)

    fields: dict[str, tuple[Any, Any]] = {}
    takes_window = False
    window_param = "window"

    for param_name, param in signature.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            raise TypeError(
                f"命令 {command_name!r} 不能使用 *args / **kwargs（参数 {param_name!r}）；"
                "请改成逐个声明、带类型的参数。"
            )

        annotation = hints.get(param_name, param.annotation)
        if param_name == "window" or _is_window_annotation(annotation):
            if param.default is not _MISSING:
                raise TypeError(f"命令 {command_name!r}：注入的 window 参数不能有默认值。")
            if takes_window:
                raise TypeError(f"命令 {command_name!r} 重复声明了 window 参数。")
            takes_window = True
            window_param = param_name
            continue

        if annotation is _MISSING:
            raise TypeError(
                f"命令 {command_name!r} 的参数 {param_name!r} 缺少类型注解，"
                "CakeUI 需要它来校验入参。"
            )
        fields[param_name] = _field_from_parameter(param, annotation)

    # 即使没有参数也要建模型：这样 ``extra="forbid"`` 能让"参数名拼错"和
    # "参数类型不对"返回完全一致的错误形状。
    args_model = create_model(  # type: ignore[call-overload]
        f"{command_name}_Args",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )

    return_adapter: TypeAdapter[Any] | None = None
    if validate_return:
        return_annotation = hints.get("return", signature.return_annotation)
        if return_annotation is not _MISSING:
            try:
                return_adapter = TypeAdapter(return_annotation)
            except Exception as exc:
                raise TypeError(f"命令 {command_name!r} 的返回注解无法使用：{exc}") from exc

    return CommandSpec(
        name=command_name,
        func=func,
        args_model=args_model,
        return_adapter=return_adapter,
        takes_window=takes_window,
        window_param=window_param,
        is_async=inspect.iscoroutinefunction(func),
    )


def run_coroutine(coro: Any) -> Any:
    """在同步代码里跑协程，即使当前线程已经有一个事件循环。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # 当前线程已经有循环（例如 pywebview 自己起的），不能嵌套 asyncio.run，
    # 只能丢到另一个线程里跑，再把结果或异常带回来。
    result: dict[str, Any] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


@dataclass(frozen=True)
class CommandSpec:
    """路由层校验、调用一个命令所需要的全部信息。"""

    name: str
    func: Callable[..., Any]
    args_model: type[BaseModel]
    return_adapter: TypeAdapter[Any] | None
    takes_window: bool
    window_param: str
    is_async: bool

    def call(self, args: dict[str, Any], window: Window | None) -> Any:
        kwargs = self._validate_args(args)
        # window 由 CakeUI 注入，永远不从 JS 传来的参数里取。
        if self.takes_window and window is not None:
            kwargs[self.window_param] = window

        result = self.func(**kwargs)
        if self.is_async:
            result = run_coroutine(result)
        return self._validate_return(result)

    def _validate_args(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            validated = self.args_model(**args)
        except ValidationError as exc:
            raise CommandValidationError(
                f"命令 {self.name!r} 的参数不合法。",
                details=_json_errors(exc),
            ) from None
        return {field: getattr(validated, field) for field in type(validated).model_fields}

    def _validate_return(self, result: Any) -> Any:
        if self.return_adapter is None:
            return result
        try:
            return self.return_adapter.validate_python(result)
        except ValidationError as exc:
            raise CommandValidationError(
                f"命令 {self.name!r} 的返回值与返回注解不一致。",
                details=_json_errors(exc),
            ) from None


class EventSpec:
    """一个前端事件的 Python 处理函数。"""

    def __init__(self, event: str, func: Callable[..., Any]) -> None:
        self.event = event
        self.func = func
        hints = _resolve_hints(func, f"事件 {event!r} 的处理函数")
        params = list(inspect.signature(func).parameters)
        if len(params) > 1:
            raise TypeError(
                f"事件 {event!r} 的处理函数最多接收一个参数（payload），"
                f"当前声明了 {len(params)} 个。"
            )
        # 只有注解是 Pydantic 模型时才做校验，其他注解（dict、str……）原样传。
        annotation = hints.get(params[0]) if params else None
        self.payload_model = (
            annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel)
            else None
        )
        self._takes_payload = bool(params)

    def call(self, payload_json: str) -> None:
        if not self._takes_payload:
            self.func()
            return

        raw = json.loads(payload_json) if payload_json else None
        if self.payload_model is not None:
            try:
                raw = self.payload_model.model_validate(raw)
            except ValidationError as exc:
                raise CommandValidationError(
                    f"事件 {self.event!r} 的 payload 不合法。",
                    details=_json_errors(exc),
                ) from None

        result = self.func(raw)
        # 事件处理函数允许写成 async def。
        if inspect.iscoroutine(result):
            run_coroutine(result)


def _json_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """把 Pydantic 的错误转成纯 JSON（``ctx`` 里可能塞着异常对象）。"""
    return json.loads(exc.json(include_url=False))
