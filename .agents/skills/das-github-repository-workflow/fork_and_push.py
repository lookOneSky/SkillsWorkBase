from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any

from github_common import (
    DEFAULT_CONFIG,
    WorkflowError,
    assert_remote_compatible,
    configure_identity,
    ensure_remote,
    ensure_tools,
    find_git_root,
    get_repo_info,
    infer_repository,
    load_account,
    local_branch_exists,
    main_guard,
    parse_repository,
    print_success,
    remote_branch_exists,
    run,
    run_git,
    stage_and_commit,
    validate_branch,
    verify_account,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fork GitHub 仓库，在指定分支提交本地变化并推送到 fork。"
    )
    parser.add_argument("repository", nargs="?", help="上游 OWNER/REPO 或仓库 URL")
    parser.add_argument("--path", type=Path, default=Path.cwd(), help="本地 Git 仓库，默认当前目录")
    return parser.parse_args()


def wait_for_fork(slug: str, config: Any) -> dict[str, Any]:
    for _ in range(10):
        info = get_repo_info(slug, config, required=False)
        if info is not None:
            return info
        time.sleep(1)
    raise WorkflowError(f"fork 已请求，但 GitHub 暂未返回仓库 {slug}；请稍后重试。")


def action() -> None:
    args = parse_args()
    requested_path = args.path.expanduser().resolve()
    if not requested_path.is_dir():
        raise WorkflowError(f"目录不存在：{requested_path}")

    ensure_tools()
    config = load_account(DEFAULT_CONFIG)
    verify_account(config)
    root = find_git_root(requested_path, config.env)
    if root is None:
        raise WorkflowError("fork-and-push 需要已有本地 Git 仓库。")
    path = root

    if args.repository:
        specified_host, source_slug = parse_repository(args.repository)
        if specified_host and specified_host != config.host:
            raise WorkflowError(
                f"仓库主机 {specified_host!r} 与账号配置 host {config.host!r} 不一致。"
            )
    else:
        source_slug = infer_repository(path, config)

    source_info = get_repo_info(source_slug, config)
    source_slug = str(source_info.get("nameWithOwner") or source_slug)
    source_owner, source_name = source_slug.split("/", 1)
    if source_owner.casefold() == config.username.casefold():
        raise WorkflowError("上游仓库属于当前账号，无需 fork；请指定原始上游仓库。")
    default_ref = source_info.get("defaultBranchRef")
    default_branch = default_ref.get("name") if isinstance(default_ref, dict) else None
    if not isinstance(default_branch, str) or not default_branch:
        raise WorkflowError(f"无法确定上游仓库 {source_slug} 的默认分支。")

    branch = config.fork_branch.strip()
    validate_branch(branch, path, config.env)
    fork_remote = config.fork_remote.strip()
    upstream_remote = config.upstream_remote.strip()
    if not fork_remote or not upstream_remote or fork_remote == upstream_remote:
        raise WorkflowError("fork 与 upstream 远程名必须非空且互不相同。")

    fork_slug = f"{config.username}/{source_name}"
    assert_remote_compatible(path, upstream_remote, config.host, source_slug, config.env)
    assert_remote_compatible(path, fork_remote, config.host, fork_slug, config.env)

    fork_info = get_repo_info(fork_slug, config, required=False)
    if fork_info is None:
        run(["gh", "repo", "fork", source_slug, "--clone=false"], env=config.env)
        fork_info = wait_for_fork(fork_slug, config)
    parent = fork_info.get("parent") if isinstance(fork_info, dict) else None
    parent_slug = parent.get("nameWithOwner") if isinstance(parent, dict) else None
    if not fork_info.get("isFork") or not isinstance(parent_slug, str):
        raise WorkflowError(f"{fork_slug} 已存在，但不是可识别的 fork；不会覆盖。")
    if parent_slug.casefold() != source_slug.casefold():
        raise WorkflowError(
            f"{fork_slug} 已 fork 自 {parent_slug}，不是请求的 {source_slug}；不会覆盖。"
        )

    ensure_remote(path, upstream_remote, config.host, source_slug, config.env)
    ensure_remote(path, fork_remote, config.host, fork_slug, config.env)
    run_git(["fetch", upstream_remote], cwd=path, env=config.env, authenticated=True)
    run_git(["fetch", fork_remote], cwd=path, env=config.env, authenticated=True)

    if local_branch_exists(path, branch, config.env) or remote_branch_exists(
        path, fork_remote, branch, config.env
    ):
        raise WorkflowError(f"分支 {branch!r} 已存在；本 Skill 仅用于首次提交。")
    run_git(
        ["switch", "-c", branch, f"{upstream_remote}/{default_branch}"],
        cwd=path,
        env=config.env,
    )

    configure_identity(path, config)
    stage_and_commit(path, config.env)
    run_git(
        ["push", "-u", fork_remote, branch],
        cwd=path,
        env=config.env,
        authenticated=True,
    )
    print_success(f"已将 {source_slug} fork 到 {fork_slug}，并推送分支 {branch}。")


if __name__ == "__main__":
    main_guard(action)
