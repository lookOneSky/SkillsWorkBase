from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SCRIPT = SCRIPTS / "deploy_spatialmind_mcp_skills.py"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("deploy_spatialmind_mcp_skills", SCRIPT)
assert SPEC and SPEC.loader
deploy_mcp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy_mcp)


class DeploySpatialMindMcpSkillsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "sources" / "MCP"
        self.target = self.root / "target" / "skills" / "custom"
        self.patcher = patch.object(deploy_mcp, "MCP_SOURCE_ROOT", self.source)
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        self.temporary_directory.cleanup()

    def create_skill(self, name: str, *, metadata_name: str | None = None) -> Path:
        skill = self.source / name
        (skill / "agents").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {metadata_name or name}\ndescription: test\n---\n",
            encoding="utf-8",
        )
        (skill / "agents" / "openai.yaml").write_text(
            "interface:\n  display_name: test\n",
            encoding="utf-8",
        )
        (skill / "payload.txt").write_text("mcp", encoding="utf-8")
        (skill / f"{name}.zip").write_bytes(b"packaged copy")
        return skill

    def run_main(self, *arguments: str) -> int:
        argv = [
            "deploy_spatialmind_mcp_skills.py",
            "--target-dir",
            str(self.target),
            *arguments,
        ]
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(
            io.StringIO()
        ), contextlib.redirect_stderr(io.StringIO()):
            return deploy_mcp.main()

    def test_all_mcp_skills_are_installed_without_codex_metadata(self) -> None:
        self.create_skill("das-one")
        self.create_skill("das-two")

        self.assertEqual(self.run_main(), 0)

        for name in ("das-one", "das-two"):
            installed = self.target / name
            self.assertEqual(
                (installed / "payload.txt").read_text(encoding="utf-8"),
                "mcp",
            )
            self.assertFalse((installed / "agents").exists())
            self.assertFalse((installed / f"{name}.zip").exists())

    def test_existing_spatialmind_skill_is_replaced(self) -> None:
        self.create_skill("das-replace")
        stale = self.target / "das-replace"
        stale.mkdir(parents=True)
        (stale / "stale.txt").write_text("stale", encoding="utf-8")

        self.assertEqual(self.run_main(), 0)

        self.assertFalse((stale / "stale.txt").exists())
        self.assertTrue((stale / "payload.txt").is_file())

    def test_invalid_skill_does_not_block_valid_skill(self) -> None:
        self.create_skill("das-good")
        self.create_skill("das-bad", metadata_name="das-other")

        self.assertEqual(self.run_main(), 1)

        self.assertTrue((self.target / "das-good" / "payload.txt").is_file())
        self.assertFalse((self.target / "das-bad").exists())

    def test_named_missing_skill_is_skipped(self) -> None:
        self.source.mkdir(parents=True)

        self.assertEqual(self.run_main("das-missing"), 0)
        self.assertFalse((self.target / "das-missing").exists())


if __name__ == "__main__":
    unittest.main()
