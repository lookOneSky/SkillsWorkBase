from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from github_common import (
    DEFAULT_CONFIG,
    AccountConfig,
    WorkflowError,
    ensure_tools,
    load_account,
    main_guard,
    parse_repository,
    print_success,
    run_git,
    verify_account,
)


@dataclass(frozen=True)
class Plugin:
    directory: str
    repository: str
    branch: str | None = None


PLUGINS = (
    Plugin(
        directory="cesium-unreal",
        repository="https://github.com/lookOneSky/cesium-unreal.git",
        branch="v2.15.0",
    ),
    Plugin(
        directory="DasUnreal",
        repository="https://github.com/lookOneSky/DasUnreal.git",
    ),
    Plugin(
        directory="DasApplication",
        repository="https://github.com/lookOneSky/DasApplication.git",
    ),
    Plugin(
        directory="DasPixel",
        repository="https://github.com/lookOneSky/DasPixel.git",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把 Das UE 插件克隆到指定 Unreal Engine 工程的 Plugins 目录。"
    )
    parser.add_argument("project_dir", type=Path, help="包含 .uproject 的 UE 工程根目录")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只验证 UE 工程目录并显示克隆计划，不访问网络或写入文件",
    )
    return parser.parse_args()


def resolve_project_dir(value: Path) -> Path:
    project_dir = value.expanduser().resolve()
    if not project_dir.is_dir():
        raise WorkflowError(f"UE 工程目录不存在：{project_dir}")

    projects = sorted(project_dir.glob("*.uproject"))
    if not projects:
        raise WorkflowError(f"目录中没有 .uproject 文件：{project_dir}")
    if len(projects) > 1:
        names = ", ".join(project.name for project in projects)
        raise WorkflowError(f"目录中存在多个 .uproject 文件，无法确定工程：{names}")
    return project_dir


def assert_expected_origin(target: Path, plugin: Plugin, config: AccountConfig) -> None:
    result = run_git(
        ["remote", "get-url", "origin"],
        cwd=target,
        env=config.env,
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        raise WorkflowError(f"插件目录已存在但没有 origin：{target}")

    actual = (result.stdout or "").strip()
    try:
        actual_host, actual_slug = parse_repository(actual)
        expected_host, expected_slug = parse_repository(plugin.repository)
    except WorkflowError as exc:
        raise WorkflowError(f"插件目录的 origin 无法识别：{target} -> {actual}") from exc

    if (
        actual_host is None
        or expected_host is None
        or actual_host.casefold() != expected_host.casefold()
        or actual_slug.casefold() != expected_slug.casefold()
    ):
        raise WorkflowError(
            f"插件目录已存在且 origin 不匹配：{target}\n"
            f"当前：{actual}\n期望：{plugin.repository}"
        )


def revision(path: Path, ref: str, config: AccountConfig) -> str | None:
    result = run_git(
        ["rev-parse", "--verify", ref],
        cwd=path,
        env=config.env,
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip()


def assert_expected_branch(target: Path, plugin: Plugin, config: AccountConfig) -> None:
    if plugin.branch is None:
        return

    result = run_git(
        ["branch", "--show-current"],
        cwd=target,
        env=config.env,
        capture=True,
        check=False,
    )
    current = (result.stdout or "").strip() if result.returncode == 0 else ""
    if current == plugin.branch:
        return

    head = revision(target, "HEAD", config)
    candidates = (
        revision(target, f"refs/remotes/origin/{plugin.branch}", config),
        revision(target, f"refs/tags/{plugin.branch}^{{commit}}", config),
    )
    if head and head in candidates:
        return

    shown = current or "detached HEAD"
    raise WorkflowError(
        f"插件目录已存在，但当前检出为 {shown!r}，期望 {plugin.branch!r}：{target}"
    )


def configure_repository_proxy(target: Path, config: AccountConfig) -> None:
    proxy = config.env.get("HTTPS_PROXY") or config.env.get("HTTP_PROXY")
    if not proxy:
        return
    for key in ("http.proxy", "https.proxy"):
        run_git(["config", "--local", key, proxy], cwd=target, env=config.env)


def clone_plugin(
    plugins_dir: Path,
    plugin: Plugin,
    config: AccountConfig,
) -> bool:
    target = plugins_dir / plugin.directory
    if target.exists():
        if not target.is_dir():
            raise WorkflowError(f"插件目标已存在且不是目录：{target}")
        assert_expected_origin(target, plugin, config)
        assert_expected_branch(target, plugin, config)
        print(f"跳过：{plugin.directory} 已存在且来源匹配。")
        return False

    arguments = ["clone", "--recursive", "--single-branch"]
    if plugin.branch:
        arguments.extend(["--branch", plugin.branch])
    arguments.extend([plugin.repository, str(target)])
    run_git(
        arguments,
        cwd=plugins_dir,
        env=config.env,
        authenticated=True,
    )
    configure_repository_proxy(target, config)
    return True


def show_plan(project_dir: Path) -> None:
    plugins_dir = project_dir / "Plugins"
    print(f"UE 工程：{project_dir}")
    print(f"插件目录：{plugins_dir}")
    for plugin in PLUGINS:
        branch = plugin.branch or "默认主分支"
        print(f"- {plugin.directory}: {plugin.repository} ({branch})")


def action() -> None:
    args = parse_args()
    project_dir = resolve_project_dir(args.project_dir)
    if args.dry_run:
        show_plan(project_dir)
        return

    ensure_tools()
    config = load_account(DEFAULT_CONFIG)
    verify_account(config)

    plugins_dir = project_dir / "Plugins"
    if plugins_dir.exists() and not plugins_dir.is_dir():
        raise WorkflowError(f"Plugins 路径已存在且不是目录：{plugins_dir}")
    try:
        plugins_dir.mkdir(exist_ok=True)
    except OSError as exc:
        raise WorkflowError(f"无法创建 Plugins 目录 {plugins_dir}：{exc}") from exc

    cloned = 0
    for plugin in PLUGINS:
        if clone_plugin(plugins_dir, plugin, config):
            cloned += 1

    if cloned:
        print_success(f"已在 {plugins_dir} 克隆 {cloned} 个插件。")
    else:
        print_success(f"{plugins_dir} 中的插件均已存在，无需克隆。")


if __name__ == "__main__":
    main_guard(action)
