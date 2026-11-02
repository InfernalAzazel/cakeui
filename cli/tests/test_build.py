"""`cakeui build`: 前端构建 + Nuitka 打包的命令行组装与产物检查。"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from cakeui import load_config
from cakeui_cli import build as build_module
from cakeui_cli.build import BuildError, find_executable, plan_build, run_build
from cakeui_cli.main import main


def write_project(root: Path, *, scripts: bool = True, extra: str = "") -> Path:
    """一个最小的可打包项目：main.py + web/dist/index.html + 可选的 build 脚本。"""
    (root / "main.py").write_text("print('hi')\n", "utf-8")
    (root / "pyproject.toml").write_text(
        f"""
[project]
name = "build-demo"

[tool.cakeui]
name = "Build Demo"
entry = "main.py"
web = "web"
web_dist = "web/dist"
{extra}
""".strip(),
        "utf-8",
    )
    web = root / "web"
    (web / "dist").mkdir(parents=True)
    (web / "dist" / "index.html").write_text("<html></html>", "utf-8")
    if scripts:
        (web / "package.json").write_text(
            '{"name": "web", "scripts": {"dev": "vite", "build": "vite build"}}\n',
            "utf-8",
        )
    return root


def fake_executor(calls: list[tuple[list[str], Path]], *, code: int = 0):
    def run(argv: list[str], cwd: Path) -> int:
        calls.append((argv, cwd))
        return code

    return run


def test_plan_uses_standalone_by_default_and_ships_the_web_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    config = load_config(write_project(tmp_path))
    plan = plan_build(config)

    assert plan.mode == "standalone"
    assert "--standalone" in plan.nuitka_argv
    assert f"--output-dir={tmp_path / 'dist'}" in plan.nuitka_argv
    # 前端产物按原相对路径落进包里，运行时 web_candidates 才能找到它。
    assert "--include-data-dir=web/dist=web/dist" in plan.nuitka_argv
    # 没有 pyproject.toml 的话，打包后的 App.from_config() 直接启动失败。
    assert "--include-data-files=pyproject.toml=pyproject.toml" in plan.nuitka_argv
    # 入口固定放在最后。
    assert plan.nuitka_argv[-1] == "main.py"
    assert plan.nuitka_argv[:3] == [sys.executable, "-m", "nuitka"]


def test_plan_ships_the_js_bridge(tmp_path: Path) -> None:
    """_bridge.js 是包数据，Nuitka 不会自动带上；漏了打包后的应用一开窗就崩。"""
    argv = plan_build(load_config(write_project(tmp_path))).nuitka_argv

    assert "--include-package-data=cakeui" in argv


def test_plan_leaves_pywebview_to_nuitka(tmp_path: Path) -> None:
    """Nuitka 的 pywebview 插件 + 内置包配置已经处理了平台模块和 js 资源。

    自己再 include 会 FATAL：Conflict between user and plugin decision。
    """
    argv = plan_build(load_config(write_project(tmp_path))).nuitka_argv

    flags = ("--include-package=webview", "--include-package-data=webview")
    assert not [item for item in argv if item.startswith(flags)]
    # 非交互：不让 Nuitka 停下来等确认下载。
    assert "--assume-yes-for-downloads" in argv


def test_plan_overrides_mode_and_output_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    config = load_config(write_project(tmp_path))
    plan = plan_build(config, mode="onefile", output_dir=tmp_path / "out")

    assert "--onefile" in plan.nuitka_argv
    assert "--standalone" not in plan.nuitka_argv
    assert plan.output_dir == (tmp_path / "out").resolve()


def test_macos_always_builds_an_app_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """pyobjc 只能在 app 环境里工作，macOS 上用 --standalone 会被 Nuitka 拒绝。"""
    monkeypatch.setattr(sys, "platform", "darwin")
    config = load_config(write_project(tmp_path))

    assert "--mode=app-dist" in plan_build(config).nuitka_argv
    assert "--mode=app" in plan_build(config, mode="onefile").nuitka_argv


def test_plan_rejects_an_unknown_mode(tmp_path: Path) -> None:
    config = load_config(write_project(tmp_path))
    with pytest.raises(BuildError, match="未知的打包模式"):
        plan_build(config, mode="zipapp")


def test_plan_runs_the_package_json_build_script(tmp_path: Path) -> None:
    config = load_config(write_project(tmp_path))
    plan = plan_build(config)

    assert plan.web_argv is not None
    assert plan.web_argv[-1] == "build"
    assert plan.web_cwd == tmp_path / "web"


def test_no_web_skips_the_frontend_build(tmp_path: Path) -> None:
    config = load_config(write_project(tmp_path))
    plan = plan_build(config, build_web=False)

    assert plan.web_argv is None
    # 资源仍然要打进去，只是不重新构建。
    assert "--include-data-dir=web/dist=web/dist" in plan.nuitka_argv


def test_config_build_table_reaches_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    config = load_config(
        write_project(
            tmp_path,
            extra="""
[tool.cakeui.build]
mode = "onefile"
console = true
include_packages = ["pydantic"]
include_data_dir = ["assets", "data=shared/data"]
extra_args = ["--quiet"]
""",
        )
    )
    plan = plan_build(config)

    assert "--onefile" in plan.nuitka_argv
    assert "--include-package=pydantic" in plan.nuitka_argv
    # 只写目录名时，源和目标是同一个路径。
    assert "--include-data-dir=assets=assets" in plan.nuitka_argv
    assert "--include-data-dir=data=shared/data" in plan.nuitka_argv
    assert "--quiet" in plan.nuitka_argv


def test_missing_index_html_is_refused(tmp_path: Path) -> None:
    root = write_project(tmp_path)
    (root / "web" / "dist" / "index.html").unlink()

    with pytest.raises(BuildError, match=r"index\.html"):
        plan_build(load_config(root))


def test_run_build_executes_both_steps_and_finds_the_binary(tmp_path: Path) -> None:
    root = write_project(tmp_path)
    calls: list[tuple[list[str], Path]] = []

    def executor(argv: list[str], cwd: Path) -> int:
        calls.append((argv, cwd))
        if "nuitka" in argv:
            dist = root / "dist" / "main.dist"
            dist.mkdir(parents=True, exist_ok=True)
            (dist / "main.bin").write_text("", "utf-8")
        return 0

    result = run_build(plan_build(load_config(root)), executor=executor)

    assert [cwd for _, cwd in calls] == [root / "web", root]
    assert result.executable == root / "dist" / "main.dist" / "main.bin"


def test_frontend_failure_stops_before_nuitka(tmp_path: Path) -> None:
    root = write_project(tmp_path)
    calls: list[tuple[list[str], Path]] = []

    with pytest.raises(BuildError, match="前端构建失败"):
        run_build(plan_build(load_config(root)), executor=fake_executor(calls, code=1))

    assert len(calls) == 1  # 前端都失败了，不应该再去跑 Nuitka


def test_nuitka_failure_is_reported(tmp_path: Path) -> None:
    root = write_project(tmp_path)
    calls: list[tuple[list[str], Path]] = []

    def executor(argv: list[str], cwd: Path) -> int:
        calls.append((argv, cwd))
        # 前端构建成功，Nuitka 失败。
        return 2 if "nuitka" in argv else 0

    with pytest.raises(BuildError, match="Nuitka 打包失败"):
        run_build(plan_build(load_config(root)), executor=executor)

    assert len(calls) == 2


def test_a_missing_artifact_is_an_error(tmp_path: Path) -> None:
    root = write_project(tmp_path)
    with pytest.raises(BuildError, match="找不到可执行文件"):
        run_build(plan_build(load_config(root)), executor=fake_executor([]))


@pytest.mark.parametrize("suffix", ["", ".bin", ".exe"])
def test_find_executable_handles_platform_naming(tmp_path: Path, suffix: str) -> None:
    out = tmp_path / "onefile"
    out.mkdir()
    (out / f"main{suffix}").write_text("", "utf-8")
    assert find_executable(out, "main", "onefile") == out / f"main{suffix}"


def test_find_executable_looks_inside_the_standalone_folder(tmp_path: Path) -> None:
    dist = tmp_path / "main.dist"
    dist.mkdir()
    (dist / "main.bin").write_text("", "utf-8")
    assert find_executable(tmp_path, "main", "standalone") == dist / "main.bin"


def test_find_executable_handles_a_macos_bundle(tmp_path: Path) -> None:
    binary = tmp_path / "main.app" / "Contents" / "MacOS" / "main"
    binary.parent.mkdir(parents=True)
    binary.write_text("", "utf-8")
    assert find_executable(tmp_path, "main", "standalone") == binary


def test_windows_defaults_disable_the_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(write_project(tmp_path))
    monkeypatch.setattr(sys, "platform", "win32")
    argv = plan_build(config).nuitka_argv

    assert "--windows-disable-console" in argv
    assert "--include-package=clr" in argv


def test_console_stays_enabled_when_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = write_project(tmp_path, extra="[tool.cakeui.build]\nconsole = true")
    monkeypatch.setattr(sys, "platform", "win32")
    argv = plan_build(load_config(root)).nuitka_argv

    assert "--windows-disable-console" not in argv


def test_darwin_includes_the_pyobjc_packages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = load_config(write_project(tmp_path))
    monkeypatch.setattr(sys, "platform", "darwin")
    argv = plan_build(config).nuitka_argv

    # pywebview 的 cocoa 后端在函数内部 import 这些，静态分析不保证能跟上。
    for name in ("objc", "AppKit", "Foundation", "WebKit", "PyObjCTools"):
        assert f"--include-package={name}" in argv


def test_dry_run_prints_the_command_without_running_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("--dry-run 不应该执行任何命令")

    monkeypatch.setattr(build_module.subprocess, "run", boom)
    assert main(["build", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "--standalone" in out
    assert "--include-data-dir=web/dist=web/dist" in out


def test_cli_build_reports_the_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(tmp_path)
    monkeypatch.chdir(root)

    def fake_run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
        if "nuitka" in argv:
            dist = root / "dist" / "main.dist"
            dist.mkdir(parents=True, exist_ok=True)
            (dist / "main.bin").write_text("", "utf-8")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(build_module.subprocess, "run", fake_run)

    assert main(["build"]) == 0
    out = capsys.readouterr().out
    assert "main.bin" in out


def test_cli_build_failure_has_no_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = write_project(tmp_path)
    monkeypatch.chdir(root)

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(argv, 2 if "nuitka" in argv else 0)

    monkeypatch.setattr(build_module.subprocess, "run", fake_run)

    assert main(["build"]) == 1
    assert "Nuitka" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("platform", "flag"),
    [
        ("darwin", "--macos-app-icon"),
        ("win32", "--windows-icon-from-ico"),
        ("linux", "--linux-icon"),
    ],
)
def test_the_icon_reaches_each_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, flag: str
) -> None:
    root = write_project(tmp_path, extra='icon = "assets/app.png"')
    monkeypatch.setattr(sys, "platform", platform)
    argv = plan_build(load_config(root)).nuitka_argv

    assert f"{flag}=assets/app.png" in argv


def test_a_relative_output_dir_is_resolved_against_the_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """从子目录调用 `cakeui build` 时，相对目录也必须是相对项目根。"""
    config = load_config(write_project(tmp_path))
    monkeypatch.chdir(tmp_path / "web")

    plan = plan_build(config, output_dir="out")

    assert plan.output_dir == (tmp_path / "out").resolve()
    # 命令行里直接用绝对路径，Nuitka 就不会按自己的 cwd 再解释一遍。
    assert f"--output-dir={plan.output_dir}" in plan.nuitka_argv


def test_missing_nuitka_is_reported_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = write_project(tmp_path)
    monkeypatch.setattr(build_module, "find_spec", lambda name: None)

    with pytest.raises(BuildError, match="没有安装 Nuitka"):
        run_build(plan_build(load_config(root)))


def test_generated_project_config_round_trips(tmp_path: Path) -> None:
    """打包进包里的 pyproject.toml 必须还能被 load_config 解析。"""
    root = write_project(tmp_path)
    data = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))

    assert data["tool"]["cakeui"]["web_dist"] == "web/dist"
