from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy_claude_skills.py"
SPEC = importlib.util.spec_from_file_location("deploy_skills", SCRIPT)
assert SPEC and SPEC.loader
deploy_skills = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy_skills)


class TargetConfigurationTests(unittest.TestCase):
    def test_workbuddy_user_skill_directory_is_configured(self) -> None:
        targets = dict(deploy_skills.TARGET_ROOTS)

        self.assertEqual(
            targets["WorkBuddy"],
            Path.home() / ".workbuddy-ai" / "skills",
        )
        self.assertEqual(
            targets["WorkBuddy Compat"],
            Path.home() / ".codebuddy" / "skills",
        )
        self.assertEqual(
            targets["WorkBuddy Legacy"],
            Path.home() / ".workbuddy" / "skills",
        )

    def test_spatial_mind_custom_skill_directory_is_configured(self) -> None:
        app_data = Path("D:/users/test/AppData/Roaming")
        with patch.dict(deploy_skills.os.environ, {"APPDATA": str(app_data)}):
            roots = dict(deploy_skills.build_target_roots())

        self.assertEqual(
            roots["SpatialMind"],
            app_data / "spatial-mind-desktop" / "skills" / "custom",
        )

    def test_workbuddy_config_dir_honours_environment_override(self) -> None:
        keys = ("WORKBUDDY_CONFIG_DIR", "CODEBUDDY_CONFIG_DIR")
        for key in keys:
            with self.subTest(key=key):
                overrides = dict.fromkeys(keys, "")
                overrides[key] = str(Path("D:/custom-config"))
                with patch.dict(deploy_skills.os.environ, overrides):
                    self.assertEqual(
                        deploy_skills.workbuddy_config_dir(),
                        Path("D:/custom-config"),
                    )

    def test_duplicate_target_roots_are_collapsed(self) -> None:
        overrides = {
            "WORKBUDDY_CONFIG_DIR": str(Path.home() / ".workbuddy"),
            "CODEBUDDY_CONFIG_DIR": "",
        }
        with patch.dict(deploy_skills.os.environ, overrides):
            roots = deploy_skills.build_target_roots()

        paths = [root for _, root in roots]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertNotIn("WorkBuddy Legacy", dict(roots))


class DeploySkillsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.shared = self.root / "sources" / "shared"
        self.claude = self.root / "sources" / "claude"
        self.targets = (
            ("Claude", self.root / "targets" / ".claude" / "skills"),
            ("Codex", self.root / "targets" / ".agents" / "skills"),
            ("WorkBuddy", self.root / "targets" / ".workbuddy-ai" / "skills"),
            (
                "WorkBuddy Compat",
                self.root / "targets" / ".codebuddy" / "skills",
            ),
            (
                "WorkBuddy Legacy",
                self.root / "targets" / ".workbuddy" / "skills",
            ),
            (
                "SpatialMind",
                self.root
                / "targets"
                / "spatial-mind-desktop"
                / "skills"
                / "custom",
            ),
        )
        self.patchers = (
            patch.object(deploy_skills, "SHARED_SOURCE_ROOT", self.shared),
            patch.object(deploy_skills, "CLAUDE_SOURCE_ROOT", self.claude),
            patch.object(deploy_skills, "TARGET_ROOTS", self.targets),
        )
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary_directory.cleanup()

    def create_skill(self, source_root: Path, name: str) -> Path:
        skill = source_root / name
        (skill / "agents").mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: test\n---\n",
            encoding="utf-8",
        )
        (skill / "agents" / "openai.yaml").write_text(
            "interface:\n  display_name: test\n",
            encoding="utf-8",
        )
        (skill / "payload.txt").write_text("payload", encoding="utf-8")
        return skill

    def create_broken_skill(self, source_root: Path, name: str, body: str) -> Path:
        skill = source_root / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(body, encoding="utf-8")
        return skill

    def run_main(self, *arguments: str) -> int:
        argv = ["deploy_claude_skills.py", *arguments]
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(
            io.StringIO()
        ), contextlib.redirect_stderr(io.StringIO()):
            return deploy_skills.main()

    def assertInstalled(self, name: str) -> None:
        for product, target_root in self.targets:
            self.assertTrue(
                (target_root / name / "payload.txt").is_file(),
                f"{product} 缺少 {name}",
            )

    def assertNotInstalled(self, name: str) -> None:
        for product, target_root in self.targets:
            self.assertFalse((target_root / name).exists(), f"{product} 多出 {name}")

    def test_shared_skill_installs_to_all_products(self) -> None:
        name = "das-shared-test"
        self.create_skill(self.shared, name)

        deploy_skills.install(name)

        for product, target_root in self.targets:
            target = target_root / name
            self.assertEqual(
                (target / "payload.txt").read_text(encoding="utf-8"),
                "payload",
            )
            self.assertEqual((target / "agents").exists(), product == "Codex")

    def test_claude_only_skill_is_removed_from_other_products(self) -> None:
        name = "das-claude-test"
        self.create_skill(self.claude, name)
        for _, target_root in self.targets:
            stale = target_root / name
            stale.mkdir(parents=True)
            (stale / "stale.txt").write_text("stale", encoding="utf-8")

        deploy_skills.install(name)

        self.assertTrue((self.targets[0][1] / name / "payload.txt").is_file())
        for _, target_root in self.targets[1:]:
            self.assertFalse((target_root / name).exists())

    def test_uninstall_removes_skill_from_all_products(self) -> None:
        name = "das-uninstall-test"
        self.create_skill(self.shared, name)
        deploy_skills.install(name)

        deploy_skills.uninstall(name)

        for _, target_root in self.targets:
            self.assertFalse((target_root / name).exists())

    def test_missing_skill_is_skipped_without_failing(self) -> None:
        self.create_skill(self.shared, "das-good")

        exit_code = self.run_main("--action", "install", "das-good", "das-absent")

        self.assertEqual(exit_code, 0)
        self.assertInstalled("das-good")
        self.assertNotInstalled("das-absent")

    def test_broken_frontmatter_is_skipped_and_reported_as_failure(self) -> None:
        self.create_skill(self.shared, "das-good")
        self.create_broken_skill(self.shared, "das-broken", "没有 frontmatter\n")

        exit_code = self.run_main("--action", "install")

        self.assertEqual(exit_code, 1)
        self.assertInstalled("das-good")
        self.assertNotInstalled("das-broken")

    def test_name_mismatch_is_skipped_and_reported_as_failure(self) -> None:
        self.create_skill(self.shared, "das-good")
        self.create_broken_skill(
            self.shared,
            "das-mismatch",
            "---\nname: das-other\ndescription: test\n---\n",
        )

        exit_code = self.run_main("--action", "install")

        self.assertEqual(exit_code, 1)
        self.assertInstalled("das-good")
        self.assertNotInstalled("das-mismatch")

    def test_duplicate_source_is_skipped_and_reported_as_failure(self) -> None:
        self.create_skill(self.shared, "das-good")
        self.create_skill(self.shared, "das-duplicate")
        self.create_skill(self.claude, "das-duplicate")

        exit_code = self.run_main("--action", "install")

        self.assertEqual(exit_code, 1)
        self.assertInstalled("das-good")
        self.assertNotInstalled("das-duplicate")

    def test_empty_source_roots_succeed_without_changes(self) -> None:
        self.shared.mkdir(parents=True)
        self.claude.mkdir(parents=True)

        self.assertEqual(deploy_skills.available_skills(), [])
        self.assertEqual(self.run_main("--action", "install"), 0)


if __name__ == "__main__":
    unittest.main()
