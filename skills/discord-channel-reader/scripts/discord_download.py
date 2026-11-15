#!/usr/bin/env python3
"""Download fresh attachments from one Discord problem message without posting."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import discord_reader as reader
from discord_tls import https_handler

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_ATTACHMENTS = 100
MAX_FILE_SECONDS = 120
CHUNK_BYTES = 64 * 1024
CDN_HOSTS = frozenset(("cdn.discordapp.com", "media.discordapp.net"))


class DownloadError(Exception):
    """Safe user-facing error, never containing a token or signed attachment URL."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def snowflake(value):
    try:
        return reader.snowflake(value)
    except reader.ReaderError:
        raise DownloadError("Discord IDs must be positive decimal snowflakes.") from None


def stored_filename(identifier, original):
    """Keep an understandable portable name while preventing path and device names."""
    if not isinstance(original, str) or not original or len(original) > 1024:
        raise DownloadError("Discord returned an invalid attachment filename.")
    cleaned = unicodedata.normalize("NFKC", original)
    cleaned = "".join("_" if c in '/\\:*?"<>|' or unicodedata.category(c).startswith("C") else c for c in cleaned)
    cleaned = cleaned.strip(" .") or "attachment"
    # Attachment IDs make names unique even on case-insensitive filesystems and
    # keep CON, NUL, COM1, etc. from becoming Windows device path components.
    suffix = Path(cleaned).suffix
    if len(suffix.encode("utf-8")) > 24:
        suffix = ""
    stem = cleaned[:-len(suffix)] if suffix else cleaned
    while len((stem + suffix).encode("utf-8")) > 160:
        stem = stem[:-1]
    return snowflake(identifier) + "-" + (stem or "attachment") + suffix


def validate_url(url, channel_id, attachment_id):
    if (not isinstance(url, str) or len(url) > 16384
            or any(ord(c) < 33 or ord(c) == 127 for c in url)):
        raise DownloadError("Discord returned an invalid attachment download address.")
    try:
        parsed = urllib.parse.urlsplit(url)
        parts = urllib.parse.unquote(parsed.path).split("/")
        valid = (parsed.scheme == "https" and parsed.hostname in CDN_HOSTS
                 and parsed.port in (None, 443) and not parsed.username and not parsed.password
                 and not parsed.fragment and len(parts) == 5
                 and parts[1] in ("attachments", "ephemeral-attachments")
                 and parts[2] == channel_id and parts[3] == attachment_id
                 and parts[4] not in ("", ".", "..") and "\\" not in parts[4])
        if not valid:
            raise ValueError
    except (ValueError, TypeError):
        raise DownloadError("Attachment download address is outside the selected Discord attachment.") from None
    return url


def validate_output(output):
    try:
        destination = Path(os.path.abspath(Path(output).expanduser()))
        if destination.exists() or destination.is_symlink():
            raise DownloadError("Choose a new output directory; existing files are never overwritten.")
        # macOS exposes its standard temporary roots through system aliases.
        # Resolve those aliases, while refusing user-controlled path links.
        aliases = {"/var": "/private/var", "/tmp": "/private/tmp"} if sys.platform == "darwin" else {}
        if any(parent.is_symlink() and aliases.get(str(parent)) != str(parent.resolve())
               for parent in destination.parents):
            raise DownloadError("Output directories must not pass through symbolic links.")
        return destination.resolve()
    except (OSError, TypeError, ValueError):
        raise DownloadError("Cannot use the requested output directory.") from None


def validate_target(client, channel_id, guild_id, category_id):
    try:
        bot = client.identify()
        if not isinstance(bot, dict) or bot.get("bot") is not True:
            raise DownloadError("Only Discord bot accounts are supported.")
        target = client.channel(channel_id)
        if (not isinstance(target, dict) or snowflake(target.get("id")) != channel_id
                or snowflake(target.get("guild_id")) != guild_id or type(target.get("type")) is not int):
            raise DownloadError("The selected channel does not belong to the expected server.")
        if target["type"] in (0, 5):
            parent = target
        elif target["type"] in (10, 11, 12):
            parent_id = snowflake(target.get("parent_id"))
            parent = client.channel(parent_id)
            if (not isinstance(parent, dict) or snowflake(parent.get("id")) != parent_id
                    or snowflake(parent.get("guild_id")) != guild_id
                    or type(parent.get("type")) is not int or parent["type"] not in (0, 5, 15, 16)):
                raise DownloadError("The selected thread has an unsupported parent channel.")
        else:
            raise DownloadError("Choose a problem text channel or an existing thread.")
        if snowflake(parent.get("parent_id")) != category_id:
            raise DownloadError("The selected channel is outside the expected problem category.")
        permissions = client.effective_permissions(parent)
        required = reader.VIEW_CHANNEL | reader.READ_HISTORY
        if type(permissions) is not int or permissions & required != required:
            raise DownloadError("The bot needs View Channel and Read Message History in the selected channel.")
    except reader.ReaderError:
        raise DownloadError("Cannot verify the bot or its access to the selected channel.") from None
    except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException):
        raise DownloadError("Cannot verify Discord channel metadata and permissions.") from None


def select_attachments(message, channel_id, message_id, requested=None):
    if (not isinstance(message, dict) or snowflake(message.get("id")) != message_id
            or snowflake(message.get("channel_id")) != channel_id):
        raise DownloadError("Discord returned a different message or channel.")
    attachments = message.get("attachments")
    if not isinstance(attachments, list) or not attachments:
        raise DownloadError("No attachments are visible in this message. Check the message ID and Message Content intent.")
    if len(attachments) > MAX_ATTACHMENTS:
        raise DownloadError("The message contains too many attachments for this download.")
    requested = [snowflake(value) for value in requested] if requested else None
    if requested is not None and len(set(requested)) != len(requested):
        raise DownloadError("Each attachment ID must be selected only once.")
    selected, seen = [], set()
    for attachment in attachments:
        if not isinstance(attachment, dict):
            raise DownloadError("Discord returned invalid attachment metadata.")
        identifier = snowflake(attachment.get("id"))
        if identifier in seen:
            raise DownloadError("Discord returned duplicate attachment IDs.")
        seen.add(identifier)
        if requested is not None and identifier not in requested:
            continue
        size = attachment.get("size")
        if type(size) is not int or not 0 <= size <= MAX_FILE_BYTES:
            raise DownloadError("Each download must be at most 32 MiB.")
        original = attachment.get("filename")
        selected.append({"attachment_id": identifier, "original_filename": original,
                         "stored_filename": stored_filename(identifier, original), "size": size,
                         "url": validate_url(attachment.get("url"), channel_id, identifier)})
    if requested is not None and set(requested) - seen:
        raise DownloadError("A selected attachment does not belong to this message.")
    if sum(item["size"] for item in selected) > MAX_TOTAL_BYTES:
        raise DownloadError("Selected attachments exceed the 128 MiB total download limit.")
    return selected


class AttachmentDownloader:
    def __init__(self, client, opener=None, clock=time.monotonic):
        self.client = client
        self.opener = opener if opener is not None else urllib.request.build_opener(NoRedirect(), https_handler())
        self.clock = clock

    def _download_file(self, item, destination):
        request = urllib.request.Request(item["url"], method="GET", headers={
            "User-Agent": "PQC-Discord/0.2.1", "Accept-Encoding": "identity",
        })
        temporary = None
        started = self.clock()
        try:
            with self.opener.open(request, timeout=30) as response:
                if response.status != 200:
                    raise DownloadError("Discord CDN did not return a complete attachment.")
                if response.geturl() != item["url"]:
                    raise DownloadError("Attachment redirects are not accepted.")
                encoding = response.headers.get("Content-Encoding", "identity").lower()
                if encoding != "identity":
                    raise DownloadError("Unexpected attachment content encoding.")
                length = response.headers.get("Content-Length")
                if length is not None and int(length) != item["size"]:
                    raise DownloadError("Attachment size differs from Discord message metadata.")
                digest, count = hashlib.sha256(), 0
                with tempfile.NamedTemporaryFile(prefix=".attachment-", suffix=".part", dir=destination, delete=False) as handle:
                    temporary = Path(handle.name)
                    while True:
                        if self.clock() - started > MAX_FILE_SECONDS:
                            raise DownloadError("Attachment download exceeded its time limit.")
                        block = response.read(min(CHUNK_BYTES, item["size"] - count + 1))
                        if not block:
                            break
                        count += len(block)
                        if count > item["size"] or count > MAX_FILE_BYTES:
                            raise DownloadError("Attachment exceeds its declared size or download limit.")
                        handle.write(block)
                        digest.update(block)
                if count != item["size"]:
                    raise DownloadError("Attachment download was incomplete; the size did not match.")
                final = destination / item["stored_filename"]
                # Link-then-unlink publishes the finished file atomically without
                # replacing a file another process may have created meanwhile.
                os.link(temporary, final)
                temporary.unlink()
                temporary = None
                return {key: item[key] for key in ("attachment_id", "original_filename", "stored_filename", "size")} | {"sha256": digest.hexdigest()}
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise DownloadError(f"Attachment download failed (HTTP {status}). Retry from the message into a new directory to refresh the URL.") from None
        except DownloadError:
            raise
        except (OSError, ValueError, TypeError, AttributeError, RuntimeError, http.client.HTTPException):
            raise DownloadError("Cannot download the attachment. Retry from the message into a new directory; no partial file was accepted.") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def download(self, channel_id, message_id, output, attachment_ids=None,
                 guild_id=reader.DEFAULT_GUILD_ID, category_id=reader.DEFAULT_CATEGORY_ID):
        channel_id, message_id, guild_id, category_id = map(snowflake, (channel_id, message_id, guild_id, category_id))
        destination = validate_output(output)
        validate_target(self.client, channel_id, guild_id, category_id)
        try:
            # Fresh message lookup refreshes expiring CDN URLs; never accept a
            # signed URL supplied by a prompt or previously exported transcript.
            message = self.client.api.get(f"/channels/{channel_id}/messages/{message_id}")
        except (reader.ReaderError, OSError, ValueError, TypeError, KeyError, http.client.HTTPException):
            raise DownloadError("Cannot read the selected message. Check bot permissions and Message Content intent.") from None
        selected = select_attachments(message, channel_id, message_id, attachment_ids)
        manifest = {"version": 1, "complete": False, "guild_id": guild_id, "category_id": category_id,
                    "channel_id": channel_id, "message_id": message_id,
                    "message_url": f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}",
                    "output_directory": str(destination), "files": []}
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            validate_output(destination)
            destination.mkdir(mode=0o700)
        except (OSError, ValueError):
            raise DownloadError("Cannot create the new attachment output directory.") from None
        try:
            for item in selected:
                manifest["files"].append(self._download_file(item, destination))
            manifest["complete"] = True
        except DownloadError as error:
            manifest["error"] = str(error)
        try:
            with (destination / "download-manifest.json").open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(manifest, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            if os.name == "posix":
                (destination / "download-manifest.json").chmod(0o600)
        except (OSError, ValueError):
            raise DownloadError("Cannot save the download manifest; this download is not confirmed complete.") from None
        return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", help="Private bot credentials file; process environment takes precedence")
    parser.add_argument("--guild-id", default=reader.DEFAULT_GUILD_ID)
    parser.add_argument("--category-id", default=reader.DEFAULT_CATEGORY_ID)
    parser.add_argument("--channel-id", required=True)
    parser.add_argument("--message-id", required=True)
    parser.add_argument("--attachment-id", action="append", help="Repeat to select particular attachments; default: all on this message")
    parser.add_argument("--output", required=True, help="A new directory; existing paths are never overwritten")
    args = parser.parse_args(argv)
    try:
        token, _ = reader.load_token(args.env_file)
        client = reader.Reader(reader.DiscordAPI(token))
        result = AttachmentDownloader(client).download(args.channel_id, args.message_id, args.output, args.attachment_id,
                                                       args.guild_id, args.category_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["complete"] else 1
    except (DownloadError, reader.ReaderError) as error:
        print(str(error) if isinstance(error, DownloadError) else "Cannot load or authenticate the configured bot.", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException):
        print("Cannot complete the attachment download; check IDs, permissions and output directory.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
