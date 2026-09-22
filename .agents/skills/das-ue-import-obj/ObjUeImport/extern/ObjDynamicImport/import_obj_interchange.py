"""Import OBJ through Unreal Interchange while reusing the legacy batch shell."""

from __future__ import print_function

import json
import os
import sys
from pathlib import Path

import unreal


_SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(_SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIRECTORY))

import import_obj as legacy


_DIFFUSE_TEXTURE_PARAMETER = "DiffuseColorMap"
_IMPORT_UNIFORM_SCALE = 100.0


def _require_interchange_api():
    required_names = (
        "InterchangeGenericAssetsPipeline",
        "InterchangeMaterialImportOption",
        "InterchangePipelineStackOverride",
    )
    missing_names = [name for name in required_names if not hasattr(unreal, name)]
    if missing_names:
        raise legacy.ObjImportError(
            "当前 Unreal 缺少 OBJ Interchange Python API：{}".format(
                ", ".join(missing_names)
            )
        )


def _set_optional_editor_property(target, property_name, value):
    try:
        target.get_editor_property(property_name)
    except Exception:
        return False
    target.set_editor_property(property_name, value)
    return True


def _load_interchange_parent_material(parent_path, validate_parameters):
    parent_material = legacy._load_parent_material(parent_path, {}, False)
    if validate_parameters:
        texture_parameters = [
            str(value)
            for value in unreal.MaterialEditingLibrary.get_texture_parameter_names(
                parent_material
            )
        ]
        legacy._validate_parameter_names(
            [_DIFFUSE_TEXTURE_PARAMETER], texture_parameters, "纹理"
        )
    return parent_material


def _create_interchange_options(asset_name, parent_path):
    _require_interchange_api()

    pipeline_stack = unreal.InterchangePipelineStackOverride()
    pipeline = unreal.InterchangeGenericAssetsPipeline(outer=pipeline_stack)
    pipeline.set_editor_property("use_source_name_for_asset", False)
    pipeline.set_editor_property("asset_name", asset_name)
    pipeline.set_editor_property("import_offset_uniform_scale", _IMPORT_UNIFORM_SCALE)

    common_meshes = pipeline.get_editor_property("common_meshes_properties")
    common_meshes.set_editor_property("remove_degenerates", False)

    mesh_pipeline = pipeline.get_editor_property("mesh_pipeline")
    mesh_pipeline.set_editor_property("import_static_meshes", True)
    mesh_pipeline.set_editor_property("combine_static_meshes", False)
    mesh_pipeline.set_editor_property("import_skeletal_meshes", False)
    mesh_pipeline.set_editor_property("build_nanite", True)
    mesh_pipeline.set_editor_property("generate_lightmap_u_vs", True)

    animation_pipeline = pipeline.get_editor_property("animation_pipeline")
    animation_pipeline.set_editor_property("import_animations", False)

    material_pipeline = pipeline.get_editor_property("material_pipeline")
    material_pipeline.set_editor_property("import_materials", True)
    material_pipeline.set_editor_property(
        "material_import",
        unreal.InterchangeMaterialImportOption.IMPORT_AS_MATERIAL_INSTANCES,
    )
    material_pipeline.set_editor_property(
        "parent_material", unreal.SoftObjectPath(parent_path)
    )

    # UE 5.5+ exposes these switches. UE 5.3/5.4 does not need them.
    _set_optional_editor_property(
        material_pipeline, "create_material_instance_for_parent", True
    )
    _set_optional_editor_property(material_pipeline, "create_new_materials", True)
    _set_optional_editor_property(material_pipeline, "reuse_existing_materials", False)
    _set_optional_editor_property(material_pipeline, "identify_duplicate_materials", False)

    texture_pipeline = material_pipeline.get_editor_property("texture_pipeline")
    texture_pipeline.set_editor_property("import_textures", True)
    texture_pipeline.set_editor_property("flip_normal_map_green_channel", False)

    pipeline_stack.add_pipeline(pipeline)
    return pipeline_stack


def _run_interchange_import(
    source_file, config, destination_path, parent_path, collect_packages
):
    asset_name = legacy._asset_name_for_source(source_file, config)
    validate_parameters = legacy._validate_boolean_config(
        config, "validate_parent_material_parameters", True
    )
    require_parent_instances = legacy._validate_boolean_config(
        config, "require_parent_material_instances", True
    )
    build_static_mesh_ddc = legacy._validate_boolean_config(
        config, "build_static_mesh_ddc", True
    )
    parent_material = _load_interchange_parent_material(
        parent_path, validate_parameters
    )

    task_config = config.get("import_task", {})
    import_task = unreal.AssetImportTask()
    legacy._set_properties(import_task, task_config, "import_task")
    import_task.set_editor_property("filename", str(source_file))
    import_task.set_editor_property("destination_path", destination_path)
    import_task.set_editor_property(
        "options", _create_interchange_options(asset_name, parent_path)
    )

    replace_existing = bool(task_config.get("replace_existing", False))
    target_asset_path = "{}/{}".format(destination_path, asset_name)
    if (
        unreal.EditorAssetLibrary.does_asset_exist(target_asset_path)
        and not replace_existing
    ):
        raise legacy.ObjImportError(
            "目标资产已存在且 replace_existing=false：{}".format(target_asset_path)
        )

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([import_task])
    imported_objects = legacy._collect_imported_objects(import_task)
    if not imported_objects:
        raise legacy.ObjImportError(
            "Interchange OBJ 导入失败，任务没有返回任何资产：{}".format(source_file)
        )

    static_meshes, material_instances = legacy._verify_import(
        imported_objects, parent_material, require_parent_instances
    )
    derived_data = (
        legacy._wait_for_static_mesh_derived_data(static_meshes)
        if build_static_mesh_ddc
        else []
    )
    if task_config.get("save", True):
        if not unreal.EditorAssetLibrary.save_directory(
            destination_path, only_if_is_dirty=True, recursive=True
        ):
            raise legacy.ObjImportError("资产保存失败：{}".format(destination_path))

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
        "import_pipeline": "interchange",
        "diffuse_texture_parameter": _DIFFUSE_TEXTURE_PARAMETER,
        "imported_assets": sorted(
            value.get_path_name() for value in imported_objects
        ),
        "static_meshes": sorted(value.get_path_name() for value in static_meshes),
        "material_instances": sorted(
            value.get_path_name() for value in material_instances
        ),
        "textures": sorted(value.get_path_name() for value in textures),
        "parent_material": parent_material.get_path_name(),
        "static_mesh_ddc": derived_data,
        "static_mesh_ddc_enabled": build_static_mesh_ddc,
        "saved": saved,
    }
    unreal.log(
        "OBJ_IMPORT_RESULT="
        + json.dumps(result, ensure_ascii=False, sort_keys=True)
    )

    if not collect_packages or not saved:
        return []
    return legacy._collect_packages(imported_objects)


def main():
    unreal.log(
        "OBJ_IMPORT_PIPELINE=interchange,diffuse_texture_parameter={}".format(
            _DIFFUSE_TEXTURE_PARAMETER
        )
    )
    legacy.main(import_runner=_run_interchange_import)


if __name__ == "__main__":
    main()
