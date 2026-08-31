#!/usr/bin/env python3
"""Launch UnrealEditor-Cmd and import one OBJ or an OBJ directory."""

from __future__ import print_function

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


class LaunchError(RuntimeError):
    """Configuration or launch error that can be shown directly to the user."""


def _load_json(config_path):
    try:
        with config_path.open("r", encoding="utf-8-sig") as config_file:
            config = json.load(config_file)
    except (OSError, ValueError) as error:
        raise LaunchError("无法读取 JSON 配置 {}：{}".format(config_path, error))
    if not isinstance(config, dict):
        raise LaunchError("JSON 根节点必须是对象：{}".format(config_path))
    return config


def _resolve_config_path(value, config_dir, label):
    if not isinstance(value, str) or not value.strip():
        raise LaunchError("请在 JSON 中配置 {}".format(label))
    expanded = os.path.expandvars(os.path.expanduser(value.strip()))
    path = Path(expanded)
    if not path.is_absolute():
        path = config_dir / path
    return path.resolve()


def _require_file(path, label):
    if not path.is_file():
        raise LaunchError("{}不存在：{}".format(label, path))


def _collect_obj_files(source_path):
    if source_path.is_file():
        if source_path.suffix.casefold() != ".obj":
            raise LaunchError("输入文件扩展名必须是 .obj：{}".format(source_path))
        return [source_path]
    if source_path.is_dir():
        obj_files = sorted(
            (
                value
                for value in source_path.rglob("*")
                if value.is_file() and value.suffix.casefold() == ".obj"
            ),
            key=lambda value: str(value).casefold(),
        )
        if not obj_files:
            raise LaunchError("输入目录内没有 OBJ 文件：{}".format(source_path))
        return obj_files
    raise LaunchError("输入路径不存在：{}".format(source_path))


def _copy_material_content(script_dir, project_file):
    source_directory = script_dir / "DasMaterial"
    if not source_directory.is_dir():
        raise LaunchError("默认材质目录不存在：{}".format(source_directory))
    parent_material_file = source_directory / "MI_Model.uasset"
    _require_file(parent_material_file, "默认母材质")

    project_content_directory = project_file.parent / "Content"
    project_content_directory.mkdir(parents=True, exist_ok=True)
    destination_directory = project_content_directory / source_directory.name
    shutil.copytree(
        str(source_directory),
        str(destination_directory),
        copy_function=shutil.copy2,
        dirs_exist_ok=True,
    )
    return destination_directory


def _parse_string_list(config, property_name):
    values = config.get(property_name, [])
    if not isinstance(values, list) or not all(
        isinstance(value, str) and value for value in values
    ):
        raise LaunchError("{} 必须是字符串数组，元素不能为空".format(property_name))
    return values


def _parse_args(argv=None):
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_path", help="要导入的 .obj 文件或目录")
    parser.add_argument(
        "--config",
        default=str(script_dir / "import_obj.json"),
        help="JSON 配置路径",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    try:
        source_path = Path(args.source_path).expanduser().resolve()
        obj_files = _collect_obj_files(source_path)

        config_path = Path(args.config).expanduser().resolve()
        _require_file(config_path, "JSON 配置")
        config = _load_json(config_path)
        config_dir = config_path.parent

        project_file = _resolve_config_path(
            config.get("project_file"), config_dir, "project_file"
        )
        editor_cmd = _resolve_config_path(
            config.get("unreal_editor_cmd"), config_dir, "unreal_editor_cmd"
        )
        _require_file(project_file, "Unreal 项目")
        if project_file.suffix.casefold() != ".uproject":
            raise LaunchError("project_file 必须指向 .uproject：{}".format(project_file))
        _require_file(editor_cmd, "UnrealEditor-Cmd.exe")

        unreal_script = Path(__file__).resolve().with_name("import_obj.py")
        _require_file(unreal_script, "Unreal Python 脚本")
        material_directory = _copy_material_content(unreal_script.parent, project_file)

        enabled_plugins = _parse_string_list(config, "enabled_plugins")
        commandlet_arguments = _parse_string_list(config, "commandlet_arguments")

        command = [
            str(editor_cmd),
            str(project_file),
            "-run=PythonScript",
            (
                "-Script=__import__('runpy').run_path("
                "__import__('os').environ['UE_OBJ_IMPORT_SCRIPT'],run_name='__main__')"
            ),
        ]
        if enabled_plugins:
            command.append("-EnablePlugins={}".format(",".join(enabled_plugins)))
        command.extend(commandlet_arguments)

        environment = os.environ.copy()
        environment["UE_OBJ_IMPORT_SOURCE"] = str(source_path)
        environment["UE_OBJ_IMPORT_CONFIG"] = str(config_path)
        environment["UE_OBJ_IMPORT_SCRIPT"] = str(unreal_script)

        print("[OBJ] 输入：{}".format(source_path))
        print("[OBJ] 文件数：{}".format(len(obj_files)))
        print("[OBJ] 项目：{}".format(project_file))
        print("[OBJ] 默认材质：{}".format(material_directory))
        print("[OBJ] 启动：{}".format(subprocess.list2cmdline(command)))
        result = subprocess.run(
            command,
            cwd=str(unreal_script.parent),
            env=environment,
            check=False,
        )
        if result.returncode != 0:
            raise LaunchError("Unreal 导入失败，退出码 {}".format(result.returncode))
        return 0
    except (LaunchError, OSError) as error:
        print("[错误] {}".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
