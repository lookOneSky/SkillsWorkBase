"""Exercise VS Code Alt+K configuration without touching real user settings."""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).with_name("configure_antigravity.py")
SPEC = importlib.util.spec_from_file_location("configure_antigravity", SCRIPT)
cfg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cfg)


class ConfigureAntigravityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.appdata = self.root / "Roaming"
        self.user = self.appdata / "Code" / "User"
        self.keymap = self.user / "keybindings.json"
        self.extensions = self.root / "extensions"
        self.registrations = []
        self.manifest = self.add_extension("1.13.0")
        self.environment = mock.patch.dict(os.environ, {"APPDATA": str(self.appdata)})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def add_extension(self, version, *, register=True, commands=None):
        directory = self.extensions / f"google.google-antigravity-{version}"
        directory.mkdir(parents=True)
        manifest = directory / "package.json"
        manifest.write_text(json.dumps({
            "publisher": "google",
            "name": "google-antigravity",
            "version": version,
            "contributes": {"commands": [
                {"command": command} for command in (
                    commands if commands is not None else (
                        "antigravity.insertSnippet", "antigravity.addFileToChat",
                    )
                )
            ]},
        }), encoding="utf-8")
        if register:
            self.registrations.append({
                "identifier": {"id": "google.google-antigravity"},
                "version": version,
                "relativeLocation": directory.name,
            })
        self.write_registry()
        return manifest

    def write_registry(self):
        (self.extensions / "extensions.json").write_text(
            json.dumps(self.registrations), encoding="utf-8",
        )

    def run_cli(self, *options, explicit=True):
        output = io.StringIO()
        args = ["--extensions-dir", str(self.extensions)]
        if explicit:
            args += ["--vscode-user-dir", str(self.user)]
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = cfg.main(args + list(options))
        return code, json.loads(output.getvalue())

    def set_keymap(self, content):
        self.user.mkdir(parents=True, exist_ok=True)
        self.keymap.write_bytes(content)

    def test_script_creates_bindings_and_check_is_read_only(self):
        args = [sys.executable, str(SCRIPT), "--vscode-user-dir", str(self.user),
                "--extensions-dir", str(self.extensions)]
        pending = subprocess.run(args + ["--check"], capture_output=True, encoding="utf-8")
        self.assertEqual(pending.returncode, 2, pending.stderr)
        self.assertEqual(json.loads(pending.stdout)["status"], "needs-configuration")
        self.assertFalse(self.user.exists())

        configured = subprocess.run(args, capture_output=True, encoding="utf-8")
        self.assertEqual(configured.returncode, 0, configured.stderr)
        result = json.loads(configured.stdout)
        self.assertTrue(result["changed"])
        self.assertNotIn("backup", result)
        self.assertEqual(cfg.parse_jsonc(self.keymap.read_text(encoding="utf-8"))[0], cfg.BINDINGS)
        before = self.keymap.read_bytes()
        checked = subprocess.run(args + ["--check"], capture_output=True, encoding="utf-8")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertFalse(json.loads(checked.stdout)["changed"])
        self.assertEqual(self.keymap.read_bytes(), before)

    def test_preserves_jsonc_bytes_and_backs_up_original(self):
        before = (
            b"\xef\xbb\xbf// user shortcuts\r\n[\r\n"
            b'    {"key":"ctrl+k","command":"other.command"}, /* keep */\r\n'
            b'    {"key":"shift+alt+k","command":"other.command",'
            b'"args":{"text":"https://example.test/a, }","quoted":"\\\"//",},},\r\n'
            b"] // end\r\n"
        )
        self.set_keymap(before)
        original_entries = cfg.parse_jsonc(before.decode("utf-8-sig"))[0]
        self.assertEqual(self.run_cli("--check")[0], 2)
        self.assertEqual(self.keymap.read_bytes(), before)
        self.assertEqual(list(self.user.iterdir()), [self.keymap])
        code, result = self.run_cli()
        self.assertEqual(code, 0, result)
        self.assertEqual(Path(result["backup"]).read_bytes(), before)
        after = self.keymap.read_bytes()
        self.assertTrue(after.startswith(before[:before.rfind(b"]")]))
        self.assertTrue(after.endswith(b"] // end\r\n"))
        self.assertNotIn(b"\n", after.replace(b"\r\n", b""))
        self.assertEqual(cfg.parse_jsonc(after.decode("utf-8-sig"))[0], original_entries + cfg.BINDINGS)

    def test_migrates_codex_and_claude_without_changing_accessibility_rules(self):
        retained = [
            {"key": "shift+alt+k", "command": "editor.action.accessibilityHelpConfigureKeybindings",
             "when": "accessibilityHelpIsShown && accessibleViewHasUnassignedKeybindings"},
            {"key": "alt+k", "command": "-editor.action.accessibilityHelpConfigureKeybindings",
             "when": "accessibilityHelpIsShown && accessibleViewHasUnassignedKeybindings"},
            {"key": "shift+alt+k", "command": "keybindings.editor.recordSearchKeys",
             "when": "inKeybindings && inKeybindingsSearch"},
            {"key": "alt+k", "command": "-keybindings.editor.recordSearchKeys",
             "when": "inKeybindings && inKeybindingsSearch"},
            {"key": "ctrl+k", "command": "chatgpt.addToThread"},
        ]
        old = [
            {"key": "Alt+K", "command": "chatgpt.addToThread", "when": "editorHasSelection"},
            {"key": "alt+k", "command": "chatgpt.addFileToThread"},
            {"key": "alt+k", "command": "claude-vscode.insertAtMention", "when": "editorTextFocus"},
            {"key": "alt+k", "command": "-claude-vscode.insertAtMention"},
            {"key": "alt+k", "command": "-chatgpt.addToThread"},
            {"key": "alt+k", "command": "-chatgpt.addFileToThread"},
        ]
        self.set_keymap(json.dumps(retained + old).encode("utf-8"))
        code, result = self.run_cli()
        self.assertEqual(code, 0, result)
        self.assertEqual(cfg.parse_jsonc(self.keymap.read_text(encoding="utf-8"))[0], retained + cfg.BINDINGS)
        self.assertEqual(self.run_cli("--check")[0], 0)

    def test_conflicting_shortcuts_are_preserved_with_targets_last(self):
        custom = [
            {"key": "Alt+K Alt+X", "command": "custom.chord", "when": "editorTextFocus"},
            {"key": "alt+[KeyK]", "command": "other.command"},
        ]
        rules = cfg.BINDINGS + custom + [
            {"key": "alt+k", "command": "-antigravity.insertSnippet"},
            {"key": "alt+k", "command": "-antigravity.addFileToChat"},
            {"key": "alt+k", "command": "antigravity.insertSnippet", "when": "editorTextFocus"},
        ]
        self.set_keymap(json.dumps(rules).encode("utf-8"))
        code, result = self.run_cli()
        self.assertEqual(code, 0, result)
        after = self.keymap.read_bytes()
        self.assertEqual(cfg.parse_jsonc(after.decode("utf-8"))[0], custom + cfg.BINDINGS)
        self.assertEqual(self.run_cli("--check")[0], 0)
        self.assertEqual(self.keymap.read_bytes(), after)

    def test_repeated_configuration_does_not_write_or_create_backups(self):
        before = b"// existing\n" + json.dumps(cfg.BINDINGS).encode("utf-8")
        self.set_keymap(before)
        timestamp = self.keymap.stat().st_mtime_ns
        with mock.patch.object(cfg, "write_keymap", side_effect=AssertionError("unexpected write")):
            for options in ((), ("--check",), ()):
                code, result = self.run_cli(*options)
                self.assertEqual(code, 0, result)
                self.assertFalse(result["changed"])
                self.assertNotIn("backup", result)
        self.assertEqual(self.keymap.read_bytes(), before)
        self.assertEqual(self.keymap.stat().st_mtime_ns, timestamp)
        self.assertEqual(list(self.user.iterdir()), [self.keymap])

    def test_comments_only_and_empty_inputs_get_bindings(self):
        for before in (None, b"", b"// header", b"[/* empty */]", b"\xef\xbb\xbf[]\r\n"):
            with self.subTest(before=before):
                after = cfg.prepare_keymap(before)
                self.assertEqual(cfg.parse_jsonc(after.decode("utf-8-sig"))[0], cfg.BINDINGS)
                self.assertEqual(cfg.prepare_keymap(after), after)

    def test_invalid_input_is_not_overwritten(self):
        samples = (
            b"[/* unterminated", b"[,]", b"[{},]", b"{}", b"null",
            b'[{"key": 3, "command":"custom"}]', b"\xff\xfe",
        )
        for before in samples:
            with self.subTest(before=before):
                self.set_keymap(before)
                for options in ((), ("--check",)):
                    code, result = self.run_cli(*options)
                    self.assertEqual(code, 1, result)
                    self.assertEqual(result["status"], "failed")
                    self.assertEqual(self.keymap.read_bytes(), before)
                    self.assertEqual(list(self.user.iterdir()), [self.keymap])

    def test_default_target_is_vscode_even_when_antigravity_ide_exists(self):
        other_dirs = [self.appdata / product / "User" for product in ("Antigravity IDE", "Antigravity")]
        for directory in other_dirs:
            directory.mkdir(parents=True)
        code, result = self.run_cli(explicit=False)
        self.assertEqual(code, 0, result)
        self.assertEqual(Path(result["keybindings"]), self.keymap.resolve())
        self.assertTrue(self.keymap.is_file())
        self.assertTrue(all(not (directory / "keybindings.json").exists() for directory in other_dirs))
        self.assertEqual(self.run_cli("--check", explicit=False)[0], 0)

    def test_named_profile_requires_explicit_directory(self):
        profile = self.user / "profiles" / "named-profile"
        profile.mkdir(parents=True)
        code, result = self.run_cli(explicit=False)
        self.assertEqual(code, 1, result)
        self.assertIn("--vscode-user-dir", result["error"])
        self.assertFalse(self.keymap.exists())
        code, result = self.run_cli("--vscode-user-dir", str(profile))
        self.assertEqual(code, 0, result)
        self.assertTrue((profile / "keybindings.json").is_file())
        self.assertFalse(self.keymap.exists())

    def test_registered_extension_is_used_instead_of_stale_version(self):
        self.add_extension("0.1.0", register=False, commands=[])
        self.assertEqual(cfg.find_manifest(self.extensions), self.manifest.resolve())
        code, result = self.run_cli()
        self.assertEqual(code, 0, result)
        self.assertEqual(Path(result["manifest"]), self.manifest.resolve())

    def test_missing_registered_extension_or_commands_does_not_write(self):
        for missing in ("registration", "antigravity.insertSnippet", "antigravity.addFileToChat"):
            with self.subTest(missing=missing):
                self.write_registry()
                package = json.loads(self.manifest.read_text(encoding="utf-8"))
                package["contributes"]["commands"] = [
                    {"command": command}
                    for command in ("antigravity.insertSnippet", "antigravity.addFileToChat")
                    if command != missing
                ]
                self.manifest.write_text(json.dumps(package), encoding="utf-8")
                if missing == "registration":
                    (self.extensions / "extensions.json").write_text("[]", encoding="utf-8")
                for options in ((), ("--check",)):
                    code, result = self.run_cli(*options)
                    self.assertEqual(code, 1, result)
                    self.assertEqual(result["status"], "failed")
                    self.assertFalse(self.user.exists())

    def test_concurrent_change_before_write_is_preserved(self):
        before = b"[]"
        other = b'[{"key":"ctrl+k","command":"other.command"}]'
        self.set_keymap(other)
        with self.assertRaisesRegex(ValueError, "已被其他程序修改"):
            cfg.write_keymap(self.keymap, before, cfg.prepare_keymap(before))
        self.assertEqual(self.keymap.read_bytes(), other)
        self.assertEqual(list(self.user.iterdir()), [self.keymap])

    def test_concurrent_change_during_write_is_preserved_and_temp_removed(self):
        before = b"[]"
        other = b'[{"key":"ctrl+k","command":"other.command"}]'
        self.set_keymap(before)
        reads = 0
        original_read = cfg.read_optional

        def concurrent_read(path):
            nonlocal reads
            reads += 1
            if reads == 2:
                path.write_bytes(other)
            return original_read(path)

        with mock.patch.object(cfg, "read_optional", side_effect=concurrent_read):
            with self.assertRaisesRegex(ValueError, "已被其他程序修改"):
                cfg.write_keymap(self.keymap, before, cfg.prepare_keymap(before))
        self.assertEqual(self.keymap.read_bytes(), other)
        backups = list(self.user.glob("keybindings.das-antigravity-*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)
        self.assertEqual(list(self.user.glob(".keybindings-*")), [])


if __name__ == "__main__":
    unittest.main()
