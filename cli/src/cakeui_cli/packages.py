"""选择和驱动 JavaScript 包管理器。

一张表决定所有事情：怎么脚手架（``pnpm create vite …``）、怎么安装、怎么跑
脚本、哪个 lockfile 说明项目已经在用它。新增一个包管理器只是加一条表项，
不需要在 CLI 里再加分支。
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from cakeui.errors import CakeUIError

DEFAULT = "npm"

# 每个跑生命周期脚本的包管理器都会设置它，例如
# "pnpm/9.1.0 npm/? node/v20.11.0 darwin arm64"。
USER_AGENT_ENV = "npm_config_user_agent"


@dataclass(frozen=True)
class PackageManager:
    """和一个包管理器打交道所需的全部信息。"""

    name: str
    lockfiles: tuple[str, ...] = ()
    # npm 需要显式的 `--` 才会把参数转交给 create-vite，其他几个直接透传。
    separator: bool = False
    # 交给 `create` 的包名。`@latest` 让脚手架保持最新，但 yarn classic 会
    # 把它当成路径（`create-vite@latest`）从而失败，所以 yarn 这里不加。
    create_package: str = "vite"

    def create_argv(self, directory: str, template: str) -> list[str]:
        """生成用本管理器脚手架 ``template`` 到 ``directory`` 的命令。"""
        argv = [self.name, "create", self.create_package, directory]
        if self.separator:
            argv.append("--")
        return [*argv, "--template", template]

    def install_argv(self) -> list[str]:
        return [self.name, "install"]

    def run_argv(self, script: str) -> list[str]:
        return [self.name, "run", script]

    def install_hint(self, directory: str) -> str:
        """用户可以直接粘贴的一行命令；用子 shell 是为了不改变他的 cwd。"""
        return f"(cd {directory} && {self.name} install)"

    def run_hint(self, directory: str, script: str) -> str:
        return f"(cd {directory} && {self.name} run {script})"


MANAGERS: dict[str, PackageManager] = {
    "npm": PackageManager(
        "npm", ("package-lock.json",), separator=True, create_package="vite@latest"
    ),
    "pnpm": PackageManager("pnpm", ("pnpm-lock.yaml",), create_package="vite@latest"),
    # yarn classic 会把 `create vite@latest` 解析成文件路径，所以这里不锁定版本。
    "yarn": PackageManager("yarn", ("yarn.lock",)),
    "bun": PackageManager("bun", ("bun.lockb", "bun.lock"), create_package="vite@latest"),
}

# 同时存在多个 lockfile 时的优先级。
_LOCKFILE_ORDER = ("pnpm", "bun", "yarn", "npm")


class PackageManagerError(CakeUIError):
    """指定的包管理器未知，或本机没有安装。"""

    code = "package_manager_error"


def names() -> list[str]:
    return list(MANAGERS)


def get(name: str) -> PackageManager:
    try:
        return MANAGERS[name]
    except KeyError:
        raise PackageManagerError(
            f"{name!r} 不是受支持的包管理器。",
            details={"available": names()},
        ) from None


def which(manager: PackageManager) -> str | None:
    return shutil.which(manager.name)


def ensure_available(manager: PackageManager) -> None:
    """确认包管理器在 PATH 上，否则给一句"装一个 / 换一个"的提示。"""
    if which(manager) is not None:
        return
    installed = [name for name in names() if shutil.which(name)]
    details: dict[str, object] = {
        "hint": (f"请安装它，或用 --package-manager 换一个：{', '.join(installed) or 'npm'}")
    }
    # 如果是从 `pnpm dlx cakeui-cli new` 之类的方式启动的，把来源也告诉用户。
    user_agent = os.environ.get(USER_AGENT_ENV)
    if user_agent:
        details["detected_from"] = user_agent
    raise PackageManagerError(f"PATH 上找不到 {manager.name!r}。", details=details)


def detect(*directories: Path | str | None) -> PackageManager:
    """按 lockfile → 调用它的 shell → npm 的顺序挑一个。

    lockfile 优先，因为它描述的是项目本身；user agent 是兜底，让
    ``pnpm dlx cakeui-cli new`` 不用额外指定也能用 pnpm 脚手架。
    """
    for directory in directories:
        if directory is None:
            continue
        found = _from_lockfile(Path(directory))
        if found is not None:
            return found
    return _from_user_agent() or MANAGERS[DEFAULT]


def detect_name(*directories: Path | str | None) -> str | None:
    """和 :func:`detect` 一样，但什么都没发现时返回 ``None``。"""
    for directory in directories:
        if directory is None:
            continue
        found = _from_lockfile(Path(directory))
        if found is not None:
            return found.name
    from_agent = _from_user_agent()
    return from_agent.name if from_agent else None


def _from_lockfile(directory: Path) -> PackageManager | None:
    for name in _LOCKFILE_ORDER:
        manager = MANAGERS[name]
        if any((directory / filename).is_file() for filename in manager.lockfiles):
            return manager
    return None


def _from_user_agent() -> PackageManager | None:
    user_agent = os.environ.get(USER_AGENT_ENV, "")
    return MANAGERS.get(user_agent.split("/", 1)[0].strip().lower())
