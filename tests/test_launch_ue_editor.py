import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPT = (Path(__file__).resolve().parents[1] / ".agents/skills/das-ue-launch/launch_ue_editor.py")
SPEC = importlib.util.spec_from_file_location("launch_ue_editor", SCRIPT)
launch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launch)


class EditorBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = self.root / "EngineRoot"
        self.engine_bin = self.engine / "Engine/Binaries/Win64"
        self.engine_bin.mkdir(parents=True)
        (self.engine / "Engine/Build").mkdir()
        self.project = self.root / "Project/Example.uproject"
        self.write_json(self.project, {"Modules": [{"Name": "Example", "Type": "Runtime"}]})
        self.binaries = self.project.parent / "Binaries/Win64"
        self.binaries.mkdir(parents=True)
        self.development = self.engine_bin / "UnrealEditor.exe"
        self.debug_game = self.engine_bin / "UnrealEditor-Win64-DebugGame.exe"
        self.development.touch()
        self.debug_game.touch()
        self.write_json(self.engine_bin / "UnrealEditor.modules", {"BuildId": "engine-id", "Modules": {}})

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8-sig")

    def manifest(self, directory, editor, module="Example", build_id="engine-id", create_dll=True):
        dll = "{}-{}.dll".format(module, launch.editor_configuration(editor))
        self.write_json(directory / (editor.stem + ".modules"),
                        {"BuildId": build_id, "Modules": {module: dll}})
        if create_dll:
            (directory / dll).touch()
        return dll

    def target(self, editor, timestamp, target_type="Editor", launch_path=None, name=None):
        path = self.binaries / (name or (editor.stem + ".target"))
        self.write_json(path, {
            "TargetType": target_type,
            "Configuration": launch.editor_configuration(editor),
            "Launch": launch_path or "$(EngineDir)/Binaries/Win64/{}".format(editor.name),
        })
        os.utime(path, (timestamp, timestamp))

    def run_main(self, *args, running=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(launch, "running_editor_processes", return_value=running or []), \
                patch.object(launch, "launch_editor", return_value=Mock(pid=123)) as start, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = launch.main([str(self.project), "--engine-root", str(self.engine), *args])
        lines = stdout.getvalue().splitlines()
        results = [json.loads(line[len(launch.RESULT_MARKER):]) for line in lines
                   if line.startswith(launch.RESULT_MARKER)]
        return code, stdout.getvalue(), stderr.getvalue(), results, start

    def test_invalid_manifests_are_unavailable(self):
        path = self.binaries / "invalid.modules"
        self.assertEqual(launch.read_modules_manifest(path), {})
        for text in ('{', '[]', '{}', '{"BuildId": "id", "Modules": []}',
                     '{"BuildId": "id", "Modules": {"Example": null}}'):
            with self.subTest(text=text):
                path.write_text(text, encoding="utf-8")
                self.assertEqual(launch.read_modules_manifest(path), {})
        path.write_bytes(b"\xff\xff")
        self.assertEqual(launch.read_modules_manifest(path), {})

    def test_executable_configuration_names(self):
        for name, config in (("UnrealEditor.exe", "Development"), ("UE4Editor.exe", "Development"),
                             ("UnrealEditor-Win64-DebugGame.exe", "DebugGame"),
                             ("UE4Editor-Win64-Debug.exe", "Debug")):
            with self.subTest(name=name):
                self.assertEqual(launch.editor_configuration(Path(name)), config)

    def test_debug_game_uses_default_engine_manifest_and_checks_nested_plugins(self):
        self.target(self.development, 10)
        self.target(self.debug_game, 20)
        for editor in (self.development, self.debug_game):
            self.manifest(self.binaries, editor)
        plugin = self.project.parent / "Plugins/Group/DasUnreal/Binaries/Win64"
        self.manifest(plugin, self.debug_game, "DasUnreal")
        (self.project.parent / "Plugins/ContentOnly/Binaries/Win64").mkdir(parents=True)
        # A configuration-specific engine manifest must never be consulted.
        self.write_json(self.engine_bin / (self.debug_game.stem + ".modules"),
                        {"BuildId": "wrong-id", "Modules": {}})
        self.assertEqual(launch.select_editor(self.engine, self.project),
                         (self.debug_game, "DebugGame", []))
        self.assertIn("DasUnreal: 缺少 UnrealEditor.modules",
                      launch.validate_editor_build(self.engine, self.project, self.development))

    def test_complete_development_beats_newer_debug_game(self):
        self.target(self.development, 10)
        self.target(self.debug_game, 20)
        for editor in (self.development, self.debug_game):
            self.manifest(self.binaries, editor)
        self.assertEqual(launch.select_editor(self.engine, self.project),
                         (self.development, "Development", []))

    def test_complete_default_development_does_not_need_target(self):
        self.target(self.debug_game, 20)
        self.manifest(self.binaries, self.debug_game)
        self.manifest(self.binaries, self.development)
        self.assertEqual(launch.select_editor(self.engine, self.project)[0], self.development)

    def test_latest_valid_non_development_target_wins(self):
        debug = self.engine_bin / "UnrealEditor-Win64-Debug.exe"
        debug.touch()
        self.target(self.debug_game, 20)
        self.target(debug, 30)
        for editor in (debug, self.debug_game):
            self.manifest(self.binaries, editor)
        self.assertEqual(launch.select_editor(self.engine, self.project), (debug, "Debug", []))

    def test_all_incomplete_retains_target_priority_and_problems(self):
        self.target(self.development, 10)
        self.target(self.debug_game, 20)
        editor, config, problems = launch.select_editor(self.engine, self.project)
        self.assertEqual((editor, config), (self.debug_game, "DebugGame"))
        self.assertEqual(problems, ["Example: 缺少 UnrealEditor-Win64-DebugGame.modules"])

    def test_forced_config_and_missing_candidate(self):
        self.target(self.debug_game, 20)
        self.manifest(self.binaries, self.debug_game)
        editor, config, problems = launch.select_editor(self.engine, self.project, "development")
        self.assertEqual((editor, config), (self.development, "Development"))
        self.assertTrue(problems)
        with self.assertRaises(launch.LaunchError):
            launch.select_editor(self.engine, self.project, "DoesNotExist")

    def test_game_targets_and_nonexistent_launches_are_ignored(self):
        self.target(self.debug_game, 20, target_type="Game")
        self.target(self.debug_game, 30, name="Missing.target", launch_path="$(EngineDir)/Missing.exe")
        self.manifest(self.binaries, self.debug_game)
        with self.assertRaises(launch.LaunchError):
            launch.select_editor(self.engine, self.project, "DebugGame")

    def test_project_dir_expansion(self):
        editor = self.binaries / self.debug_game.name
        editor.touch()
        self.target(editor, 20, launch_path="$(ProjectDir)/Binaries/Win64/{}".format(editor.name))
        self.manifest(self.binaries, editor)
        self.assertEqual(launch.select_editor(self.engine, self.project), (editor, "DebugGame", []))

    def test_mismatched_build_and_missing_dll_are_reported(self):
        dll = self.manifest(self.binaries, self.development, build_id="old-id", create_dll=False)
        problems = launch.validate_editor_build(self.engine, self.project, self.development)
        self.assertEqual(len(problems), 2)
        self.assertIn("BuildId", problems[0])
        self.assertEqual(problems[1], "Example: 缺少 " + dll)

    def test_corrupt_project_or_missing_engine_manifest_cannot_pass(self):
        self.manifest(self.binaries, self.development)
        (self.binaries / "UnrealEditor.modules").write_text('{', encoding="utf-8")
        self.assertIn("清单无效", launch.validate_editor_build(self.engine, self.project, self.development)[0])
        self.manifest(self.binaries, self.development)
        (self.engine_bin / "UnrealEditor.modules").unlink()
        self.assertIn("引擎:", launch.validate_editor_build(self.engine, self.project, self.development)[0])

    def test_ue4_engine_manifest_fallback(self):
        (self.engine_bin / "UnrealEditor.modules").rename(self.engine_bin / "UE4Editor.modules")
        self.development.unlink()
        editor = self.engine_bin / "UE4Editor.exe"
        editor.touch()
        self.manifest(self.binaries, editor)
        self.assertEqual(launch.select_editor(self.engine, self.project), (editor, "Development", []))

    def test_blueprint_and_unbuilt_template_use_default_without_warning(self):
        self.binaries.rmdir()
        for data in ({}, {"Modules": [{"Name": "Example", "Type": "Runtime"}]}):
            with self.subTest(data=data):
                self.write_json(self.project, data)
                self.assertEqual(launch.select_editor(self.engine, self.project),
                                 (self.development, "Development", []))

    def test_no_executable_is_an_error(self):
        self.development.unlink()
        with self.assertRaises(launch.LaunchError):
            launch.select_editor(self.engine, self.project)

    @unittest.skipUnless(os.name == "nt", "Windows launcher")
    def test_forced_incomplete_main_launches_and_limits_problem_output(self):
        self.manifest(self.binaries, self.development)
        for index in range(7):
            self.manifest(self.project.parent / "Plugins/Plugin{}/Binaries/Win64".format(index),
                          self.debug_game)
        json_path = self.root / "result.json"
        code, stdout, stderr, results, start = self.run_main(
            "--config", "Development", "--json", str(json_path), "--", "-log")
        self.assertEqual((code, stderr), (0, ""))
        start.assert_called_once_with(self.development, self.project, ["-log"])
        self.assertIn("[配置] Development", stdout)
        warning = next(line for line in stdout.splitlines() if line.startswith("[提示]"))
        self.assertEqual(warning.count("缺少"), 3)
        result = results[0]
        self.assertEqual(result["configuration"], "Development")
        self.assertFalse(result["modules_ready"])
        self.assertEqual(len(result["modules_problems"]), 5)
        self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), result)

    @unittest.skipUnless(os.name == "nt", "Windows launcher")
    def test_nonexistent_forced_config_exits_one_without_launch(self):
        code, _, stderr, results, start = self.run_main("--config", "不存在的配置")
        self.assertEqual(code, 1)
        self.assertIn("不存在的配置", stderr)
        self.assertEqual(results, [])
        start.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows launcher")
    def test_running_process_config_overrides_available_development_and_forced_config(self):
        self.manifest(self.binaries, self.development)
        command_line = '"{}" "{}"'.format(self.debug_game, self.project)
        code, stdout, _, results, start = self.run_main(
            "--config", "Development", running=[("50056", command_line)])
        self.assertEqual(code, 0)
        start.assert_not_called()
        self.assertIn("[运行中]", stdout)
        self.assertNotIn("[提示]", stdout)
        self.assertEqual(results[0]["editor"], str(self.debug_game))
        self.assertEqual(results[0]["configuration"], "DebugGame")
        self.assertTrue(results[0]["modules_ready"])
        self.assertEqual(results[0]["modules_problems"], [])


if __name__ == "__main__":
    unittest.main()
