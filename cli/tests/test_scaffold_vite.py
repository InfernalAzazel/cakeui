"""Scaffolding against Vite itself, not against a vendored copy of it.

Network-gated: set ``CAKEUI_TEST_VITE=1`` to run. The rest of the suite uses the
fake runner in ``conftest.py`` so it stays offline and fast.
"""

from __future__ import annotations

import os
import shutil

import pytest
from cakeui_cli.scaffold import scaffold
from cakeui_cli.vite import attach_boot, find_entry

pytestmark = [
    pytest.mark.skipif(shutil.which("npm") is None, reason="npm is not installed"),
    pytest.mark.skipif(
        not os.environ.get("CAKEUI_TEST_VITE"),
        reason="set CAKEUI_TEST_VITE=1 to scaffold with the real Vite",
    ),
]


@pytest.mark.parametrize("template", ["vue-ts", "vanilla-ts"])
def test_real_vite_scaffold(tmp_path, template: str) -> None:
    result = scaffold("real-app", tmp_path / "app", template=template)

    assert result.entry.name in {"main.ts", "main.tsx"}
    assert 'import "./cakeui-boot";' in result.entry.read_text("utf-8")
    assert (result.web / "package.json").is_file()
    assert (result.web / "src" / "cakeui-boot.ts").is_file()
    assert result.bridge_files

    package = (result.web / "package.json").read_text("utf-8")
    assert '"real-app-web"' in package


def test_entry_and_boot_helpers(tmp_path) -> None:
    index = tmp_path / "index.html"
    index.write_text('<script type="module" src="/src/main.tsx"></script>', "utf-8")
    entry = tmp_path / "src" / "main.tsx"
    entry.parent.mkdir()
    entry.write_text("console.log(1)\n", "utf-8")

    assert find_entry(tmp_path) == entry
    assert attach_boot(entry) is True
    assert attach_boot(entry) is False  # idempotent
    assert entry.read_text("utf-8").count("cakeui:bridge") == 1
