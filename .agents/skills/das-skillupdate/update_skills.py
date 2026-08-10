#!/usr/bin/env python3
"""同步 SkillsWorkBase，并重新部署当前用户的 Das Skills。"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPOSITORY_URL = "https://github.com/lookOneSky/SkillsWorkBase.git"
REPOSITORY_DIR = Path.home() / "SkillsWorkBase"
GIT_PROXY = "http://127.0.0.1:10808"
DEPLOY_SCRIPT = Path("scripts") / "deploy_claude_skills.py"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def run(command: list[str], *, cwd: Path | None = None) -> None:
    print(f"> {subprocess.list2cmdline(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def configure_git_proxy(proxy: str) -> None:
    run(["git", "config", "--global", "http.proxy", proxy])
    run(["git", "config", "--global", "https.proxy", proxy])


def sync_repository(repository_url: str, repository_dir: Path) -> None:
    if not repository_dir.exists():
        repository_dir.parent.mkdir(parents=True, exist_ok=True)
        print(f"正在克隆 SkillsWorkBase：{repository_dir}")
        run(["git", "clone", repository_url, str(repository_dir)])
        return

    if not repository_dir.is_dir() or not (repository_dir / ".git").is_dir():
        raise RuntimeError(f"目标已存在但不是 Git 仓库：{repository_dir}")

    print(f"正在更新 SkillsWorkBase：{repository_dir}")
    run(["git", "pull", "--ff-only"], cwd=repository_dir)


def deploy(repository_dir: Path) -> None:
    deploy_script = repository_dir / DEPLOY_SCRIPT
    if not deploy_script.is_file():
        raise FileNotFoundError(f"未找到部署入口：{deploy_script}")

    print("正在非交互部署 Claude/Codex Skills")
    run(
        [sys.executable, str(deploy_script), "--action", "install"],
        cwd=repository_dir,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-url", default=REPOSITORY_URL, help=argparse.SUPPRESS)
    parser.add_argument(
        "--repo-dir",
        type=Path,
        default=REPOSITORY_DIR,
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--proxy", default=GIT_PROXY, help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository_dir = args.repo_dir.expanduser().resolve()
    try:
        configure_git_proxy(args.proxy)
        sync_repository(args.repo_url, repository_dir)
        deploy(repository_dir)
    except (FileNotFoundError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Das Skill 更新失败：{error}", file=sys.stderr)
        return 1
    print("Das Skills 已更新并完成部署。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
