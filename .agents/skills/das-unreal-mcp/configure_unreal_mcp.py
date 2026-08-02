#!/usr/bin/env python3
"""Configure Unreal MCP and Python remote execution for one .uproject."""

import argparse
import codecs
import json
import os
import re
import subprocess
import sys
from pathlib import Path


MCP_SETTINGS_SECTION = "/Script/ModelContextProtocolEngine.ModelContextProtocolSettings"
PYTHON_SETTINGS_SECTION = "/Script/PythonScriptPlugin.PythonScriptPluginSettings"
REQUIRED_PLUGINS = (
    "ModelContextProtocol",
    "AllToolsets",
    "PythonScriptPlugin",
)
SKIPPED_SEARCH_DIRS = {"Binaries", "DerivedDataCache", "Intermediate", "Saved"}
POWERSHELL_UTF8_PREFIX = (
    "$ErrorActionPreference='Stop';"
    "$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
)


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
    except FileNotFoundError:
        raise
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
    content = json.dumps(value, ensure_ascii=False, indent="\t") + "\n"
    atomic_write_text(path, content)


def enable_plugins(project_data):
    plugins = project_data.setdefault("Plugins", [])
    if not isinstance(plugins, list):
        raise ConfigurationError(".uproject 的 Plugins 必须是数组")
    changed = False
    by_name = {
        entry.get("Name", "").casefold(): entry
        for entry in plugins
        if isinstance(entry, dict)
    }
    for plugin_name in REQUIRED_PLUGINS:
        entry = by_name.get(plugin_name.casefold())
        if entry is None:
            plugins.append({"Name": plugin_name, "Enabled": True})
            changed = True
        elif entry.get("Enabled") is not True:
            entry["Enabled"] = True
            changed = True
    return changed


def normalize_engine_dir(path):
    candidate = Path(path).expanduser().resolve()
    if candidate.name.casefold() != "engine":
        candidate = candidate / "Engine"
    editor = candidate / "Binaries" / "Win64" / "UnrealEditor.exe"
    if not editor.is_file():
        raise ConfigurationError("找不到 UnrealEditor.exe：{}".format(editor))
    return candidate


def engine_from_editor_executable(executable):
    if not executable:
        return None
    path = Path(executable)
    for parent in path.parents:
        if parent.name.casefold() == "engine":
            try:
                return normalize_engine_dir(parent)
            except ConfigurationError:
                return None
    return None


def engine_from_registry(association):
    if os.name != "nt" or not association:
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Epic Games\Unreal Engine\Builds",
        ) as key:
            location, _ = winreg.QueryValueEx(key, association)
        return normalize_engine_dir(location)
    except (FileNotFoundError, OSError, ConfigurationError):
        return None


def engine_from_launcher(association):
    if not association:
        return None
    manifest = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / (
        r"Epic\UnrealEngineLauncher\LauncherInstalled.dat"
    )
    if not manifest.is_file():
        return None
    try:
        data = load_json(manifest)
    except ConfigurationError:
        return None
    expected = association if association.startswith("UE_") else "UE_{}".format(association)
    for entry in data.get("InstallationList", []):
        if not isinstance(entry, dict):
            continue
        names = {str(entry.get("AppName", "")), str(entry.get("ArtifactId", ""))}
        if expected in names:
            try:
                return normalize_engine_dir(entry.get("InstallLocation", ""))
            except ConfigurationError:
                continue
    return None


def resolve_engine_dir(project_data, editor_records=(), override=None):
    if override:
        return normalize_engine_dir(override)
    for record in editor_records:
        engine = engine_from_editor_executable(record.get("ExecutablePath"))
        if engine:
            return engine

    association = str(project_data.get("EngineAssociation", "")).strip()
    engine = engine_from_registry(association) or engine_from_launcher(association)
    if engine:
        return engine
    if association:
        conventional = Path(r"C:\Program Files\Epic Games") / (
            association if association.startswith("UE_") else "UE_{}".format(association)
        )
        try:
            return normalize_engine_dir(conventional)
        except ConfigurationError:
            pass
    raise ConfigurationError(
        "无法根据 EngineAssociation={!r} 定位引擎；可传 --engine-root".format(association)
    )


def find_plugin_descriptor(engine_dir, plugin_name):
    known = {
        "ModelContextProtocol": engine_dir
        / "Plugins/Experimental/ModelContextProtocol/ModelContextProtocol.uplugin",
        "AllToolsets": engine_dir
        / "Plugins/Experimental/Toolsets/AllToolsets/AllToolsets.uplugin",
        "PythonScriptPlugin": engine_dir
        / "Plugins/Experimental/PythonScriptPlugin/PythonScriptPlugin.uplugin",
    }
    candidate = known[plugin_name]
    if candidate.is_file():
        return candidate
    matches = list((engine_dir / "Plugins").rglob("{}.uplugin".format(plugin_name)))
    return matches[0] if matches else None


def validate_engine_plugins(engine_dir):
    missing = [name for name in REQUIRED_PLUGINS if not find_plugin_descriptor(engine_dir, name)]
    if missing:
        raise ConfigurationError(
            "引擎缺少所需插件：{}（{}）".format(", ".join(missing), engine_dir)
        )


def run_powershell(script, check=True):
    completed = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ConfigurationError("PowerShell 调用失败：{}".format(detail))
    return completed


def query_unreal_editors():
    if os.name != "nt":
        raise ConfigurationError("此配置脚本仅支持 Windows")
    script = POWERSHELL_UTF8_PREFIX + (
        "$items=@(Get-CimInstance Win32_Process -Filter \"Name='UnrealEditor.exe'\" | "
        "ForEach-Object {[PSCustomObject]@{ProcessId=[int]$_.ProcessId;"
        "ExecutablePath=[string]$_.ExecutablePath;CommandLine=[string]$_.CommandLine}});"
        "ConvertTo-Json -Compress -InputObject $items"
    )
    output = run_powershell(script).stdout.strip() or "[]"
    try:
        records = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ConfigurationError("无法解析 UnrealEditor 进程列表：{}".format(output)) from exc
    if isinstance(records, dict):
        records = [records]
    return records


def normalized_windows_text(value):
    return str(value or "").replace("/", "\\").casefold()


def matching_project_editors(records, uproject):
    needle = normalized_windows_text(uproject.resolve())
    return [
        record
        for record in records
        if needle in normalized_windows_text(record.get("CommandLine"))
    ]


def ambiguous_project_editors(records, uproject):
    filename = normalized_windows_text(uproject.name)
    return [
        record
        for record in records
        if not record.get("CommandLine")
        or filename in normalized_windows_text(record.get("CommandLine"))
    ]


def close_editor(record, timeout_seconds, force_close):
    process_id = int(record["ProcessId"])
    timeout_ms = max(1, int(timeout_seconds * 1000))
    force_literal = "$true" if force_close else "$false"
    script = POWERSHELL_UTF8_PREFIX + (
        "$process=Get-Process -Id {pid} -ErrorAction SilentlyContinue;"
        "if($null -eq $process){{exit 0}};"
        "if(-not $process.CloseMainWindow()){{exit 10}};"
        "if(-not $process.WaitForExit({timeout})){{"
        "if({force}){{$process | Stop-Process -Force;$process.WaitForExit(30000);exit 0}};"
        "exit 11}}"
    ).format(pid=process_id, timeout=timeout_ms, force=force_literal)
    completed = run_powershell(script, check=False)
    if completed.returncode == 10:
        raise ConfigurationError(
            "无法请求编辑器正常退出（PID {}）；请手工关闭后重试".format(process_id)
        )
    if completed.returncode == 11:
        raise ConfigurationError(
            "编辑器在 {} 秒内未退出（PID {}），可能有未保存提示；请处理后重试".format(
                timeout_seconds, process_id
            )
        )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ConfigurationError(
            "关闭编辑器失败（PID {}，退出码 {}）：{}".format(
                process_id, completed.returncode, detail
            )
        )


def decode_ini(path):
    if not path.exists():
        return "", "utf-8", "\r\n"
    data = path.read_bytes()
    if data.startswith(codecs.BOM_UTF8):
        text, encoding = data.decode("utf-8-sig"), "utf-8-sig"
    elif data.startswith(codecs.BOM_UTF16_LE):
        text, encoding = data.decode("utf-16"), "utf-16"
    elif data.startswith(codecs.BOM_UTF16_BE):
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


def update_mcp_file(path):
    if path.exists():
        data = load_json(path)
    else:
        data = {}
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ConfigurationError(".mcp.json 的 mcpServers 必须是对象")
    expected = {"type": "http", "url": "http://127.0.0.1:8000/mcp"}
    changed = servers.get("unreal-mcp") != expected
    if changed:
        servers["unreal-mcp"] = expected
        write_json(path, data)
    return changed


def prevalidate_config_files(project_dir):
    mcp_file = project_dir / ".mcp.json"
    if mcp_file.exists():
        data = load_json(mcp_file)
        servers = data.get("mcpServers", {})
        if not isinstance(servers, dict):
            raise ConfigurationError(".mcp.json 的 mcpServers 必须是对象")
    for ini_file in (
        project_dir / "Saved/Config/WindowsEditor/EditorPerProjectUserSettings.ini",
        project_dir / "Config/DefaultEngine.ini",
    ):
        if ini_file.exists():
            decode_ini(ini_file)


def configure_files(uproject, project_data):
    project_dir = uproject.parent
    results = []
    if enable_plugins(project_data):
        write_json(uproject, project_data)
        results.append(str(uproject))

    editor_settings = (
        project_dir / "Saved/Config/WindowsEditor/EditorPerProjectUserSettings.ini"
    )
    if set_ini_value(editor_settings, MCP_SETTINGS_SECTION, "bAutoStartServer", "True"):
        results.append(str(editor_settings))

    default_engine = project_dir / "Config/DefaultEngine.ini"
    if set_ini_value(default_engine, PYTHON_SETTINGS_SECTION, "bRemoteExecution", "True"):
        results.append(str(default_engine))

    mcp_file = project_dir / ".mcp.json"
    if update_mcp_file(mcp_file):
        results.append(str(mcp_file))
    return results


def restart_editor(engine_dir, uproject):
    editor = engine_dir / "Binaries/Win64/UnrealEditor.exe"
    process = subprocess.Popen([str(editor), str(uproject)], cwd=str(uproject.parent))
    return process.pid


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help="包含 .uproject 的目录，也可直接传 .uproject（默认当前目录）",
    )
    parser.add_argument("--engine-root", help="UE 安装根目录或 Engine 目录")
    parser.add_argument(
        "--close-timeout",
        type=float,
        default=300.0,
        help="等待编辑器正常退出的秒数（默认 300）",
    )
    parser.add_argument(
        "--force-close",
        action="store_true",
        help="超时后强制关闭；可能丢失未保存内容，仅在明确授权后使用",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="写完配置后不重启编辑器（用于维护或测试）",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        uproject = find_uproject(args.project)
        project_data = load_json(uproject)
        all_editors = query_unreal_editors()
        project_editors = matching_project_editors(all_editors, uproject)
        if not project_editors:
            ambiguous = ambiguous_project_editors(all_editors, uproject)
            if ambiguous:
                process_ids = ", ".join(str(item["ProcessId"]) for item in ambiguous)
                raise ConfigurationError(
                    "发现可能属于该项目但无法按完整路径确认的编辑器进程（PID {}）；"
                    "请手工关闭后重试".format(process_ids)
                )
        engine_dir = resolve_engine_dir(project_data, project_editors, args.engine_root)
        validate_engine_plugins(engine_dir)
        prevalidate_config_files(uproject.parent)

        print("[项目] {}".format(uproject))
        print("[引擎] {}".format(engine_dir.parent))
        for record in project_editors:
            print("[关闭] UnrealEditor.exe PID {}".format(record["ProcessId"]))
            close_editor(record, args.close_timeout, args.force_close)

        remaining = matching_project_editors(query_unreal_editors(), uproject)
        if remaining:
            raise ConfigurationError("编辑器尚未完全退出，拒绝写入用户配置")

        changed_files = configure_files(uproject, project_data)
        if changed_files:
            for path in changed_files:
                print("[已更新] {}".format(path))
        else:
            print("[配置] 已是目标状态")

        if args.no_restart:
            print("[完成] 已按要求跳过编辑器重启")
        else:
            process_id = restart_editor(engine_dir, uproject)
            print("[重启] UnrealEditor.exe PID {}".format(process_id))
        return 0
    except (ConfigurationError, OSError) as exc:
        print("[错误] {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
