"""在 Unreal Editor 中生成固定 30 秒建筑日出 Level Sequence。

输入只取当前关卡数据大纲 ``DasImport`` 目录及其子目录中的 Actor。
脚本会覆盖 ``/Game/Cinematics/LS_Auto`` 内已有的轨道和绑定，然后打开并播放序列。
"""

from __future__ import print_function

import json
import math
import traceback

import unreal


SEQUENCE_PATH = "/Game/Cinematics/LS_Auto"
MODEL_FOLDER = "DasImport"

FPS = 30
DURATION_SECONDS = 30
END_FRAME = FPS * DURATION_SECONDS

SUNRISE_FRAME = 8 * FPS
FIRST_PULL_FRAME = 14 * FPS
SUN_FRONT_FRAME = 24 * FPS

CAMERA_FOCAL_LENGTH_MM = 18.0
CAMERA_ASPECT_RATIO = 16.0 / 9.0
CAMERA_HORIZONTAL_FOV_DEGREES = 65.0

SUNRISE_FALLBACK_TIME = 600.0
SUNRISE_SCAN_END = 1200.0
SUNRISE_SCAN_STEP = 20.0
SUNRISE_BINARY_STEPS = 10

RESULT_MARKER = "DAS_SUNRISE_SEQUENCE="


class SunriseSequenceError(RuntimeError):
    """当前关卡无法生成日出序列。"""


def _vector(value):
    return [float(value.x), float(value.y), float(value.z)]


def _folder_text(actor):
    try:
        return str(actor.get_folder_path()).replace("\\", "/").strip("/")
    except Exception:
        return ""


def _is_in_model_folder(actor):
    folder = _folder_text(actor).casefold()
    wanted = MODEL_FOLDER.casefold()
    return folder == wanted or folder.startswith(wanted + "/")


def _collect_model_actors():
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = [actor for actor in subsystem.get_all_level_actors() if _is_in_model_folder(actor)]
    if not actors:
        raise SunriseSequenceError(
            "当前关卡的数据大纲中没有 {} 目录下的 Actor。".format(MODEL_FOLDER)
        )
    return actors


def _actor_bounds(actor):
    try:
        origin, extent = actor.get_actor_bounds(
            only_colliding_components=False,
            include_from_child_actors=True,
        )
    except TypeError:
        origin, extent = actor.get_actor_bounds(False, True)

    values = (origin.x, origin.y, origin.z, extent.x, extent.y, extent.z)
    if not all(math.isfinite(float(value)) for value in values):
        return None
    return origin, extent


def _merge_model_bounds(actors):
    minimum = None
    maximum = None
    highest_actor = None
    highest_z = -float("inf")

    for actor in actors:
        bounds = _actor_bounds(actor)
        if bounds is None:
            unreal.log_warning(
                "[SunriseSequence] 跳过无有效包围盒的 Actor：{}".format(
                    actor.get_actor_label()
                )
            )
            continue
        origin, extent = bounds
        actor_minimum = unreal.Vector(
            origin.x - extent.x,
            origin.y - extent.y,
            origin.z - extent.z,
        )
        actor_maximum = unreal.Vector(
            origin.x + extent.x,
            origin.y + extent.y,
            origin.z + extent.z,
        )
        if minimum is None:
            minimum = actor_minimum
            maximum = actor_maximum
        else:
            minimum.x = min(minimum.x, actor_minimum.x)
            minimum.y = min(minimum.y, actor_minimum.y)
            minimum.z = min(minimum.z, actor_minimum.z)
            maximum.x = max(maximum.x, actor_maximum.x)
            maximum.y = max(maximum.y, actor_maximum.y)
            maximum.z = max(maximum.z, actor_maximum.z)

        if actor_maximum.z > highest_z:
            highest_z = actor_maximum.z
            highest_actor = actor

    if minimum is None:
        raise SunriseSequenceError(
            "{} 目录下的 Actor 都没有有效包围盒。".format(MODEL_FOLDER)
        )
    return minimum, maximum, highest_actor


def _make_rotator(pitch, yaw=0.0, roll=0.0):
    return unreal.Rotator(pitch=float(pitch), yaw=float(yaw), roll=float(roll))


def _camera_plan(minimum, maximum, sun_focus_pitch):
    size_x = max(float(maximum.x - minimum.x), 100.0)
    size_y = max(float(maximum.y - minimum.y), 100.0)
    size_z = max(float(maximum.z - minimum.z), 100.0)
    center_y = (minimum.y + maximum.y) * 0.5

    horizontal_fov = math.radians(CAMERA_HORIZONTAL_FOV_DEGREES)
    vertical_fov = 2.0 * math.atan(
        math.tan(horizontal_fov * 0.5) / CAMERA_ASPECT_RATIO
    )

    clearance = max(size_z * 0.06, max(size_x, size_y) * 0.015, 100.0)
    horizontal_distance = (size_y * 0.5) / math.tan(horizontal_fov * 0.43)
    vertical_distance = (size_z + clearance) / math.tan(vertical_fov * 0.85)
    stand_off = max(horizontal_distance, vertical_distance, size_x * 0.35, 300.0)
    stand_off *= 1.08

    initial_location = unreal.Vector(
        minimum.x - stand_off,
        center_y,
        maximum.z + clearance,
    )
    first_pull_location = unreal.Vector(
        initial_location.x - stand_off * 0.45,
        initial_location.y,
        initial_location.z + clearance * 0.12,
    )
    final_location = unreal.Vector(
        first_pull_location.x - stand_off * 0.60,
        first_pull_location.y,
        first_pull_location.z + clearance * 0.08,
    )

    # 场景全部位于相机下方，太阳沿 +X 地平线出现；该俯角让二者同时留在画面内。
    initial_rotation = _make_rotator(-math.degrees(vertical_fov) * 0.42)
    sun_rotation = _make_rotator(max(1.0, min(float(sun_focus_pitch), 12.0)))

    return (
        (0, initial_location, initial_rotation),
        (SUNRISE_FRAME, initial_location, initial_rotation),
        (FIRST_PULL_FRAME, first_pull_location, initial_rotation),
        (SUN_FRONT_FRAME, first_pull_location, sun_rotation),
        (END_FRAME, final_location, sun_rotation),
    )


def _has_property(actor, property_name):
    try:
        actor.get_editor_property(property_name)
        return True
    except Exception:
        return False


def _find_sky_actor(actors):
    candidates = []
    for actor in actors:
        if not _has_property(actor, "Time of Day"):
            continue
        try:
            class_name = actor.get_class().get_name().casefold()
        except Exception:
            class_name = ""
        score = 10 if "ultra_dynamic_sky" in class_name else 0
        candidates.append((score, actor.get_actor_label().casefold(), actor))
    if not candidates:
        return None
    candidates.sort(key=lambda value: (-value[0], value[1]))
    return candidates[0][2]


def _all_directional_light_components(actors):
    components = []
    for actor in actors:
        try:
            components.extend(actor.get_components_by_class(unreal.DirectionalLightComponent))
        except Exception:
            continue
    return components


def _sun_component_score(component, sky_actor):
    score = 0
    try:
        if bool(component.get_editor_property("atmosphere_sun_light")):
            score += 100
            if int(component.get_editor_property("atmosphere_sun_light_index")) == 0:
                score += 50
    except Exception:
        pass

    try:
        owner = component.get_owner()
    except Exception:
        owner = None
    if owner == sky_actor:
        score += 40

    names = []
    try:
        names.append(component.get_name())
    except Exception:
        pass
    if owner is not None:
        try:
            names.append(owner.get_actor_label())
            names.append(owner.get_class().get_name())
        except Exception:
            pass
    text = " ".join(str(name) for name in names).casefold()
    if "sun" in text:
        score += 25
    if "moon" in text:
        score -= 75
    return score


def _sun_component_name(component):
    names = []
    try:
        names.append(component.get_owner().get_actor_label())
    except Exception:
        pass
    try:
        names.append(component.get_name())
    except Exception:
        pass
    return "/".join(str(name) for name in names).casefold()


def _find_sun_component(actors, sky_actor):
    components = _all_directional_light_components(actors)
    if not components:
        return None
    components.sort(
        key=lambda value: (
            -_sun_component_score(value, sky_actor),
            _sun_component_name(value),
        )
    )
    return components[0]


def _apply_time_of_day(sky_actor, value):
    try:
        sky_actor.call_method("SetTimeofDay", (float(value),))
        return
    except Exception:
        pass
    sky_actor.set_editor_property("Time of Day", float(value))


def _sun_elevation(component):
    forward = component.get_forward_vector()
    visible_sun_z = max(-1.0, min(1.0, -float(forward.z)))
    return math.degrees(math.asin(visible_sun_z))


def _detect_sunrise_time(sky_actor, sun_component):
    original_time = float(sky_actor.get_editor_property("Time of Day"))
    samples = []
    try:
        value = 0.0
        while value <= SUNRISE_SCAN_END:
            _apply_time_of_day(sky_actor, value)
            samples.append((value, _sun_elevation(sun_component)))
            value += SUNRISE_SCAN_STEP

        elevations = [sample[1] for sample in samples]
        if max(elevations) - min(elevations) < 5.0:
            raise SunriseSequenceError("太阳组件未随 Time of Day 更新")

        lower = None
        upper = None
        for previous, current in zip(samples, samples[1:]):
            if previous[1] <= 0.0 < current[1]:
                lower = previous[0]
                upper = current[0]
                break
        if lower is None:
            raise SunriseSequenceError("0:00 至 12:00 没有检测到太阳穿过地平线")

        for _ in range(SUNRISE_BINARY_STEPS):
            middle = (lower + upper) * 0.5
            _apply_time_of_day(sky_actor, middle)
            if _sun_elevation(sun_component) > 0.0:
                upper = middle
            else:
                lower = middle
        return (lower + upper) * 0.5, True
    except Exception as error:
        unreal.log_warning(
            "[SunriseSequence] 无法从太阳组件采样日出，使用 06:00：{}".format(error)
        )
        return SUNRISE_FALLBACK_TIME, False
    finally:
        _apply_time_of_day(sky_actor, original_time)


def _sun_focus_pitch(sky_actor, sun_component, time_of_day):
    if sky_actor is None or sun_component is None:
        return 8.0
    original_time = float(sky_actor.get_editor_property("Time of Day"))
    try:
        _apply_time_of_day(sky_actor, time_of_day)
        return _sun_elevation(sun_component)
    except Exception:
        return 8.0
    finally:
        _apply_time_of_day(sky_actor, original_time)


def _set_sky_for_sequencer(sky_actor, initial_time):
    for property_name in (
        "Animate Time of Day",
        "Randomize Time Of Day",
        "Use System Time",
    ):
        if _has_property(sky_actor, property_name):
            sky_actor.set_editor_property(property_name, False)
    if _has_property(sky_actor, "North Yaw"):
        # 工程现有天气工具也用 270°，对应日出沿世界 +X 方向。
        sky_actor.set_editor_property("North Yaw", 270.0)
    _apply_time_of_day(sky_actor, initial_time)


def _load_or_create_sequence():
    sequence = unreal.load_asset(SEQUENCE_PATH)
    if sequence is not None:
        if not isinstance(sequence, unreal.LevelSequence):
            raise SunriseSequenceError("{} 已存在但不是 Level Sequence。".format(SEQUENCE_PATH))
        return sequence

    directory, asset_name = SEQUENCE_PATH.rsplit("/", 1)
    unreal.EditorAssetLibrary.make_directory(directory)
    sequence = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        asset_name,
        directory,
        unreal.LevelSequence,
        unreal.LevelSequenceFactoryNew(),
    )
    if sequence is None:
        raise SunriseSequenceError("无法创建 {}。".format(SEQUENCE_PATH))
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


def _sequence_track(sequence, track_class):
    try:
        return sequence.add_track(track_class)
    except AttributeError:
        return sequence.add_master_track(track_class)


def _section_channels(section):
    try:
        return list(section.get_all_channels())
    except AttributeError:
        return list(section.get_channels())


def _add_key(channel, frame, value, interpolation):
    try:
        channel.add_key(
            unreal.FrameNumber(int(frame)),
            float(value),
            interpolation=interpolation,
        )
    except TypeError:
        channel.add_key(unreal.FrameNumber(int(frame)), float(value))


def _add_transform_track(binding, keys):
    track = binding.add_track(unreal.MovieScene3DTransformTrack)
    section = track.add_section()
    section.set_range(0, END_FRAME)
    try:
        section.set_editor_property("use_quaternion_interpolation", True)
    except Exception:
        pass

    channels = _section_channels(section)
    if len(channels) < 9:
        raise SunriseSequenceError("Transform 轨道通道数不足：{}。".format(len(channels)))

    interpolation = unreal.MovieSceneKeyInterpolation.AUTO
    for frame, location, rotation in keys:
        values = (
            location.x,
            location.y,
            location.z,
            rotation.roll,
            rotation.pitch,
            rotation.yaw,
            1.0,
            1.0,
            1.0,
        )
        for channel, value in zip(channels[:9], values):
            _add_key(channel, frame, value, interpolation)


def _add_camera(sequence, camera_keys):
    binding = sequence.add_spawnable_from_class(unreal.CineCameraActor)
    binding.set_display_name("CAM_LS_Auto_Sunrise")
    camera_template = binding.get_object_template()
    component = camera_template.get_cine_camera_component()
    component.set_editor_property("current_focal_length", CAMERA_FOCAL_LENGTH_MM)
    try:
        component.set_editor_property("constrain_aspect_ratio", True)
        component.set_editor_property("aspect_ratio", CAMERA_ASPECT_RATIO)
    except Exception:
        pass

    _add_transform_track(binding, camera_keys)

    cut_track = _sequence_track(sequence, unreal.MovieSceneCameraCutTrack)
    cut_section = cut_track.add_section()
    cut_section.set_range(0, END_FRAME)
    cut_section.set_camera_binding_id(sequence.get_binding_id(binding))
    return binding


def _add_time_of_day_track(sequence, sky_actor, sunrise_time):
    start_time = max(0.0, sunrise_time - 50.0)
    keys = (
        (0, start_time),
        (SUNRISE_FRAME, sunrise_time),
        (FIRST_PULL_FRAME, min(2400.0, sunrise_time + 35.0)),
        (SUN_FRONT_FRAME, min(2400.0, sunrise_time + 90.0)),
        (END_FRAME, min(2400.0, sunrise_time + 120.0)),
    )

    binding = sequence.add_possessable(sky_actor)
    binding.set_display_name("Ultra Dynamic Sky - Sunrise")
    track = binding.add_track(unreal.MovieSceneFloatTrack)
    track.set_property_name_and_path("Time of Day", "Time of Day")
    section = track.add_section()
    section.set_range(0, END_FRAME)
    channels = _section_channels(section)
    if not channels:
        raise SunriseSequenceError("Time of Day 轨道没有可写通道。")
    for frame, value in keys:
        _add_key(channels[0], frame, value, unreal.MovieSceneKeyInterpolation.LINEAR)
    return start_time, keys


def _add_directional_sun_track(sequence, sun_component):
    if sun_component is None:
        raise SunriseSequenceError(
            "关卡里既没有 Ultra Dynamic Sky，也没有 Directional Light。"
        )
    sun_actor = sun_component.get_owner()
    if sun_actor is None:
        raise SunriseSequenceError("太阳 Directional Light 没有所属 Actor。")

    location = sun_actor.get_actor_location()
    keys = (
        (0, location, _make_rotator(4.0, 180.0)),
        (SUNRISE_FRAME, location, _make_rotator(0.0, 180.0)),
        (FIRST_PULL_FRAME, location, _make_rotator(-5.0, 180.0)),
        (SUN_FRONT_FRAME, location, _make_rotator(-11.0, 180.0)),
        (END_FRAME, location, _make_rotator(-15.0, 180.0)),
    )
    binding = sequence.add_possessable(sun_actor)
    binding.set_display_name("Directional Sun - Sunrise")
    _add_transform_track(binding, keys)
    return sun_actor


def _configure_sequence(sequence):
    sequence.set_display_rate(unreal.FrameRate(numerator=FPS, denominator=1))
    sequence.set_playback_start(0)
    sequence.set_playback_end(END_FRAME)
    try:
        sequence.set_view_range_start(0.0)
        sequence.set_view_range_end(float(DURATION_SECONDS))
        sequence.set_work_range_start(0.0)
        sequence.set_work_range_end(float(DURATION_SECONDS))
    except Exception:
        pass


def _save(sequence, save_level):
    subsystem = unreal.get_editor_subsystem(unreal.EditorAssetSubsystem)
    if not subsystem.save_loaded_asset(sequence, False):
        raise SunriseSequenceError("保存序列失败：{}。".format(SEQUENCE_PATH))
    if save_level and not unreal.EditorLoadingAndSavingUtils.save_current_level():
        raise SunriseSequenceError("序列已保存，但 Ultra Dynamic Sky 所在关卡保存失败。")


def play_sequence(sequence):
    library = unreal.LevelSequenceEditorBlueprintLibrary
    library.open_level_sequence(sequence)
    library.set_current_time(0)
    library.play()


def create_sequence(play=True):
    all_actors = unreal.get_editor_subsystem(
        unreal.EditorActorSubsystem
    ).get_all_level_actors()
    model_actors = _collect_model_actors()
    minimum, maximum, highest_actor = _merge_model_bounds(model_actors)
    sky_actor = _find_sky_actor(all_actors)
    sun_component = _find_sun_component(all_actors, sky_actor)

    sunrise_time = None
    sampled_sunrise = False
    if sky_actor is not None and sun_component is not None:
        sunrise_time, sampled_sunrise = _detect_sunrise_time(sky_actor, sun_component)
    elif sky_actor is not None:
        sunrise_time = SUNRISE_FALLBACK_TIME
        unreal.log_warning(
            "[SunriseSequence] 找到 Ultra Dynamic Sky，但没有太阳组件，使用 06:00。"
        )

    focus_time = (sunrise_time or SUNRISE_FALLBACK_TIME) + 90.0
    focus_pitch = _sun_focus_pitch(sky_actor, sun_component, focus_time)
    camera_keys = _camera_plan(minimum, maximum, focus_pitch)

    sequence = _load_or_create_sequence()
    _reset_sequence(sequence)
    _configure_sequence(sequence)
    _add_camera(sequence, camera_keys)

    save_level = False
    time_keys = None
    sun_mode = "directional_light_rotation"
    if sky_actor is not None:
        start_time, time_keys = _add_time_of_day_track(
            sequence, sky_actor, sunrise_time
        )
        _set_sky_for_sequencer(sky_actor, start_time)
        save_level = True
        sun_mode = "uds_time_of_day"
    else:
        _add_directional_sun_track(sequence, sun_component)

    _save(sequence, save_level)
    if play:
        play_sequence(sequence)

    result = {
        "asset_path": SEQUENCE_PATH,
        "duration_seconds": DURATION_SECONDS,
        "fps": FPS,
        "model_folder": MODEL_FOLDER,
        "model_actor_count": len(model_actors),
        "highest_actor": highest_actor.get_actor_label() if highest_actor else None,
        "bounds_min": _vector(minimum),
        "bounds_max": _vector(maximum),
        "sun_mode": sun_mode,
        "sunrise_time_of_day": sunrise_time,
        "sunrise_sampled": sampled_sunrise,
        "time_keys": list(time_keys) if time_keys else None,
        "timeline_frames": {
            "sunrise": SUNRISE_FRAME,
            "first_pull_end": FIRST_PULL_FRAME,
            "sun_front": SUN_FRONT_FRAME,
            "second_pull_end": END_FRAME,
        },
        "played": bool(play),
    }
    unreal.log(RESULT_MARKER + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return sequence


if __name__ == "__main__":
    try:
        create_sequence(play=True)
    except Exception as error:
        unreal.log_error("{}ERROR={}".format(RESULT_MARKER, error))
        unreal.log_error(traceback.format_exc())
        raise
