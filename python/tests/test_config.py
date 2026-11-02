"""Config parsing and path safety."""

from __future__ import annotations

from pathlib import Path

import pytest
from cakeui import find_pyproject, load_config
from cakeui.errors import ConfigError


def write_pyproject(root: Path, body: str) -> Path:
    path = root / "pyproject.toml"
    path.write_text(body.strip(), "utf-8")
    return path


def test_minimal_config_uses_defaults(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[project]
name = "my-app"

[tool.cakeui]
name = "My App"
""",
    )
    config = load_config(tmp_path)
    assert config.name == "My App"
    assert config.entry == "main.py"
    assert config.build.mode == "standalone"
    assert config.build.console is False
    assert "pydantic" in config.build.include_packages
    assert config.root == tmp_path


def test_name_falls_back_to_the_project_table(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[project]
name = "my-app"

[tool.cakeui]
entry = "app.py"
""",
    )
    config = load_config(tmp_path)
    assert config.name == "my-app"


def test_missing_tool_table_is_reported(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[project]\nname = "x"\n')
    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path)
    assert "[tool.cakeui]" in excinfo.value.message
    assert "hint" in excinfo.value.details


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="不存在"):
        load_config(tmp_path / "nope.toml")


def test_unknown_keys_are_rejected_with_the_field_name(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[tool.cakeui]
name = "X"
web_dir = "web"
""",
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path)
    fields = [item["field"] for item in excinfo.value.details]  # type: ignore[union-attr]
    assert "web_dir" in fields


def test_bad_mode_is_rejected(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[tool.cakeui]
name = "X"

[tool.cakeui.build]
mode = "zipped"
""",
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path)
    fields = [item["field"] for item in excinfo.value.details]  # type: ignore[union-attr]
    assert any("mode" in field for field in fields)


def test_paths_outside_the_project_are_refused(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[tool.cakeui]
name = "X"
web = "../../elsewhere"
""",
    )
    with pytest.raises(ConfigError, match="项目目录之外"):
        load_config(tmp_path)


def test_web_candidates_prefer_the_build_output(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        """
[tool.cakeui]
name = "X"
web = "web"
web_dist = "web/dist"
""",
    )
    config = load_config(tmp_path)
    candidates = config.web_candidates
    assert candidates[0] == tmp_path / "web" / "dist"
    assert candidates[1] == tmp_path / "web"


def test_resolve_index_html(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[tool.cakeui]\nname = "X"\nweb = "web"\n')
    assert load_config(tmp_path).resolve_index_html() is None

    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("<html></html>", "utf-8")
    assert load_config(tmp_path).resolve_index_html() == tmp_path / "web" / "index.html"


def test_find_pyproject_walks_up(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[tool.cakeui]\nname = "X"\n')
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)
    assert find_pyproject(nested) == tmp_path / "pyproject.toml"


def test_find_pyproject_skips_projects_without_the_table(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[project]\nname = "x"\n')
    assert find_pyproject(tmp_path) is None


def test_invalid_toml_is_reported(tmp_path: Path) -> None:
    write_pyproject(tmp_path, "[tool.cakeui\nname = 1")
    with pytest.raises(ConfigError, match="TOML 不合法"):
        load_config(tmp_path)


def test_icon_candidates_follow_the_platform(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[tool.cakeui]\nname = "X"\nicon = "assets/icon"\n')
    config = load_config(tmp_path)

    assert config.icon_candidates("darwin")[0].name == "icon.icns"
    assert config.icon_candidates("win32")[0].name == "icon.ico"
    assert config.icon_candidates("linux")[0].name == "icon.png"


def test_a_full_filename_is_tried_before_the_platform_format(tmp_path: Path) -> None:
    """写全了文件名就尊重用户的选择，别自作主张换成别的格式。"""
    write_pyproject(tmp_path, '[tool.cakeui]\nname = "X"\nicon = "logo.png"\n')
    config = load_config(tmp_path)

    candidates = config.icon_candidates("darwin")
    assert candidates[0] == tmp_path / "logo.png"
    assert candidates[1] == tmp_path / "logo.icns"


def test_an_icon_directory_looks_for_icon_dot_star(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[tool.cakeui]\nname = "X"\nicon = "assets"\n')
    (tmp_path / "assets").mkdir()
    config = load_config(tmp_path)

    assert config.icon_candidates("linux")[0] == tmp_path / "assets" / "icon.png"


def test_resolve_icon_picks_the_first_file_that_exists(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[tool.cakeui]\nname = "X"\nicon = "assets/icon"\n')
    (tmp_path / "assets").mkdir()
    assert load_config(tmp_path).resolve_icon("darwin") is None

    (tmp_path / "assets" / "icon.png").write_bytes(b"\x00")
    assert load_config(tmp_path).resolve_icon("darwin") == tmp_path / "assets" / "icon.png"


def test_no_icon_configured_means_no_candidates(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[tool.cakeui]\nname = "X"\n')
    config = load_config(tmp_path)

    assert config.icon_candidates() == []
    assert config.resolve_icon() is None
