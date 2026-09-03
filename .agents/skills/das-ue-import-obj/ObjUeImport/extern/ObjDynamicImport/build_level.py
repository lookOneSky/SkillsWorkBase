"""Run inside Unreal Editor and gather one import batch into a single level."""

from __future__ import print_function

import json
import os
from pathlib import Path

import unreal


class BuildLevelError(RuntimeError):
    """Expected level or configuration error."""


_ORIGIN_ALIGNMENTS = ("bottom_center", "center", "xy_center")

_DEFAULTS = {
    "level_root": "/Game/ObjImport",
    "level_name_prefix": "mapObjImport_",
    "origin_alignment": "bottom_center",
}


def _load_json(config_path):
    """读取 UTF-8(-BOM) 的 JSON 配置，根节点必须是对象。"""
    try:
        with config_path.open("r", encoding="utf-8-sig") as config_file:
            config = json.load(config_file)
    except (OSError, ValueError) as error:
        raise BuildLevelError("无法读取 JSON 配置 {}：{}".format(config_path, error))
    if not isinstance(config, dict):
        raise BuildLevelError("JSON 根节点必须是对象：{}".format(config_path))
    return config


def _require_game_directory(value, field_name):
    """校验并规范化一个必须位于 /Game 下的目录路径。"""
    if not isinstance(value, str) or not value.strip():
        raise BuildLevelError("{} 不能为空".format(field_name))
    path = value.strip().replace("\\", "/").rstrip("/")
    if path.casefold().startswith("game/"):
        path = "/" + path
    if path != "/Game" and not path.startswith("/Game/"):
        raise BuildLevelError("{} 必须位于 Content（/Game）下：{}".format(field_name, path))
    return path


def _collect_static_mesh_paths(destination_path):
    """列出批次目录里的全部 StaticMesh 资产路径，用 AssetData 判类型避免加载无关资产。"""
    static_mesh_paths = []
    for asset_path in unreal.EditorAssetLibrary.list_assets(
        destination_path, recursive=True, include_folder=False
    ):
        asset_data = unreal.EditorAssetLibrary.find_asset_data(asset_path)
        if str(asset_data.asset_class_path.asset_name) == "StaticMesh":
            static_mesh_paths.append(asset_path)
    return sorted(static_mesh_paths, key=lambda value: value.casefold())


def _load_static_meshes(static_mesh_paths):
    """加载全部 StaticMesh；关卡建好之前不能加载，NewMap 的 GC 会顺手回收它们。"""
    static_meshes = []
    for asset_path in static_mesh_paths:
        static_mesh = unreal.load_asset(asset_path)
        if not isinstance(static_mesh, unreal.StaticMesh):
            raise BuildLevelError("静态模型加载失败：{}".format(asset_path))
        static_meshes.append(static_mesh)
    return static_meshes


def _merge_bounding_boxes(static_meshes):
    """合并全部 StaticMesh 的包围盒，返回 (最小点, 最大点)。"""
    minimum = None
    maximum = None
    for static_mesh in static_meshes:
        box = static_mesh.get_bounding_box()
        if not box.is_valid:
            raise BuildLevelError(
                "静态模型没有有效包围盒：{}".format(static_mesh.get_path_name())
            )
        # box.min / box.max 每次访问都会新建一个 Vector，循环里先取出来。
        box_min = box.min
        box_max = box.max
        if minimum is None:
            minimum = unreal.Vector(box_min.x, box_min.y, box_min.z)
            maximum = unreal.Vector(box_max.x, box_max.y, box_max.z)
            continue
        minimum.x = min(minimum.x, box_min.x)
        minimum.y = min(minimum.y, box_min.y)
        minimum.z = min(minimum.z, box_min.z)
        maximum.x = max(maximum.x, box_max.x)
        maximum.y = max(maximum.y, box_max.y)
        maximum.z = max(maximum.z, box_max.z)
    if minimum is None:
        raise BuildLevelError("没有可用于计算包围盒的静态模型")
    return minimum, maximum


def _compute_origin_offset(minimum, maximum, origin_alignment):
    """算出让整批模型的总包围盒对齐原点的统一偏移量。

    OBJ 瓦块顶点保留各自的原始坐标，全部用同一个偏移量放置才能保持相对位置。
    """
    offset_x = -(minimum.x + maximum.x) * 0.5
    offset_y = -(minimum.y + maximum.y) * 0.5
    if origin_alignment == "bottom_center":
        offset_z = -minimum.z
    elif origin_alignment == "center":
        offset_z = -(minimum.z + maximum.z) * 0.5
    else:
        offset_z = 0.0
    return unreal.Vector(offset_x, offset_y, offset_z)


def _wait_for_render_data(static_meshes):
    """读 RenderData 逼停 UE 的异步静态网格编译。

    带 -AllowCommandletRendering 时 FApp::CanEverRender() 为真，
    UStaticMeshComponent::SetStaticMesh 里有
    checkf(StaticMesh->GetRenderData()->IsInitialized())，编译没完就会断言崩溃。
    get_num_lods / get_num_triangles 都要读 RenderData，会阻塞到编译结束。
    """
    for static_mesh in static_meshes:
        if static_mesh.get_num_lods() <= 0 or static_mesh.get_num_triangles(0) <= 0:
            raise BuildLevelError(
                "静态模型没有可用的渲染数据：{}".format(static_mesh.get_path_name())
            )


def _spawn_static_meshes(static_meshes, offset):
    """按同一个偏移量把全部 StaticMesh 放进当前关卡。

    不能用 EditorActorSubsystem.spawn_actor_from_object：它会走编辑器拖放的
    placement 路径（AssetSelection.cpp:847），那里 GEditor->GetEditorSubsystem
    <UPlacementSubsystem>() 没有判空，commandlet 下取不到该子系统会直接 AV。
    spawn_actor_from_class 最终走 UEditorEngine::AddActor -> World->SpawnActor，
    不依赖任何编辑器视口状态。
    """
    actor_subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    rotation = unreal.Rotator(0.0, 0.0, 0.0)
    for static_mesh in static_meshes:
        actor = actor_subsystem.spawn_actor_from_class(
            unreal.StaticMeshActor, offset, rotation
        )
        if not actor:
            raise BuildLevelError(
                "放置静态模型失败：{}".format(static_mesh.get_path_name())
            )
        component = actor.static_mesh_component
        if not component.set_static_mesh(static_mesh):
            raise BuildLevelError(
                "绑定静态模型失败：{}".format(static_mesh.get_path_name())
            )
        actor.set_actor_label(static_mesh.get_name())


def _discard_unfinished_level(level_path):
    """删掉 new_level 已经存过盘、但没能放进模型的空关卡。

    清理失败不能掩盖原始错误，所以这里只记日志，不往外抛。
    """
    try:
        deleted = unreal.EditorAssetLibrary.delete_asset(level_path)
    except Exception as error:  # noqa: BLE001 - 清理失败只记录
        unreal.log_warning("OBJ_LEVEL_CLEANUP_FAILED={}：{}".format(level_path, error))
        return
    if deleted:
        unreal.log_warning("OBJ_LEVEL_CLEANUP={}".format(level_path))
    else:
        unreal.log_warning("OBJ_LEVEL_CLEANUP_FAILED={}".format(level_path))


def main():
    config_value = os.environ.get("UE_LEVEL_CONFIG", "")
    unfinished_level_path = ""
    try:
        unreal.log("[BuildLevel] 开始生成本批次关卡")
        if not config_value:
            raise BuildLevelError(
                "环境变量 UE_LEVEL_CONFIG 为空，请从 obj_ue_import.exe 启动"
            )
        config = _load_json(Path(config_value).expanduser().resolve())

        destination_path = _require_game_directory(
            config.get("destination_path"), "destination_path"
        )
        level_root = _require_game_directory(
            config.get("level_root", _DEFAULTS["level_root"]), "level_root"
        )
        name_prefix = config.get("level_name_prefix", _DEFAULTS["level_name_prefix"])
        if not isinstance(name_prefix, str):
            raise BuildLevelError("level_name_prefix 必须是字符串")
        origin_alignment = config.get("origin_alignment", _DEFAULTS["origin_alignment"])
        if origin_alignment not in _ORIGIN_ALIGNMENTS:
            raise BuildLevelError(
                "origin_alignment 只支持 {}，收到 {}".format(
                    "、".join(_ORIGIN_ALIGNMENTS), origin_alignment
                )
            )
        batch_timestamp = config.get("batch_timestamp", "")
        if not isinstance(batch_timestamp, str) or not batch_timestamp:
            raise BuildLevelError("batch_timestamp 不能为空")

        level_path = "{}/{}{}".format(level_root, name_prefix, batch_timestamp)
        if unreal.EditorAssetLibrary.does_asset_exist(level_path):
            raise BuildLevelError("关卡已存在：{}".format(level_path))

        static_mesh_paths = _collect_static_mesh_paths(destination_path)
        if not static_mesh_paths:
            raise BuildLevelError("批次目录里没有 StaticMesh：{}".format(destination_path))

        # 先建空关卡：new_level 内部走 GEditor->NewMap()，会先做一次 GC。
        # 静态模型必须在这之后加载，否则会被这次 GC 回收。
        level_subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if not level_subsystem.new_level(level_path):
            raise BuildLevelError("关卡创建失败：{}".format(level_path))
        # new_level 内部已经把空关卡存了一次盘，之后任何一步失败都要把它删掉。
        unfinished_level_path = level_path

        static_meshes = _load_static_meshes(static_mesh_paths)
        _wait_for_render_data(static_meshes)
        minimum, maximum = _merge_bounding_boxes(static_meshes)
        offset = _compute_origin_offset(minimum, maximum, origin_alignment)
        _spawn_static_meshes(static_meshes, offset)

        # 新关卡还没有 SaveAs 之外的文件名，SaveCurrentLevel 在 unattended 下会直接失败
        # （FileHelpers.cpp:3860），只能走 SaveMap。
        editor_subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        if not unreal.EditorLoadingAndSavingUtils.save_map(
            editor_subsystem.get_editor_world(), level_path
        ):
            raise BuildLevelError("关卡保存失败：{}".format(level_path))
        unfinished_level_path = ""

        unreal.log(
            "OBJ_IMPORT_LEVEL="
            + json.dumps(
                {
                    "level_path": level_path,
                    "destination_path": destination_path,
                    "static_mesh_count": len(static_meshes),
                    "origin_alignment": origin_alignment,
                    "offset": [offset.x, offset.y, offset.z],
                    "bounds_min": [minimum.x, minimum.y, minimum.z],
                    "bounds_max": [maximum.x, maximum.y, maximum.z],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    except Exception as error:
        unreal.log_error("OBJ_LEVEL_ERROR={}".format(error))
        if unfinished_level_path:
            _discard_unfinished_level(unfinished_level_path)
        raise


if __name__ == "__main__":
    main()
