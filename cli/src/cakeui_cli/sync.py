"""``cakeui sync``：把前端里由 CakeUI 生成的文件对齐到当前安装的版本。

``web/src/lib/cakeui/`` 下的三份文件其实来自两个包，更新路径也不一样：

``cakeui.js`` / ``cakeui.d.ts``
    运行时 ``cakeui.bridge`` 的构建产物。文件头就写着 do not edit，而且被模板的
    ``.gitignore`` 忽略，所以它们只是运行时协议的镜像，无条件覆盖。

``cakeui-boot.ts``
    CLI 模板里的启动模块，是给人改的（README 里就写着删掉入口那行 import 即可
    脱离 CakeUI）。所以本地有改动时默认保留，只有 ``--force`` 才覆盖。

``cakeui dev`` 只在真的起了 dev server 时顺手刷新前两份（``--url`` 模式、没有
``package.json`` 的项目都碰不到），``cakeui new`` 又只装一次；这个命令把两件事
合成一个显式动作，并且能补回入口文件里丢掉的 boot import。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cakeui.bridge import (
    BRIDGE_FILENAME,
    BRIDGE_TYPES_FILENAME,
    bridge_module_source,
    bridge_types_source,
)
from cakeui.config import CakeUIConfig
from cakeui.errors import CakeUIError

from .scaffold import BASE_DIR
from .vite import BOOT_MARKER, BRIDGE_DIR, attach_boot, find_entry

BOOT_FILENAME = "cakeui-boot.ts"
_BOOT_TEMPLATE = BASE_DIR / "web" / "src" / BRIDGE_DIR / BOOT_FILENAME


class SyncError(CakeUIError):
    """当前目录不是一个能同步的项目。"""

    code = "sync_error"


@dataclass(frozen=True)
class SyncResult:
    """同步做了什么，供 CLI 原样打印。"""

    target: Path
    written: list[Path] = field(default_factory=list)
    kept: list[Path] = field(default_factory=list)
    entry: Path | None = None
    entry_updated: bool = False
    dry_run: bool = False
    # 有的项目根本没有可同步的东西，这不算失败，只是没做事。
    note: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.written or self.entry_updated)


def sync_project(
    config: CakeUIConfig,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> SyncResult:
    """把生成的文件重写进 ``web/src/lib/cakeui``。

    ``dry_run`` 只计算会改什么，一个字节都不写。
    """
    web = config.web_path
    if web is None:
        raise SyncError(
            "[tool.cakeui] 没有配置 web，找不到前端目录。",
            details={
                "hint": '加一行 web = "web"，或者先在项目根目录跑 `cakeui new`。',
                "root": str(config.root),
            },
        )

    source = web / "src"
    if not source.is_dir():
        # 没有打包器的项目：桥接由运行时在启动时写到 index.html 旁边，这里无事可做。
        return SyncResult(
            target=source / BRIDGE_DIR,
            dry_run=dry_run,
            note=f"{source} 不存在：这个前端不走打包器，桥接由应用启动时自行写出，无需同步。",
        )

    target = source / BRIDGE_DIR
    written: list[Path] = []
    kept: list[Path] = []

    for name, content in (
        (BRIDGE_FILENAME, bridge_module_source()),
        (BRIDGE_TYPES_FILENAME, bridge_types_source()),
    ):
        if _write_if_changed(target / name, content, dry_run=dry_run):
            written.append(target / name)

    boot = target / BOOT_FILENAME
    boot_source = _boot_source()
    if not boot.is_file():
        # 缺文件不是"覆盖"，直接补上。
        if _write_if_changed(boot, boot_source, dry_run=dry_run):
            written.append(boot)
    elif _same_content(boot, boot_source):
        pass
    elif force:
        if _write_if_changed(boot, boot_source, dry_run=dry_run):
            written.append(boot)
    else:
        kept.append(boot)

    entry = find_entry(web)
    entry_updated = False
    if entry is not None:
        # 预览时只看标记，别真去动用户的入口文件。
        entry_updated = not _has_boot_import(entry) if dry_run else attach_boot(entry)

    return SyncResult(
        target=target,
        written=written,
        kept=kept,
        entry=entry,
        entry_updated=entry_updated,
        dry_run=dry_run,
    )


def _boot_source() -> str:
    """CLI 里随包发布的启动模块模板。"""
    try:
        return _BOOT_TEMPLATE.read_text("utf-8")
    except OSError as exc:
        raise SyncError(
            f"CLI 安装不完整，找不到启动模块模板 {BOOT_FILENAME}。",
            details={
                "expected": str(_BOOT_TEMPLATE),
                "hint": "重新安装 cakeui-cli（pip install --force-reinstall cakeui-cli）。",
            },
        ) from exc


def _same_content(path: Path, content: str) -> bool:
    try:
        return path.read_text("utf-8") == content
    except (OSError, UnicodeDecodeError):
        return False


def _has_boot_import(entry: Path) -> bool:
    try:
        return BOOT_MARKER in entry.read_text("utf-8")
    except (OSError, UnicodeDecodeError):
        return False


def _write_if_changed(path: Path, content: str, *, dry_run: bool) -> bool:
    """内容没变就不动文件；返回这次是否需要（或已经）更新。

    和 ``cakeui.bridge`` 里的同名逻辑一致：不必要地重写文件会让 mtime 变化，
    进而让前端工具的缓存和 git 状态白忙一场。
    """
    if _same_content(path, content):
        return False
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, "utf-8")
    return True
