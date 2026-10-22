"""Hosted verification identifies changed/missing program files without exposing secrets."""

import json
import tempfile
import unittest
from pathlib import Path

from tier_release import build_info, manifest


class BuildIdentificationCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "data").mkdir()
        (self.root / "requirements.txt").write_text("discord.py==2.7.1\n")
        (self.root / "bot.py").write_text("print('synthetic program')\n")
        (self.root / "data/tier_build.json").write_text(
            json.dumps(manifest("test-release", self.root))
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_matching_package_is_identified_without_reading_env_or_database_files(self):
        before = build_info(self.root)
        (self.root / ".env").write_text("SYNTHETIC_SECRET=not-a-real-secret")
        (self.root / "state").mkdir()
        (self.root / "state/tierlist.sqlite3").write_bytes(b"artificial private state")
        after = build_info(self.root)
        self.assertEqual(before, after)
        self.assertTrue(after["verified"])
        self.assertEqual(after["version"], "test-release")

    def test_modified_file_reports_its_name_without_its_contents(self):
        (self.root / "bot.py").write_text("SYNTHETIC_SECRET_CONTENT")
        info = build_info(self.root)
        self.assertFalse(info["verified"])
        self.assertEqual(info["changed_files"], ["bot.py"])
        self.assertNotIn("SYNTHETIC_SECRET_CONTENT", json.dumps(info))

    def test_partial_upload_and_missing_manifest_are_not_reported_as_valid(self):
        (self.root / "bot.py").unlink()
        self.assertFalse(build_info(self.root)["verified"])
        self.assertEqual(build_info(self.root)["changed_files"], ["bot.py"])
        (self.root / "data/tier_build.json").unlink()
        self.assertFalse(build_info(self.root)["verified"])

    def test_manifest_cannot_make_verifier_read_paths_outside_the_program(self):
        path = self.root / "data/tier_build.json"
        data = json.loads(path.read_text())
        data["files"] = {"../outside.txt": "bad"}
        path.write_text(json.dumps(data))
        self.assertFalse(build_info(self.root)["verified"])
        self.assertEqual(build_info(self.root)["files_checked"], 0)
