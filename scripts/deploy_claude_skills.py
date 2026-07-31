#!/usr/bin/env python3
"""将 .agents/skills 中的 Skill 部署到 .claude/skills。"""

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
TARGET_ROOT = ROOT / ".claude" / "skills"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def deploy(name: str) -> None:
    if not NAME_RE.fullmatch(name):
        raise ValueError(f"非法 Skill 名称：{name}")

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
    print(f"已部署：{name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skills", nargs="*", help="Skill 名称；省略时部署全部")
    args = parser.parse_args()

    names = args.skills or sorted(
        path.name for path in SOURCE_ROOT.iterdir() if (path / "SKILL.md").is_file()
    )
    if not names:
        parser.error("没有找到可部署的 Skill")
    for name in names:
        deploy(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
