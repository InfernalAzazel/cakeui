"""A stand-in for `npm create vite`, so tests never touch the network."""

from __future__ import annotations

import json
from pathlib import Path

from cakeui_cli.packages import PackageManager

ENTRY = "src/main.ts"
MAIN_TS = "import { createApp } from 'vue'\ncreateApp({}).mount('#app')\n"


def fake_vite_scaffold(web: Path, template: str, manager: PackageManager | None = None) -> Path:
    """Write the files a real ``--template vue-ts`` scaffold would write."""
    src = web / "src"
    src.mkdir(parents=True, exist_ok=True)
    (web / "index.html").write_text(
        f'<div id="app"></div>\n<script type="module" src="/{ENTRY}"></script>\n',
        "utf-8",
    )
    (web / "package.json").write_text(
        json.dumps(
            {
                "name": "web",
                "private": True,
                "type": "module",
                "scripts": {"dev": "vite", "build": "vite build"},
            }
        )
        + "\n",
        "utf-8",
    )
    (web / ENTRY).write_text(MAIN_TS, "utf-8")
    (web / ".gitignore").write_text("node_modules/\ndist/\n", "utf-8")
    (web / f".{template}-marker").write_text(template, "utf-8")
    if manager is not None:
        (web / ".manager").write_text(manager.name, "utf-8")
    return web
