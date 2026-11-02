"""The JSON envelope protocol over ``js_api``."""

from __future__ import annotations

import json

import pytest
from cakeui import App, Window
from cakeui.router import Router
from pydantic import BaseModel


class Ping(BaseModel):
    """Module-level so annotations resolve under ``from __future__ import annotations``."""

    count: int


def route(router: Router, message: object, window: Window | None = None) -> dict:
    """Send one protocol message and decode the reply envelope."""
    return json.loads(router.handle(json.dumps(message), window))


@pytest.fixture
def router(app: App) -> Router:
    received: list[dict] = []

    @app.command
    def greet(name: str) -> str:
        return f"hi {name}"

    @app.command
    def boom() -> str:
        raise RuntimeError("kaboom")

    @app.on("log")
    def on_log(payload: dict) -> None:
        received.append(payload)

    router_instance = app.router
    router_instance.received = received  # type: ignore[attr-defined]
    return router_instance


def test_invoke_returns_data(router: Router) -> None:
    result = route(router, {"t": "invoke", "cmd": "greet", "args": {"name": "Ada"}})
    assert result == {"ok": True, "data": "hi Ada"}


def test_unknown_command_lists_the_available_ones(router: Router) -> None:
    result = route(router, {"t": "invoke", "cmd": "nope"})
    assert result["ok"] is False
    assert result["error"]["code"] == "command_not_found"
    assert "greet" in result["error"]["details"]["available"]


def test_malformed_json_is_a_bad_request(router: Router) -> None:
    result = json.loads(router.handle("{not json"))
    assert result["error"]["code"] == "bad_request"


def test_unknown_message_type_is_a_bad_request(router: Router) -> None:
    result = route(router, {"t": "watch"})
    assert result["error"]["code"] == "bad_request"


def test_non_object_payload_is_a_bad_request(router: Router) -> None:
    result = route(router, [1, 2, 3])
    assert result["error"]["code"] == "bad_request"


def test_validation_errors_are_structured(router: Router) -> None:
    result = route(router, {"t": "invoke", "cmd": "greet", "args": {}})
    assert result["ok"] is False
    assert result["error"]["code"] == "validation_error"
    assert result["error"]["details"][0]["loc"] == ["name"]


def test_unexpected_exceptions_are_hidden_without_debug(router: Router) -> None:
    result = route(router, {"t": "invoke", "cmd": "boom"})
    assert result["error"]["code"] == "internal_error"
    assert "RuntimeError: kaboom" in result["error"]["message"]
    assert "details" not in result["error"]


def test_debug_includes_a_traceback() -> None:
    router = Router(debug=True)

    @router.add_command
    def boom() -> None:
        raise RuntimeError("kaboom")

    result = route(router, {"t": "invoke", "cmd": "boom"})
    assert "Traceback" in result["error"]["details"]["traceback"]


def test_emit_reaches_python_handlers(router: Router) -> None:
    result = route(router, {"t": "emit", "event": "log", "payload": {"message": "hello"}})
    assert result == {"ok": True, "data": 1}
    assert router.received == [{"message": "hello"}]  # type: ignore[attr-defined]


def test_emit_to_an_unregistered_event_is_refused(router: Router) -> None:
    result = route(router, {"t": "emit", "event": "missing", "payload": None})
    assert result["error"]["code"] == "bad_request"
    assert "log" in result["error"]["details"]["registered"]


def test_event_payload_can_be_a_pydantic_model(app: App) -> None:
    seen: list[int] = []

    @app.on("ping")
    def on_ping(ping: Ping) -> None:
        seen.append(ping.count)

    result = route(app.router, {"t": "emit", "event": "ping", "payload": {"count": 3}})
    assert result["ok"] is True
    assert seen == [3]


def test_event_payload_validation_failure(app: App) -> None:
    @app.on("ping")
    def on_ping(ping: Ping) -> None:
        pass

    result = route(app.router, {"t": "emit", "event": "ping", "payload": {}})
    assert result["error"]["code"] == "validation_error"


def test_handler_exceptions_surface_as_event_handler_error(app: App) -> None:
    @app.on("explode")
    def on_explode(payload: object) -> None:
        raise ValueError("nope")

    result = route(app.router, {"t": "emit", "event": "explode", "payload": 1})
    assert result["error"]["code"] == "event_handler_error"
    assert "nope" in result["error"]["message"]


def test_window_is_forwarded_to_the_command(app: App) -> None:
    @app.command
    def whoami(window: Window) -> str:
        return window.id

    window = Window(object(), app, window_id="w42")
    result = route(app.router, {"t": "invoke", "cmd": "whoami"}, window)
    assert result["data"] == "w42"
