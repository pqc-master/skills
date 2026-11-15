"""Offline publisher checks. Every credential, response, and identity is synthetic."""
import contextlib
import copy
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.request


SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "discord_publish.py"
spec = importlib.util.spec_from_file_location("discord_publish", SOURCE)
publisher_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher_module)
P = publisher_module

GUILD = "1563153526283051008"
CHANNEL = "1563154015389224961"
SECOND_CHANNEL = "1563154015389224962"
WEBHOOK = "1563154015389224990"
SECOND_WEBHOOK = "1563154015389224991"
MESSAGE = "1563154015389224999"
SECRET = "synthetic_webhook_token_" + "X" * 60
URL = "https://discord.com/api/v10/webhooks/" + WEBHOOK + "/" + SECRET
SECOND_URL = "https://discord.com/api/v10/webhooks/" + SECOND_WEBHOOK + "/" + SECRET


def configuration():
    return {"version": 1, "display_name": "민영", "webhooks": {
        CHANNEL: {"guild_id": GUILD, "webhook_id": WEBHOOK, "url": URL},
    }}


def metadata(channel=CHANNEL, webhook=WEBHOOK, guild=GUILD, kind=1):
    return {"id": webhook, "type": kind, "guild_id": guild,
            "channel_id": channel, "name": "shared hook", "token": SECRET}


def sent_message(channel=CHANNEL, webhook=WEBHOOK):
    return {"id": MESSAGE, "channel_id": channel, "webhook_id": webhook,
            "author": {"id": webhook, "username": "민영 · Codex"},
            "content": "검증 완료"}


class Response:
    def __init__(self, value=None, status=200, raw=None, headers=None):
        self.status = status
        self.headers = headers or {}
        self.body = raw if raw is not None else json.dumps(value).encode("utf-8")

    def read(self, amount=None):
        if isinstance(self.body, BaseException):
            raise self.body
        return self.body if amount is None else self.body[:amount]

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("Unexpected additional HTTP request")
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def http_error(status, body=None, headers=None):
    payload = body if body is not None else {"message": URL + " " + SECRET}
    return urllib.error.HTTPError(URL, status, "private " + SECRET,
                                  headers or {}, io.BytesIO(json.dumps(payload).encode("utf-8")))


class FakeAPI:
    def __init__(self, hook=None, result=None):
        self.hook = hook if hook is not None else metadata()
        self.result = result if result is not None else sent_message()
        self.calls = []

    def get(self, url):
        self.calls.append(("GET", url, None))
        if isinstance(self.hook, BaseException):
            raise self.hook
        return copy.deepcopy(self.hook)

    def execute(self, url, payload):
        self.calls.append(("POST", url, copy.deepcopy(payload)))
        if isinstance(self.result, BaseException):
            raise self.result
        return copy.deepcopy(self.result)


class PublisherValidationTests(unittest.TestCase):
    def test_normalize_accepts_copied_url_and_returns_fixed_api_version(self):
        copied = URL.replace("/api/v10/", "/api/")
        self.assertEqual(P.normalize_webhook_url(copied), (URL, WEBHOOK))
        self.assertEqual(P.normalize_webhook_url(URL), (URL, WEBHOOK))

    def test_urls_cannot_select_other_hosts_routes_or_query_actions(self):
        bad_urls = [
            URL.replace("https:", "http:"),
            URL.replace("discord.com", "example.com"),
            URL.replace("discord.com", "discord.com.example.com"),
            URL.replace("discord.com", "user@discord.com"),
            URL.replace("discord.com", "discord.com:443"),
            URL + "?wait=true", URL + "#fragment", URL + "/messages/123",
            URL.replace("/v10/", "/v9/"),
            URL.replace(WEBHOOK, "0"),
            URL.replace(WEBHOOK, str(1 << 64)),
            URL.replace(SECRET, "%2F" + SECRET),
            URL.replace("/webhooks/", "/channels/"),
        ]
        for value in bad_urls:
            with self.subTest(url_kind=value.split("/")[2]):
                with self.assertRaises(P.PublisherError) as caught:
                    P.normalize_webhook_url(value)
                self.assertNotIn(SECRET, str(caught.exception))
                self.assertNotIn(value, str(caught.exception))

    def test_unicode_name_limit_includes_suffix_and_utf16_units(self):
        self.assertEqual(P.utf16_length("가😀"), 3)
        self.assertEqual(P.display_username("민영"), "민영 · Codex")
        suffix_units = P.utf16_length(" · Codex")
        name = "가" * (80 - suffix_units)
        self.assertEqual(P.utf16_length(P.display_username(name)), 80)
        with self.assertRaises(P.PublisherError):
            P.display_username(name + "가")
        with self.assertRaises(P.PublisherError):
            P.display_username("😀" * ((80 - suffix_units) // 2 + 1))
        for name in ("", "   ", "person\nother", "person\x00"):
            with self.subTest(name=repr(name)), self.assertRaises(P.PublisherError):
                P.display_username(name)

    def test_content_limit_counts_astral_characters_conservatively(self):
        client = P.Publisher(configuration(), api=FakeAPI())
        client.preview(CHANNEL, "😀" * 1000)
        for body in ("😀" * 1001, "가" * 2001, "", " \n\t"):
            with self.subTest(length=len(body)), self.assertRaises(P.PublisherError):
                client.preview(CHANNEL, body)


class PublisherConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "private" / "publisher.json"

    def test_config_roundtrip_creates_private_file(self):
        expected = configuration()
        P.save_config(expected, self.path)
        self.assertEqual(P.load_config(self.path), expected)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_failed_atomic_replacement_preserves_existing_configuration(self):
        P.save_config(configuration(), self.path)
        original = self.path.read_bytes()
        files_before = set(self.path.parent.iterdir())
        changed = configuration()
        changed["display_name"] = "철수"
        with mock.patch.object(P.os, "replace", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises((P.PublisherError, OSError)):
                P.save_config(changed, self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(set(self.path.parent.iterdir()), files_before)

    @unittest.skipUnless(os.name == "posix", "POSIX permission contract")
    def test_world_readable_config_is_rejected(self):
        P.save_config(configuration(), self.path)
        self.path.chmod(0o644)
        with self.assertRaises(P.PublisherError) as caught:
            P.load_config(self.path)
        self.assertNotIn(SECRET, str(caught.exception))

    def test_corrupt_config_errors_do_not_echo_secret_values(self):
        self.path.parent.mkdir()
        cases = [
            '{"private": "' + SECRET,
            json.dumps({"version": SECRET, "webhooks": {}}),
            json.dumps({"version": 1, "display_name": "name", "webhooks": SECRET}),
        ]
        for text in cases:
            with self.subTest(case=len(text)):
                self.path.write_text(text, encoding="utf-8")
                self.path.chmod(0o600)
                with self.assertRaises(P.PublisherError) as caught:
                    P.load_config(self.path)
                self.assertNotIn(SECRET, str(caught.exception))

    def test_setup_adds_channel_without_removing_existing_binding(self):
        P.save_config(configuration(), self.path)
        api = FakeAPI(hook=metadata(channel=SECOND_CHANNEL, webhook=SECOND_WEBHOOK))
        out = io.StringIO()
        with mock.patch.object(P.getpass, "getpass", return_value=SECOND_URL), \
                contextlib.redirect_stdout(out):
            P.setup(self.path, name="철수", guild_id=GUILD, api=api)
        saved = P.load_config(self.path)
        self.assertEqual(saved["webhooks"][CHANNEL], configuration()["webhooks"][CHANNEL])
        self.assertEqual(saved["webhooks"][SECOND_CHANNEL]["webhook_id"], SECOND_WEBHOOK)
        self.assertEqual(saved["display_name"], "철수")
        self.assertNotIn(SECRET, out.getvalue())
        self.assertFalse(any(call[0] == "POST" for call in api.calls))

    def test_setup_wrong_guild_does_not_replace_existing_config(self):
        P.save_config(configuration(), self.path)
        original = self.path.read_bytes()
        api = FakeAPI(hook=metadata(guild="1563153526283051009"))
        with mock.patch.object(P.getpass, "getpass", return_value=URL):
            with self.assertRaises(P.PublisherError):
                P.setup(self.path, name="철수", guild_id=GUILD, api=api)
        self.assertEqual(self.path.read_bytes(), original)

    def test_profile_change_preserves_all_bindings_without_network(self):
        initial = configuration()
        initial["webhooks"][SECOND_CHANNEL] = {
            "guild_id": GUILD, "webhook_id": SECOND_WEBHOOK, "url": SECOND_URL,
        }
        P.save_config(initial, self.path)
        with mock.patch.object(P.WebhookAPI, "get", side_effect=AssertionError("Profile must stay offline")), \
                mock.patch.object(P.WebhookAPI, "execute", side_effect=AssertionError("Profile must stay offline")):
            P.update_profile("철수", self.path)
        saved = P.load_config(self.path)
        self.assertEqual(saved["display_name"], "철수")
        self.assertEqual(saved["webhooks"], initial["webhooks"])


class PublisherBehaviorTests(unittest.TestCase):
    def test_preview_performs_no_network_and_hides_webhook_secret(self):
        api = FakeAPI()
        result = P.Publisher(configuration(), api=api).preview(CHANNEL, "검증 완료")
        self.assertEqual(api.calls, [])
        rendered = json.dumps(result, ensure_ascii=False)
        self.assertIn("민영", rendered)
        self.assertIn(CHANNEL, rendered)
        self.assertIn("검증 완료", rendered)
        self.assertNotIn(SECRET, rendered)
        self.assertNotIn(URL, rendered)

    def test_target_or_type_mismatch_blocks_post(self):
        hooks = [metadata(channel=SECOND_CHANNEL), metadata(guild="1563153526283051009"),
                 metadata(webhook=SECOND_WEBHOOK), metadata(kind=2)]
        for hook in hooks:
            with self.subTest(hook=hook["id"]):
                api = FakeAPI(hook=hook)
                with self.assertRaises(P.PublisherError) as caught:
                    P.Publisher(configuration(), api=api).send(CHANNEL, "검증 완료")
                self.assertFalse(any(call[0] == "POST" for call in api.calls))
                self.assertNotIn(SECRET, str(caught.exception))

    def test_posts_name_and_disables_all_mentions_and_returns_message_link(self):
        api = FakeAPI()
        text = "@everyone <@123> 검증 완료"
        result = P.Publisher(configuration(), api=api).send(CHANNEL, text)
        self.assertEqual([call[0] for call in api.calls], ["GET", "POST"])
        payload = api.calls[1][2]
        self.assertEqual(payload["content"], text)
        self.assertEqual(payload["username"], "민영 · Codex")
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertEqual(result["message_url"], f"https://discord.com/channels/{GUILD}/{CHANNEL}/{MESSAGE}")
        self.assertNotIn(SECRET, json.dumps(result))

    def test_malformed_success_is_unknown_and_never_reposted(self):
        for result in ({}, {"id": MESSAGE}, sent_message(channel=SECOND_CHANNEL),
                       sent_message(webhook=SECOND_WEBHOOK)):
            with self.subTest(keys=list(result)):
                api = FakeAPI(result=result)
                with self.assertRaises(P.OutcomeUnknown):
                    P.Publisher(configuration(), api=api).send(CHANNEL, "검증 완료")
                self.assertEqual(sum(call[0] == "POST" for call in api.calls), 1)

    def test_unconfigured_channel_does_not_make_requests(self):
        api = FakeAPI()
        with self.assertRaises(P.PublisherError):
            P.Publisher(configuration(), api=api).send(SECOND_CHANNEL, "검증 완료")
        self.assertEqual(api.calls, [])


class PublisherHTTPTests(unittest.TestCase):
    def test_execute_requests_acknowledgement_and_uses_no_bot_authorization(self):
        opener = Opener([Response(sent_message())])
        payload = {"username": "민영 · Codex", "content": "검증 완료", "allowed_mentions": {"parse": []}}
        P.WebhookAPI(opener=opener).execute(URL, payload)
        request = opener.requests[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, URL + "?wait=true")
        self.assertEqual(json.loads(request.data), payload)
        self.assertIsNone(request.get_header("Authorization"))

    def test_429_retries_after_server_delay(self):
        for body, headers, delay in [({"retry_after": 0.25}, {}, 0.25),
                                     ({}, {"Retry-After": "0.5"}, 0.5)]:
            with self.subTest(delay=delay):
                opener = Opener([http_error(429, body, headers), Response(sent_message())])
                sleeper = mock.Mock()
                P.WebhookAPI(opener=opener, sleeper=sleeper).execute(URL, {"content": "test"})
                self.assertEqual(len(opener.requests), 2)
                waited = sum(call.args[0] for call in sleeper.call_args_list)
                self.assertGreaterEqual(waited, delay)
                self.assertLess(waited, delay + 1)

    def test_unknown_post_outcomes_are_not_automatically_retried_or_leaked(self):
        cases = [http_error(500), urllib.error.URLError("private " + URL),
                 TimeoutError("private " + SECRET), Response(raw=b"not-json"),
                 Response(raw=b"", status=204),
                 Response(raw=http.client.IncompleteRead(SECRET.encode("ascii")))]
        for value in cases:
            with self.subTest(kind=type(value).__name__):
                opener = Opener([value, Response(sent_message())])
                with self.assertRaises(P.OutcomeUnknown) as caught:
                    P.WebhookAPI(opener=opener).execute(URL, {"content": "test"})
                self.assertEqual(len(opener.requests), 1)
                self.assertNotIn(SECRET, str(caught.exception))
                self.assertNotIn(URL, str(caught.exception))

    def test_denied_or_missing_webhook_is_not_retried_or_echoed(self):
        for code in (400, 401, 403, 404):
            with self.subTest(status=code):
                opener = Opener([http_error(code), Response(sent_message())])
                with self.assertRaises(P.PublisherError) as caught:
                    P.WebhookAPI(opener=opener).execute(URL, {"content": "test"})
                self.assertEqual(len(opener.requests), 1)
                self.assertNotIn(SECRET, str(caught.exception))
                self.assertNotIn(URL, str(caught.exception))

    def test_rate_limit_retries_are_bounded_and_do_not_ignore_long_wait(self):
        opener = Opener([http_error(429, {"retry_after": 0}) for _ in range(10)])
        sleeper = mock.Mock()
        with self.assertRaises(P.PublisherError):
            P.WebhookAPI(opener=opener, sleeper=sleeper).execute(URL, {"content": "test"})
        self.assertGreater(len(opener.requests), 1)
        self.assertLess(len(opener.requests), 10)
        opener = Opener([http_error(429, {"retry_after": 3600}), Response(sent_message())])
        sleeper = mock.Mock()
        with self.assertRaises(P.PublisherError):
            P.WebhookAPI(opener=opener, sleeper=sleeper).execute(URL, {"content": "test"})
        self.assertEqual(len(opener.requests), 1)
        sleeper.assert_not_called()

    def test_redirect_handler_rejects_offsite_redirects(self):
        api = P.WebhookAPI()
        opener = api.opener
        handlers = [handler for handler in opener.handlers
                    if hasattr(handler, "redirect_request")]
        self.assertTrue(handlers)
        request = urllib.request.Request(URL)
        for handler in handlers:
            redirected = handler.redirect_request(request, None, 302, "redirect",
                                                  {}, "https://example.com/collect")
            self.assertIsNone(redirected)


class PublisherCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "publisher.json"
        P.save_config(configuration(), self.path)

    def run_cli(self, args, api):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(P, "WebhookAPI", return_value=api), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = P.main(["--config", str(self.path)] + args)
        combined = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn(SECRET, combined)
        self.assertNotIn(URL, combined)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_preview_cli_reads_utf8_file_without_network(self):
        content = "검증 결과\n둘째 줄 😀\n"
        message_file = Path(self.temp.name) / "message.md"
        message_file.write_text(content, encoding="utf-8")
        api = FakeAPI()
        code, output, _ = self.run_cli(
            ["preview", "--channel-id", CHANNEL, "--content-file", str(message_file)], api)
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(output)["sent"])
        self.assertEqual(json.loads(output)["content"], content)
        self.assertEqual(api.calls, [])

    def test_profile_cli_is_offline_and_preserves_webhooks(self):
        api = FakeAPI()
        code, output, _ = self.run_cli(["profile", "--name", "철수"], api)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["username"], "철수 · Codex")
        self.assertEqual(P.load_config(self.path)["webhooks"], configuration()["webhooks"])
        self.assertEqual(api.calls, [])

    def test_corrupt_config_cli_reports_failure_without_leaking_secret(self):
        self.path.write_text('{"broken": "' + SECRET, encoding="utf-8")
        api = FakeAPI()
        code, output, error = self.run_cli(["doctor", "--channel-id", CHANNEL], api)
        self.assertEqual(code, 1)
        self.assertEqual(output, "")
        self.assertTrue(error)
        self.assertEqual(api.calls, [])

    def test_cli_distinguishes_unknown_delivery_and_does_not_retry(self):
        for failed_response in (http_error(500), Response(raw=http.client.IncompleteRead(SECRET.encode("ascii")))):
            with self.subTest(response=type(failed_response).__name__):
                opener = Opener([Response(metadata()), failed_response])
                api = P.WebhookAPI(opener=opener)
                code, output, error = self.run_cli(["send", "--channel-id", CHANNEL, "--text", "검증 완료"], api)
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertIn("unknown", error.lower())
                self.assertEqual([r.get_method() for r in opener.requests], ["GET", "POST"])


if __name__ == "__main__":
    unittest.main()
