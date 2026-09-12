"""das_ue_sequence.exe 的 UE Python 桥接层。

inspect 只读取当前关卡数据；apply 只把 C++ 生成的 JSON 计划写入 Sequencer。
运镜、日出时间、轨迹与关键帧算法全部位于 C++ 的 UeSequencePlan.cpp。
"""

from __future__ import print_function

import json
import math
import traceback

import unreal


RESULT_MARKER = "DAS_SUNRISE_SEQUENCE="
CAMERA_KEY_FRAMES = (0, 132, 264, 331, 404, 503, 647, 900)
TIME_KEY_FRAMES = (0, 132, 359, 477)


class SequenceBridgeError(RuntimeError):
    pass


def _plain(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _finite_or_none(value):
    number = float(value)
    return number if math.isfinite(number) else None


def _read_property(actor, property_name):
    try:
        return _plain(actor.get_editor_property(property_name))
    except Exception:
        return None


def _actor_path(actor):
    return actor.get_path_name()


def _folder_text(actor):
    try:
        return str(actor.get_folder_path()).replace("\\", "/").strip("/")
    except Exception:
        return ""


def _actor_bounds(actor):
    try:
        origin, extent = actor.get_actor_bounds(
            only_colliding_components=False,
            include_from_child_actors=True,
        )
    except TypeError:
        origin, extent = actor.get_actor_bounds(False, True)
    return {
        "origin": [
            _finite_or_none(origin.x),
            _finite_or_none(origin.y),
            _finite_or_none(origin.z),
        ],
        "extent": [
            _finite_or_none(extent.x),
            _finite_or_none(extent.y),
            _finite_or_none(extent.z),
        ],
    }


def _inspect():
    actors = unreal.get_editor_subsystem(
        unreal.EditorActorSubsystem
    ).get_all_level_actors()

    actor_descriptions = []
    directional_lights = []
    for actor in actors:
        try:
            bounds = _actor_bounds(actor)
        except Exception:
            bounds = None
        actor_descriptions.append({
            "actor_path": _actor_path(actor),
            "label": actor.get_actor_label(),
            "class_name": actor.get_class().get_name(),
            "folder": _folder_text(actor),
            "bounds_origin": bounds["origin"] if bounds else None,
            "bounds_extent": bounds["extent"] if bounds else None,
            "time_of_day": _read_property(actor, "Time of Day"),
            "latitude": _read_property(actor, "Latitude"),
            "longitude": _read_property(actor, "Longitude"),
            "time_zone": _read_property(actor, "Time Zone"),
            "animate_time_of_day": _read_property(actor, "Animate Time of Day"),
            "randomize_time_of_day": _read_property(actor, "Randomize Time Of Day"),
            "use_system_time": _read_property(actor, "Use System Time"),
            "north_yaw": _read_property(actor, "North Yaw"),
        })

        try:
            components = actor.get_components_by_class(unreal.DirectionalLightComponent)
        except Exception:
            components = ()
        for component in components:
            location = actor.get_actor_location()
            directional_lights.append({
                "actor_path": _actor_path(actor),
                "actor_label": actor.get_actor_label(),
                "class_name": actor.get_class().get_name(),
                "component_name": component.get_name(),
                "atmosphere_sun_light": bool(
                    _read_property(component, "atmosphere_sun_light") or False
                ),
                "atmosphere_sun_light_index": int(
                    _read_property(component, "atmosphere_sun_light_index") or 0
                ),
                "location": [
                    _finite_or_none(location.x),
                    _finite_or_none(location.y),
                    _finite_or_none(location.z),
                ],
            })

    return {
        "ok": True,
        "mode": "inspect",
        "actors": actor_descriptions,
        "directional_lights": directional_lights,
    }


def _find_actor(actor_path):
    actors = unreal.get_editor_subsystem(
        unreal.EditorActorSubsystem
    ).get_all_level_actors()
    for actor in actors:
        if _actor_path(actor) == actor_path:
            return actor
    raise SequenceBridgeError("当前关卡找不到 Actor：{}".format(actor_path))


def _load_plan():
    plan_path = globals().get("DAS_SEQUENCE_PLAN_PATH")
    if not plan_path:
        raise SequenceBridgeError("apply 模式没有 DAS_SEQUENCE_PLAN_PATH")
    with open(plan_path, "r", encoding="utf-8") as stream:
        plan = json.load(stream)
    if not isinstance(plan, dict):
        raise SequenceBridgeError("C++ 计划根节点不是对象")
    return plan


def _load_or_create_sequence(asset_path):
    sequence = unreal.load_asset(asset_path)
    if sequence is not None:
        if not isinstance(sequence, unreal.LevelSequence):
            raise SequenceBridgeError("{} 已存在但不是 Level Sequence".format(asset_path))
        return sequence

    directory, asset_name = asset_path.rsplit("/", 1)
    unreal.EditorAssetLibrary.make_directory(directory)
    sequence = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        asset_name,
        directory,
        unreal.LevelSequence,
        unreal.LevelSequenceFactoryNew(),
    )
    if sequence is None:
        raise SequenceBridgeError("无法创建 {}".format(asset_path))
    return sequence


def _reset_sequence(sequence):
    for binding in list(sequence.get_bindings()):
        binding.remove()
    try:
        tracks = list(sequence.get_tracks())
        remove_track = sequence.remove_track
    except AttributeError:
        tracks = list(sequence.get_master_tracks())
        remove_track = sequence.remove_master_track
    for track in tracks:
        remove_track(track)


def _root_track(sequence, track_class):
    try:
        return sequence.add_track(track_class)
    except AttributeError:
        return sequence.add_master_track(track_class)


def _channels(section):
    try:
        return list(section.get_all_channels())
    except AttributeError:
        return list(section.get_channels())


def _interpolation(name):
    if str(name).casefold() == "linear":
        return unreal.MovieSceneKeyInterpolation.LINEAR
    return unreal.MovieSceneKeyInterpolation.AUTO


def _add_key(channel, key):
    frame = unreal.FrameNumber(int(key["frame"]))
    value = float(key["value"])
    channel.add_key(
        frame,
        value,
        interpolation=_interpolation(key.get("interpolation", "auto")),
    )


def _keys_at_frames(keys, frames, interpolation=None):
    keys_by_frame = {int(key["frame"]): key for key in keys}
    sparse_keys = []
    for frame in frames:
        if frame not in keys_by_frame:
            raise SequenceBridgeError("计划缺少关键帧：{}".format(frame))
        key = dict(keys_by_frame[frame])
        if interpolation is not None:
            key["interpolation"] = interpolation(frame)
        sparse_keys.append(key)
    return sparse_keys


def _camera_interpolation(frame):
    return "auto" if frame < 647 else "linear"


def _time_interpolation(_frame):
    return "auto"


def _add_transform_track(binding, end_frame, keys):
    track = binding.add_track(unreal.MovieScene3DTransformTrack)
    section = track.add_section()
    section.set_range(0, end_frame)
    try:
        section.set_editor_property("use_quaternion_interpolation", True)
    except Exception:
        pass

    channels = _channels(section)
    if len(channels) < 9:
        raise SequenceBridgeError("Transform 轨道通道数不足：{}".format(len(channels)))
    for transform_key in keys:
        location = transform_key["location"]
        rotation = transform_key["rotation"]
        scale = transform_key.get("scale", [1.0, 1.0, 1.0])
        values = location + [rotation[2], rotation[0], rotation[1]] + scale
        for channel, value in zip(channels[:9], values):
            _add_key(channel, {
                "frame": transform_key["frame"],
                "value": value,
                "interpolation": transform_key.get("interpolation", "auto"),
            })


def _add_camera(sequence, plan):
    camera = plan["camera"]
    binding = sequence.add_spawnable_from_class(unreal.CineCameraActor)
    binding.set_display_name(camera["display_name"])
    template = binding.get_object_template()
    if template is None:
        raise SequenceBridgeError("Spawnable CineCameraActor 没有对象模板")

    component = template.get_cine_camera_component()
    if component is None:
        # UE 5.3 的 Spawnable 模板可通过属性取得相机组件，但
        # CineCameraActor.get_cine_camera_component() 会错误返回 None。
        component = template.get_editor_property("camera_component")
    if component is None:
        raise SequenceBridgeError("Spawnable CineCameraActor 没有相机组件")
    # 用 C++ 取景计算所用的同一画幅和焦距，避免默认 Filmback / Lens 预设改变视野。
    filmback = component.get_editor_property("filmback")
    filmback.set_editor_property("sensor_width", float(camera["sensor_width_mm"]))
    filmback.set_editor_property("sensor_height", float(camera["sensor_height_mm"]))
    # UE 5.3 Python 将相机 setter 暴露为属性写入，统一通过编辑器属性设置。
    component.set_editor_property("filmback", filmback)
    focal_length = float(camera["focal_length_mm"])
    lens = component.get_editor_property("lens_settings")
    lens.set_editor_property("min_focal_length", min(
        float(lens.get_editor_property("min_focal_length")), focal_length
    ))
    lens.set_editor_property("max_focal_length", max(
        float(lens.get_editor_property("max_focal_length")), focal_length
    ))
    component.set_editor_property("lens_settings", lens)
    component.set_editor_property("current_focal_length", focal_length)
    component.set_editor_property("constrain_aspect_ratio", True)
    component.set_editor_property("aspect_ratio", float(camera["aspect_ratio"]))
    component.set_editor_property("override_custom_near_clipping_plane", True)
    component.set_editor_property("custom_near_clipping_plane", float(camera["near_clip_cm"]))
    # 模型尺度和拉远距离都可变化，避免固定手动焦距使模型失焦。
    focus = component.get_editor_property("focus_settings")
    focus.set_editor_property("focus_method", unreal.CameraFocusMethod.DISABLE)
    component.set_editor_property("focus_settings", focus)

    camera_keys = _keys_at_frames(
        camera["transform_keys"], CAMERA_KEY_FRAMES, _camera_interpolation
    )
    _add_transform_track(binding, int(plan["end_frame"]), camera_keys)
    cut_track = _root_track(sequence, unreal.MovieSceneCameraCutTrack)
    cut_section = cut_track.add_section()
    cut_section.set_range(0, int(plan["end_frame"]))
    cut_section.set_camera_binding_id(sequence.get_binding_id(binding))


def _add_sky(sequence, plan):
    sky = plan.get("sky")
    if not sky:
        return False
    actor = _find_actor(sky["actor_path"])
    for entry in sky["properties"]:
        actor.set_editor_property(entry["name"], entry["value"])
    try:
        actor.call_method("SetTimeofDay", (float(sky["initial_time"]),))
    except Exception:
        actor.set_editor_property("Time of Day", float(sky["initial_time"]))

    binding = sequence.add_possessable(actor)
    binding.set_display_name(sky["display_name"])
    # 与参考资源中 UDS 的 Time of Day Double 属性匹配。
    track = binding.add_track(unreal.MovieSceneDoubleTrack)
    track.set_property_name_and_path(sky["property_name"], sky["property_path"])
    section = track.add_section()
    section.set_range(0, int(plan["end_frame"]))
    channels = _channels(section)
    if not channels:
        raise SequenceBridgeError("Time of Day 轨道没有可写通道")
    time_keys = _keys_at_frames(sky["time_keys"], TIME_KEY_FRAMES, _time_interpolation)
    for key in time_keys:
        _add_key(channels[0], key)
    return True


def _add_sun(sequence, plan):
    sun = plan.get("sun")
    if not sun:
        return
    actor = _find_actor(sun["actor_path"])
    binding = sequence.add_possessable(actor)
    binding.set_display_name(sun["display_name"])
    sun_keys = _keys_at_frames(
        sun["transform_keys"], TIME_KEY_FRAMES, _time_interpolation
    )
    _add_transform_track(binding, int(plan["end_frame"]), sun_keys)


def _apply():
    plan = _load_plan()
    sequence = _load_or_create_sequence(plan["sequence_path"])
    _reset_sequence(sequence)
    sequence.set_display_rate(
        unreal.FrameRate(numerator=int(plan["fps"]), denominator=1)
    )
    sequence.set_playback_start(0)
    sequence.set_playback_end(int(plan["end_frame"]))
    _add_camera(sequence, plan)
    sky_changed = _add_sky(sequence, plan)
    _add_sun(sequence, plan)

    subsystem = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
    if not subsystem.save_loaded_asset(sequence, False):
        raise SequenceBridgeError("保存序列失败：{}".format(plan["sequence_path"]))
    if sky_changed and not unreal.EditorLoadingAndSavingUtils.save_current_level():
        raise SequenceBridgeError("序列已保存，但天空参数所在关卡保存失败")

    if bool(plan.get("play", True)):
        library = unreal.LevelSequenceEditorBlueprintLibrary
        library.open_level_sequence(sequence)
        library.set_current_time(0)
        library.play()

    return {
        "ok": True,
        "mode": "apply",
        "asset_path": plan["sequence_path"],
        "played": bool(plan.get("play", True)),
        "summary": plan["summary"],
    }


try:
    mode = str(globals().get("DAS_SEQUENCE_MODE", "")).casefold()
    if mode == "inspect":
        OUTCOME = _inspect()
    elif mode == "apply":
        OUTCOME = _apply()
    else:
        raise SequenceBridgeError("未知桥接模式：{}".format(mode))
except Exception as error:
    OUTCOME = {
        "ok": False,
        "error": str(error),
        "traceback": traceback.format_exc(),
    }

print(RESULT_MARKER + json.dumps(OUTCOME, ensure_ascii=False, sort_keys=True))
