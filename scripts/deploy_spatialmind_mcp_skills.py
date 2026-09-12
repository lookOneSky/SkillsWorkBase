#!/usr/bin/env python3
"""将 MCP 专用 Skill 安装或更新到 SpatialMind。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import deploy_claude_skills as skill_deployer


ROOT = Path(__file__).resolve().parent.parent
MCP_SOURCE_ROOT = ROOT / ".agents" / "skills" / "MCP"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def available_skills() -> list[str]:
    if not MCP_SOURCE_ROOT.is_dir():
        raise FileNotFoundError(f"未找到 MCP Skill 目录：{MCP_SOURCE_ROOT}")
    return sorted(
        path.name
        for path in MCP_SOURCE_ROOT.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )


def install(name: str, target_root: Path) -> None:
    skill_deployer.validate_name(name)
    source = MCP_SOURCE_ROOT / name
    skill_file = source / "SKILL.md"
    if not skill_file.is_file():
        raise skill_deployer.SkillMissing(f"未找到 MCP Skill：{name}")

    metadata_name = skill_deployer.declared_name(skill_file)
    if metadata_name != name:
        raise skill_deployer.SkillInvalid(
            f"Skill 目录名必须与 YAML name 一致：{name} != {metadata_name}"
        )
    skill_deployer.install_to(
        name,
        source,
        target_root,
        "SpatialMind MCP",
        ignored_root_names=frozenset({f"{name}.zip"}),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skills", nargs="*", help="MCP Skill 名称；省略时部署全部")
    parser.add_argument(
        "--target-dir",
        type=Path,
        help="SpatialMind Skill 目标目录；默认自动解析",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_root = (
        args.target_dir.expanduser().resolve()
        if args.target_dir
        else skill_deployer.spatial_mind_skills_dir()
    )
    try:
        names = args.skills or available_skills()
    except (FileNotFoundError, OSError) as error:
        print(f"SpatialMind MCP Skill 部署失败：{error}", file=sys.stderr)
        return 1

    if not names:
        print("没有找到可部署的 MCP Skill，未做更改。")
        return 0

    succeeded: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    for name in names:
        try:
            install(name, target_root)
        except skill_deployer.SkillMissing as error:
            skipped.append(name)
            print(f"已跳过（源中不存在）：{error}")
        except (
            skill_deployer.SkillInvalid,
            ValueError,
            OSError,
            UnicodeError,
        ) as error:
            failed.append(f"{name}：{error}")
            sys.stdout.flush()
            print(f"已跳过（处理失败）：{name}：{error}", file=sys.stderr)
        else:
            succeeded.append(name)

    print(
        f"SpatialMind MCP 汇总：成功 {len(succeeded)} 个 / "
        f"跳过 {len(skipped)} 个 / 失败 {len(failed)} 个"
    )
    for failure in failed:
        print(f"失败：{failure}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
