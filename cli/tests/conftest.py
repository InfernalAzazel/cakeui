"""Fixtures for CLI tests: a project on disk and a fake Vite scaffold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from scaffold_fakes import fake_vite_scaffold


@pytest.fixture
def cli_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "cli-demo"

[tool.cakeui]
name = "Cli Demo"
entry = "main.py"
web = "web"
""".strip(),
        "utf-8",
    )
    (tmp_path / "main.py").write_text("print('hello')\n", "utf-8")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("<html></html>", "utf-8")
    return tmp_path


@pytest.fixture
def fake_vite(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch the real `create vite` call; returns the templates requested."""
    calls: list[str] = []

    def runner(web: Path, template: str, **kwargs: Any) -> Path:
        calls.append(template)
        return fake_vite_scaffold(web, template, kwargs.get("manager"))

    monkeypatch.setattr("cakeui_cli.scaffold.create_vite", runner)
    # Keep tests independent of whichever package manager ran pytest.
    monkeypatch.delenv("npm_config_user_agent", raising=False)
    return calls


@pytest.fixture
def vite_runner():
    return fake_vite_scaffold
