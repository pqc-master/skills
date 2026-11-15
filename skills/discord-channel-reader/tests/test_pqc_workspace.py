"""Project archive safety and complete-source round-trip regression tests."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pqc_workspace as W


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="pqc-workspace-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "main.py").write_text("print('hello')\n")
        self.archive = self.root / "sourcecode.zip"
        self.output = self.root / "unpacked"

    def make_zip(self, names):
        with zipfile.ZipFile(self.archive, "w") as archive:
            for name in names:
                archive.writestr(name, b"source")

    def test_complete_project_round_trip_keeps_assets_lockfiles_empty_dirs_and_exec(self):
        (self.project / ".github").mkdir()
        (self.project / ".github/workflow.yml").write_text("name: test\n")
        (self.project / "requirements.lock").write_text("dependency==1\n")
        (self.project / "assets").mkdir()
        (self.project / "assets/data.bin").write_bytes(bytes(range(256)))
        (self.project / "uploads").mkdir()
        (self.project / "run.sh").write_text("#!/bin/sh\nexit 0\n")
        (self.project / "run.sh").chmod(0o755)
        packed = W.pack_project(self.project, self.archive)
        extracted = W.extract_archive(self.archive, self.output)
        self.assertEqual(packed["archive_sha256"], extracted["archive_sha256"])
        self.assertEqual(packed["file_count"], 5)
        for name in ("main.py", ".github/workflow.yml", "requirements.lock", "assets/data.bin", "run.sh"):
            self.assertEqual((self.project / name).read_bytes(), (self.output / name).read_bytes())
        self.assertTrue((self.output / "uploads").is_dir())
        if os.name == "posix":
            self.assertTrue((self.output / "run.sh").stat().st_mode & 0o111)
        manifest = json.loads(Path(packed["manifest_path"]).read_text())
        for entry in manifest["files"]:
            self.assertEqual(entry["sha256"], hashlib.sha256((self.output / entry["path"]).read_bytes()).hexdigest())

    def test_exclusions_are_listed_but_build_and_dist_sources_remain(self):
        for name in (".git", ".venv", "node_modules", "build", "dist"):
            (self.project / name).mkdir()
            (self.project / name / "file.txt").write_text("content")
        (self.project / ".env").write_text("DISCORD_BOT_TOKEN=synthetic")
        (self.project / ".env.example").write_text("DISCORD_BOT_TOKEN=\n")
        result = W.pack_project(self.project, self.archive)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertIn("build/file.txt", archive.namelist())
            self.assertIn("dist/file.txt", archive.namelist())
            self.assertIn(".env.example", archive.namelist())
            self.assertNotIn(".env", archive.namelist())
            self.assertNotIn(".git/file.txt", archive.namelist())
        self.assertEqual({x["path"] for x in result["excluded"]}, {".env", ".git/", ".venv/", "node_modules/"})

    def test_unchanged_snapshot_has_stable_archive_hash(self):
        first = W.pack_project(self.project, self.archive)
        second = W.pack_project(self.project, self.root / "second.zip")
        self.assertEqual(first["archive_sha256"], second["archive_sha256"])

    def test_private_key_blocks_pack_before_creating_submission(self):
        (self.project / "key.pem").write_text("-----BEGIN PRIVATE KEY-----\nsynthetic\n")
        with self.assertRaises(W.WorkspaceError):
            W.pack_project(self.project, self.archive)
        self.assertFalse(self.archive.exists())

    def test_existing_output_and_manifest_are_not_overwritten(self):
        self.archive.write_bytes(b"keep")
        with self.assertRaises(W.WorkspaceError):
            W.pack_project(self.project, self.archive)
        self.assertEqual(self.archive.read_bytes(), b"keep")
        self.archive.unlink()
        sidecar = Path(str(self.archive) + ".manifest.json")
        sidecar.write_bytes(b"keep manifest")
        with self.assertRaises(W.WorkspaceError):
            W.pack_project(self.project, self.archive)
        self.assertFalse(self.archive.exists())
        self.assertEqual(sidecar.read_bytes(), b"keep manifest")

    def test_output_inside_project_is_refused(self):
        with self.assertRaises(W.WorkspaceError):
            W.pack_project(self.project, self.project / "output.zip")

    def test_unsafe_paths_rejected_before_output_exists(self):
        for name in ("../escape", "/absolute", "C:/escape", "folder\\escape", "a/../escape", "NUL.txt", "a/trailing. "):
            with self.subTest(name=name):
                self.make_zip([name])
                with self.assertRaises(W.WorkspaceError):
                    W.extract_archive(self.archive, self.output)
                self.assertFalse(self.output.exists())

    def test_duplicate_case_and_unicode_parent_collisions_rejected(self):
        for names in (("A.txt", "a.txt"), ("DIR/a.txt", "dir/b.txt"), ("é/a", "e\u0301/b"), ("a", "a/b")):
            with self.subTest(names=names):
                self.make_zip(names)
                with self.assertRaises(W.WorkspaceError):
                    W.extract_archive(self.archive, self.output)
                self.assertFalse(self.output.exists())

    def test_symlink_zip_entry_cannot_escape(self):
        item = zipfile.ZipInfo("link")
        item.create_system = 3
        item.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr(item, "../outside")
        with self.assertRaises(W.WorkspaceError):
            W.extract_archive(self.archive, self.output)
        self.assertFalse(self.output.exists())

    def test_project_symlink_is_not_followed(self):
        outside = self.root / "private.txt"
        outside.write_text("synthetic secret")
        try:
            (self.project / "link").symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links unavailable")
        with self.assertRaises(W.WorkspaceError):
            W.pack_project(self.project, self.archive)
        self.assertFalse(self.archive.exists())

    def test_declared_size_and_entry_count_limits_precede_extraction(self):
        self.make_zip(["a", "b"])
        for limit, value in (("MAX_FILES", 1), ("MAX_FILE_BYTES", 1), ("MAX_TOTAL_BYTES", 1)):
            with self.subTest(limit=limit), mock.patch.object(W, limit, value):
                with self.assertRaises(W.WorkspaceError):
                    W.extract_archive(self.archive, self.output)
                self.assertFalse(self.output.exists())

    def test_corrupt_content_fails_without_publishing_partial_output(self):
        self.make_zip(["main.py"])
        self.archive.write_bytes(self.archive.read_bytes().replace(b"source", b"broken", 1))
        with self.assertRaises(zipfile.BadZipFile):
            W.extract_archive(self.archive, self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(Path(str(self.output) + ".extraction.json").exists())

    def test_existing_extract_directory_is_preserved(self):
        self.make_zip(["main.py"])
        self.output.mkdir()
        (self.output / "keep").write_text("keep")
        with self.assertRaises(W.WorkspaceError):
            W.extract_archive(self.archive, self.output)
        self.assertEqual((self.output / "keep").read_text(), "keep")

    def test_manifest_failure_removes_only_new_archive(self):
        with mock.patch.object(W, "_write_manifest", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                W.pack_project(self.project, self.archive)
        self.assertFalse(self.archive.exists())
        self.assertTrue((self.project / "main.py").exists())


if __name__ == "__main__":
    unittest.main()
