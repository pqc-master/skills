"""Offline problem-channel submission tests with synthetic archives and API responses."""
import contextlib
import http.client
from email import policy
from email.parser import BytesParser
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import urllib.request
import urllib.error
import zipfile


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("discord_submit_test_subject", SCRIPTS / "discord_submit.py")
S = importlib.util.module_from_spec(spec)
with mock.patch.object(sys, "path", [str(SCRIPTS)] + sys.path):
    spec.loader.exec_module(S)

GUILD = "1563153526283051008"
CATEGORY = "1570317863984701441"
CHANNEL = "1570317863984701442"
OTHER_CHANNEL = "1570317863984701443"
THREAD = "1570317863984701444"
BOT = "1570317863984701491"
OTHER_BOT = "1570317863984701492"
HOOK = "1570317863984701493"
OTHER_HOOK = "1570317863984701494"
MESSAGE = "1570317863984701495"
BOT_TOKEN = "synthetic_submission_bot_token"
HOOK_TOKEN = "synthetic_submission_webhook_token"
OLD_TOKEN = "synthetic_unused_config_webhook_token"
VIEW_CHANNEL = 1 << 10
MANAGE_WEBHOOKS = 1 << 29


def webhook(identifier=HOOK, owner=BOT, channel=CHANNEL, guild=GUILD, name="PQC Results", kind=1):
    return {"id": identifier, "type": kind, "name": name, "channel_id": channel,
            "guild_id": guild, "token": HOOK_TOKEN, "user": {"id": owner, "bot": True}}


def unpack(body, content_type):
    message = BytesParser(policy=policy.default).parsebytes(
        b"MIME-Version: 1.0\r\nContent-Type: " + content_type.encode("ascii") + b"\r\n\r\n" + body)
    parts = {}
    for part in message.iter_parts():
        parts[part.get_param("name", header="content-disposition")] = part
    return json.loads(parts["payload_json"].get_payload(decode=True)), parts


class Reader:
    def __init__(self, channels=None, permissions=VIEW_CHANNEL | MANAGE_WEBHOOKS):
        self.channels = channels or {
            CHANNEL: {"id": CHANNEL, "guild_id": GUILD, "parent_id": CATEGORY, "type": 0},
            OTHER_CHANNEL: {"id": OTHER_CHANNEL, "guild_id": GUILD, "parent_id": CATEGORY, "type": 0},
        }
        self.permissions = permissions
        self.calls = []

    def identify(self):
        self.calls.append(("identify",))
        return {"id": BOT, "bot": True, "username": "synthetic bot"}

    def channel(self, channel_id):
        self.calls.append(("channel", channel_id))
        return self.channels[channel_id]

    def effective_permissions(self, channel):
        self.calls.append(("permissions", channel["id"]))
        return self.permissions


class SubmissionAPI:
    def __init__(self, hooks=None):
        self.hooks = [webhook()] if hooks is None else hooks
        self.calls = []
        self.bodies = []

    def list_webhooks(self, parent_id):
        self.calls.append(("list", parent_id))
        return self.hooks

    def create_webhook(self, parent_id):
        self.calls.append(("create", parent_id))
        return webhook(channel=parent_id)

    def execute_webhook(self, webhook_id, webhook_token, body, content_type, thread_id=None):
        self.calls.append(("execute", webhook_id, webhook_token, thread_id))
        self.bodies.append((body, content_type))
        _, parts = unpack(body, content_type)
        return {"id": MESSAGE, "channel_id": thread_id or self.current_channel(), "webhook_id": webhook_id,
                "attachments": [{"id": "111", "filename": parts["files[0]"].get_filename(), "size": len(parts["files[0]"].get_payload(decode=True))},
                                {"id": "112", "filename": parts["files[1]"].get_filename(), "size": len(parts["files[1]"].get_payload(decode=True))}]}

    def current_channel(self):
        for call in reversed(self.calls):
            if call[0] in ("list", "create"):
                return call[1]
        raise AssertionError("Target should be checked before executing a webhook")


class IsolatedSubmission(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="discord-submit-test-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.archive = self.home / "코드 원본.zip"
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("solution.py", "print('synthetic solution')\n")
        self.report = self.home / "작업 보고서.md"
        self.report.write_text("# 검증 보고서\n가상 테스트 자료입니다.\n", encoding="utf-8")
        self.config = {"version": 1, "display_name": "민영", "webhooks": {
            OTHER_CHANNEL: {"guild_id": GUILD, "webhook_id": OTHER_HOOK,
                            "url": "https://discord.com/api/webhooks/" + OTHER_HOOK + "/" + OLD_TOKEN},
        }}
        for patcher in (mock.patch.object(Path, "home", return_value=self.home),
                        mock.patch.object(sys, "path", [str(SCRIPTS)] + sys.path),
                        mock.patch.dict(os.environ, {}, clear=True),
                        mock.patch.object(urllib.request.OpenerDirector, "open",
                                          side_effect=AssertionError("No real network permitted"))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def files(self):
        return S.load_files(self.archive, self.report)

    def submitter(self, reader=None, api=None):
        self.reader = reader if reader is not None else Reader()
        self.api = api if api is not None else SubmissionAPI()
        return S.Submitter(self.config, reader_client=self.reader, api=self.api)

    def assert_no_secrets(self, value):
        output = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        for secret in (BOT_TOKEN, HOOK_TOKEN, OLD_TOKEN):
            self.assertNotIn(secret, output)


class SubmissionFileTests(IsolatedSubmission):
    def test_input_file_roles_and_original_bytes_are_preserved(self):
        files = self.files()
        self.assertEqual([f["filename"] for f in files], ["sourcecode.zip", "report.md"])
        self.assertEqual(files[0]["data"], self.archive.read_bytes())
        self.assertEqual(files[1]["data"], self.report.read_bytes())
        self.assertTrue(all(len(f["sha256"]) == 64 for f in files))

    def test_non_zip_source_is_rejected(self):
        self.archive.write_bytes(b"not an archive")
        with self.assertRaises(S.SubmissionError):
            self.files()

    def test_non_utf8_report_is_rejected(self):
        self.report.write_bytes(b"\xff\xfe\x00")
        with self.assertRaises(S.SubmissionError):
            self.files()

    def test_missing_or_oversized_input_is_rejected(self):
        self.report.unlink()
        with self.assertRaises(S.SubmissionError):
            self.files()
        with self.report.open("wb") as output:
            output.truncate(26 * 1024 * 1024)
        with self.assertRaises(S.SubmissionError):
            self.files()


class SubmissionWorkflowTests(IsolatedSubmission):
    def test_preview_uses_current_channel_and_never_reads_bot_or_webhook(self):
        submitter = self.submitter()
        result = submitter.preview(CHANNEL, self.files())
        self.assertEqual(result["channel_id"], CHANNEL)
        self.assertEqual(result["username"], "민영 · Codex")
        self.assertEqual(self.reader.calls, [])
        self.assertEqual(self.api.calls, [])
        self.assertEqual([f["filename"] for f in result["files"]], ["sourcecode_민영.zip", "report_민영.md"])
        self.assert_no_secrets(result)
        self.assertNotIn("data", result["files"][0])

    def test_send_uploads_both_files_once_with_header_name_and_mentions_disabled(self):
        submitter = self.submitter()
        result = submitter.send(CHANNEL, self.files(), message="검증 결과 공유 @everyone")
        self.assertEqual(self.api.calls, [("list", CHANNEL), ("execute", HOOK, HOOK_TOKEN, None)])
        payload, parts = unpack(*self.api.bodies[0])
        self.assertEqual(payload["username"], "민영 · Codex")
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(payload["content"], "검증 결과 공유 @everyone")
        self.assertEqual([a["filename"] for a in payload["attachments"]], ["sourcecode_민영.zip", "report_민영.md"])
        self.assertEqual([parts[f"files[{index}]"].get_filename() for index in range(2)],
                         ["sourcecode_민영.zip", "report_민영.md"])
        self.assertEqual(parts["files[0]"].get_payload(decode=True), self.archive.read_bytes())
        self.assertEqual(parts["files[1]"].get_payload(decode=True), self.report.read_bytes())
        self.assertEqual(result["message_url"], f"https://discord.com/channels/{GUILD}/{CHANNEL}/{MESSAGE}")
        self.assert_no_secrets(result)

    def test_preview_and_send_use_safe_author_names_without_changing_inputs_or_profile(self):
        for name, suffix in (("  김 민영  ", "김_민영"),
                             ('a/b\\c:d"e<f>g|h?i*j', "a_b_c_d_e_f_g_h_i_j"),
                             ("../\\:*?\"<>|", "user"),
                             ("민\u2028영", "민_영")):
            with self.subTest(name=name):
                self.config["display_name"] = name
                profile_before = json.dumps(self.config, sort_keys=True)
                files = self.files()
                files_before = [dict(item) for item in files]
                submitter = self.submitter()
                preview = submitter.preview(CHANNEL, files)
                result = submitter.send(CHANNEL, files)
                payload, parts = unpack(*self.api.bodies[0])
                expected_names = [f"sourcecode_{suffix}.zip", f"report_{suffix}.md"]
                self.assertEqual([item["filename"] for item in preview["files"]], expected_names)
                self.assertEqual(result["files"], preview["files"])
                self.assertEqual([item["filename"] for item in payload["attachments"]], expected_names)
                self.assertEqual([parts[f"files[{index}]"].get_filename() for index in range(2)], expected_names)
                self.assertEqual(payload["username"], name.strip() + " · Codex")
                self.assertEqual(files, files_before)
                self.assertEqual(json.dumps(self.config, sort_keys=True), profile_before)
                for index, item in enumerate(files):
                    self.assertEqual(preview["files"][index]["sha256"], item["sha256"])
                    self.assertEqual(parts[f"files[{index}]"].get_payload(decode=True), item["data"])
                self.assertTrue(self.archive.is_file())
                self.assertTrue(self.report.is_file())

    def test_control_characters_in_display_name_still_fail_before_network(self):
        for name in ("민\r\n영", "민\x00영", "민\u202e영"):
            with self.subTest(name=name):
                self.config["display_name"] = name
                with self.assertRaises(S.SubmissionError):
                    self.submitter()
                self.assertEqual(self.reader.calls, [])
                self.assertEqual(self.api.calls, [])

    def test_no_existing_webhook_creates_one_on_current_problem_channel(self):
        submitter = self.submitter(api=SubmissionAPI(hooks=[]))
        submitter.send(CHANNEL, self.files())
        self.assertEqual(self.api.calls, [("list", CHANNEL), ("create", CHANNEL), ("execute", HOOK, HOOK_TOKEN, None)])

    def test_other_bots_or_differently_named_webhooks_are_never_reused(self):
        hooks = [webhook(identifier=OTHER_HOOK, owner=OTHER_BOT),
                 webhook(identifier=OTHER_HOOK, name="Other integration"),
                 webhook(identifier=OTHER_HOOK, kind=2)]
        submitter = self.submitter(api=SubmissionAPI(hooks=hooks))
        submitter.send(CHANNEL, self.files())
        self.assertEqual(self.api.calls, [("list", CHANNEL), ("create", CHANNEL), ("execute", HOOK, HOOK_TOKEN, None)])

    def test_each_invocation_selects_channel_without_changing_saved_profile(self):
        before = json.dumps(self.config, sort_keys=True)
        submitter = self.submitter(api=SubmissionAPI(hooks=[]))
        submitter.send(CHANNEL, self.files())
        submitter.send(OTHER_CHANNEL, self.files())
        self.assertIn(("list", CHANNEL), self.api.calls)
        self.assertIn(("list", OTHER_CHANNEL), self.api.calls)
        self.assertEqual(json.dumps(self.config, sort_keys=True), before)

    def test_wrong_server_or_category_blocks_webhook_creation_and_posting(self):
        for field, value in (("guild_id", "999999999999999999"), ("parent_id", "999999999999999998")):
            with self.subTest(field=field):
                target = {"id": CHANNEL, "guild_id": GUILD, "parent_id": CATEGORY, "type": 0, field: value}
                submitter = self.submitter(reader=Reader(channels={CHANNEL: target}))
                with self.assertRaises(S.SubmissionError):
                    submitter.send(CHANNEL, self.files())
                self.assertEqual(self.api.calls, [])

    def test_view_and_manage_webhooks_permissions_are_required(self):
        for permissions in (0, VIEW_CHANNEL, MANAGE_WEBHOOKS):
            with self.subTest(permissions=permissions):
                submitter = self.submitter(reader=Reader(permissions=permissions))
                with self.assertRaises(S.SubmissionError):
                    submitter.send(CHANNEL, self.files())
                self.assertEqual(self.api.calls, [])

    def test_thread_submission_uses_parent_webhook_and_explicit_thread_target(self):
        channels = {CHANNEL: {"id": CHANNEL, "guild_id": GUILD, "parent_id": CATEGORY, "type": 0},
                    THREAD: {"id": THREAD, "guild_id": GUILD, "parent_id": CHANNEL, "type": 11}}
        submitter = self.submitter(reader=Reader(channels=channels))
        result = submitter.send(THREAD, self.files())
        self.assertEqual(self.api.calls, [("list", CHANNEL), ("execute", HOOK, HOOK_TOKEN, THREAD)])
        self.assertEqual(result["message_url"], f"https://discord.com/channels/{GUILD}/{THREAD}/{MESSAGE}")

    def test_invalid_created_webhook_is_not_used_for_file_upload(self):
        api = SubmissionAPI(hooks=[])
        def invalid_created(parent_id):
            api.calls.append(("create", parent_id))
            return webhook(channel=OTHER_CHANNEL)
        api.create_webhook = invalid_created
        submitter = self.submitter(api=api)
        with self.assertRaises(S.OutcomeUnknown) as caught:
            submitter.send(CHANNEL, self.files())
        self.assert_no_secrets(str(caught.exception))
        self.assertEqual(api.calls, [("list", CHANNEL), ("create", CHANNEL)])

    def test_unconfirmed_attachment_or_channel_result_is_not_reported_as_success(self):
        for fault in ("missing_report", "wrong_channel", "wrong_filename"):
            with self.subTest(fault=fault):
                api = SubmissionAPI()
                execute = api.execute_webhook
                def invalid_result(*args, **kwargs):
                    response = execute(*args, **kwargs)
                    if fault == "missing_report":
                        response["attachments"].pop()
                    elif fault == "wrong_filename":
                        response["attachments"][0]["filename"] = "sourcecode.zip"
                    else:
                        response["channel_id"] = OTHER_CHANNEL
                    return response
                api.execute_webhook = invalid_result
                submitter = self.submitter(api=api)
                with self.assertRaises(S.OutcomeUnknown):
                    submitter.send(CHANNEL, self.files())
                self.assertEqual(sum(call[0] == "execute" for call in api.calls), 1)

    def test_preview_cli_requires_current_channel_and_does_not_read_bot_token(self):
        config_path = self.home / "publisher.json"
        S.publisher.save_config(self.config, config_path)
        args = ["--config", str(config_path), "preview", "--source-zip", str(self.archive), "--report", str(self.report)]
        out = io.StringIO()
        with mock.patch.object(S.reader, "load_token", side_effect=AssertionError("Preview must not load bot credentials")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                S.main(args)
            self.assertEqual(caught.exception.code, 2)
            self.assertEqual(S.main(args + ["--channel-id", CHANNEL]), 0)
        self.assertEqual(json.loads(out.getvalue())["channel_id"], CHANNEL)
        self.assert_no_secrets(out.getvalue())

    def test_total_multipart_limit_is_enforced_before_any_api_call(self):
        submitter = self.submitter()
        with mock.patch.object(S, "MAX_REQUEST_BYTES", 100):
            with self.assertRaises(S.SubmissionError):
                submitter.send(CHANNEL, self.files())
        self.assertEqual(self.reader.calls, [])
        self.assertEqual(self.api.calls, [])


class Response:
    status = 200

    def __init__(self, result=None, error=None, raw=None):
        self.body = raw if raw is not None else json.dumps({} if result is None else result).encode("utf-8")
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        if self.error:
            raise self.error
        return self.body if size < 0 else self.body[:size]


class Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def http_error(status, body=b"{}", headers=None):
    return urllib.error.HTTPError("https://discord.com/api/v10/webhooks/" + HOOK + "/" + HOOK_TOKEN,
                                  status, "synthetic", headers or {}, io.BytesIO(body))


class SubmissionTransportTests(IsolatedSubmission):
    def multipart(self):
        payload = {"username": "민영 · Codex", "allowed_mentions": {"parse": []}}
        return S.encode_multipart(payload, self.files())

    def test_management_requests_use_bot_auth_but_execution_does_not(self):
        opener = Opener(Response([]), Response(webhook()), Response({"id": MESSAGE}))
        api = S.SubmissionAPI(BOT_TOKEN, opener=opener, sleeper=lambda _: None)
        api.list_webhooks(CHANNEL)
        api.create_webhook(CHANNEL)
        api.execute_webhook(HOOK, HOOK_TOKEN, *self.multipart(), thread_id=THREAD)
        listing, creation, execution = opener.requests
        self.assertEqual(listing.get_header("Authorization"), "Bot " + BOT_TOKEN)
        self.assertEqual(creation.get_header("Authorization"), "Bot " + BOT_TOKEN)
        self.assertEqual(listing.get_method(), "GET")
        self.assertEqual(creation.get_method(), "POST")
        self.assertEqual(json.loads(creation.data), {"name": "PQC Results"})
        self.assertIsNone(execution.get_header("Authorization"))
        self.assertEqual(execution.get_method(), "POST")
        self.assertTrue(execution.full_url.endswith("?wait=true&thread_id=" + THREAD))

    def test_429_wait_is_obeyed_before_retrying_file_upload(self):
        opener = Opener(http_error(429, b'{"retry_after": 0.25}'), Response({"id": MESSAGE}))
        waits = []
        api = S.SubmissionAPI(BOT_TOKEN, opener=opener, sleeper=waits.append)
        result = api.execute_webhook(HOOK, HOOK_TOKEN, *self.multipart())
        self.assertEqual(result["id"], MESSAGE)
        self.assertEqual(len(opener.requests), 2)
        self.assertGreaterEqual(sum(waits), 0.25)

    def test_long_rate_limit_does_not_retry_early(self):
        opener = Opener(http_error(429, b'{"retry_after": 3600}'))
        waits = []
        api = S.SubmissionAPI(BOT_TOKEN, opener=opener, sleeper=waits.append)
        with self.assertRaises(S.SubmissionError):
            api.execute_webhook(HOOK, HOOK_TOKEN, *self.multipart())
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(waits, [])

    def test_uncertain_upload_is_never_retried_and_hides_raw_error_details(self):
        failures = [http_error(503, HOOK_TOKEN.encode()), urllib.error.URLError(BOT_TOKEN),
                    Response(error=http.client.IncompleteRead(HOOK_TOKEN.encode())), Response(raw=b"not-json")]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                opener = Opener(failure)
                waits = []
                api = S.SubmissionAPI(BOT_TOKEN, opener=opener, sleeper=waits.append)
                with self.assertRaises(S.OutcomeUnknown) as caught:
                    api.execute_webhook(HOOK, HOOK_TOKEN, *self.multipart())
                self.assert_no_secrets(str(caught.exception))
                self.assertEqual(len(opener.requests), 1)
                self.assertEqual(waits, [])

    def test_uncertain_webhook_creation_is_not_repeated(self):
        opener = Opener(urllib.error.URLError(BOT_TOKEN))
        api = S.SubmissionAPI(BOT_TOKEN, opener=opener, sleeper=lambda _: None)
        with self.assertRaises(S.OutcomeUnknown) as caught:
            api.create_webhook(CHANNEL)
        self.assert_no_secrets(str(caught.exception))
        self.assertEqual(len(opener.requests), 1)

    def test_definitive_http_failure_does_not_retry_or_expose_response(self):
        opener = Opener(http_error(403, (BOT_TOKEN + HOOK_TOKEN).encode()))
        api = S.SubmissionAPI(BOT_TOKEN, opener=opener, sleeper=lambda _: None)
        with self.assertRaises(S.APIError) as caught:
            api.execute_webhook(HOOK, HOOK_TOKEN, *self.multipart())
        self.assertEqual(caught.exception.status, 403)
        self.assert_no_secrets(str(caught.exception))
        self.assertEqual(len(opener.requests), 1)

    def test_malformed_webhook_token_is_rejected_before_request(self):
        opener = Opener()
        api = S.SubmissionAPI(BOT_TOKEN, opener=opener, sleeper=lambda _: None)
        with self.assertRaises(S.SubmissionError):
            api.execute_webhook(HOOK, "../" + HOOK_TOKEN, *self.multipart())
        self.assertEqual(opener.requests, [])

    def test_redirect_handler_never_forwards_request_to_another_host(self):
        request = urllib.request.Request("https://discord.com/api/v10/channels/" + CHANNEL + "/webhooks",
                                         headers={"Authorization": "Bot " + BOT_TOKEN})
        handler = S.NoRedirect()
        self.assertIsNone(handler.redirect_request(request, None, 302, "redirect", {}, "https://other.invalid/"))


if __name__ == "__main__":
    unittest.main()
