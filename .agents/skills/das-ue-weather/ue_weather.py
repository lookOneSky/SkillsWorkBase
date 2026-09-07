#!/usr/bin/env python3
"""Read or set the Ultra Dynamic Weather state in a running Unreal Editor."""

from __future__ import annotations

import argparse
import sys

from uds_common import (
    DEFAULT_FOLDER,
    UdsError,
    add_common_arguments,
    apply_plan,
    discover,
    emit,
    emit_result,
    open_connection,
    resolve_target,
    select_candidate,
)

RESULT_MARKER = "UE_WEATHER_RESULT="

# 手动天气值：命令行名、UDW 变量名、配套的逐值覆盖开关（没有开关的为 None）
MANUAL_VALUES = (
    ("cloud_coverage", "Cloud Coverage", "Cloud Coverage - Manual Override"),
    ("rain", "Rain", "Rain - Manual Override"),
    ("snow", "Snow", "Snow - Manual Override"),
    ("fog", "Fog", "Fog - Manual Override"),
    ("dust", "Dust", "Dust - Manual Override"),
    ("wind_strength", "Wind Intensity", "Wind Intensity - Manual Override"),
    ("lightning", "Lightning", None),
)

# 不属于手动天气状态、单独写入的值
INDEPENDENT_VALUES = (("wind_direction", "Base Wind Direction"),)


# 回读项：预设、每个手动值与其开关、风向
def build_reads() -> list:
    reads = [{"op": "property", "name": "Weather", "as": "weather"}]
    for key, prop, switch in MANUAL_VALUES:
        reads.append({"op": "property", "name": prop, "as": key})
        if switch:
            reads.append({"op": "property", "name": switch, "as": key + "_override"})
    for key, prop in INDEPENDENT_VALUES:
        reads.append({"op": "property", "name": prop, "as": key})
    return reads


# 收集本次命令给出的手动值，未给出的保持原状
def collect_manual(args) -> list:
    given = []
    for key, prop, switch in MANUAL_VALUES:
        value = getattr(args, key, None)
        if value is not None:
            given.append((key, prop, switch, float(value)))
    return given


# 组装天气写入计划；给了预设时先清覆盖、再写预设、最后应用本次手动值
def build_weather_plan(target: dict, preset_path, manual: list, independent: list, save: bool) -> dict:
    steps = []
    if preset_path is not None:
        for _key, _prop, switch in MANUAL_VALUES:
            if switch:
                # 覆盖开关按 UDS 版本可能缺失，缺了就跳过，不阻断写预设
                steps.append(
                    {"op": "property", "name": switch, "value": False, "optional": True}
                )
        steps.append({"op": "preset", "name": "Weather", "asset": preset_path})
    for _key, prop, switch, value in manual:
        steps.append({"op": "property", "name": prop, "value": value})
        if switch:
            steps.append({"op": "property", "name": switch, "value": True})
    for _key, prop, value in independent:
        steps.append({"op": "property", "name": prop, "value": value})

    plan = {
        "transaction": "设置天气状态",
        "folder": DEFAULT_FOLDER,
        "steps": steps,
        "reads": build_reads(),
        "save": bool(save),
    }
    if target["mode"] == "existing":
        plan["actor_path"] = target["actor_path"]
    else:
        plan["blueprint_path"] = target["blueprint_path"]
    return plan


# 汇报当前预设、生效的手动覆盖与风向
def report(result: dict) -> None:
    emit("实例", result.get("actor_path") or "?")
    if result.get("created"):
        emit("新建", "已在当前关卡原点创建，并放入 {} 文件夹".format(DEFAULT_FOLDER))
    after = result.get("after") or {}
    emit("天气", "预设 {}".format(after.get("weather") or "未选择（使用手动天气状态）"))
    active = [
        "{}={}".format(prop, after.get(key))
        for key, prop, switch in MANUAL_VALUES
        if after.get(key) is not None and (switch is None or after.get(key + "_override"))
    ]
    if active:
        emit("手动", "、".join(active))
    if after.get("wind_direction") is not None:
        emit("风向", after["wind_direction"])
    if result.get("saved"):
        emit("已保存", "、".join(result["saved"]))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    parser.add_argument("--weather-actor", help="指定 UDW 实例的对象路径或标签")
    parser.add_argument("--weather-blueprint", help="指定 UDW 蓝图的对象路径或资产名")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("get", help="读取当前天气状态")
    subparsers.add_parser("list-presets", help="列出可用的天气预设")

    setter = subparsers.add_parser("set", help="设置天气")
    setter.add_argument("--preset", help="天气预设资产名或对象路径")
    setter.add_argument("--cloud-coverage", type=float, help="云量")
    setter.add_argument("--rain", type=float, help="雨")
    setter.add_argument("--snow", type=float, help="雪")
    setter.add_argument("--fog", type=float, help="雾")
    setter.add_argument("--dust", type=float, help="沙尘")
    setter.add_argument("--wind-strength", type=float, help="风强度")
    setter.add_argument("--wind-direction", type=float, help="风向角度，独立于天气预设")
    setter.add_argument("--lightning", type=float, help="雷电，手动天气状态值")
    setter.add_argument("--save", action="store_true", help="保存受影响的关卡或 Actor 包")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        is_set = args.command == "set"
        manual = collect_manual(args) if is_set else []
        independent = []
        if is_set:
            for key, prop in INDEPENDENT_VALUES:
                value = getattr(args, key, None)
                if value is not None:
                    independent.append((key, prop, float(value)))
            if not manual and not independent and not args.preset:
                raise UdsError("set 需要 --preset 或至少一个手动参数")

        context, connection = open_connection(args)
        emit("项目", context["uproject"])
        with connection:
            need_presets = args.command == "list-presets" or (is_set and bool(args.preset))
            discovery = discover(
                connection, "weather", need_blueprints=is_set, need_presets=need_presets
            )

            if args.command == "list-presets":
                presets = discovery.get("presets") or []
                emit("预设", "共 {} 个".format(len(presets)))
                for item in presets:
                    print("  {}\t{}".format(item["name"], item["path"]))
                emit_result(RESULT_MARKER, {"ok": True, "presets": presets})
                return 0

            preset_path = None
            if is_set and args.preset:
                preset = select_candidate(
                    discovery.get("presets") or [], args.preset, "天气预设", "--preset"
                )
                preset_path = preset["path"]

            target = resolve_target(
                discovery, "weather", args.weather_actor, args.weather_blueprint, create=is_set
            )
            plan = build_weather_plan(
                target, preset_path, manual, independent, getattr(args, "save", False)
            )
            result = apply_plan(connection, plan)

        report(result)
        if getattr(args, "save", False) and not result.get("saved"):
            emit("提示", "没有需要保存的改动")
        emit_result(RESULT_MARKER, result)
        return 0
    except (UdsError, OSError) as exc:
        print("[错误] {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
