from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "das-ue-project-pack"
    / "pack_ue_project.py"
)
SPEC = importlib.util.spec_from_file_location("pack_ue_project", SCRIPT)
assert SPEC and SPEC.loader
pack_ue_project = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pack_ue_project)


class ExternalDlcPluginManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output_directory = Path(self.temporary_directory.name) / "202609291200_DLC_DLCAnTang"
        self.plugin_path = (
            self.output_directory
            / "Windows"
            / "DasWDS"
            / "Plugins"
            / "DLCAnTang"
            / "DLCAnTang.uplugin"
        )
        self.plugin_path.parent.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_descriptor(self, can_contain_content: bool = True) -> dict:
        descriptor = {
            "FileVersion": 3,
            "Version": 1,
            "VersionName": "1.0",
            "FriendlyName": "DLCAnTang",
            "CanContainContent": can_contain_content,
            "Installed": False,
        }
        self.plugin_path.write_text(
            json.dumps(descriptor, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return descriptor

    def test_writes_manifest_next_to_plugin_folder(self) -> None:
        descriptor = self.write_descriptor()

        manifest_path = pack_ue_project.write_external_dlc_plugin_manifest(
            self.output_directory,
            "DLCAnTang",
        )

        self.assertEqual(
            manifest_path,
            self.plugin_path.parent.parent / "DLCAnTang.upluginmanifest",
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest,
            {
                "Contents": [
                    {
                        "File": "../../../DasWDS/Plugins/DLCAnTang/DLCAnTang.uplugin",
                        "Descriptor": descriptor,
                    }
                ]
            },
        )

    def test_rejects_content_disabled_plugin(self) -> None:
        self.write_descriptor(can_contain_content=False)

        with self.assertRaisesRegex(
            pack_ue_project.PackageError,
            "CanContainContent 必须为 true",
        ):
            pack_ue_project.write_external_dlc_plugin_manifest(
                self.output_directory,
                "DLCAnTang",
            )

    def test_dlc_parameters_drop_embedded_plugin_manifest_option(self) -> None:
        release_root = self.output_directory.parent / pack_ue_project.RELEASE_DIRECTORY_NAME
        metadata = (
            release_root
            / "202609291100"
            / "Win64"
            / pack_ue_project.RELEASE_METADATA_RELATIVE
        )
        metadata.parent.mkdir(parents=True)
        metadata.write_bytes(b"registry")
        parameters = {
            "DLCPakPluginFile": "D:/wrong/DLCAnTang.upluginmanifest",
            "dlcname": "old-name",
        }

        pack_ue_project.apply_release_parameters(
            parameters,
            self.output_directory.parent,
            self.output_directory,
            "Win64",
            True,
            "DLCAnTang",
        )

        self.assertNotIn("DLCPakPluginFile", parameters)
        self.assertEqual(parameters["dlcname"], "DLCAnTang")


if __name__ == "__main__":
    unittest.main()
