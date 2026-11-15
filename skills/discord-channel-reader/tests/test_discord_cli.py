"""Offline command dispatch and bundled-skill installation checks."""
import contextlib
import hashlib
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock
import urllib.request


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
with mock.patch.object(sys, "path", [str(SCRIPTS)] + sys.path):
    spec = importlib.util.spec_from_file_location("discord_cli_test_subject", SCRIPTS / "discord_cli.py")
    C = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(C)
    R = importlib.import_module("desktop_runtime")


class IsolatedCLITest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="discord-cli-test-")
        self.addCleanup(temporary.cleanup)
        self.scratch = Path(temporary.name)
        # Windows/OpenSSL needs its OS paths even when application credentials are isolated.
        system_environment = {key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ}
        for patcher in (
            mock.patch.object(sys, "path", [str(SCRIPTS)] + sys.path),
            mock.patch.dict(os.environ, system_environment, clear=True),
            mock.patch.object(urllib.request.OpenerDirector, "open", side_effect=AssertionError("No network permitted")),
            mock.patch.object(socket, "create_connection", side_effect=AssertionError("No network permitted")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


class CLIDispatchTests(IsolatedCLITest):
    def test_read_publish_and_setup_dispatch_without_implicit_actions(self):
        for command, module_name, args in (
            ("read", "discord_reader", ["channels"]),
            ("publish", "discord_publish", ["preview", "--channel-id", "123", "--text", "안내"]),
            ("setup", "discord_setup", ["--skip-publish"]),
            ("submit", "discord_submit", ["preview", "--channel-id", "123", "--source-zip", "sourcecode.zip", "--report", "report.md"]),
        ):
            with self.subTest(command=command):
                module = types.ModuleType(module_name)
                module.main = mock.Mock(return_value=7)
                with mock.patch.dict(sys.modules, {module_name: module}), \
                        mock.patch.object(C, "install_skill", side_effect=AssertionError("Unexpected install")):
                    status = C.main([command] + args)
                self.assertEqual(status, 7)
                module.main.assert_called_once_with(args)

    def test_help_and_version_do_not_load_settings_or_install(self):
        for args in ([], ["--help"], ["--version"]):
            with self.subTest(args=args), \
                    mock.patch.object(Path, "home", side_effect=AssertionError("Must not inspect home")), \
                    mock.patch.object(C, "install_skill", side_effect=AssertionError("Unexpected install")), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(C.main(args), 0)

    def test_invalid_command_or_extra_install_arguments_never_install(self):
        for args in (["not-a-command"], ["install", "unexpected"], ["self-test", "unexpected"]):
            with self.subTest(args=args), mock.patch.object(C, "install_skill") as install, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(C.main(args), 1)
                install.assert_not_called()

    def test_install_failure_does_not_print_arbitrary_exception_details(self):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(C, "install_skill", side_effect=OSError("synthetic-secret-canary")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(C.main(["install"]), 1)
        self.assertNotIn("synthetic-secret-canary", out.getvalue() + err.getvalue())

    def test_self_test_is_offline_and_never_uses_user_home(self):
        real_temporary_directory = tempfile.TemporaryDirectory
        created = []
        def isolated_directory(*args, **kwargs):
            kwargs["dir"] = self.scratch
            temporary = real_temporary_directory(*args, **kwargs)
            created.append(Path(temporary.name))
            return temporary
        with mock.patch.object(Path, "home", side_effect=AssertionError("Self-test must not inspect home")), \
                mock.patch.object(C.tempfile, "TemporaryDirectory", side_effect=isolated_directory), \
                mock.patch.object(sys, "frozen", False, create=True):
            result = C.self_test()
        self.assertTrue(result["ok"])
        self.assertFalse(result["network_used"])
        self.assertFalse(result["frozen"])
        self.assertEqual(result["category_id"], "1570317863984701441")
        self.assertGreater(result["ca_count"], 0)
        self.assertTrue(created)
        self.assertTrue(all(not path.exists() for path in created))
        self.assertNotIn("offline-test-token", json.dumps(result))

    def test_source_mode_does_not_claim_to_provide_standalone_runtime(self):
        with mock.patch.object(sys, "frozen", False, create=True):
            with self.assertRaises(R.InstallError):
                R.runtime_directory()


class SkillInstallerTests(IsolatedCLITest):
    def setUp(self):
        super().setUp()
        self.payload = self.scratch / "payload"
        self.runtime = self.scratch / "runtime"
        self.target = self.scratch / "installed" / "discord-channel-reader"
        (self.payload / "scripts").mkdir(parents=True)
        (self.payload / "assets").mkdir()
        self.runtime.mkdir()
        self.executable_name = "pqc-discord.exe" if sys.platform == "win32" else "pqc-discord"
        (self.payload / "SKILL.md").write_text("# Synthetic skill\n", encoding="utf-8")
        (self.payload / "scripts" / "example.py").write_text("print('version one')\n", encoding="utf-8")
        (self.runtime / self.executable_name).write_bytes(b"synthetic executable")
        (self.runtime / "_internal").mkdir()
        (self.runtime / "_internal" / "library.bin").write_bytes(b"synthetic library")

    def install(self):
        with mock.patch.object(Path, "home", side_effect=AssertionError("Explicit install must not inspect home")):
            return R.install_skill(target=self.target, payload=self.payload, runtime=self.runtime)

    def symlink(self, path, target, directory=False):
        try:
            path.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest("This test requires permission to create symbolic links")

    def snapshot(self):
        return {path.relative_to(self.target).as_posix(): path.read_bytes()
                for path in self.target.rglob("*") if path.is_file() and not path.is_symlink()}

    def test_install_copies_runtime_and_excludes_credentials_or_cache(self):
        (self.payload / ".env").write_text("synthetic-secret-canary")
        (self.payload / "publisher.json").write_text("synthetic-secret-canary")
        (self.payload / "__pycache__").mkdir()
        (self.payload / "__pycache__" / "example.pyc").write_bytes(b"cache")
        result = self.install()
        self.assertTrue(result["installed"])
        self.assertEqual(Path(result["path"]), self.target)
        self.assertEqual(Path(result["runtime"]), self.target / "bin" / self.executable_name)
        self.assertTrue((self.target / "SKILL.md").is_file())
        self.assertEqual((self.target / "bin" / "_internal" / "library.bin").read_bytes(), b"synthetic library")
        self.assertFalse((self.target / ".env").exists())
        self.assertFalse((self.target / "publisher.json").exists())
        self.assertFalse((self.target / "__pycache__").exists())
        manifest = json.loads((self.target / R.MANIFEST_NAME).read_text())
        self.assertIn("bin/" + self.executable_name, manifest["files"])
        self.assertNotIn("synthetic-secret-canary", json.dumps(result))

    def test_managed_update_preserves_unknown_user_files(self):
        self.install()
        note = self.target / "my-notes.txt"
        note.write_text("preserve me", encoding="utf-8")
        (self.payload / "scripts" / "example.py").write_text("print('version two')\n", encoding="utf-8")
        self.install()
        self.assertEqual(note.read_text(), "preserve me")
        self.assertIn("version two", (self.target / "scripts" / "example.py").read_text())

    def test_locally_modified_managed_file_blocks_update_before_mutation(self):
        self.install()
        (self.target / "scripts" / "example.py").write_text("local customization\n", encoding="utf-8")
        before = self.snapshot()
        (self.payload / "SKILL.md").write_text("# Updated synthetic skill\n", encoding="utf-8")
        with self.assertRaises(R.InstallError):
            self.install()
        self.assertEqual(self.snapshot(), before)

    def test_prior_approved_hash_allows_legacy_skill_upgrade(self):
        self.target.mkdir(parents=True)
        legacy_text = b"# old distributed version\n"
        (self.target / "SKILL.md").write_bytes(legacy_text)
        digest = hashlib.sha256(legacy_text).hexdigest()
        (self.payload / "assets" / "legacy-skill-hashes.json").write_text(json.dumps({"SKILL.md": [digest]}))
        self.install()
        self.assertEqual((self.target / "SKILL.md").read_bytes(), (self.payload / "SKILL.md").read_bytes())

    def test_symlink_target_is_rejected_and_external_directory_unchanged(self):
        outside = self.scratch / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep")
        self.target.parent.mkdir(parents=True)
        self.symlink(self.target, outside, directory=True)
        with self.assertRaises(R.InstallError):
            self.install()
        self.assertEqual((outside / "keep.txt").read_text(), "keep")
        self.assertEqual(sorted(path.name for path in outside.iterdir()), ["keep.txt"])

    def test_symlink_in_managed_parent_is_rejected_without_writing_through_it(self):
        outside = self.scratch / "outside"
        outside.mkdir()
        (outside / "example.py").write_text("outside data")
        self.target.mkdir(parents=True)
        self.symlink(self.target / "scripts", outside, directory=True)
        with self.assertRaises(R.InstallError):
            self.install()
        self.assertEqual((outside / "example.py").read_text(), "outside data")
        self.assertFalse((self.target / "SKILL.md").exists())

    def test_outside_payload_symlink_is_rejected(self):
        outside = self.scratch / "outside-secret"
        outside.write_text("synthetic-secret-canary")
        self.symlink(self.payload / "external-link", outside)
        with self.assertRaises(R.InstallError):
            self.install()
        self.assertFalse(self.target.exists())

    def test_internal_absolute_runtime_link_never_depends_on_removed_source(self):
        library = self.runtime / "_internal" / "library.bin"
        self.symlink(self.runtime / "linked-library", library.resolve())
        try:
            self.install()
        except R.InstallError:
            self.assertFalse(self.target.exists())
            return
        shutil.rmtree(self.runtime)
        installed = self.target / "bin" / "linked-library"
        self.assertTrue(installed.is_file(), "Installed runtime must not refer back to the extracted distribution")
        self.assertEqual(installed.read_bytes(), b"synthetic library")


if __name__ == "__main__":
    unittest.main()
