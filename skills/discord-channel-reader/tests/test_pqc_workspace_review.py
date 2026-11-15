"""Independent regressions for project ZIP completeness and portable exclusions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pqc_workspace as W


class WorkspaceReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="pqc-archive-review-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "main.py").write_text("print('project')\n")
        self.archive = self.root / "sourcecode.zip"
        self.output = self.root / "unpacked"

    def test_unreadable_subdirectory_cannot_be_silently_omitted(self):
        restricted = self.project / "required-assets"
        restricted.mkdir()
        (restricted / "schema.json").write_text('{"required":true}')
        real_scandir = W.os.scandir
        def scandir(path):
            if Path(path) == restricted:
                raise PermissionError("synthetic permission denial")
            return real_scandir(path)
        with mock.patch.object(W.os, "scandir", side_effect=scandir):
            with self.assertRaises(W.WorkspaceError):
                W.pack_project(self.project, self.archive)
        self.assertFalse(self.archive.exists())
        self.assertFalse(Path(str(self.archive) + ".manifest.json").exists())

    def test_windows_case_equivalent_local_settings_are_excluded(self):
        for name in (".ENV", "Publisher.JSON", ".NPMRC"):
            (self.project / name).write_text("synthetic-credential-canary")
        (self.project / ".GIT").mkdir()
        (self.project / ".GIT" / "config").write_text("synthetic-credential-canary")
        result = W.pack_project(self.project, self.archive)
        with zipfile.ZipFile(self.archive) as archive:
            payloads = [archive.read(name) for name in archive.namelist() if not name.endswith("/")]
        self.assertTrue(all(b"synthetic-credential-canary" not in payload for payload in payloads))
        self.assertEqual({entry["path"] for entry in result["excluded"]}, {".ENV", "Publisher.JSON", ".NPMRC", ".GIT/"})

    def test_embedded_nul_name_is_rejected_despite_zipinfo_filename_truncation(self):
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("aXb.txt", b"content")
        self.archive.write_bytes(self.archive.read_bytes().replace(b"aXb.txt", b"a\x00b.txt"))
        with self.assertRaises(W.WorkspaceError):
            W.extract_archive(self.archive, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
