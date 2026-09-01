#!/usr/bin/env python3
"""Package an Unreal project with a matching Launcher profile or safe defaults."""

from __future__ import annotations

import argparse
import json
import locale
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path


PROFILE_SUFFIXES = {".ulp2"}
SKIPPED_DIRECTORIES = {
    ".git",
    ".svn",
    ".vs",
    "Binaries",
    "DerivedDataCache",
    "Intermediate",
    "Saved",
}
PROFILE_SKIPPED_DIRECTORIES = {
    ".git",
    ".svn",
    ".vs",
    "Binaries",
    "Content",
    "DerivedDataCache",
    "Intermediate",
    "Plugins",
    "Source",
}
TIMESTAMP_RE = re.compile(r"^\d{12}(?:_DLC)?(?:[_-]\d{2})?$")
HASH_SUFFIX_RE = re.compile(r"_[0-9a-f]{32}$", re.IGNORECASE)
COOK_FAILURE_RE = re.compile(
    r"(?:Error_UnknownCookFailure|Cook(?:ing)?(?: commandlet)? failed|"
    r"CookResults:\s*(?:Error|Failed)|LogCook:\s*Error|ExitCode\s*=\s*25\b)",
    re.IGNORECASE,
)
PROFILE_MODE_FIELDS = ("CreateReleaseVersion", "CreateDLC")
RELEASE_DIRECTORY_NAME = "Releases"
RELEASE_METADATA_RELATIVE = "Metadata/DevelopmentAssetRegistry.bin"
RELEASE_VERSION_RE = re.compile(r"^\d{12}$")
OUTPUT_INDEX_SUFFIX_RE = re.compile(r"_\d{2}$")
DLC_ONLY_PARAMETERS = ("dlcname", "generatepatch", "stagebasereleasepaks", "addpatchlevel")
RELEASE_PARAMETERS = (
    "createreleaseversion",
    "createreleaseversionroot",
    "basedonreleaseversion",
    "basedonreleaseversionroot",
)


class PackageError(RuntimeError):
    """Expected configuration or packaging failure."""


def read_json(path: Path) -> dict:
    raw = path.read_bytes()
    encodings = ["utf-8-sig"]
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.insert(0, "utf-16")
    preferred_encoding = locale.getpreferredencoding(False)
    if preferred_encoding and preferred_encoding.casefold() not in {
        item.casefold() for item in encodings
    }:
        encodings.append(preferred_encoding)
    last_error = None
    for encoding in encodings:
        try:
            data = json.loads(raw.decode(encoding))
            if not isinstance(data, dict):
                raise PackageError("JSON 根节点不是对象：{}".format(path))
            return data
        except (UnicodeError, json.JSONDecodeError) as exc:
            last_error = exc
    raise PackageError("无法解析配置：{} ({})".format(path, last_error))


def apply_packaging_mode(data: dict, dlc: bool) -> None:
    data["CreateReleaseVersion"] = not dlc
    data["CreateDLC"] = dlc


def update_profile_packaging_mode(path: Path, dlc: bool) -> None:
    raw = path.read_bytes()
    encodings = ["utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"]
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.insert(0, "utf-16")
    preferred_encoding = locale.getpreferredencoding(False)
    if preferred_encoding and preferred_encoding.casefold() not in {
        item.casefold() for item in encodings
    }:
        encodings.append(preferred_encoding)

    text = None
    encoding = None
    for candidate in encodings:
        try:
            text = raw.decode(candidate)
            encoding = candidate
            break
        except UnicodeError:
            continue
    if text is None or encoding is None:
        raise PackageError("无法读取配置编码：{}".format(path))

    values = {
        "CreateReleaseVersion": not dlc,
        "CreateDLC": dlc,
    }
    updated = text
    for field in PROFILE_MODE_FIELDS:
        pattern = re.compile(
            r'(^[ \t]*"{}"[ \t]*:[ \t]*)(?:true|false)([ \t]*,)'.format(
                re.escape(field)
            ),
            re.MULTILINE,
        )
        updated, count = pattern.subn(
            lambda match, value=values[field]: "{}{}{}".format(
                match.group(1), str(value).lower(), match.group(2)
            ),
            updated,
        )
        if count != 1:
            raise PackageError(
                "配置字段 {} 应恰好出现一次：{}".format(field, path)
            )

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(path.parent),
            prefix="{}.".format(path.name),
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(updated.encode(encoding))
        os.replace(str(temporary_path), str(path))
    except OSError as exc:
        if temporary_path:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise PackageError("无法更新配置模式：{} ({})".format(path, exc)) from exc


def normalize_name(value: object) -> str:
    return "".join(character.casefold() for character in str(value) if character.isalnum())


def name_forms(value: object) -> set[str]:
    normalized = normalize_name(value)
    result = {normalized} if normalized else set()
    if normalized.startswith("das") and len(normalized) > 3:
        result.add(normalized[3:])
    return result


def resolve_project(value: str) -> Path:
    source = Path(value).expanduser()
    if not source.exists():
        raise PackageError("工程路径不存在：{}".format(source))
    if source.is_file():
        if source.suffix.casefold() != ".uproject":
            raise PackageError("工程文件不是 .uproject：{}".format(source))
        return source.resolve()

    direct = sorted(source.glob("*.uproject"), key=lambda item: str(item).casefold())
    candidates = direct
    if not candidates:
        candidates = []
        for current, directories, files in os.walk(str(source)):
            current_path = Path(current)
            depth = len(current_path.relative_to(source).parts)
            directories[:] = [
                item
                for item in directories
                if item not in SKIPPED_DIRECTORIES and depth < 3
            ]
            candidates.extend(
                current_path / filename
                for filename in files
                if filename.casefold().endswith(".uproject")
            )
    candidates = sorted(
        {item.resolve() for item in candidates},
        key=lambda item: str(item).casefold(),
    )
    if not candidates:
        raise PackageError("目录中没有 .uproject：{}".format(source))
    if len(candidates) > 1:
        raise PackageError(
            "目录中找到多个 .uproject，请直接指定其中一个：{}".format(
                ", ".join(str(item) for item in candidates)
            )
        )
    return candidates[0]


def iter_profile_files(root: Path, max_depth: int = 6):
    if root.is_file():
        if root.suffix.casefold() in PROFILE_SUFFIXES:
            yield root.resolve()
        return
    if not root.is_dir():
        return
    for current, directories, files in os.walk(str(root)):
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts)
        directories[:] = [
            item
            for item in directories
            if item not in PROFILE_SKIPPED_DIRECTORIES and depth < max_depth
        ]
        for filename in files:
            candidate = current_path / filename
            if candidate.suffix.casefold() in PROFILE_SUFFIXES:
                yield candidate.resolve()


def profile_script(data: dict) -> dict:
    scripts = data.get("scripts")
    if not isinstance(scripts, list):
        return {}
    for item in scripts:
        if isinstance(item, dict) and str(item.get("script", "")).casefold() == "buildcookrun":
            return item
    return {}


def profile_alias_groups(path: Path, data: dict) -> list[tuple[set[str], float]]:
    filename = HASH_SUFFIX_RE.sub("", path.stem)
    groups = [
        (name_forms(filename), 850.0),
        (name_forms(data.get("Name", "")), 900.0),
    ]
    shareable = str(data.get("ShareableProjectPath", "")).replace("\\", "/")
    if shareable:
        groups.append((name_forms(Path(shareable).stem), 1000.0))
    script = profile_script(data)
    addcmdline = script.get("addcmdline")
    if isinstance(addcmdline, dict):
        groups.append((name_forms(addcmdline.get("sessionname", "")), 800.0))
    return groups


def profile_score(project: Path, path: Path, data: dict) -> float:
    targets = name_forms(project.stem)
    groups = profile_alias_groups(path, data)
    best = 0.0
    for aliases, exact_score in groups:
        if targets.intersection(aliases):
            best = max(best, exact_score)
        for target in targets:
            for alias in aliases:
                best = max(best, 100.0 * SequenceMatcher(None, target, alias).ratio())
    return best


def select_profile(project: Path, engine: Path) -> tuple[Path | None, dict | None]:
    roots = [
        (Path(__file__).resolve().parent, 2),
        (engine, 6),
    ]
    files = {}
    for root, max_depth in roots:
        for path in iter_profile_files(root, max_depth=max_depth):
            files[os.path.normcase(str(path))] = path

    matches = []
    for path in files.values():
        try:
            data = read_json(path)
        except (OSError, PackageError) as exc:
            print("[跳过配置] {}".format(exc), file=sys.stderr)
            continue
        score = profile_score(project, path, data)
        if score >= 65.0:
            matches.append((score, path.stat().st_mtime, path, data))
    if not matches:
        return None, None
    matches.sort(key=lambda item: (item[0], item[1], str(item[2]).casefold()), reverse=True)
    _, _, path, data = matches[0]
    print("[找到配置文件] {}".format(path))
    return path, data


def normalize_engine(value: Path) -> tuple[Path, Path] | None:
    path = value.expanduser()
    if path.is_file():
        if path.name.casefold() == "runuat.bat":
            return path.parents[2].resolve(), path.resolve()
        for parent in path.parents:
            run_uat = parent / "Build/BatchFiles/RunUAT.bat"
            if parent.name.casefold() == "engine" and run_uat.is_file():
                return parent.resolve(), run_uat.resolve()
        return None

    candidates = [
        path,
        path / "Engine",
        path / "Engine/Windows/Engine",
        path / "Windows/Engine",
    ]
    for engine in candidates:
        run_uat = engine / "Build/BatchFiles/RunUAT.bat"
        if run_uat.is_file():
            return engine.resolve(), run_uat.resolve()
    return None


def engine_from_registry(association: str) -> tuple[Path, Path] | None:
    if os.name != "nt" or not association:
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Epic Games\Unreal Engine\Builds",
        ) as key:
            location, _ = winreg.QueryValueEx(key, association)
        return normalize_engine(Path(location))
    except (FileNotFoundError, OSError):
        return None


def engine_from_launcher(association: str) -> tuple[Path, Path] | None:
    if not association:
        return None
    manifest = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / (
        "Epic/UnrealEngineLauncher/LauncherInstalled.dat"
    )
    if not manifest.is_file():
        return None
    try:
        data = read_json(manifest)
    except (OSError, PackageError):
        return None
    expected = association if association.startswith("UE_") else "UE_{}".format(association)
    for entry in data.get("InstallationList", []):
        if not isinstance(entry, dict):
            continue
        names = {str(entry.get("AppName", "")), str(entry.get("ArtifactId", ""))}
        if expected in names:
            result = normalize_engine(Path(str(entry.get("InstallLocation", ""))))
            if result:
                return result
    return None


def resolve_engine(
    project: Path,
    project_data: dict,
    override: str | None,
) -> tuple[Path, Path]:
    if override:
        result = normalize_engine(Path(override))
        if not result:
            raise PackageError("指定路径中找不到 RunUAT.bat：{}".format(override))
        return result

    association = str(project_data.get("EngineAssociation", "")).strip()
    result = engine_from_registry(association) or engine_from_launcher(association)
    if result:
        return result
    if association:
        result = normalize_engine(
            Path(r"C:\Program Files\Epic Games")
            / (association if association.startswith("UE_") else "UE_{}".format(association))
        )
        if result:
            return result

    for parent in [project.parent, *project.parents]:
        result = normalize_engine(parent)
        if result:
            return result
    raise PackageError(
        "无法定位 Unreal Engine；请传 --engine-root，或修正 .uproject 的 EngineAssociation"
    )


def is_path_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def find_editor_command(engine: Path, script: dict) -> Path:
    profile_value = str(script.get("unrealexe", "")).strip()
    if profile_value:
        profile_path = Path(profile_value)
        if profile_path.is_file() and is_path_inside(profile_path, engine):
            return profile_path.resolve()
    binaries = engine / "Binaries/Win64"
    preferred = [
        binaries / "UnrealEditor-Cmd.exe",
        binaries / "UnrealEditor-Win64-DebugGame-Cmd.exe",
        binaries / "UE4Editor-Cmd.exe",
    ]
    for candidate in preferred:
        if candidate.is_file():
            return candidate.resolve()
    discovered = sorted(binaries.glob("*Editor*-Cmd.exe"), key=lambda item: item.name.casefold())
    if discovered:
        return discovered[0].resolve()
    raise PackageError("引擎中找不到命令行编辑器：{}".format(binaries))


def configuration_name(value: str) -> str:
    normalized = normalize_name(value)
    aliases = {
        "debug": "DebugGame",
        "debuggame": "DebugGame",
        "shiping": "Shipping",
        "shipping": "Shipping",
    }
    if normalized not in aliases:
        raise argparse.ArgumentTypeError("配置仅支持 debug 或 shipping")
    return aliases[normalized]


def profile_output_directory(data: dict | None) -> Path | None:
    if not data:
        return None
    value = str(data.get("PackageDir", "")).strip()
    if not value:
        value = str(profile_script(data).get("stagingdirectory", "")).strip()
    return Path(value).expanduser() if value else None


def resolve_output_root(
    project: Path,
    data: dict | None,
    work_directory: str | None,
) -> Path:
    """确定打包工作目录，本次输出与基线都放在该目录下"""
    if work_directory:
        root = Path(work_directory).expanduser()
    else:
        profile_output = profile_output_directory(data)
        if profile_output:
            root = (
                profile_output.parent
                if TIMESTAMP_RE.fullmatch(profile_output.name)
                else profile_output
            )
        else:
            root = project.parent / "Saved/PackagedBuilds"
    return root.resolve()


def choose_output_directory(root: Path, dlc: bool) -> Path:
    """在打包工作目录下选出本次输出目录，重名时追加序号"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    directory_name = "{}_DLC".format(timestamp) if dlc else timestamp
    candidate = root / directory_name
    index = 1
    while candidate.exists():
        candidate = root / "{}_{:02d}".format(directory_name, index)
        index += 1
    return candidate


def release_root(output_root: Path) -> Path:
    """基线根目录，位于打包工作目录下"""
    return output_root / RELEASE_DIRECTORY_NAME


def release_version_name(output_directory: Path) -> str:
    """主干基线版本名，去掉输出目录的重名序号后缀"""
    return OUTPUT_INDEX_SUFFIX_RE.sub("", output_directory.name)


def has_release_payload(directory: Path) -> bool:
    """基线目录下任一平台目录含开发期资产注册表即视为可用"""
    try:
        platforms = [item for item in directory.iterdir() if item.is_dir()]
    except OSError:
        return False
    return any((item / RELEASE_METADATA_RELATIVE).is_file() for item in platforms)


def latest_release_version(output_root: Path) -> str | None:
    """取打包工作目录中最新的可用基线版本名"""
    root = release_root(output_root)
    if not root.is_dir():
        return None
    names = sorted(
        item.name
        for item in root.iterdir()
        if item.is_dir()
        and RELEASE_VERSION_RE.fullmatch(item.name)
        and has_release_payload(item)
    )
    return names[-1] if names else None


def apply_release_parameters(
    parameters: dict,
    output_root: Path,
    output_directory: Path,
    dlc: bool,
) -> None:
    """主干打包写出基线，DLC 打包引用打包目录中最新的基线"""
    for key in RELEASE_PARAMETERS:
        parameters.pop(key, None)
    if dlc:
        if not parameters.get("dlcname"):
            raise PackageError("DLC 模式必须在配置中提供 DLCName")
        version = latest_release_version(output_root)
        if not version:
            raise PackageError(
                "未找到可用基线，请先在同一目录完成一次主干打包：{}".format(
                    release_root(output_root)
                )
            )
        parameters["basedonreleaseversionroot"] = str(release_root(output_root))
        parameters["basedonreleaseversion"] = version
        return
    for key in DLC_ONLY_PARAMETERS:
        parameters.pop(key, None)
    parameters["createreleaseversionroot"] = str(release_root(output_root))
    parameters["createreleaseversion"] = release_version_name(output_directory)


def build_parameters(
    project: Path,
    output_root: Path,
    output_directory: Path,
    configuration: str,
    editor_command: Path,
    engine: Path,
    data: dict | None,
    dlc: bool,
) -> dict:
    script = profile_script(data or {})
    if script:
        parameters = {"project": str(project)}
        for key, value in script.items():
            if key in {
                "script",
                "project",
                "clientconfig",
                "serverconfig",
                "stagingdirectory",
                "unrealexe",
            }:
                continue
            parameters[key] = value
        parameters.setdefault("noP4", True)
        parameters.setdefault("utf8output", True)
        parameters.setdefault("platform", ["Win64"])
        parameters.setdefault("build", True)
        parameters.setdefault("cook", True)
        parameters.setdefault("pak", True)
        parameters.setdefault("compressed", True)
        parameters.setdefault("manifests", True)
        parameters.setdefault("stage", True)
        parameters.setdefault("package", True)
        cultures = data.get("CookedCultures") if data else None
        maps = data.get("CookedMaps") if data else None
        if cultures and "CookCultures" not in parameters:
            parameters["CookCultures"] = cultures
        if maps and "map" not in parameters:
            parameters["map"] = maps
        if data and "unversionedcookedcontent" not in parameters:
            parameters["unversionedcookedcontent"] = bool(data.get("CookUnversioned", True))
    else:
        parameters = {
            "project": str(project),
            "noP4": True,
            "nocompile": True,
            "nocompileeditor": True,
            "utf8output": True,
            "platform": ["Win64"],
            "build": True,
            "cook": True,
            "CookCultures": ["en"],
            "unversionedcookedcontent": True,
            "pak": True,
            "compressed": True,
            "manifests": True,
            "stage": True,
            "package": True,
        }
    if data:
        cultures = data.get("CookedCultures")
        maps = data.get("CookedMaps")
        cooked_platforms = data.get("CookedPlatforms")
        if cultures and (not script or "CookCultures" not in parameters):
            parameters["CookCultures"] = cultures
        if maps and (not script or "map" not in parameters):
            parameters["map"] = maps
        if cooked_platforms and (not script or "platform" not in parameters):
            parameters["platform"] = [
                "Win64" if str(item).casefold() in {"windows", "windowsnoeditor"} else item
                for item in cooked_platforms
            ]
        top_level_booleans = {
            "unversionedcookedcontent": "CookUnversioned",
            "pak": "DeployWithUnrealPak",
            "compressed": "Compressed",
            "skipcookingeditorcontent": "SkipCookingEditorContent",
            "EncryptIniFiles": "EncryptIniFiles",
            "ForDistribution": "ForDistribution",
            "generatepatch": "GeneratePatch",
        }
        for parameter_name, profile_name in top_level_booleans.items():
            if (not script or parameter_name not in parameters) and profile_name in data:
                parameters[parameter_name] = bool(data[profile_name])
    parameters["clientconfig"] = [configuration]
    parameters["serverconfig"] = [configuration]
    parameters["unrealexe"] = str(editor_command)
    if (engine / "Build/InstalledBuild.txt").is_file():
        parameters["installed"] = True
    parameters["stagingdirectory"] = str(output_directory)
    apply_release_parameters(parameters, output_root, output_directory, dlc)
    return parameters


def nested_command_line(value: dict) -> str:
    parts = []
    for key, item in value.items():
        if not key:
            if item not in (None, "", False):
                parts.append(str(item))
            continue
        if item is True:
            parts.append("-{}".format(key))
        elif item in (None, "", False):
            continue
        else:
            text = str(item)
            if any(character.isspace() for character in text):
                text = '"{}"'.format(text.replace('"', '\\"'))
            parts.append("-{}={}".format(key, text))
    return " ".join(parts)


def parameter_token(key: str, value: object) -> str | None:
    if value is True:
        return "-{}".format(key)
    if value in (None, "", False):
        return None
    if isinstance(value, list):
        if not value:
            return None
        text = "+".join(str(item) for item in value if str(item))
        if not text:
            return None
    elif isinstance(value, dict):
        text = nested_command_line(value)
        if not text:
            return None
    else:
        text = str(value)
    return "-{}={}".format(key, text)


def build_command(run_uat: Path, project: Path, parameters: dict) -> list[str]:
    command = [
        str(run_uat),
        "-ScriptsForProject={}".format(project),
        "BuildCookRun",
    ]
    for key, value in parameters.items():
        token = parameter_token(key, value)
        if token:
            command.append(token)
    return command


def log_indicates_cook_failure(log_path: Path) -> bool:
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return COOK_FAILURE_RE.search(content) is not None


def build_cook_retry_command(command: list[str]) -> list[str]:
    retry_command = list(command)
    if not any(item.casefold() == "-skipbuild" for item in retry_command):
        retry_command.append("-skipbuild")
    return retry_command


def run_uat(command: list[str], project: Path, log_path: Path) -> int:
    encoding = locale.getpreferredencoding(False) or "utf-8"
    try:
        process = subprocess.Popen(
            command,
            cwd=str(project.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=encoding,
            errors="replace",
        )
    except OSError as exc:
        raise PackageError("无法启动 RunUAT：{}".format(exc)) from exc
    try:
        with log_path.open("w", encoding="utf-8", newline="\n") as stream:
            if process.stdout is not None:
                for line in process.stdout:
                    print(line, end="")
                    stream.write(line)
        return process.wait()
    except KeyboardInterrupt as exc:
        process.terminate()
        process.wait()
        raise PackageError("用户中止打包，日志：{}".format(log_path)) from exc


def run_with_single_cook_retry(
    command: list[str],
    project: Path,
    log_path: Path,
) -> tuple[int, list[Path]]:
    log_paths = [log_path]
    return_code = run_uat(command, project, log_path)
    if return_code == 0 or not log_indicates_cook_failure(log_path):
        return return_code, log_paths

    retry_command = build_cook_retry_command(command)
    retry_log_path = log_path.with_name(
        "{}-CookRetry{}".format(log_path.stem, log_path.suffix)
    )
    log_paths.append(retry_log_path)
    print("[Cook 重试] 首次 Cook 失败，仅重试一次并跳过 Build")
    print("[Cook 重试日志] {}".format(retry_log_path))
    print("[Cook 重试命令] {}".format(subprocess.list2cmdline(retry_command)))
    return run_uat(retry_command, project, retry_log_path), log_paths


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", nargs="?", help=".uproject 或包含它的工程文件夹")
    parser.add_argument("work_directory", nargs="?", help="输出工作目录；默认从配置提取")
    parser.add_argument(
        "--configuration",
        type=configuration_name,
        default="Shipping",
        metavar="debug|shipping",
        help="构建配置，默认 shipping；debug 使用 DebugGame",
    )
    parser.add_argument("--engine-root", help="Unreal 安装根目录、Engine 目录或 RunUAT.bat")
    parser.add_argument(
        "--dlc",
        action="store_true",
        help="使用 DLC 模式；默认使用非 DLC 模式",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印计划和命令")
    return parser.parse_args(argv)


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv=None) -> int:
    configure_console_encoding()
    args = parse_args(argv)
    try:
        if not args.project:
            raise PackageError("缺少工程文件夹或 .uproject")

        project = resolve_project(args.project)
        project_data = read_json(project)
        engine, run_uat_path = resolve_engine(project, project_data, args.engine_root)
        profile_path, profile_data = select_profile(project, engine)
        if args.dlc and (profile_path is None or profile_data is None):
            raise PackageError("DLC 模式必须匹配包含模式字段的 .ulp2 配置")
        if profile_data is not None:
            apply_packaging_mode(profile_data, args.dlc)
        script = profile_script(profile_data or {})
        editor_command = find_editor_command(engine, script)
        output_root = resolve_output_root(project, profile_data, args.work_directory)
        output_directory = choose_output_directory(output_root, args.dlc)
        parameters = build_parameters(
            project,
            output_root,
            output_directory,
            args.configuration,
            editor_command,
            engine,
            profile_data,
            args.dlc,
        )
        command = build_command(run_uat_path, project, parameters)

        print("[工程] {}".format(project))
        print("[配置文件] {}".format(profile_path or "未匹配，使用默认参数"))
        print("[打包模式] {}".format("DLC" if args.dlc else "非 DLC"))
        if profile_data is not None:
            print(
                "[模式配置] CreateReleaseVersion={}, CreateDLC={}".format(
                    str(profile_data["CreateReleaseVersion"]).lower(),
                    str(profile_data["CreateDLC"]).lower(),
                )
            )
        print("[构建配置] {}".format(args.configuration))
        print("[输出目录] {}".format(output_directory))
        if args.dlc:
            print(
                "[基线来源] {}".format(
                    release_root(output_root) / parameters["basedonreleaseversion"]
                )
            )
        else:
            print(
                "[基线输出] {}".format(
                    release_root(output_root) / parameters["createreleaseversion"]
                )
            )
        print("[命令] {}".format(subprocess.list2cmdline(command)))
        if args.dry_run:
            print("[结果] dry-run，未执行打包")
            return 0

        if output_directory.exists() and any(output_directory.iterdir()):
            raise PackageError("输出目录不是空目录，已禁止覆盖：{}".format(output_directory))
        if profile_path is not None:
            update_profile_packaging_mode(profile_path, args.dlc)
            print("[已更新配置模式] {}".format(profile_path))
        output_directory.mkdir(parents=True, exist_ok=True)
        log_path = output_directory.parent / "{}-BuildCookRun.log".format(output_directory.name)
        print("[日志] {}".format(log_path))
        return_code, log_paths = run_with_single_cook_retry(
            command,
            project,
            log_path,
        )
        if return_code != 0:
            raise PackageError(
                "RunUAT 失败，退出码 {}，日志：{}".format(
                    return_code,
                    ", ".join(str(item) for item in log_paths),
                )
            )
        print("[结果] 打包成功：{}".format(output_directory))
        return 0
    except (OSError, PackageError) as exc:
        print("[错误] {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
