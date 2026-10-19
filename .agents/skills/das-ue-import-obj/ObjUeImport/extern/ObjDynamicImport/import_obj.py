"""Run inside Unreal Editor and import the OBJ supplied by the launcher."""

from __future__ import print_function

import codecs
import hashlib
import json
import os
import re
import shutil
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

_CLEANUP_DEFAULTS = {
    "unload_after_import": True,
    "interval": 1,
}

_BATCH_MATERIAL_DEFAULTS = {
    "enabled": True,
    # 空串 = 放进批次目录下的 data_info_directory，删批次目录时一起删掉。
    # 显式填绝对目录（支持 {timestamp} / {date}）则按老行为放到批次目录外。
    "destination_root": "",
}

# 批次目录下汇总元数据、批次母材质与关卡的目录名，obj_ue_import.exe 读的是同一个键。
_DATA_INFO_DIRECTORY_DEFAULT = "DasDataInfo"
_TILES_DIRECTORY = "Tiles"

_REFERENCE_TOKEN_PATTERN = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')
_MAP_OPTION_ARGUMENTS = {
    "-blendu": 1,
    "-blendv": 1,
    "-boost": 1,
    "-mm": 2,
    "-texres": 1,
    "-clamp": 1,
    "-bm": 1,
    "-imfchan": 1,
    "-type": 1,
    "-cc": 1,
}
_VARIABLE_MAP_OPTIONS = {"-o", "-s", "-t"}


def _load_json(config_path):
    try:
        with config_path.open("r", encoding="utf-8-sig") as config_file:
            config = json.load(config_file)
    except (OSError, ValueError) as error:
        raise ObjImportError("无法读取 JSON 配置 {}：{}".format(config_path, error))
    if not isinstance(config, dict):
        raise ObjImportError("JSON 根节点必须是对象：{}".format(config_path))
    return config


def _detect_obj_text_encoding(path):
    """Accept UTF-8 first, then GBK, without loading large OBJ files into memory."""
    for encoding in ("utf-8-sig", "gbk"):
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
        try:
            with path.open("rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    decoder.decode(chunk, final=False)
                decoder.decode(b"", final=True)
            return encoding
        except UnicodeDecodeError:
            continue
        except OSError as error:
            raise ObjImportError("无法读取 OBJ/MTL 文件 {}：{}".format(path, error))
    raise ObjImportError(
        "OBJ/MTL 文件既不是有效 UTF-8，也不是有效 GBK：{}".format(path)
    )


def _reference_tokens(value):
    return [
        next(group for group in match.groups() if group is not None)
        for match in _REFERENCE_TOKEN_PATTERN.finditer(value)
    ]


def _resolve_obj_reference(base_directory, reference):
    reference_path = Path(reference.strip().strip('"').strip("'"))
    if not reference_path.is_absolute():
        reference_path = base_directory / reference_path
    try:
        return reference_path.resolve()
    except (OSError, RuntimeError):
        return reference_path.absolute()


def _obj_material_references(path, line):
    content = line.split("#", 1)[0].strip()
    parts = content.split(None, 1)
    if len(parts) != 2 or parts[0].casefold() != "mtllib":
        return []
    value = parts[1].strip()
    if not value:
        return []

    # First accept the complete remainder as a filename (which supports spaces).
    whole_reference = _resolve_obj_reference(path.parent, value)
    if whole_reference.is_file():
        return [whole_reference]

    # Otherwise treat it as the standard space-separated list of MTL names.
    references = []
    for token in _reference_tokens(value):
        candidate = _resolve_obj_reference(path.parent, token)
        if candidate.is_file():
            references.append(candidate)
    return references


def _material_texture_reference(path, line):
    content = line.split("#", 1)[0].strip()
    parts = content.split(None, 1)
    if len(parts) != 2:
        return None
    directive, value = parts[0].casefold(), parts[1]
    if not (
        directive.startswith("map_")
        or directive in ("bump", "disp", "decal", "norm", "refl")
    ):
        return None

    tokens = _reference_tokens(value.strip())
    index = 0
    while index < len(tokens) and tokens[index].startswith("-"):
        option = tokens[index].casefold()
        if option in _VARIABLE_MAP_OPTIONS:
            index += 1
            consumed = 0
            while index < len(tokens) and consumed < 3:
                try:
                    float(tokens[index])
                except ValueError:
                    break
                index += 1
                consumed += 1
            if consumed == 0:
                break
            continue

        argument_count = _MAP_OPTION_ARGUMENTS.get(option)
        if argument_count is None:
            break
        index += 1 + argument_count

    texture_name = " ".join(tokens[index:]).strip()
    if not texture_name:
        return None
    return _resolve_obj_reference(path.parent, texture_name)


def _read_obj_material_dependencies(source_file):
    source_file = Path(source_file).resolve()
    text_encodings = {source_file: _detect_obj_text_encoding(source_file)}
    material_files = set()
    texture_files = set()

    with source_file.open(
        "r", encoding=text_encodings[source_file], newline=None
    ) as obj:
        for line in obj:
            material_files.update(_obj_material_references(source_file, line))

    for material_file in material_files:
        text_encodings[material_file] = _detect_obj_text_encoding(material_file)
        with material_file.open(
            "r", encoding=text_encodings[material_file], newline=None
        ) as material:
            for line in material:
                texture_file = _material_texture_reference(material_file, line)
                if texture_file is not None and texture_file.is_file():
                    texture_files.add(texture_file)

    return text_encodings, texture_files


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.digest()


def _write_utf8_copy(source_path, destination_path, source_encoding):
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination_path.with_name(destination_path.name + ".tmp")
    try:
        with source_path.open("r", encoding=source_encoding, newline="") as source:
            with temporary_path.open("w", encoding="utf-8", newline="") as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
        os.replace(str(temporary_path), str(destination_path))
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _prepare_obj_source_for_import(source_file):
    """Make a persistent UTF-8 staging copy only when OBJ/MTL contains GBK text."""
    source_file = Path(source_file).resolve()
    text_encodings, texture_files = _read_obj_material_dependencies(source_file)
    gbk_files = [
        path for path, encoding in text_encodings.items() if encoding == "gbk"
    ]
    if not gbk_files:
        return source_file

    source_paths = set(text_encodings) | texture_files
    try:
        dependency_root = Path(
            os.path.commonpath([str(path.parent) for path in source_paths])
        )
    except ValueError as error:
        raise ObjImportError(
            "OBJ、MTL 与贴图位于不同磁盘，无法保留相对路径进行 UTF-8 预处理：{}".format(
                source_file
            )
        ) from error

    cache_key = hashlib.sha256()
    for path in sorted(source_paths, key=lambda value: str(value).casefold()):
        try:
            relative_path = os.path.relpath(str(path), str(dependency_root))
        except ValueError as error:
            raise ObjImportError("无法建立 OBJ 编码缓存相对路径：{}".format(path)) from error
        cache_key.update(relative_path.casefold().encode("utf-8"))
        cache_key.update(_file_sha256(path))

    cache_root = (
        Path(unreal.Paths.project_saved_dir())
        / "ObjImportUtf8"
        / cache_key.hexdigest()
    )
    for path, encoding in text_encodings.items():
        relative_path = os.path.relpath(str(path), str(dependency_root))
        _write_utf8_copy(path, cache_root / relative_path, encoding)
        if encoding == "gbk":
            unreal.log(
                "OBJ_IMPORT_ENCODING=GBK->UTF-8,source={},staged={}".format(
                    path, cache_root / relative_path
                )
            )
    for path in texture_files:
        relative_path = os.path.relpath(str(path), str(dependency_root))
        destination_path = cache_root / relative_path
        if (
            not destination_path.is_file()
            or _file_sha256(destination_path) != _file_sha256(path)
        ):
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(path), str(destination_path))

    staged_source = cache_root / os.path.relpath(str(source_file), str(dependency_root))
    return staged_source


def _require_commandlet_rendering():
    """Textures build no derived data without -AllowCommandletRendering.

    UTexture::CachePlatformData is gated on FApp::CanEverRender(), which is
    (!IsRunningCommandlet() || IsAllowCommandletRendering()) && !nullrhi. Under
    -run=PythonScript the first term is false, so every texture would be saved with
    an empty DDC and the editor would rebuild all of them on its next startup.
    UStaticMesh has no such gate, which is why meshes come out fine either way.
    """
    command_line = unreal.SystemLibrary.get_command_line()
    switches = {
        token.strip().lstrip("-/").casefold()
        for token in command_line.replace("\t", " ").split(" ")
    }
    if "nullrhi" in switches:
        raise ObjImportError(
            "命令行带有 -nullrhi，纹理不会构建 DDC，"
            "编辑器下次打开会重新构建全部纹理。请去掉该参数。"
        )
    if "allowcommandletrendering" not in switches:
        raise ObjImportError(
            "命令行缺少 -AllowCommandletRendering，纹理不会构建 DDC，"
            "编辑器下次打开会重新构建全部纹理。请在 commandlet_arguments 中加上该参数。"
        )


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
    # UE 会把符号折叠成下划线。先保留数字负号的语义，避免 +0010 与
    # -0010 最终生成同名资产；正号继续沿用原规则，不改变已有正数资产名。
    value = re.sub(r"-(?=\d)", "neg", value.strip())
    characters = []
    for character in value:
        characters.append(character if character.isalnum() or character == "_" else "_")
    name = re.sub(r"_+", "_", "".join(characters)).strip("_")
    if not name:
        raise ObjImportError("无法从 OBJ 文件名生成合法的 Unreal 资产名")
    if name[0].isdigit():
        name = "Mesh_" + name
    return name


def _asset_name_for_source(source_file, config):
    source_stem = _sanitize_asset_name(source_file.stem)
    asset_prefix = config.get("asset_name_prefix", "")
    if not isinstance(asset_prefix, str):
        raise ObjImportError("asset_name_prefix 必须是字符串")
    return _sanitize_asset_name(asset_prefix + source_stem)


def _tile_destination_path(destination_path, source_file):
    return "{}/{}/{}".format(
        destination_path, _TILES_DIRECTORY, _sanitize_asset_name(source_file.stem)
    )


def _validate_unique_asset_names(source_files, config):
    assets_by_name = {}
    conflicts = []
    for source_file in source_files:
        asset_name = _asset_name_for_source(source_file, config)
        name_key = asset_name.casefold()
        previous_file = assets_by_name.get(name_key)
        if previous_file is None:
            assets_by_name[name_key] = source_file
            continue
        conflicts.append((asset_name, previous_file, source_file))

    if not conflicts:
        return

    details = "\n".join(
        "  {} <- {} | {}".format(asset_name, first_file, second_file)
        for asset_name, first_file, second_file in conflicts
    )
    raise ObjImportError(
        "多个 OBJ 会生成同名 Unreal 资产，已在导入前中止：\n{}".format(details)
    )


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


def _load_cleanup_config(config):
    cleanup = config.get("cleanup", {})
    if not isinstance(cleanup, dict):
        raise ObjImportError("cleanup 必须是 JSON 对象")

    unknown_fields = set(cleanup) - set(_CLEANUP_DEFAULTS)
    if unknown_fields:
        raise ObjImportError(
            "不支持的 cleanup 字段：{}".format(", ".join(sorted(unknown_fields)))
        )

    unload_after_import = _validate_boolean_config(
        cleanup, "unload_after_import", _CLEANUP_DEFAULTS["unload_after_import"]
    )

    interval = cleanup.get("interval", _CLEANUP_DEFAULTS["interval"])
    if isinstance(interval, bool) or not isinstance(interval, int):
        raise ObjImportError("cleanup.interval 必须是整数")
    if interval < 1:
        raise ObjImportError("cleanup.interval 不能小于 1")

    return unload_after_import, interval


def _load_batch_material_config(config):
    """读取 batch_parent_material 段：是否为本批次复制一份独立母材质、复制到哪个目录。"""
    batch_material = config.get("batch_parent_material", {})
    if not isinstance(batch_material, dict):
        raise ObjImportError("batch_parent_material 必须是 JSON 对象")

    unknown_fields = set(batch_material) - set(_BATCH_MATERIAL_DEFAULTS)
    if unknown_fields:
        raise ObjImportError(
            "不支持的 batch_parent_material 字段：{}".format(", ".join(sorted(unknown_fields)))
        )

    enabled = _validate_boolean_config(
        batch_material, "enabled", _BATCH_MATERIAL_DEFAULTS["enabled"]
    )
    destination_root = batch_material.get(
        "destination_root", _BATCH_MATERIAL_DEFAULTS["destination_root"]
    )
    if not isinstance(destination_root, str):
        raise ObjImportError("batch_parent_material.destination_root 必须是字符串")
    return enabled, destination_root.strip()


def _data_info_path(config, destination_path):
    """批次目录下汇总元数据、批次母材质与关卡的目录，与 obj_ue_import.exe 用同一个配置键。"""
    name = config.get("data_info_directory", _DATA_INFO_DIRECTORY_DEFAULT)
    if not isinstance(name, str) or not name.strip():
        raise ObjImportError("data_info_directory 不能为空")
    name = name.strip().replace("\\", "/").strip("/")
    if "/" in name:
        raise ObjImportError("data_info_directory 只能是一级目录名：{}".format(name))
    return "{}/{}".format(destination_path, name)


def _batch_material_root(config, material_root, destination_path, batch_timestamp):
    """批次母材质的落点：配置显式给了目录就用它，否则放进批次目录下的 DasDataInfo。"""
    if material_root:
        return _normalize_game_directory(material_root, batch_timestamp)
    return _data_info_path(config, destination_path)


def _resolve_batch_timestamp(config):
    """批次时间戳由启动器下发，母材质名才能和批次目录、批次关卡完全对齐。"""
    batch_timestamp = config.get("batch_timestamp", "")
    if not isinstance(batch_timestamp, str):
        raise ObjImportError("batch_timestamp 必须是字符串")
    batch_timestamp = batch_timestamp.strip()
    if batch_timestamp:
        return batch_timestamp
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _duplicate_parent_material(parent_path, destination_root, batch_timestamp):
    """把母材质复制成本批次专用的一份，返回副本的对象路径。

    导入器按 FbxImportOptions.BaseMaterial 建材质实例（FbxMaterialImport.cpp:686），
    换掉这个路径就等于给本批次一套独立的材质参数，调参不影响历史批次。
    """
    source_package = parent_path.rsplit(".", 1)[0]
    target_name = "{}_{}".format(source_package.rsplit("/", 1)[-1], batch_timestamp)
    target_package = "{}/{}".format(destination_root, target_name)
    if unreal.EditorAssetLibrary.does_asset_exist(target_package):
        raise ObjImportError("本批次母材质已存在：{}".format(target_package))

    duplicated = unreal.EditorAssetLibrary.duplicate_asset(source_package, target_package)
    if not duplicated:
        raise ObjImportError("母材质复制失败：{} -> {}".format(source_package, target_package))
    if not unreal.EditorAssetLibrary.save_loaded_asset(duplicated, only_if_is_dirty=False):
        raise ObjImportError("本批次母材质保存失败：{}".format(target_package))

    unreal.log(
        "OBJ_IMPORT_BATCH_MATERIAL="
        + json.dumps(
            {"source": parent_path, "batch_parent_material": duplicated.get_path_name()},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return duplicated.get_path_name()


def _collect_packages(imported_objects):
    packages = []
    seen_names = set()
    for imported_object in imported_objects:
        package = imported_object.get_outermost()
        if not package:
            continue
        package_name = package.get_name()
        if package_name in seen_names:
            continue
        seen_names.add(package_name)
        packages.append(package)
    return packages


def _unload_packages(packages):
    """Free imported assets; plain collect_garbage keeps RF_Standalone assets alive."""
    if not packages:
        return

    try:
        unloaded, message = unreal.EditorLoadingAndSavingUtils.unload_packages(packages)
    except Exception as error:
        unreal.log_warning("OBJ_IMPORT_UNLOAD_SKIPPED={}".format(error))
        return

    if not unloaded:
        unreal.log_warning(
            "OBJ_IMPORT_UNLOAD_SKIPPED={}".format(message or "资产仍被引用")
        )


def _use_full_precision_uvs(static_meshes):
    mesh_subsystem = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    if mesh_subsystem is None:
        raise ObjImportError("无法获取 StaticMeshEditorSubsystem，不能开启全精度 UV")

    for static_mesh in static_meshes:
        lod_count = mesh_subsystem.get_lod_count(static_mesh)
        if lod_count <= 0:
            raise ObjImportError(
                "静态模型没有可设置全精度 UV 的 LOD：{}".format(
                    static_mesh.get_path_name()
                )
            )
        for lod_index in range(lod_count):
            build_settings = mesh_subsystem.get_lod_build_settings(
                static_mesh, lod_index
            )
            if build_settings.get_editor_property("use_full_precision_u_vs"):
                continue
            build_settings.set_editor_property("use_full_precision_u_vs", True)
            # The setter marks the mesh dirty and requests a rebuild.
            mesh_subsystem.set_lod_build_settings(
                static_mesh, lod_index, build_settings
            )


def _wait_for_static_mesh_derived_data(static_meshes):
    derived_data = []
    for static_mesh in static_meshes:
        mesh_path = static_mesh.get_path_name()
        # Import and LOD settings changes have requested mesh builds. Both methods
        # below read RenderData, which forces UE's async static-mesh compiler to
        # finish. FStaticMeshRenderData::Cache uses a blocking DDC put, so the
        # derived data request has completed before these calls return.
        triangle_count = static_mesh.get_num_triangles(0)
        lod_count = static_mesh.get_num_lods()
        if lod_count <= 0:
            raise ObjImportError("静态模型没有可构建的 LOD：{}".format(mesh_path))
        if triangle_count <= 0:
            raise ObjImportError("静态模型 DDC 构建后没有有效三角形：{}".format(mesh_path))

        derived_data.append(
            {
                "static_mesh": mesh_path,
                "lod_count": lod_count,
                "lod0_triangle_count": triangle_count,
            }
        )
        unreal.log(
            "OBJ_IMPORT_DDC={}".format(
                json.dumps(derived_data[-1], ensure_ascii=False, sort_keys=True)
            )
        )
    return derived_data


def _run_import(source_file, config, destination_path, parent_path, collect_packages):
    asset_name = _asset_name_for_source(source_file, config)

    validate_parameters = _validate_boolean_config(
        config, "validate_parent_material_parameters", True
    )
    require_parent_instances = _validate_boolean_config(
        config, "require_parent_material_instances", True
    )
    build_static_mesh_ddc = _validate_boolean_config(
        config, "build_static_mesh_ddc", True
    )
    import_ui, texture_import_config = _create_import_options(config, parent_path)
    parent_material = _load_parent_material(
        parent_path, texture_import_config, validate_parameters
    )

    task_config = config.get("import_task", {})
    import_task = unreal.AssetImportTask()
    _set_properties(import_task, task_config, "import_task")
    import_source_file = _prepare_obj_source_for_import(source_file)
    import_task.set_editor_property("filename", str(import_source_file))
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
    _use_full_precision_uvs(static_meshes)
    derived_data = (
        _wait_for_static_mesh_derived_data(static_meshes)
        if build_static_mesh_ddc
        else []
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
    saved = bool(task_config.get("save", True))
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
        "static_mesh_ddc": derived_data,
        "static_mesh_ddc_enabled": build_static_mesh_ddc,
        "saved": saved,
    }
    unreal.log("OBJ_IMPORT_RESULT=" + json.dumps(result, ensure_ascii=False, sort_keys=True))

    # 没保存的资产是 dirty 的，UnloadPackages 会跳过它们，交出去只会白跑一次 GC。
    if not collect_packages or not saved:
        return []
    return _collect_packages(imported_objects)


def main(import_runner=None):
    if import_runner is None:
        import_runner = _run_import
    source_value = os.environ.get("UE_OBJ_IMPORT_SOURCE", "")
    config_value = os.environ.get("UE_OBJ_IMPORT_CONFIG", "")
    try:
        if not source_value:
            raise ObjImportError(
                "环境变量 UE_OBJ_IMPORT_SOURCE 为空，请通过 obj_ue_import.exe 启动"
            )
        if not config_value:
            raise ObjImportError(
                "环境变量 UE_OBJ_IMPORT_CONFIG 为空，请通过 obj_ue_import.exe 启动"
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
        _validate_unique_asset_names(source_files, config)
        unload_after_import, cleanup_interval = _load_cleanup_config(config)
        _require_commandlet_rendering()
        _register_legacy_material_mount()
        batch_timestamp = _resolve_batch_timestamp(config)
        destination_path = _normalize_game_directory(
            config.get("destination_root"), batch_timestamp
        )
        if _data_info_path(config, destination_path).casefold() == (
            destination_path + "/" + _TILES_DIRECTORY
        ).casefold():
            raise ObjImportError(
                "data_info_directory 不能与瓦块目录 {} 同名".format(
                    _TILES_DIRECTORY
                )
            )
        parent_path = _normalize_object_path(config.get("parent_material"))
        duplicate_parent, material_root = _load_batch_material_config(config)
        if duplicate_parent:
            parent_path = _duplicate_parent_material(
                parent_path,
                _batch_material_root(
                    config, material_root, destination_path, batch_timestamp
                ),
                batch_timestamp,
            )
        pending_packages = []
        for index, source_file in enumerate(source_files, start=1):
            pending_packages.extend(
                import_runner(
                    source_file,
                    config,
                    _tile_destination_path(destination_path, source_file),
                    parent_path,
                    unload_after_import,
                )
            )
            if unload_after_import and index % cleanup_interval == 0:
                _unload_packages(pending_packages)
                pending_packages = []
        if unload_after_import:
            _unload_packages(pending_packages)
            pending_packages = []
        unreal.log(
            "OBJ_IMPORT_BATCH_RESULT="
            + json.dumps(
                {
                    "destination_path": destination_path,
                    "parent_material": parent_path,
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
