#!/usr/bin/env python3
"""Package Unreal Engine plugins into a timestamped directory and install them."""

import argparse
import json
import locale
import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


CONFIG_PATH = Path(__file__).with_name("plugin_pack_config.json")
SKIPPED_DIRS = {
    ".git",
    ".svn",
    ".vs",
    "Binaries",
    "DerivedDataCache",
    "HostProject",
    "Intermediate",
    "Saved",
}
DEPENDENCY_WARNING_RE = re.compile(
    r"Plugin\s+'([^']+)'\s+does not list plugin\s+'([^']+)'\s+as a dependency",
    re.IGNORECASE,
)
QUOTED_TOKEN_RE = re.compile(r"[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']")
SAFE_TIMESTAMP_RE = re.compile(r"^[0-9A-Za-z._-]+$")


class PackError(RuntimeError):
    pass


@dataclass
class PluginInfo:
    descriptor: Path
    directory: Path
    name: str
    data: dict
    encoding: str = "utf-8"
    request_name: str = ""


def normalize_name(value):
    return "".join(char.casefold() for char in str(value) if char.isalnum())


def load_fixed_plugins():
    try:
        content, _ = read_text_auto(CONFIG_PATH)
        data = json.loads(content)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackError("无法读取 Skill 插件配置：{} ({})".format(CONFIG_PATH, exc)) from exc
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, list) or not plugins:
        raise PackError("Skill 插件配置的 plugins 必须是非空数组：{}".format(CONFIG_PATH))
    normalized = []
    seen = set()
    for item in plugins:
        if not isinstance(item, str) or not item.strip():
            raise PackError("Skill 插件配置包含无效名称：{}".format(CONFIG_PATH))
        name = item.strip()
        key = normalize_name(name)
        if not key or key in seen:
            raise PackError("Skill 插件配置包含重复或无效名称：{}".format(name))
        seen.add(key)
        normalized.append(name)
    return normalized


def resolve_existing(value, label):
    path = Path(value).expanduser()
    try:
        return path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise PackError("{}不存在：{}".format(label, path)) from exc
    except OSError as exc:
        raise PackError("无法访问{}：{} ({})".format(label, path, exc)) from exc


def is_relative_to(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def descriptor_paths(root, excluded_roots=()):
    if root.is_file():
        if root.suffix.casefold() != ".uplugin":
            raise PackError("插件源文件不是 .uplugin：{}".format(root))
        return [root]

    excluded = [Path(item).resolve() for item in excluded_roots]
    found = []
    for current, directories, files in os.walk(str(root), followlinks=False):
        current_path = Path(current)
        kept = []
        for directory in directories:
            candidate = (current_path / directory).resolve()
            if directory in SKIPPED_DIRS:
                continue
            if any(is_relative_to(candidate, item) for item in excluded):
                continue
            kept.append(directory)
        directories[:] = kept
        for filename in files:
            if filename.casefold().endswith(".uplugin"):
                found.append((current_path / filename).resolve())
    return sorted(set(found), key=lambda item: str(item).casefold())


def read_text_auto(path):
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        encoding = locale.getpreferredencoding(False) or "utf-8"
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError as exc:
            raise UnicodeError("不支持的文本编码") from exc


def load_plugin(descriptor, strict=True):
    try:
        content, encoding = read_text_auto(descriptor)
        data = json.loads(content)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        if strict:
            raise PackError("无法解析插件描述文件：{} ({})".format(descriptor, exc)) from exc
        return None
    if not isinstance(data, dict):
        if strict:
            raise PackError("插件描述文件根节点不是对象：{}".format(descriptor))
        return None
    return PluginInfo(
        descriptor=descriptor,
        directory=descriptor.parent,
        name=descriptor.stem,
        data=data,
        encoding=encoding,
    )


def plugin_aliases(plugin):
    aliases = {
        normalize_name(plugin.name),
        normalize_name(plugin.directory.name),
    }
    if normalize_name(plugin.name) == "cesiumforunreal":
        aliases.add("cesiumunreal")
    return aliases


def direct_plugin_from_request(source_root, request):
    path = Path(request).expanduser()
    if not path.is_absolute():
        path = source_root / path
    if not path.exists():
        return None
    path = path.resolve()
    if path.is_file():
        return load_plugin(path)
    direct = sorted(path.glob("*.uplugin"))
    if len(direct) != 1:
        detail = "未找到 .uplugin" if not direct else "找到多个 .uplugin"
        raise PackError("指定插件目录根部{}：{}".format(detail, path))
    return load_plugin(direct[0].resolve())


def select_plugins(source_root, candidates, requests):
    selected = []
    used = set()
    for request in requests:
        direct = direct_plugin_from_request(source_root, request)
        matches = [direct] if direct is not None else [
            item for item in candidates if normalize_name(request) in plugin_aliases(item)
        ]
        unique = {str(item.descriptor).casefold(): item for item in matches}
        matches = list(unique.values())
        if not matches:
            raise PackError("未找到插件 {}，源目录：{}".format(request, source_root))
        if len(matches) > 1:
            raise PackError(
                "固定插件 {} 匹配多个目录，请整理源目录使其唯一：{}".format(
                    request, ", ".join(str(item.directory) for item in matches)
                )
            )
        plugin = matches[0]
        key = str(plugin.descriptor).casefold()
        if key not in used:
            plugin.request_name = request
            selected.append(plugin)
            used.add(key)
    return selected


def resolve_engine(value):
    original = resolve_existing(value, "Unreal Engine 目录")
    if original.is_file():
        if original.name.casefold() != "runuat.bat":
            raise PackError("引擎文件不是 RunUAT.bat：{}".format(original))
        engine = original.parents[2]
        return engine, original

    candidates = [
        original,
        original / "Engine",
        original / "Windows" / "Engine",
        original / "Engine" / "Windows" / "Engine",
    ]
    checked = []
    for engine in candidates:
        run_uat = engine / "Build" / "BatchFiles" / "RunUAT.bat"
        checked.append(str(run_uat))
        if run_uat.is_file():
            return engine.resolve(), run_uat.resolve()
    raise PackError("未找到 RunUAT.bat，已检查：{}".format(", ".join(checked)))


def modules_from_plugin(plugin):
    result = set()
    modules = plugin.data.get("Modules", [])
    if isinstance(modules, list):
        for item in modules:
            if isinstance(item, dict) and isinstance(item.get("Name"), str):
                result.add(item["Name"])
    return result


def engine_module_owners(engine_dir):
    owners = {}
    plugins_dir = engine_dir / "Plugins"
    if not plugins_dir.is_dir():
        return owners
    for descriptor in descriptor_paths(plugins_dir):
        plugin = load_plugin(descriptor, strict=False)
        if plugin is None:
            continue
        for module in modules_from_plugin(plugin):
            owners.setdefault(module.casefold(), plugin.name)
    return owners


def build_module_owners(engine_dir, selected):
    owners = engine_module_owners(engine_dir)
    for plugin in selected:
        for module in modules_from_plugin(plugin):
            owners[module.casefold()] = plugin.name
    return owners


def referenced_plugin_names(plugin, module_owners):
    dependencies = set()
    source_dir = plugin.directory / "Source"
    if not source_dir.is_dir():
        return dependencies
    for build_file in source_dir.rglob("*.Build.cs"):
        try:
            content, _ = read_text_auto(build_file)
        except (OSError, UnicodeError):
            continue
        for token in QUOTED_TOKEN_RE.findall(content):
            owner = module_owners.get(token.casefold())
            if owner and owner.casefold() != plugin.name.casefold():
                dependencies.add(owner)
    return dependencies


def write_text(path, content, encoding="utf-8"):
    with path.open("w", encoding=encoding, newline="\n") as stream:
        stream.write(content)


def write_descriptor(plugin):
    backup = plugin.descriptor.with_suffix(plugin.descriptor.suffix + ".autofix.bak")
    if not backup.exists():
        shutil.copy2(str(plugin.descriptor), str(backup))
    temporary = plugin.descriptor.with_name(".{}.autofix.tmp".format(plugin.descriptor.name))
    payload = json.dumps(plugin.data, ensure_ascii=False, indent="\t") + "\n"
    try:
        write_text(temporary, payload, plugin.encoding)
        os.replace(str(temporary), str(plugin.descriptor))
    finally:
        if temporary.exists():
            temporary.unlink()
    return backup


def ensure_dependencies(plugin, dependency_names, dry_run=False):
    wanted = sorted(
        {
            name
            for name in dependency_names
            if name and name.casefold() != plugin.name.casefold()
        },
        key=str.casefold,
    )
    if not wanted:
        return []
    entries = plugin.data.get("Plugins")
    if entries is None:
        entries = []
        plugin.data["Plugins"] = entries
    if not isinstance(entries, list):
        raise PackError("{}.Plugins 不是数组，无法自动修复".format(plugin.descriptor))
    existing = {}
    for item in entries:
        if isinstance(item, dict) and isinstance(item.get("Name"), str):
            existing[item["Name"].casefold()] = item
    changes = []
    for name in wanted:
        item = existing.get(name.casefold())
        if item is None:
            entries.append({"Name": name, "Enabled": True})
            existing[name.casefold()] = entries[-1]
            changes.append("新增 {}".format(name))
        elif item.get("Enabled") is not True:
            item["Enabled"] = True
            changes.append("启用 {}".format(item["Name"]))
    if changes and not dry_run:
        backup = write_descriptor(plugin)
        print("[自动修复] {}：{}；备份 {}".format(plugin.name, "、".join(changes), backup))
    elif changes:
        print("[可自动修复] {}：{}".format(plugin.name, "、".join(changes)))
    return changes


def repair_declared_dependencies(selected, module_owners, dry_run=False):
    changes = []
    for plugin in selected:
        referenced = referenced_plugin_names(plugin, module_owners)
        plugin_changes = ensure_dependencies(plugin, referenced, dry_run=dry_run)
        changes.extend((plugin.name, item) for item in plugin_changes)
    return changes


def selected_dependency_names(plugin, selected):
    aliases = {}
    for item in selected:
        for alias in plugin_aliases(item):
            aliases[alias] = item.name
        aliases[normalize_name(item.name)] = item.name
    result = set()
    entries = plugin.data.get("Plugins", [])
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("Name"), str):
                continue
            dependency = aliases.get(normalize_name(entry["Name"]))
            if dependency and dependency.casefold() != plugin.name.casefold():
                result.add(dependency.casefold())
    return result


def dependency_order(selected):
    remaining = list(selected)
    ordered = []
    completed = set()
    while remaining:
        ready = [
            plugin
            for plugin in remaining
            if selected_dependency_names(plugin, selected).issubset(completed)
        ]
        if not ready:
            raise PackError(
                "所选插件存在循环依赖，无法确定打包顺序：{}".format(
                    ", ".join(plugin.name for plugin in remaining)
                )
            )
        for plugin in ready:
            ordered.append(plugin)
            completed.add(plugin.name.casefold())
            remaining.remove(plugin)
    return ordered


def unique_session_dir(output_root, timestamp, create=True):
    if not SAFE_TIMESTAMP_RE.fullmatch(timestamp):
        raise PackError("时间目录名只能包含字母、数字、点、下划线和连字符：{}".format(timestamp))
    candidate = output_root / timestamp
    if create:
        suffix = 1
        while candidate.exists():
            candidate = output_root / "{}-{:02d}".format(timestamp, suffix)
            suffix += 1
        candidate.mkdir(parents=True)
    return candidate


def uat_command(run_uat, plugin, package_dir, platforms, rocket, extra_args):
    command = [
        str(run_uat),
        "BuildPlugin",
        "-Plugin={}".format(plugin.descriptor),
        "-Package={}".format(package_dir),
        "-TargetPlatforms={}".format(platforms),
    ]
    if rocket:
        command.append("-Rocket")
    command.extend(extra_args)
    return command


def run_uat(command, log_file):
    display = subprocess.list2cmdline(command)
    print("[命令] {}".format(display))
    encoding = locale.getpreferredencoding(False) or "utf-8"
    output = []
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=encoding,
            errors="replace",
        )
    except OSError as exc:
        raise PackError("无法启动 RunUAT：{}".format(exc)) from exc
    try:
        with log_file.open("w", encoding="utf-8", newline="\n") as stream:
            if process.stdout is not None:
                for line in process.stdout:
                    print(line, end="")
                    stream.write(line)
                    output.append(line)
        return_code = process.wait()
    except KeyboardInterrupt:
        process.terminate()
        process.wait()
        raise
    return return_code, "".join(output)


def warning_repairs(output, selected, dry_run=False):
    by_name = {plugin.name.casefold(): plugin for plugin in selected}
    changes = []
    for owner, dependency in DEPENDENCY_WARNING_RE.findall(output):
        plugin = by_name.get(owner.casefold())
        if plugin is None:
            continue
        repaired = ensure_dependencies(plugin, [dependency], dry_run=dry_run)
        changes.extend((plugin.name, item) for item in repaired)
    return changes


def remove_package_dir(package_dir, session_dir):
    if not package_dir.exists():
        return
    resolved = package_dir.resolve()
    if resolved.parent != session_dir.resolve():
        raise PackError("拒绝清理时间目录之外的路径：{}".format(resolved))
    shutil.rmtree(str(resolved))


def packaged_plugin_root(package_dir, plugin):
    direct = sorted(package_dir.glob("*.uplugin"))
    if len(direct) == 1:
        return package_dir
    matches = [
        path
        for path in package_dir.rglob("*.uplugin")
        if path.stem.casefold() == plugin.name.casefold()
        and not any(part in SKIPPED_DIRS for part in path.relative_to(package_dir).parts[:-1])
    ]
    if len(matches) == 1:
        return matches[0].parent
    raise PackError(
        "打包命令成功，但无法确定 {} 的成品根目录：{}".format(plugin.name, package_dir)
    )


def package_plugin(
    plugin,
    selected,
    run_uat_path,
    session_dir,
    platforms,
    rocket,
    extra_args,
    max_attempts,
    auto_fix,
):
    package_dir = session_dir / plugin.directory.name
    logs_dir = session_dir / "_logs"
    logs_dir.mkdir(exist_ok=True)
    logs = []
    for attempt in range(1, max_attempts + 1):
        remove_package_dir(package_dir, session_dir)
        log_file = logs_dir / "{}-attempt-{}.log".format(plugin.name, attempt)
        logs.append(log_file)
        command = uat_command(
            run_uat_path, plugin, package_dir, platforms, rocket, extra_args
        )
        print("[打包] {}，第 {}/{} 次".format(plugin.name, attempt, max_attempts))
        return_code, output = run_uat(command, log_file)
        repairs = warning_repairs(output, selected) if auto_fix else []
        if repairs and attempt < max_attempts:
            print("[重试] 已根据 UBT 依赖警告修复描述文件")
            continue
        if return_code != 0:
            raise PackError(
                "{} 打包失败（退出码 {}）；日志：{}".format(
                    plugin.name, return_code, log_file
                )
            )
        if repairs:
            raise PackError(
                "{} 已自动修复依赖，但重试次数不足；增大 --max-attempts 后重试，日志：{}".format(
                    plugin.name, log_file
                )
            )
        root = packaged_plugin_root(package_dir, plugin)
        print("[打包完成] {}：{}".format(plugin.name, root))
        return root, logs
    raise PackError("{} 达到最大重试次数".format(plugin.name))


def unique_backup_path(destination, timestamp):
    candidate = destination.with_name("{}.backup-{}".format(destination.name, timestamp))
    index = 1
    while os.path.lexists(str(candidate)):
        candidate = destination.with_name(
            "{}.backup-{}-{:02d}".format(destination.name, timestamp, index)
        )
        index += 1
    return candidate


def install_plugin(packaged_root, plugin, install_root, timestamp):
    install_root.mkdir(parents=True, exist_ok=True)
    destination = install_root / plugin.directory.name
    staging = install_root / ".{}.installing-{}".format(
        plugin.directory.name, uuid.uuid4().hex
    )
    backup = None
    try:
        shutil.copytree(str(packaged_root), str(staging), symlinks=True)
        if os.path.lexists(str(destination)):
            backup = unique_backup_path(destination, timestamp)
            destination.rename(backup)
        staging.rename(destination)
    except Exception:
        if os.path.lexists(str(staging)):
            if staging.is_dir() and not staging.is_symlink():
                shutil.rmtree(str(staging))
            else:
                staging.unlink()
        if backup is not None and not os.path.lexists(str(destination)):
            backup.rename(destination)
        raise
    print("[部署完成] {}：{}".format(plugin.name, destination))
    if backup is not None:
        print("[原目录备份] {}".format(backup))
    return destination, backup


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="包含 Skill 固定插件清单的源目录")
    parser.add_argument("engine", help="Unreal Engine 根目录、Engine 目录或 RunUAT.bat")
    parser.add_argument("output", help="打包输出根目录；脚本会在其下创建时间目录")
    parser.add_argument("--target-platforms", default="Win64", help="UAT 目标平台")
    parser.add_argument("--install-dir", help="部署目录，默认 Engine/Plugins/Marketplace")
    parser.add_argument("--timestamp", help="指定时间目录名，默认 yyyyMMddHHmm")
    parser.add_argument("--max-attempts", type=int, default=3, help="每个插件最大尝试次数")
    parser.add_argument("--uat-arg", action="append", default=[], help="附加 UAT 参数，可重复")
    parser.add_argument("--no-install", action="store_true", help="不复制成品到引擎")
    parser.add_argument("--no-auto-fix", action="store_true", help="不自动修改 .uplugin 依赖")
    parser.add_argument("--no-rocket", action="store_true", help="不向 BuildPlugin 传入 -Rocket")
    parser.add_argument("--dry-run", action="store_true", help="仅检查并输出计划，不修改或打包")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        if os.name != "nt" and not args.dry_run:
            raise PackError("此脚本仅支持 Windows")
        if args.max_attempts < 1:
            raise PackError("--max-attempts 必须大于 0")
        source = resolve_existing(args.source, "插件源路径")
        if not source.is_dir():
            raise PackError("插件源路径必须是包含固定插件清单的目录：{}".format(source))
        engine_dir, run_uat_path = resolve_engine(args.engine)
        output_root = Path(args.output).expanduser().resolve()
        descriptors = descriptor_paths(source, excluded_roots=(output_root, engine_dir))
        candidates = [load_plugin(path) for path in descriptors]
        fixed_plugins = load_fixed_plugins()
        selected = select_plugins(source, candidates, fixed_plugins)
        module_owners = build_module_owners(engine_dir, selected)
        repair_declared_dependencies(
            selected,
            module_owners,
            dry_run=args.dry_run or args.no_auto_fix,
        )
        ordered = dependency_order(selected)
        timestamp = args.timestamp or datetime.now().strftime("%Y%m%d%H%M")
        session_dir = unique_session_dir(output_root, timestamp, create=not args.dry_run)
        install_root = (
            Path(args.install_dir).expanduser().resolve()
            if args.install_dir
            else engine_dir / "Plugins" / "Marketplace"
        )

        print("[引擎] {}".format(engine_dir))
        print("[RunUAT] {}".format(run_uat_path))
        print("[时间目录] {}".format(session_dir))
        print("[固定插件] {}".format(", ".join(fixed_plugins)))
        print("[打包顺序] {}".format(" -> ".join(item.name for item in ordered)))
        if args.dry_run:
            for plugin in ordered:
                package_dir = session_dir / plugin.directory.name
                print(
                    "[计划命令] {}".format(
                        subprocess.list2cmdline(
                            uat_command(
                                run_uat_path,
                                plugin,
                                package_dir,
                                args.target_platforms,
                                not args.no_rocket,
                                args.uat_arg,
                            )
                        )
                    )
                )
                if not args.no_install:
                    print("[计划部署] {}".format(install_root / plugin.directory.name))
            print("[完成] dry-run 未修改文件")
            return 0

        results = []
        for plugin in ordered:
            packaged_root, logs = package_plugin(
                plugin=plugin,
                selected=selected,
                run_uat_path=run_uat_path,
                session_dir=session_dir,
                platforms=args.target_platforms,
                rocket=not args.no_rocket,
                extra_args=args.uat_arg,
                max_attempts=args.max_attempts,
                auto_fix=not args.no_auto_fix,
            )
            destination = None
            backup = None
            if not args.no_install:
                destination, backup = install_plugin(
                    packaged_root, plugin, install_root, session_dir.name
                )
            results.append(
                {
                    "plugin": plugin.name,
                    "source": str(plugin.directory),
                    "package": str(packaged_root),
                    "install": str(destination) if destination else None,
                    "backup": str(backup) if backup else None,
                    "logs": [str(item) for item in logs],
                }
            )
        summary = session_dir / "_package-summary.json"
        write_text(summary, json.dumps(results, ensure_ascii=False, indent=2) + "\n")
        print("[摘要] {}".format(summary))
        print("[完成] {} 个插件全部打包成功".format(len(results)))
        return 0
    except PackError as exc:
        print("[错误] {}".format(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("[中止] 用户取消", file=sys.stderr)
        return 130
    except (OSError, shutil.Error) as exc:
        print("[错误] 文件操作失败：{}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
