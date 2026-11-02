"""Shared fixtures: a fake pywebview window so nothing needs a GUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from _fakes import FakeNative
from cakeui import App, Window


@pytest.fixture
def app() -> App:
    return App(title="Test")


@pytest.fixture
def window(app: App) -> Window:
    return Window(FakeNative(), app, window_id="w1")


@pytest.fixture(autouse=True)
def _reset_resource_root() -> Any:
    """Keep the module-level override from leaking between tests."""
    from cakeui.resources import set_resource_root

    set_resource_root(None)
    yield
    set_resource_root(None)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A minimal CakeUI project on disk."""
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo-app"

[tool.cakeui]
name = "Demo"
entry = "main.py"
web = "web"
""".strip(),
        "utf-8",
    )
    (tmp_path / "main.py").write_text("print('hi')\n", "utf-8")
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html></html>", "utf-8")
    return tmp_path
