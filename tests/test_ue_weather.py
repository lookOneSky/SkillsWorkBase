"""das-ue-weather 宿主端逻辑测试：换算、消歧、计划编排与错误传播。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / ".agents" / "skills" / "das-ue-weather"
sys.path.insert(0, str(SKILL_DIR))

import uds_common  # noqa: E402  pylint: disable=wrong-import-position
import ue_time  # noqa: E402  pylint: disable=wrong-import-position
import ue_weather  # noqa: E402  pylint: disable=wrong-import-position

UdsError = uds_common.UdsError


class TimeConversionTests(unittest.TestCase):
    def test_clock_uses_linear_0_2400_scale(self) -> None:
        self.assertEqual(uds_common.parse_clock_text("09:30"), 950.0)
        self.assertEqual(uds_common.parse_clock_text("15:45"), 1575.0)
        self.assertEqual(uds_common.parse_clock_text("00:00"), 0.0)
        self.assertEqual(uds_common.parse_clock_text("24:00"), 2400.0)

    def test_clock_accepts_seconds(self) -> None:
        self.assertAlmostEqual(uds_common.parse_clock_text("09:30:36"), 951.0, places=4)

    def test_clock_rejects_bad_format_and_range(self) -> None:
        for value in ("9", "9.5", "09-30", "3PM", "", "09:60", "24:30", "25:00"):
            with self.subTest(value=value), self.assertRaises(UdsError):
                uds_common.parse_clock_text(value)

    def test_raw_scale_is_range_checked(self) -> None:
        self.assertEqual(uds_common.parse_time_of_day("950"), 950.0)
        for value in ("-1", "2400.5", "abc"):
            with self.subTest(value=value), self.assertRaises(UdsError):
                uds_common.parse_time_of_day(value)

    def test_format_round_trips(self) -> None:
        self.assertEqual(uds_common.format_time_of_day(950), "09:30:00")
        self.assertEqual(uds_common.format_time_of_day(1575), "15:45:00")

    def test_time_inputs_are_mutually_exclusive(self) -> None:
        with self.assertRaises(UdsError):
            ue_time.resolve_time_value("09:30", "950")
        with self.assertRaises(UdsError):
            ue_time.resolve_time_value(None, None)
        self.assertEqual(ue_time.resolve_time_value("09:30", None), 950.0)
        self.assertEqual(ue_time.resolve_time_value(None, "950"), 950.0)


class LaunchResultTests(unittest.TestCase):
    def test_inline_json_and_marker_prefix(self) -> None:
        payload = {"project": "D:/P/P.uproject"}
        self.assertEqual(uds_common.load_launch_result(json.dumps(payload)), payload)
        line = "UE_LAUNCH_RESULT=" + json.dumps(payload)
        self.assertEqual(uds_common.load_launch_result(line), payload)

    def test_file_path_with_marker_line(self) -> None:
        payload = {"project": "D:/P/P.uproject"}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "launch.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(uds_common.load_launch_result(str(path)), payload)

    def test_missing_file_and_bad_json_report_errors(self) -> None:
        with self.assertRaises(UdsError):
            uds_common.load_launch_result("D:/definitely/missing/launch.json")
        with self.assertRaises(UdsError):
            uds_common.load_launch_result("{not json")


class CandidateSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        # 资产可以改目录或位于插件中，选择只看名称与对象路径
        self.presets = [
            {"name": "Rain", "path": "/Game/Custom/Weather/Rain.Rain"},
            {"name": "Snow", "path": "/MyPlugin/Weather/Snow.Snow"},
        ]

    def test_single_candidate_needs_no_hint(self) -> None:
        picked = uds_common.select_candidate(self.presets[:1], None, "天气预设", "--preset")
        self.assertEqual(picked["name"], "Rain")

    def test_multiple_candidates_list_object_paths(self) -> None:
        with self.assertRaises(UdsError) as caught:
            uds_common.select_candidate(self.presets, None, "天气预设", "--preset")
        message = str(caught.exception)
        self.assertIn("--preset", message)
        self.assertIn("/MyPlugin/Weather/Snow.Snow", message)

    def test_explicit_name_and_object_path_both_match(self) -> None:
        by_name = uds_common.select_candidate(self.presets, "Snow", "天气预设", "--preset")
        by_path = uds_common.select_candidate(
            self.presets, "/MyPlugin/Weather/Snow.Snow", "天气预设", "--preset"
        )
        self.assertEqual(by_name["path"], by_path["path"])

    def test_unknown_name_reports_available(self) -> None:
        with self.assertRaises(UdsError) as caught:
            uds_common.select_candidate(self.presets, "Hail", "天气预设", "--preset")
        self.assertIn("Hail", str(caught.exception))

    def test_actor_label_matches(self) -> None:
        actors = [{"path": "/Game/Map.Map:PersistentLevel.UDS_1", "label": "Sky"}]
        picked = uds_common.select_candidate(actors, "Sky", "UDS 实例", "--sky-actor")
        self.assertEqual(picked["label"], "Sky")


class TargetResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.actor = {"path": "/Game/Map.Map:PersistentLevel.UDS_1", "label": "Sky"}
        self.blueprint = {
            "name": "Ultra_Dynamic_Sky",
            "path": "/Game/UltraDynamicSky/Blueprints/Ultra_Dynamic_Sky.Ultra_Dynamic_Sky",
        }

    def test_existing_instance_is_reused(self) -> None:
        discovery = {"actors": [self.actor], "blueprints": [self.blueprint]}
        target = uds_common.resolve_target(discovery, "sky", None, None, create=True)
        self.assertEqual(target["mode"], "existing")
        self.assertEqual(target["actor_path"], self.actor["path"])

    def test_missing_instance_is_created_from_blueprint(self) -> None:
        discovery = {"actors": [], "blueprints": [self.blueprint]}
        target = uds_common.resolve_target(discovery, "sky", None, None, create=True)
        self.assertEqual(target["mode"], "create")
        self.assertEqual(target["blueprint_path"], self.blueprint["path"])

    def test_read_only_never_creates(self) -> None:
        with self.assertRaises(UdsError) as caught:
            uds_common.resolve_target({"actors": []}, "sky", None, None, create=False)
        self.assertIn("读取命令不会新建", str(caught.exception))

    def test_ambiguous_actors_require_option(self) -> None:
        discovery = {
            "actors": [self.actor, {"path": "/Game/Map.Map:PersistentLevel.UDS_2", "label": "Sky2"}]
        }
        with self.assertRaises(UdsError) as caught:
            uds_common.resolve_target(discovery, "sky", None, None, create=True)
        self.assertIn("--sky-actor", str(caught.exception))

    def test_missing_blueprint_reports_before_any_write(self) -> None:
        with self.assertRaises(UdsError):
            uds_common.resolve_target(
                {"actors": [], "blueprints": []}, "weather", None, None, create=True
            )


class PlanBuildingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.existing = {"mode": "existing", "actor_path": "/Game/Map.Map:PersistentLevel.A_1"}
        self.creating = {"mode": "create", "blueprint_path": "/Game/BP/UDW.UDW"}

    def test_time_plan_prefers_function_then_property(self) -> None:
        plan = ue_time.build_time_plan(self.existing, 950.0, save=False)
        self.assertEqual(plan["actor_path"], self.existing["actor_path"])
        step = plan["steps"][0]
        self.assertEqual(step["op"], "call_or_property")
        self.assertEqual(step["name"], "SetTimeofDay")
        self.assertEqual(step["property"], "Time of Day")
        self.assertEqual(step["args"], [950.0])
        self.assertFalse(plan["save"])

    def test_time_plan_for_new_actor_carries_blueprint_and_folder(self) -> None:
        plan = ue_time.build_time_plan(self.creating, 950.0, save=True)
        self.assertEqual(plan["blueprint_path"], self.creating["blueprint_path"])
        self.assertEqual(plan["folder"], uds_common.DEFAULT_FOLDER)
        self.assertTrue(plan["save"])
        self.assertNotIn("actor_path", plan)

    def test_manual_only_keeps_preset_untouched(self) -> None:
        manual = [("rain", "Rain", "Rain - Manual Override", 5.0)]
        plan = ue_weather.build_weather_plan(self.existing, None, manual, [], save=False)
        names = [step["name"] for step in plan["steps"]]
        self.assertNotIn("Weather", names)
        self.assertEqual(names, ["Rain", "Rain - Manual Override"])
        self.assertTrue(plan["steps"][1]["value"])

    def test_preset_clears_overrides_then_applies_same_command_manual(self) -> None:
        manual = [("fog", "Fog", "Fog - Manual Override", 2.0)]
        plan = ue_weather.build_weather_plan(
            self.existing, "/Game/W/Rain.Rain", manual, [], save=False
        )
        ops = [(step["op"], step["name"], step.get("value")) for step in plan["steps"]]
        preset_index = [index for index, item in enumerate(ops) if item[0] == "preset"][0]
        cleared = [item for item in ops[:preset_index] if item[0] == "property"]
        self.assertTrue(cleared)
        self.assertTrue(all(item[2] is False for item in cleared))
        self.assertIn(("property", "Fog", 2.0), ops[preset_index:])
        self.assertIn(("property", "Fog - Manual Override", True), ops[preset_index:])

    def test_wind_direction_is_written_independently(self) -> None:
        plan = ue_weather.build_weather_plan(
            self.existing, None, [], [("wind_direction", "Base Wind Direction", 90.0)], save=False
        )
        self.assertEqual(
            plan["steps"], [{"op": "property", "name": "Base Wind Direction", "value": 90.0}]
        )

    def test_lightning_has_no_override_switch(self) -> None:
        manual = [("lightning", "Lightning", None, 1.0)]
        plan = ue_weather.build_weather_plan(self.existing, None, manual, [], save=False)
        self.assertEqual(plan["steps"], [{"op": "property", "name": "Lightning", "value": 1.0}])

    def test_weather_reads_cover_preset_values_switches_and_wind(self) -> None:
        names = {item["as"] for item in ue_weather.build_reads()}
        self.assertIn("weather", names)
        self.assertIn("rain", names)
        self.assertIn("rain_override", names)
        self.assertIn("wind_direction", names)


class FakeConnection:
    """替身连接：按预设的远端返回值驱动 EditorConnection.run。"""

    def __init__(self, output=(), result=""):
        self.output = list(output)
        self.result = result
        self.commands = []

    def run_command(self, command, **_kwargs):
        self.commands.append(command)
        return {"output": self.output, "result": self.result}


class FakeModule:
    MODE_EXEC_FILE = "ExecuteFile"


def make_connection(output=(), result=""):
    connection = uds_common.EditorConnection({"uproject": Path("D:/P/P.uproject")})
    connection._module = FakeModule()  # pylint: disable=protected-access
    connection._connection = FakeConnection(output, result)  # pylint: disable=protected-access
    return connection


def remote_line(payload):
    return {"type": "Info", "output": uds_common.REMOTE_MARKER + json.dumps(payload)}


class RemoteResultTests(unittest.TestCase):
    def test_success_payload_is_returned(self) -> None:
        connection = make_connection([remote_line({"ok": True, "created": False})])
        self.assertEqual(connection.run("pass"), {"ok": True, "created": False})

    def test_save_failure_propagates_as_error(self) -> None:
        connection = make_connection(
            [remote_line({"ok": False, "error": "RuntimeError: 保存失败，未写入任何包"})]
        )
        with self.assertRaises(UdsError) as caught:
            connection.run("pass")
        self.assertIn("保存失败", str(caught.exception))

    def test_missing_property_error_propagates(self) -> None:
        connection = make_connection(
            [remote_line({"ok": False, "error": "RuntimeError: 以下属性不存在或不可写：Weather"})]
        )
        with self.assertRaises(UdsError) as caught:
            connection.run("pass")
        self.assertIn("Weather", str(caught.exception))

    def test_no_marker_reports_editor_output(self) -> None:
        connection = make_connection([{"type": "Error", "output": "SyntaxError: bad"}])
        with self.assertRaises(UdsError) as caught:
            connection.run("pass")
        self.assertIn("SyntaxError", str(caught.exception))


class ReadinessTests(unittest.TestCase):
    def test_missing_editor_points_at_launch_skill(self) -> None:
        context = {"process_ids": [], "remote": {"enabled": True, "plugin_enabled": True}}
        with self.assertRaises(UdsError) as caught:
            uds_common.check_ready(context)
        self.assertIn("das-ue-launch", str(caught.exception))

    def test_disabled_remote_execution_points_at_autoconfig_skill(self) -> None:
        context = {"process_ids": ["1"], "remote": {"enabled": False, "plugin_enabled": True}}
        with self.assertRaises(UdsError) as caught:
            uds_common.check_ready(context)
        self.assertIn("das-ue-autoconfig", str(caught.exception))

    def test_ready_context_passes(self) -> None:
        context = {"process_ids": ["1"], "remote": {"enabled": True, "plugin_enabled": True}}
        self.assertIsNone(uds_common.check_ready(context))


class SupportErrorTests(unittest.TestCase):
    def test_launch_errors_become_uds_errors(self) -> None:
        def boom():
            raise RuntimeError("无法定位 Unreal Engine")

        with self.assertRaises(UdsError) as caught:
            uds_common.call_support(boom)
        self.assertIn("无法定位 Unreal Engine", str(caught.exception))

    def test_engine_resolution_failure_suggests_engine_root(self) -> None:
        def resolve(*_args):
            raise RuntimeError("无法定位 Unreal Engine")

        context = {
            "uproject": Path("D:/P/P.uproject"),
            "engine_root": None,
            "engine_override": None,
            "project_data": {},
            "support": {"resolve_engine_root": resolve},
        }
        with self.assertRaises(UdsError) as caught:
            uds_common.ensure_engine_root(context)
        self.assertIn("--engine-root", str(caught.exception))

    def test_known_engine_root_is_returned_as_is(self) -> None:
        context = {"engine_root": Path("S:/UE/Engine")}
        self.assertEqual(uds_common.ensure_engine_root(context), Path("S:/UE/Engine"))


class InjectedCodeTests(unittest.TestCase):
    def test_templates_render_to_valid_python(self) -> None:
        for template in (uds_common.DISCOVER_TEMPLATE, uds_common.APPLY_TEMPLATE):
            code = uds_common.build_code(template, {"a": 1, "b": "中文"})
            compile(code, "<injected>", "exec")

    def test_payload_survives_round_trip(self) -> None:
        payload = {"steps": [{"op": "property", "name": "Fog", "value": 2.0}]}
        code = uds_common.build_code(uds_common.APPLY_TEMPLATE, payload)
        literal = code.split("json.loads(", 1)[1].split(")", 1)[0]
        self.assertEqual(json.loads(eval(literal)), payload)  # pylint: disable=eval-used


class EndpointTests(unittest.TestCase):
    def test_endpoint_is_split_and_falls_back(self) -> None:
        self.assertEqual(uds_common.split_endpoint("239.0.0.1:6766", ("x", 1)), ("239.0.0.1", 6766))
        self.assertEqual(uds_common.split_endpoint("", ("x", 1)), ("x", 1))
        self.assertEqual(uds_common.split_endpoint("239.0.0.1:abc", ("x", 1)), ("x", 1))

    def test_simple_class_name_strips_wrapper_and_suffix(self) -> None:
        self.assertEqual(uds_common.simple_class_name("Ultra_Dynamic_Sky_C"), "ultra_dynamic_sky")
        self.assertEqual(
            uds_common.simple_class_name("BlueprintGeneratedClass'/Game/A/Rain.Rain_C'"), "rain"
        )
        self.assertEqual(uds_common.simple_class_name("/Script/Engine.Actor"), "actor")


if __name__ == "__main__":
    unittest.main()
