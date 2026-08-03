#!/usr/bin/env python3
"""Import one FBX into a running Unreal Editor with material instances."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path


class ImportFbxError(RuntimeError):
    """Expected import or environment error."""


def load_remote_support():
    support_dir = Path(__file__).resolve().parent.parent / "das-unreal-mcp"
    if not (support_dir / "configure_unreal_mcp.py").is_file():
        raise ImportFbxError("缺少同级 Skill das-unreal-mcp，请先安装完整 Skill 集")
    sys.path.insert(0, str(support_dir))
    try:
        from configure_unreal_mcp import (  # pylint: disable=import-outside-toplevel
            ConfigurationError,
            find_uproject,
            load_json,
            query_unreal_editors,
            resolve_engine_dir,
        )
        from unreal_python_remote import (  # pylint: disable=import-outside-toplevel
            select_project_node,
        )
    except (ImportError, OSError) as exc:
        raise ImportFbxError("无法加载 das-unreal-mcp：{}".format(exc)) from exc
    return {
        "ConfigurationError": ConfigurationError,
        "find_uproject": find_uproject,
        "load_json": load_json,
        "query_unreal_editors": query_unreal_editors,
        "resolve_engine_dir": resolve_engine_dir,
        "select_project_node": select_project_node,
    }


def sanitize_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    name = re.sub(r"_+", "_", name)
    if not name:
        raise ImportFbxError("无法从 FBX 文件名生成合法 Unreal 资产名，请传 --asset-name")
    if name[0].isdigit():
        name = "Mesh_" + name
    return name


def derive_names(source_file: Path, destination_path: str | None, asset_name: str | None):
    source_stem = sanitize_name(source_file.stem)
    base_name = source_stem[3:] if source_stem.casefold().startswith("sm_") else source_stem
    resolved_asset_name = sanitize_name(asset_name) if asset_name else "SM_" + base_name
    resolved_destination = destination_path or "/Game/Imported/Mesh/{}".format(base_name)
    resolved_destination = resolved_destination.replace("\\", "/").rstrip("/")
    if not resolved_destination.startswith("/Game/"):
        raise ImportFbxError("目标目录必须位于 /Game 下：{}".format(resolved_destination))
    if "." in resolved_destination.rsplit("/", 1)[-1]:
        raise ImportFbxError("--destination-path 必须是目录而不是对象路径")
    return resolved_destination, resolved_asset_name


def normalize_parent_path(value: str) -> str:
    path = value.strip()
    if "'" in path and path.endswith("'"):
        path = path.split("'", 1)[1][:-1]
    path = path.replace("\\", "/")
    if not path.startswith("/Game/"):
        raise ImportFbxError("父材质必须使用 /Game 下的资产路径：{}".format(path))
    leaf = path.rsplit("/", 1)[-1]
    if "." not in leaf:
        path = "{}.{}".format(path, leaf)
    return path


def normalize_parameter_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ImportFbxError("BaseColor 纹理参数名不能为空")
    if any(ord(character) < 32 for character in name):
        raise ImportFbxError("BaseColor 纹理参数名包含控制字符")
    return name


def build_unreal_code(config: dict[str, str]) -> str:
    payload = repr(json.dumps(config, ensure_ascii=True))
    return """\
import json
import re
import unreal

_config = json.loads({payload})
_source_file = _config["source_file"]
_destination_path = _config["destination_path"]
_asset_name = _config["asset_name"]
_parent_material_path = _config["parent_material_path"]
_base_color_parameter = _config["base_color_parameter"]
_asset_library = unreal.EditorAssetLibrary


def _object_path(value):
    return value.get_path_name() if value else ""


def _list_destination_assets():
    if not _asset_library.does_directory_exist(_destination_path):
        return set()
    return set(_asset_library.list_assets(_destination_path, recursive=True, include_folder=False))


def _name_tokens(value):
    name = value.get_name() if hasattr(value, "get_name") else str(value)
    normalized = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
    return normalized, set(part for part in normalized.split("_") if part)


def _texture_score(texture, material):
    texture_name, texture_tokens = _name_tokens(texture)
    compact_name = texture_name.replace("_", "")
    score = 0
    if "basecolor" in compact_name:
        score += 120
    elif "albedo" in texture_tokens:
        score += 100
    elif "diffuse" in texture_tokens or "diff" in texture_tokens:
        score += 80
    elif "color" in texture_tokens or "colour" in texture_tokens:
        score += 40
    elif "d" in texture_tokens:
        score += 20

    if texture_tokens.intersection(
        {{"normal", "norm", "roughness", "rough", "metallic", "metal", "orm", "ao", "occlusion", "height", "opacity", "emissive"}}
    ):
        score -= 200

    _, material_tokens = _name_tokens(material)
    material_tokens -= {{"mi", "m", "mat", "material", "instance"}}
    texture_identity_tokens = texture_tokens - {{
        "t", "tex", "texture", "base", "basecolor", "color", "colour", "albedo", "diffuse", "diff", "d"
    }}
    score += 15 * len(material_tokens.intersection(texture_identity_tokens))
    try:
        if texture.get_editor_property("srgb"):
            score += 5
    except Exception:
        pass
    return score


def _select_base_color_texture(material, textures):
    texture_paths = {{_object_path(value) for value in textures}}
    current = unreal.MaterialEditingLibrary.get_material_instance_texture_parameter_value(
        material, _base_color_parameter
    )
    if current and _object_path(current) in texture_paths:
        return current
    if len(textures) == 1:
        return textures[0]

    ranked = sorted(
        [(_texture_score(value, material), _object_path(value), value) for value in textures],
        key=lambda item: (item[0], item[1]),
        reverse=True,
    )
    if not ranked or ranked[0][0] <= 0:
        raise RuntimeError(
            "未找到 BaseColor 纹理：{{}}".format(", ".join(sorted(texture_paths)) or "无")
        )
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        raise RuntimeError(
            "无法唯一确定 {{}} 的 BaseColor 纹理：{{}}".format(
                _object_path(material), ", ".join(item[1] for item in ranked)
            )
        )
    return ranked[0][2]


_target_mesh_path = "{{}}/{{}}.{{}}".format(_destination_path, _asset_name, _asset_name)
if _asset_library.does_asset_exist(_target_mesh_path):
    raise RuntimeError("目标静态模型已存在，已禁止覆盖：{{}}".format(_target_mesh_path))

_parent_material = unreal.load_asset(_parent_material_path)
if not _parent_material:
    raise RuntimeError("父材质不存在：{{}}".format(_parent_material_path))
if not isinstance(_parent_material, unreal.MaterialInterface):
    raise RuntimeError("父材质路径不是 MaterialInterface：{{}}".format(_parent_material_path))
_parent_texture_parameters = [
    str(value) for value in unreal.MaterialEditingLibrary.get_texture_parameter_names(_parent_material)
]
_matching_parameters = [
    value
    for value in _parent_texture_parameters
    if value.casefold() == _base_color_parameter.casefold()
]
if not _matching_parameters:
    raise RuntimeError(
        "父材质没有纹理参数 {{}}；可用参数：{{}}".format(
            _base_color_parameter, ", ".join(_parent_texture_parameters) or "无"
        )
    )
_base_color_parameter = _matching_parameters[0]

_before_assets = _list_destination_assets()
try:
    _pipeline = unreal.InterchangeGenericAssetsPipeline()
    _pipeline.asset_name = _asset_name

    _mesh_pipeline = _pipeline.mesh_pipeline
    _mesh_pipeline.import_static_meshes = True
    _mesh_pipeline.import_skeletal_meshes = False
    _mesh_pipeline.combine_static_meshes_behavior = unreal.InterchangeCombineStaticMeshesBehavior.ALL

    _material_pipeline = _pipeline.material_pipeline
    _material_pipeline.import_materials = True
    _material_pipeline.create_new_materials = True
    _material_pipeline.reuse_existing_materials = False
    _material_pipeline.material_import = unreal.InterchangeMaterialImportOption.IMPORT_AS_MATERIAL_INSTANCES
    _material_pipeline.create_material_instance_for_parent = True
    _material_pipeline.parent_material = unreal.SoftObjectPath(_parent_material_path)

    _pipeline_override = unreal.InterchangePipelineStackOverride()
    _pipeline_override.add_pipeline(_pipeline)

    _task = unreal.AssetImportTask()
    _task.filename = _source_file
    _task.destination_path = _destination_path
    _task.destination_name = _asset_name
    _task.automated = True
    _task.replace_existing = False
    _task.save = True
    _task.options = _pipeline_override

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([_task])
    _imported = list(_task.get_objects())
    if not _imported:
        raise RuntimeError("模型导入失败：{{}}".format(_source_file))

    _static_meshes = [value for value in _imported if isinstance(value, unreal.StaticMesh)]
    if not _static_meshes:
        raise RuntimeError("导入结果中没有静态模型：{{}}".format(_source_file))

    _material_instances = {{}}
    _slot_count = 0
    for _mesh in _static_meshes:
        _slots = list(_mesh.get_editor_property("static_materials"))
        if not _slots:
            raise RuntimeError("静态模型没有可验证的材质槽：{{}}".format(_object_path(_mesh)))
        for _slot_index, _slot in enumerate(_slots):
            _slot_count += 1
            _material = _slot.get_editor_property("material_interface")
            if not _material:
                raise RuntimeError(
                    "材质槽为空：{{}}[{{}}]".format(_object_path(_mesh), _slot_index)
                )
            try:
                _actual_parent = _material.get_editor_property("parent")
            except Exception as _error:
                raise RuntimeError(
                    "材质槽不是材质实例：{{}}[{{}}] -> {{}}".format(
                        _object_path(_mesh), _slot_index, _object_path(_material)
                    )
                ) from _error
            if _object_path(_actual_parent) != _object_path(_parent_material):
                raise RuntimeError(
                    "材质实例父级不匹配：{{}}，实际 {{}}，预期 {{}}".format(
                        _object_path(_material),
                        _object_path(_actual_parent),
                        _object_path(_parent_material),
                    )
                )
            _material_instances[_object_path(_material)] = _material

    _after_assets = _list_destination_assets()
    _imported_textures = {{}}
    for _value in _imported:
        if isinstance(_value, unreal.Texture):
            _imported_textures[_object_path(_value)] = _value
    for _asset_path in _after_assets - _before_assets:
        _value = unreal.load_asset(_asset_path)
        if isinstance(_value, unreal.Texture):
            _imported_textures[_object_path(_value)] = _value
    if not _imported_textures:
        raise RuntimeError("FBX 没有导入可绑定的 BaseColor 纹理")

    _base_color_bindings = {{}}
    _textures = list(_imported_textures.values())
    for _material_path, _material in _material_instances.items():
        _base_color_texture = _select_base_color_texture(_material, _textures)
        unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(
            _material, _base_color_parameter, _base_color_texture
        )
        _actual_texture = unreal.MaterialEditingLibrary.get_material_instance_texture_parameter_value(
            _material, _base_color_parameter
        )
        if _object_path(_actual_texture) != _object_path(_base_color_texture):
            raise RuntimeError(
                "BaseColor 参数绑定失败：{{}}.{{}}".format(
                    _material_path, _base_color_parameter
                )
            )
        if not _asset_library.save_asset(_material_path, False):
            raise RuntimeError("材质实例保存失败：{{}}".format(_material_path))
        _base_color_bindings[_material_path] = _object_path(_base_color_texture)

    _result = {{
        "source_file": _source_file,
        "destination_path": _destination_path,
        "asset_name": _asset_name,
        "static_meshes": [_object_path(value) for value in _static_meshes],
        "material_instances": sorted(_material_instances),
        "material_slot_count": _slot_count,
        "parent_material": _object_path(_parent_material),
        "base_color_parameter": _base_color_parameter,
        "base_color_bindings": _base_color_bindings,
        "saved": True,
    }}
    print("FBX_IMPORT_RESULT=" + json.dumps(_result, ensure_ascii=False, sort_keys=True))
except Exception:
    _after_assets = _list_destination_assets()
    _new_assets = sorted(_after_assets - _before_assets, reverse=True)
    for _asset_path in _new_assets:
        try:
            _asset_library.delete_asset(_asset_path)
        except Exception as _rollback_error:
            unreal.log_error("回滚资产失败：{{}}（{{}}）".format(_asset_path, _rollback_error))
    raise
""".format(payload=payload)


def print_remote_result(result: dict) -> int:
    for entry in result.get("output") or []:
        stream = sys.stderr if entry.get("type") == "Error" else sys.stdout
        stream.write(entry.get("output", "") + "\n")
    if result.get("success"):
        return 0
    print("[错误] Unreal 执行失败：{}".format(result.get("result")), file=sys.stderr)
    return 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fbx_path", help="本地 FBX 文件路径")
    parser.add_argument("parent_material_path", help="Unreal 父材质对象路径")
    parser.add_argument("base_color_parameter", help="父材质的 BaseColor 纹理参数名")
    parser.add_argument("--project", default=".", help=".uproject 或包含它的目录")
    parser.add_argument(
        "--destination-path", help="导入目录，默认 /Game/Imported/Mesh/<FBX名>"
    )
    parser.add_argument("--asset-name", help="静态模型名，默认 SM_<FBX名>")
    parser.add_argument("--engine-root", help="UE 安装根目录或 Engine 目录")
    parser.add_argument("--timeout", type=float, default=15.0, help="远程节点发现超时秒数")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    connection = None
    try:
        source_file = Path(args.fbx_path).expanduser().resolve()
        if not source_file.is_file():
            raise ImportFbxError("FBX 文件不存在：{}".format(source_file))
        if source_file.suffix.casefold() != ".fbx":
            raise ImportFbxError("输入文件不是 FBX：{}".format(source_file))

        destination_path, asset_name = derive_names(
            source_file, args.destination_path, args.asset_name
        )
        parent_material_path = normalize_parent_path(args.parent_material_path)
        base_color_parameter = normalize_parameter_name(args.base_color_parameter)

        support = load_remote_support()
        uproject = support["find_uproject"](args.project)
        project_data = support["load_json"](uproject)
        try:
            editor_records = support["query_unreal_editors"]()
        except support["ConfigurationError"]:
            editor_records = ()
        engine_dir = support["resolve_engine_dir"](
            project_data,
            editor_records=editor_records,
            override=args.engine_root,
        )
        remote_module_dir = (
            engine_dir / "Plugins/Experimental/PythonScriptPlugin/Content/Python"
        )
        if not (remote_module_dir / "remote_execution.py").is_file():
            raise ImportFbxError("找不到 remote_execution.py：{}".format(remote_module_dir))
        sys.path.insert(0, str(remote_module_dir))
        import remote_execution  # pylint: disable=import-outside-toplevel

        config = remote_execution.RemoteExecutionConfig()
        config.multicast_group_endpoint = ("239.0.0.1", 6766)
        config.multicast_bind_address = "127.0.0.1"
        connection = remote_execution.RemoteExecution(config)
        connection.start()

        deadline = time.time() + args.timeout
        node = None
        last_error = None
        while time.time() < deadline:
            try:
                node = support["select_project_node"](
                    connection.remote_nodes, uproject.parent, uproject.stem
                )
                break
            except support["ConfigurationError"] as exc:
                last_error = exc
                time.sleep(0.25)
        if node is None:
            raise last_error or ImportFbxError(
                "未发现 Unreal Python 远程节点；请先运行 das-unreal-mcp 并重启编辑器"
            )

        connection.open_command_connection(node["node_id"])
        unreal_code = build_unreal_code(
            {
                "source_file": str(source_file),
                "destination_path": destination_path,
                "asset_name": asset_name,
                "parent_material_path": parent_material_path,
                "base_color_parameter": base_color_parameter,
            }
        )
        result = connection.run_command(
            unreal_code,
            unattended=True,
            exec_mode=remote_execution.MODE_EXEC_FILE,
            raise_on_failure=False,
        )
        return print_remote_result(result)
    except (ImportFbxError, OSError, RuntimeError) as exc:
        print("[错误] {}".format(exc), file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            try:
                connection.stop()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
