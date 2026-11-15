"""Offline desktop settings tests; no user credentials, display, or network needed."""
import contextlib
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
import urllib.request


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("discord_desktop", SCRIPTS / "discord_desktop.py")
D = importlib.util.module_from_spec(spec)
with mock.patch.object(sys, "path", [str(SCRIPTS)] + sys.path):
    spec.loader.exec_module(D)

GUILD = "1563153526283051008"
CHANNEL = "1570317863984701442"
OTHER_CHANNEL = "1570317863984701443"
WEBHOOK = "1570317863984701490"
OTHER_WEBHOOK = "1570317863984701492"
BOT = "1570317863984701491"
OLD_TOKEN = "synthetic_desktop_old_token"
NEW_TOKEN = "synthetic_desktop_new_token"
ENV_TOKEN = "synthetic_desktop_environment_token"
HOOK_SECRET = "synthetic_desktop_webhook_token_" + "X" * 48
HOOK_URL = "https://discord.com/api/v10/webhooks/" + WEBHOOK + "/" + HOOK_SECRET
OTHER_URL = "https://discord.com/api/v10/webhooks/" + OTHER_WEBHOOK + "/" + HOOK_SECRET


class ReaderFactory:
    def __init__(self, error=None):
        self.error = error
        self.tokens = []

    def __call__(self, token):
        self.tokens.append(token)
        return self

    def doctor(self):
        if self.error:
            raise self.error
        return {"bot_id": BOT, "username": "PQC Reader", "bot_authentication": "ok",
                "message_content_intent": True, "warning": None, "channel_access": "not tested"}


class WebhookAPI:
    def __init__(self, error=None, channel_id=CHANNEL, webhook_id=WEBHOOK, guild_id=GUILD):
        self.error = error
        self.calls = []
        self.channel_id = channel_id
        self.webhook_id = webhook_id
        self.guild_id = guild_id

    def get(self, url):
        self.calls.append(("GET", url))
        if self.error:
            raise self.error
        return {"type": 1, "id": self.webhook_id, "guild_id": self.guild_id,
                "channel_id": self.channel_id, "token": HOOK_SECRET, "url": url}

    def execute(self, *args, **kwargs):
        raise AssertionError("Desktop settings must never post a Discord message")


class DesktopSettingsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="discord-desktop-test-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.config_dir = self.home / "settings"
        self.bot_path = self.config_dir / ".env"
        self.publisher_path = self.config_dir / "publisher.json"
        # Keep Windows/OpenSSL OS paths; all application environment values remain isolated.
        system_environment = {key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ}
        for patcher in (mock.patch.object(Path, "home", return_value=self.home),
                        mock.patch.object(sys, "path", [str(SCRIPTS)] + sys.path),
                        mock.patch.dict(os.environ, system_environment, clear=True),
                        mock.patch.object(urllib.request.OpenerDirector, "open",
                                          side_effect=AssertionError("Offline tests must not reach the network"))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_private(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)

    def configured_publisher(self):
        return {"version": 1, "display_name": "민영", "webhooks": {
            CHANNEL: {"guild_id": GUILD, "webhook_id": WEBHOOK, "url": HOOK_URL},
            OTHER_CHANNEL: {"guild_id": GUILD, "webhook_id": OTHER_WEBHOOK, "url": OTHER_URL},
        }}

    def seed(self):
        self.write_private(self.bot_path, "# keep\nDISCORD_BOT_TOKEN=" + OLD_TOKEN + "\nOTHER=keep\n")
        D.publisher.save_config(self.configured_publisher(), self.publisher_path)

    def service(self, factory=None, api=None, environ=None):
        self.factory = factory if factory is not None else ReaderFactory()
        self.api = api if api is not None else WebhookAPI()
        return D.SetupService(config_dir=self.config_dir, reader_factory=self.factory,
                              webhook_api=self.api, environ={} if environ is None else environ)

    def assert_no_secrets(self, value):
        output = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        for secret in (OLD_TOKEN, NEW_TOKEN, ENV_TOKEN, HOOK_SECRET, HOOK_URL, OTHER_URL):
            self.assertNotIn(secret, output)

    def capture(self, function, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = function(**kwargs)
        self.assert_no_secrets(out.getvalue() + err.getvalue())
        self.assert_no_secrets(result)
        return result

    def test_inspect_projects_safe_settings_without_network_or_secret_fields(self):
        self.seed()
        service = self.service()
        state = self.capture(service.inspect)
        self.assertEqual(state["display_name"], "민영")
        self.assertEqual(set(state["channel_ids"]), {CHANNEL, OTHER_CHANNEL})
        self.assertEqual(state["category_id"], "1570317863984701441")
        self.assertEqual(self.factory.tokens, [])
        self.assertEqual(self.api.calls, [])

    def test_explicit_token_view_reads_local_value_without_output_network_or_writes(self):
        self.seed()
        original_bot = self.bot_path.read_bytes()
        original_publisher = self.publisher_path.read_bytes()
        service = self.service()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(D.setup, "save_bot_token", side_effect=AssertionError("Viewing must not save")), \
                mock.patch.object(D.publisher, "save_config", side_effect=AssertionError("Viewing must not save")):
            token = service.current_bot_token()
        self.assertEqual(token, OLD_TOKEN)
        self.assertEqual(out.getvalue() + err.getvalue(), "")
        self.assertEqual(self.factory.tokens, [])
        self.assertEqual(self.api.calls, [])
        self.assertEqual(self.bot_path.read_bytes(), original_bot)
        self.assertEqual(self.publisher_path.read_bytes(), original_publisher)
        self.capture(service.inspect)

    def test_explicit_token_view_uses_the_same_source_priority_as_authentication(self):
        legacy = self.home / ".fiesta-discord/.env"
        self.write_private(legacy, "DISCORD_BOT_TOKEN=" + OLD_TOKEN + "\n")
        service = D.SetupService(config_dir=self.config_dir, environ={}, use_legacy=True)
        self.assertEqual(service.current_bot_token(), OLD_TOKEN)
        self.write_private(self.bot_path, "DISCORD_BOT_TOKEN=" + NEW_TOKEN + "\n")
        self.assertEqual(service.current_bot_token(), NEW_TOKEN)
        for variable in ("DISCORD_BOT_TOKEN", "FIESTA_RELAY_BOT_TOKEN"):
            with self.subTest(variable=variable):
                service = D.SetupService(config_dir=self.config_dir, environ={variable: ENV_TOKEN}, use_legacy=True)
                self.assertEqual(service.current_bot_token(), ENV_TOKEN)
                self.capture(service.inspect)

    def test_explicit_token_view_missing_state_does_not_create_configuration(self):
        service = self.service()
        self.assertIsNone(service.current_bot_token())
        self.assertFalse(self.config_dir.exists())
        self.assertEqual(self.factory.tokens, [])
        self.assertEqual(self.api.calls, [])

    def test_explicit_token_view_sanitizes_errors_with_credential_values(self):
        service = self.service()
        for error in (OSError(OLD_TOKEN), D.reader.ReaderError(NEW_TOKEN)):
            with self.subTest(error_type=type(error).__name__), \
                    mock.patch.object(service, "_load_bot", side_effect=error):
                with self.assertRaises(D.DesktopError) as caught:
                    service.current_bot_token()
                self.assert_no_secrets(str(caught.exception))

    def test_blank_fields_preserve_saved_credentials_and_webhook_bindings(self):
        self.seed()
        original_bot = self.bot_path.read_bytes()
        original_publisher = self.publisher_path.read_bytes()
        service = self.service()
        result = self.capture(service.save)
        self.assertTrue(result["complete"])
        self.assertFalse(result["message_sent"])
        self.assertEqual(self.bot_path.read_bytes(), original_bot)
        self.assertEqual(self.publisher_path.read_bytes(), original_publisher)
        self.assertEqual(self.factory.tokens, [OLD_TOKEN])
        self.assertTrue(all(method == "GET" for method, _ in self.api.calls))

    def test_new_values_are_validated_and_saved_privately(self):
        service = self.service()
        result = self.capture(service.save, bot_token=NEW_TOKEN, display_name="민영", webhook_url=HOOK_URL)
        self.assertTrue(result["complete"])
        self.assertFalse(result["message_sent"])
        self.assertEqual(self.factory.tokens, [NEW_TOKEN])
        self.assertEqual(self.api.calls, [("GET", HOOK_URL)])
        self.assertEqual(D.reader.load_token(str(self.bot_path), environ={})[0], NEW_TOKEN)
        saved = D.publisher.load_config(self.publisher_path)
        self.assertEqual(saved["display_name"], "민영")
        self.assertEqual(saved["webhooks"][CHANNEL]["url"], HOOK_URL)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.bot_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.publisher_path.stat().st_mode), 0o600)

    def test_name_can_be_saved_before_webhook_and_reused_when_channel_is_added(self):
        service = self.service()
        result = self.capture(service.save, bot_token=NEW_TOKEN, display_name="민영")
        self.assertTrue(result["complete"])
        self.assertFalse(result["message_sent"])
        self.assertEqual(self.api.calls, [])
        saved = D.publisher.load_config(self.publisher_path)
        self.assertEqual(saved["display_name"], "민영")
        self.assertEqual(saved["webhooks"], {})
        result = self.capture(service.save, webhook_url=HOOK_URL)
        self.assertTrue(result["complete"])
        saved = D.publisher.load_config(self.publisher_path)
        self.assertEqual(saved["display_name"], "민영")
        self.assertEqual(saved["webhooks"][CHANNEL]["url"], HOOK_URL)
        self.assertEqual(self.api.calls, [("GET", HOOK_URL)])

    def test_name_only_change_preserves_all_webhook_secrets(self):
        self.seed()
        original_bot = self.bot_path.read_bytes()
        service = self.service()
        result = self.capture(service.save, display_name="철수")
        self.assertTrue(result["complete"])
        saved = D.publisher.load_config(self.publisher_path)
        self.assertEqual(saved["display_name"], "철수")
        self.assertEqual(saved["webhooks"], self.configured_publisher()["webhooks"])
        self.assertEqual(self.bot_path.read_bytes(), original_bot)

    def test_rejected_new_token_does_not_overwrite_saved_bot_file(self):
        self.seed()
        original_bot = self.bot_path.read_bytes()
        original_publisher = self.publisher_path.read_bytes()
        service = self.service(factory=ReaderFactory(D.reader.APIError(401, "/users/@me")))
        result = self.capture(service.save, bot_token=NEW_TOKEN)
        self.assertFalse(result["complete"])
        self.assertEqual(self.bot_path.read_bytes(), original_bot)
        self.assertEqual(self.publisher_path.read_bytes(), original_publisher)

    def test_failed_webhook_stage_keeps_old_webhooks_and_reports_saved_bot(self):
        self.seed()
        original_publisher = self.publisher_path.read_bytes()
        service = self.service(api=WebhookAPI(D.publisher.APIError(403)))
        result = self.capture(service.save, bot_token=NEW_TOKEN, display_name="철수", webhook_url=HOOK_URL)
        self.assertFalse(result["complete"])
        self.assertFalse(result["message_sent"])
        self.assertEqual(D.reader.load_token(str(self.bot_path), environ={})[0], NEW_TOKEN)
        self.assertEqual(self.publisher_path.read_bytes(), original_publisher)
        self.assertNotEqual(result["bot"]["status"], "failed")
        self.assertEqual(result["publishing"]["status"], "failed")

    def test_wrong_server_webhook_does_not_replace_saved_binding(self):
        self.seed()
        original = self.publisher_path.read_bytes()
        service = self.service(api=WebhookAPI(guild_id="999999999999999999"))
        result = self.capture(service.save, webhook_url=HOOK_URL)
        self.assertFalse(result["complete"])
        self.assertEqual(self.publisher_path.read_bytes(), original)

    def test_environment_token_has_priority_without_claiming_local_file_token(self):
        self.seed()
        original = self.bot_path.read_bytes()
        service = self.service(environ={"FIESTA_RELAY_BOT_TOKEN": ENV_TOKEN})
        state = self.capture(service.inspect)
        self.assertIn("environment", state["bot_source"])
        result = self.capture(service.save)
        self.assertTrue(result["complete"])
        self.assertEqual(self.factory.tokens, [ENV_TOKEN])
        self.assertEqual(self.bot_path.read_bytes(), original)

    def test_environment_override_blocks_misleading_new_local_token_save(self):
        self.seed()
        original = self.bot_path.read_bytes()
        service = self.service(environ={"DISCORD_BOT_TOKEN": ENV_TOKEN})
        result = self.capture(service.save, bot_token=NEW_TOKEN)
        self.assertFalse(result["complete"])
        self.assertEqual(self.bot_path.read_bytes(), original)
        self.assertNotIn(NEW_TOKEN, self.factory.tokens)

    def test_invalid_webhook_url_is_rejected_before_network_or_persistence(self):
        self.seed()
        original = self.publisher_path.read_bytes()
        service = self.service()
        result = self.capture(service.save, webhook_url="https://attacker.invalid/" + HOOK_SECRET)
        self.assertFalse(result["complete"])
        self.assertEqual(self.api.calls, [])
        self.assertEqual(self.publisher_path.read_bytes(), original)

    def test_malformed_publisher_file_is_not_silently_replaced(self):
        self.write_private(self.bot_path, "DISCORD_BOT_TOKEN=" + OLD_TOKEN + "\n")
        self.write_private(self.publisher_path, '{"broken": "' + HOOK_SECRET)
        original = self.publisher_path.read_bytes()
        service = self.service()
        self.capture(service.inspect)
        result = self.capture(service.save, display_name="민영", webhook_url=HOOK_URL)
        self.assertFalse(result["complete"])
        self.assertEqual(self.publisher_path.read_bytes(), original)
        self.assertEqual(self.api.calls, [])

    def test_invalid_name_does_not_replace_publisher_or_request_webhook(self):
        self.seed()
        original = self.publisher_path.read_bytes()
        service = self.service()
        result = self.capture(service.save, display_name="invalid\nname", webhook_url=HOOK_URL)
        self.assertFalse(result["complete"])
        self.assertEqual(self.publisher_path.read_bytes(), original)
        self.assertEqual(self.api.calls, [])

    def test_explicit_configuration_does_not_fall_back_to_unrelated_home_credentials(self):
        service = self.service()
        with mock.patch.object(Path, "home", side_effect=AssertionError("Explicit config must not consult real home")):
            state = self.capture(service.inspect)
        self.assertEqual(state["channel_ids"], [])
        self.assertEqual(self.factory.tokens, [])
        self.assertEqual(self.api.calls, [])

    def test_unexpected_transport_error_is_sanitized_and_keeps_existing_file(self):
        self.seed()
        original = self.bot_path.read_bytes()
        service = self.service(factory=ReaderFactory(OSError(NEW_TOKEN + " " + HOOK_URL)))
        result = self.capture(service.save, bot_token=NEW_TOKEN)
        self.assertFalse(result["complete"])
        self.assertEqual(self.bot_path.read_bytes(), original)

    def test_install_is_explicit_and_does_not_save_or_validate_credentials(self):
        self.seed()
        original_bot = self.bot_path.read_bytes()
        original_publisher = self.publisher_path.read_bytes()
        installer = mock.Mock(return_value={"skill_path": str(self.home / "installed")})
        factory, api = ReaderFactory(), WebhookAPI()
        service = D.SetupService(config_dir=self.config_dir, reader_factory=factory,
                                 webhook_api=api, environ={}, installer=installer)
        self.capture(service.inspect)
        installer.assert_not_called()
        self.capture(service.install)
        installer.assert_called_once_with()
        self.assertEqual(factory.tokens, [])
        self.assertEqual(api.calls, [])
        self.assertEqual(self.bot_path.read_bytes(), original_bot)
        self.assertEqual(self.publisher_path.read_bytes(), original_publisher)

    def test_installer_failure_does_not_expose_arbitrary_exception_details(self):
        service = D.SetupService(config_dir=self.config_dir, environ={},
                                 installer=mock.Mock(side_effect=OSError(HOOK_URL)))
        with self.assertRaises(D.DesktopError) as caught:
            service.install()
        self.assert_no_secrets(str(caught.exception))


class DesktopSmokeTests(unittest.TestCase):
    def test_smoke_test_does_not_inspect_user_configuration_or_construct_network_clients(self):
        root = mock.MagicMock()
        with mock.patch.object(D, "_create_root", return_value=root), \
                mock.patch.object(D, "_create_smoke_view") as view, \
                mock.patch.object(D, "SetupService", side_effect=AssertionError("Smoke must not load real settings")), \
                mock.patch.object(Path, "home", side_effect=AssertionError("Smoke must not read real home")), \
                mock.patch.object(D.reader, "DiscordAPI", side_effect=AssertionError("Smoke must not use Discord API")), \
                mock.patch.object(D.publisher, "WebhookAPI", side_effect=AssertionError("Smoke must not use webhook API")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status = D.main(["--smoke-test"])
        self.assertEqual(status, 0)
        view.assert_called_once_with(root)
        root.destroy.assert_called_once()

    def test_help_does_not_initialize_gui_or_credentials(self):
        with mock.patch.object(D, "_create_root", side_effect=AssertionError("Help must be headless")), \
                mock.patch.object(Path, "home", side_effect=AssertionError("Help must not read real home")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                D.main(["--help"])
        self.assertEqual(caught.exception.code, 0)


class DesktopPrimaryFormTests(unittest.TestCase):
    def window(self):
        window = object.__new__(D.DiscordDesktop)
        window.busy = False
        window.closed = False
        window.has_current_token = True
        window.token_visible = False
        for name in ("token", "name", "current_token", "token_entry", "current_token_entry",
                     "token_view_button", "name_entry", "save_button", "install_button", "bot_status",
                     "name_status", "root"):
            setattr(window, name, mock.Mock())
        window.token.get.return_value = ""
        window.name.get.return_value = "민영"
        window.service = mock.Mock(installer=lambda: None)
        window.service.current_bot_token.return_value = OLD_TOKEN
        window.service.inspect.return_value = {
            "bot_status": "저장된 봇", "bot_source": "synthetic settings file",
            "publisher_status": "저장된 이름", "display_name": "민영", "errors": [],
        }
        window._append = mock.Mock()
        return window

    def test_save_uses_only_bot_token_and_name_without_channel_or_webhook_field(self):
        window = self.window()
        window.token.get.return_value = NEW_TOKEN
        started = []
        def start(kind, operation):
            started.append(kind)
            operation()
        window._start = start
        window._save()
        self.assertEqual(started, ["save"])
        window.service.save.assert_called_once_with(NEW_TOKEN, "민영")
        window.token.set.assert_called_once_with("")

    def test_busy_state_needs_only_primary_form_fields(self):
        window = self.window()
        window._set_busy(True)
        self.assertTrue(window.busy)
        for widget in (window.token_entry, window.name_entry, window.save_button, window.token_view_button):
            widget.state.assert_called_with(["disabled"])

    def test_current_token_is_only_loaded_on_explicit_show_and_cleared_on_hide(self):
        window = self.window()
        window._refresh_state()
        window.service.current_bot_token.assert_not_called()
        window._toggle_current_token()
        window.service.current_bot_token.assert_called_once_with()
        self.assertTrue(window.token_visible)
        window.current_token.set.assert_called_with(OLD_TOKEN)
        window.current_token_entry.configure.assert_called_with(show="")
        window.token.set.assert_not_called()
        window._append.assert_not_called()
        window._toggle_current_token()
        self.assertFalse(window.token_visible)
        window.current_token.set.assert_called_with("********")
        window.current_token_entry.configure.assert_called_with(show="*")
        self.assertEqual(window.service.current_bot_token.call_count, 1)

    def test_missing_token_has_empty_display_and_disabled_view_button(self):
        window = self.window()
        window.service.inspect.return_value["bot_source"] = None
        window._refresh_state()
        self.assertFalse(window.has_current_token)
        window.current_token.set.assert_called_with("")
        window.token_view_button.state.assert_called_with(["disabled"])
        window.service.current_bot_token.assert_not_called()

    def test_failed_show_keeps_token_hidden_and_logs_only_safe_error(self):
        window = self.window()
        window.service.current_bot_token.side_effect = OSError(OLD_TOKEN)
        window._toggle_current_token()
        self.assertFalse(window.token_visible)
        self.assertNotIn(mock.call(OLD_TOKEN), window.current_token.set.call_args_list)
        window._append.assert_called_once()
        self.assertNotIn(OLD_TOKEN, str(window._append.call_args))

    def test_removed_token_stays_hidden_if_configuration_disappears_before_show(self):
        window = self.window()
        window.service.current_bot_token.return_value = None
        window._toggle_current_token()
        self.assertFalse(window.has_current_token)
        self.assertFalse(window.token_visible)
        window.current_token.set.assert_called_with("")
        window.current_token_entry.configure.assert_called_with(show="*")
        window.token_view_button.state.assert_called_with(["disabled"])
        window.token.set.assert_not_called()

    def test_busy_window_does_not_reveal_tokens(self):
        window = self.window()
        window.busy = True
        window._toggle_current_token()
        window.service.current_bot_token.assert_not_called()
        window.current_token.set.assert_not_called()

    def test_save_refresh_busy_and_close_clear_revealed_value(self):
        for operation in ("save", "refresh", "busy", "close"):
            with self.subTest(operation=operation):
                window = self.window()
                window._toggle_current_token()
                window._start = mock.Mock()
                if operation == "save":
                    window._save()
                elif operation == "refresh":
                    window._refresh_state()
                elif operation == "busy":
                    window._set_busy(True)
                else:
                    window._close()
                self.assertFalse(window.token_visible)
                window.current_token.set.assert_called_with("********")
                window.current_token_entry.configure.assert_called_with(show="*")

    def test_saving_after_viewing_keeps_replacement_blank_and_environment_source_intact(self):
        with tempfile.TemporaryDirectory(prefix="discord-view-save-test-") as temporary:
            config_dir = Path(temporary)
            bot_path = config_dir / ".env"
            D.setup.save_bot_token(OLD_TOKEN, bot_path)
            original = bot_path.read_bytes()
            factory = ReaderFactory()
            service = D.SetupService(config_dir=config_dir, reader_factory=factory,
                                     environ={"DISCORD_BOT_TOKEN": ENV_TOKEN})
            window = self.window()
            window.service = service
            window._toggle_current_token()
            window.current_token.set.assert_called_with(ENV_TOKEN)
            result = []
            window._start = lambda kind, operation: result.append(operation())
            window._save()
            self.assertTrue(result[0]["complete"])
            self.assertEqual(factory.tokens, [ENV_TOKEN])
            self.assertEqual(bot_path.read_bytes(), original)
            self.assertNotIn(ENV_TOKEN, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
