"""在 Unreal 编辑器里执行 das_ue_weather.exe 下发的时间 / 天气计划。

由 das_ue_weather.exe 通过 Python 远程执行送进编辑器，用编辑器自带的 Python 运行，
本机不需要安装 Python。计划文件路径由引导语句写进全局变量 UDS_PLAN_PATH。

计划格式见 README.md 的“计划文件”一节。演员识别、步骤操作码与属性名都照搬
das-ue-weather 的 uds_common.py / ue_weather.py，改这里之前先对一遍那两份脚本。
"""

import json
import math
import os
import traceback

import unreal

RESULT_MARKER = "UDS_REMOTE_RESULT="

# 演员种类：类名用来认，required_properties 用来在改名 / 子蓝图的情况下兜底，
# blueprint_paths 是商城资产的默认落点，命中就省掉一次全资产库扫描。
ACTOR_KINDS = {
    "sky": {
        "label": "Ultra Dynamic Sky",
        "class_names": ("ultra_dynamic_sky",),
        "required_properties": ("Time of Day",),
        "blueprint_paths": ("/Game/UltraDynamicSky/Blueprints/Ultra_Dynamic_Sky",),
    },
    "weather": {
        "label": "Ultra Dynamic Weather",
        "class_names": ("ultra_dynamic_weather",),
        "required_properties": ("Weather",),
        "blueprint_paths": ("/Game/UltraDynamicSky/Blueprints/Ultra_Dynamic_Weather",),
    },
}

# 天气预设的默认目录；预设是 UDS_Weather_Settings 的子类，工程挪过目录时靠资产名兜底。
PRESET_FOLDERS = ("/Game/UltraDynamicSky/Blueprints/Weather_Effects/Weather_Presets",)

OBJ_IMPORT_ROOT = "/Game/ObjImport"
DATA_INFO_DIRECTORY = "DasDataInfo"
METADATA_FILE_NAME = "metadata.json"
REAL_CELESTIAL_PROPERTIES = (
    "Simulate Real Sun",
    "Simulate Real Moon",
    "Simulate Real Stars",
    "Latitude",
    "Longitude",
    "Time Zone",
    "North Yaw",
)


class UdsRemoteError(RuntimeError):
    pass


def normalize_name(name):
    """蓝图生成类带 _C 后缀，统一去掉再比较。"""
    text = str(name or "").strip().lower()
    if text.endswith("_c"):
        text = text[:-2]
    return text


def class_name_candidates(actor):
    """收集一个演员所有可能的类名：自身类名加整条继承链。"""
    names = []
    try:
        names.append(actor.get_class().get_name())
    except Exception:
        pass
    try:
        for entry in type(actor).__mro__:
            names.append(entry.__name__)
    except Exception:
        pass
    return [normalize_name(name) for name in names if name]


def has_properties(actor, property_names):
    for property_name in property_names:
        try:
            actor.get_editor_property(property_name)
        except Exception:
            return False
    return True


def find_actor(kind):
    """在关卡里找实例：先按类名精确找，再退回只看必需属性。"""
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = subsystem.get_all_level_actors()
    spec = ACTOR_KINDS[kind]

    loose_match = None
    for actor in actors:
        if not has_properties(actor, spec["required_properties"]):
            continue
        if any(name in spec["class_names"] for name in class_name_candidates(actor)):
            return actor
        if loose_match is None:
            loose_match = actor
    return loose_match


def iter_blueprint_assets():
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        return registry.get_assets_by_class(
            unreal.TopLevelAssetPath("/Script/Engine", "Blueprint"), True
        )
    except Exception:
        # UE 5.0 之前 get_assets_by_class 收的是纯字符串类名。
        return registry.get_assets_by_class("Blueprint", True)


def asset_name_of(asset_data):
    try:
        return str(asset_data.asset_name)
    except Exception:
        return ""


def find_blueprint_class(kind):
    """找到能生成该演员的蓝图类：先试默认路径，再扫资产库按名字认，找不到返回 None。"""
    spec = ACTOR_KINDS[kind]
    for asset_path in spec["blueprint_paths"]:
        try:
            loaded = unreal.EditorAssetLibrary.load_blueprint_class(asset_path)
        except Exception:
            loaded = None
        if loaded is not None:
            return loaded

    for asset_data in iter_blueprint_assets():
        if normalize_name(asset_name_of(asset_data)) not in spec["class_names"]:
            continue
        try:
            object_path = str(asset_data.get_editor_property("package_name"))
            asset_path = "{}.{}".format(object_path, asset_name_of(asset_data))
            loaded = unreal.EditorAssetLibrary.load_blueprint_class(asset_path)
        except Exception:
            continue
        if loaded is not None:
            return loaded
    return None


def resolve_actor(kind, folder, created):
    """拿到演员：先在关卡里找，找不到就用蓝图生成一个并放进大纲目录。"""
    actor = find_actor(kind)
    if actor is not None:
        return actor

    spec = ACTOR_KINDS[kind]
    blueprint_class = find_blueprint_class(kind)
    if blueprint_class is None:
        raise UdsRemoteError(
            "关卡里没有 {0}，工程里也找不到它的蓝图。{0} 是付费商城资产，"
            "请先把它导入工程。".format(spec["label"])
        )

    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = subsystem.spawn_actor_from_class(
        blueprint_class, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0)
    )
    if actor is None:
        raise UdsRemoteError("无法生成 {}".format(spec["label"]))
    if folder:
        try:
            actor.set_folder_path(folder)
        except Exception:
            pass
    created.append(spec["label"])
    return actor


def resolve_preset(asset_hint):
    """外面只给天气类型的资产名，路径在这里找：先默认目录，再扫资产库。"""
    wanted = str(asset_hint).strip()
    value = None
    for folder in PRESET_FOLDERS:
        try:
            value = unreal.load_asset("{}/{}".format(folder, wanted))
        except Exception:
            value = None
        if value is not None:
            break
    if value is None:
        for asset_data in iter_blueprint_assets():
            if asset_name_of(asset_data).lower() != wanted.lower():
                continue
            value = unreal.load_asset(str(asset_data.get_editor_property("package_name")))
            if value is not None:
                break
    if value is None:
        raise UdsRemoteError("找不到天气预设资产：{}".format(wanted))
    # 预设槽要的是对象；给到的是类时取它的默认对象。
    if isinstance(value, unreal.Class):
        value = unreal.get_default_object(value)
    return value


def obj_import_batch_from_asset_path(asset_path):
    """从真实资产路径提取 /Game/ObjImport 下的实际批次名。"""
    normalized = str(asset_path or "").strip().replace("\\", "/")
    package_path = normalized.split(".", 1)[0]
    prefix = OBJ_IMPORT_ROOT + "/"
    if not package_path.casefold().startswith(prefix.casefold()):
        return None

    relative_path = package_path[len(prefix) :]
    batch_name = relative_path.split("/", 1)[0].strip()
    if not batch_name:
        return None
    return {
        "name": batch_name,
        "root": "{}/{}".format(OBJ_IMPORT_ROOT, batch_name),
    }


def current_world_obj_import_batch():
    """当前关卡本身位于 ObjImport 批次内时，优先用它消除多批次歧义。"""
    try:
        subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        world = subsystem.get_editor_world()
        if world is not None:
            return obj_import_batch_from_asset_path(world.get_path_name())
    except Exception:
        pass
    return None


def actor_folder_path(actor):
    try:
        return str(actor.get_folder_path())
    except Exception:
        return ""


def static_meshes_of_actor(actor):
    """兼容 StaticMeshActor 与带 StaticMeshComponent 的自定义 Actor。"""
    components = []
    try:
        component = actor.get_editor_property("static_mesh_component")
        if component is not None:
            components.append(component)
    except Exception:
        pass
    try:
        components.extend(actor.get_components_by_class(unreal.StaticMeshComponent))
    except Exception:
        pass

    meshes = []
    mesh_paths = set()
    for component in components:
        try:
            static_mesh = component.get_editor_property("static_mesh")
        except Exception:
            continue
        if static_mesh is None:
            continue
        mesh_path = static_mesh.get_path_name()
        if mesh_path in mesh_paths:
            continue
        mesh_paths.add(mesh_path)
        meshes.append(static_mesh)
    return meshes


def collect_obj_import_batches():
    """由当前数据大纲里的 StaticMesh 真实资产路径反查导入批次。"""
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    batches = {}
    for level_actor in subsystem.get_all_level_actors():
        folder_path = actor_folder_path(level_actor)
        for static_mesh in static_meshes_of_actor(level_actor):
            static_mesh_path = static_mesh.get_path_name()
            batch = obj_import_batch_from_asset_path(static_mesh_path)
            if batch is None:
                continue
            batch_key = batch["root"].casefold()
            if batch_key not in batches:
                batches[batch_key] = {
                    "name": batch["name"],
                    "root": batch["root"],
                    "folder": folder_path,
                    "static_mesh": static_mesh_path,
                }
    return batches


def select_current_obj_import_batch():
    batches = collect_obj_import_batches()
    if not batches:
        raise UdsRemoteError(
            "当前关卡的数据大纲里没有引用 /Game/ObjImport 的 StaticMesh，"
            "无法确定真实天体模拟原点。"
        )

    world_batch = current_world_obj_import_batch()
    if world_batch is not None:
        world_key = world_batch["root"].casefold()
        if world_key in batches:
            return batches[world_key]
        raise UdsRemoteError(
            "当前 ObjImport 关卡属于批次 {}，但数据大纲中的 StaticMesh 不属于该批次。".format(
                world_batch["name"]
            )
        )

    if len(batches) == 1:
        return next(iter(batches.values()))

    batch_names = sorted(batch["name"] for batch in batches.values())
    raise UdsRemoteError(
        "当前关卡包含多个 ObjImport 批次，无法确定真实天体模拟原点：{}".format(
            "、".join(batch_names)
        )
    )


def metadata_file_for_batch(batch):
    content_directory = unreal.Paths.convert_relative_path_to_full(
        unreal.Paths.project_content_dir()
    )
    relative_batch = batch["root"][len("/Game/") :]
    return os.path.normpath(
        os.path.join(
            content_directory,
            *relative_batch.split("/"),
            DATA_INFO_DIRECTORY,
            METADATA_FILE_NAME
        )
    )


def finite_coordinate(value, field_name, minimum, maximum, metadata_file):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UdsRemoteError(
            "{} 的 {} 不是有效数值：{}".format(metadata_file, field_name, value)
        )
    coordinate = float(value)
    if not math.isfinite(coordinate) or coordinate < minimum or coordinate > maximum:
        raise UdsRemoteError(
            "{} 的 {} 超出范围 [{}, {}]：{}".format(
                metadata_file, field_name, minimum, maximum, value
            )
        )
    return coordinate


def read_batch_real_origin(batch):
    metadata_file = metadata_file_for_batch(batch)
    try:
        with open(metadata_file, "r", encoding="utf-8-sig") as stream:
            document = json.load(stream)
    except (OSError, ValueError) as error:
        raise UdsRemoteError(
            "无法读取对应 ObjImport 批次的 {}：{}".format(metadata_file, error)
        )
    if not isinstance(document, dict):
        raise UdsRemoteError("{} 的 JSON 根节点不是对象。".format(metadata_file))

    destination_path = document.get("destination_path")
    if (
        isinstance(destination_path, str)
        and destination_path.strip()
        and destination_path.strip().rstrip("/").casefold() != batch["root"].casefold()
    ):
        raise UdsRemoteError(
            "{} 记录的 destination_path 与当前 StaticMesh 批次不一致：{}".format(
                metadata_file, destination_path
            )
        )

    metadata_entries = document.get("metadata")
    if not isinstance(metadata_entries, list) or not metadata_entries:
        raise UdsRemoteError("{} 没有 metadata 经纬度记录。".format(metadata_file))
    origin = metadata_entries[0]
    if not isinstance(origin, dict):
        raise UdsRemoteError("{} 的第一条 metadata 记录不是对象。".format(metadata_file))

    return {
        "latitude": finite_coordinate(
            origin.get("latitude"), "latitude", -90.0, 90.0, metadata_file
        ),
        "longitude": finite_coordinate(
            origin.get("longitude"), "longitude", -180.0, 180.0, metadata_file
        ),
        "metadata_file": metadata_file,
    }


def initialize_real_celestial_from_obj_import(actor, applied, skipped):
    """Sun 已开启代表用户配置过；否则一次性初始化整组真实天体参数。"""
    try:
        real_sun_enabled = bool(actor.get_editor_property("Simulate Real Sun"))
    except Exception as error:
        raise UdsRemoteError("读取 Simulate Real Sun 失败：{}".format(error))
    if real_sun_enabled:
        skipped.append("真实 Sun 模拟已开启，保留用户调整过的天体配置")
        return

    # 先检查 UDS 版本与原点数据，所有前置条件满足后才开始写 Actor。
    for property_name in REAL_CELESTIAL_PROPERTIES[1:]:
        try:
            actor.get_editor_property(property_name)
        except Exception as error:
            raise UdsRemoteError("读取 {} 失败：{}".format(property_name, error))
    batch = select_current_obj_import_batch()
    origin = read_batch_real_origin(batch)

    values = (
        ("Latitude", origin["latitude"]),
        ("Longitude", origin["longitude"]),
        ("Time Zone", 8.0),
        ("North Yaw", 270.0),
        ("Simulate Real Moon", True),
        ("Simulate Real Stars", True),
        # Sun 最后写；中途失败时下次设置时间仍会重新完成初始化。
        ("Simulate Real Sun", True),
    )
    for property_name, value in values:
        try:
            actor.set_editor_property(property_name, value)
        except Exception as error:
            raise UdsRemoteError("写属性 {} 失败：{}".format(property_name, error))
        applied.append("{}={}".format(property_name, value))
    applied.append(
        "真实天体来源={}，大纲目录={}，StaticMesh={}，metadata={}".format(
            batch["name"],
            batch["folder"] or "<根目录>",
            batch["static_mesh"],
            origin["metadata_file"],
        )
    )


def apply_step(actor, step, applied, skipped):
    operation = step.get("op")
    name = step.get("name")
    optional = bool(step.get("optional"))

    if operation == "initialize_real_celestial_from_obj_import":
        initialize_real_celestial_from_obj_import(actor, applied, skipped)
        return

    if operation == "property":
        try:
            actor.set_editor_property(name, step.get("value"))
        except Exception as error:
            if optional:
                skipped.append("{}（属性不存在）".format(name))
                return
            raise UdsRemoteError("写属性 {} 失败：{}".format(name, error))
        applied.append("{}={}".format(name, step.get("value")))
        return

    if operation == "preset":
        value = resolve_preset(step.get("asset"))
        try:
            actor.set_editor_property(name, value)
        except Exception as error:
            raise UdsRemoteError("写预设 {} 失败：{}".format(name, error))
        applied.append("{}={}".format(name, step.get("asset")))
        return

    if operation == "call":
        try:
            actor.call_method(name, tuple(step.get("args") or ()))
        except Exception as error:
            if optional:
                skipped.append("{}（函数不存在）".format(name))
                return
            raise UdsRemoteError("调用 {} 失败：{}".format(name, error))
        applied.append("{}()".format(name))
        return

    if operation == "call_or_property":
        # 新版 UDS 有 SetTimeofDay，老版本只能直接写属性。
        try:
            actor.call_method(name, tuple(step.get("args") or ()))
            applied.append("{}()".format(name))
            return
        except Exception:
            pass
        property_name = step.get("property")
        try:
            actor.set_editor_property(property_name, step.get("value"))
        except Exception as error:
            raise UdsRemoteError(
                "调用 {} 与写属性 {} 都失败：{}".format(name, property_name, error)
            )
        applied.append("{}={}".format(property_name, step.get("value")))
        return

    raise UdsRemoteError("未知的步骤操作码：{}".format(operation))


def to_plain(value):
    """读回来的值可能是 UObject 或结构体，统一转成能进 JSON 的形式。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    try:
        return value.get_path_name()
    except Exception:
        return str(value)


def read_values(actor, reads):
    values = {}
    for entry in reads or ():
        alias = entry.get("as") or entry.get("name")
        try:
            if entry.get("op") == "call":
                values[alias] = to_plain(actor.call_method(entry.get("name"), ()))
            else:
                values[alias] = to_plain(actor.get_editor_property(entry.get("name")))
        except Exception:
            values[alias] = None
    return values


def save_actor(actor, saved):
    try:
        unreal.EditorLoadingAndSavingUtils.save_current_level()
        saved.append("current_level")
    except Exception as error:
        saved.append("current_level 失败：{}".format(error))
    try:
        package = actor.get_package()
        if package is not None:
            unreal.EditorLoadingAndSavingUtils.save_packages([package], False)
            saved.append(package.get_name())
    except Exception as error:
        saved.append("actor package 失败：{}".format(error))


def run_task(task, folder, should_save):
    kind = task.get("kind")
    if kind not in ACTOR_KINDS:
        raise UdsRemoteError("未知的任务类型：{}".format(kind))

    created = []
    actor = resolve_actor(kind, folder, created)

    applied = []
    skipped = []
    before = read_values(actor, task.get("reads"))
    with unreal.ScopedEditorTransaction(task.get("transaction") or "das_ue_weather"):
        for step in task.get("steps") or ():
            apply_step(actor, step, applied, skipped)
    after = read_values(actor, task.get("reads"))

    saved = []
    if should_save:
        save_actor(actor, saved)

    return {
        "kind": kind,
        "label": ACTOR_KINDS[kind]["label"],
        "created": created,
        "actor_path": actor.get_path_name(),
        "actor_label": actor.get_actor_label(),
        "applied": applied,
        "skipped": skipped,
        "saved": saved,
        "before": before,
        "after": after,
    }


def main():
    plan_path = globals().get("UDS_PLAN_PATH")
    if not plan_path:
        raise UdsRemoteError("引导语句没有设置 UDS_PLAN_PATH。")
    with open(plan_path, "r", encoding="utf-8") as stream:
        plan = json.load(stream)

    folder = plan.get("outliner_folder") or ""
    should_save = bool(plan.get("save"))
    tasks = plan.get("tasks") or ()
    if not tasks:
        raise UdsRemoteError("计划里没有任何任务。")

    results = []
    for task in tasks:
        results.append(run_task(task, folder, should_save))
    return {"ok": True, "tasks": results}


try:
    OUTCOME = main()
except Exception as top_error:  # 失败也要回一份结构化结果，exe 才能报出原因。
    OUTCOME = {
        "ok": False,
        "error": str(top_error),
        "traceback": traceback.format_exc(),
    }

print(RESULT_MARKER + json.dumps(OUTCOME, ensure_ascii=False))
