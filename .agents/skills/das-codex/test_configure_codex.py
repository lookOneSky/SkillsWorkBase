import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parent
SPEC = importlib.util.spec_from_file_location("configure_codex", ROOT / "configure_codex.py")
cfg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cfg)
ORIGINAL = b'export function mode(){let N=M?.mode??v??`default`;return {collaborationMode:N};}\n'


class ConfigureCodexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="das-codex-test-")
        self.root = Path(self.tmp.name)
        assert self.root.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.tmp.cleanup)
        self.extensions = self.root / "extensions"
        self.extension = self.extensions / "openai.chatgpt-1.2.3"
        self.assets = self.extension / "webview" / "assets"
        self.assets.mkdir(parents=True)
        (self.extension / "out").mkdir()
        (self.extension / "out" / "extension.js").write_bytes(b"commandKeybindings")
        (self.assets / "src-registry.js").write_bytes(b"composer.togglePlanMode")
        self.module = self.assets / "use-collaboration-mode-fixture.js"
        self.module.write_bytes(ORIGINAL)
        (self.extension / "package.json").write_bytes(cfg.json_bytes({"publisher": "openai", "name": "chatgpt", "version": "1.2.3", "contributes": {"commands": [{"command": rule["command"]} for rule in cfg.CODE_RULES]}}))
        (self.extensions / "extensions.json").write_bytes(cfg.json_bytes([{"identifier": {"id": "openai.chatgpt"}, "relativeLocation": self.extension.name}]))
        self.home = self.root / "home"
        self.keymap = self.home / "keybindings.json"
        self.user_dir = self.root / "vscode-user"
        self.vscode_keymap = self.user_dir / "keybindings.json"
        self.args = ["--extensions-dir", str(self.extensions), "--codex-home", str(self.home), "--vscode-user-dir", str(self.user_dir)]

    def run_cli(self, *extra):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = cfg.main(self.args + list(extra))
        return code, output.getvalue()

    def set_keymap(self, entries):
        self.home.mkdir(exist_ok=True)
        self.keymap.write_bytes(cfg.json_bytes(entries))

    def test_initialize_and_restore_exact_bytes(self):
        self.set_keymap([{"command": "newTask", "key": "Ctrl+Alt+N", "version": 1}])
        before = self.keymap.read_bytes()
        code, output = self.run_cli()
        self.assertEqual(code, 0, output)
        result = json.loads(output)
        entries = cfg.load_json(self.keymap)
        self.assertEqual(entries[0], {"command": "newTask", "key": "Ctrl+Alt+N", "version": 1})
        self.assertEqual(entries[-1], {"command": cfg.COMMAND, "key": cfg.KEY})
        code_rules, _ = cfg.parse_jsonc(self.vscode_keymap.read_text(encoding="utf-8"))
        self.assertEqual(code_rules, cfg.CODE_RULES)
        self.assertTrue(all(result["checks"].values()))
        self.assertNotEqual(self.module.read_bytes(), ORIGINAL)
        self.assertTrue(result["reload_required"])
        code, output = self.run_cli("--restore", result["backup"])
        self.assertEqual(code, 0, output)
        self.assertEqual(self.module.read_bytes(), ORIGINAL)
        self.assertEqual(self.keymap.read_bytes(), before)
        self.assertFalse(self.vscode_keymap.exists())

    def test_repeat_execution_does_not_write_or_create_backup(self):
        code, output = self.run_cli()
        self.assertEqual(code, 0, output)
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (self.keymap, self.module, self.vscode_keymap)}
        backups = list((self.home / "backups").iterdir())
        code, output = self.run_cli()
        self.assertEqual(code, 0, output)
        self.assertNotIn("backup", json.loads(output))
        self.assertEqual(backups, list((self.home / "backups").iterdir()))
        self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before})

    def test_new_keymap_is_removed_on_restore(self):
        code, output = self.run_cli()
        self.assertEqual(code, 0, output)
        backup = json.loads(output)["backup"]
        code, output = self.run_cli("--restore", backup)
        self.assertEqual(code, 0, output)
        self.assertFalse(self.keymap.exists())
        self.assertFalse(self.vscode_keymap.exists())
        self.assertEqual(self.module.read_bytes(), ORIGINAL)

    def test_key_conflict_stops_before_any_write(self):
        self.set_keymap([{"command": "newTask", "key": "Tab+Shift"}])
        before = self.keymap.read_bytes()
        code, output = self.run_cli()
        self.assertEqual(code, 1, output)
        self.assertEqual(self.keymap.read_bytes(), before)
        self.assertEqual(self.module.read_bytes(), ORIGINAL)
        self.assertFalse((self.home / "backups").exists())

    def test_invalid_json_stops_before_any_write(self):
        self.home.mkdir()
        self.keymap.write_bytes(b"[{invalid json}]")
        code, output = self.run_cli()
        self.assertEqual(code, 1, output)
        self.assertEqual(self.module.read_bytes(), ORIGINAL)
        self.assertEqual(self.keymap.read_bytes(), b"[{invalid json}]")

    def test_unknown_plugin_structure_is_not_patched(self):
        self.module.write_bytes(b"new code structure")
        code, output = self.run_cli()
        self.assertEqual(code, 1, output)
        self.assertEqual(self.module.read_bytes(), b"new code structure")
        self.assertFalse(self.home.exists())
        self.assertFalse(self.user_dir.exists())

    def test_failed_second_write_rolls_back_first(self):
        original_write = cfg.atomic_write
        def failing_write(path, data):
            if path == self.module:
                raise PermissionError("simulated locked plugin")
            return original_write(path, data)
        with patch.object(cfg, "atomic_write", side_effect=failing_write):
            code, output = self.run_cli()
        self.assertEqual(code, 1, output)
        self.assertFalse(self.keymap.exists())
        self.assertFalse(self.vscode_keymap.exists())
        self.assertEqual(self.module.read_bytes(), ORIGINAL)
        self.assertEqual(len(list((self.home / "backups").iterdir())), 1)

    def test_restore_preserves_changes_made_after_initialization(self):
        code, output = self.run_cli()
        self.assertEqual(code, 0, output)
        backup = json.loads(output)["backup"]
        current_mode = self.module.read_bytes()
        entries = cfg.load_json(self.keymap) + [{"command": "newTask", "key": "Ctrl+N"}]
        self.keymap.write_bytes(cfg.json_bytes(entries))
        code, output = self.run_cli("--restore", backup)
        self.assertEqual(code, 1, output)
        self.assertEqual(cfg.load_json(self.keymap), entries)
        self.assertEqual(self.module.read_bytes(), current_mode)

    def test_registered_version_is_selected(self):
        (self.extensions / "openai.chatgpt-999.0.0").mkdir()
        code, output = self.run_cli()
        self.assertEqual(code, 0, output)
        self.assertEqual(json.loads(output)["extension"], str(self.extension))

    def test_check_never_writes_and_reports_pending_configuration(self):
        code, output = self.run_cli("--check")
        self.assertEqual(code, 2, output)
        self.assertFalse(self.home.exists())
        self.assertEqual(self.module.read_bytes(), ORIGINAL)
        self.assertEqual(self.run_cli()[0], 0)
        code, output = self.run_cli("--check")
        self.assertEqual(code, 0, output)
        self.assertEqual(json.loads(output)["pending_files"], [])

    def test_other_plan_binding_is_preserved_and_null_binding_removed(self):
        self.set_keymap([{"command": cfg.COMMAND, "key": "Ctrl+Alt+P"}, {"command": cfg.COMMAND, "key": None}])
        code, output = self.run_cli()
        self.assertEqual(code, 0, output)
        self.assertEqual(cfg.load_json(self.keymap), [{"command": cfg.COMMAND, "key": "Ctrl+Alt+P"}, {"command": cfg.COMMAND, "key": cfg.KEY}])

    def test_renamed_minified_variables_are_supported(self):
        renamed = ORIGINAL.replace(b'N=M?.mode??v??`default`', b'selected=$thread?.mode??$draft??"default"')
        self.assertNotEqual(renamed, ORIGINAL)
        self.module.write_bytes(renamed)
        code, output = self.run_cli()
        self.assertEqual(code, 0, output)
        self.assertIn(b'selected=$thread?.mode??$draft??"plan"', self.module.read_bytes())

    def set_vscode_keymap(self, text):
        self.user_dir.mkdir(exist_ok=True)
        self.vscode_keymap.write_bytes(text.encode("utf-8"))

    def test_jsonc_comments_trailing_commas_and_bom_are_preserved(self):
        text = '\ufeff// user note\r\n[\r\n /* kept */ {"key":"ctrl+x","command":"custom","args":{"text":"// literal, } /* text */ \\\"",},}, // trailing\r\n]\r\n'
        self.set_vscode_keymap(text)
        before = self.vscode_keymap.read_bytes()
        original_entries, _ = cfg.parse_jsonc(text.lstrip("\ufeff"))
        code, output = self.run_cli()
        self.assertEqual(code, 0, output)
        current = self.vscode_keymap.read_bytes()
        self.assertTrue(current.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"// user note\r\n", current)
        self.assertIn(b"/* kept */", current)
        self.assertIn(b"// trailing", current)
        entries, _ = cfg.parse_jsonc(current.decode("utf-8-sig"))
        self.assertEqual(entries, original_entries + cfg.CODE_RULES)
        code, output = self.run_cli("--restore", json.loads(output)["backup"])
        self.assertEqual(code, 0, output)
        self.assertEqual(self.vscode_keymap.read_bytes(), before)

    def test_vscode_jsonc_append_handles_all_array_endings(self):
        samples = ["", "// only comment", "[]", "[ ]", "/* note */ [/* inside */]",
                   '[{"key":"ctrl+x","command":"custom"}]',
                   '[{"key":"ctrl+x","command":"custom"},]',
                   '[{"key":"ctrl+x","command":"custom"} // final comment\n]']
        for text in samples:
            with self.subTest(text=text):
                self.set_vscode_keymap(text)
                original_entries, _ = cfg.parse_jsonc(text)
                _, after = cfg.prepare_vscode_keymap(self.vscode_keymap)
                entries, _ = cfg.parse_jsonc(after.decode("utf-8"))
                self.assertEqual(entries, original_entries + cfg.CODE_RULES)

    def test_later_editor_alt_k_conflict_is_overridden_without_deleting_rules(self):
        original = cfg.CODE_RULES + [{"key": "Alt+K", "command": "another.command", "when": "editorTextFocus"}]
        self.set_vscode_keymap(json.dumps(original))
        code, output = self.run_cli()
        self.assertEqual(code, 0, output)
        entries, _ = cfg.parse_jsonc(self.vscode_keymap.read_text(encoding="utf-8"))
        self.assertEqual(entries, original + cfg.CODE_RULES)
        self.assertEqual(self.run_cli("--check")[0], 0)
        self.assertNotIn("backup", json.loads(self.run_cli()[1]))

    def test_invalid_vscode_jsonc_leaves_all_configuration_untouched(self):
        self.set_vscode_keymap('[{"key":"alt+k", /* unterminated')
        before = self.vscode_keymap.read_bytes()
        code, output = self.run_cli()
        self.assertEqual(code, 1, output)
        self.assertFalse(self.home.exists())
        self.assertEqual(self.module.read_bytes(), ORIGINAL)
        self.assertEqual(self.vscode_keymap.read_bytes(), before)
        self.assertEqual(json.loads(output)["status"], "failed")

    def test_failed_vscode_write_rolls_back_plan_and_keymap(self):
        original_write = cfg.atomic_write
        def failing_write(path, data):
            if path == self.vscode_keymap:
                raise PermissionError("simulated locked VS Code keybindings")
            return original_write(path, data)
        with patch.object(cfg, "atomic_write", side_effect=failing_write):
            code, output = self.run_cli()
        self.assertEqual(code, 1, output)
        self.assertFalse(self.keymap.exists())
        self.assertFalse(self.vscode_keymap.exists())
        self.assertEqual(self.module.read_bytes(), ORIGINAL)

    def test_missing_code_command_is_reported_before_any_write(self):
        package = cfg.load_json(self.extension / "package.json")
        package["contributes"]["commands"] = []
        (self.extension / "package.json").write_bytes(cfg.json_bytes(package))
        code, output = self.run_cli()
        self.assertEqual(code, 1, output)
        self.assertIn("chatgpt.addToThread", json.loads(output)["error"])
        self.assertFalse(self.home.exists())
        self.assertFalse(self.user_dir.exists())

    def test_shared_codex_and_vscode_path_is_rejected(self):
        code, output = self.run_cli("--vscode-user-dir", str(self.home))
        self.assertEqual(code, 1, output)
        self.assertFalse(self.home.exists())

    def test_check_detects_deleted_alt_k_rule(self):
        self.assertEqual(self.run_cli()[0], 0)
        self.set_vscode_keymap(json.dumps(cfg.CODE_RULES[:1]))
        code, output = self.run_cli("--check")
        self.assertEqual(code, 2, output)
        result = json.loads(output)
        self.assertFalse(result["checks"]["alt_k_current_file"])
        self.assertEqual(result["pending_files"], [str(self.vscode_keymap)])

    def test_post_write_verification_failure_reports_recoverable_backup(self):
        original_verify = cfg.verify_configuration
        calls = 0
        def failing_verification(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise cfg.ConfigError("simulated post-write verification failure")
            return original_verify(*args)
        with patch.object(cfg, "verify_configuration", side_effect=failing_verification):
            code, output = self.run_cli()
        self.assertEqual(code, 1, output)
        result = json.loads(output)
        self.assertEqual(result["status"], "failed")
        backup = next((self.home / "backups").iterdir())
        self.assertIn(str(backup), result["error"])
        self.assertIn("simulated post-write verification failure", result["error"])
        code, output = self.run_cli("--restore", str(backup))
        self.assertEqual(code, 0, output)
        self.assertFalse(self.keymap.exists())
        self.assertFalse(self.vscode_keymap.exists())
        self.assertEqual(self.module.read_bytes(), ORIGINAL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
