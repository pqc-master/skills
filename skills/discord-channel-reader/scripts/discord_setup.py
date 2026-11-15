#!/usr/bin/env python3
"""Set up the bot token and author name for the current problem channel."""
from __future__ import annotations

import argparse
import getpass
import http.client
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import warnings

# Keep this entry point usable from an installed skill as well as a repository checkout.
SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)
import discord_reader as reader
import discord_publish as publisher


DEFAULT_GUILD_ID = reader.DEFAULT_GUILD_ID
TOKEN_VARIABLES = ("DISCORD_BOT_TOKEN", "FIESTA_RELAY_BOT_TOKEN")


class SetupError(Exception):
    """A setup failure whose message must not contain credential values."""


def bot_config_path():
    return Path.home() / ".config/discord-channel-reader/.env"


def _ask(question, default=True):
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        answer = input(question + suffix).strip().casefold()
        if not answer:
            return default
        if answer in ("y", "yes", "네", "예"):
            return True
        if answer in ("n", "no", "아니요"):
            return False
        print("y 또는 n을 입력하세요.")


def _has_token_environment():
    return any(os.environ.get(key, "").strip() for key in TOKEN_VARIABLES)


def _hidden_token():
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            token = getpass.getpass("Discord 봇 토큰 (숨김 입력): ").strip()
    except getpass.GetPassWarning:
        raise SetupError("숨김 입력이 가능한 사용자 본인의 터미널에서 실행하세요.") from None
    if not token or any(character.isspace() for character in token):
        raise SetupError("봇 토큰만 입력하세요. 'Bot ' 접두사는 제외합니다.")
    return token


def _read_existing_env(path):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise SetupError("봇 설정 파일은 심볼릭 링크가 아닌 일반 파일이어야 합니다.")
        if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
            raise SetupError("봇 설정 파일 권한을 600으로 설정한 뒤 다시 실행하세요.")
        if info.st_size > 128 * 1024:
            raise SetupError("봇 설정 파일이 너무 큽니다.")
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError):
        raise SetupError("봇 설정 파일을 읽을 수 없습니다. 파일과 권한을 확인하세요.") from None


def save_bot_token(token, path=None, replace=False):
    """Atomically save a dedicated token, preserving unrelated dotenv entries."""
    if not isinstance(token, str) or not token or any(character.isspace() for character in token):
        raise SetupError("유효한 봇 토큰을 입력하세요.")
    path = Path(path).expanduser() if path is not None else bot_config_path()
    existing = _read_existing_env(path)
    if existing is not None and not replace:
        raise SetupError("기존 봇 설정을 보존했습니다. 교체하려면 --replace-token을 지정하세요.")
    lines = []
    inserted = False
    for line in (existing or "").splitlines(keepends=True):
        normalized = line.strip()
        if normalized.startswith("export "):
            normalized = normalized[7:].strip()
        key, separator, _ = normalized.partition("=")
        if separator and key.strip() == "DISCORD_BOT_TOKEN":
            if not inserted:
                lines.append("DISCORD_BOT_TOKEN=" + token + "\n")
                inserted = True
        else:
            lines.append(line)
    if not inserted:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += "\n"
        lines.append("DISCORD_BOT_TOKEN=" + token + "\n")
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix=".discord-token-", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
            if os.name == "posix":
                os.fchmod(destination.fileno(), 0o600)
            destination.write("".join(lines))
            destination.flush()
            os.fsync(destination.fileno())
        if existing is None:
            # A concurrent setup must not overwrite a file created after our initial check.
            os.link(temporary, path)
            os.unlink(temporary)
        else:
            os.replace(temporary, path)
        temporary = None
    except OSError:
        raise SetupError("봇 토큰을 저장하지 못했습니다. 기존 설정 파일은 덮어쓰지 않았습니다.") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _reader_for_token(token):
    return reader.Reader(reader.DiscordAPI(token))


def _check_bot(token, factory):
    try:
        return factory(token).doctor()
    except http.client.HTTPException:
        raise SetupError("Discord 인증 응답을 읽지 못했습니다. 기존 설정은 보존되어 있습니다.") from None


def _safe_bot_result(diagnosis, source, saved):
    result = {
        "status": "configured" if saved else "reused",
        "credential_source": source,
        "credential_saved": saved,
    }
    for key in ("bot_id", "username", "bot_authentication", "message_content_intent", "warning", "channel_access"):
        if key in diagnosis:
            result[key] = diagnosis[key]
    return result


def _explain_environment_override():
    raise SetupError(
        "DISCORD_BOT_TOKEN 또는 FIESTA_RELAY_BOT_TOKEN 환경변수가 파일보다 우선합니다. "
        "현재 터미널에서 두 환경변수를 해제한 뒤 --replace-token으로 다시 실행하세요. "
        "기존 환경변수와 파일은 변경하지 않았습니다."
    )


def setup_bot(config_path=None, replace_token=False, reader_factory=None):
    path = Path(config_path).expanduser() if config_path is not None else bot_config_path()
    factory = reader_factory if reader_factory is not None else _reader_for_token
    if replace_token and _has_token_environment():
        _explain_environment_override()
    if not replace_token and (path.exists() or path.is_symlink()):
        # load_token intentionally gives process environment variables precedence.
        token, source = reader.load_token(str(path))
        diagnosis = _check_bot(token, factory)
        result = _safe_bot_result(diagnosis, source, False)
        if source == "process environment":
            result["credential_note"] = "환경변수가 로컬 설정 파일보다 우선하여 사용되었습니다."
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if not _ask("위 기존 봇 연결을 그대로 사용할까요?", True):
                _explain_environment_override()
        return result
    if not replace_token:
        try:
            token, source = reader.load_token()
        except reader.ReaderError:
            token, source = None, None
        if token is not None:
            diagnosis = _check_bot(token, factory)
            # Display only the same safe identity projection used in the final output.
            print(json.dumps(_safe_bot_result(diagnosis, source, False), ensure_ascii=False, indent=2))
            if _ask("위 기존 봇 연결을 그대로 사용할까요?", True):
                return _safe_bot_result(diagnosis, source, False)
            if _has_token_environment():
                _explain_environment_override()
    token = _hidden_token()
    diagnosis = _check_bot(token, factory)
    # A failed authentication above never replaces an existing token file.
    save_bot_token(token, path, replace=replace_token)
    return _safe_bot_result(diagnosis, str(path), True)


def setup_publisher(config_path=None, name=None, guild_id=DEFAULT_GUILD_ID, api=None):
    config = publisher.load_config(config_path, missing_ok=True)
    if not config["webhooks"]:
        result = publisher.setup(config_path=config_path, name=name, guild_id=guild_id, api=api)
        return dict(result, status="configured", access_checked=True)
    if name is not None:
        publisher.update_profile(name, config_path)
        config["display_name"] = name.strip()
    safe = {
        "status": "reused",
        "username": publisher.display_username(config["display_name"]),
        "channel_ids": list(config["webhooks"]),
        "access_checked": False,
    }
    print(json.dumps(safe, ensure_ascii=False, indent=2))
    if _ask("다른 채널의 웹훅도 추가할까요?", False):
        result = publisher.setup(config_path=config_path, name=name, guild_id=guild_id, api=api)
        return dict(result, status="configured", access_checked=True)
    return safe


def setup_profile(name=None, config_path=None):
    """Save only an author name; preserve any advanced webhook settings offline."""
    config = publisher.load_config(config_path, missing_ok=True)
    if name is None:
        name = config["display_name"] or input("표시 이름: ").strip()
    publisher.display_username(name)
    name = name.strip()
    changed = name != config["display_name"]
    if changed:
        config["display_name"] = name
        publisher.save_config(config, config_path)
    path = Path(config_path).expanduser() if config_path is not None else publisher.default_config_path()
    return {
        "status": "configured" if changed else "reused",
        "display_name": name,
        "config_path": str(path),
        "message_sent": False,
    }


def _failure_result(error):
    return {"status": "failed", "error": str(error)}


def run_setup(skip_bot=False, skip_publish=False, name=None, guild_id=DEFAULT_GUILD_ID,
              replace_token=False, with_webhook=False):
    if skip_bot and skip_publish:
        raise SetupError("--skip-bot과 --skip-publish를 동시에 지정할 수 없습니다.")
    if skip_bot and replace_token:
        raise SetupError("--replace-token은 봇 설정을 진행할 때만 사용할 수 있습니다.")
    result = {"complete": True, "message_sent": False}
    if skip_bot:
        result["bot"] = {"status": "skipped"}
    else:
        try:
            result["bot"] = setup_bot(replace_token=replace_token)
        except (SetupError, reader.ReaderError) as error:
            result["bot"] = _failure_result(error)
            result["complete"] = False
    if skip_publish:
        result["publishing"] = {"status": "skipped"}
    else:
        try:
            if with_webhook:
                if _ask("웹훅 게시도 설정할까요?", True):
                    result["publishing"] = setup_publisher(name=name, guild_id=guild_id)
                else:
                    result["publishing"] = {"status": "skipped"}
            else:
                result["publishing"] = setup_profile(name=name)
        except (SetupError, publisher.PublisherError) as error:
            result["publishing"] = _failure_result(error)
            result["complete"] = False
    if not result["complete"]:
        result["note"] = "완료된 단계의 설정은 저장되어 있습니다. 실패한 단계만 다시 설정하세요."
    return result, 0 if result["complete"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-bot", action="store_true", help="Set up the author name without reading bot credentials")
    parser.add_argument("--skip-publish", action="store_true", help="Set up the bot only; skip author-name and optional webhook settings")
    parser.add_argument("--name", help="Self-declared author name for problem-channel submissions")
    parser.add_argument("--guild-id", default=DEFAULT_GUILD_ID, help="Expected server ID for optional --with-webhook setup")
    parser.add_argument("--with-webhook", action="store_true", help="Also offer the advanced text-webhook setup flow")
    parser.add_argument("--replace-token", action="store_true", help="Validate and replace the dedicated bot token; preserve other dotenv entries")
    args = parser.parse_args(argv)
    try:
        result, status = run_setup(**vars(args))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return status
    except (SetupError, reader.ReaderError, publisher.PublisherError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except EOFError:
        print("입력이 종료되었습니다. 이미 완료된 단계의 설정은 보존되어 있습니다.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("설정을 중단했습니다. 이미 완료된 단계의 설정은 보존되어 있습니다. 메시지는 전송하지 않았습니다.", file=sys.stderr)
        return 130
    except (OSError, ValueError, TypeError, http.client.HTTPException):
        print("설정을 완료하지 못했습니다. 로컬 파일·입력·연결을 확인하세요. 완료된 단계의 설정은 보존되어 있습니다.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
