"""Package manager selection: one table drives scaffold, install and `dev`."""

from __future__ import annotations

import pytest
from cakeui_cli import packages
from cakeui_cli.packages import PackageManager, PackageManagerError


def test_known_manager_names() -> None:
    assert packages.names() == ["npm", "pnpm", "yarn", "bun"]


def test_unknown_manager_is_rejected() -> None:
    with pytest.raises(PackageManagerError) as excinfo:
        packages.get("cnpm")
    assert "pnpm" in excinfo.value.details["available"]


def test_create_argv_only_needs_a_separator_for_npm() -> None:
    assert packages.get("npm").create_argv("web", "vue-ts") == [
        "npm",
        "create",
        "vite@latest",
        "web",
        "--",
        "--template",
        "vue-ts",
    ]
    assert packages.get("pnpm").create_argv("web", "vue-ts") == [
        "pnpm",
        "create",
        "vite@latest",
        "web",
        "--template",
        "vue-ts",
    ]
    assert packages.get("bun").create_argv("web", "vue-ts")[-2:] == ["--template", "vue-ts"]


def test_yarn_classic_gets_an_unpinned_spec() -> None:
    # `yarn create vite@latest` resolves to a path and fails with ENOENT.
    assert packages.get("yarn").create_argv("web", "vue-ts") == [
        "yarn",
        "create",
        "vite",
        "web",
        "--template",
        "vue-ts",
    ]


def test_install_and_run_commands() -> None:
    pnpm = packages.get("pnpm")
    assert pnpm.install_argv() == ["pnpm", "install"]
    assert pnpm.run_argv("dev") == ["pnpm", "run", "dev"]
    # Hints are pasteable from the project root, so they run in a subshell.
    assert pnpm.install_hint("web") == "(cd web && pnpm install)"
    assert pnpm.run_hint("web", "build") == "(cd web && pnpm run build)"


def test_detect_prefers_a_lockfile(tmp_path) -> None:
    (tmp_path / "pnpm-lock.yaml").write_text("", "utf-8")
    assert packages.detect(tmp_path).name == "pnpm"

    bun = tmp_path / "bun-project"
    bun.mkdir()
    (bun / "bun.lock").write_text("", "utf-8")
    assert packages.detect(bun).name == "bun"

    # Several lockfiles: the fixed order (pnpm, bun, yarn, npm) decides.
    mixed = tmp_path / "mixed"
    mixed.mkdir()
    (mixed / "package-lock.json").write_text("", "utf-8")
    (mixed / "yarn.lock").write_text("", "utf-8")
    assert packages.detect(mixed).name == "yarn"


def test_detect_falls_back_to_the_invoking_shell(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(packages.USER_AGENT_ENV, "pnpm/11.5.0 npm/? node/v22.0.0 darwin arm64")
    assert packages.detect(tmp_path).name == "pnpm"


def test_detect_defaults_to_npm(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(packages.USER_AGENT_ENV, raising=False)
    assert packages.detect(tmp_path).name == "npm"
    # `detect_name` reports "nothing to go on" instead of inventing npm.
    assert packages.detect_name(tmp_path) is None


def test_lockfile_beats_the_user_agent(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(packages.USER_AGENT_ENV, "npm/10.0.0 node/v20.0.0")
    (tmp_path / "yarn.lock").write_text("", "utf-8")
    assert packages.detect(tmp_path).name == "yarn"


def test_missing_binary_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(packages.shutil, "which", lambda _name: None)
    with pytest.raises(PackageManagerError, match="PATH 上找不到"):
        packages.ensure_available(packages.get("pnpm"))


def test_manager_is_a_value_object() -> None:
    assert PackageManager("pnpm") == PackageManager("pnpm")
