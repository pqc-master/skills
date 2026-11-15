#!/usr/bin/env python3
"""Publish explicitly requested text through a locally configured Discord webhook."""
from __future__ import annotations

import argparse
import getpass
import http.client
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import warnings


API_ROOT = "https://discord.com/api/v10"
DEFAULT_GUILD_ID = "1563153526283051008"
USERNAME_SUFFIX = " · Codex"
MAX_ATTEMPTS = 4
MAX_RETRY_DELAY = 60.0
MAX_TOTAL_RETRY_WAIT = 120.0
MAX_RESPONSE_BYTES = 1024 * 1024


class PublisherError(Exception):
    """A definitive failure; messages deliberately exclude webhook credentials."""


class OutcomeUnknown(PublisherError):
    """A POST might have succeeded; callers must not automatically retry it."""


class APIError(PublisherError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Discord HTTP {status}. Check webhook configuration and channel access.")


def snowflake(value):
    if isinstance(value, bool):
        raise PublisherError("Discord IDs must be positive decimal snowflakes.")
    value = str(value)
    if not re.fullmatch(r"[1-9][0-9]{0,19}", value) or int(value) > (1 << 64) - 1:
        raise PublisherError("Discord IDs must be positive decimal snowflakes.")
    return value


def utf16_length(text):
    if not isinstance(text, str):
        raise PublisherError("Text must be a Unicode string.")
    try:
        return len(text.encode("utf-16-le")) // 2
    except UnicodeError:
        raise PublisherError("Text contains an invalid Unicode character.") from None


def display_username(name):
    if not isinstance(name, str) or not name.strip():
        raise PublisherError("Enter a nonempty display name.")
    if any(unicodedata.category(char).startswith("C") for char in name):
        raise PublisherError("Display names cannot contain control or invisible formatting characters.")
    username = name.strip() + USERNAME_SUFFIX
    if utf16_length(username) > 80:
        raise PublisherError("Display name plus ' · Codex' must fit within 80 UTF-16 units.")
    return username


def validate_content(content):
    if not isinstance(content, str) or not content.strip():
        raise PublisherError("Enter a nonempty message.")
    if utf16_length(content) > 2000:
        raise PublisherError("Message exceeds 2000 UTF-16 units. Shorten it; text is not split or truncated.")
    return content


def normalize_webhook_url(url):
    """Accept only copied Discord incoming-webhook URLs, with no extra parameters."""
    if not isinstance(url, str) or any(char.isspace() for char in url):
        raise PublisherError("Enter a Discord webhook URL without whitespace.")
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        raise PublisherError("Invalid Discord webhook URL.") from None
    match = re.fullmatch(r"/api(?:/v10)?/webhooks/([1-9][0-9]{0,19})/([A-Za-z0-9_-]{1,512})", parsed.path)
    if (parsed.scheme != "https" or parsed.netloc != "discord.com"
            or parsed.query or parsed.fragment or "?" in url or "#" in url or not match):
        raise PublisherError("Use an https://discord.com/api/webhooks/ID/TOKEN URL without query or fragment.")
    webhook_id = snowflake(match.group(1))
    return f"{API_ROOT}/webhooks/{webhook_id}/{match.group(2)}", webhook_id


def default_config_path():
    return Path.home() / ".config/discord-channel-reader/publisher.json"


def _config_path(path):
    return Path(path).expanduser() if path is not None else default_config_path()


def validate_config(config):
    if not isinstance(config, dict) or type(config.get("version")) is not int or config.get("version") != 1:
        raise PublisherError("Unsupported publisher configuration. Run setup to configure a webhook.")
    name = config.get("display_name")
    display_username(name)
    bindings = config.get("webhooks")
    if not isinstance(bindings, dict):
        raise PublisherError("Invalid publisher webhook configuration.")
    normalized = {}
    for channel_id, binding in bindings.items():
        channel_id = snowflake(channel_id)
        if not isinstance(binding, dict):
            raise PublisherError("Invalid publisher webhook binding.")
        url, webhook_id = normalize_webhook_url(binding.get("url"))
        if snowflake(binding.get("webhook_id")) != webhook_id:
            raise PublisherError("Webhook ID does not match its configured URL. Run setup again.")
        normalized[channel_id] = {
            "guild_id": snowflake(binding.get("guild_id")),
            "webhook_id": webhook_id,
            "url": url,
        }
    return {"version": 1, "display_name": name.strip(), "webhooks": normalized}


def load_config(path=None, missing_ok=False):
    path = _config_path(path)
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise PublisherError("Publisher configuration must be a regular file, not a symbolic link.")
        if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
            raise PublisherError("Publisher configuration is accessible to other users; set its permissions to 600.")
        if info.st_size > 128 * 1024:
            raise PublisherError("Publisher configuration is too large.")
        return validate_config(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        if missing_ok:
            return {"version": 1, "display_name": "", "webhooks": {}}
        raise PublisherError("Publisher is not configured. Run setup in your terminal first.") from None
    except (OSError, UnicodeError, ValueError, TypeError):
        raise PublisherError("Cannot read publisher configuration. Check its format and file permissions.") from None


def save_config(config, path=None):
    config = validate_config(config)
    path = _config_path(path)
    temporary = None
    try:
        # Validate existing files before replacing them; do not follow secret-file symlinks.
        if path.exists() or path.is_symlink():
            load_config(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=".publisher-", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            if os.name == "posix":
                os.fchmod(output.fileno(), 0o600)
            json.dump(config, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError:
        raise PublisherError("Cannot save publisher configuration; the previous file was preserved.") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WebhookAPI:
    def __init__(self, opener=None, sleeper=time.sleep):
        self.opener = opener if opener is not None else urllib.request.build_opener(NoRedirect())
        self.sleeper = sleeper

    def _wait(self, seconds):
        while seconds > 0:
            part = min(seconds, 30.0)
            self.sleeper(part)
            seconds -= part

    @staticmethod
    def _retry_delay(error):
        fallback = error.headers.get("Retry-After") if error.headers else None
        try:
            data = json.loads(error.read(65536))
            raw = data.get("retry_after", fallback) if isinstance(data, dict) else fallback
        except (ValueError, TypeError, OSError, http.client.HTTPException):
            raw = fallback
        for value in (raw, fallback):
            try:
                delay = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(delay) and delay >= 0:
                return delay + 0.1
        raise PublisherError("Discord rate limit did not provide a valid retry delay. Try again later.")

    def _request(self, url, payload=None):
        url, _ = normalize_webhook_url(url)
        posting = payload is not None
        method = "POST" if posting else "GET"
        if posting:
            url += "?wait=true"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if posting else None
        waited = 0.0
        for attempt in range(MAX_ATTEMPTS):
            request = urllib.request.Request(url, data=data, method=method, headers={
                "User-Agent": "DiscordBot (https://github.com/pqc-master/skills, 1.0)",
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if posting else {}),
            })
            try:
                with self.opener.open(request, timeout=30) as response:
                    status = getattr(response, "status", 200)
                    if not 200 <= status < 300:
                        if posting:
                            raise OutcomeUnknown("Unexpected Discord response. Delivery is unknown; check the channel before retrying.")
                        raise APIError(status)
                    body = response.read(MAX_RESPONSE_BYTES + 1)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ValueError("Response too large")
                    result = json.loads(body)
                    if not isinstance(result, dict):
                        raise ValueError("Object response required")
                    return result
            except urllib.error.HTTPError as error:
                status = error.code
                try:
                    if status == 429:
                        delay = self._retry_delay(error)
                    elif 500 <= status <= 599:
                        if posting:
                            raise OutcomeUnknown("Discord returned a server error. Delivery is unknown; check the channel before retrying.") from None
                        delay = float(2 ** attempt)
                    else:
                        raise APIError(status) from None
                finally:
                    error.close()
                if attempt == MAX_ATTEMPTS - 1:
                    raise APIError(status) from None
                if delay > MAX_RETRY_DELAY or waited + delay > MAX_TOTAL_RETRY_WAIT:
                    raise PublisherError("Discord requires a longer rate-limit wait. No retry was sent; try again later.") from None
                self._wait(delay)
                waited += delay
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
                if posting:
                    raise OutcomeUnknown("Connection failed during posting. Delivery is unknown; check the channel before retrying.") from None
                if attempt == MAX_ATTEMPTS - 1:
                    raise PublisherError("Cannot reach Discord after bounded retries.") from None
                delay = float(2 ** attempt)
                self._wait(delay)
                waited += delay
            except (ValueError, TypeError, UnicodeError):
                if posting:
                    raise OutcomeUnknown("Discord returned an unreadable posting result. Delivery is unknown; check the channel before retrying.") from None
                raise PublisherError("Discord returned invalid webhook metadata.") from None
        raise PublisherError("Discord retry budget exhausted.")

    def get(self, url):
        return self._request(url)

    def execute(self, url, payload):
        return self._request(url, payload)


def validate_metadata(metadata, webhook_id, guild_id=None, channel_id=None):
    if not isinstance(metadata, dict) or type(metadata.get("type")) is not int or metadata.get("type") != 1:
        raise PublisherError("Only incoming webhooks for server channels are supported.")
    actual = {
        "webhook_id": snowflake(metadata.get("id")),
        "guild_id": snowflake(metadata.get("guild_id")),
        "channel_id": snowflake(metadata.get("channel_id")),
    }
    if (actual["webhook_id"] != snowflake(webhook_id)
            or (guild_id is not None and actual["guild_id"] != snowflake(guild_id))
            or (channel_id is not None and actual["channel_id"] != snowflake(channel_id))):
        raise PublisherError("Webhook target differs from the configured server or channel. Check it and run setup again.")
    return actual


class Publisher:
    def __init__(self, config, api=None):
        self.config = validate_config(config)
        self.api = api if api is not None else WebhookAPI()

    def _binding(self, channel_id):
        channel_id = snowflake(channel_id)
        binding = self.config["webhooks"].get(channel_id)
        if binding is None:
            raise PublisherError("This channel has no configured webhook. Run setup for the intended channel.")
        return channel_id, binding

    def preview(self, channel_id, content):
        channel_id, binding = self._binding(channel_id)
        content = validate_content(content)
        return {
            "sent": False,
            "username": display_username(self.config["display_name"]),
            "guild_id": binding["guild_id"],
            "channel_id": channel_id,
            "content": content,
            "content_length_utf16": utf16_length(content),
            "author_identity": "self-declared display name, not authenticated Discord identity",
        }

    def doctor(self, channel_id):
        channel_id, binding = self._binding(channel_id)
        target = validate_metadata(self.api.get(binding["url"]), binding["webhook_id"], binding["guild_id"], channel_id)
        return dict(target, username=display_username(self.config["display_name"]), webhook_access="ok", message_sent=False)

    def send(self, channel_id, content):
        preview = self.preview(channel_id, content)
        channel_id, binding = self._binding(channel_id)
        self.doctor(channel_id)
        result = self.api.execute(binding["url"], {
            "username": preview["username"],
            "content": preview["content"],
            "allowed_mentions": {"parse": []},
        })
        try:
            if not isinstance(result, dict):
                raise PublisherError("Invalid message response")
            message_id = snowflake(result.get("id"))
            if (snowflake(result.get("channel_id")) != channel_id
                    or snowflake(result.get("webhook_id")) != binding["webhook_id"]):
                raise PublisherError("Message response does not match target")
        except PublisherError:
            raise OutcomeUnknown("Discord did not confirm the intended message. Check the channel before retrying.") from None
        return {
            "sent": True,
            "username": preview["username"],
            "guild_id": binding["guild_id"],
            "channel_id": channel_id,
            "message_id": message_id,
            "message_url": f"https://discord.com/channels/{binding['guild_id']}/{channel_id}/{message_id}",
        }


def setup(config_path=None, name=None, guild_id=DEFAULT_GUILD_ID, api=None):
    config = load_config(config_path, missing_ok=True)
    guild_id = snowflake(guild_id)
    if name is None:
        name = config["display_name"] or input("표시 이름: ").strip()
    username = display_username(name)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            url = getpass.getpass("Discord 웹훅 URL (숨김 입력): ").strip()
    except getpass.GetPassWarning:
        raise PublisherError("Run setup in your own terminal with hidden input available.") from None
    url, webhook_id = normalize_webhook_url(url)
    api = api if api is not None else WebhookAPI()
    target = validate_metadata(api.get(url), webhook_id, guild_id)
    config["display_name"] = name.strip()
    config["webhooks"][target["channel_id"]] = {
        "guild_id": target["guild_id"], "webhook_id": webhook_id, "url": url,
    }
    save_config(config, config_path)
    return dict(target, configured=True, username=username, config_path=str(_config_path(config_path)))


def update_profile(name, config_path=None):
    config = load_config(config_path)
    username = display_username(name)
    config["display_name"] = name.strip()
    save_config(config, config_path)
    return {"display_name": name.strip(), "username": username, "config_path": str(_config_path(config_path))}


def read_content(args):
    if args.text is not None:
        return validate_content(args.text)
    try:
        if args.content_file == "-":
            content = sys.stdin.read(8001)
        else:
            with Path(args.content_file).expanduser().open(encoding="utf-8") as source:
                content = source.read(8001)
    except (OSError, UnicodeError):
        raise PublisherError("Cannot read the UTF-8 message file.") from None
    return validate_content(content)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Private publisher JSON path (default: ~/.config/discord-channel-reader/publisher.json)")
    commands = parser.add_subparsers(dest="command", required=True)
    configure = commands.add_parser("setup", help="Save display name and a hidden-input webhook URL; performs GET only")
    configure.add_argument("--name", help="Your self-declared display name, without the ' · Codex' suffix")
    configure.add_argument("--guild-id", default=DEFAULT_GUILD_ID, help="Expected server ID for the webhook")
    profile = commands.add_parser("profile", help="Change the display name locally without reentering webhook URLs")
    profile.add_argument("--name", required=True)
    doctor = commands.add_parser("doctor", help="Check one configured webhook target; does not send a message")
    doctor.add_argument("--channel-id", required=True)
    for command in ("preview", "send"):
        sub = commands.add_parser(command, help="Show the local message preview" if command == "preview" else "Publish one message to the explicitly selected channel")
        sub.add_argument("--channel-id", required=True)
        content = sub.add_mutually_exclusive_group(required=True)
        content.add_argument("--text", help="Message text")
        content.add_argument("--content-file", help="UTF-8 message file, or - to read standard input")
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            result = setup(args.config, args.name, args.guild_id)
        elif args.command == "profile":
            result = update_profile(args.name, args.config)
        else:
            publisher = Publisher(load_config(args.config))
            if args.command == "doctor":
                result = publisher.doctor(args.channel_id)
            else:
                content = read_content(args)
                result = getattr(publisher, args.command)(args.channel_id, content)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except OutcomeUnknown as error:
        print(str(error), file=sys.stderr)
        return 2
    except PublisherError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, EOFError):
        print("Cannot complete request. Check local configuration, message input and webhook access.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. If posting had begun, check the channel before retrying.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
