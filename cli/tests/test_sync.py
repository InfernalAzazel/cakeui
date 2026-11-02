"""`cakeui sync`: 把 web/src/lib/cakeui 对齐到当前安装的版本。"""

from __future__ import annotations

from pathlib import Path

import pytest
from cakeui import load_config
from cakeui_cli.main import main
from cakeui_cli.sync import BOOT_FILENAME, SyncError, sync_project
from cakeui_cli.vite import BOOT_MARKER, BRIDGE_DIR


def write_project(root: Path, *, source_dir: bool = True) -> Path:
    """一个最小项目：pyproject + web/index.html + web/src/main.ts。"""
    (root / "pyproject.toml").write_text(
        """
[project]
name = "sync-demo"

[tool.cakeui]
name = "Sync Demo"
entry = "main.py"
web = "web"
""".strip(),
        "utf-8",
    )
    (root / "main.py").write_text("print('hi')\n", "utf-8")
    web = root / "web"
    web.mkdir()
    (web / "index.html").write_text('<script type="module" src="/src/main.ts"></script>', "utf-8")
    if source_dir:
        src = web / "src"
        src.mkdir()
        (src / "main.ts").write_text('console.log("app");\n', "utf-8")
    return root


def bridge_dir(root: Path) -> Path:
    return root / "web" / "src" / BRIDGE_DIR


def test_sync_writes_the_whole_bridge_directory(tmp_path: Path) -> None:
    root = write_project(tmp_path)
    result = sync_project(load_config(root))

    target = bridge_dir(root)
    assert result.target == target
    assert sorted(path.name for path in result.written) == sorted(
        ["cakeui.js", "cakeui.d.ts", BOOT_FILENAME]
    )
    assert "export" in (target / "cakeui.js").read_text("utf-8")
    assert (target / "cakeui.d.ts").is_file()
    assert BOOT_FILENAME in {path.name for path in target.iterdir()}


def test_sync_attaches_the_boot_import_to_the_entry(tmp_path: Path) -> None:
    root = write_project(tmp_path)
    result = sync_project(load_config(root))

    assert result.entry == root / "web" / "src" / "main.ts"
    assert result.entry_updated is True
    text = result.entry.read_text("utf-8")  # type: ignore[union-attr]
    assert BOOT_MARKER in text
    assert 'import "./lib/cakeui/cakeui-boot";' in text
    # 原有内容不能被重写，只允许追加。
    assert text.startswith('console.log("app");')


def test_sync_does_not_duplicate_an_existing_import(tmp_path: Path) -> None:
    root = write_project(tmp_path)
    sync_project(load_config(root))

    again = sync_project(load_config(root))

    assert again.entry_updated is False
    assert again.written == []
    assert again.changed is False


def test_sync_keeps_a_locally_edited_boot_module(tmp_path: Path) -> None:
    """cakeui-boot.ts 是给人改的：默认不能把本地改动冲掉。"""
    root = write_project(tmp_path)
    sync_project(load_config(root))
    boot = bridge_dir(root) / BOOT_FILENAME
    boot.write_text("// 我自己改的 toast\n", "utf-8")

    result = sync_project(load_config(root))

    assert result.kept == [boot]
    assert boot.read_text("utf-8") == "// 我自己改的 toast\n"


def test_force_overwrites_the_boot_module(tmp_path: Path) -> None:
    root = write_project(tmp_path)
    sync_project(load_config(root))
    boot = bridge_dir(root) / BOOT_FILENAME
    boot.write_text("// 我自己改的 toast\n", "utf-8")

    result = sync_project(load_config(root), force=True)

    assert boot in result.written
    assert boot.read_text("utf-8") != "// 我自己改的 toast\n"


def test_generated_files_are_always_overwritten(tmp_path: Path) -> None:
    """这两份是构建产物，被 git 忽略，本地手改应该被覆盖。"""
    root = write_project(tmp_path)
    sync_project(load_config(root))
    bridge = bridge_dir(root) / "cakeui.js"
    bridge.write_text("// 手改过的桥接\n", "utf-8")

    result = sync_project(load_config(root))

    assert bridge in result.written
    assert "export" in bridge.read_text("utf-8")


def test_sync_does_not_touch_files_that_are_already_current(tmp_path: Path) -> None:
    root = write_project(tmp_path)
    sync_project(load_config(root))
    bridge = bridge_dir(root) / "cakeui.js"
    before = bridge.stat().st_mtime_ns

    sync_project(load_config(root))

    assert bridge.stat().st_mtime_ns == before


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    root = write_project(tmp_path)
    result = sync_project(load_config(root), dry_run=True)

    assert result.written  # 报告了会写哪些
    assert not bridge_dir(root).exists()
    assert BOOT_MARKER not in (root / "web" / "src" / "main.ts").read_text("utf-8")


def test_dry_run_reports_the_pending_import(tmp_path: Path) -> None:
    root = write_project(tmp_path)
    result = sync_project(load_config(root), dry_run=True)

    assert result.entry_updated is True
    assert result.changed is True


def test_a_project_without_a_bundler_is_not_an_error(tmp_path: Path) -> None:
    """没有 web/src 的项目由运行时在启动时写出 index.html 旁边的桥接。"""
    root = write_project(tmp_path, source_dir=False)
    result = sync_project(load_config(root))

    assert result.note is not None
    assert result.written == []
    assert not (root / "web" / "src").exists()


def test_a_project_without_a_web_directory_is_refused(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.cakeui]\nname = "No Web"\n', "utf-8")

    with pytest.raises(SyncError) as excinfo:
        sync_project(load_config(tmp_path))

    assert "web" in excinfo.value.message
    assert "hint" in excinfo.value.details


# -- CLI 层 ----------------------------------------------------------------
def test_the_command_reports_what_it_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_project(tmp_path)
    monkeypatch.chdir(root)

    assert main(["sync"]) == 0

    out = capsys.readouterr().out
    assert "cakeui.js" in out
    assert "cakeui-boot.ts" in out
    assert bridge_dir(root).is_dir()


def test_the_command_is_quiet_when_nothing_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_project(tmp_path)
    monkeypatch.chdir(root)
    main(["sync"])
    capsys.readouterr()

    assert main(["sync"]) == 0
    assert "没有改动" in capsys.readouterr().out


def test_dry_run_through_the_cli_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = write_project(tmp_path)
    monkeypatch.chdir(root)

    assert main(["sync", "--dry-run"]) == 0

    assert "--dry-run" in capsys.readouterr().err
    assert not bridge_dir(root).exists()
