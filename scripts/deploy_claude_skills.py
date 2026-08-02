#!/usr/bin/env python3
"""将共享 Skill 与 Claude 专用 Skill 安装到当前用户目录。"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import uuid
from pathlib import Path


NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
ROOT = Path(__file__).resolve().parent.parent
SHARED_SOURCE_ROOT = ROOT / ".agents" / "skills"
CLAUDE_SOURCE_ROOT = ROOT / ".claude" / "skills"
TARGET_ROOTS = (
    ("Claude", Path.home() / ".claude" / "skills"),
    ("Codex", Path.home() / ".agents" / "skills"),
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def validate_name(name: str) -> None:
    if not NAME_RE.fullmatch(name):
        raise ValueError(f"非法 Skill 名称：{name}")


def declared_name(skill_file: Path) -> str:
    text = skill_file.read_text(encoding="utf-8-sig")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"无效的 YAML frontmatter：{skill_file}")
    names = [
        line.split(":", 1)[1].strip()
        for line in match.group(1).splitlines()
        if line.startswith("name:")
    ]
    if len(names) != 1:
        raise ValueError(f"YAML frontmatter 必须且只能包含一个 name：{skill_file}")
    validate_name(names[0])
    return names[0]


def remove_legacy_install(name: str, target_root: Path, product: str) -> None:
    if not name.startswith("das-"):
        return
    legacy = target_root / name.removeprefix("das-")
    legacy_skill = legacy / "SKILL.md"
    if not legacy_skill.is_file():
        return
    try:
        legacy_name = declared_name(legacy_skill)
    except (OSError, UnicodeError, ValueError):
        return
    if legacy_name != name:
        return
    remove(legacy)
    print(f"已清理 {product} 旧版无前缀目录：{legacy}")


def install_to(name: str, source: Path, target_root: Path, product: str) -> None:
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / name
    staging = target_root / f".{name}.tmp-{uuid.uuid4().hex}"
    backup = target_root / f".{name}.bak-{uuid.uuid4().hex}"
    source_resolved = source.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {item for item in names if item == "__pycache__" or item.endswith(".pyc")}
        if (
            product == "Claude"
            and Path(directory).resolve() == source_resolved
            and "agents" in names
        ):
            ignored.add("agents")
        return ignored

    shutil.copytree(source, staging, ignore=ignore)
    moved_old = False
    try:
        if target.exists() or target.is_symlink():
            target.rename(backup)
            moved_old = True
        staging.rename(target)
    except Exception:
        remove(staging)
        if moved_old and not target.exists():
            backup.rename(target)
        raise
    else:
        remove(backup)
    print(f"已安装到 {product}：{name} -> {target}")
    remove_legacy_install(name, target_root, product)


def locate_skill(name: str) -> tuple[Path, set[str]]:
    validate_name(name)
    matches = [
        (SHARED_SOURCE_ROOT / name, {product for product, _ in TARGET_ROOTS}),
        (CLAUDE_SOURCE_ROOT / name, {"Claude"}),
    ]
    matches = [
        (source, products)
        for source, products in matches
        if (source / "SKILL.md").is_file()
    ]
    if not matches:
        raise FileNotFoundError(f"未找到 Skill：{name}")
    if len(matches) > 1:
        raise ValueError(f"Skill 同时存在于共享与 Claude 专用目录：{name}")
    return matches[0]


def install(name: str) -> None:
    source, products = locate_skill(name)
    skill_file = source / "SKILL.md"
    metadata_name = declared_name(skill_file)
    if metadata_name != name:
        raise ValueError(
            f"Skill 目录名必须与 YAML name 一致：{name} != {metadata_name}"
        )
    for product, target_root in TARGET_ROOTS:
        if product in products:
            install_to(name, source, target_root, product)
            continue
        target = target_root / name
        if target.exists() or target.is_symlink():
            remove(target)
            print(f"已清理 {product} 不适用的 Skill：{name} -> {target}")
        remove_legacy_install(name, target_root, product)


def uninstall(name: str) -> None:
    validate_name(name)
    for product, target_root in TARGET_ROOTS:
        target = target_root / name
        if not (target.exists() or target.is_symlink()):
            print(f"{product} 未安装：{name}")
            remove_legacy_install(name, target_root, product)
            continue
        remove(target)
        print(f"已从 {product} 卸载：{name} -> {target}")
        remove_legacy_install(name, target_root, product)


def available_skills() -> list[str]:
    sources: dict[str, Path] = {}
    for source_root in (SHARED_SOURCE_ROOT, CLAUDE_SOURCE_ROOT):
        if not source_root.is_dir():
            continue
        for path in source_root.iterdir():
            if not (path / "SKILL.md").is_file():
                continue
            if path.name in sources:
                raise ValueError(f"Skill 同时存在于共享与 Claude 专用目录：{path.name}")
            metadata_name = declared_name(path / "SKILL.md")
            if metadata_name != path.name:
                raise ValueError(
                    f"Skill 目录名必须与 YAML name 一致：{path.name} != {metadata_name}"
                )
            sources[path.name] = path
    if not sources:
        raise FileNotFoundError(
            f"未找到 Skill 目录：{SHARED_SOURCE_ROOT} 或 {CLAUDE_SOURCE_ROOT}"
        )
    return sorted(sources)


def read_key() -> str:
    if sys.platform == "win32" and sys.stdin.isatty():
        import msvcrt

        while True:
            key = msvcrt.getwch()
            if key in {"\x00", "\xe0"}:
                msvcrt.getwch()
                continue
            print(key)
            return key
    return input().strip()


def choose_action() -> str | None:
    print("Claude/Codex 用户级 Skill 部署工具")
    print(f"共享 Skill 源：{SHARED_SOURCE_ROOT}")
    print(f"Claude 专用 Skill 源：{CLAUDE_SOURCE_ROOT}")
    for product, target_root in TARGET_ROOTS:
        print(f"{product} 目标目录：{target_root}")
    print("[1] 安装或更新全部")
    print("[2] 卸载全部")
    print("[0] 退出")
    while True:
        print("请选择操作：", end="", flush=True)
        choice = read_key().lower()
        if choice in {"1", "i"}:
            return "install"
        if choice in {"2", "u"}:
            return "uninstall"
        if choice in {"0", "q"}:
            return None
        print("无效按键，请按 1、2 或 0。")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skills", nargs="*", help="Skill 名称；省略时处理全部")
    parser.add_argument(
        "--action",
        choices=("install", "uninstall"),
        help="直接指定操作；省略时显示按键菜单",
    )
    args = parser.parse_args()

    action = args.action or choose_action()
    if action is None:
        print("已退出，未做更改。")
        return 0

    names = args.skills or available_skills()
    if not names:
        parser.error("没有找到可处理的 Skill")
    operation = install if action == "install" else uninstall
    for name in names:
        operation(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
