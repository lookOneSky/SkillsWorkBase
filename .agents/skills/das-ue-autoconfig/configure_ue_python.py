#!/usr/bin/env python3
"""Enable Unreal Python remote execution for one .uproject."""

import argparse
import codecs
import json
import os
import re
import subprocess
import sys
from pathlib import Path


PYTHON_SETTINGS_SECTION = "/Script/PythonScriptPlugin.PythonScriptPluginSettings"
PYTHON_PLUGIN = "PythonScriptPlugin"
SKIPPED_SEARCH_DIRS = {"Binaries", "DerivedDataCache", "Intermediate", "Saved"}


class ConfigurationError(RuntimeError):
    pass


def find_uproject(project_input):
    path = Path(project_input).expanduser().resolve()
    if path.is_file():
        if path.suffix.casefold() != ".uproject":
            raise ConfigurationError("输入文件不是 .uproject：{}".format(path))
        return path
    if not path.is_dir():
        raise ConfigurationError("项目目录不存在：{}".format(path))

    direct = sorted(path.glob("*.uproject"))
    if len(direct) == 1:
        return direct[0]
    if len(direct) > 1:
        raise ConfigurationError(
            "目录中存在多个 .uproject，请直接传入目标文件：{}".format(
                ", ".join(str(item) for item in direct)
            )
        )

    candidates = []
    for item in path.rglob("*.uproject"):
        relative_parts = item.relative_to(path).parts[:-1]
        if not any(part in SKIPPED_SEARCH_DIRS for part in relative_parts):
            candidates.append(item)
    candidates.sort()
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ConfigurationError("未找到 .uproject：{}".format(path))
    raise ConfigurationError(
        "递归找到多个 .uproject，请直接传入目标文件：{}".format(
            ", ".join(str(item) for item in candidates)
        )
    )


def load_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("JSON 无法解析：{} ({})".format(path, exc)) from exc
    if not isinstance(value, dict):
        raise ConfigurationError("JSON 顶层必须是对象：{}".format(path))
    return value


def atomic_write_text(path, text, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".{}.{}.tmp".format(path.name, os.getpid()))
    try:
        with temporary.open("w", encoding=encoding, newline="") as stream:
            stream.write(text)
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path, value):
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent="\t") + "\n")


def enable_python_plugin(project_data):
    plugins = project_data.setdefault("Plugins", [])
    if not isinstance(plugins, list):
        raise ConfigurationError(".uproject 的 Plugins 必须是数组")
    for entry in plugins:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("Name", "")).casefold() != PYTHON_PLUGIN.casefold():
            continue
        if entry.get("Enabled") is True:
            return False
        entry["Enabled"] = True
        return True
    plugins.append({"Name": PYTHON_PLUGIN, "Enabled": True})
    return True


def decode_ini(path):
    if not path.exists():
        return "", "utf-8", "\r\n"
    data = path.read_bytes()
    if data.startswith(codecs.BOM_UTF8):
        text, encoding = data.decode("utf-8-sig"), "utf-8-sig"
    elif data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        text, encoding = data.decode("utf-16"), "utf-16"
    else:
        try:
            text, encoding = data.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            text, encoding = data.decode("mbcs"), "mbcs"
    newline = "\r\n" if "\r\n" in text else "\n"
    return text, encoding, newline


def set_ini_value(path, section, key, value):
    text, encoding, newline = decode_ini(path)
    lines = text.splitlines()
    section_header = "[{}]".format(section).casefold()
    start = None
    end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if start is None and stripped.casefold() == section_header:
            start = index
            continue
        if start is not None and stripped.startswith("[") and stripped.endswith("]"):
            end = index
            break

    key_pattern = re.compile(r"^\s*{}\s*=".format(re.escape(key)), re.IGNORECASE)
    changed = False
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["[{}]".format(section), "{}={}".format(key, value)])
        changed = True
    else:
        matches = [index for index in range(start + 1, end) if key_pattern.match(lines[index])]
        replacement = "{}={}".format(key, value)
        if matches:
            first = matches[0]
            if lines[first] != replacement:
                lines[first] = replacement
                changed = True
            for duplicate in reversed(matches[1:]):
                del lines[duplicate]
                changed = True
        else:
            lines.insert(end, replacement)
            changed = True

    if changed:
        atomic_write_text(path, newline.join(lines) + newline, encoding=encoding)
    return changed


def running_editor_pids(uproject):
    if os.name != "nt":
        return []
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "Get-CimInstance Win32_Process -Filter \"Name='UnrealEditor.exe'\" | "
        "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    needle = str(uproject).replace("/", "\\").casefold()
    pids = []
    for line in completed.stdout.splitlines():
        process_id, _, command_line = line.partition("|")
        if needle in command_line.replace("/", "\\").casefold():
            pids.append(process_id.strip())
    return pids


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help="包含 .uproject 的目录，也可直接传 .uproject（默认当前目录）",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        uproject = find_uproject(args.project)
        project_data = load_json(uproject)
        default_engine = uproject.parent / "Config/DefaultEngine.ini"
        decode_ini(default_engine)

        print("[项目] {}".format(uproject))
        changed = []
        if set_ini_value(default_engine, PYTHON_SETTINGS_SECTION, "bRemoteExecution", "True"):
            changed.append(default_engine)
        if enable_python_plugin(project_data):
            write_json(uproject, project_data)
            changed.append(uproject)

        for path in changed:
            print("[已更新] {}".format(path))
        if not changed:
            print("[配置] 已是目标状态")

        pids = running_editor_pids(uproject)
        if pids and changed:
            print("[提示] 编辑器正在运行（PID {}），需重启后生效".format(", ".join(pids)))
        return 0
    except (ConfigurationError, OSError) as exc:
        print("[错误] {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
