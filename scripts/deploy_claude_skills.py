#!/usr/bin/env python3
"""将 .agents/skills 中的 Skill 安装到当前用户的 Claude 配置目录。"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import uuid
from pathlib import Path


NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = ROOT / ".agents" / "skills"
TARGET_ROOT = Path.home() / ".claude" / "skills"

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


def install(name: str) -> None:
    validate_name(name)
    source = SOURCE_ROOT / name
    if not (source / "SKILL.md").is_file():
        raise FileNotFoundError(f"缺少源文件：{source / 'SKILL.md'}")

    TARGET_ROOT.mkdir(parents=True, exist_ok=True)
    target = TARGET_ROOT / name
    staging = TARGET_ROOT / f".{name}.tmp-{uuid.uuid4().hex}"
    backup = TARGET_ROOT / f".{name}.bak-{uuid.uuid4().hex}"
    source_resolved = source.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {item for item in names if item == "__pycache__" or item.endswith(".pyc")}
        if Path(directory).resolve() == source_resolved and "agents" in names:
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
    print(f"已安装：{name} -> {target}")


def uninstall(name: str) -> None:
    validate_name(name)
    target = TARGET_ROOT / name
    if not (target.exists() or target.is_symlink()):
        print(f"未安装：{name}")
        return
    remove(target)
    print(f"已卸载：{name} -> {target}")


def available_skills() -> list[str]:
    if not SOURCE_ROOT.is_dir():
        raise FileNotFoundError(f"未找到 Skill 目录：{SOURCE_ROOT}")
    return sorted(
        path.name for path in SOURCE_ROOT.iterdir() if (path / "SKILL.md").is_file()
    )


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
    print("Claude 用户级 Skill 部署工具")
    print(f"目标目录：{TARGET_ROOT}")
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
