"""Test doubles for pywebview objects."""

from __future__ import annotations

from typing import Any


class FakeEvent:
    """Mimics ``webview.event.Event``: ``+= handler`` then ``set()``."""

    def __init__(self) -> None:
        self._handlers: list[Any] = []
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def __iadd__(self, handler: Any) -> FakeEvent:
        self._handlers.append(handler)
        return self

    def set(self) -> None:
        self._set = True
        for handler in list(self._handlers):
            handler(self)


class FakeEvents:
    def __init__(self) -> None:
        self.loaded = FakeEvent()
        self.closed = FakeEvent()


class FakeNative:
    """Stands in for ``webview.Window``; records every ``evaluate_js`` call."""

    def __init__(self, title: str = "Fake") -> None:
        self.title = title
        self.events = FakeEvents()
        self.scripts: list[str] = []
        self.destroyed = False
        self.visible = True

    def evaluate_js(self, script: str) -> int:
        self.scripts.append(script)
        return 1

    def destroy(self) -> None:
        self.destroyed = True

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False
