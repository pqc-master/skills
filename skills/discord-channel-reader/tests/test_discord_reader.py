"""Offline behavioral checks: all Discord responses and secrets are synthetic."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest import mock
import urllib.error

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "discord_reader.py"
sys.path.insert(0, str(SOURCE.parent))
spec = importlib.util.spec_from_file_location("discord_reader", SOURCE)
reader_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader_module)
R = reader_module


def message(ident, channel="20", content=None):
    return {"id": str(ident), "channel_id": channel, "type": 0,
            "content": content if content is not None else f"message {ident}",
            "author": {"id": "60", "username": "tester"},
            "timestamp": "2026-11-14T12:00:00+00:00", "attachments": []}


def channel(ident="20", kind=0, parent="10", overwrites=None):
    return {"id": ident, "guild_id": "1", "name": f"channel-{ident}", "type": kind,
            "parent_id": parent, "permission_overwrites": overwrites or []}


class FakeAPI:
    def __init__(self, permissions=None, intent=True):
        self.calls = []
        self.data = {
            "/users/@me": {"id": "9", "username": "reader", "bot": True},
            "/oauth2/applications/@me": {"flags": (1 << 19) if intent else 0},
            "/guilds/1": {"id": "1", "owner_id": "8"},
            "/guilds/1/roles": [{"id": "1", "permissions": str(
                R.VIEW_CHANNEL | R.READ_HISTORY if permissions is None else permissions)}],
            "/guilds/1/members/9": {"roles": []},
            "/channels/20": channel(),
        }

    def get(self, route, params=None):
        self.calls.append((route, dict(params) if params else None))
        if route not in self.data:
            raise AssertionError(f"Unexpected API request: {route} {params}")
        result = self.data[route]
        if callable(result):
            result = result(params)
        if isinstance(result, Exception):
            raise result
        return result


class ListingCLITests(unittest.TestCase):
    def run_listing(self, command, guild_id, category_id, override=False):
        api = FakeAPI()
        category = dict(channel(category_id, 4, None), guild_id=guild_id)
        child = dict(channel("30", parent=category_id), guild_id=guild_id)
        api.data[f"/channels/{category_id}"] = category
        api.data[f"/guilds/{guild_id}/channels"] = [category, child]
        argv = [command]
        if override:
            argv.extend(["--guild-id", guild_id] if command == "categories"
                        else ["--category-id", category_id])
        output = io.StringIO()
        with mock.patch.object(R, "load_token", return_value=("synthetic-token", "test")), \
                mock.patch.object(R, "DiscordAPI", return_value=api), contextlib.redirect_stdout(output):
            self.assertEqual(R.main(argv), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["guild_id"], guild_id)
        if command == "categories":
            self.assertEqual([c["id"] for c in result["categories"]], [category_id])
        else:
            self.assertEqual(result["category_id"], category_id)
            self.assertEqual([c["id"] for c in result["channels"]], ["30"])
        self.assertFalse(any(route.endswith("/messages") for route, _ in api.calls))

    def test_id_free_listing_uses_configured_server_and_category(self):
        for command in ("categories", "channels"):
            with self.subTest(command=command):
                self.run_listing(command, "1563153526283051008", "1570317863984701441")

    def test_explicit_ids_override_defaults(self):
        for command in ("categories", "channels"):
            with self.subTest(command=command):
                self.run_listing(command, "1", "10", override=True)


class ExportTests(unittest.TestCase):
    def export(self, api, output, threads=False):
        with mock.patch.object(R, "start_boundary", return_value="1000"):
            return R.export_history(R.Reader(api), "20", output, threads)

    def test_more_than_100_and_short_pages_continue_to_empty(self):
        api = FakeAPI()
        pages = {"1000": [message(i) for i in range(999, 899, -1)],
                 "900": [message(899), message(898)],
                 "898": [message(897)], "897": []}
        api.data["/channels/20/messages"] = lambda p: pages[p["before"]]
        with tempfile.TemporaryDirectory() as base:
            output = Path(base) / "export"
            metadata, code = self.export(api, output)
            self.assertEqual(code, 0)
            self.assertTrue(metadata["complete"])
            self.assertEqual(metadata["message_count"], 103)
            self.assertEqual([p["before"] for route, p in api.calls if route.endswith("/messages")],
                             ["1000", "900", "898", "897"])
            records = [json.loads(line) for line in (output / "messages.jsonl").read_text().splitlines()]
            self.assertEqual(len(records), 103)
            text = (output / "transcript.md").read_text()
            self.assertLess(text.index("Message: 897"), text.index("Message: 999"))
            self.assertFalse((output / ".messages.sqlite").exists())

    def test_no_history_permission_is_not_an_empty_success(self):
        api = FakeAPI(permissions=R.VIEW_CHANNEL)
        api.data["/channels/20/messages"] = []
        with tempfile.TemporaryDirectory() as base:
            metadata, code = self.export(api, Path(base) / "export")
        self.assertEqual(code, 2)
        self.assertFalse(metadata["complete"])
        self.assertFalse(metadata["channels"][0]["pagination_complete"])
        self.assertFalse(any(route.endswith("/messages") for route, _ in api.calls))

    def test_intent_disabled_does_not_claim_full_content(self):
        api = FakeAPI(intent=False)
        api.data["/channels/20/messages"] = []
        with tempfile.TemporaryDirectory() as base:
            metadata, code = self.export(api, Path(base) / "export")
        self.assertEqual(code, 2)
        self.assertTrue(metadata["pagination_complete"])
        self.assertFalse(metadata["text_content_available"])
        self.assertFalse(metadata["complete"])

    def test_missing_intent_metadata_is_unknown(self):
        api = FakeAPI()
        api.data["/oauth2/applications/@me"] = R.APIError(403, "/oauth2/applications/@me")
        enabled, warning = R.Reader(api).content_status()
        self.assertIsNone(enabled)
        self.assertIn("unknown", warning)

    def test_partial_failure_preserves_collected_messages(self):
        api = FakeAPI()
        def pages(params):
            if params["before"] == "1000":
                return [message(900)]
            raise R.APIError(403, "/channels/20/messages")
        api.data["/channels/20/messages"] = pages
        with tempfile.TemporaryDirectory() as base:
            output = Path(base) / "export"
            metadata, code = self.export(api, output)
            self.assertEqual(code, 2)
            self.assertEqual(metadata["message_count"], 1)
            self.assertFalse(metadata["complete"])
            self.assertEqual(json.loads((output / "messages.jsonl").read_text())["id"], "900")
            self.assertTrue((output / "transcript.md").exists())
            self.assertTrue((output / ".messages.sqlite").exists())

    def test_duplicates_and_post_boundary_messages_are_not_exported(self):
        api = FakeAPI()
        pages = {"1000": [message(1001), message(999), message(999), message(900)],
                 "900": [message(900), message(899)], "899": []}
        api.data["/channels/20/messages"] = lambda p: pages[p["before"]]
        with tempfile.TemporaryDirectory() as base:
            output = Path(base) / "export"
            metadata, code = self.export(api, output)
            ids = [json.loads(line)["id"] for line in (output / "messages.jsonl").read_text().splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual(ids, ["999", "900", "899"])
        self.assertEqual(metadata["message_count"], 3)

    def test_cursor_stall_is_partial_error(self):
        api = FakeAPI()
        api.data["/channels/20/messages"] = lambda p: [message(900)]
        with tempfile.TemporaryDirectory() as base:
            metadata, code = self.export(api, Path(base) / "export")
        self.assertEqual(code, 2)
        self.assertFalse(metadata["complete"])
        self.assertEqual(metadata["message_count"], 1)

    def test_existing_directory_is_preserved(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as base:
            marker = Path(base) / "unchanged.txt"
            marker.write_text("keep")
            with self.assertRaises(FileExistsError):
                self.export(api, base)
            self.assertEqual(marker.read_text(), "keep")


class ThreadAndPermissionTests(unittest.TestCase):
    def test_category_derives_guild_and_filters_direct_children(self):
        api = FakeAPI()
        api.data["/channels/10"] = channel("10", 4, None)
        api.data["/guilds/1/channels"] = [channel("21", 2), channel("20"),
                                         channel("22", parent="11"), channel("23", 11, "20")]
        result = R.Reader(api).category_channels("10")
        self.assertEqual(result["guild_id"], "1")
        self.assertEqual([c["id"] for c in result["channels"]], ["20", "21"])

    def test_public_archives_use_timestamp_even_after_short_page(self):
        api = FakeAPI()
        route = "/channels/20/threads/archived/public"
        newest, older = "2026-11-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00"
        def pages(params):
            if "before" not in params:
                return {"threads": [dict(channel("50", 11, "20"), thread_metadata={"archive_timestamp": newest})], "has_more": True}
            self.assertEqual(params["before"], newest)
            return {"threads": [dict(channel("40", 11, "20"), thread_metadata={"archive_timestamp": older})], "has_more": False}
        api.data[route] = pages
        self.assertEqual([t["id"] for t in R.Reader(api).archived_threads(route)], ["50", "40"])

    def test_joined_private_archives_use_id_not_timestamp(self):
        api = FakeAPI()
        route = "/channels/20/users/@me/threads/archived/private"
        api.data[route] = lambda p: ({"threads": [channel("50", 12, "20")], "has_more": True}
                                     if "before" not in p else {"threads": [], "has_more": False})
        self.assertEqual([t["id"] for t in R.Reader(api).archived_threads(route, joined=True)], ["50"])
        self.assertEqual(api.calls[-1][1]["before"], "50")

    def test_archive_empty_has_more_is_error(self):
        api = FakeAPI()
        route = "/channels/20/threads/archived/public"
        api.data[route] = {"threads": [], "has_more": True}
        with self.assertRaises(R.ReaderError):
            list(R.Reader(api).archived_threads(route))

    def test_thread_discovery_deduplicates_and_tracks_partial_failure(self):
        api = FakeAPI()
        public = channel("50", 11, "20")
        api.data["/guilds/1/threads/active"] = {"threads": [public, channel("51", 11, "21")]}
        api.data["/channels/20/threads/archived/public"] = {"threads": [public], "has_more": False}
        api.data["/channels/20/users/@me/threads/archived/private"] = R.APIError(403, "archive")
        warnings = []
        ids, complete = R.Reader(api).discover_threads(channel(), warnings)
        self.assertEqual(ids, ["50"])
        self.assertFalse(complete)
        self.assertTrue(warnings)

    def test_private_all_only_with_manage_threads(self):
        for manage in [False, True]:
            with self.subTest(manage=manage):
                api = FakeAPI(permissions=R.VIEW_CHANNEL | R.READ_HISTORY | (R.MANAGE_THREADS if manage else 0))
                api.data["/guilds/1/threads/active"] = {"threads": []}
                for route in ["/channels/20/threads/archived/public", "/channels/20/users/@me/threads/archived/private", "/channels/20/threads/archived/private"]:
                    api.data[route] = {"threads": [], "has_more": False}
                R.Reader(api).discover_threads(channel(), [])
                self.assertEqual(any(route == "/channels/20/threads/archived/private" for route, _ in api.calls), manage)

    def test_role_and_member_overwrite_order(self):
        api = FakeAPI()
        api.data["/guilds/1/roles"].extend([{"id": "70", "permissions": "0"}, {"id": "71", "permissions": "0"}])
        api.data["/guilds/1/members/9"]["roles"] = ["70", "71"]
        overwrites = [{"id": "1", "type": 0, "deny": str(R.READ_HISTORY), "allow": "0"},
                      {"id": "70", "type": 0, "deny": str(R.READ_HISTORY), "allow": "0"},
                      {"id": "71", "type": 0, "deny": "0", "allow": str(R.READ_HISTORY)}]
        reader = R.Reader(api)
        self.assertTrue(reader.effective_permissions(channel(overwrites=overwrites)) & R.READ_HISTORY)
        overwrites.append({"id": "9", "type": 1, "deny": str(R.READ_HISTORY), "allow": "0"})
        self.assertFalse(reader.effective_permissions(channel(overwrites=overwrites)) & R.READ_HISTORY)

    def test_thread_uses_parent_overwrites(self):
        api = FakeAPI()
        api.data["/channels/20"]["permission_overwrites"] = [{"id": "1", "type": 0, "allow": "0", "deny": str(R.READ_HISTORY)}]
        self.assertFalse(R.Reader(api).effective_permissions(channel("50", 11, "20")) & R.READ_HISTORY)


class FakeResponse:
    def __init__(self, data, headers=None):
        self.data = data
        self.headers = headers or {}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps(self.data).encode()


class HTTPAndCredentialTests(unittest.TestCase):
    def test_requests_are_get_only_and_authorization_not_url(self):
        opener = mock.Mock()
        opener.open.return_value = FakeResponse([])
        client = R.DiscordAPI("synthetic-token", opener=opener, sleeper=lambda _: None)
        client.get("/channels/20/messages", {"limit": 100})
        req = opener.open.call_args.args[0]
        self.assertEqual(req.get_method(), "GET")
        self.assertEqual(req.get_header("Authorization"), "Bot synthetic-token")
        self.assertNotIn("synthetic-token", req.full_url)
        self.assertIsNone(req.data)
        with self.assertRaises(R.ReaderError): client.get("https://evil.invalid/token")

    def test_429_json_delay_honored_then_success(self):
        opener = mock.Mock()
        opener.open.side_effect = [urllib.error.HTTPError("url", 429, "rate", {}, io.BytesIO(b'{"retry_after":2.5}')),
                                   FakeResponse({"ok": True})]
        sleeps = []
        client = R.DiscordAPI("synthetic-token", opener=opener, sleeper=sleeps.append)
        self.assertEqual(client.get("/users/@me"), {"ok": True})
        self.assertGreaterEqual(sum(sleeps), 2.5)
        self.assertEqual(opener.open.call_count, 2)

    def test_429_header_delay_honored_when_body_is_not_json(self):
        opener = mock.Mock()
        opener.open.side_effect = [urllib.error.HTTPError("url", 429, "rate", {"Retry-After": "3"}, io.BytesIO(b'not json')),
                                   FakeResponse([])]
        sleeps = []
        R.DiscordAPI("synthetic-token", opener=opener, sleeper=sleeps.append).get("/users/@me")
        self.assertGreaterEqual(sum(sleeps), 3)

    def test_401_is_not_retried_and_error_does_not_echo_body(self):
        opener = mock.Mock()
        opener.open.side_effect = urllib.error.HTTPError("url", 401, "unauthorized", {}, io.BytesIO(b'synthetic-token'))
        sleeps = []
        with self.assertRaises(R.APIError) as caught:
            R.DiscordAPI("synthetic-token", opener=opener, sleeper=sleeps.append).get("/users/@me")
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(sleeps, [])
        self.assertNotIn("synthetic-token", str(caught.exception))

    def test_bounded_retries_preserve_failure(self):
        opener = mock.Mock()
        opener.open.side_effect = lambda *a, **k: (_ for _ in ()).throw(
            urllib.error.HTTPError("url", 503, "unavailable", {}, io.BytesIO(b'{}')))
        with self.assertRaises(R.APIError):
            R.DiscordAPI("synthetic-token", opener=opener, sleeper=lambda _: None).get("/users/@me")
        self.assertEqual(opener.open.call_count, 6)

    def test_dotenv_not_executed_and_environment_takes_precedence(self):
        with tempfile.TemporaryDirectory() as base:
            path = Path(base) / ".env"
            path.write_text("DISCORD_BOT_TOKEN='literal-$(do-not-run)'\n")
            path.chmod(0o600)
            self.assertEqual(R.load_token(path, environ={})[0], "literal-$(do-not-run)")
            self.assertEqual(R.load_token(path, environ={"FIESTA_RELAY_BOT_TOKEN": "environment-token"})[0], "environment-token")
            if os.name == "posix":
                path.chmod(0o644)
                with self.assertRaises(R.ReaderError): R.load_token(path, environ={})

    def test_regular_user_token_not_accepted_as_bot(self):
        api = FakeAPI()
        api.data["/users/@me"]["bot"] = False
        with self.assertRaises(R.ReaderError): R.Reader(api).identify()

    def test_redirects_cannot_forward_authorization(self):
        self.assertIsNone(R.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil.invalid"))


if __name__ == "__main__":
    unittest.main()
