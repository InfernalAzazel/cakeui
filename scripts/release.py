#!/usr/bin/env python3
"""一键改版本号：把 CakeUI 的所有版本声明对齐到同一个新值。

版本号在这个仓库里散落在 9 个地方，手改必然漏一两处，而漏掉的那个往往正是
`uv.lock` 或者桥接产物这类"看不见"的位置，要等到发版流程的半途才炸。这个脚本
把它们集中到一张表里，改完顺手把派生文件重新生成，最后打上标签。

用法::

    python scripts/release.py 0.2.0            # 改文件 + 重新生成 + 提交 + 打标签
    python scripts/release.py 0.2.0 --dry-run  # 只说要改什么
    python scripts/release.py 0.3.0rc1         # 预发布版本也认

刻意不依赖任何第三方库：这个脚本要能在 CI 和裸机上直接跑。

## 为什么不用 sed 全量替换

`cli/src/cakeui_cli/templates/_base_/pyproject.toml` 里也有一个 `0.1.0`，那是
**用户新建项目自己的版本号**，跟 CakeUI 无关。全量替换会把生成出来的项目染成
CakeUI 的版本号。所以这里只改白名单里的位置，并且每处都带上下文匹配。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 版本号必须能被 PyPI 和 semver 同时接受：预发布用 0.3.0rc1 这种形式。
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)[0-9]+)?$")


@dataclass(frozen=True)
class Target:
    """一处版本声明。

    ``pattern`` 必须只匹配一个位置：多余匹配会在写入前被检测出来，避免误伤
    同名内容（比如模板里的版本号）。
    """

    path: Path
    pattern: re.Pattern[str]
    template: str
    label: str
    # 出现次数必须完全等于这个值，多一处少一处都当错误处理。
    count: int = 1


def targets(new: str) -> list[Target]:
    """所有需要改的位置。顺序只是为了日志好读。"""
    return [
        Target(
            ROOT / "python" / "pyproject.toml",
            re.compile(r'(?m)^version = "([^"]+)"$'),
            f'version = "{new}"',
            "运行时版本",
        ),
        Target(
            ROOT / "cli" / "pyproject.toml",
            re.compile(r'(?m)^version = "([^"]+)"$'),
            f'version = "{new}"',
            "CLI 版本",
        ),
        Target(
            ROOT / "cli" / "pyproject.toml",
            re.compile(r'(?m)^    "cakeui>=([^"]+)",$'),
            f'    "cakeui>={new}",',
            "CLI 对运行时的依赖下限",
        ),
        Target(
            ROOT / "js" / "package.json",
            re.compile(r'(?m)^  "version": "([^"]+)",$'),
            f'  "version": "{new}",',
            "前端包版本",
        ),
        Target(
            ROOT / "js" / "src" / "index.ts",
            re.compile(r'(?m)^const VERSION = "([^"]+)";$'),
            f'const VERSION = "{new}";',
            "桥接协议版本",
        ),
        Target(
            ROOT / "python" / "src" / "cakeui" / "__init__.py",
            re.compile(r'(?m)^    __version__ = "([^"]+)"$'),
            f'    __version__ = "{new}"',
            "无包元数据时的兜底",
        ),
        Target(
            ROOT / "cli" / "src" / "cakeui_cli" / "__init__.py",
            re.compile(r'(?m)^__version__ = "([^"]+)"$'),
            f'__version__ = "{new}"',
            "CLI 兜底",
        ),
        Target(
            ROOT / "cli" / "src" / "cakeui_cli" / "scaffold.py",
            re.compile(r'(?m)^    cakeui_requirement: str = ">=([^"]+)",$'),
            f'    cakeui_requirement: str = ">={new}",',
            "脚手架默认依赖下限",
        ),
        Target(
            ROOT / "cli" / "tests" / "test_cli.py",
            re.compile(r"""(?m)^    assert '"cakeui>=([^"]+)"' in pyproject$"""),
            f"""    assert '"cakeui>={new}"' in pyproject""",
            "脚手架测试断言",
        ),
    ]


def current_version() -> str:
    """以运行时包的 pyproject 为准。"""
    data = tomllib.loads((ROOT / "python" / "pyproject.toml").read_text("utf-8"))
    return data["project"]["version"]


def apply(new: str, *, dry_run: bool) -> list[tuple[Target, str]]:
    """改文件，返回 (目标, 旧版本) 列表供日志用。"""
    changed: list[tuple[Target, str]] = []

    for target in targets(new):
        try:
            text = target.path.read_text("utf-8")
        except OSError as exc:
            sys.exit(f"读不了 {target.path}：{exc}")

        matches = target.pattern.findall(text)
        if len(matches) != target.count:
            # 匹配数不对时绝不写入：多一个就是误伤，少一个就是结构变了。
            sys.exit(
                f"{target.path.relative_to(ROOT)} 里 {target.label} 应该匹配 "
                f"{target.count} 处，实际 {len(matches)} 处。文件结构变了，先改脚本。"
            )

        old = matches[0] if isinstance(matches[0], str) else matches[0][0]
        if old == new:
            continue

        updated = target.pattern.sub(target.template, text)
        if not dry_run:
            target.path.write_text(updated, "utf-8")
        changed.append((target, old))

    return changed


def run(argv: list[str], what: str, *, dry_run: bool) -> None:
    """跑一条命令，失败就让整个流程停下。"""
    print(f"› {what}：{' '.join(argv)}")
    if dry_run:
        return
    completed = subprocess.run(argv, cwd=ROOT)
    if completed.returncode != 0:
        sys.exit(f"{what} 失败（退出码 {completed.returncode}）。")


def scaffold_notes(new: str, *, dry_run: bool) -> None:
    """放一个发布说明的空壳，免得发版时那一步悄悄回退。

    只在文件不存在时创建：已经写好的说明不能被覆盖。模板里的标题就是工作流预期
    的分节，写的时候照着填即可。
    """
    path = ROOT / ".github" / "release-notes" / f"v{new}.md"
    if path.is_file():
        print(f"› 发布说明已存在：{path.relative_to(ROOT)}")
        return

    print(f"› 新建发布说明：{path.relative_to(ROOT)}")
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "## 新特性\n\n- \n\n## 修复\n\n- \n\n## 升级须知\n\n",
        "utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="把 CakeUI 的所有版本声明改到同一个新值。",
    )
    parser.add_argument("version", help="新版本号，例如 0.2.0 或 0.3.0rc1。")
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印会改哪些文件，不写入也不提交。"
    )
    parser.add_argument("--no-commit", action="store_true", help="改完文件就停，不提交、不打标签。")
    parser.add_argument("--no-tag", action="store_true", help="提交但不打标签。")
    args = parser.parse_args(argv)

    new = args.version.removeprefix("v")
    if not VERSION_RE.match(new):
        sys.exit(f"版本号 {args.version!r} 不合法，期望 0.2.0 / 0.3.0rc1 这种形式。")

    old = current_version()
    if old == new:
        sys.exit(f"当前已经是 {new} 了，没有要改的。")

    print(f"版本 {old} -> {new}")

    changed = apply(new, dry_run=args.dry_run)
    for target, previous in changed:
        print(f"  {target.path.relative_to(ROOT)}  {previous} -> {new}  ({target.label})")
    if not changed:
        print("  没有文件需要改。")

    # 派生文件：lockfile 和桥接产物都带着版本号，必须跟着重新生成。
    run(["uv", "lock"], "刷新 uv.lock", dry_run=args.dry_run)
    run(["npm", "--prefix", "js", "run", "build"], "重建桥接产物", dry_run=args.dry_run)

    # 发布说明必须落在标签指向的提交里：工作流从 tag 的 tree 读这个文件，晚一步
    # 提交就会读不到，Release 正文悄悄退化成自动生成的说明。
    scaffold_notes(new, dry_run=args.dry_run)

    if args.dry_run:
        print("\n--dry-run：没有写入任何文件。")
        return 0

    if args.no_commit:
        print("\n--no-commit：文件已改好，没有提交。")
        return 0

    run(["git", "add", "-A"], "暂存改动", dry_run=False)
    run(
        ["git", "commit", "-m", f"chore(release): {new}"],
        "提交",
        dry_run=False,
    )

    if not args.no_tag:
        tag = f"v{new}"
        existing = subprocess.run(
            ["git", "tag", "--list", tag], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip()
        if existing:
            print(f"\n标签 {tag} 已存在，跳过。")
        else:
            run(["git", "tag", "-a", tag, "-m", f"cakeui {new}"], f"打标签 {tag}", dry_run=False)
            print(f"\n推上去即可发版：git push && git push origin {tag}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
