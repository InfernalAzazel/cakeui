"""Command registration, Pydantic validation and window injection."""

from __future__ import annotations

import pytest
from cakeui import App, Window, command
from cakeui.commands import build_command_spec
from cakeui.errors import CommandValidationError
from pydantic import BaseModel


class TaskInput(BaseModel):
    """Module-level so ``get_type_hints`` can resolve the forward reference."""

    title: str
    done: bool = False


def test_basic_command_validates_and_calls() -> None:
    def greet(name: str) -> str:
        return f"hi {name}"

    spec = build_command_spec(greet)
    assert spec.name == "greet"
    assert spec.call({"name": "Ada"}, None) == "hi Ada"


def test_defaults_are_applied() -> None:
    def repeat(text: str, times: int = 2) -> str:
        return text * times

    spec = build_command_spec(repeat)
    assert spec.call({"text": "a"}, None) == "aa"
    assert spec.call({"text": "a", "times": 3}, None) == "aaa"


def test_optional_parameter_with_none_default() -> None:
    def show(value: str = None) -> str:  # type: ignore[assignment]  # noqa: RUF013
        return "none" if value is None else value

    spec = build_command_spec(show)
    assert spec.call({}, None) == "none"
    assert spec.call({"value": "x"}, None) == "x"


def test_extra_arguments_are_rejected() -> None:
    def ping() -> str:
        return "pong"

    spec = build_command_spec(ping)
    with pytest.raises(CommandValidationError) as excinfo:
        spec.call({"unexpected": 1}, None)

    assert excinfo.value.code == "validation_error"
    assert excinfo.value.details[0]["loc"] == ["unexpected"]


def test_type_errors_are_reported_per_field() -> None:
    def add(a: int, b: int) -> int:
        return a + b

    spec = build_command_spec(add)
    with pytest.raises(CommandValidationError) as excinfo:
        spec.call({"a": 1, "b": "two"}, None)

    errors = excinfo.value.details
    assert len(errors) == 1
    assert errors[0]["loc"] == ["b"]
    assert "int" in errors[0]["msg"]


def test_invalid_return_value_is_rejected() -> None:
    def bad() -> int:
        return "not an int"  # type: ignore[return-value]

    spec = build_command_spec(bad)
    with pytest.raises(CommandValidationError) as excinfo:
        spec.call({}, None)
    assert "返回值" in excinfo.value.message


def test_validate_return_false_skips_check() -> None:
    def bad() -> int:
        return "not an int"  # type: ignore[return-value]

    spec = build_command_spec(bad, validate_return=False)
    assert spec.call({}, None) == "not an int"


def test_window_is_injected_and_not_part_of_the_payload() -> None:
    app = App(title="Test")
    sent: list[tuple[str, object]] = []

    @app.command
    def ping(window: Window) -> str:
        sent.append(("ping", window.id))
        return window.id

    spec = app.router.get("ping")
    assert spec is not None
    assert spec.takes_window
    assert not spec.args_model.model_fields

    fake_window = Window(object(), app, window_id="w9")
    assert spec.call({}, fake_window) == "w9"
    assert sent == [("ping", "w9")]

    with pytest.raises(CommandValidationError):
        spec.call({"window": "nope"}, fake_window)


def test_window_injection_accepts_pipe_union_annotation() -> None:
    """``Window | None`` 和 ``Optional[Window]`` 是两种运行期对象，都要认。"""

    def ping(window: Window | None) -> str:
        assert window is not None
        return window.id

    spec = build_command_spec(ping)
    assert spec.takes_window

    app = App()
    fake_window = Window(object(), app, window_id="w7")
    assert spec.call({}, fake_window) == "w7"


def test_unannotated_parameter_fails_at_registration() -> None:
    def broken(name) -> str:  # type: ignore[no-untyped-def]
        return name

    with pytest.raises(TypeError, match="缺少类型注解"):
        build_command_spec(broken)


def test_varargs_are_refused_with_a_helpful_message() -> None:
    def broken(*args: int) -> int:
        return sum(args)

    with pytest.raises(TypeError, match=r"\*args / \*\*kwargs"):
        build_command_spec(broken)


def test_duplicate_command_names_are_refused() -> None:
    app = App()

    @app.command
    def ping() -> str:
        return "a"

    with pytest.raises(ValueError, match="已经注册过了"):

        @app.command
        def ping() -> str:  # type: ignore[misc]
            return "b"


def test_module_level_command_can_be_collected_by_an_app() -> None:
    @command
    def shared(value: int) -> int:
        return value + 1

    app = App(commands=[shared])
    spec = app.router.get("shared")
    assert spec is not None
    assert spec.call({"value": 1}, None) == 2


def test_async_commands_are_supported() -> None:
    @command
    async def double(value: int) -> int:
        return value * 2

    spec = build_command_spec(double)
    assert spec.is_async
    assert spec.call({"value": 21}, None) == 42


def test_pydantic_model_argument_is_validated_recursively() -> None:
    def add(task: TaskInput) -> str:
        return f"{task.title}:{task.done}"

    spec = build_command_spec(add)
    assert spec.call({"task": {"title": "write tests"}}, None) == "write tests:False"
    with pytest.raises(CommandValidationError):
        spec.call({"task": {"done": True}}, None)
