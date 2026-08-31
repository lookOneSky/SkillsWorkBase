"""Run inside Unreal Editor and import the OBJ supplied by the launcher."""

from __future__ import print_function

import json
import os
import re
from datetime import datetime
from pathlib import Path

import unreal


class ObjImportError(RuntimeError):
    """Expected import or configuration error."""


_TEXTURE_PARAMETER_PROPERTIES = (
    "base_diffuse_texture_name",
    "base_normal_texture_name",
    "base_emmisive_texture_name",
    "base_specular_texture_name",
    "base_opacity_texture_name",
)

_VECTOR_PARAMETER_PROPERTIES = (
    "base_color_name",
    "base_emissive_color_name",
)

_LEGACY_MATERIAL_MOUNT = "/DasTest/"


def _load_json(config_path):
    try:
        with config_path.open("r", encoding="utf-8-sig") as config_file:
            config = json.load(config_file)
    except (OSError, ValueError) as error:
        raise ObjImportError("无法读取 JSON 配置 {}：{}".format(config_path, error))
    if not isinstance(config, dict):
        raise ObjImportError("JSON 根节点必须是对象：{}".format(config_path))
    return config


def _register_legacy_material_mount():
    """Resolve dependencies authored under the material bundle's old mount."""
    content_directory = os.path.abspath(unreal.Paths.project_content_dir()).replace(
        "\\", "/"
    )
    if not content_directory.endswith("/"):
        content_directory += "/"
    unreal.SystemLibrary.execute_console_command(
        None,
        "PackageName.RegisterMountPoint {} {}".format(
            _LEGACY_MATERIAL_MOUNT, content_directory
        ),
    )
    unreal.log(
        "OBJ_IMPORT_MATERIAL_MOUNT={} -> {}".format(
            _LEGACY_MATERIAL_MOUNT, content_directory
        )
    )


def _sanitize_asset_name(value):
    characters = []
    for character in value.strip():
        characters.append(character if character.isalnum() or character == "_" else "_")
    name = re.sub(r"_+", "_", "".join(characters)).strip("_")
    if not name:
        raise ObjImportError("无法从 OBJ 文件名生成合法的 Unreal 资产名")
    if name[0].isdigit():
        name = "Mesh_" + name
    return name


def _normalize_game_directory(value, batch_timestamp):
    if not isinstance(value, str) or not value.strip():
        raise ObjImportError("destination_root 不能为空")
    path = (
        value.strip()
        .replace("{timestamp}", batch_timestamp)
        .replace("{date}", batch_timestamp[:8])
        .replace("\\", "/")
        .rstrip("/")
    )
    if path.casefold().startswith("content/"):
        path = "/Game/" + path[len("Content/") :]
    elif path.casefold() == "content":
        path = "/Game"
    elif path.casefold().startswith("game/"):
        path = "/" + path
    if path != "/Game" and not path.startswith("/Game/"):
        raise ObjImportError("destination_root 必须位于 Content（/Game）下：{}".format(path))
    return path


def _normalize_object_path(value):
    if not isinstance(value, str) or not value.strip():
        raise ObjImportError("parent_material 不能为空")
    path = value.strip()
    if "'" in path and path.endswith("'"):
        path = path.split("'", 1)[1][:-1]
    path = path.replace("\\", "/")
    if path.casefold().startswith("game/"):
        path = "/" + path
    if not path.startswith("/Game/"):
        raise ObjImportError("parent_material 必须是 /Game 下的对象路径：{}".format(path))
    leaf = path.rsplit("/", 1)[-1]
    if "." not in leaf:
        path = "{}.{}".format(path, leaf)
    return path


def _coerce_editor_value(target, property_name, value):
    current = target.get_editor_property(property_name)
    if isinstance(value, str):
        enum_value = getattr(type(current), value, None)
        if enum_value is not None:
            return enum_value
        if type(current).__name__ == "SoftObjectPath":
            return unreal.SoftObjectPath(value)
        if type(current).__name__ == "Name":
            return unreal.Name(value)
    return value


def _set_properties(target, values, section_name):
    if not isinstance(values, dict):
        raise ObjImportError("{} 必须是 JSON 对象".format(section_name))
    for property_name, value in values.items():
        try:
            converted_value = _coerce_editor_value(target, property_name, value)
            target.set_editor_property(property_name, converted_value)
        except Exception as error:
            raise ObjImportError(
                "配置 {}.{} 无法写入 {}：{}".format(
                    section_name,
                    property_name,
                    target.get_class().get_name(),
                    error,
                )
            )


def _configured_parameter_names(texture_import_config, property_names):
    result = []
    for property_name in property_names:
        if property_name not in texture_import_config:
            continue
        value = texture_import_config[property_name]
        if not isinstance(value, str):
            raise ObjImportError(
                "texture_import_data.{} 必须是字符串".format(property_name)
            )
        if value:
            result.append(value)
    return result


def _validate_parameter_names(configured_names, available_names, label):
    available_by_case = {value.casefold(): value for value in available_names}
    missing_names = [
        value for value in configured_names if value.casefold() not in available_by_case
    ]
    if missing_names:
        raise ObjImportError(
            "母材质缺少{}参数 {}；可用参数：{}".format(
                label,
                ", ".join(missing_names),
                ", ".join(available_names) or "无",
            )
        )


def _load_parent_material(parent_path, texture_import_config, validate_parameters):
    parent_material = unreal.load_asset(parent_path)
    if not parent_material:
        raise ObjImportError("母材质不存在：{}".format(parent_path))
    if not isinstance(parent_material, unreal.MaterialInterface):
        raise ObjImportError("parent_material 不是 MaterialInterface：{}".format(parent_path))

    if validate_parameters:
        texture_parameters = [
            str(value)
            for value in unreal.MaterialEditingLibrary.get_texture_parameter_names(
                parent_material
            )
        ]
        vector_parameters = [
            str(value)
            for value in unreal.MaterialEditingLibrary.get_vector_parameter_names(
                parent_material
            )
        ]
        _validate_parameter_names(
            _configured_parameter_names(
                texture_import_config, _TEXTURE_PARAMETER_PROPERTIES
            ),
            texture_parameters,
            "纹理",
        )
        _validate_parameter_names(
            _configured_parameter_names(
                texture_import_config, _VECTOR_PARAMETER_PROPERTIES
            ),
            vector_parameters,
            "向量",
        )
    return parent_material


def _create_import_options(config, parent_path):
    import_ui = unreal.FbxImportUI()
    _set_properties(import_ui, config.get("obj_import_ui", {}), "obj_import_ui")

    static_mesh_data = import_ui.get_editor_property("static_mesh_import_data")
    _set_properties(
        static_mesh_data,
        config.get("static_mesh_import_data", {}),
        "static_mesh_import_data",
    )

    texture_import_config = config.get("texture_import_data", {})
    texture_data = import_ui.get_editor_property("texture_import_data")
    _set_properties(texture_data, texture_import_config, "texture_import_data")
    texture_data.set_editor_property(
        "base_material_name", unreal.SoftObjectPath(parent_path)
    )
    return import_ui, texture_import_config


def _collect_imported_objects(import_task):
    imported_objects = list(import_task.get_objects())
    imported_paths = list(import_task.get_editor_property("imported_object_paths"))
    imported_objects.extend(unreal.load_asset(value) for value in imported_paths)

    unique_objects = {}
    for imported_object in imported_objects:
        if imported_object:
            unique_objects[imported_object.get_path_name()] = imported_object
    return list(unique_objects.values())


def _verify_import(imported_objects, parent_material, require_parent_instances):
    static_meshes = [
        value for value in imported_objects if isinstance(value, unreal.StaticMesh)
    ]
    if not static_meshes:
        raise ObjImportError("导入结果中没有 StaticMesh")

    material_instances = {}
    parent_path = parent_material.get_path_name()
    for static_mesh in static_meshes:
        static_materials = list(static_mesh.get_editor_property("static_materials"))
        if require_parent_instances and not static_materials:
            raise ObjImportError("静态模型没有材质槽：{}".format(static_mesh.get_path_name()))
        for slot_index, static_material in enumerate(static_materials):
            material = static_material.get_editor_property("material_interface")
            if not isinstance(material, unreal.MaterialInstanceConstant):
                if require_parent_instances:
                    raise ObjImportError(
                        "材质槽未生成 MaterialInstanceConstant：{}[{}] -> {}".format(
                            static_mesh.get_path_name(),
                            slot_index,
                            material.get_path_name() if material else "None",
                        )
                    )
                continue
            actual_parent = material.get_editor_property("parent")
            actual_parent_path = actual_parent.get_path_name() if actual_parent else ""
            if actual_parent_path != parent_path:
                if require_parent_instances:
                    raise ObjImportError(
                        "材质实例父级不匹配：{}，实际 {}，预期 {}".format(
                            material.get_path_name(), actual_parent_path, parent_path
                        )
                    )
                continue
            material_instances[material.get_path_name()] = material
    return static_meshes, list(material_instances.values())


def _validate_boolean_config(config, property_name, default_value):
    value = config.get(property_name, default_value)
    if not isinstance(value, bool):
        raise ObjImportError("{} 必须是布尔值".format(property_name))
    return value


def _run_import(source_file, config, destination_path):
    source_stem = _sanitize_asset_name(source_file.stem)
    asset_prefix = config.get("asset_name_prefix", "")
    if not isinstance(asset_prefix, str):
        raise ObjImportError("asset_name_prefix 必须是字符串")
    asset_name = _sanitize_asset_name(asset_prefix + source_stem)

    validate_parameters = _validate_boolean_config(
        config, "validate_parent_material_parameters", True
    )
    require_parent_instances = _validate_boolean_config(
        config, "require_parent_material_instances", True
    )
    parent_path = _normalize_object_path(config.get("parent_material"))
    import_ui, texture_import_config = _create_import_options(config, parent_path)
    parent_material = _load_parent_material(
        parent_path, texture_import_config, validate_parameters
    )

    task_config = config.get("import_task", {})
    import_task = unreal.AssetImportTask()
    _set_properties(import_task, task_config, "import_task")
    import_task.set_editor_property("filename", str(source_file))
    import_task.set_editor_property("destination_path", destination_path)
    import_task.set_editor_property("destination_name", asset_name)
    import_task.set_editor_property("options", import_ui)

    # UE 5.3 enables Interchange OBJ by default. A specified FbxFactory selects the
    # legacy OBJ path that consumes FbxTextureImportData and its parent material.
    import_factory = unreal.FbxFactory()
    import_task.set_editor_property("factory", import_factory)

    replace_existing = bool(task_config.get("replace_existing", False))
    target_asset_path = "{}/{}".format(destination_path, asset_name)
    if unreal.EditorAssetLibrary.does_asset_exist(target_asset_path) and not replace_existing:
        raise ObjImportError(
            "目标资产已存在且 replace_existing=false：{}".format(target_asset_path)
        )

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([import_task])
    imported_objects = _collect_imported_objects(import_task)
    if not imported_objects:
        raise ObjImportError("OBJ 导入失败，任务没有返回任何资产：{}".format(source_file))

    static_meshes, material_instances = _verify_import(
        imported_objects, parent_material, require_parent_instances
    )
    if task_config.get("save", True):
        if not unreal.EditorAssetLibrary.save_directory(
            destination_path, only_if_is_dirty=True, recursive=True
        ):
            raise ObjImportError("资产保存失败：{}".format(destination_path))

    physical_directory = os.path.abspath(
        os.path.join(
            unreal.Paths.project_content_dir(),
            destination_path[len("/Game/") :],
        )
    )
    textures = [
        value for value in imported_objects if isinstance(value, unreal.Texture)
    ]
    result = {
        "source_file": str(source_file),
        "destination_path": destination_path,
        "physical_directory": physical_directory,
        "imported_assets": sorted(
            value.get_path_name() for value in imported_objects
        ),
        "static_meshes": sorted(
            value.get_path_name() for value in static_meshes
        ),
        "material_instances": sorted(
            value.get_path_name() for value in material_instances
        ),
        "textures": sorted(value.get_path_name() for value in textures),
        "parent_material": parent_material.get_path_name(),
        "saved": bool(task_config.get("save", True)),
    }
    unreal.log("OBJ_IMPORT_RESULT=" + json.dumps(result, ensure_ascii=False, sort_keys=True))


def main():
    source_value = os.environ.get("UE_OBJ_IMPORT_SOURCE", "")
    config_value = os.environ.get("UE_OBJ_IMPORT_CONFIG", "")
    try:
        if not source_value:
            raise ObjImportError(
                "环境变量 UE_OBJ_IMPORT_SOURCE 为空，请从 import_obj.bat 启动"
            )
        if not config_value:
            raise ObjImportError(
                "环境变量 UE_OBJ_IMPORT_CONFIG 为空，请从 import_obj.bat 启动"
            )
        source_path = Path(source_value).expanduser().resolve()
        config_path = Path(config_value).expanduser().resolve()
        if source_path.is_file():
            if source_path.suffix.casefold() != ".obj":
                raise ObjImportError("OBJ 文件无效：{}".format(source_path))
            source_files = [source_path]
        elif source_path.is_dir():
            source_files = sorted(
                (
                    value
                    for value in source_path.rglob("*")
                    if value.is_file() and value.suffix.casefold() == ".obj"
                ),
                key=lambda value: str(value).casefold(),
            )
            if not source_files:
                raise ObjImportError("输入目录内没有 OBJ 文件：{}".format(source_path))
        else:
            raise ObjImportError("OBJ 输入路径无效：{}".format(source_path))
        config = _load_json(config_path)
        _register_legacy_material_mount()
        batch_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination_path = _normalize_game_directory(
            config.get("destination_root"), batch_timestamp
        )
        for source_file in source_files:
            _run_import(source_file, config, destination_path)
        unreal.log(
            "OBJ_IMPORT_BATCH_RESULT="
            + json.dumps(
                {
                    "destination_path": destination_path,
                    "source_count": len(source_files),
                    "timestamp": batch_timestamp,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    except Exception as error:
        unreal.log_error("OBJ_IMPORT_ERROR={}".format(error))
        raise


if __name__ == "__main__":
    main()
