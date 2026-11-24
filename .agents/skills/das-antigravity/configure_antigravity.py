#!/usr/bin/env python3
"""Configure Alt+K to add selections or files to Antigravity chat in VS Code."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path


EXTENSION = "google.google-antigravity"
BINDINGS = [
    {"key": "alt+k", "command": "-claude-vscode.insertAtMention", "when": "editorTextFocus"},
    {
        "key": "alt+k", "command": "antigravity.insertSnippet",
        "when": "editorTextFocus && editorHasSelection",
    },
    {
        "key": "alt+k", "command": "antigravity.addFileToChat",
        "when": "editorTextFocus && !editorHasSelection && (resourceScheme == file || resourceScheme == vscode-remote)",
    },
]
MANAGED_COMMANDS = {
    "chatgpt.addToThread", "chatgpt.addFileToThread", "claude-vscode.insertAtMention",
    "antigravity.insertSnippet", "antigravity.addFileToChat",
}
MANAGED_COMMANDS |= {f"-{command}" for command in MANAGED_COMMANDS}
JSON_STRING = r'"(?:\\.|[^"\\])*"'
COMMENTS_OR_STRINGS = re.compile(JSON_STRING + r"|//[^\r\n]*|/\*.*?\*/", re.DOTALL)
TRAILING_COMMAS_OR_STRINGS = re.compile(JSON_STRING + r"|,(?=\s*[\]}])")
ALT_K_PREFIX = re.compile(r"^\s*alt[+-](?:k|\[keyk\])(?:\s|$)", re.IGNORECASE)
WHITESPACE = re.compile(r"\s*")


def find_manifest(root):
    root = root.expanduser().resolve()
    registry = root / "extensions.json"
    if registry.is_file():
        registrations = json.loads(registry.read_text(encoding="utf-8-sig"))
        if not isinstance(registrations, list):
            raise ValueError(f"无效的 VS Code 扩展注册信息：{registry}")
        paths = {
            (root / entry["relativeLocation"]).resolve()
            for entry in registrations
            if entry.get("identifier", {}).get("id", "").lower() == EXTENSION
        }
    else:
        paths = {path.resolve() for path in root.glob(f"{EXTENSION}-*") if path.is_dir()}
    if len(paths) != 1:
        raise ValueError(f"无法唯一确定 VS Code 的 Antigravity 扩展目录：{root}")
    directory = paths.pop()
    if not directory.is_relative_to(root):
        raise ValueError(f"Antigravity 扩展的注册路径超出了扩展目录：{directory}")
    manifest = directory / "package.json"
    package = json.loads(manifest.read_text(encoding="utf-8-sig"))
    commands = {item.get("command") for item in package.get("contributes", {}).get("commands", [])}
    if (
        f"{package.get('publisher')}.{package.get('name')}".lower() != EXTENSION
        or not {binding["command"] for binding in BINDINGS[1:]}.issubset(commands)
    ):
        raise ValueError(f"未找到 Antigravity 的选中文本和文件聊天命令：{manifest}")
    return manifest


def parse_jsonc(text):
    """Mask comments and trailing commas without changing character offsets."""
    clean = COMMENTS_OR_STRINGS.sub(
        lambda match: re.sub(r"[^\r\n]", " ", match[0]) if match[0].startswith("/") else match[0],
        text,
    )

    def trailing_comma(match):
        if match[0] == "," and clean[:match.start()].rstrip()[-1:] not in ("", "[", "{", ","):
            return " "
        return match[0]

    strict = TRAILING_COMMAS_OR_STRINGS.sub(trailing_comma, clean)
    entries = json.loads(strict) if strict.strip() else []
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict)
        or not isinstance(entry.get("key"), str)
        or not isinstance(entry.get("command"), str)
        for entry in entries
    ):
        raise ValueError("快捷键配置必须是 key/command 对象数组")
    return entries, clean, strict


def matches_alt_k(key):
    return key.strip().lower().replace("-", "+") in ("alt+k", "alt+[keyk]")


def remove_entries(text, clean, strict, count, removed):
    if not removed:
        return text
    decoder = json.JSONDecoder()
    position = clean.index("[") + 1
    edits = []
    for index in range(count):
        start = WHITESPACE.match(clean, position).end()
        _, end = decoder.raw_decode(strict, start)
        separator = WHITESPACE.match(clean, end).end()
        position = separator + 1
        if index not in removed:
            continue
        if clean[separator] == ",":
            if text[end:separator].strip():
                edits.append((separator, separator + 1))
            else:
                end = separator + 1
        line_start = text.rfind("\n", 0, start) + 1
        line_end = text.find("\n", end)
        if line_end != -1 and not text[line_start:start].strip() and not text[end:line_end].strip():
            start, end = line_start, line_end + 1
        edits.append((start, end))
    for start, end in sorted(edits, reverse=True):
        text = text[:start] + text[end:]
    return text


def append_bindings(text):
    _, clean, _ = parse_jsonc(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    body = ("," + newline).join(
        "    " + json.dumps(binding, indent=4).replace("\n", newline + "    ")
        for binding in BINDINGS
    )
    if not clean.strip():
        separator = newline if text and not text.endswith("\n") else ""
        return text + separator + "[" + newline + body + newline + "]" + newline
    closing = clean.rfind("]")
    last = len(clean[:closing].rstrip()) - 1
    prefix = text[:closing]
    if clean[last] not in "[,":
        prefix = prefix[:last + 1] + "," + prefix[last + 1:]
    if not prefix.endswith("\n"):
        prefix += newline
    return prefix + body + newline + text[closing:]


def prepare_keymap(before):
    text = before.decode("utf-8-sig") if before is not None else ""
    entries, clean, strict = parse_jsonc(text)
    removed = {
        index for index, entry in enumerate(entries)
        if matches_alt_k(entry["key"]) and entry["command"] in MANAGED_COMMANDS
    }
    active = [
        entry for entry in entries
        if not entry["command"].startswith("-") and ALT_K_PREFIX.match(entry["key"])
    ]
    if [entry for index, entry in enumerate(entries) if index in removed] == BINDINGS and active[-2:] == BINDINGS[1:]:
        return before
    updated = remove_entries(text, clean, strict, len(entries), removed)
    updated = append_bindings(updated)
    expected = [entry for index, entry in enumerate(entries) if index not in removed] + BINDINGS
    if parse_jsonc(updated)[0] != expected:
        raise ValueError("生成的快捷键配置校验失败")
    bom = b"\xef\xbb\xbf" if before and before.startswith(b"\xef\xbb\xbf") else b""
    return bom + updated.encode("utf-8")


def find_user_dir(explicit=None):
    if explicit is not None:
        return explicit.expanduser().resolve()
    appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    directory = appdata / "Code" / "User"
    # A named Profile can have its own shortcuts. Avoid silently editing the default.
    profiles = directory / "profiles"
    if profiles.is_dir() and any(path.is_dir() for path in profiles.iterdir()):
        raise ValueError("检测到命名 Profile；请用 --vscode-user-dir 指定当前 Profile 的实际配置目录")
    return directory.resolve()


def read_optional(path):
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def write_keymap(path, before, after):
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    temporary = None
    try:
        if read_optional(path) != before:
            raise ValueError(f"快捷键文件已被其他程序修改，请重试：{path}")
        if before is not None:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix="keybindings.das-antigravity-", suffix=".bak", delete=False,
            ) as stream:
                backup = Path(stream.name)
                stream.write(before)
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".keybindings-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(after)
        if read_optional(path) != before:
            raise ValueError(f"快捷键文件已被其他程序修改，请重试：{path}")
        temporary.replace(path)
        if read_optional(path) != after:
            raise ValueError(f"写入后校验失败：{path}")
    except (OSError, ValueError) as exc:
        if backup is not None:
            raise ValueError(f"{exc}（备份：{backup}）") from exc
        raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return backup


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vscode-user-dir", type=Path, help="包含 keybindings.json 的 VS Code 用户或 Profile 目录")
    parser.add_argument("--extensions-dir", type=Path, default=Path.home() / ".vscode" / "extensions")
    parser.add_argument("--check", action="store_true", help="只检查；需要配置时返回 2")
    args = parser.parse_args(argv)
    try:
        manifest = find_manifest(args.extensions_dir)
        path = find_user_dir(args.vscode_user_dir) / "keybindings.json"
        before = read_optional(path)
        after = prepare_keymap(before)
        pending = before != after
        result = {
            "status": "needs-configuration" if pending and args.check else "configured",
            "keybindings": str(path), "manifest": str(manifest), "bindings": BINDINGS, "changed": False,
        }
        if pending and not args.check:
            backup = write_keymap(path, before, after)
            result["changed"] = True
            if backup is not None:
                result["backup"] = str(backup)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if pending and args.check else 0
    except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
