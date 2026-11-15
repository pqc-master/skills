"""Offline first-time setup tests using isolated files and synthetic credentials."""
import contextlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("discord_setup", SCRIPTS / "discord_setup.py")
setup_module = importlib.util.module_from_spec(spec)
with mock.patch.object(sys, "path", [str(SCRIPTS)] + sys.path):
    spec.loader.exec_module(setup_module)
S = setup_module

GUILD = "1563153526283051008"
CHANNEL = "1570317863984701442"
WEBHOOK = "1570317863984701490"
BOT = "1570317863984701491"
OLD_TOKEN = "synthetic_old_bot_token"
NEW_TOKEN = "synthetic_new_bot_token"
ENV_TOKEN = "synthetic_environment_bot_token"
HOOK_SECRET = "synthetic_webhook_token_" + "X" * 60
HOOK_URL = "https://discord.com/api/v10/webhooks/" + WEBHOOK + "/" + HOOK_SECRET


def bot_status():
    return {"bot_id": BOT, "username": "PQC Reader", "bot_authentication": "ok",
            "message_content_intent": True, "warning": None, "channel_access": "not tested"}


class ReaderFactory:
    def __init__(self, error=None):
        self.tokens = []
        self.error = error
        self.doctor_calls = 0

    def __call__(self, token):
        self.tokens.append(token)
        return self

    def doctor(self):
        self.doctor_calls += 1
        if self.error is not None:
            raise self.error
        return bot_status()


class WebhookAPI:
    def __init__(self):
        self.calls = []

    def get(self, url):
        self.calls.append(("GET", url))
        return {"id": WEBHOOK, "guild_id": GUILD, "channel_id": CHANNEL,
                "type": 1, "token": HOOK_SECRET, "name": "team hook"}

    def execute(self, *args, **kwargs):
        raise AssertionError("Setup must never post a Discord message")


class IsolatedSetup(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.patchers = [mock.patch.object(Path, "home", return_value=self.home),
                         mock.patch.dict(os.environ, {}, clear=True)]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.bot_path = self.home / ".config/discord-channel-reader/.env"
        self.publish_path = self.bot_path.with_name("publisher.json")
        self.legacy_path = self.home / ".fiesta-discord/.env"

    def write_private(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)

    def assert_no_secrets(self, value):
        rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        for secret in (OLD_TOKEN, NEW_TOKEN, ENV_TOKEN, HOOK_SECRET, HOOK_URL):
            self.assertNotIn(secret, rendered)

    def capture(self, function, *args, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = function(*args, **kwargs)
        self.assert_no_secrets(out.getvalue() + err.getvalue())
        self.assert_no_secrets(result)
        return result

    def publisher_config(self):
        return {"version": 1, "display_name": "민영", "webhooks": {
            CHANNEL: {"guild_id": GUILD, "webhook_id": WEBHOOK, "url": HOOK_URL},
        }}


class BotSetupTests(IsolatedSetup):
    def test_new_token_is_hidden_validated_then_saved_privately(self):
        factory = ReaderFactory()
        with mock.patch.object(S.getpass, "getpass", return_value=NEW_TOKEN) as prompt:
            result = self.capture(S.setup_bot, reader_factory=factory)
        prompt.assert_called_once()
        self.assertEqual(factory.tokens, [NEW_TOKEN])
        self.assertEqual(factory.doctor_calls, 1)
        self.assertEqual(S.reader.load_token(str(self.bot_path), environ={})[0], NEW_TOKEN)
        self.assertEqual(result["status"], "configured")
        self.assertTrue(result["credential_saved"])
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.bot_path.stat().st_mode), 0o600)

    def test_existing_dedicated_token_is_reused_without_prompts(self):
        self.write_private(self.bot_path, "DISCORD_BOT_TOKEN=" + OLD_TOKEN + "\n")
        original = self.bot_path.read_bytes()
        factory = ReaderFactory()
        with mock.patch.object(S.getpass, "getpass", side_effect=AssertionError("Unexpected secret prompt")), \
                mock.patch("builtins.input", side_effect=AssertionError("Unexpected reuse prompt")):
            result = self.capture(S.setup_bot, reader_factory=factory)
        self.assertEqual(factory.tokens, [OLD_TOKEN])
        self.assertEqual(result["status"], "reused")
        self.assertFalse(result["credential_saved"])
        self.assertEqual(self.bot_path.read_bytes(), original)

    def test_existing_environment_token_is_reused_without_copying_secret(self):
        factory = ReaderFactory()
        with mock.patch.dict(os.environ, {"DISCORD_BOT_TOKEN": ENV_TOKEN}, clear=True), \
                mock.patch("builtins.input", return_value=""), \
                mock.patch.object(S.getpass, "getpass", side_effect=AssertionError("Unexpected secret prompt")):
            result = self.capture(S.setup_bot, reader_factory=factory)
        self.assertEqual(factory.tokens, [ENV_TOKEN])
        self.assertEqual(result["status"], "reused")
        self.assertEqual(result["credential_source"], "process environment")
        self.assertFalse(self.bot_path.exists())

    def test_legacy_token_is_reused_without_moving_or_exposing_it(self):
        self.write_private(self.legacy_path, "FIESTA_RELAY_BOT_TOKEN=" + OLD_TOKEN + "\n")
        original = self.legacy_path.read_bytes()
        factory = ReaderFactory()
        with mock.patch("builtins.input", return_value="y"), \
                mock.patch.object(S.getpass, "getpass", side_effect=AssertionError("Unexpected secret prompt")):
            result = self.capture(S.setup_bot, reader_factory=factory)
        self.assertEqual(factory.tokens, [OLD_TOKEN])
        self.assertEqual(result["status"], "reused")
        self.assertEqual(self.legacy_path.read_bytes(), original)
        self.assertFalse(self.bot_path.exists())

    def test_environment_priority_is_reported_instead_of_claiming_file_token(self):
        self.write_private(self.bot_path, "DISCORD_BOT_TOKEN=" + OLD_TOKEN + "\n")
        factory = ReaderFactory()
        with mock.patch.dict(os.environ, {"FIESTA_RELAY_BOT_TOKEN": ENV_TOKEN}, clear=True), \
                mock.patch("builtins.input", return_value="y") as reuse_prompt, \
                mock.patch.object(S.getpass, "getpass", side_effect=AssertionError("Unexpected secret prompt")):
            result = self.capture(S.setup_bot, reader_factory=factory)
        reuse_prompt.assert_called_once()
        self.assertEqual(factory.tokens, [ENV_TOKEN])
        self.assertEqual(result["credential_source"], "process environment")
        self.assertIn(OLD_TOKEN, self.bot_path.read_text())

    def test_replacing_token_with_overriding_environment_is_refused(self):
        self.write_private(self.bot_path, "DISCORD_BOT_TOKEN=" + OLD_TOKEN + "\n")
        original = self.bot_path.read_bytes()
        for key in ("DISCORD_BOT_TOKEN", "FIESTA_RELAY_BOT_TOKEN"):
            with self.subTest(variable=key):
                factory = ReaderFactory()
                with mock.patch.dict(os.environ, {key: ENV_TOKEN}, clear=True), \
                        mock.patch.object(S.getpass, "getpass", side_effect=AssertionError("Must refuse before prompting")):
                    with self.assertRaises(S.SetupError) as caught:
                        S.setup_bot(replace_token=True, reader_factory=factory)
                self.assert_no_secrets(str(caught.exception))
                self.assertEqual(factory.tokens, [])
                self.assertEqual(self.bot_path.read_bytes(), original)

    def test_invalid_new_token_does_not_overwrite_existing_configuration(self):
        self.write_private(self.bot_path, "# keep\nDISCORD_BOT_TOKEN=" + OLD_TOKEN + "\nOTHER=value\n")
        original = self.bot_path.read_bytes()
        factory = ReaderFactory(error=S.reader.APIError(401, "/users/@me"))
        with mock.patch.object(S.getpass, "getpass", return_value=NEW_TOKEN):
            with self.assertRaises((S.SetupError, S.reader.ReaderError)) as caught:
                S.setup_bot(replace_token=True, reader_factory=factory)
        self.assert_no_secrets(str(caught.exception))
        self.assertEqual(self.bot_path.read_bytes(), original)

    def test_successful_replacement_preserves_unrelated_env_lines(self):
        self.write_private(self.bot_path, "# preserved comment\nDISCORD_BOT_TOKEN=" + OLD_TOKEN + "\nOTHER=keep-this\n")
        factory = ReaderFactory()
        with mock.patch.object(S.getpass, "getpass", return_value=NEW_TOKEN):
            self.capture(S.setup_bot, replace_token=True, reader_factory=factory)
        saved = self.bot_path.read_text()
        self.assertIn("# preserved comment\n", saved)
        self.assertIn("OTHER=keep-this\n", saved)
        self.assertEqual(S.reader.load_token(str(self.bot_path), environ={})[0], NEW_TOKEN)

    def test_declining_legacy_token_saves_new_token_without_changing_legacy(self):
        self.write_private(self.legacy_path, "FIESTA_RELAY_BOT_TOKEN=" + OLD_TOKEN + "\n")
        original = self.legacy_path.read_bytes()
        factory = ReaderFactory()
        with mock.patch("builtins.input", return_value="n"), \
                mock.patch.object(S.getpass, "getpass", return_value=NEW_TOKEN):
            result = self.capture(S.setup_bot, reader_factory=factory)
        self.assertEqual(factory.tokens, [OLD_TOKEN, NEW_TOKEN])
        self.assertEqual(result["status"], "configured")
        self.assertEqual(self.legacy_path.read_bytes(), original)
        self.assertEqual(S.reader.load_token(str(self.bot_path), environ={})[0], NEW_TOKEN)

    def test_incomplete_bot_response_does_not_leak_or_replace_saved_token(self):
        self.write_private(self.bot_path, "DISCORD_BOT_TOKEN=" + OLD_TOKEN + "\n")
        original = self.bot_path.read_bytes()
        factory = ReaderFactory(error=http.client.IncompleteRead(NEW_TOKEN.encode("ascii")))
        with mock.patch.object(S, "_reader_for_token", side_effect=factory), \
                mock.patch.object(S.getpass, "getpass", return_value=NEW_TOKEN):
            code = self.capture(S.main, ["--replace-token", "--skip-publish"])
        self.assertEqual(code, 1)
        self.assertEqual(factory.tokens, [NEW_TOKEN])
        self.assertEqual(self.bot_path.read_bytes(), original)


class PublisherSetupTests(IsolatedSetup):
    def test_existing_name_and_webhooks_are_reused_without_reentering_secrets(self):
        expected = self.publisher_config()
        S.publisher.save_config(expected, self.publish_path)
        api = WebhookAPI()
        with mock.patch.object(S.getpass, "getpass", side_effect=AssertionError("Unexpected webhook prompt")), \
                mock.patch("builtins.input", return_value=""):
            result = self.capture(S.setup_publisher, api=api)
        self.assertEqual(S.publisher.load_config(self.publish_path), expected)
        self.assertEqual(result["status"], "reused")
        self.assertFalse(any(call[0] == "POST" for call in api.calls))

    def test_name_override_preserves_existing_webhook_bindings(self):
        expected = self.publisher_config()
        S.publisher.save_config(expected, self.publish_path)
        api = WebhookAPI()
        with mock.patch.object(S.getpass, "getpass", side_effect=AssertionError("Unexpected webhook prompt")), \
                mock.patch("builtins.input", return_value=""):
            self.capture(S.setup_publisher, name="철수", api=api)
        result = S.publisher.load_config(self.publish_path)
        self.assertEqual(result["display_name"], "철수")
        self.assertEqual(result["webhooks"], expected["webhooks"])

    def test_new_publisher_collects_name_and_hidden_webhook_without_posting(self):
        api = WebhookAPI()
        with mock.patch("builtins.input", return_value="민영"), \
                mock.patch.object(S.getpass, "getpass", return_value=HOOK_URL) as secret_prompt:
            result = self.capture(S.setup_publisher, api=api)
        self.assertEqual(result["status"], "configured")
        secret_prompt.assert_called_once()
        self.assertEqual(S.publisher.load_config(self.publish_path), self.publisher_config())
        self.assertTrue(api.calls)
        self.assertTrue(all(call[0] == "GET" for call in api.calls))


class ProfileSetupTests(IsolatedSetup):
    def test_new_profile_asks_only_for_name_and_saves_without_webhook(self):
        with mock.patch("builtins.input", return_value="민영") as prompt, \
                mock.patch.object(S.getpass, "getpass", side_effect=AssertionError("No secret needed for name setup")), \
                mock.patch.object(S.publisher, "WebhookAPI", side_effect=AssertionError("Profile setup must stay offline")):
            result = self.capture(S.setup_profile)
        prompt.assert_called_once()
        self.assertEqual(result["display_name"], "민영")
        self.assertEqual(S.publisher.load_config(self.publish_path),
                         {"version": 1, "display_name": "민영", "webhooks": {}})
        self.assertFalse(self.bot_path.exists())

    def test_existing_profile_reuse_needs_no_prompt_or_write(self):
        expected = self.publisher_config()
        S.publisher.save_config(expected, self.publish_path)
        original = self.publish_path.read_bytes()
        with mock.patch("builtins.input", side_effect=AssertionError("Saved name must be reused")), \
                mock.patch.object(S.publisher, "save_config", side_effect=AssertionError("No rewrite needed")):
            result = self.capture(S.setup_profile)
        self.assertEqual(result["status"], "reused")
        self.assertEqual(self.publish_path.read_bytes(), original)

    def test_name_change_preserves_existing_advanced_webhooks(self):
        expected = self.publisher_config()
        S.publisher.save_config(expected, self.publish_path)
        with mock.patch.object(S.publisher, "WebhookAPI", side_effect=AssertionError("No API required")):
            self.capture(S.setup_profile, name="철수")
        actual = S.publisher.load_config(self.publish_path)
        self.assertEqual(actual["display_name"], "철수")
        self.assertEqual(actual["webhooks"], expected["webhooks"])

    def test_invalid_name_preserves_existing_profile(self):
        S.publisher.save_config(self.publisher_config(), self.publish_path)
        original = self.publish_path.read_bytes()
        with self.assertRaises(S.publisher.PublisherError):
            S.setup_profile(name=" ")
        self.assertEqual(self.publish_path.read_bytes(), original)


class SetupFlowTests(IsolatedSetup):
    def test_skip_bot_never_reads_bot_credentials(self):
        with mock.patch.object(S, "setup_bot", side_effect=AssertionError("Bot stage must be skipped")), \
                mock.patch.object(S, "setup_profile", return_value={"status": "reused"}) as stage, \
                mock.patch.object(S, "setup_publisher", side_effect=AssertionError("No default webhook setup")), \
                mock.patch("builtins.input", side_effect=AssertionError("No webhook opt-in prompt")):
            result, code = self.capture(S.run_setup, skip_bot=True)
        self.assertEqual(code, 0)
        self.assertTrue(result["complete"])
        stage.assert_called_once()

    def test_skip_publish_never_loads_or_requests_webhook(self):
        with mock.patch.object(S, "setup_bot", return_value={"status": "reused"}) as stage, \
                mock.patch.object(S, "setup_profile", side_effect=AssertionError("Profile stage must be skipped")), \
                mock.patch.object(S, "setup_publisher", side_effect=AssertionError("Publisher stage must be skipped")):
            result, code = self.capture(S.run_setup, skip_publish=True)
        self.assertEqual(code, 0)
        self.assertTrue(result["complete"])
        stage.assert_called_once()

    def test_profile_failure_keeps_successful_bot_setup_and_reports_partial(self):
        def configure_bot(**kwargs):
            S.save_bot_token(NEW_TOKEN, self.bot_path)
            return {"status": "configured", "credential_saved": True, **bot_status()}
        with mock.patch.object(S, "setup_bot", side_effect=configure_bot), \
                mock.patch.object(S, "setup_profile", side_effect=S.publisher.PublisherError("Invalid display name")):
            result, code = self.capture(S.run_setup)
        self.assertNotEqual(code, 0)
        self.assertFalse(result["complete"])
        self.assertEqual(S.reader.load_token(str(self.bot_path), environ={})[0], NEW_TOKEN)
        self.assertIn("configured", json.dumps(result))

    def test_default_flow_collects_token_and_name_without_webhook_questions(self):
        factory = ReaderFactory()
        with mock.patch.object(S, "_reader_for_token", side_effect=factory), \
                mock.patch.object(S.getpass, "getpass", return_value=NEW_TOKEN) as secret_prompt, \
                mock.patch("builtins.input", return_value="민영") as name_prompt, \
                mock.patch.object(S, "setup_publisher", side_effect=AssertionError("No default webhook setup")), \
                mock.patch.object(S.publisher, "WebhookAPI", side_effect=AssertionError("No webhook API needed")):
            result, code = self.capture(S.run_setup)
        self.assertEqual(code, 0)
        self.assertTrue(result["complete"])
        self.assertFalse(result["message_sent"])
        secret_prompt.assert_called_once()
        name_prompt.assert_called_once()
        self.assertEqual(S.reader.load_token(str(self.bot_path), environ={})[0], NEW_TOKEN)
        self.assertEqual(S.publisher.load_config(self.publish_path),
                         {"version": 1, "display_name": "민영", "webhooks": {}})

    def test_explicit_advanced_flag_keeps_optional_webhook_flow(self):
        with mock.patch.object(S, "setup_bot", side_effect=AssertionError("Bot stage must be skipped")), \
                mock.patch.object(S, "setup_publisher", return_value={"status": "configured"}) as stage, \
                mock.patch.object(S, "setup_profile", side_effect=AssertionError("Advanced flow owns name setup")), \
                mock.patch("builtins.input", return_value="y") as prompt:
            code = self.capture(S.main, ["--skip-bot", "--with-webhook", "--name", "민영"])
        self.assertEqual(code, 0)
        prompt.assert_called_once()
        stage.assert_called_once_with(name="민영", guild_id=GUILD)


if __name__ == "__main__":
    unittest.main()
