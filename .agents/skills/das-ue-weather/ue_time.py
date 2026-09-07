#!/usr/bin/env python3
"""Read or set the Ultra Dynamic Sky time of day in a running Unreal Editor."""

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
    format_time_of_day,
    open_connection,
    parse_clock_text,
    parse_time_of_day,
    resolve_target,
)

RESULT_MARKER = "UE_TIME_RESULT="

# 回读项：时间本身，加上三个可能覆盖初始时刻的开关
TIME_READS = [
    {"op": "property", "name": "Time of Day", "as": "time_of_day"},
    {"op": "property", "name": "Animate Time of Day", "as": "animate_time_of_day"},
    {"op": "property", "name": "Randomize Time Of Day", "as": "randomize_time_of_day"},
    {"op": "property", "name": "Use System Time", "as": "use_system_time"},
    {"op": "call", "name": "Is it Daytime?", "as": "is_daytime"},
]

# 会让本次设置在运行时被覆盖的开关
OVERRIDE_SWITCHES = (
    ("animate_time_of_day", "Animate Time of Day"),
    ("randomize_time_of_day", "Randomize Time Of Day"),
    ("use_system_time", "Use System Time"),
)


# 把互斥的两种时间输入归一成 UDS 的 0-2400 刻度
def resolve_time_value(time_text, time_of_day) -> float:
    if time_text is not None and time_of_day is not None:
        raise UdsError("--time 与 --time-of-day 只能给一个")
    if time_text is not None:
        return parse_clock_text(time_text)
    if time_of_day is not None:
        return parse_time_of_day(time_of_day)
    raise UdsError("set 需要 --time 或 --time-of-day")


# 组装写入计划：优先调用 UDS 自己的函数，失败回落到属性写入
def build_time_plan(target: dict, value, save: bool) -> dict:
    steps = []
    if value is not None:
        steps.append(
            {
                "op": "call_or_property",
                "name": "SetTimeofDay",
                "args": [value],
                "property": "Time of Day",
                "value": value,
            }
        )
    plan = {
        "transaction": "设置 Time of Day",
        "folder": DEFAULT_FOLDER,
        "steps": steps,
        "reads": TIME_READS,
        "save": bool(save),
    }
    if target["mode"] == "existing":
        plan["actor_path"] = target["actor_path"]
    else:
        plan["blueprint_path"] = target["blueprint_path"]
    return plan


# 汇报回读到的时间与可能覆盖它的开关
def report(result: dict) -> None:
    emit("实例", result.get("actor_path") or "?")
    if result.get("created"):
        emit("新建", "已在当前关卡原点创建，并放入 {} 文件夹".format(DEFAULT_FOLDER))
    after = result.get("after") or {}
    value = after.get("time_of_day")
    if value is not None:
        emit("时间", "{}（Time of Day {}）".format(format_time_of_day(value), value))
    active = [label for key, label in OVERRIDE_SWITCHES if after.get(key)]
    if active:
        emit("提示", "{} 已开启，运行时可能覆盖本次设置".format("、".join(active)))
    if result.get("saved"):
        emit("已保存", "、".join(result["saved"]))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_arguments(parser)
    parser.add_argument("--sky-actor", help="指定 UDS 实例的对象路径或标签")
    parser.add_argument("--sky-blueprint", help="指定 UDS 蓝图的对象路径或资产名")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("get", help="读取当前时间")

    setter = subparsers.add_parser("set", help="设置初始时刻")
    setter.add_argument("--time", help="HH:MM 或 HH:MM:SS")
    setter.add_argument("--time-of-day", help="UDS 原始 0-2400 数值")
    setter.add_argument("--save", action="store_true", help="保存受影响的关卡或 Actor 包")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        is_set = args.command == "set"
        value = resolve_time_value(args.time, args.time_of_day) if is_set else None

        context, connection = open_connection(args)
        emit("项目", context["uproject"])
        with connection:
            discovery = discover(connection, "sky", need_blueprints=is_set, need_presets=False)
            target = resolve_target(
                discovery, "sky", args.sky_actor, args.sky_blueprint, create=is_set
            )
            plan = build_time_plan(target, value, getattr(args, "save", False))
            result = apply_plan(connection, plan)

        report(result)
        if getattr(args, "save", False) and not result.get("saved"):
            emit("提示", "没有需要保存的改动")
        result["time_text"] = format_time_of_day((result.get("after") or {}).get("time_of_day"))
        emit_result(RESULT_MARKER, result)
        return 0
    except (UdsError, OSError) as exc:
        print("[错误] {}".format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
