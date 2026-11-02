"""Finding and supervising the web frontend's dev server."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from cakeui import load_config
from cakeui_cli import packages
from cakeui_cli.devserver import (
    DevCommand,
    DevServer,
    DevServerError,
    detect_dev_command,
    refresh_bridge_module,
)


def write_project(root: Path, *, with_package_json: bool, extra: str = "") -> Path:
    (root / "pyproject.toml").write_text(
        f"""
[project]
name = "demo"

[tool.cakeui]
name = "Demo"
entry = "main.py"
web = "web"
{extra}
""".strip(),
        "utf-8",
    )
    (root / "main.py").write_text("print('hi')\n", "utf-8")
    web = root / "web"
    web.mkdir()
    if with_package_json:
        (web / "package.json").write_text(
            json.dumps({"name": "demo-web", "scripts": {"dev": "vite", "build": "vite build"}}),
            "utf-8",
        )
    return web


# -- detection ---------------------------------------------------------------
def test_dev_command_from_package_json(tmp_path: Path) -> None:
    write_project(tmp_path, with_package_json=True)
    command = detect_dev_command(load_config(tmp_path))

    assert command is not None
    assert command.argv == ["npm", "run", "dev"]
    assert command.cwd == tmp_path / "web"
    assert command.source == "package.json"


def test_recorded_package_manager_wins_over_detection(tmp_path: Path) -> None:
    write_project(tmp_path, with_package_json=True, extra='package_manager = "pnpm"')
    # No lockfile on disk: only the recorded value says pnpm.
    command = detect_dev_command(load_config(tmp_path))

    assert command is not None
    assert command.argv == ["pnpm", "run", "dev"]


def test_lockfile_still_covers_projects_without_a_recorded_manager(tmp_path: Path) -> None:
    web = write_project(tmp_path, with_package_json=True)
    (web / "pnpm-lock.yaml").write_text("", "utf-8")

    command = detect_dev_command(load_config(tmp_path))
    assert command is not None
    assert command.argv == ["pnpm", "run", "dev"]


def test_unknown_recorded_manager_is_reported(tmp_path: Path) -> None:
    from cakeui_cli.packages import PackageManagerError

    write_project(tmp_path, with_package_json=True, extra='package_manager = "cnpm"')
    with pytest.raises(PackageManagerError):
        detect_dev_command(load_config(tmp_path))


def test_dev_command_ignores_a_package_without_a_dev_script(tmp_path: Path) -> None:
    web = write_project(tmp_path, with_package_json=False)
    package = json.dumps({"scripts": {"build": "vite build"}})
    (web / "package.json").write_text(package, "utf-8")
    assert detect_dev_command(load_config(tmp_path)) is None


def test_dev_command_without_a_web_frontend(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\n[tool.cakeui]\nname = "X"\n', "utf-8"
    )
    assert detect_dev_command(load_config(tmp_path)) is None


def test_explicit_dev_command_wins(tmp_path: Path) -> None:
    write_project(tmp_path, with_package_json=True, extra='dev_command = "pnpm run watch"')
    command = detect_dev_command(load_config(tmp_path))

    assert command is not None
    assert command.argv == ["pnpm", "run", "watch"]
    assert command.cwd == tmp_path
    assert command.source == "config"


@pytest.mark.parametrize(
    ("lockfile", "expected"),
    [
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lock", "bun"),
        ("package-lock.json", "npm"),
    ],
)
def test_package_manager_from_lockfile(tmp_path: Path, lockfile: str, expected: str) -> None:
    assert packages.detect_name(tmp_path) is None
    (tmp_path / lockfile).write_text("", "utf-8")
    assert packages.detect_name(tmp_path) == expected


def test_package_manager_prefers_the_web_directory(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_text("", "utf-8")
    web = tmp_path / "web"
    web.mkdir()
    (web / "pnpm-lock.yaml").write_text("", "utf-8")
    assert packages.detect_name(web, tmp_path) == "pnpm"


def test_dev_command_uses_the_detected_package_manager(tmp_path: Path) -> None:
    web = write_project(tmp_path, with_package_json=True)
    (web / "pnpm-lock.yaml").write_text("", "utf-8")
    command = detect_dev_command(load_config(tmp_path))
    assert command is not None
    assert command.argv == ["pnpm", "run", "dev"]


def test_refresh_bridge_module_writes_into_its_own_subdirectory(tmp_path: Path) -> None:
    web = write_project(tmp_path, with_package_json=True)
    (web / "src").mkdir()
    written = refresh_bridge_module(load_config(tmp_path))

    bridge = web / "src" / "lib" / "cakeui"
    assert [path.name for path in written] == ["cakeui.js", "cakeui.d.ts"]
    assert all(path.parent == bridge for path in written)
    assert "export" in (bridge / "cakeui.js").read_text("utf-8")


def test_refresh_bridge_module_is_a_noop_without_src(tmp_path: Path) -> None:
    write_project(tmp_path, with_package_json=True)
    assert refresh_bridge_module(load_config(tmp_path)) == []


# -- process supervision -----------------------------------------------------
def fake_server(tmp_path: Path, body: str) -> DevCommand:
    script = tmp_path / "server.py"
    script.write_text(body, "utf-8")
    return DevCommand([sys.executable, "-u", str(script)], tmp_path, "test")


def test_wait_for_url_reads_vite_output(tmp_path: Path) -> None:
    command = fake_server(
        tmp_path,
        "import time\n"
        "print('\\\\x1b[32m  \\\\u279c  Local:\\\\x1b[0m   http://localhost:5199/')\n"
        "time.sleep(30)\n",
    )
    server = DevServer(command, echo=False)
    try:
        server.start()
        assert server.wait_for_url(timeout=20) == "http://localhost:5199/"
    finally:
        server.stop()


def test_stop_terminates_the_dev_server(tmp_path: Path) -> None:
    command = fake_server(
        tmp_path,
        "import time\nprint('Local: http://localhost:5198/')\ntime.sleep(30)\n",
    )
    server = DevServer(command, echo=False)
    server.start()
    server.wait_for_url(timeout=20)
    process = server._process
    assert process is not None

    server.stop()
    assert process.poll() is not None


def test_a_crashed_server_reports_its_output(tmp_path: Path) -> None:
    command = fake_server(
        tmp_path,
        "print('sh: vite: command not found')\nraise SystemExit(127)\n",
    )
    server = DevServer(command, echo=False)
    server.start()
    try:
        with pytest.raises(DevServerError) as excinfo:
            server.wait_for_url(timeout=30)
    finally:
        server.stop()

    assert "在就绪前就退出了" in excinfo.value.message
    assert "command not found" in excinfo.value.details["output"]


def test_missing_executable_is_reported(tmp_path: Path) -> None:
    server = DevServer(DevCommand(["definitely-not-a-real-binary"], tmp_path, "test"))
    with pytest.raises(DevServerError) as excinfo:
        server.start()
    assert "PATH 上找不到" in excinfo.value.message


def test_fallback_url_is_used_when_the_server_never_prints_one(tmp_path: Path) -> None:
    command = fake_server(tmp_path, "import time\ntime.sleep(30)\n")
    server = DevServer(command, echo=False)
    server.start()
    try:
        assert server.wait_for_url(timeout=0.5, fallback="http://localhost:4000/") == (
            "http://localhost:4000/"
        )
    finally:
        server.stop()


def test_timeout_without_a_fallback_raises(tmp_path: Path) -> None:
    command = fake_server(tmp_path, "import time\ntime.sleep(30)\n")
    server = DevServer(command, echo=False)
    server.start()
    try:
        with pytest.raises(DevServerError, match="没有打印出 URL"):
            server.wait_for_url(timeout=0.4)
    finally:
        server.stop()


def test_echo_forwards_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    command = fake_server(
        tmp_path,
        "import time\nprint('Local: http://localhost:5197/')\ntime.sleep(30)\n",
    )
    server = DevServer(command, echo=True)
    server.start()
    try:
        server.wait_for_url(timeout=20)
    finally:
        server.stop()
    assert "localhost:5197" in capsys.readouterr().out


def test_server_can_be_used_as_a_context_manager(tmp_path: Path) -> None:
    command = fake_server(
        tmp_path,
        "import time\nprint('Local: http://localhost:5196/')\ntime.sleep(30)\n",
    )
    with DevServer(command, echo=False) as server:
        assert server.wait_for_url(timeout=20) == "http://localhost:5196/"
        process = server._process
    assert process is not None and process.poll() is not None


def test_subprocess_is_started_in_its_own_group(tmp_path: Path) -> None:
    """Ctrl-C must reach the window and the dev server independently."""
    import os

    if os.name == "nt":
        pytest.skip("process groups behave differently on Windows")

    command = fake_server(
        tmp_path,
        "import os, time\n"
        "print('Local: http://localhost:5195/')\n"
        "print('pgid', os.getpgid(0), flush=True)\n"
        "time.sleep(30)\n",
    )
    server = DevServer(command, echo=False)
    server.start()
    try:
        server.wait_for_url(timeout=20)
        time.sleep(0.2)
        pgid = next(line for line in server.output.splitlines() if line.startswith("pgid"))
        child_pgid = int(pgid.split()[1])
        assert server._process is not None
        assert child_pgid == server._process.pid
    finally:
        server.stop()


def test_ansi_codes_are_stripped_from_recorded_output(tmp_path: Path) -> None:
    command = fake_server(
        tmp_path,
        "import time\n"
        "print('\\\\x1b[1mVITE v7\\\\x1b[0m  ready in 10 ms')\n"
        "print('Local: http://localhost:5194/')\n"
        "time.sleep(30)\n",
    )
    server = DevServer(command, echo=False)
    server.start()
    try:
        server.wait_for_url(timeout=20)
        assert "\x1b" not in server.output
        assert "VITE v7" in server.output
    finally:
        server.stop()


def test_non_loopback_urls_are_ignored() -> None:
    from cakeui_cli.devserver import _find_url

    assert _find_url("  Network:   http://192.168.1.5:5173/") is None
    assert _find_url("  Local:   http://localhost:5173/") == "http://localhost:5173/"
    assert _find_url("ready at http://127.0.0.1:8080.") == "http://127.0.0.1:8080"


def test_dev_command_display_is_joined() -> None:
    assert DevCommand(["npm", "run", "dev"], Path("."), "x").display == "npm run dev"


def test_completed_process_is_not_stopped_twice(tmp_path: Path) -> None:
    command = fake_server(tmp_path, "print('Local: http://localhost:5193/')\nexit(0)\n")
    server = DevServer(command, echo=False)
    server.start()
    time.sleep(1)
    server.stop()
    server.stop()  # must not raise
    assert isinstance(server.output, str)


def test_subprocess_creation_errors_are_wrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command = fake_server(tmp_path, "print('x')\n")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("nope")

    monkeypatch.setattr(subprocess, "Popen", boom)
    server = DevServer(command, echo=False)
    with pytest.raises(DevServerError, match="无法启动"):
        server.start()
