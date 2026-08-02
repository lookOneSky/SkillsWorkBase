from __future__ import annotations

import argparse
import re
from pathlib import Path

from github_common import (
    DEFAULT_CONFIG,
    WorkflowError,
    assert_remote_compatible,
    configure_identity,
    ensure_create_branch,
    ensure_remote,
    ensure_tools,
    find_git_root,
    get_repo_info,
    load_account,
    main_guard,
    print_success,
    run,
    run_git,
    stage_and_commit,
    verify_account,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把本地目录创建为 GitHub 私有仓库，提交并推送到 main。"
    )
    parser.add_argument("--path", type=Path, default=Path.cwd(), help="本地目录，默认当前目录")
    parser.add_argument("--name", help="GitHub 仓库名，默认使用目录名")
    parser.add_argument("--description", default="", help="GitHub 仓库描述")
    return parser.parse_args()


def action() -> None:
    args = parse_args()
    path = args.path.expanduser().resolve()
    if not path.is_dir():
        raise WorkflowError(f"目录不存在：{path}")

    ensure_tools()
    config = load_account(DEFAULT_CONFIG)
    verify_account(config)

    repo_name = (args.name or path.name).strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", repo_name) or repo_name in {".", ".."}:
        raise WorkflowError("仓库名只能包含英文字母、数字、点、连字符和下划线。")
    slug = f"{config.username}/{repo_name}"
    if get_repo_info(slug, config, required=False) is not None:
        raise WorkflowError(f"GitHub 仓库 {slug} 已存在；本脚本不会覆盖已有仓库。")

    root = find_git_root(path, config.env)
    if root is not None and root != path:
        raise WorkflowError(
            f"指定目录位于已有 Git 仓库 {root} 内；请传入仓库根目录，避免误提交父目录。"
        )
    if root is None:
        run_git(["init", "-b", "main"], cwd=path, env=config.env)
    elif run_git(
        ["rev-parse", "--verify", "HEAD"],
        cwd=path,
        env=config.env,
        capture=True,
        check=False,
    ).returncode == 0:
        raise WorkflowError("当前仓库已有提交；本 Skill 仅用于首次提交。")

    remote = config.create_remote.strip()
    if not remote:
        raise WorkflowError("远程名不能为空。")
    assert_remote_compatible(path, remote, config.host, slug, config.env)
    ensure_create_branch(path, "main", config.env)
    configure_identity(path, config)
    stage_and_commit(path, config.env)

    command = ["gh", "repo", "create", slug, "--private"]
    if args.description:
        command.extend(["--description", args.description])
    run(command, env=config.env)
    ensure_remote(path, remote, config.host, slug, config.env)
    run_git(
        ["push", "-u", remote, "main"],
        cwd=path,
        env=config.env,
        authenticated=True,
    )
    print_success(f"已创建私有仓库 {slug} 并推送 main。")


if __name__ == "__main__":
    main_guard(action)
