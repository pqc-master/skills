"""Offline attachment download contracts; no credentials or live Discord traffic."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import urllib.error

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("discord_download_subject", SCRIPTS / "discord_download.py")
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)

GUILD = D.reader.DEFAULT_GUILD_ID
CATEGORY = D.reader.DEFAULT_CATEGORY_ID
CHANNEL = "1571489400854937640"
THREAD = "1571489400854937641"
MESSAGE = "1571505072066789386"
FIRST = "1571505072066789387"
SECOND = "1571505072066789388"
SECRET = "synthetic_signed_cdn_secret_canary"
BOT = "1544609357185028106"


def attachment(identifier=FIRST, filename="problem_source.zip", data=b"archive", channel=CHANNEL):
    return {"id": identifier, "filename": filename, "size": len(data),
            "url": f"https://cdn.discordapp.com/attachments/{channel}/{identifier}/file.bin?ex=abcd&is=abcd&hm={SECRET}"}


class FakeReader:
    def __init__(self, attachments=None, thread=False):
        self.channels = {CHANNEL: {"id": CHANNEL, "guild_id": GUILD, "parent_id": CATEGORY, "type": 0}}
        self.channel_id = THREAD if thread else CHANNEL
        if thread:
            self.channels[THREAD] = {"id": THREAD, "guild_id": GUILD, "parent_id": CHANNEL, "type": 11}
        self.message = {"id": MESSAGE, "channel_id": self.channel_id,
                        "attachments": attachments if attachments is not None else [attachment(channel=self.channel_id)]}
        self.permissions = D.reader.VIEW_CHANNEL | D.reader.READ_HISTORY
        self.api = self
        self.requests = []
        self.checked = []

    def identify(self):
        return {"id": BOT, "bot": True}

    def channel(self, identifier):
        return self.channels[identifier]

    def effective_permissions(self, channel):
        self.checked.append(channel["id"])
        return self.permissions

    def get(self, route):
        self.requests.append(route)
        if route != f"/channels/{self.channel_id}/messages/{MESSAGE}":
            raise AssertionError("Unexpected message lookup")
        return copy.deepcopy(self.message)


class Response(io.BytesIO):
    def __init__(self, data, url, headers=None, status=200):
        super().__init__(data)
        self.url = url
        self.headers = headers if headers is not None else {"Content-Length": str(len(data))}
        self.status = status

    def geturl(self):
        return self.url


class Opener:
    def __init__(self, bodies=None, error=None, headers=None, redirect=None):
        self.bodies = list(bodies or [b"archive"])
        self.error = error
        self.headers = headers
        self.redirect = redirect
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        if self.error:
            raise self.error
        return Response(self.bodies.pop(0), self.redirect or request.full_url, self.headers)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="discord-download-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "download"
        self.client = FakeReader()
        self.opener = Opener()

    def download(self, **kwargs):
        downloader = D.AttachmentDownloader(self.client, self.opener)
        return downloader.download(self.client.channel_id, MESSAGE, self.output, **kwargs)

    def assert_no_secret(self, value):
        text = value if isinstance(value, str) else json.dumps(value)
        self.assertNotIn(SECRET, text)
        self.assertNotIn("cdn.discordapp.com", text)
        self.assertNotIn("Authorization", text)

    def test_fresh_message_download_preserves_bytes_and_records_hash(self):
        result = self.download()
        self.assertTrue(result["complete"])
        self.assertEqual(self.client.requests, [f"/channels/{CHANNEL}/messages/{MESSAGE}"])
        self.assertEqual(result["files"][0]["original_filename"], "problem_source.zip")
        path = self.output / result["files"][0]["stored_filename"]
        self.assertEqual(path.read_bytes(), b"archive")
        self.assertEqual(result["files"][0]["sha256"], hashlib.sha256(b"archive").hexdigest())
        persisted = json.loads((self.output / "download-manifest.json").read_text())
        self.assertEqual(result, persisted)
        self.assert_no_secret(result)
        if os.name == "posix":
            self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_cdn_get_never_carries_bot_authorization(self):
        self.download()
        request = self.opener.requests[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.get_header("Authorization"))
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("Accept-encoding"), "identity")

    def test_selects_only_requested_attachment_ids(self):
        self.client.message["attachments"].append(attachment(SECOND, "report.txt", b"report"))
        self.opener.bodies = [b"report"]
        result = self.download(attachment_ids=[SECOND])
        self.assertEqual([item["attachment_id"] for item in result["files"]], [SECOND])
        self.assertEqual(len(self.opener.requests), 1)

    def test_missing_or_duplicate_selected_id_prevents_network_download(self):
        for identifiers in (["999"], [FIRST, FIRST]):
            with self.subTest(ids=identifiers), self.assertRaises(D.DownloadError):
                self.download(attachment_ids=identifiers)
        self.assertEqual(self.opener.requests, [])
        self.assertFalse(self.output.exists())

    def test_threads_use_parent_permissions_but_thread_message_route(self):
        self.client = FakeReader(thread=True)
        self.client.channels[CHANNEL]["type"] = 15
        result = self.download()
        self.assertTrue(result["complete"])
        self.assertEqual(self.client.checked, [CHANNEL])
        self.assertEqual(self.client.requests, [f"/channels/{THREAD}/messages/{MESSAGE}"])

    def test_guild_category_and_read_permissions_are_enforced_before_message_lookup(self):
        changes = (("guild_id", "999"), ("parent_id", "999"), ("type", 4))
        for key, value in changes:
            with self.subTest(key=key):
                self.client = FakeReader()
                self.client.channels[CHANNEL][key] = value
                with self.assertRaises(D.DownloadError):
                    self.download()
                self.assertEqual(self.client.requests, [])
        for permission in (D.reader.VIEW_CHANNEL, D.reader.READ_HISTORY):
            self.client = FakeReader()
            self.client.permissions = permission
            with self.assertRaises(D.DownloadError):
                self.download()
            self.assertEqual(self.client.requests, [])

    def test_message_identity_mismatch_is_rejected(self):
        self.client.message["channel_id"] = "999"
        with self.assertRaises(D.DownloadError):
            self.download()
        self.assertEqual(self.opener.requests, [])

    def test_no_visible_attachments_does_not_claim_success(self):
        self.client.message["attachments"] = []
        with self.assertRaisesRegex(D.DownloadError, "Message Content intent"):
            self.download()
        self.assertFalse(self.output.exists())

    def test_unsafe_or_unrelated_cdn_urls_are_rejected_before_request(self):
        base = attachment()["url"]
        invalid = [base.replace("https:", "http:"), base.replace("cdn.discordapp.com", "evil.invalid"),
                   base.replace("cdn.discordapp.com", "cdn.discordapp.com.evil.invalid"),
                   base.replace("cdn.discordapp.com", "user@cdn.discordapp.com"),
                   base.replace("cdn.discordapp.com", "cdn.discordapp.com:8443"),
                   base.replace(CHANNEL, "999"), base.replace(FIRST, "999"),
                   base.replace("/attachments/", "/avatars/"), base + "#fragment", base + "\n"]
        for url in invalid:
            with self.subTest(url=url):
                self.client.message["attachments"][0]["url"] = url
                with self.assertRaises(D.DownloadError) as caught:
                    self.download()
                self.assert_no_secret(str(caught.exception))
        self.assertEqual(self.opener.requests, [])
        self.assertFalse(self.output.exists())

    def test_media_cdn_and_ephemeral_attachment_paths_are_accepted(self):
        self.client.message["attachments"][0]["url"] = attachment()["url"].replace("cdn.discordapp.com/attachments", "media.discordapp.net/ephemeral-attachments")
        self.assertTrue(self.download()["complete"])

    def test_unsafe_filenames_are_stored_as_portable_unique_components(self):
        names = ["../outside.zip", "C:\\outside.zip", "CON.txt", "a:b?c*.zip", "name. ", "이름.zip"]
        for index, original in enumerate(names):
            identifier = str(int(FIRST) + index)
            name = D.stored_filename(identifier, original)
            self.assertTrue(name.startswith(identifier + "-"))
            self.assertNotIn("/", name)
            self.assertNotIn("\\", name)
            self.assertFalse(any(c in name for c in ':?*"<>|'))
            self.assertFalse(name.endswith((".", " ")))
            self.assertEqual(Path(name).name, name)

    def test_duplicate_case_names_stay_distinct_by_attachment_id(self):
        self.client.message["attachments"] = [attachment(FIRST, "Source.ZIP"), attachment(SECOND, "source.zip")]
        self.opener.bodies = [b"archive", b"archive"]
        result = self.download()
        names = [item["stored_filename"].casefold() for item in result["files"]]
        self.assertEqual(len(set(names)), 2)

    def test_existing_output_is_preserved_before_any_api_request(self):
        self.output.mkdir()
        (self.output / "keep.txt").write_text("keep")
        with self.assertRaises(D.DownloadError):
            self.download()
        self.assertEqual((self.output / "keep.txt").read_text(), "keep")
        self.assertEqual(self.client.requests, [])
        self.assertEqual(self.opener.requests, [])

    def test_symlink_output_parent_is_rejected(self):
        real = self.root / "real"
        real.mkdir()
        link = self.root / "link"
        try:
            link.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation is unavailable")
        self.output = link / "download"
        with self.assertRaises(D.DownloadError):
            self.download()
        self.assertEqual(list(real.iterdir()), [])

    def test_declared_size_limits_rejected_before_network(self):
        self.client.message["attachments"][0]["size"] = D.MAX_FILE_BYTES + 1
        with self.assertRaises(D.DownloadError):
            self.download()
        self.assertEqual(self.opener.requests, [])
        self.client.message["attachments"] = [attachment(str(int(FIRST) + i)) for i in range(5)]
        for item in self.client.message["attachments"]:
            item["size"] = D.MAX_FILE_BYTES
        with self.assertRaises(D.DownloadError):
            self.download()
        self.assertEqual(self.opener.requests, [])

    def test_truncated_or_extra_body_never_accepts_partial_file(self):
        for body in (b"short", b"archiveEXTRA"):
            with self.subTest(body=body):
                self.output = self.root / ("try-" + str(len(body)))
                self.opener = Opener([body], headers={})
                result = self.download()
                self.assertFalse(result["complete"])
                self.assertEqual(result["files"], [])
                self.assertEqual([p.name for p in self.output.iterdir()], ["download-manifest.json"])

    def test_expired_cdn_url_reports_partial_failure_without_secret_or_retry(self):
        url = attachment()["url"]
        self.opener.error = urllib.error.HTTPError(url, 403, SECRET, {}, io.BytesIO(SECRET.encode()))
        result = self.download()
        self.assertFalse(result["complete"])
        self.assertIn("HTTP 403", result["error"])
        self.assertEqual(len(self.opener.requests), 1)
        self.assert_no_secret(result)

    def test_unknown_transport_error_is_sanitized(self):
        self.opener.error = OSError(attachment()["url"])
        result = self.download()
        self.assertFalse(result["complete"])
        self.assert_no_secret(result)

    def test_partial_download_preserves_completed_files_and_marks_manifest_incomplete(self):
        self.client.message["attachments"].append(attachment(SECOND, "report.txt", b"report"))
        self.opener.bodies = [b"archive", b"short"]
        self.opener.headers = {}
        result = self.download()
        self.assertFalse(result["complete"])
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual((self.output / result["files"][0]["stored_filename"]).read_bytes(), b"archive")
        self.assert_no_secret((self.output / "download-manifest.json").read_text())

    def test_redirect_response_is_not_downloaded(self):
        self.opener.redirect = "https://evil.invalid/" + SECRET
        result = self.download()
        self.assertFalse(result["complete"])
        self.assertEqual(result["files"], [])
        self.assert_no_secret(result)
        self.assertIsNone(D.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil.invalid"))

    def test_existing_final_file_is_not_replaced_during_download(self):
        original = self.opener.open
        def race(request, timeout):
            (self.output / D.stored_filename(FIRST, "problem_source.zip")).write_bytes(b"keep")
            return original(request, timeout)
        self.opener.open = race
        result = self.download()
        self.assertFalse(result["complete"])
        self.assertEqual((self.output / D.stored_filename(FIRST, "problem_source.zip")).read_bytes(), b"keep")

    def test_cli_returns_failure_for_incomplete_manifest(self):
        incomplete = {"complete": False, "files": [], "error": "safe error"}
        output = io.StringIO()
        with mock.patch.object(D.reader, "load_token", return_value=("synthetic-bot-token", "fake")), \
                mock.patch.object(D.reader, "DiscordAPI"), mock.patch.object(D.reader, "Reader"), \
                mock.patch.object(D, "AttachmentDownloader") as downloader, contextlib.redirect_stdout(output):
            downloader.return_value.download.return_value = incomplete
            status = D.main(["--channel-id", CHANNEL, "--message-id", MESSAGE, "--output", str(self.output)])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue()), incomplete)
        self.assertNotIn("synthetic-bot-token", output.getvalue())


if __name__ == "__main__":
    unittest.main()
