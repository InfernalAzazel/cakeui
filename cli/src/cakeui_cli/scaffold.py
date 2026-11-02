"""项目脚手架：Vite 负责生成前端，CakeUI 把自己合并进去。

只需要一个共享层：

``templates/_base_/``
    每个项目都会拿到的文件，会覆盖到生成的前端之上。里面的内容最终落在项目
    根目录（``main.py``、``pyproject.toml``……）。

前端本身从不内置副本：由 ``npm create vite`` 现生成，因此 Vue / React / Svelte
始终是上游版本，CakeUI 的差异只限于桥接文件和一行 import。
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cakeui.bridge import ensure_bridge_module
from cakeui.errors import CakeUIError

from . import packages
from .packages import PackageManager
from .vite import BRIDGE_DIR, WEB_DIR, ViteError, attach_boot, create_vite, find_entry

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
BASE_DIR = TEMPLATES_DIR / "_base_"
DEFAULT_TEMPLATE = "vue-ts"

# 内置模板只是"Vite 认识、我们也验证过"的名字清单；前端永远由 Vite 生成。
# 其他合法的 Vite 模板名同样可以直接用。
BUILTIN_TEMPLATES = ("vue-ts", "react-ts", "svelte-ts", "vanilla-ts")

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
# 模板里的 dotfile 没法正常放进仓库，用下划线前缀代替，复制时改回来。
_RENAMES = {"_gitignore": ".gitignore", "_gitattributes": ".gitattributes", "_env": ".env"}

ViteRunner = Callable[..., Path]


class ScaffoldError(CakeUIError):
    """项目没能生成出来。"""

    code = "scaffold_error"


@dataclass(frozen=True)
class ScaffoldResult:
    """脚手架产物，供 CLI 打印准确的摘要。"""

    destination: Path
    entry: Path
    bridge_files: list[Path]
    template: str
    package_manager: PackageManager

    @property
    def web(self) -> Path:
        return self.destination / WEB_DIR


def template_names() -> list[str]:
    """内置模板名清单（供 ``--help`` 和报错提示用）。"""
    return list(BUILTIN_TEMPLATES)


def resolve_template(name: str) -> str:
    """校验并返回要交给 Vite 的模板名。

    内置清单之外的合法名字原样透传，例如 ``--template solid-ts``：Vite 自己
    认识它就够了，CakeUI 不需要提前知道。
    """
    if not _NAME_PATTERN.match(name):
        raise ScaffoldError(
            f"{name!r} 不是合法的模板名。",
            details={"available": template_names(), "hint": "请传一个 Vite 模板名。"},
        )
    return name


def validate_project_name(name: str) -> str:
    """校验项目名并原样返回，方便链式使用。"""
    if not _NAME_PATTERN.match(name):
        raise ScaffoldError(
            f"{name!r} 不能用作项目名。",
            details={
                "hint": (
                    "只能用小写字母、数字和单个连字符或下划线，并以字母开头（例如 my-notes）。"
                )
            },
        )
    return name


def display_name(project_name: str) -> str:
    """``my-notes`` → ``My Notes``，用在文档标题里。"""
    return re.sub(r"[-_]+", " ", project_name).title()


def scaffold(
    project_name: str,
    destination: Path,
    *,
    template: str = DEFAULT_TEMPLATE,
    force: bool = False,
    cakeui_requirement: str = ">=0.1.0",
    cakeui_source: Path | None = None,
    package_manager: str | PackageManager | None = None,
    runner: ViteRunner | None = None,
) -> ScaffoldResult:
    """按 ``template`` 生成 ``destination``。

    ``cakeui_source`` 把运行时指向本地 checkout：``cakeui new`` 在运行时是从
    磁盘（而不是 PyPI）安装的时候会传它，否则新项目里 ``uv sync`` 解析不到
    ``cakeui``。

    ``runner`` 可注入，测试因此能在没有网络的情况下验证合并逻辑；生产环境永远
    使用 :func:`cakeui_cli.vite.create_vite`。
    """
    validate_project_name(project_name)
    selected = resolve_template(template)
    manager = _resolve_manager(package_manager)
    destination = destination.resolve()

    if destination.exists():
        if not destination.is_dir():
            raise ScaffoldError(f"{destination} 已存在，而且不是目录。")
        if any(destination.iterdir()) and not force:
            raise ScaffoldError(
                f"{destination} 不是空目录。",
                details={"hint": "加 --force 强制写入，或者换一个 --dir。"},
            )

    substitutions = {
        "project_name": project_name,
        "display_name": display_name(project_name),
        "cakeui_requirement": cakeui_requirement,
        "package_manager": manager.name,
        "install_command": manager.install_hint(WEB_DIR),
        "build_command": manager.run_hint(WEB_DIR, "build"),
    }

    destination.mkdir(parents=True, exist_ok=True)
    web = destination / WEB_DIR
    (runner or create_vite)(web, selected, manager=manager)
    rename_web_package(web, f"{project_name}-web")

    # 先放共享文件，再放项目自己的文件。
    _merge(BASE_DIR, destination, substitutions)
    if cakeui_source is not None:
        _pin_local_runtime(destination / "pyproject.toml", cakeui_source)

    entry = find_entry(web)
    if entry is None:
        raise ViteError(
            "找不到可以挂载 CakeUI 的前端入口模块。",
            details={
                "looked_in": str(web / "index.html"),
                "hint": '请保留 index.html 里的 <script type="module" src=...> 标签。',
            },
        )

    bridge_files = ensure_bridge_module(entry.parent / BRIDGE_DIR)
    attach_boot(entry)

    return ScaffoldResult(
        destination=destination,
        entry=entry,
        bridge_files=bridge_files,
        template=selected,
        package_manager=manager,
    )


def _merge(source: Path, destination: Path, substitutions: dict[str, str]) -> None:
    """把 ``source`` 覆盖到 ``destination``，同时处理改名的 dotfile 和占位符。"""
    if not source.is_dir():
        raise ScaffoldError(
            f"模板目录 {source.name!r} 不存在。",
            details={"expected": str(source)},
        )

    for path in sorted(source.rglob("*")):
        relative = _renamed(path.relative_to(source))
        target = destination / relative
        target = target.parent / _substitute(target.name, substitutions)

        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        _copy_or_render(path, target, substitutions)


def _copy_or_render(source: Path, target: Path, substitutions: dict[str, str]) -> None:
    """能按 UTF-8 读出来就替换占位符，读不出来就当二进制直接复制。"""
    try:
        text = source.read_text("utf-8")
    except UnicodeDecodeError:
        shutil.copyfile(source, target)
        return
    target.write_text(_substitute(text, substitutions), "utf-8")


def _resolve_manager(manager: str | PackageManager | None) -> PackageManager:
    if isinstance(manager, PackageManager):
        return manager
    if manager:
        return packages.get(manager)
    # 新项目沿用"运行这条命令的地方"所用的包管理器：先看当前目录的 lockfile，
    # 再看启动 cakeui 的 shell。
    return packages.detect(Path.cwd())


def rename_web_package(web: Path, name: str) -> None:
    """把生成的 package.json 名字改成 ``<项目>-web``，而不是默认的 "web"。"""
    manifest = web / "package.json"
    if not manifest.is_file():
        return
    try:
        data = json.loads(manifest.read_text("utf-8"))
    except (OSError, ValueError):
        return
    data["name"] = name
    manifest.write_text(json.dumps(data, indent=2) + "\n", "utf-8")


def _pin_local_runtime(pyproject: Path, source: Path) -> None:
    """把新项目指向本地的 ``cakeui`` checkout。

    只在运行时尚且没发布的时候用：否则新项目里的 ``uv sync`` 根本解析不到
    ``cakeui``。写进去的注释会告诉用户什么时候可以删掉这段。
    """
    try:
        text = pyproject.read_text("utf-8")
    except OSError:
        return
    if "[tool.uv.sources]" in text:
        return

    snippet = (
        "\n# 本地 checkout：`cakeui new` 检测到尚未发布的 CakeUI 运行时。\n"
        "# 等 cakeui 从 PyPI 安装后，删掉这张表即可。\n"
        "[tool.uv.sources]\n"
        f'cakeui = {{ path = "{source.as_posix()}" }}\n'
    )
    pyproject.write_text(text.rstrip("\n") + "\n" + snippet, "utf-8")


def _renamed(relative: Path) -> Path:
    """把下划线前缀的 dotfile 名字改回真正的文件名。"""
    parts = list(relative.parts)
    if parts:
        parts[-1] = _RENAMES.get(parts[-1], parts[-1])
    return Path(*parts)


def _substitute(text: str, substitutions: dict[str, str]) -> str:
    """替换 ``{{ key }}``（带不带空格都认）。"""
    for key, value in substitutions.items():
        text = text.replace("{{ " + key + " }}", value).replace("{{" + key + "}}", value)
    return text
