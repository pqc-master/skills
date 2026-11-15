"""Offline multi-skill installation checks with isolated synthetic resources."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import desktop_runtime as R


class BundleInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="pqc-bundle-test-")
        self.addCleanup(temporary.cleanup)
        self.scratch = Path(temporary.name)
        self.payload = self.scratch / "payload"
        self.target = self.scratch / "installed"
        self.runtime = self.scratch / "runtime"
        self.runtime.mkdir()
        self.executable_name = "pqc-discord.exe" if sys.platform == "win32" else "pqc-discord"
        (self.runtime / self.executable_name).write_bytes(b"synthetic runtime")
        for name in R.SKILL_NAMES:
            directory = self.payload / name
            (directory / "references").mkdir(parents=True)
            (directory / "SKILL.md").write_text("# " + name + "\n", encoding="utf-8")
            (directory / "references" / "guide.md").write_text("version one\n", encoding="utf-8")

    def install(self, **kwargs):
        with mock.patch.object(Path, "home", side_effect=AssertionError("Explicit target must not inspect user home")):
            return R.install_bundle(target_directory=self.target, payload_directory=self.payload,
                                    runtime=self.runtime, **kwargs)

    def snapshot(self):
        return {path.relative_to(self.target).as_posix(): path.read_bytes()
                for path in self.target.rglob("*") if path.is_file() and not path.is_symlink()}

    def change_payload(self):
        for name in R.SKILL_NAMES:
            (self.payload / name / "references" / "guide.md").write_text("version two\n", encoding="utf-8")

    def symlink(self, path, target):
        try:
            path.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Platform does not permit test symlinks")

    def test_installs_five_siblings_and_only_one_runtime(self):
        result = self.install()
        self.assertTrue(result["installed"])
        self.assertEqual(result["skills"], list(R.SKILL_NAMES))
        for name in R.SKILL_NAMES:
            target = self.target / name
            self.assertTrue((target / "SKILL.md").is_file())
            self.assertTrue((target / R.MANIFEST_NAME).is_file())
            self.assertEqual((target / "bin").exists(), name == R.SKILL_NAME)
        self.assertEqual(Path(result["runtime"]).read_bytes(), b"synthetic runtime")

    def test_missing_last_skill_blocks_every_install_before_mutation(self):
        (self.payload / R.SKILL_NAMES[-1] / "SKILL.md").unlink()
        with self.assertRaises(R.InstallError):
            self.install()
        self.assertFalse(self.target.exists())

    def test_last_skill_local_change_blocks_updates_to_all_siblings(self):
        self.install()
        local = self.target / R.SKILL_NAMES[-1] / "SKILL.md"
        local.write_text("user edit\n")
        before = self.snapshot()
        self.change_payload()
        with mock.patch.object(R, "_stage_plan", side_effect=AssertionError("No staging before all preflight passes")):
            with self.assertRaises(R.InstallError):
                self.install()
        self.assertEqual(self.snapshot(), before)

    def test_successful_update_preserves_unmanaged_files_in_every_skill(self):
        self.install()
        for name in R.SKILL_NAMES:
            (self.target / name / "personal.txt").write_text("keep " + name)
        self.change_payload()
        self.install()
        for name in R.SKILL_NAMES:
            self.assertEqual((self.target / name / "personal.txt").read_text(), "keep " + name)
            self.assertEqual((self.target / name / "references" / "guide.md").read_text(), "version two\n")

    def test_second_replacement_failure_restores_every_existing_skill(self):
        self.install()
        before = self.snapshot()
        self.change_payload()
        original_rename = Path.rename
        failed = False
        def rename(path, destination):
            nonlocal failed
            if path.name.startswith(".pqc-install-") and Path(destination) == self.target / R.SKILL_NAMES[1] and not failed:
                failed = True
                raise OSError("synthetic failure")
            return original_rename(path, destination)
        with mock.patch.object(Path, "rename", rename):
            with self.assertRaises(R.InstallError):
                self.install()
        self.assertTrue(failed)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(any(path.name.startswith(".pqc-") for path in self.target.iterdir()))

    def test_new_install_failure_removes_all_partial_skills(self):
        original_rename = Path.rename
        def rename(path, destination):
            if path.name.startswith(".pqc-install-") and Path(destination) == self.target / R.SKILL_NAMES[2]:
                raise OSError("synthetic failure")
            return original_rename(path, destination)
        with mock.patch.object(Path, "rename", rename):
            with self.assertRaises(R.InstallError):
                self.install()
        self.assertEqual(list(self.target.iterdir()), [])

    def test_later_skill_symlink_target_is_rejected_before_any_change(self):
        self.install()
        outside = self.scratch / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("outside unchanged")
        target = self.target / R.SKILL_NAMES[-1]
        moved = self.scratch / "saved-last-skill"
        target.rename(moved)
        self.symlink(target, outside)
        before = self.snapshot()
        self.change_payload()
        with self.assertRaises(R.InstallError):
            self.install()
        self.assertTrue(target.is_symlink())
        self.assertEqual((outside / "keep.txt").read_text(), "outside unchanged")
        self.assertEqual(self.snapshot(), before)

    def test_source_install_never_resolves_or_copies_a_runtime(self):
        with mock.patch.object(R, "runtime_directory", side_effect=AssertionError("Source install has no frozen runtime")):
            result = self.install(include_runtime=False)
        self.assertIsNone(result["runtime"])
        self.assertEqual(len(result["skills"]), 5)
        self.assertFalse((self.target / R.SKILL_NAME / "bin").exists())

    def test_default_app_install_uses_the_complete_bundle(self):
        with mock.patch.object(R, "install_bundle", return_value={"installed": True, "skills": list(R.SKILL_NAMES)}) as install:
            result = R.install_skill()
        install.assert_called_once_with()
        self.assertEqual(len(result["skills"]), 5)

    def test_source_update_does_not_mix_new_instructions_with_old_binary(self):
        self.install()
        before = self.snapshot()
        self.change_payload()
        with self.assertRaises(R.InstallError):
            self.install(include_runtime=False)
        self.assertEqual(self.snapshot(), before)

    def test_malformed_prior_manifest_blocks_without_raw_value_disclosure(self):
        self.install()
        manifest = self.target / R.SKILL_NAMES[-1] / R.MANIFEST_NAME
        manifest.write_text(json.dumps({"files": {"SKILL.md": {"secret": "synthetic-canary"}}}))
        before = self.snapshot()
        with self.assertRaises(R.InstallError) as caught:
            self.install()
        self.assertNotIn("synthetic-canary", str(caught.exception))
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
