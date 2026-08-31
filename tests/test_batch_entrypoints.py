from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BATCH_FILES = (
    ROOT / "DeploySkills.bat",
    ROOT / "ClaudeSkill部署.bat",
    ROOT / "Skill一键部署.bat",
)


class BatchEntrypointTests(unittest.TestCase):
    def test_batch_files_use_windows_line_endings(self) -> None:
        for path in BATCH_FILES:
            data = path.read_bytes()
            self.assertNotIn(b"\n", data.replace(b"\r\n", b""), path.name)

    def test_compatibility_entrypoints_call_ascii_main_file(self) -> None:
        for path in BATCH_FILES[1:]:
            content = path.read_text(encoding="utf-8")
            self.assertIn("DeploySkills.bat", content)


if __name__ == "__main__":
    unittest.main()
