#!/usr/bin/env python3
"""Launch the Unreal Editor for one .uproject when it is not already running."""

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path


SKIPPED_SEARCH_DIRS = {"Binaries", "DerivedDataCache", "Intermediate", "Saved"}
BUILDS_REGISTRY_KEY = r"SOFTWARE\Epic Games\Unreal Engine\Builds"
LAUNCHER_MANIFEST = "Epic/UnrealEngineLauncher/LauncherInstalled.dat"
DEFAULT_EDITOR_NAMES = ("UnrealEditor.exe", "UE4Editor.exe")
EDITOR_WINDOW_CLASS = "UnrealWindow"  # FWindowsWindow::AppWindowClass
PYTHON_SETTINGS_SECTION = "/Script/PythonScriptPlugin.PythonScriptPluginSettings"
MAPS_SETTINGS_SECTION = "/Script/EngineSettings.GameMapsSettings"
RESULT_MARKER = "UE_LAUNCH_RESULT="
STDOUT_LEVEL_LIMIT = 30


class LaunchError(RuntimeError):
    pass


# 定位唯一的 .uproject：可传文件、项目目录，或省略后递归查找
def find_uproject(project_input: str) -> Path:
    path = Path(project_input).expanduser().resolve()
    if path.is_file():
        if path.suffix.casefold() != ".uproject":
            raise LaunchError("输入文件不是 .uproject：{}".format(path))
        return path
    if not path.is_dir():
        raise LaunchError("项目目录不存在：{}".format(path))

    direct = sorted(path.glob("*.uproject"))
    if len(direct) == 1:
        return direct[0]
    if len(direct) > 1:
        raise LaunchError(
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
        raise LaunchError("未找到 .uproject：{}".format(path))
    raise LaunchError(
        "递归找到多个 .uproject，请直接传入目标文件：{}".format(
            ", ".join(str(item) for item in candidates)
        )
    )


# 读取 JSON 文件，失败时返回空字典
def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


# 读取 UE 的 ini 配置，返回 {段: {键: 值}}，同名键取最后一次赋值
def read_ini(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    for encoding in ("utf-8-sig", "utf-16", "mbcs"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except (UnicodeError, LookupError):
            continue
        except OSError:
            return {}
    else:
        return {}

    sections: dict[str, dict[str, str]] = {}
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            sections.setdefault(section, {})
            continue
        key, separator, value = stripped.partition("=")
        if separator:
            sections.setdefault(section, {})[key.strip().lstrip("+-.!")] = value.strip()
    return sections


# 引擎根目录必须同时含 Engine/Binaries 与 Engine/Build（对齐 IsValidRootDirectory）
def is_valid_engine_root(path: Path) -> bool:
    return (path / "Engine/Binaries").is_dir() and (path / "Engine/Build").is_dir()


# 把引擎根目录或其 Engine 子目录规范成根目录
def normalize_engine_root(value: Path) -> Path | None:
    path = value.expanduser()
    candidates = [path]
    if path.name.casefold() == "engine":
        candidates.append(path.parent)
    for candidate in candidates:
        if is_valid_engine_root(candidate):
            return candidate.resolve()
    return None


# 枚举本机引擎安装：Launcher 清单 + HKCU 自定义构建（对齐 EnumerateEngineInstallations）
def enumerate_engine_installations() -> dict[str, Path]:
    installations: dict[str, Path] = {}

    manifest = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / LAUNCHER_MANIFEST
    if manifest.is_file():
        for entry in load_json(manifest).get("InstallationList", []):
            if not isinstance(entry, dict):
                continue
            app_name = str(entry.get("AppName", ""))
            location = str(entry.get("InstallLocation", "")).strip()
            if not location or not app_name.startswith("UE_"):
                continue
            root = normalize_engine_root(Path(location))
            if root:
                installations[app_name[3:]] = root

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, BUILDS_REGISTRY_KEY) as key:
            for index in range(winreg.QueryInfoKey(key)[1]):
                name, value, _ = winreg.EnumValue(key, index)
                location = str(value).strip()
                root = normalize_engine_root(Path(location)) if location else None
                if root:
                    installations[name] = root
    except (ImportError, OSError):
        pass

    return installations


# 依据 EngineAssociation 定位引擎根目录（对齐 GetEngineIdentifierForProject）
def resolve_engine_root(uproject: Path, project_data: dict, override: str | None) -> Path:
    if override:
        root = normalize_engine_root(Path(override))
        if not root:
            raise LaunchError("指定路径不是引擎根目录：{}".format(override))
        return root

    association = str(project_data.get("EngineAssociation", "")).strip()
    if association:
        if "/" in association or "\\" in association:
            root = normalize_engine_root((uproject.parent / association).resolve())
            if root:
                return root
        for identifier, root in enumerate_engine_installations().items():
            if identifier.casefold() == association.casefold():
                return root
        root = normalize_engine_root(
            Path(r"C:\Program Files\Epic Games")
            / (association if association.startswith("UE_") else "UE_{}".format(association))
        )
        if root:
            return root

    for parent in uproject.parents:
        if is_valid_engine_root(parent):
            return parent.resolve()

    raise LaunchError(
        "无法定位 Unreal Engine；请传 --engine-root，或修正 .uproject 的 EngineAssociation"
    )


# 优先用工程 Binaries 中的 Editor target，退回引擎默认编辑器（对齐 TryGetEditorFileName）
def find_editor_binary(engine_root: Path, uproject: Path) -> Path:
    binaries = uproject.parent / "Binaries/Win64"
    targets = []
    if binaries.is_dir():
        for item in binaries.glob("*.target"):
            try:
                targets.append((item.stat().st_mtime, item))
            except OSError:
                continue
    targets.sort(reverse=True)

    for _, target in targets:
        data = load_json(target)
        if data.get("TargetType") != "Editor" or data.get("Configuration") != "Development":
            continue
        launch = str(data.get("Launch", "")).strip()
        if not launch:
            continue
        launch = launch.replace("$(EngineDir)", str(engine_root / "Engine"))
        launch = launch.replace("$(ProjectDir)", str(uproject.parent))
        candidate = Path(launch)
        if candidate.is_file():
            return candidate.resolve()

    for name in DEFAULT_EDITOR_NAMES:
        candidate = engine_root / "Engine/Binaries/Win64" / name
        if candidate.is_file():
            return candidate.resolve()

    raise LaunchError("找不到编辑器可执行文件：{}".format(engine_root / "Engine/Binaries/Win64"))


# 取所有编辑器进程的 PID 与命令行
def query_editor_processes() -> list[tuple[str, str]]:
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "Get-CimInstance Win32_Process -Filter \"Name LIKE '%Editor%.exe'\" | "
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
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    processes = []
    for line in completed.stdout.splitlines():
        process_id, separator, command_line = line.partition("|")
        if separator and process_id.strip().isdigit():
            processes.append((process_id.strip(), command_line))
    return processes


# 找出正在打开该工程的编辑器进程：先匹配完整路径，再退回文件名
def running_editor_processes(uproject: Path) -> list[tuple[str, str]]:
    full_path = str(uproject).replace("/", "\\").casefold()
    file_name = uproject.name.casefold()
    exact = []
    loose = []
    for process_id, command_line in query_editor_processes():
        text = command_line.replace("/", "\\").casefold()
        if full_path in text:
            exact.append((process_id, command_line))
        elif file_name in text:
            loose.append((process_id, command_line))
    return exact or loose


# 从运行中的编辑器命令行反查引擎根目录与编辑器路径
def engine_from_process(command_line: str) -> tuple[Path | None, Path | None]:
    text = command_line.strip()
    executable = text[1:].split('"', 1)[0] if text.startswith('"') else text.split(" ", 1)[0]
    path = Path(executable)
    if not executable or not path.is_file():
        return None, None
    root = normalize_engine_root(path.parents[3]) if len(path.parents) > 3 else None
    return root, path.resolve()


# 以脱离父进程的方式启动编辑器（对齐 FWindowsPlatformInstallation::LaunchEditor）
def launch_editor(editor: Path, uproject: Path, extra_args: list[str]) -> subprocess.Popen:
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(
        [str(editor), str(uproject), *extra_args],
        cwd=str(uproject.parent),
        creationflags=flags,
        close_fds=True,
    )


# 判断进程是否已创建可见的编辑器主窗口（启动画面用的是 SplashScreenClass）
def has_editor_window(process_id: int) -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]

    owner = wintypes.DWORD()
    buffer = ctypes.create_unicode_buffer(256)
    found = False

    def visit(window, _):
        nonlocal found
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if owner.value == process_id and user32.IsWindowVisible(window):
            user32.GetClassNameW(window, buffer, len(buffer))
            if buffer.value == EDITOR_WINDOW_CLASS:
                found = True
                return False
        return True

    user32.EnumWindows(enum_proc(visit), 0)
    return found


# 等待编辑器主窗口出现，超时返回 False
def wait_for_editor(process: subprocess.Popen, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LaunchError("编辑器进程已退出（退出码 {}）".format(process.returncode))
        if has_editor_window(process.pid):
            return True
        time.sleep(1.0)
    return False


# 汇总 Python 远程执行的连接参数，供其他脚本接入运行中的编辑器
def python_remote_execution(config: dict, project_data: dict) -> dict:
    values = config.get(PYTHON_SETTINGS_SECTION, {})
    plugins = project_data.get("Plugins", [])
    plugin_enabled = isinstance(plugins, list) and any(
        isinstance(entry, dict)
        and str(entry.get("Name", "")).casefold() == "pythonscriptplugin"
        and entry.get("Enabled") is True
        for entry in plugins
    )
    return {
        "plugin_enabled": plugin_enabled,
        "enabled": values.get("bRemoteExecution", "False").casefold() == "true",
        "multicast_group_endpoint": values.get(
            "RemoteExecutionMulticastGroupEndpoint", "239.0.0.1:6766"
        ),
        "multicast_bind_address": values.get("RemoteExecutionMulticastBindAddress", "127.0.0.1"),
        "multicast_ttl": values.get("RemoteExecutionMulticastTtl", "0"),
    }


# 索引工程 Content 下的全部关卡，输出 /Game 包路径供后续 Python 操作定位
def index_levels(uproject: Path) -> list[dict]:
    content = uproject.parent / "Content"
    if not content.is_dir():
        return []
    levels = []
    for item in sorted(content.rglob("*.umap"), key=lambda value: str(value).casefold()):
        relative = item.relative_to(content).with_suffix("").as_posix()
        levels.append(
            {
                "name": item.stem,
                "package": "/Game/{}".format(relative),
                "object_path": "/Game/{}.{}".format(relative, item.stem),
            }
        )
    return levels


# 汇总实例信息：进程、引擎、关卡索引与远程执行参数
def build_result(
    status: str,
    uproject: Path,
    engine_root: Path | None,
    editor: Path | None,
    process_ids: list[str],
    ready: bool | None,
) -> dict:
    config = read_ini(uproject.parent / "Config/DefaultEngine.ini")
    maps = config.get(MAPS_SETTINGS_SECTION, {})
    levels = index_levels(uproject)
    return {
        "status": status,
        "ready": ready,
        "project": str(uproject),
        "project_name": uproject.stem,
        "project_dir": str(uproject.parent),
        "engine_root": str(engine_root) if engine_root else "",
        "editor": str(editor) if editor else "",
        "process_ids": [int(item) for item in process_ids],
        "python_remote_execution": python_remote_execution(config, load_json(uproject)),
        "editor_startup_map": maps.get("EditorStartupMap", ""),
        "game_default_map": maps.get("GameDefaultMap", ""),
        "level_count": len(levels),
        "levels": levels,
        "levels_truncated": False,
        "levels_file": "",
    }


# 输出机器可读结果，供后续 Python 操作接入；关卡过多时 stdout 只给前若干条
def report_result(result: dict, json_path: str | None) -> None:
    if json_path:
        path = Path(json_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        result = dict(result, levels_file=str(path))
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("[结果] {}".format(path))

    print("[关卡] 共 {} 个，启动关卡 {}".format(
        result["level_count"], result["editor_startup_map"] or "未配置"
    ))
    if result["level_count"] > STDOUT_LEVEL_LIMIT:
        result = dict(
            result, levels=result["levels"][:STDOUT_LEVEL_LIMIT], levels_truncated=True
        )
    print("{}{}".format(RESULT_MARKER, json.dumps(result, ensure_ascii=False)))


def parse_args(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    extra_args = []
    if "--" in argv:
        separator = argv.index("--")
        extra_args = argv[separator + 1 :]
        argv = argv[:separator]

    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="`--` 之后的内容作为编辑器附加命令行参数，例如：-- -log",
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help="包含 .uproject 的目录，也可直接传 .uproject（默认当前目录）",
    )
    parser.add_argument("--engine-root", help="引擎根目录，用于 EngineAssociation 定位失败时")
    parser.add_argument(
        "--wait",
        type=float,
        default=0.0,
        help="等待编辑器主窗口出现的秒数（默认 0，即启动后立即返回）",
    )
    parser.add_argument("--json", dest="json_path", help="把实例信息另存为 JSON 文件")
    args = parser.parse_args(argv)
    args.extra = extra_args
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        if os.name != "nt":
            raise LaunchError("本脚本仅支持 Windows")

        uproject = find_uproject(args.project)
        print("[项目] {}".format(uproject))

        running = running_editor_processes(uproject)
        engine_root = None
        editor = None
        try:
            engine_root = resolve_engine_root(uproject, load_json(uproject), args.engine_root)
            editor = find_editor_binary(engine_root, uproject)
        except LaunchError:
            if not running:
                raise
            engine_root, editor = engine_from_process(running[0][1])

        if running:
            for process_id, command_line in running:
                print("[运行中] PID {} {}".format(process_id, command_line.strip()))
            result = build_result(
                "running", uproject, engine_root, editor, [item for item, _ in running], None
            )
            report_result(result, args.json_path)
            return 0

        print("[引擎] {}".format(engine_root))
        print("[编辑器] {}".format(editor))
        process = launch_editor(editor, uproject, args.extra)
        print("[启动] PID {}".format(process.pid))

        ready = None
        if args.wait > 0:
            ready = wait_for_editor(process, args.wait)
            if ready:
                print("[就绪] 编辑器主窗口已出现")
            else:
                print("[超时] {:.0f} 秒内未出现编辑器主窗口，进程仍在启动".format(args.wait))

        result = build_result(
            "launched", uproject, engine_root, editor, [str(process.pid)], ready
        )
        report_result(result, args.json_path)
        return 0
    except (LaunchError, OSError) as exc:
        print("[错误] {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
