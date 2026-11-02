"""Resource resolution and the packaged JS bridge asset."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from cakeui import load_config, resource_path, resource_root, set_resource_root
from cakeui.bridge import (
    bridge_module_source,
    bridge_source,
    bridge_types_source,
    ensure_bridge_file,
    ensure_bridge_module,
)
from cakeui.errors import BridgeError
from cakeui.resources import ENV_RESOURCE_ROOT


def test_resource_path_is_relative_to_the_root(tmp_path: Path) -> None:
    set_resource_root(tmp_path)
    assert resource_root() == tmp_path.resolve()
    assert resource_path("assets/logo.png") == (tmp_path / "assets" / "logo.png").resolve()


def test_absolute_paths_pass_through(tmp_path: Path) -> None:
    set_resource_root(tmp_path / "ignored")
    absolute = Path("/tmp/somewhere/icon.png")
    assert resource_path(absolute) == absolute
    assert resource_path(str(absolute)) == absolute


def test_env_var_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_RESOURCE_ROOT, str(tmp_path))
    assert resource_root() == tmp_path.resolve()


def test_explicit_override_beats_the_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_RESOURCE_ROOT, str(tmp_path / "env"))
    set_resource_root(tmp_path / "explicit")
    assert resource_root() == (tmp_path / "explicit").resolve()


def test_dev_fallback_uses_the_running_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "main.py"
    script.write_text("", "utf-8")
    monkeypatch.setattr(sys, "argv", [str(script)])
    monkeypatch.delenv(ENV_RESOURCE_ROOT, raising=False)
    assert resource_root() == tmp_path.resolve()


def test_nuitka_standalone_resolves_to_the_dist_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nuitka standalone：包目录在 <dist>/cakeui/，根目录就是 <dist>/。

    ``__compiled__.containing_dir`` 指向 --output-dir（<dist> 的上一级），
    用它定位资源会直接找错地方。
    """
    from cakeui import resources

    dist = tmp_path / "main.dist"
    monkeypatch.setattr(resources, "_PACKAGE_DIR", dist / "cakeui")
    monkeypatch.setitem(
        vars(resources),
        "__compiled__",
        type(
            "Compiled", (), {"standalone": True, "onefile": False, "containing_dir": str(tmp_path)}
        )(),
    )

    assert resources.resource_root() == dist


def test_nuitka_onefile_resolves_to_the_unpacked_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """onefile：数据文件解压到临时目录，包目录仍在那里面。"""
    from cakeui import resources

    unpacked = tmp_path / "onefile_123"
    monkeypatch.setattr(resources, "_PACKAGE_DIR", unpacked / "cakeui")
    monkeypatch.setitem(
        vars(resources),
        "__compiled__",
        type("Compiled", (), {"standalone": True, "onefile": True})(),
    )

    assert resources.resource_root() == unpacked


def test_packaged_app_finds_its_shipped_pyproject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """打包后没有 cwd 帮助，只能靠产物目录里的 pyproject.toml。"""
    from cakeui import resources
    from cakeui.config import default_search_start

    dist = tmp_path / "main.dist"
    dist.mkdir()
    (dist / "pyproject.toml").write_text(
        '[tool.cakeui]\nname = "Packed"\nweb_dist = "web/dist"\n', "utf-8"
    )
    monkeypatch.setattr(resources, "_PACKAGE_DIR", dist / "cakeui")
    monkeypatch.setitem(
        vars(resources),
        "__compiled__",
        type("Compiled", (), {"standalone": True, "onefile": False})(),
    )
    # 打包后 argv[0] 是可执行文件而不是 .py 脚本，且从别的目录启动。
    monkeypatch.setattr(sys, "argv", [str(dist / "main")])
    monkeypatch.chdir(tmp_path.parent)

    assert default_search_start() == dist
    assert load_config().name == "Packed"


def test_bridge_asset_is_packaged() -> None:
    assert "invoke" in bridge_source()


def test_bridge_module_and_types_are_packaged() -> None:
    module = bridge_module_source()
    assert "export" in module
    assert "window.cakeui" not in module  # ESM build must not require the global

    types = bridge_types_source()
    assert "export declare function invoke" in types


def test_bridge_assets_match_the_js_build() -> None:
    """Guards against committing stale copies of js/dist/*."""
    dist = Path(__file__).resolve().parents[2] / "js" / "dist"
    if not dist.is_dir():
        pytest.skip("js/ has not been built in this checkout")

    pairs = {
        "cakeui.global.js": bridge_source,
        "index.mjs": bridge_module_source,
        "index.d.ts": bridge_types_source,
    }
    for filename, reader in pairs.items():
        assert reader() == (dist / filename).read_text("utf-8"), f"{filename} is stale"


def test_ensure_bridge_module_writes_js_and_types(tmp_path: Path) -> None:
    written = ensure_bridge_module(tmp_path)

    assert [path.name for path in written] == ["cakeui.js", "cakeui.d.ts"]
    assert (tmp_path / "cakeui.js").read_text("utf-8") == bridge_module_source()
    assert (tmp_path / "cakeui.d.ts").read_text("utf-8") == bridge_types_source()


def test_ensure_bridge_module_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "cakeui.js"
    ensure_bridge_module(tmp_path)
    first_mtime = target.stat().st_mtime_ns

    target.write_text("stale", "utf-8")
    ensure_bridge_module(tmp_path)

    assert target.read_text("utf-8") == bridge_module_source()
    assert target.stat().st_mtime_ns != first_mtime


def test_ensure_bridge_file_writes_and_is_idempotent(tmp_path: Path) -> None:
    target = ensure_bridge_file(tmp_path)
    assert target == tmp_path / "cakeui.js"
    assert target.read_text("utf-8") == bridge_source()

    first_mtime = target.stat().st_mtime_ns
    target.write_text("stale", "utf-8")
    ensure_bridge_file(tmp_path)
    assert target.read_text("utf-8") == bridge_source()
    assert target.stat().st_mtime_ns != first_mtime


def test_missing_asset_raises_a_bridge_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cakeui.bridge._DIR", tmp_path)
    with pytest.raises(BridgeError) as excinfo:
        bridge_source()
    assert "npm run build" in excinfo.value.details["hint"]


def test_bridge_file_is_written_next_to_a_read_only_dir_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name == "nt":
        pytest.skip("chmod semantics differ on Windows")

    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(0o500)
    try:
        with pytest.raises(BridgeError):
            ensure_bridge_file(readonly / "nested")
    finally:
        readonly.chmod(0o700)
