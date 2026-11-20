#!/usr/bin/env python3
"""Restore Claude Code's Alt+K file and selection shortcut in VS Code."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path


EXTENSION = "anthropic.claude-code"
COMMAND = "claude-vscode.insertAtMention"
BINDING = {"key": "alt+k", "command": COMMAND, "when": "editorTextFocus"}
REPLACED_COMMANDS = {"chatgpt.addToThread", "chatgpt.addFileToThread", f"-{COMMAND}"}
JSON_STRING = r'"(?:\\.|[^"\\])*"'
COMMENTS_OR_STRINGS = re.compile(JSON_STRING + r"|//[^\r\n]*|/\*.*?\*/", re.DOTALL)
TRAILING_COMMAS_OR_STRINGS = re.compile(JSON_STRING + r"|,(?=\s*[\]}])")
WHITESPACE = re.compile(r"\s*")
ALT_K_PREFIX = re.compile(r"^\s*alt[+-](?:k|\[keyk\])(?:\s|$)", re.IGNORECASE)


def find_manifest(root):
    root = root.expanduser().resolve()
    registry = root / "extensions.json"
    if registry.is_file():
        registrations = json.loads(registry.read_text(encoding="utf-8-sig"))
        paths = {
            (root / entry["relativeLocation"]).resolve()
            for entry in registrations
            if entry.get("identifier", {}).get("id", "").lower() == EXTENSION
        }
    else:
        paths = {path.resolve() for path in root.glob(f"{EXTENSION}-*") if path.is_dir()}
    if len(paths) != 1:
        raise ValueError(f"无法唯一确定 Claude Code 扩展目录：{root}")
    path = paths.pop()
    if not path.is_relative_to(root):
        raise ValueError(f"Claude Code 扩展的注册路径超出了扩展目录：{path}")
    manifest = path / "package.json"
    package = json.loads(manifest.read_text(encoding="utf-8-sig"))
    commands = package.get("contributes", {}).get("commands", [])
    if (
        f"{package.get('publisher')}.{package.get('name')}".lower() != EXTENSION
        or not any(item.get("command") == COMMAND for item in commands)
    ):
        raise ValueError(f"未找到 Claude Code 的文件引用命令：{manifest}")
    return manifest


def parse_jsonc(text):
    """Keep offsets while masking comments and trailing commas for the JSON decoder."""
    uncommented = COMMENTS_OR_STRINGS.sub(
        lambda match: re.sub(r"[^\r\n]", " ", match[0]) if match[0].startswith("/") else match[0],
        text,
    )

    def trailing_comma(match):
        if match[0] == "," and uncommented[:match.start()].rstrip()[-1:] not in ("", "[", "{", ","):
            return " "
        return match[0]

    strict = TRAILING_COMMAS_OR_STRINGS.sub(trailing_comma, uncommented)
    entries = json.loads(strict) if strict.strip() else []
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict)
        or not isinstance(entry.get("key"), str)
        or not isinstance(entry.get("command"), str)
        for entry in entries
    ):
        raise ValueError("VS Code 快捷键配置必须是 key/command 对象数组")
    return entries, uncommented, strict


def remove_entries(text, uncommented, strict, count, removed):
    if not removed:
        return text
    decoder = json.JSONDecoder()
    position = uncommented.index("[") + 1
    edits = []
    for index in range(count):
        start = WHITESPACE.match(uncommented, position).end()
        _, end = decoder.raw_decode(strict, start)
        separator = WHITESPACE.match(uncommented, end).end()
        position = separator + 1
        if index not in removed:
            continue
        if uncommented[separator] == ",":
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


def append_binding(text):
    _, clean, _ = parse_jsonc(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    body = "    " + json.dumps(BINDING, indent=4).replace("\n", newline + "    ")
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


def matches_alt_k(key):
    return key.strip().lower().replace("-", "+") == BINDING["key"]


def matches_binding(entry):
    return (
        matches_alt_k(entry["key"])
        and entry["command"] == COMMAND
        and entry.get("when") == BINDING["when"]
        and entry.get("args") is None
    )


def prepare_keymap(before):
    text = before.decode("utf-8-sig") if before is not None else ""
    entries, uncommented, strict = parse_jsonc(text)
    removed = {
        index for index, entry in enumerate(entries)
        if matches_alt_k(entry["key"]) and entry["command"] in REPLACED_COMMANDS
    }
    active = [
        entry for index, entry in enumerate(entries)
        if index not in removed and not entry["command"].startswith("-")
        and ALT_K_PREFIX.match(entry["key"])
    ]
    append = not active or not matches_binding(active[-1])
    if append:
        removed.update(index for index, entry in enumerate(entries) if matches_binding(entry))
    if not removed and not append:
        return before

    updated = remove_entries(text, uncommented, strict, len(entries), removed)
    expected = [entry for index, entry in enumerate(entries) if index not in removed]
    if append:
        updated = append_binding(updated)
        expected.append(BINDING)
    if parse_jsonc(updated)[0] != expected:
        raise ValueError("生成的 VS Code 快捷键配置校验失败")
    bom = b"\xef\xbb\xbf" if before and before.startswith(b"\xef\xbb\xbf") else b""
    return bom + updated.encode("utf-8")


def read_optional(path):
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def write_keymap(path, before, after):
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if before is not None:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix="keybindings.das-claude-",
                                         suffix=".bak", delete=False) as stream:
            backup = Path(stream.name)
            stream.write(before)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".keybindings-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(after)
    try:
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
        temporary.unlink(missing_ok=True)
    return backup


def main(argv=None):
    appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vscode-user-dir", type=Path, default=appdata / "Code" / "User")
    parser.add_argument("--extensions-dir", type=Path, default=Path.home() / ".vscode" / "extensions")
    parser.add_argument("--check", action="store_true", help="只检查；需要配置时返回 2")
    args = parser.parse_args(argv)
    path = args.vscode_user_dir.expanduser().resolve() / "keybindings.json"
    try:
        manifest = find_manifest(args.extensions_dir)
        before = read_optional(path)
        after = prepare_keymap(before)
        pending = before != after
        result = {"status": "configured", "keybindings": str(path), "manifest": str(manifest)}
        if pending and args.check:
            result["status"] = "needs-configuration"
        elif pending:
            backup = write_keymap(path, before, after)
            if backup is not None:
                result["backup"] = str(backup)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if pending and args.check else 0
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
