"""读取 ``pyproject.toml`` 里的 ``[tool.cakeui]`` 配置表。"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import ConfigError
from .resources import program_dir, resource_root

DEFAULT_CONFIG_FILE = "pyproject.toml"

# 各平台认的原生图标格式，按优先级排列。
#
# 同一个 ``icon = "assets/icon"`` 在 macOS 上挑 .icns、Windows 上挑 .ico、
# Linux 上挑 .png：用户换图标时把整套文件放进同一个目录就行，配置不用动。
ICON_SUFFIXES: dict[str, tuple[str, ...]] = {
    "darwin": (".icns", ".png"),
    "win32": (".ico", ".png"),
    "linux": (".png", ".svg"),
}
# 不认识的平台按这个顺序找，.png 是唯一哪里都能读的格式。
DEFAULT_ICON_SUFFIXES = (".png", ".icns", ".ico", ".svg")


class BuildConfig(BaseModel):
    """``cakeui build``（Nuitka 打包）用到的参数，v0.3 起生效。"""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["standalone", "onefile"] = "standalone"
    console: bool = False
    output_dir: str = "dist"
    include_packages: list[str] = Field(default_factory=lambda: ["pydantic", "pydantic_core"])
    include_data_dir: list[str] = Field(default_factory=list)
    extra_args: list[str] = Field(default_factory=list)


class CakeUIConfig(BaseModel):
    """解析后的 ``[tool.cakeui]``。

    ``root`` 是 ``pyproject.toml`` 所在目录，由 :func:`load_config` 填进去，
    它本身永远不会出现在 TOML 文件里。
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    name: str
    entry: str = "main.py"
    web: str | None = None
    web_dist: str | None = None
    # `cakeui new` 会写下这一项，这样即使还没有 lockfile，也知道该用哪个包管理器。
    package_manager: str | None = None
    icon: str | None = None
    dev_url: str | None = None
    dev_command: str | None = None
    build: BuildConfig = Field(default_factory=BuildConfig)
    root: Path = Field(default_factory=Path)

    # -- 派生路径 --------------------------------------------------------
    @property
    def entry_path(self) -> Path:
        return self.root / self.entry

    @property
    def web_path(self) -> Path | None:
        """前端源码目录（``web/``），没配置就是 ``None``。"""
        return self.root / self.web if self.web else None

    @property
    def web_candidates(self) -> list[Path]:
        """可能含有 ``index.html`` 的目录，按优先级排列。

        构建产物优先于源码，和 Tauri / Electron 的行为一致：``web/dist``
        存在就说明它是真正要发布的那份。
        """
        candidates: list[Path] = []
        if self.web_dist:
            candidates.append(self.root / self.web_dist)
        if self.web:
            candidates.append(self.root / self.web)
        return candidates

    def resolve_index_html(self) -> Path | None:
        """在候选目录里找第一个真实存在的 ``index.html``。"""
        for directory in self.web_candidates:
            candidate = directory / "index.html"
            if candidate.is_file():
                return candidate
        return None

    def icon_candidates(self, platform: str | None = None) -> list[Path]:
        """按平台优先级列出候选图标，可能一个都不存在。

        ``icon`` 可以写全文件名（``assets/logo.png``）、只写主干
        （``assets/icon``）或者写目录（``assets``，目录里的文件要叫 ``icon.*``）。
        前一种完全按写的来，后两种才按平台去补扩展名：这样"换成自己的图标"
        只需要覆盖文件，``pyproject.toml`` 一个字都不用改。
        """
        if not self.icon:
            return []

        base = self.root / self.icon
        if base.is_dir():
            base = base / "icon"

        suffixes = ICON_SUFFIXES.get(platform or sys.platform, DEFAULT_ICON_SUFFIXES)
        derived = [base.with_suffix(suffix) for suffix in suffixes]
        if base.suffix:
            # 写全了文件名就先信它，再退回同名的平台格式，让 .png 也能在
            # macOS 上凑合（Nuitka 会自己转成 .icns）。
            return [base, *(path for path in derived if path != base)]
        return derived

    def resolve_icon(self, platform: str | None = None) -> Path | None:
        """第一个真实存在的候选图标；没配或者文件不全时返回 ``None``。"""
        return next((path for path in self.icon_candidates(platform) if path.is_file()), None)

    def validate_paths(self) -> None:
        """拒绝跑到项目目录之外的路径，免得一个笔误让打包读到整块磁盘。"""
        root = self.root.resolve()
        checks = [
            (self.entry, "entry"),
            (self.web, "web"),
            (self.web_dist, "web_dist"),
            (self.icon, "icon"),
            (self.build.output_dir, "build.output_dir"),
        ]
        # include_data_dir 的写法是 "源路径=目标路径"，只看等号左边。
        checks += [
            (item.split("=", 1)[0], "build.include_data_dir")
            for item in self.build.include_data_dir
        ]
        for value, field in checks:
            if not value:
                continue
            target = (root / value).resolve()
            if target != root and root not in target.parents:
                raise ConfigError(
                    f"[tool.cakeui] 的 {field} = {value!r} 指向了项目目录之外。",
                    details={"root": str(root), "resolved": str(target)},
                )


def default_search_start() -> Path:
    """查找 ``pyproject.toml`` 的起点。

    开发时是启动脚本所在目录（这样 ``python main.py`` 在任何 cwd 下都能跑）；
    打包后 ``resource_root()`` 指向应用产物目录，那里放着随包发布的
    ``pyproject.toml``。
    """
    script = program_dir()
    if script is not None:
        return script
    return resource_root()


def find_pyproject(start: str | Path | None = None) -> Path | None:
    """从 ``start`` 往上逐级查找带 ``[tool.cakeui]`` 的 ``pyproject.toml``。"""
    directory = Path(start).expanduser().resolve() if start else default_search_start()
    if directory.is_file():
        directory = directory.parent

    for candidate_dir in (directory, *directory.parents):
        candidate = candidate_dir / DEFAULT_CONFIG_FILE
        if not candidate.is_file():
            continue
        try:
            data = tomllib.loads(candidate.read_text("utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue  # 上层目录里的坏文件不应该挡住查找
        if isinstance(data.get("tool", {}).get("cakeui"), dict):
            return candidate
    return None


def load_config(path: str | Path | None = None) -> CakeUIConfig:
    """加载并校验 ``[tool.cakeui]``。

    ``path`` 可以是 ``pyproject.toml``、项目目录，或者留空（向上自动查找）。
    """
    resolved = _resolve_pyproject(path)
    try:
        data = tomllib.loads(resolved.read_text("utf-8"))
    except OSError as exc:
        raise ConfigError(f"无法读取 {resolved}：{exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{resolved} 里的 TOML 不合法：{exc}") from exc

    table = data.get("tool", {}).get("cakeui")
    if not isinstance(table, dict):
        raise ConfigError(
            f"{resolved} 里没有 [tool.cakeui] 表。",
            details={"hint": '加一段 [tool.cakeui]，至少写上 name = "MyApp"。'},
        )

    payload: dict[str, Any] = dict(table)
    # 没写 name 就继承 [project].name，省得每个项目写两遍。
    payload.setdefault("name", _project_name(data))
    payload["root"] = resolved.parent

    if not payload.get("name"):
        raise ConfigError(f"{resolved} 里 [tool.cakeui] 没有 name，[project] 也没有。")

    try:
        config = CakeUIConfig(**payload)
    except ValidationError as exc:
        raise ConfigError(
            f"{resolved} 里的 [tool.cakeui] 不合法。", details=_validation_details(exc)
        ) from exc

    config.validate_paths()
    return config


def _resolve_pyproject(path: str | Path | None) -> Path:
    """把用户给的 path 归一化成具体的 ``pyproject.toml`` 文件路径。"""
    if path is None:
        found = find_pyproject()
        if found is None:
            raise ConfigError(
                "找不到带 [tool.cakeui] 的 pyproject.toml。",
                details={"hint": "请在 CakeUI 项目里运行，或显式传入路径。"},
            )
        return found

    candidate = Path(path).expanduser().resolve()
    if candidate.is_dir():
        candidate = candidate / DEFAULT_CONFIG_FILE
    if not candidate.is_file():
        raise ConfigError(f"{candidate} 不存在。")
    return candidate


def _project_name(data: dict[str, Any]) -> str | None:
    """取 ``[project].name`` 作为 name 的兜底值。"""
    project = data.get("project")
    if isinstance(project, dict):
        name = project.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _validation_details(exc: ValidationError) -> list[dict[str, Any]]:
    """把 Pydantic 的错误压成 ``[{field, message}]``，方便 CLI 直接打印。"""
    details: list[dict[str, Any]] = []
    for error in exc.errors(include_url=False):
        loc = ".".join(str(part) for part in error.get("loc", ())) or "<root>"
        details.append({"field": loc, "message": error.get("msg", "invalid value")})
    return details
