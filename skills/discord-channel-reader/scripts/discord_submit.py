#!/usr/bin/env python3
"""Preview or submit named source ZIP and Markdown report attachments."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import math
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile

import discord_publish as publisher
import discord_reader as reader
from discord_tls import https_handler


API_ROOT = "https://discord.com/api/v10"
DEFAULT_GUILD_ID = reader.DEFAULT_GUILD_ID
DEFAULT_CATEGORY_ID = reader.DEFAULT_CATEGORY_ID
# Discord forbids names containing "discord" or "clyde" on webhook creation.
WEBHOOK_NAME = "PQC Results"
VIEW_CHANNEL = 1 << 10
MANAGE_WEBHOOKS = 1 << 29
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_REQUEST_BYTES = 25 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_ATTEMPTS = 4
MAX_RETRY_DELAY = 60.0
MAX_TOTAL_RETRY_WAIT = 120.0
FILENAMES = ("sourcecode.zip", "report.md")


class SubmissionError(Exception):
    """A definite failure, expressed without credentials or raw API responses."""


class OutcomeUnknown(SubmissionError):
    """A mutation may have succeeded and must not be automatically repeated."""


class APIError(SubmissionError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Discord HTTP {status}. Check bot permissions and the selected channel.")


def snowflake(value):
    try:
        return publisher.snowflake(value)
    except publisher.PublisherError:
        raise SubmissionError("Discord IDs must be positive decimal snowflakes.") from None


def _username(config):
    try:
        if not isinstance(config, dict):
            raise ValueError
        return publisher.display_username(config.get("display_name"))
    except (publisher.PublisherError, ValueError, TypeError):
        raise SubmissionError("Configure a valid display name before submitting files.") from None


def _upload_filenames(display_name):
    # Validate by the same rules as the author header, without changing that name.
    _username({"display_name": display_name})
    # Avoid paths, Windows-reserved characters and multipart header quoting.
    suffix = "".join("_" if character in '<>:"/\\|?*' or character.isspace() else character
                     for character in display_name.strip()).strip("._") or "user"
    return (f"sourcecode_{suffix}.zip", f"report_{suffix}.md")


def _message(message):
    if message is None:
        return ""
    try:
        if publisher.utf16_length(message) > 2000:
            raise SubmissionError("Message exceeds 2000 UTF-16 units. Shorten it before submitting.")
    except publisher.PublisherError:
        raise SubmissionError("Message must contain valid Unicode text.") from None
    return message


def _validate_data(filename, data):
    if not isinstance(data, bytes) or len(data) > MAX_FILE_BYTES:
        raise SubmissionError("Each attachment must be at most 20 MiB.")
    if filename == "sourcecode.zip":
        try:
            # Reading the central directory checks the archive format without
            # decompressing user-controlled entries or extracting any files.
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                archive.infolist()
        except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, ValueError, EOFError):
            raise SubmissionError("The source archive must be a valid ZIP file.") from None
    elif filename == "report.md":
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            raise SubmissionError("The report must use UTF-8 encoding.") from None
        if not text.lstrip("\ufeff").strip():
            raise SubmissionError("The report must not be empty.")


def _files(files):
    if not isinstance(files, (list, tuple)) or len(files) != 2:
        raise SubmissionError("Submit exactly sourcecode.zip and report.md together.")
    result = []
    for filename, item in zip(FILENAMES, files):
        if not isinstance(item, dict) or item.get("filename") != filename:
            raise SubmissionError("Attachment names must be sourcecode.zip and report.md, in that order.")
        data = item.get("data")
        _validate_data(filename, data)
        result.append({"filename": filename, "data": data, "size": len(data),
                       "sha256": hashlib.sha256(data).hexdigest()})
    return result


def load_files(source_zip, report):
    result = []
    for filename, path in zip(FILENAMES, (source_zip, report)):
        try:
            path = Path(path).expanduser()
            if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                raise SubmissionError("Choose two regular files, each at most 20 MiB.")
            with path.open("rb") as handle:
                data = handle.read(MAX_FILE_BYTES + 1)
        except (OSError, ValueError, TypeError):
            raise SubmissionError("Cannot read the source ZIP or report file.") from None
        result.append({"filename": filename, "data": data})
    return _files(result)


def encode_multipart(payload, files, *, display_name=None):
    files = _files(files)
    filenames = FILENAMES if display_name is None else _upload_filenames(display_name)
    try:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise SubmissionError("Cannot encode the submission message.") from None
    boundary = "pqc-discord-" + uuid.uuid4().hex
    # A boundary must not occur inside a supplied file or the JSON part.
    while any(boundary.encode("ascii") in part for part in [serialized] + [f["data"] for f in files]):
        boundary = "pqc-discord-" + uuid.uuid4().hex
    marker = boundary.encode("ascii")
    parts = [b"--" + marker + b"\r\n",
             b'Content-Disposition: form-data; name="payload_json"\r\n',
             b"Content-Type: application/json\r\n\r\n", serialized, b"\r\n"]
    for index, (item, filename) in enumerate(zip(files, filenames)):
        mime = "application/zip" if index == 0 else "text/markdown; charset=utf-8"
        parts.extend([b"--" + marker + b"\r\n",
                      f'Content-Disposition: form-data; name="files[{index}]"; filename="{filename}"\r\n'.encode("utf-8"),
                      f"Content-Type: {mime}\r\n\r\n".encode("ascii"), item["data"], b"\r\n"])
    parts.append(b"--" + marker + b"--\r\n")
    if sum(len(part) for part in parts) > MAX_REQUEST_BYTES:
        raise SubmissionError("The complete upload exceeds 25 MiB. Reduce the files before submitting.")
    return b"".join(parts), "multipart/form-data; boundary=" + boundary


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _webhook_token(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", value):
        raise SubmissionError("Discord did not return a usable incoming webhook token.")
    return value


class SubmissionAPI:
    def __init__(self, token, opener=None, sleeper=time.sleep):
        if not isinstance(token, str) or not token or any(not 33 <= ord(c) <= 126 for c in token):
            raise SubmissionError("Invalid bot token format. Supply a token without the Bot prefix.")
        self.token = token
        self.opener = opener if opener is not None else urllib.request.build_opener(NoRedirect(), https_handler())
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
            except (ValueError, TypeError):
                continue
            if math.isfinite(delay) and delay >= 0:
                return delay + 0.1
        raise SubmissionError("Discord rate limiting did not supply a valid retry delay. Try again later.")

    @staticmethod
    def _unknown(creating):
        if creating:
            return OutcomeUnknown("Webhook creation could not be confirmed. Check the channel's webhooks before rerunning setup or submission.")
        return OutcomeUnknown("Submission could not be confirmed. Check the selected channel before retrying; the files may already be posted.")

    def _request(self, url, data=None, content_type=None, bot_auth=False, creating=False, expect_list=False):
        posting = data is not None
        waited = 0.0
        for attempt in range(MAX_ATTEMPTS):
            headers = {"User-Agent": "DiscordBot (https://github.com/pqc-master/skills, 1.0)",
                       "Accept": "application/json"}
            if bot_auth:
                headers["Authorization"] = "Bot " + self.token
            if content_type:
                headers["Content-Type"] = content_type
            request = urllib.request.Request(url, data=data, headers=headers, method="POST" if posting else "GET")
            try:
                with self.opener.open(request, timeout=30) as response:
                    status = getattr(response, "status", 200)
                    if not 200 <= status < 300:
                        if posting and 500 <= status <= 599:
                            raise self._unknown(creating)
                        raise APIError(status)
                    body = response.read(MAX_RESPONSE_BYTES + 1)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ValueError
                    result = json.loads(body)
                    if not isinstance(result, list if expect_list else dict):
                        raise ValueError
                    return result
            except urllib.error.HTTPError as error:
                status = error.code
                try:
                    if status == 429:
                        delay = self._retry_delay(error)
                    elif 500 <= status <= 599:
                        if posting:
                            raise self._unknown(creating) from None
                        delay = float(2 ** attempt)
                    else:
                        raise APIError(status) from None
                finally:
                    try:
                        error.close()
                    except (OSError, http.client.HTTPException):
                        pass
                if attempt == MAX_ATTEMPTS - 1:
                    raise APIError(status) from None
                if delay > MAX_RETRY_DELAY or waited + delay > MAX_TOTAL_RETRY_WAIT:
                    raise SubmissionError("Discord requires a longer rate-limit wait. No retry was sent; try again later.") from None
                self._wait(delay)
                waited += delay
            except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
                if posting:
                    raise self._unknown(creating) from None
                if attempt == MAX_ATTEMPTS - 1:
                    raise SubmissionError("Cannot reach Discord after bounded retries.") from None
                delay = float(2 ** attempt)
                self._wait(delay)
                waited += delay
            except (ValueError, TypeError, UnicodeError):
                if posting:
                    raise self._unknown(creating) from None
                raise SubmissionError("Discord returned invalid webhook metadata.") from None
        raise SubmissionError("Discord retry budget exhausted.")

    def list_webhooks(self, parent_id):
        parent_id = snowflake(parent_id)
        return self._request(f"{API_ROOT}/channels/{parent_id}/webhooks", bot_auth=True, expect_list=True)

    def create_webhook(self, parent_id):
        parent_id = snowflake(parent_id)
        data = json.dumps({"name": WEBHOOK_NAME}).encode("utf-8")
        return self._request(f"{API_ROOT}/channels/{parent_id}/webhooks", data=data,
                             content_type="application/json", bot_auth=True, creating=True)

    def execute_webhook(self, webhook_id, webhook_token, body, content_type, thread_id=None):
        webhook_id = snowflake(webhook_id)
        webhook_token = _webhook_token(webhook_token)
        if not isinstance(body, bytes) or len(body) > MAX_REQUEST_BYTES:
            raise SubmissionError("The complete upload must be at most 25 MiB.")
        if not isinstance(content_type, str) or not re.fullmatch(r"multipart/form-data; boundary=[A-Za-z0-9_-]+", content_type):
            raise SubmissionError("Invalid multipart content type.")
        url = f"{API_ROOT}/webhooks/{webhook_id}/{webhook_token}?wait=true"
        if thread_id is not None:
            url += "&thread_id=" + snowflake(thread_id)
        return self._request(url, data=body, content_type=content_type)


def validate_target(reader_client, channel_id, guild_id, category_id):
    channel_id, guild_id, category_id = map(snowflake, (channel_id, guild_id, category_id))
    try:
        target = reader_client.channel(channel_id)
        if not isinstance(target, dict) or snowflake(target.get("id")) != channel_id or snowflake(target.get("guild_id")) != guild_id:
            raise SubmissionError("The selected channel does not belong to the expected server.")
        channel_type = target.get("type")
        if type(channel_type) is not int:
            raise SubmissionError("Discord returned an unsupported channel type.")
        if channel_type in (0, 5):
            parent = target
        elif channel_type in (10, 11, 12):
            parent_id = snowflake(target.get("parent_id"))
            parent = reader_client.channel(parent_id)
            if (not isinstance(parent, dict) or snowflake(parent.get("id")) != parent_id
                    or snowflake(parent.get("guild_id")) != guild_id
                    or type(parent.get("type")) is not int or parent.get("type") not in (0, 5, 15, 16)):
                raise SubmissionError("The selected thread does not have an allowed parent channel in this server.")
        else:
            raise SubmissionError("Select a text channel or an existing thread; forum, media and category parents cannot receive a submission directly.")
        if snowflake(parent.get("parent_id")) != category_id:
            raise SubmissionError("The selected channel is outside the expected problem category.")
        permissions = reader_client.effective_permissions(parent)
        required = VIEW_CHANNEL | MANAGE_WEBHOOKS
        if not isinstance(permissions, int) or permissions & required != required:
            raise SubmissionError("The bot needs View Channel and Manage Webhooks permissions in the selected parent channel.")
        return target, parent
    except reader.ReaderError:
        raise SubmissionError("Cannot verify the selected channel. Check the bot's server, channel and private-thread access.") from None
    except (KeyError, TypeError, ValueError, OSError, http.client.HTTPException):
        raise SubmissionError("Cannot verify Discord channel metadata and permissions.") from None


def _validate_webhook(metadata, bot_id, parent_id, guild_id):
    if not isinstance(metadata, dict):
        raise SubmissionError("Discord returned invalid incoming webhook metadata.")
    owner = metadata.get("user")
    if (type(metadata.get("type")) is not int or metadata.get("type") != 1
            or metadata.get("name") != WEBHOOK_NAME or not isinstance(owner, dict)
            or snowflake(owner.get("id")) != bot_id
            or snowflake(metadata.get("channel_id")) != parent_id
            or snowflake(metadata.get("guild_id")) != guild_id):
        raise SubmissionError("The managed webhook does not match this bot and the selected channel.")
    return snowflake(metadata.get("id")), _webhook_token(metadata.get("token"))


class Submitter:
    def __init__(self, config, reader_client=None, api=None,
                 guild_id=DEFAULT_GUILD_ID, category_id=DEFAULT_CATEGORY_ID):
        self.username = _username(config)
        self.display_name = config["display_name"].strip()
        self.reader = reader_client
        self.api = api
        self.guild_id = snowflake(guild_id)
        self.category_id = snowflake(category_id)

    def _prepare(self, channel_id, files, message):
        channel_id = snowflake(channel_id)
        files = _files(files)
        filenames = _upload_filenames(self.display_name)
        content = _message(message)
        payload = {"username": self.username, "allowed_mentions": {"parse": []},
                   "attachments": [{"id": index, "filename": filename} for index, filename in enumerate(filenames)]}
        if content:
            payload["content"] = content
        body, content_type = encode_multipart(payload, files, display_name=self.display_name)
        preview = {"guild_id": self.guild_id, "category_id": self.category_id,
                   "channel_id": channel_id, "username": self.username, "content": content,
                   "files": [{"filename": filename, "size": item["size"], "sha256": item["sha256"]}
                             for item, filename in zip(files, filenames)],
                   "may_create_webhook": True}
        return preview, body, content_type

    def preview(self, channel_id, files, message=None):
        return self._prepare(channel_id, files, message)[0]

    def send(self, channel_id, files, message=None):
        preview, body, content_type = self._prepare(channel_id, files, message)
        channel_id = preview["channel_id"]
        if self.reader is None or self.api is None:
            raise SubmissionError("Bot authentication is required to submit files.")
        try:
            bot = self.reader.identify()
            if not isinstance(bot, dict) or bot.get("bot") is not True:
                raise SubmissionError("Only Discord bot accounts are supported.")
            bot_id = snowflake(bot.get("id"))
        except reader.ReaderError:
            raise SubmissionError("Cannot authenticate the configured bot.") from None
        except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException):
            raise SubmissionError("Cannot verify the configured bot's identity.") from None
        target, parent = validate_target(self.reader, channel_id, self.guild_id, self.category_id)
        parent_id = snowflake(parent["id"])
        webhooks = self.api.list_webhooks(parent_id)
        if not isinstance(webhooks, list):
            raise SubmissionError("Discord returned invalid channel webhook metadata.")
        candidates = [item for item in webhooks if isinstance(item, dict)
                      and type(item.get("type")) is int and item.get("type") == 1
                      and item.get("name") == WEBHOOK_NAME and isinstance(item.get("user"), dict)
                      and str(item["user"].get("id")) == bot_id]
        created = not candidates
        metadata = candidates[0] if candidates else self.api.create_webhook(parent_id)
        try:
            webhook_id, webhook_token = _validate_webhook(metadata, bot_id, parent_id, self.guild_id)
        except SubmissionError:
            if created:
                raise SubmissionAPI._unknown(True) from None
            raise
        thread_id = channel_id if target["type"] in (10, 11, 12) else None
        response = self.api.execute_webhook(webhook_id, webhook_token, body, content_type, thread_id=thread_id)
        try:
            if (not isinstance(response, dict) or snowflake(response.get("channel_id")) != channel_id
                    or snowflake(response.get("webhook_id")) != webhook_id):
                raise ValueError
            message_id = snowflake(response.get("id"))
            attachments = response.get("attachments")
            if not isinstance(attachments, list) or len(attachments) != 2:
                raise ValueError
            actual = {}
            for attachment in attachments:
                if (not isinstance(attachment, dict) or not isinstance(attachment.get("filename"), str)
                        or type(attachment.get("size")) is not int or attachment["filename"] in actual):
                    raise ValueError
                actual[attachment["filename"]] = attachment["size"]
            if actual != {item["filename"]: item["size"] for item in preview["files"]}:
                raise ValueError
        except (SubmissionError, KeyError, ValueError, TypeError):
            raise SubmissionAPI._unknown(False) from None
        return {"status": "sent", "guild_id": self.guild_id, "channel_id": channel_id,
                "message_id": message_id, "username": self.username, "files": preview["files"],
                "message_url": f"https://discord.com/channels/{self.guild_id}/{channel_id}/{message_id}"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", help="Private bot credential file; process environment takes precedence")
    parser.add_argument("--config", help="Private display-name configuration (default: ~/.config/discord-channel-reader/publisher.json)")
    parser.add_argument("--guild-id", default=DEFAULT_GUILD_ID)
    parser.add_argument("--category-id", default=DEFAULT_CATEGORY_ID)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("preview", "send"):
        sub = commands.add_parser(command, help="Validate files and preview locally without network access" if command == "preview" else "Submit both files using a bot-managed channel webhook")
        sub.add_argument("--channel-id", required=True)
        sub.add_argument("--source-zip", required=True)
        sub.add_argument("--report", required=True)
        sub.add_argument("--message", help="Optional message, at most 2000 UTF-16 units")
    args = parser.parse_args(argv)
    try:
        config = publisher.load_config(args.config)
        files = load_files(args.source_zip, args.report)
        submitter = Submitter(config, guild_id=args.guild_id, category_id=args.category_id)
        if args.command == "send":
            # Reject local input errors before reading credentials or using the network.
            submitter.preview(args.channel_id, files, args.message)
            token, _ = reader.load_token(args.env_file)
            submitter.reader = reader.Reader(reader.DiscordAPI(token))
            submitter.api = SubmissionAPI(token)
        result = getattr(submitter, args.command)(args.channel_id, files, args.message)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except OutcomeUnknown as error:
        print(str(error), file=sys.stderr)
        return 2
    except SubmissionError as error:
        print(str(error), file=sys.stderr)
        return 1
    except publisher.PublisherError:
        print("Cannot read the display-name configuration. Run setup and check private file permissions.", file=sys.stderr)
        return 1
    except reader.ReaderError:
        print("Cannot use the configured bot credentials. Check the private token file and bot access.", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, EOFError, http.client.HTTPException):
        print("Cannot complete submission. Check configuration, selected channel and the two files.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. If sending began, check the channel and its webhooks before retrying.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
