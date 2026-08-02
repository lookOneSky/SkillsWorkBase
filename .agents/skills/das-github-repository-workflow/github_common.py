from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse


DEFAULT_CONFIG = Path(__file__).with_name("github-account.json")
DEFAULT_PROXY = "http://127.0.0.1:10808"


class WorkflowError(RuntimeError):
    pass


@dataclass(frozen=True)
class AccountConfig:
    host: str
    username: str
    git_name: str
    git_email: str
    create_remote: str
    fork_remote: str
    upstream_remote: str
    fork_branch: str
    env: dict[str, str]


def _string(raw: Mapping[str, Any], key: str, default: str = "") -> str:
    value = raw.get(key, default)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise WorkflowError(f"配置项 {key!r} 必须是字符串。")
    return value.strip()


def load_account(path: Path) -> AccountConfig:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise WorkflowError(
            f"找不到账号配置：{path}\n"
            "请直接填写 Skill 同级的 github-account.json。"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"无法读取账号配置 {path}：{exc}") from exc
    if not isinstance(raw, dict):
        raise WorkflowError("账号配置的 JSON 顶层必须是对象。")

    host = _string(raw, "host", "github.com").lower()
    username = _string(raw, "username")
    if not host or "/" in host or "://" in host:
        raise WorkflowError("host 必须是主机名，例如 github.com。")
    if not username or username == "your-github-username":
        raise WorkflowError("请在账号 JSON 中填写 username。")

    token_env = _string(raw, "token_env", "GITHUB_TOKEN")
    token = os.environ.get(token_env, "") if token_env else ""
    token = token or _string(raw, "token")

    env = os.environ.copy()
    env["GH_PROMPT_DISABLED"] = "1"
    env["GH_HOST"] = host
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    if token:
        env["GH_TOKEN"] = token

    proxy = _string(raw, "proxy", DEFAULT_PROXY)
    if proxy:
        env["HTTP_PROXY"] = proxy
        env["HTTPS_PROXY"] = proxy
        env["http_proxy"] = proxy
        env["https_proxy"] = proxy

    return AccountConfig(
        host=host,
        username=username,
        git_name=_string(raw, "git_name"),
        git_email=_string(raw, "git_email"),
        create_remote=_string(raw, "create_remote", "origin"),
        fork_remote=_string(raw, "fork_remote", "fork"),
        upstream_remote=_string(raw, "upstream_remote", "upstream"),
        fork_branch=_string(raw, "fork_branch", "Jiangs"),
        env=env,
    )


def ensure_tools() -> None:
    missing = [name for name in ("git", "gh") if shutil.which(name) is None]
    if missing:
        raise WorkflowError(f"缺少命令：{', '.join(missing)}。请先安装并加入 PATH。")


def run(
    command: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    printable = subprocess.list2cmdline([str(item) for item in command])
    print(f"> {printable}", flush=True)
    result = subprocess.run(
        [str(item) for item in command],
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env is not None else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=False,
    )
    if check and result.returncode != 0:
        details = "\n".join(
            part.strip() for part in (result.stdout or "", result.stderr or "") if part.strip()
        )
        suffix = f"\n{details}" if details else ""
        raise WorkflowError(f"命令失败（退出码 {result.returncode}）：{printable}{suffix}")
    return result


def run_git(
    arguments: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    capture: bool = False,
    check: bool = True,
    authenticated: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = ["git"]
    if authenticated:
        command.extend(
            [
                "-c",
                "credential.helper=",
                "-c",
                "credential.helper=!gh auth git-credential",
            ]
        )
    command.extend(arguments)
    return run(command, cwd=cwd, env=env, capture=capture, check=check)


def verify_account(config: AccountConfig) -> None:
    result = run(
        ["gh", "api", "--hostname", config.host, "user", "--jq", ".login"],
        env=config.env,
        capture=True,
    )
    actual = (result.stdout or "").strip()
    if actual.casefold() != config.username.casefold():
        raise WorkflowError(
            f"账号不匹配：JSON 配置为 {config.username!r}，当前认证账号为 {actual!r}。"
        )


def find_git_root(path: Path, env: Mapping[str, str]) -> Optional[Path]:
    result = run_git(
        ["rev-parse", "--show-toplevel"], cwd=path, env=env, capture=True, check=False
    )
    if result.returncode != 0:
        return None
    return Path((result.stdout or "").strip()).resolve()


def configure_identity(path: Path, config: AccountConfig) -> None:
    if config.git_name:
        run_git(["config", "--local", "user.name", config.git_name], cwd=path, env=config.env)
    if config.git_email:
        run_git(
            ["config", "--local", "user.email", config.git_email], cwd=path, env=config.env
        )

    for key in ("user.name", "user.email"):
        result = run_git(["config", "--get", key], cwd=path, env=config.env, capture=True, check=False)
        if result.returncode != 0 or not (result.stdout or "").strip():
            raise WorkflowError(f"Git 缺少 {key}；请在账号 JSON 中配置对应值。")


def validate_branch(branch: str, path: Path, env: Mapping[str, str]) -> None:
    if not branch:
        raise WorkflowError("分支名不能为空。")
    result = run_git(
        ["check-ref-format", "--branch", branch], cwd=path, env=env, capture=True, check=False
    )
    if result.returncode != 0:
        raise WorkflowError(f"无效的 Git 分支名：{branch!r}。")


def ensure_create_branch(path: Path, branch: str, env: Mapping[str, str]) -> None:
    validate_branch(branch, path, env)
    has_head = run_git(
        ["rev-parse", "--verify", "HEAD"], cwd=path, env=env, capture=True, check=False
    ).returncode == 0
    if not has_head:
        run_git(["symbolic-ref", "HEAD", f"refs/heads/{branch}"], cwd=path, env=env)
        return

    current = run_git(
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=path,
        env=env,
        capture=True,
        check=False,
    )
    if current.returncode != 0:
        raise WorkflowError("当前仓库处于 detached HEAD，无法安全切换到 main。")
    current_name = (current.stdout or "").strip()
    if current_name == branch:
        return

    target_exists = run_git(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=path,
        env=env,
        check=False,
    ).returncode == 0
    if target_exists:
        run_git(["switch", branch], cwd=path, env=env)
    else:
        run_git(["branch", "-m", branch], cwd=path, env=env)


def stage_and_commit(path: Path, env: Mapping[str, str]) -> None:
    run_git(["add", "-A"], cwd=path, env=env)
    diff = run_git(["diff", "--cached", "--quiet"], cwd=path, env=env, check=False)
    if diff.returncode not in (0, 1):
        raise WorkflowError("无法检查暂存区状态。")
    if diff.returncode == 1:
        run_git(["commit", "-m", "init"], cwd=path, env=env)
    else:
        run_git(["commit", "--allow-empty", "-m", "init"], cwd=path, env=env)


def parse_repository(value: str) -> tuple[Optional[str], str]:
    candidate = value.strip()
    if not candidate:
        raise WorkflowError("仓库名不能为空。")

    scp_match = re.fullmatch(r"(?:[^@/]+@)?([^:/]+):([^/]+)/(.+)", candidate)
    if scp_match and "://" not in candidate:
        host = scp_match.group(1).lower()
        slug = f"{scp_match.group(2)}/{scp_match.group(3)}"
    elif "://" in candidate:
        parsed = urlparse(candidate)
        host = (parsed.hostname or "").lower()
        slug = parsed.path.strip("/")
    else:
        host = None
        slug = candidate.strip("/")

    if slug.endswith(".git"):
        slug = slug[:-4]
    parts = slug.split("/")
    if len(parts) != 2 or not all(parts):
        raise WorkflowError(f"无法识别 GitHub 仓库：{value!r}；请使用 OWNER/REPO 或仓库 URL。")
    return host, f"{parts[0]}/{parts[1]}"


def repository_url(host: str, slug: str) -> str:
    return f"https://{host}/{slug}.git"


def get_remote(path: Path, remote: str, env: Mapping[str, str]) -> Optional[str]:
    result = run_git(
        ["remote", "get-url", remote], cwd=path, env=env, capture=True, check=False
    )
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip()


def assert_remote_compatible(
    path: Path, remote: str, host: str, slug: str, env: Mapping[str, str]
) -> None:
    actual = get_remote(path, remote, env)
    if actual is None:
        return
    try:
        actual_host, actual_slug = parse_repository(actual)
    except WorkflowError as exc:
        raise WorkflowError(f"远程 {remote!r} 已存在且无法识别：{actual}") from exc
    actual_host = (actual_host or host).lower()
    if actual_host != host.lower() or actual_slug.casefold() != slug.casefold():
        raise WorkflowError(
            f"远程 {remote!r} 已指向 {actual!r}，不会自动覆盖；期望 {host}/{slug}。"
        )


def ensure_remote(
    path: Path, remote: str, host: str, slug: str, env: Mapping[str, str]
) -> None:
    assert_remote_compatible(path, remote, host, slug, env)
    if get_remote(path, remote, env) is None:
        run_git(["remote", "add", remote, repository_url(host, slug)], cwd=path, env=env)


def get_repo_info(
    slug: str, config: AccountConfig, *, required: bool = True
) -> Optional[dict[str, Any]]:
    result = run(
        [
            "gh",
            "repo",
            "view",
            slug,
            "--json",
            "name,nameWithOwner,defaultBranchRef,isFork,parent",
        ],
        env=config.env,
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        if required:
            details = (result.stderr or result.stdout or "").strip()
            raise WorkflowError(f"无法读取仓库 {slug!r}。{(' ' + details) if details else ''}")
        return None
    try:
        value = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"GitHub CLI 返回了无效 JSON：{exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowError("GitHub CLI 返回的仓库信息格式无效。")
    return value


def infer_repository(path: Path, config: AccountConfig) -> str:
    for remote in (config.upstream_remote, "origin", config.fork_remote):
        value = get_remote(path, remote, config.env)
        if not value:
            continue
        host, slug = parse_repository(value)
        if host and host.lower() != config.host:
            continue
        info = get_repo_info(slug, config, required=False)
        if not info:
            continue
        if info.get("isFork") and isinstance(info.get("parent"), dict):
            parent = info["parent"].get("nameWithOwner")
            if isinstance(parent, str) and parent:
                return parent
        return str(info.get("nameWithOwner") or slug)
    raise WorkflowError("无法从远程推断上游仓库；请显式传入 OWNER/REPO。")


def local_branch_exists(path: Path, branch: str, env: Mapping[str, str]) -> bool:
    return run_git(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=path,
        env=env,
        check=False,
    ).returncode == 0


def remote_branch_exists(
    path: Path, remote: str, branch: str, env: Mapping[str, str]
) -> bool:
    return run_git(
        ["show-ref", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}"],
        cwd=path,
        env=env,
        check=False,
    ).returncode == 0


def print_success(message: str) -> None:
    print(f"\n完成：{message}")


def main_guard(action: Any) -> None:
    try:
        action()
    except KeyboardInterrupt:
        print("\n已取消。")
        raise SystemExit(130)
    except WorkflowError as exc:
        print(f"\n错误：{exc}")
        raise SystemExit(1)
