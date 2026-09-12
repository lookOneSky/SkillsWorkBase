from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "das-skillupdate"
    / "update_skills.py"
)
SPEC = importlib.util.spec_from_file_location("update_skills", SCRIPT)
assert SPEC and SPEC.loader
update_skills = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update_skills)


class UpdateSkillsDeployTests(unittest.TestCase):
    def test_shared_then_mcp_skills_are_deployed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shared_script = repository / update_skills.DEPLOY_SCRIPT
            mcp_script = repository / update_skills.MCP_DEPLOY_SCRIPT
            shared_script.parent.mkdir(parents=True)
            shared_script.touch()
            mcp_script.touch()

            with patch.object(update_skills, "run") as run:
                update_skills.deploy(repository)

            self.assertEqual(
                run.call_args_list,
                [
                    call(
                        [
                            sys.executable,
                            str(shared_script),
                            "--action",
                            "install",
                        ],
                        cwd=repository,
                    ),
                    call([sys.executable, str(mcp_script)], cwd=repository),
                ],
            )

    def test_missing_mcp_deployer_stops_before_deployment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory)
            shared_script = repository / update_skills.DEPLOY_SCRIPT
            shared_script.parent.mkdir(parents=True)
            shared_script.touch()

            with patch.object(update_skills, "run") as run:
                with self.assertRaises(FileNotFoundError):
                    update_skills.deploy(repository)

            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
