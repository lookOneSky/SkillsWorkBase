"""在 Unreal 编辑器里执行 das_ue_weather.exe 下发的时间 / 天气计划。

由 das_ue_weather.exe 通过 Python 远程执行送进编辑器，用编辑器自带的 Python 运行，
本机不需要安装 Python。计划文件路径由引导语句写进全局变量 UDS_PLAN_PATH。

计划格式见 README.md 的“计划文件”一节。演员识别、步骤操作码与属性名都照搬
das-ue-weather 的 uds_common.py / ue_weather.py，改这里之前先对一遍那两份脚本。
"""

import json
import traceback

import unreal

RESULT_MARKER = "UDS_REMOTE_RESULT="

# 演员种类：类名用来认，required_properties 用来在改名 / 子蓝图的情况下兜底。
ACTOR_KINDS = {
    "sky": {
        "label": "Ultra Dynamic Sky",
        "class_names": ("ultra_dynamic_sky",),
        "required_properties": ("Time of Day",),
    },
    "weather": {
        "label": "Ultra Dynamic Weather",
        "class_names": ("ultra_dynamic_weather",),
        "required_properties": ("Weather",),
    },
}

# 天气预设的锚点类名；预设资产是它的子类，放在哪个目录不固定。
PRESET_CLASS_NAME = "uds_weather_settings"


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


def find_actor(kind, actor_hint):
    """按对象路径 / 标签指定优先；否则先按类名精确找，再退回只看必需属性。"""
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = subsystem.get_all_level_actors()
    spec = ACTOR_KINDS[kind]

    if actor_hint:
        wanted = str(actor_hint).strip()
        for actor in actors:
            if actor.get_path_name() == wanted or actor.get_actor_label() == wanted:
                return actor
        raise UdsRemoteError("找不到指定的 {} 实例：{}".format(spec["label"], wanted))

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


def find_blueprint_class(kind, blueprint_hint):
    """找到能生成该演员的蓝图类，找不到返回 None。"""
    spec = ACTOR_KINDS[kind]
    if blueprint_hint:
        wanted = str(blueprint_hint).strip()
        loaded = unreal.EditorAssetLibrary.load_blueprint_class(wanted)
        if loaded is None:
            raise UdsRemoteError("无法加载指定的蓝图：{}".format(wanted))
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


def resolve_actor(kind, actor_hint, blueprint_hint, folder, created):
    """拿到演员：先在关卡里找，找不到就用蓝图生成一个并放进大纲目录。"""
    actor = find_actor(kind, actor_hint)
    if actor is not None:
        return actor

    spec = ACTOR_KINDS[kind]
    blueprint_class = find_blueprint_class(kind, blueprint_hint)
    if blueprint_class is None:
        raise UdsRemoteError(
            "关卡里没有 {0}，工程里也找不到它的蓝图。{0} 是付费商城资产，"
            "请先把它导入工程，或用 --{1}-blueprint 指定蓝图路径。".format(
                spec["label"], "sky" if kind == "sky" else "weather"
            )
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
    """预设可以给完整资产路径，也可以只给资产名。"""
    wanted = str(asset_hint).strip()
    value = unreal.load_asset(wanted)
    if value is None:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
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


def apply_step(actor, step, applied, skipped):
    operation = step.get("op")
    name = step.get("name")
    optional = bool(step.get("optional"))

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
    actor = resolve_actor(
        kind, task.get("actor_path"), task.get("blueprint_path"), folder, created
    )

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
