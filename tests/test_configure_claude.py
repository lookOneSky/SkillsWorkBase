import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / ".claude/skills/das-claude/configure_claude.py"
SPEC = importlib.util.spec_from_file_location("configure_claude", SCRIPT)
cfg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cfg)


class ConfigureClaudeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        extensions = root / "extensions"
        extension = extensions / "anthropic.claude-code-2.1.322"
        extension.mkdir(parents=True)
        self.manifest = extension / "package.json"
        self.manifest.write_text(json.dumps({
            "publisher": "anthropic", "name": "claude-code",
            "contributes": {"commands": [{"command": cfg.COMMAND}]},
        }), encoding="utf-8")
        (extensions / "extensions.json").write_text(json.dumps([{
            "identifier": {"id": "anthropic.claude-code"}, "relativeLocation": extension.name,
        }]), encoding="utf-8")
        (extensions / "anthropic.claude-code-stale").mkdir()
        self.keymap = root / "profile" / "keybindings.json"
        self.args = ["--extensions-dir", str(extensions), "--vscode-user-dir", str(self.keymap.parent)]

    def run_cli(self, *options):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = cfg.main(self.args + list(options))
        return code, json.loads(output.getvalue())

    def set_keymap(self, data):
        self.keymap.parent.mkdir(exist_ok=True)
        self.keymap.write_bytes(data)

    def test_migrates_legacy_rules_without_touching_other_bindings(self):
        before = (
            b"\xef\xbb\xbf// user comment\r\n[\r\n"
            b'    {"key":"ctrl+k","command":"chatgpt.addToThread"},\r\n'
            b'    {"key":"alt+k","command":"-other.command"},\r\n'
            b'    {"key":"Alt+K","command":"chatgpt.addToThread"} /* keep */, \r\n'
            b'    {"key":"alt+k","command":"claude-vscode.insertAtMention","when":"editorTextFocus"},\r\n'
            b'    {"key":"alt+k","command":"-claude-vscode.insertAtMention","when":"editorTextFocus"},\r\n'
            b'    {"key":"alt+k","command":"chatgpt.addFileToThread"},\r\n'
            b'    {"key":"shift+alt+k","command":"other.command","args":{"text":"// text, }",},},\r\n'
            b"]\r\n"
        )
        self.set_keymap(before)
        self.assertEqual(self.run_cli("--check")[0], 2)
        self.assertEqual(self.keymap.read_bytes(), before)
        code, result = self.run_cli()
        self.assertEqual(code, 0, result)
        self.assertEqual(Path(result["manifest"]), self.manifest)
        self.assertEqual(Path(result["backup"]).read_bytes(), before)
        after = self.keymap.read_bytes()
        self.assertTrue(after.startswith(b"\xef\xbb\xbf// user comment\r\n"))
        self.assertIn(b"/* keep */", after)
        self.assertIn(b'"args":{"text":"// text, }",},},\r\n', after)
        rules = cfg.parse_jsonc(after.decode("utf-8-sig"))[0]
        self.assertEqual(rules, [
            {"key": "ctrl+k", "command": "chatgpt.addToThread"},
            {"key": "alt+k", "command": "-other.command"},
            cfg.BINDING,
            {"key": "shift+alt+k", "command": "other.command", "args": {"text": "// text, }"}},
        ])
        self.assertEqual(self.run_cli("--check")[0], 0)
        self.assertNotIn("backup", self.run_cli()[1])
        self.assertEqual(self.keymap.read_bytes(), after)

    def test_prioritizes_claude_over_later_editor_binding_and_preserves_it(self):
        conflict = {"key": "Alt+K Alt+X", "command": "custom", "when": "editorTextFocus"}
        before = json.dumps([cfg.BINDING, conflict]).encode()
        after = cfg.prepare_keymap(before)
        self.assertEqual(cfg.parse_jsonc(after.decode())[0], [conflict, cfg.BINDING])
        self.assertEqual(cfg.prepare_keymap(after), after)

    def test_can_create_binding_when_no_entries_remain(self):
        samples = (None, b"// comment", b"[]", b'[{"key":"alt+k","command":"chatgpt.addToThread"}]')
        for before in samples:
            with self.subTest(before=before):
                after = cfg.prepare_keymap(before)
                self.assertEqual(cfg.parse_jsonc(after.decode())[0], [cfg.BINDING])

    def test_invalid_jsonc_or_missing_command_leaves_keymap_intact(self):
        invalid = b"[/* unterminated"
        self.set_keymap(invalid)
        self.assertEqual(self.run_cli()[0], 1)
        self.assertEqual(self.keymap.read_bytes(), invalid)
        self.set_keymap(b"[]")
        self.manifest.write_text('{"publisher":"anthropic","name":"claude-code"}', encoding="utf-8")
        self.assertEqual(self.run_cli()[0], 1)
        self.assertEqual(list(self.keymap.parent.iterdir()), [self.keymap])
        self.assertEqual(self.keymap.read_bytes(), b"[]")


if __name__ == "__main__":
    unittest.main()
