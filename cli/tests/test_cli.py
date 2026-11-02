"""`cakeui new`, `cakeui dev` and `cakeui info`."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from cakeui_cli.main import main
from cakeui_cli.scaffold import (
    ScaffoldError,
    display_name,
    scaffold,
    template_names,
    validate_project_name,
)
from scaffold_fakes import fake_vite_scaffold


def fake_runner(calls: list[str] | None = None):
    """A Vite runner that mimics the real scaffold without touching the network."""

    def create(web: Path, template: str, **kwargs: Any) -> Path:
        if calls is not None:
            calls.append(template)
        return fake_vite_scaffold(web, template, kwargs.get("manager"))

    return create


def test_bundled_templates_are_vite_templates(tmp_path: Path) -> None:
    names = template_names()
    assert {"vue-ts", "react-ts", "svelte-ts", "vanilla-ts"} <= set(names)
    assert "_base_" not in names  # shared files, not a template
    assert "vanilla" not in names  # no hand-written no-build template


def test_base_directory_holds_the_python_side() -> None:
    from cakeui_cli.scaffold import BASE_DIR

    assert (BASE_DIR / "main.py").is_file()
    assert (BASE_DIR / "pyproject.toml").is_file()
    assert (BASE_DIR / "web" / "src" / "lib" / "cakeui" / "cakeui-boot.ts").is_file()
    # The frontend itself is never vendored: Vite generates it into web/.
    assert not (BASE_DIR / "web" / "index.html").exists()


def test_scaffold_merges_vite_output_with_the_base_layer(tmp_path: Path) -> None:
    calls: list[str] = []
    result = scaffold("my-app", tmp_path / "app", runner=fake_runner(calls))

    assert calls == ["vue-ts"]  # the default template
    project = result.destination

    # From `npm create vite`
    assert (project / "web" / "index.html").is_file()
    assert (project / "web" / "src" / "main.ts").is_file()
    assert (project / "web" / "package.json").is_file()

    # From `_base_`
    assert (project / "main.py").is_file()
    assert (project / "README.md").is_file()
    assert (project / ".gitignore").is_file()
    assert not (project / "_gitignore").exists()
    bridge = project / "web" / "src" / "lib" / "cakeui"
    assert (bridge / "cakeui-boot.ts").is_file()

    # Generated bridge, in CakeUI's own subdirectory
    assert (bridge / "cakeui.js").is_file()
    assert (bridge / "cakeui.d.ts").is_file()
    assert "export" in (bridge / "cakeui.js").read_text("utf-8")

    assert result.entry == project / "web" / "src" / "main.ts"


def test_generated_types_replace_the_template_placeholder(tmp_path: Path) -> None:
    """模板里的 cakeui.d.ts 只是占位，生成时必须被真实声明覆盖。"""
    from cakeui.bridge import bridge_types_source

    result = scaffold("my-app", tmp_path / "app", runner=fake_runner())
    generated = (result.destination / "web" / "src" / "lib" / "cakeui" / "cakeui.d.ts").read_text(
        "utf-8"
    )

    assert generated == bridge_types_source()
    assert "占位类型声明" not in generated


def test_entry_file_gets_one_bridge_import(tmp_path: Path) -> None:
    result = scaffold("my-app", tmp_path / "app", runner=fake_runner())
    entry = result.entry
    text = entry.read_text("utf-8")

    assert text.count("// cakeui:bridge") == 1
    assert 'import "./lib/cakeui/cakeui-boot";' in text
    # The framework's own code is untouched.
    assert text.startswith("import { createApp } from 'vue'")


def test_placeholders_are_substituted(tmp_path: Path) -> None:
    result = scaffold("my-notes-app", tmp_path / "app", runner=fake_runner())
    project = result.destination

    pyproject = (project / "pyproject.toml").read_text("utf-8")
    assert 'name = "my-notes-app"' in pyproject
    assert 'name = "My Notes App"' in pyproject
    assert '"cakeui>=0.1.0"' in pyproject
    assert 'web_dist = "web/dist"' in pyproject

    readme = (project / "README.md").read_text("utf-8")
    assert "My Notes App" in readme

    for path in project.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".toml", ".md", ".ts", ".js"}:
            assert "{{" not in path.read_text("utf-8"), f"unsubstituted placeholder in {path}"


def test_local_runtime_is_pinned_when_requested(tmp_path: Path) -> None:
    source = tmp_path / "checkout" / "python"
    result = scaffold("my-app", tmp_path / "app", runner=fake_runner(), cakeui_source=source)
    pyproject = (result.destination / "pyproject.toml").read_text("utf-8")

    assert "[tool.uv.sources]" in pyproject
    assert f'cakeui = {{ path = "{source.as_posix()}" }}' in pyproject


def test_no_source_table_by_default(tmp_path: Path) -> None:
    result = scaffold("my-app", tmp_path / "app", runner=fake_runner())
    assert "[tool.uv.sources]" not in (result.destination / "pyproject.toml").read_text("utf-8")


def test_any_vite_template_name_passes_through(tmp_path: Path) -> None:
    calls: list[str] = []
    result = scaffold("my-app", tmp_path / "app", template="solid-ts", runner=fake_runner(calls))

    assert calls == ["solid-ts"]
    assert result.template == "solid-ts"
    assert (result.destination / "main.py").is_file()


def test_unknown_template_name_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ScaffoldError, match="不是合法的模板名"):
        scaffold("my-app", tmp_path / "app", template="Not A Template", runner=fake_runner())


def test_missing_entry_script_is_reported(tmp_path: Path) -> None:
    from cakeui_cli.vite import ViteError

    def broken(web: Path, _template: str, **_kwargs: Any) -> Path:
        web.mkdir(parents=True, exist_ok=True)
        (web / "index.html").write_text('<div id="app"></div>\n', "utf-8")
        return web

    with pytest.raises(ViteError, match="入口模块"):
        scaffold("my-app", tmp_path / "app", runner=broken)


def test_package_manager_reaches_the_runner_and_the_docs(tmp_path: Path) -> None:
    calls: list[str] = []
    result = scaffold("my-app", tmp_path / "app", package_manager="pnpm", runner=fake_runner(calls))

    assert calls == ["vue-ts"]
    assert result.package_manager.name == "pnpm"
    assert (result.web / ".manager").read_text("utf-8") == "pnpm"

    pyproject = (result.destination / "pyproject.toml").read_text("utf-8")
    assert 'package_manager = "pnpm"' in pyproject

    readme = (result.destination / "README.md").read_text("utf-8")
    assert "(cd web && pnpm install)" in readme
    assert "(cd web && pnpm run build)" in readme
    assert not re.search(r"\bnpm\b", readme)  # not even as a fallback hint


def test_unknown_package_manager_is_refused(tmp_path: Path) -> None:
    from cakeui_cli.packages import PackageManagerError

    with pytest.raises(PackageManagerError):
        scaffold("my-app", tmp_path / "app", package_manager="cnpm", runner=fake_runner())


def test_package_manager_defaults_to_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("npm_config_user_agent", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bun.lockb").write_text("", "utf-8")

    result = scaffold("my-app", tmp_path / "app", runner=fake_runner())
    assert result.package_manager.name == "bun"


def test_display_name_helper() -> None:
    assert display_name("my-notes_app") == "My Notes App"


@pytest.mark.parametrize("name", ["Bad Name", "1app", "-app", "app/", ""])
def test_invalid_names_are_refused(name: str) -> None:
    with pytest.raises(ScaffoldError):
        validate_project_name(name)


def test_non_empty_destination_is_refused(tmp_path: Path) -> None:
    destination = tmp_path / "app"
    destination.mkdir()
    (destination / "keep.txt").write_text("x", "utf-8")

    with pytest.raises(ScaffoldError, match="不是空目录"):
        scaffold("demo", destination, runner=fake_runner())
    # Nothing is written when the destination is refused.
    assert list(destination.iterdir()) == [destination / "keep.txt"]


def test_force_writes_into_a_non_empty_directory(tmp_path: Path) -> None:
    destination = tmp_path / "app"
    destination.mkdir()
    (destination / "keep.txt").write_text("x", "utf-8")

    scaffold("demo", destination, force=True, runner=fake_runner())
    assert (destination / "main.py").is_file()
    assert (destination / "keep.txt").is_file()


def test_unknown_template_lists_alternatives(tmp_path: Path) -> None:
    with pytest.raises(ScaffoldError) as excinfo:
        scaffold("demo", tmp_path / "app", template="no such template")
    assert "vue-ts" in excinfo.value.details["available"]


def test_new_command_reports_next_steps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fake_vite: list[str]
) -> None:
    destination = tmp_path / "my-app"
    code = main(["new", "my-app", "--dir", str(destination), "--no-install"])

    assert code == 0
    assert (destination / "main.py").is_file()
    out = capsys.readouterr().out
    assert "cakeui dev" in out
    assert "vue-ts" in out
    assert fake_vite == ["vue-ts"]


def test_cli_errors_are_reported_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], fake_vite: list[str]
) -> None:
    destination = tmp_path / "app"
    destination.mkdir()
    (destination / "keep.txt").write_text("x", "utf-8")

    assert main(["new", "app", "--dir", str(destination), "--no-install"]) == 1
    assert "不是空目录" in capsys.readouterr().err


def test_info_prints_the_resolved_config(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(cli_project)
    assert main(["info"]) == 0
    out = capsys.readouterr().out
    assert "Cli Demo" in out
    assert "main.py" in out
    assert "index.html" in out


def test_dev_runs_the_entry_point_with_the_dev_url(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(cli_project)
    recorded: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        recorded["command"] = command
        recorded["env"] = kwargs["env"]
        recorded["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("cakeui_cli.main.subprocess.run", fake_run)

    code = main(["dev", "--url", "http://localhost:5173", "--", "--flag"])

    assert code == 0
    assert recorded["command"][1:3] == ["-u", str(cli_project / "main.py")]
    assert recorded["command"][-1] == "--flag"
    assert recorded["env"]["CAKEUI_DEV_URL"] == "http://localhost:5173"
    assert recorded["cwd"] == cli_project


def test_dev_passes_through_a_dev_url_from_the_environment(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lets `npm run dev` or a task runner hand the URL to `cakeui dev`."""
    monkeypatch.chdir(cli_project)
    monkeypatch.setenv("CAKEUI_DEV_URL", "http://localhost:3000")
    recorded: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        recorded["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("cakeui_cli.main.subprocess.run", fake_run)

    assert main(["dev"]) == 0
    assert recorded["env"]["CAKEUI_DEV_URL"] == "http://localhost:3000"


def test_dev_starts_the_configured_dev_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Python entry point must see the URL the dev server printed."""
    server_pid = tmp_path / "server.pid"
    (tmp_path / "dev_server.py").write_text(
        "import os, pathlib, time\n"
        f"pathlib.Path({str(server_pid)!r}).write_text(str(os.getpid()))\n"
        "print('  VITE v7.3.7  ready in 10 ms')\n"
        "print('  Local:   http://localhost:5188/')\n"
        "time.sleep(30)\n",
        "utf-8",
    )
    (tmp_path / "main.py").write_text(
        "import os\nprint('URL=' + os.environ.get('CAKEUI_DEV_URL', '<unset>'))\n",
        "utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        f"""
[project]
name = "demo"

[tool.cakeui]
name = "Demo"
entry = "main.py"
dev_command = '{sys.executable} -u dev_server.py'
""".strip(),
        "utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert main(["dev"]) == 0

    # The child ran with the detected URL, and the server was shut down after.
    assert server_pid.is_file(), "the dev server never started"
    pid = int(server_pid.read_text())
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            break
        time.sleep(0.05)
    else:
        os.kill(pid, 15)  # pragma: no cover - cleanup on failure
        raise AssertionError("the dev server outlived `cakeui dev`")


def test_dev_reports_a_dev_server_that_dies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "dev_server.py").write_text("raise SystemExit(1)\n", "utf-8")
    (tmp_path / "main.py").write_text("print('should not run')\n", "utf-8")
    (tmp_path / "pyproject.toml").write_text(
        f"""
[project]
name = "demo"

[tool.cakeui]
name = "Demo"
entry = "main.py"
dev_command = '{sys.executable} -u dev_server.py'
""".strip(),
        "utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert main(["dev"]) == 1


def test_dev_url_flag_does_not_start_a_server(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--url` means the developer already has a server running."""
    monkeypatch.chdir(cli_project)
    (cli_project / "web" / "package.json").write_text(
        json.dumps({"scripts": {"dev": "vite"}}), "utf-8"
    )
    recorded: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        recorded["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("cakeui_cli.main.subprocess.run", fake_run)

    assert main(["dev", "--url", "http://localhost:7000/"]) == 0
    assert recorded["env"]["CAKEUI_DEV_URL"] == "http://localhost:7000/"


def test_dev_sets_no_dev_url_when_none_is_configured(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(cli_project)
    monkeypatch.delenv("CAKEUI_DEV_URL", raising=False)
    recorded: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        recorded["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("cakeui_cli.main.subprocess.run", fake_run)

    assert main(["dev"]) == 0
    assert "CAKEUI_DEV_URL" not in recorded["env"]
