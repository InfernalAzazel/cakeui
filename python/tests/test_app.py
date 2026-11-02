"""App wiring: config defaults, event delivery, and web asset resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _fakes import FakeNative
from cakeui import App, Window, load_config
from cakeui.errors import CakeUIError, ConfigError


def payload_of(script: str) -> dict:
    """Pull the JSON payload out of a ``window.__cakeui._dispatch('...')`` call."""
    start = script.index("(") + 1
    end = script.rindex(")")
    return json.loads(json.loads(script[start:end]))


def test_title_defaults_to_the_config_name(project: Path) -> None:
    app = App.from_config(project)
    assert app.title == "Demo"
    assert app.config is not None
    assert app.config.root == project


def test_from_config_without_a_project_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["pytest"])
    with pytest.raises(ConfigError, match=r"pyproject\.toml"):
        App.from_config()


def test_nothing_is_emitted_before_the_window_loads(app: App) -> None:
    window = Window(FakeNative(), app, window_id="w1")
    app._windows.append(window)

    assert app.emit("toast", {"text": "early"}) == 0
    assert window.native.scripts == []  # type: ignore[attr-defined]

    window.native.events.loaded.set()  # type: ignore[attr-defined]

    scripts = window.native.scripts  # type: ignore[attr-defined]
    assert len(scripts) == 1
    assert payload_of(scripts[0]) == {"event": "toast", "payload": {"text": "early"}}


def test_emit_reaches_every_window(app: App, window: Window) -> None:
    second = Window(FakeNative(), app, window_id="w2")
    app._windows.extend([window, second])
    for item in (window, second):
        item.native.events.loaded.set()  # type: ignore[attr-defined]

    assert app.emit("ping") == 2
    assert payload_of(window.native.scripts[-1]) == {"event": "ping", "payload": None}  # type: ignore[attr-defined]


def test_emit_serializes_pydantic_and_paths(app: App, window: Window) -> None:
    from pydantic import BaseModel

    class Item(BaseModel):
        name: str

    window.native.events.loaded.set()  # type: ignore[attr-defined]
    app._windows.append(window)
    app.emit("item", {"model": Item(name="cake"), "path": Path("/tmp/x")})

    payload = payload_of(window.native.scripts[-1])["payload"]  # type: ignore[attr-defined]
    assert payload == {"model": {"name": "cake"}, "path": "/tmp/x"}


def test_unserializable_payload_raises(app: App, window: Window) -> None:
    window.native.events.loaded.set()  # type: ignore[attr-defined]
    app._windows.append(window)

    with pytest.raises(CakeUIError) as excinfo:
        app.emit("bad", {"value": object()})
    assert excinfo.value.code == "serialization_error"


def test_event_names_with_quotes_are_escaped(app: App, window: Window) -> None:
    window.native.events.loaded.set()  # type: ignore[attr-defined]
    app._windows.append(window)
    app.emit('quote\'s "event"', {"text": "line\nbreak \u2028 separator"})

    script = window.native.scripts[-1]  # type: ignore[attr-defined]
    assert "\u2028" not in script
    assert payload_of(script) == {
        "event": 'quote\'s "event"',
        "payload": {"text": "line\nbreak \u2028 separator"},
    }


def test_local_web_frontend_is_found_and_the_bridge_is_written(project: Path) -> None:
    app = App.from_config(project)
    url = app._resolve_url()

    index = project / "web" / "index.html"
    assert url == str(index)
    bridge = project / "web" / "cakeui.js"
    assert bridge.is_file()
    assert "invoke" in bridge.read_text("utf-8")


def test_dev_url_env_overrides_local_files(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAKEUI_DEV_URL", "http://localhost:5173")
    app = App.from_config(project)
    assert app._resolve_url() == "http://localhost:5173"


def test_explicit_url_wins_over_the_env(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAKEUI_DEV_URL", "http://localhost:5173")
    app = App.from_config(project, url="http://localhost:9999")
    assert app._resolve_url() == "http://localhost:9999"


def test_web_dist_wins_over_web_source(project: Path) -> None:
    dist = project / "web" / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>built</html>", "utf-8")

    config = load_config(project)
    config = config.model_copy(update={"web_dist": "web/dist"})
    app = App.from_config(project, config=config)

    assert app._resolve_url() == str(dist / "index.html")


def test_missing_web_frontend_gives_an_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n[tool.cakeui]\nname = "X"\n', "utf-8"
    )
    app = App.from_config(tmp_path)
    with pytest.raises(ConfigError) as excinfo:
        app._resolve_url()
    assert "index.html" in excinfo.value.message
    assert "hint" in excinfo.value.details


def test_debug_env_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAKEUI_DEBUG", "1")
    assert App().debug is True
    assert App(debug=False).debug is False
