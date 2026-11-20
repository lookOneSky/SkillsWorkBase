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
        (self.extension / "package.json").write_bytes(cfg.json_bytes({"publisher": "openai", "name": "chatgpt", "version": "1.2.3"}))
        (self.extensions / "extensions.json").write_bytes(cfg.json_bytes([{"identifier": {"id": "openai.chatgpt"}, "relativeLocation": self.extension.name}]))
        self.home = self.root / "home"
        self.keymap = self.home / "keybindings.json"
        appdata = self.root / "appdata"
        self.vscode_keymap = appdata / "Code" / "User" / "keybindings.json"
        appdata_patch = patch.dict(cfg.os.environ, {"APPDATA": str(appdata)})
        appdata_patch.start()
        self.addCleanup(appdata_patch.stop)
        self.args = ["--extensions-dir", str(self.extensions), "--codex-home", str(self.home)]

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
        self.assertFalse(self.vscode_keymap.exists())
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
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (self.keymap, self.module)}
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
        self.assertFalse(self.vscode_keymap.exists())

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

    def test_plan_initialization_keeps_claude_shortcut(self):
        self.vscode_keymap.parent.mkdir(parents=True)
        claude = b'[{"key":"alt+k","command":"claude-vscode.insertAtMention","when":"editorTextFocus"}]'
        self.vscode_keymap.write_bytes(claude)
        code, output = self.run_cli()
        self.assertEqual(code, 0, output)
        self.assertEqual(self.vscode_keymap.read_bytes(), claude)

    def test_legacy_vscode_keybindings_backup_can_still_be_restored(self):
        self.vscode_keymap.parent.mkdir(parents=True)
        before = b"[]"
        after = b'[{"key":"alt+k","command":"chatgpt.addToThread"}]'
        backup = cfg.create_backup(self.home, [(self.vscode_keymap, before, after)])
        self.vscode_keymap.write_bytes(after)
        code, output = self.run_cli("--restore", str(backup))
        self.assertEqual(code, 0, output)
        self.assertEqual(self.vscode_keymap.read_bytes(), before)

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
