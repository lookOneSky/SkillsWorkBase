#!/usr/bin/env python3
"""Shared editor connection, asset discovery and plan execution for UDS and UDW."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path


class UdsError(RuntimeError):
    """可直接展示给用户的配置或执行错误。"""


LAUNCH_SKILL = "das-ue-launch"
AUTOCONFIG_SKILL = "das-ue-autoconfig"
REMOTE_MARKER = "UDS_REMOTE_RESULT="
DEFAULT_FOLDER = "DasWeather"
NODE_POLL_INTERVAL = 0.25

# 两类 Actor 的识别信息：锚点类名（不含 _C 后缀）与用于确认的必要属性
ACTOR_KINDS = {
    "sky": {
        "label": "Ultra Dynamic Sky",
        "class_names": ("ultra_dynamic_sky",),
        "required_properties": ("Time of Day",),
        "option": "--sky-actor",
        "blueprint_option": "--sky-blueprint",
    },
    "weather": {
        "label": "Ultra Dynamic Weather",
        "class_names": ("ultra_dynamic_weather",),
        "required_properties": ("Weather",),
        "option": "--weather-actor",
        "blueprint_option": "--weather-blueprint",
    },
}

# 天气预设的锚点类名；预设资产是它的子类，位置不固定
PRESET_CLASS_NAME = "uds_weather_settings"


# ---------------------------------------------------------------- 宿主端工具


# 去掉蓝图生成类的 _C 后缀并归一化，便于按类名比较
def simple_class_name(value: str) -> str:
    text = str(value or "").strip()
    if "'" in text:
        text = text.split("'")[1] if text.count("'") >= 2 else text
    text = text.rsplit("/", 1)[-1]
    text = text.rsplit(".", 1)[-1]
    if text.casefold().endswith("_c"):
        text = text[:-2]
    return text.casefold()


# 解析 --launch-result：接受文件路径、行内 JSON，或带 UE_LAUNCH_RESULT= 前缀的行
def load_launch_result(value: str | None) -> dict:
    if not value:
        return {}
    text = str(value).strip()
    marker = "UE_LAUNCH_RESULT="
    if marker in text:
        text = text.split(marker, 1)[1].strip()
    if not text.startswith("{"):
        path = Path(text).expanduser()
        try:
            text = path.read_text(encoding="utf-8-sig").strip()
        except OSError as exc:
            raise UdsError("无法读取实例 JSON：{}".format(exc)) from exc
        if marker in text:
            text = text.split(marker, 1)[1].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UdsError("实例 JSON 解析失败：{}".format(exc)) from exc
    if not isinstance(data, dict):
        raise UdsError("实例 JSON 必须是对象")
    return data


# 借用同级 das-ue-launch 的工程与引擎定位实现，避免重复
def load_launch_support() -> dict:
    support_dir = Path(__file__).resolve().parent.parent / LAUNCH_SKILL
    if not (support_dir / "launch_ue_editor.py").is_file():
        raise UdsError("缺少同级 Skill {}，请先安装完整 Skill 集".format(LAUNCH_SKILL))
    sys.path.insert(0, str(support_dir))
    try:
        from launch_ue_editor import (  # pylint: disable=import-outside-toplevel
            find_uproject,
            load_json,
            python_remote_execution,
            read_ini,
            resolve_engine_root,
            running_editor_processes,
        )
    except (ImportError, OSError) as exc:
        raise UdsError("无法加载 {}：{}".format(LAUNCH_SKILL, exc)) from exc
    return {
        "find_uproject": find_uproject,
        "load_json": load_json,
        "python_remote_execution": python_remote_execution,
        "read_ini": read_ini,
        "resolve_engine_root": resolve_engine_root,
        "running_editor_processes": running_editor_processes,
    }


# das-ue-launch 的函数抛 LaunchError，转成本 Skill 的错误类型统一处理
def call_support(function, *args):
    try:
        return function(*args)
    except RuntimeError as exc:
        raise UdsError(str(exc)) from exc


# 汇总连接所需的上下文：优先用启动器 JSON，缺失字段再自行推导
def resolve_context(launch_result: dict, project: str | None, engine_root: str | None = None) -> dict:
    launch_result = launch_result or {}
    uproject_text = launch_result.get("project") or project
    remote = launch_result.get("python_remote_execution")
    resolved_engine = engine_root or launch_result.get("engine_root") or ""
    process_ids = [str(item) for item in launch_result.get("process_ids") or []]

    support = load_launch_support()
    if not uproject_text:
        uproject = call_support(support["find_uproject"], ".")
    else:
        uproject = Path(uproject_text).expanduser()
        if uproject.is_dir() or uproject.suffix.casefold() != ".uproject":
            uproject = call_support(support["find_uproject"], str(uproject))

    project_data = support["load_json"](uproject)
    if not remote:
        config = support["read_ini"](uproject.parent / "Config/DefaultEngine.ini")
        remote = support["python_remote_execution"](config, project_data)
    if not process_ids:
        process_ids = [item for item, _ in call_support(
            support["running_editor_processes"], uproject
        )]

    return {
        "uproject": uproject,
        "engine_root": Path(resolved_engine) if resolved_engine else None,
        "engine_override": engine_root,
        "project_data": project_data,
        "support": support,
        "remote": dict(remote or {}),
        "process_ids": process_ids,
    }


# 引擎定位放在编辑器检查之后：没开编辑器时先报更可行动的那个错误
def ensure_engine_root(context: dict) -> Path:
    if context.get("engine_root"):
        return context["engine_root"]
    support = context.get("support") or load_launch_support()
    try:
        resolved = support["resolve_engine_root"](
            context["uproject"], context.get("project_data") or {}, context.get("engine_override")
        )
    except RuntimeError as exc:
        raise UdsError("{}；也可以给本脚本加 --engine-root".format(exc)) from exc
    context["engine_root"] = Path(resolved)
    return context["engine_root"]


# 连接前的前置检查：编辑器在跑、远程执行已开
def check_ready(context: dict) -> None:
    if not context["process_ids"]:
        raise UdsError(
            "未发现运行中的编辑器；请先运行 {} 的 launch_ue_editor.py".format(LAUNCH_SKILL)
        )
    remote = context["remote"]
    if not remote.get("plugin_enabled", True) or not remote.get("enabled", False):
        raise UdsError(
            "Python 远程执行未开启；请先运行 {} 的 configure_ue_python.py 并重启编辑器".format(
                AUTOCONFIG_SKILL
            )
        )


# 不同 UE 版本 PythonScriptPlugin 位置不同，逐个位置查 remote_execution.py
def resolve_remote_module(engine_root: Path) -> Path:
    preferred = (
        engine_root / "Engine/Plugins/Experimental/PythonScriptPlugin/Content/Python",
        engine_root / "Engine/Plugins/PythonScriptPlugin/Content/Python",
    )
    for candidate in preferred:
        if (candidate / "remote_execution.py").is_file():
            return candidate
    for candidate in sorted(
        engine_root.glob("Engine/Plugins/**/PythonScriptPlugin/Content/Python/remote_execution.py")
    ):
        return candidate.parent
    raise UdsError("找不到 remote_execution.py：{}".format(engine_root))


# 把 "239.0.0.1:6766" 拆成 remote_execution 需要的二元组
def split_endpoint(value: str, fallback: tuple[str, int]) -> tuple[str, int]:
    text = str(value or "").strip()
    if ":" not in text:
        return fallback
    host, _, port = text.rpartition(":")
    try:
        return host.strip(), int(port)
    except ValueError:
        return fallback


# 规范化路径用于比较，Windows 下大小写与分隔符都不敏感
def normalized_path(value) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(value))))


# 在已发现的远程节点里挑出当前工程的那一个
def select_project_node(nodes, project_dir, project_name):
    expected = normalized_path(project_dir)
    exact = [
        node
        for node in nodes
        if node.get("project_root") and normalized_path(node["project_root"]) == expected
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise UdsError("同一工程发现多个 Python 远程节点，请只保留一个编辑器实例")
    by_name = [node for node in nodes if node.get("project_name") == project_name]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        raise UdsError("同名工程发现多个 Python 远程节点，请只保留一个编辑器实例")
    available = ", ".join(
        "{} ({})".format(node.get("project_name", "?"), node.get("project_root", "?"))
        for node in nodes
    )
    raise UdsError("未发现当前工程的 Python 远程节点；已发现：{}".format(available or "无"))


class EditorConnection:
    """连接运行中的编辑器并执行注入代码。"""

    def __init__(self, context: dict, timeout: float = 15.0):
        self.context = context
        self.timeout = timeout
        self._module = None
        self._connection = None

    # 建立组播发现连接并绑定到当前工程的节点
    def __enter__(self) -> "EditorConnection":
        module_dir = resolve_remote_module(ensure_engine_root(self.context))
        sys.path.insert(0, str(module_dir))
        try:
            import remote_execution  # pylint: disable=import-outside-toplevel
        except ImportError as exc:
            raise UdsError("无法导入 remote_execution：{}".format(exc)) from exc
        self._module = remote_execution

        remote = self.context["remote"]
        config = remote_execution.RemoteExecutionConfig()
        config.multicast_group_endpoint = split_endpoint(
            remote.get("multicast_group_endpoint"), ("239.0.0.1", 6766)
        )
        config.multicast_bind_address = (
            remote.get("multicast_bind_address") or "127.0.0.1"
        )
        connection = remote_execution.RemoteExecution(config)
        connection.start()
        self._connection = connection

        uproject = self.context["uproject"]
        deadline = time.time() + self.timeout
        last_error = None
        while time.time() < deadline:
            try:
                node = select_project_node(
                    connection.remote_nodes, uproject.parent, uproject.stem
                )
                connection.open_command_connection(node["node_id"])
                return self
            except UdsError as exc:
                last_error = exc
                time.sleep(NODE_POLL_INTERVAL)
        self.close()
        raise last_error or UdsError("未发现 Unreal Python 远程节点")

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self.close()
        return False

    # 关闭连接，忽略清理阶段的次生错误
    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.stop()
            except Exception:  # pylint: disable=broad-except
                pass
            self._connection = None

    # 在编辑器里执行一段代码并取回结构化结果
    # 命令会原样回显在响应里，而 remote_execution 单次只 recv 8192 字节，
    # 所以正文写进临时文件，只发一行引导代码，避免响应被截断
    def run(self, code: str) -> dict:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="uds_", encoding="utf-8", delete=False
        ) as payload_file:
            payload_file.write(code)
            payload_path = Path(payload_file.name)
        bootstrap = (
            "exec(compile(open(r'{}', encoding='utf-8').read(), 'uds_remote', 'exec'))"
        ).format(payload_path)
        try:
            result = self._connection.run_command(
                bootstrap,
                unattended=True,
                exec_mode=self._module.MODE_EXEC_FILE,
                raise_on_failure=False,
            )
        finally:
            try:
                payload_path.unlink()
            except OSError:
                pass
        payload = None
        errors = []
        for entry in result.get("output") or []:
            text = entry.get("output", "")
            if entry.get("type") == "Error":
                errors.append(text)
            for line in text.splitlines():
                if line.startswith(REMOTE_MARKER):
                    payload = line[len(REMOTE_MARKER):]
        if payload is not None:
            data = json.loads(payload)
            if not data.get("ok", False):
                raise UdsError(data.get("error") or "编辑器执行失败")
            return data
        detail = "\n".join(errors).strip() or str(result.get("result") or "").strip()
        raise UdsError("编辑器执行失败：{}".format(detail or "无输出"))


# 把参数打包进注入代码，模板里的字面花括号需要写成双花括号
def build_code(template: str, payload: dict) -> str:
    return template.format(payload=repr(json.dumps(payload, ensure_ascii=True)))


# ---------------------------------------------------------------- 候选消歧


# 判断用户给的标识是否指向该候选：接受对象路径、资产名或 Actor 标签
def candidate_matches(candidate: dict, wanted: str) -> bool:
    needle = str(wanted).strip().casefold()
    if not needle:
        return False
    for key in ("path", "label", "name", "class_name"):
        value = str(candidate.get(key, "")).strip().casefold()
        if value and value == needle:
            return True
    path = str(candidate.get("path", "")).strip().casefold()
    return bool(path) and path.rsplit("/", 1)[-1].split(".")[0] == needle


# 描述候选列表，报错时让用户能直接复制对象路径
def describe_candidates(candidates: list) -> str:
    return "、".join(
        "{}（{}）".format(item.get("path", "?"), item.get("label") or item.get("name") or "")
        for item in candidates
    )


# 从候选里挑唯一目标；多个且未指定时报错并列出对象路径
def select_candidate(candidates: list, wanted: str | None, noun: str, option: str) -> dict:
    items = list(candidates or [])
    if wanted:
        matched = [item for item in items if candidate_matches(item, wanted)]
        if len(matched) == 1:
            return matched[0]
        if not matched:
            raise UdsError(
                "未找到指定的{}：{}；可选：{}".format(noun, wanted, describe_candidates(items) or "无")
            )
        raise UdsError(
            "指定的{}不唯一：{}；可选：{}".format(noun, wanted, describe_candidates(matched))
        )
    if len(items) == 1:
        return items[0]
    if not items:
        raise UdsError("未找到{}".format(noun))
    raise UdsError(
        "{}不唯一，请用 {} 指定：{}".format(noun, option, describe_candidates(items))
    )


# 选定要操作的 Actor：已有实例优先，缺失时回落到蓝图资产供新建
def resolve_target(discovery: dict, kind: str, actor_wanted, blueprint_wanted, create: bool) -> dict:
    info = ACTOR_KINDS[kind]
    actors = discovery.get("actors") or []
    if actors or actor_wanted:
        actor = select_candidate(actors, actor_wanted, "{} 实例".format(info["label"]), info["option"])
        return {"mode": "existing", "actor_path": actor["path"], "actor": actor}
    if not create:
        raise UdsError(
            "当前关卡没有 {} 实例；读取命令不会新建，请先在关卡中放置".format(info["label"])
        )
    blueprints = discovery.get("blueprints") or []
    blueprint = select_candidate(
        blueprints, blueprint_wanted, "{} 蓝图".format(info["label"]), info["blueprint_option"]
    )
    return {"mode": "create", "blueprint_path": blueprint["path"], "blueprint": blueprint}


# ---------------------------------------------------------------- 时间换算


TIME_PATTERN = re.compile(r"^(\d{1,2}):(\d{1,2})(?::(\d{1,2}(?:\.\d+)?))?$")


# HH:MM[:SS] 按小时比例换算到 UDS 的 0-2400 线性刻度，09:30 -> 950
def parse_clock_text(value: str) -> float:
    text = str(value).strip()
    match = TIME_PATTERN.match(text)
    if not match:
        raise UdsError("时间格式应为 HH:MM 或 HH:MM:SS：{}".format(value))
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = float(match.group(3) or 0.0)
    if hour > 24 or minute >= 60 or second >= 60:
        raise UdsError("时间超出范围：{}".format(value))
    total = (hour + minute / 60.0 + second / 3600.0) * 100.0
    if total > 2400.0:
        raise UdsError("时间超出范围：{}".format(value))
    return round(total, 6)


# 校验直接给出的 UDS 原始刻度
def parse_time_of_day(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise UdsError("Time of Day 必须是数值：{}".format(value)) from exc
    if not 0.0 <= number <= 2400.0:
        raise UdsError("Time of Day 超出 0-2400：{}".format(value))
    return round(number, 6)


# 把 0-2400 刻度还原成便于阅读的时钟字符串
def format_time_of_day(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "?"
    total_seconds = int(round(number / 100.0 * 3600.0))
    total_seconds %= 24 * 3600
    return "{:02d}:{:02d}:{:02d}".format(
        total_seconds // 3600, (total_seconds % 3600) // 60, total_seconds % 60
    )


# ---------------------------------------------------------------- 输出


# 统一的 [标签] 输出格式
def emit(label: str, message) -> None:
    print("[{}] {}".format(label, message))


# 末行输出单行 JSON，供调用方解析
def emit_result(marker: str, result: dict) -> None:
    print("{}{}".format(marker, json.dumps(result, ensure_ascii=False)))


# ---------------------------------------------------------------- 注入代码


DISCOVER_TEMPLATE = '''
import json
import unreal

_config = json.loads({payload})


def _simple(value):
    text = str(value or "").strip()
    if text.count("'") >= 2:
        text = text.split("'")[1]
    text = text.rsplit("/", 1)[-1]
    text = text.rsplit(".", 1)[-1]
    if text.casefold().endswith("_c"):
        text = text[:-2]
    return text.casefold()


def _class_names(actor):
    names = []
    try:
        for klass in type(actor).__mro__:
            names.append(_simple(klass.__name__))
    except Exception:
        pass
    try:
        names.append(_simple(actor.get_class().get_name()))
    except Exception:
        pass
    return names


def _has_properties(obj, names):
    for name in names:
        try:
            obj.get_editor_property(name)
        except Exception:
            return False
    return True


def _actor_path(actor):
    try:
        return actor.get_path_name()
    except Exception:
        return ""


def _tag_value(asset, name):
    try:
        value = asset.get_tag_value(name)
    except Exception:
        value = None
    if value is None:
        try:
            value = asset.get_editor_property("tag_values").get(name)
        except Exception:
            value = None
    return "" if value is None else str(value)


def _blueprint_assets():
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    try:
        path = unreal.TopLevelAssetPath("/Script/Engine", "Blueprint")
        return list(registry.get_assets_by_class(path, True))
    except Exception:
        return list(registry.get_assets_by_class("Blueprint", True))


def _asset_entry(asset):
    package = str(asset.package_name)
    name = str(asset.asset_name)
    return {{
        "name": name,
        "path": "{{}}.{{}}".format(package, name),
        "package": package,
        "parent": _simple(_tag_value(asset, "ParentClass")),
        "class_name": _simple(_tag_value(asset, "GeneratedClass")) or name.casefold(),
    }}


def _preset_assets(entries, anchor):
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    found = []
    seen = set()
    for entry in entries:
        if _simple(entry["name"]) not in anchor:
            continue
        package = entry["package"]
        class_name = package.rsplit("/", 1)[-1] + "_C"
        try:
            assets = registry.get_assets_by_class(
                unreal.TopLevelAssetPath(package, class_name), True
            )
        except Exception:
            continue
        for asset in assets:
            item = _asset_entry(asset)
            if item["path"] not in seen:
                seen.add(item["path"])
                found.append(item)
    return found


def _collect_actors(needles, required):
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    found = []
    for actor in subsystem.get_all_level_actors():
        names = _class_names(actor)
        if not any(needle in names for needle in needles):
            continue
        if not _has_properties(actor, required):
            continue
        try:
            folder = str(actor.get_folder_path())
        except Exception:
            folder = ""
        found.append({{
            "path": _actor_path(actor),
            "label": actor.get_actor_label(),
            "class_name": _simple(actor.get_class().get_name()),
            "folder": folder,
        }})
    return found


def _descendants(entries, anchors):
    by_class = {{}}
    for entry in entries:
        by_class.setdefault(entry["class_name"], entry)
        by_class.setdefault(_simple(entry["name"]), entry)
    matched = []
    for entry in entries:
        current = entry
        seen = set()
        while current is not None:
            key = current["class_name"]
            if key in seen:
                break
            seen.add(key)
            if _simple(current["name"]) in anchors or key in anchors:
                matched.append(entry)
                break
            parent = current.get("parent") or ""
            if parent in anchors:
                matched.append(entry)
                break
            current = by_class.get(parent)
    return matched


_result = {{"ok": True}}
try:
    _needles = [_simple(item) for item in _config["class_names"]]
    _required = list(_config["required_properties"])
    _result["actors"] = _collect_actors(_needles, _required)
    _entries = []
    if _config.get("need_blueprints") or _config.get("preset_anchor"):
        _entries = [_asset_entry(asset) for asset in _blueprint_assets()]
    if _config.get("need_blueprints"):
        _result["blueprints"] = _descendants(_entries, set(_needles))
    if _config.get("preset_anchor"):
        _anchor = {{_simple(_config["preset_anchor"])}}
        # 预设通常是设置类的实例资产，按生成类枚举；老版本把预设做成蓝图类时回落到继承链
        _presets = _preset_assets(_entries, _anchor)
        if not _presets:
            _presets = [
                item for item in _descendants(_entries, _anchor)
                if _simple(item["name"]) not in _anchor
            ]
        _result["presets"] = _presets
except Exception as _error:
    _result = {{"ok": False, "error": "{{}}: {{}}".format(type(_error).__name__, _error)}}

print("UDS_REMOTE_RESULT=" + json.dumps(_result, ensure_ascii=False))
'''


APPLY_TEMPLATE = '''
import json
import unreal

_config = json.loads({payload})


def _find_actor(path):
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for actor in subsystem.get_all_level_actors():
        try:
            if actor.get_path_name() == path:
                return actor
        except Exception:
            continue
    raise RuntimeError("Actor 已不在关卡中：" + path)


def _asset_path(path):
    head, separator, tail = str(path).rpartition(".")
    if separator and "/" not in tail:
        return head
    return str(path)


def _spawn_actor(blueprint_path, folder):
    loaded = unreal.EditorAssetLibrary.load_blueprint_class(_asset_path(blueprint_path))
    if loaded is None:
        raise RuntimeError("无法加载蓝图类：" + blueprint_path)
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = subsystem.spawn_actor_from_class(
        loaded, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0)
    )
    if actor is None:
        raise RuntimeError("无法创建 Actor：" + blueprint_path)
    if folder:
        try:
            actor.set_folder_path(folder)
        except Exception:
            pass
    return actor


def _readable(value):
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, str):
        return value
    try:
        return str(value.get_path_name())
    except Exception:
        pass
    try:
        return str(value.get_name())
    except Exception:
        return str(value)


def _check_property(actor, name):
    try:
        return True, actor.get_editor_property(name)
    except Exception as error:
        return False, str(error)


def _read(actor, reads):
    values = {{}}
    for item in reads:
        name = item["name"]
        if item["op"] == "property":
            ok, value = _check_property(actor, name)
            values[item.get("as") or name] = _readable(value) if ok else None
        else:
            try:
                values[item.get("as") or name] = _readable(actor.call_method(name))
            except Exception:
                values[item.get("as") or name] = None
    return values


def _preset_value(asset_path):
    if not asset_path:
        return None
    # 预设是设置类的实例资产，直接加载对象；蓝图类形式的预设走 load_blueprint_class
    loaded = unreal.load_asset(_asset_path(asset_path))
    if loaded is None:
        loaded = unreal.EditorAssetLibrary.load_blueprint_class(_asset_path(asset_path))
    if loaded is None:
        raise RuntimeError("无法加载天气预设：" + str(asset_path))
    return loaded


def _apply_step(actor, step):
    kind = step["op"]
    if kind == "property":
        actor.set_editor_property(step["name"], step["value"])
        return "property:" + step["name"]
    if kind == "preset":
        value = _preset_value(step.get("asset"))
        try:
            actor.set_editor_property(step["name"], value)
        except Exception:
            if value is None:
                raise
            actor.set_editor_property(step["name"], unreal.get_default_object(value))
        return "preset:" + step["name"]
    if kind == "call":
        actor.call_method(step["name"], tuple(step.get("args") or []))
        return "call:" + step["name"]
    if kind == "call_or_property":
        try:
            actor.call_method(step["name"], tuple(step.get("args") or []))
            return "call:" + step["name"]
        except Exception:
            actor.set_editor_property(step["property"], step["value"])
            return "property:" + step["property"]
    raise RuntimeError("未知操作：" + str(kind))


def _save(actor):
    saved = []
    try:
        package = actor.get_package()
    except Exception:
        package = None
    failures = []
    try:
        if unreal.EditorLoadingAndSavingUtils.save_current_level():
            saved.append("level")
    except Exception as error:
        failures.append(str(error))
    if package is not None:
        try:
            if unreal.EditorLoadingAndSavingUtils.save_packages([package], False):
                saved.append(str(package.get_name()))
        except Exception as error:
            failures.append(str(error))
    if not saved and failures:
        raise RuntimeError("保存失败：" + "；".join(failures))
    return saved


_result = {{"ok": True, "created": False, "applied": [], "skipped": [], "saved": []}}
try:
    if _config.get("actor_path"):
        _actor = _find_actor(_config["actor_path"])
    else:
        _actor = _spawn_actor(_config["blueprint_path"], _config.get("folder") or "")
        _result["created"] = True

    _result["actor_path"] = _actor.get_path_name()
    _result["actor_label"] = _actor.get_actor_label()

    _steps = []
    _missing = []
    for _step in _config.get("steps") or []:
        _name = _step.get("property") if _step["op"] == "call_or_property" else _step.get("name")
        if _step["op"] in ("property", "preset") or _step["op"] == "call_or_property":
            _ok, _detail = _check_property(_actor, _name)
            if not _ok:
                # 可选步骤对应不同 UDS 版本可能没有的属性，跳过而不是整体失败
                if _step.get("optional"):
                    _result["skipped"].append(_name)
                    continue
                _missing.append("{{}}（{{}}）".format(_name, _detail))
        _steps.append(_step)
    if _missing:
        raise RuntimeError("以下属性不存在或不可写：" + "、".join(_missing))

    _result["before"] = _read(_actor, _config.get("reads") or [])
    if _steps:
        with unreal.ScopedEditorTransaction(_config.get("transaction") or "Das Weather"):
            for _step in _steps:
                _result["applied"].append(_apply_step(_actor, _step))
    _result["after"] = _read(_actor, _config.get("reads") or [])

    if _config.get("save"):
        _result["saved"] = _save(_actor)
except Exception as _error:
    _result = {{"ok": False, "error": "{{}}: {{}}".format(type(_error).__name__, _error)}}

print("UDS_REMOTE_RESULT=" + json.dumps(_result, ensure_ascii=False))
'''


# 在编辑器里查找实例、蓝图与预设候选
def discover(connection: EditorConnection, kind: str, need_blueprints: bool, need_presets: bool) -> dict:
    info = ACTOR_KINDS[kind]
    payload = {
        "class_names": list(info["class_names"]),
        "required_properties": list(info["required_properties"]),
        "need_blueprints": bool(need_blueprints),
        "preset_anchor": PRESET_CLASS_NAME if need_presets else "",
    }
    return connection.run(build_code(DISCOVER_TEMPLATE, payload))


# 执行一份操作计划：定位或新建 Actor、按序写入、回读、可选保存
def apply_plan(connection: EditorConnection, plan: dict) -> dict:
    return connection.run(build_code(APPLY_TEMPLATE, plan))


# 两个命令脚本共用的参数
def add_common_arguments(parser) -> None:
    parser.add_argument("--launch-result", help="das-ue-launch 输出的实例 JSON 路径或内容")
    parser.add_argument("--project", help="项目目录或 .uproject，缺少实例 JSON 时使用")
    parser.add_argument("--engine-root", help="引擎根目录，EngineAssociation 定位失败时使用")
    parser.add_argument("--timeout", type=float, default=15.0, help="远程节点发现超时秒数")


# 组装上下文并完成前置检查，返回可直接进入 with 的连接
def open_connection(args) -> tuple[dict, EditorConnection]:
    context = resolve_context(
        load_launch_result(args.launch_result), args.project, args.engine_root
    )
    check_ready(context)
    return context, EditorConnection(context, timeout=args.timeout)
