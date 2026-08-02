from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any


SCHEMA_URL = "https://json.schemastore.org/claude-code-settings.json"
ALLOWED_TOOLS = ("Bash", "PowerShell", "Read", "Edit", "Write", "Glob", "Grep")
PROXY_URL = "http://127.0.0.1:10808"
PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY")
CODEX_SET_HEADER_RE = re.compile(
    r"^\s*\[\s*shell_environment_policy\s*\.\s*set\s*\]\s*(?:#.*)?$"
)
TOML_TABLE_HEADER_RE = re.compile(r"^\s*\[{1,2}.*\]{1,2}\s*(?:#.*)?$")
CODEX_PROXY_KEY_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<key>HTTP_PROXY|HTTPS_PROXY|\"HTTP_PROXY\"|"
    r"\"HTTPS_PROXY\"|'HTTP_PROXY'|'HTTPS_PROXY')[ \t]*=.*$"
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Configure Claude permissions and proxy, or Codex proxy only."
    )
    parser.add_argument("target", choices=("claude", "codex"))
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        help=(
            "Claude project root, or Codex home. Defaults to the current directory "
            "for Claude and CODEX_HOME/~/.codex for Codex."
        ),
    )
    return parser.parse_args()


def require_directory(path: Path, label: str, *, create: bool = False) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.exists() and not resolved.is_dir():
        raise ValueError(f"{label}不是目录：{resolved}")
    if not resolved.exists():
        if not create:
            raise ValueError(f"{label}不存在：{resolved}")
        resolved.mkdir(parents=True)
    return resolved


def claude_settings_path(root: Path | None) -> Path:
    project_root = require_directory(root or Path.cwd(), "项目目录")
    return project_root / ".claude" / "settings.local.json"


def codex_config_path(root: Path | None) -> Path:
    if root is None:
        configured_home = os.environ.get("CODEX_HOME")
        root = Path(configured_home) if configured_home else Path.home() / ".codex"
    codex_home = require_directory(root, "Codex 配置目录", create=True)
    return codex_home / "config.toml"


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if not path.is_file():
        raise ValueError(f"设置路径不是文件：{path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"设置文件不是有效 JSON：{path}（第 {exc.lineno} 行，第 {exc.colno} 列）"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(f"设置文件的顶层必须是 JSON 对象：{path}")
    return data


def load_toml(path: Path) -> str:
    if not path.exists():
        return ""
    if not path.is_file():
        raise ValueError(f"配置路径不是文件：{path}")
    return path.read_text(encoding="utf-8-sig")


def require_object(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.setdefault(key, {})
    if not isinstance(value, dict):
        raise ValueError(f'设置字段 "{key}" 必须是对象')
    return value


def require_list(parent: dict[str, Any], key: str) -> list[Any]:
    value = parent.setdefault(key, [])
    if not isinstance(value, list):
        raise ValueError(f'设置字段 "permissions.{key}" 必须是数组')
    return value


def append_missing(items: list[Any], additions: tuple[str, ...]) -> None:
    for item in additions:
        if item not in items:
            items.append(item)


def update_claude_settings(data: dict[str, Any]) -> None:
    data.setdefault("$schema", SCHEMA_URL)
    data["skipDangerousModePermissionPrompt"] = True

    environment = require_object(data, "env")
    for variable in PROXY_VARIABLES:
        environment[variable] = PROXY_URL

    permissions = require_object(data, "permissions")
    permissions["defaultMode"] = "bypassPermissions"
    append_missing(require_list(permissions, "allow"), ALLOWED_TOOLS)

    temp_claude = str(Path(tempfile.gettempdir()).resolve() / "claude")
    append_missing(require_list(permissions, "additionalDirectories"), (temp_claude,))


def parse_toml(text: str, path: Path | None = None) -> dict[str, Any]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        location = f"：{path}" if path else ""
        raise ValueError(f"配置文件不是有效 TOML{location}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ValueError("TOML 顶层必须是表")
    return data


def newline_for(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def proxy_key_name(token: str) -> str:
    return token.strip("\"'")


def update_codex_config(text: str, path: Path | None = None) -> str:
    data = parse_toml(text, path)
    policy = data.get("shell_environment_policy", {})
    if not isinstance(policy, dict):
        raise ValueError('配置字段 "shell_environment_policy" 必须是表')
    set_values = policy.get("set")
    if set_values is not None and not isinstance(set_values, dict):
        raise ValueError('配置字段 "shell_environment_policy.set" 必须是表')

    newline = newline_for(text)
    lines = text.splitlines(keepends=True)
    header_index = next(
        (index for index, line in enumerate(lines) if CODEX_SET_HEADER_RE.match(line)),
        None,
    )

    if header_index is None:
        if set_values is not None:
            raise ValueError(
                '字段 "shell_environment_policy.set" 使用了内联或点号形式；'
                "请改为 [shell_environment_policy.set] 表后重试"
            )
        rendered = text
        if rendered and not rendered.endswith(("\n", "\r")):
            rendered += newline
        if rendered and not rendered.endswith(newline * 2):
            rendered += newline
        rendered += (
            f"[shell_environment_policy.set]{newline}"
            f'HTTP_PROXY = "{PROXY_URL}"{newline}'
            f'HTTPS_PROXY = "{PROXY_URL}"{newline}'
        )
    else:
        section_end = len(lines)
        for index in range(header_index + 1, len(lines)):
            if TOML_TABLE_HEADER_RE.match(lines[index]):
                section_end = index
                break

        found: set[str] = set()
        for index in range(header_index + 1, section_end):
            match = CODEX_PROXY_KEY_RE.match(lines[index].rstrip("\r\n"))
            if not match:
                continue
            variable = proxy_key_name(match.group("key"))
            ending = "\r\n" if lines[index].endswith("\r\n") else newline
            lines[index] = (
                f'{match.group("indent")}{variable} = "{PROXY_URL}"{ending}'
            )
            found.add(variable)

        additions = [
            f'{variable} = "{PROXY_URL}"{newline}'
            for variable in PROXY_VARIABLES
            if variable not in found
        ]
        if additions:
            if section_end > 0 and not lines[section_end - 1].endswith(("\n", "\r")):
                lines[section_end - 1] += newline
            lines[section_end:section_end] = additions
        rendered = "".join(lines)

    updated = parse_toml(rendered, path)
    updated_proxy = updated["shell_environment_policy"]["set"]
    for variable in PROXY_VARIABLES:
        if updated_proxy.get(variable) != PROXY_URL:
            raise ValueError(f"Codex 代理字段写入失败：{variable}")
    return rendered


def write_text(path: Path, rendered: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(rendered)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def configure_claude(root: Path | None) -> Path:
    path = claude_settings_path(root)
    data = load_json_object(path)
    update_claude_settings(data)
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return path


def configure_codex(root: Path | None) -> Path:
    path = codex_config_path(root)
    rendered = update_codex_config(load_toml(path), path)
    write_text(path, rendered)
    return path


def main() -> int:
    args = parse_args()
    try:
        if args.target == "claude":
            path = configure_claude(args.root)
            print(f"已更新 Claude 权限与代理：{path}")
        else:
            path = configure_codex(args.root)
            print(f"已更新 Codex 代理：{path}")
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
