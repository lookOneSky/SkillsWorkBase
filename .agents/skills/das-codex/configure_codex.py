#!/usr/bin/env python3
"""Configure Shift+Tab and initial Plan mode for the VS Code Codex extension."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path


COMMAND = "composer.togglePlanMode"
KEY = "Shift+Tab"
MODE_RE = re.compile(
    rb"\b[A-Za-z_$][\w$]*=[A-Za-z_$][\w$]*\?\.mode\?\?"
    rb"[A-Za-z_$][\w$]*\?\?(?P<quote>[`\"'])(?P<mode>default|plan)(?P=quote)"
)


class ConfigError(RuntimeError):
    pass


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"无效的 JSON：{path}：{exc}") from exc


def read_optional(path):
    return path.read_bytes() if path.exists() else None


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def atomic_write(path, data):
    if data is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def package_version(path):
    package = load_json(path / "package.json")
    if package.get("publisher") != "openai" or package.get("name") != "chatgpt":
        raise ConfigError(f"不是 OpenAI Codex 插件目录：{path}")
    return str(package.get("version", ""))


def find_extension(root, explicit=None):
    if explicit is not None:
        path = explicit.expanduser().resolve()
        package_version(path)
        return path
    root = root.expanduser().resolve()
    registry = root / "extensions.json"
    if registry.exists():
        entries = load_json(registry)
        if not isinstance(entries, list):
            raise ConfigError(f"扩展注册文件必须是数组：{registry}")
        paths = []
        for entry in entries:
            if entry.get("identifier", {}).get("id", "").lower() != "openai.chatgpt":
                continue
            relative = entry.get("relativeLocation")
            if not isinstance(relative, str):
                raise ConfigError("扩展注册信息缺少 relativeLocation；请指定 --extension-dir")
            path = (root / relative).resolve()
            if not path.is_relative_to(root) or not path.is_dir():
                raise ConfigError(f"无效的 Codex 插件注册路径：{path}")
            paths.append(path)
        paths = list(dict.fromkeys(paths))
        if len(paths) == 1:
            package_version(paths[0])
            return paths[0]
        if len(paths) > 1:
            raise ConfigError("存在多个已注册的 Codex 插件；请指定 --extension-dir")
        raise ConfigError(f"VS Code 未注册 Codex 插件：{registry}")
    paths = [path for path in root.glob("openai.chatgpt-*") if path.is_dir()]
    if len(paths) != 1:
        raise ConfigError("无法唯一确定 Codex 插件；请安装插件或指定 --extension-dir")
    package_version(paths[0])
    return paths[0]


def prepare_keymap(path):
    before = read_optional(path)
    entries = load_json(path) if before is not None else []
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict)
        or not isinstance(entry.get("command"), str)
        or (entry.get("key") is not None and not isinstance(entry["key"], str))
        or "key" not in entry
        for entry in entries
    ):
        raise ConfigError(f"快捷键配置必须是 command/key 对象数组：{path}")
    has_binding = False
    has_disabled = False
    for entry in entries:
        matches = sorted(str(entry["key"]).lower().replace(" ", "").split("+")) == ["shift", "tab"]
        if matches and entry["command"] != COMMAND:
            raise ConfigError(f"Shift+Tab 已被 {entry['command']} 使用，未修改任何文件")
        has_binding |= matches and entry["command"] == COMMAND
        has_disabled |= entry["command"] == COMMAND and entry["key"] is None
    if has_binding and not has_disabled:
        return before, before
    entries = [entry for entry in entries if not (entry["command"] == COMMAND and entry["key"] is None)]
    if not has_binding:
        entries.append({"command": COMMAND, "key": KEY})
    return before, json_bytes(entries)


def prepare_mode(extension):
    assets = extension / "webview" / "assets"
    host = extension / "out" / "extension.js"
    if not host.is_file() or b"commandKeybindings" not in host.read_bytes():
        raise ConfigError("此插件版本不支持内置快捷键配置，未修改任何文件")
    if not any(COMMAND.encode() in path.read_bytes() for path in assets.glob("src-*.js")):
        raise ConfigError("此插件版本缺少 Plan 切换命令，未修改任何文件")
    modules = list(assets.glob("use-collaboration-mode-*.js"))
    if len(modules) != 1:
        raise ConfigError("无法唯一确定模式资源文件，未修改任何文件")
    path = modules[0]
    before = path.read_bytes()
    matches = list(MODE_RE.finditer(before))
    if len(matches) != 1 or b"collaborationMode" not in before:
        raise ConfigError("插件模式代码结构不兼容，未修改任何文件；需适配新版本脚本")
    match = matches[0]
    after = before[:match.start("mode")] + b"plan" + before[match.end("mode"):]
    return path, before, after


def transact(changes):
    """Preflight both files, then undo completed writes if a later write fails."""
    for path, before, _ in changes:
        if read_optional(path) != before:
            raise ConfigError(f"文件已被其他程序修改，请重试：{path}")
    completed = []
    try:
        for path, before, after in changes:
            atomic_write(path, after)
            completed.append((path, before, after))
            if read_optional(path) != after:
                raise ConfigError(f"写入后校验失败：{path}")
    except BaseException as exc:
        failed = []
        for path, before, after in reversed(completed):
            try:
                if read_optional(path) != after:
                    raise ConfigError("文件在写入后再次发生变化")
                atomic_write(path, before)
            except OSError as rollback_error:
                failed.append(f"{path}: {rollback_error}")
            except ConfigError as rollback_error:
                failed.append(f"{path}: {rollback_error}")
        if failed:
            raise ConfigError(f"操作失败：{exc}；回滚失败，请使用备份恢复：{'; '.join(failed)}") from exc
        raise


def create_backup(home, changes):
    backup = home / "backups" / ("das-codex-init-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6])
    backup.mkdir(parents=True, exist_ok=False)
    records = []
    for index, (path, before, after) in enumerate(changes):
        filename = f"{index}-{path.name}.bak"
        if before is not None:
            (backup / filename).write_bytes(before)
        records.append({"path": str(path), "file": filename, "before_sha256": digest(before), "after_sha256": digest(after)})
    (backup / "manifest.json").write_bytes(json_bytes({"version": 1, "files": records}))
    return backup


def restore(backup):
    backup = backup.expanduser().resolve()
    manifest = load_json(backup / "manifest.json")
    if manifest.get("version") != 1 or not isinstance(manifest.get("files"), list):
        raise ConfigError("不支持的备份格式")
    changes = []
    for record in manifest["files"]:
        path = Path(record["path"])
        filename = record["file"]
        if not path.is_absolute() or Path(filename).name != filename:
            raise ConfigError("备份包含无效路径")
        if path.name != "keybindings.json" and not path.match("use-collaboration-mode-*.js"):
            raise ConfigError("备份包含未知的配置文件")
        original = (backup / filename).read_bytes() if record["before_sha256"] is not None else None
        current = read_optional(path)
        if digest(original) != record["before_sha256"]:
            raise ConfigError(f"备份校验失败：{filename}")
        if current == original:
            continue
        if digest(current) != record["after_sha256"]:
            raise ConfigError(f"文件在初始化后有其他修改，停止恢复：{path}")
        changes.append((path, current, original))
    transact(changes)
    return {"status": "restored", "backup": str(backup), "reload_required": bool(changes)}


def initialize(args):
    extension = find_extension(args.extensions_dir, args.extension_dir)
    home = args.codex_home.expanduser().resolve()
    mode_path, mode_before, mode_after = prepare_mode(extension)
    keymap_path = home / "keybindings.json"
    keymap_before, keymap_after = prepare_keymap(keymap_path)
    changes = [(path, before, after) for path, before, after in (
        (keymap_path, keymap_before, keymap_after), (mode_path, mode_before, mode_after)
    ) if before != after]
    result = {
        "status": "needs-initialization" if changes else "configured",
        "extension": str(extension), "version": package_version(extension),
        "shortcut": KEY, "command": COMMAND, "initial_mode": "plan",
        "keymap": str(keymap_path), "pending_files": [str(item[0]) for item in changes],
        "reload_required": False,
    }
    if args.check:
        return result, 2 if changes else 0
    if changes:
        backup = create_backup(home, changes)
        try:
            transact(changes)
        except (OSError, ConfigError) as exc:
            raise ConfigError(f"{exc}；备份：{backup}") from exc
        result.update(status="configured", backup=str(backup), pending_files=[], reload_required=True)
    return result, 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex"))
    parser.add_argument("--extensions-dir", type=Path, default=Path.home() / ".vscode" / "extensions")
    parser.add_argument("--extension-dir", type=Path, help="指定某个 Codex 插件安装目录")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只检查；需要初始化时退出码为 2")
    mode.add_argument("--restore", type=Path, metavar="BACKUP", help="恢复指定备份")
    args = parser.parse_args(argv)
    try:
        if args.restore is not None:
            result, code = restore(args.restore), 0
        else:
            result, code = initialize(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (OSError, ValueError, ConfigError) as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
