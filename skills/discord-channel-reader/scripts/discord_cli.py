#!/usr/bin/env python3
"""PQC Discord standalone command runner; no external Python installation required."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

from desktop_runtime import VERSION, InstallError, install_skill, skill_payload


def self_test():
    import discord_publish as publisher
    import discord_reader as reader
    import discord_setup as setup
    import discord_submit as submit
    import zipfile
    from discord_tls import https_handler

    context = https_handler()._context
    if not context.get_ca_certs():
        raise RuntimeError("No trusted CA certificates bundled")
    if not (skill_payload() / "SKILL.md").is_file():
        raise RuntimeError("Bundled skill assets missing")
    config = {"version": 1, "display_name": "테스트", "webhooks": {"234567890123456789": {
        "guild_id": reader.DEFAULT_GUILD_ID, "webhook_id": "345678901234567890",
        "url": "https://discord.com/api/webhooks/345678901234567890/offline-test-token",
    }}}
    with tempfile.TemporaryDirectory(prefix="pqc-discord-selftest-") as scratch:
        path = Path(scratch) / "publisher.json"
        publisher.save_config(config, path)
        preview = publisher.Publisher(publisher.load_config(path)).preview("234567890123456789", "오프라인 확인")
        if preview["sent"] or preview["username"] != "테스트 · Codex":
            raise RuntimeError("Publisher preview failed")
        token_path = Path(scratch) / ".env"
        setup.save_bot_token("offline-test-token", token_path)
        if reader.load_token(str(token_path), environ={})[0] != "offline-test-token":
            raise RuntimeError("Credential round trip failed")
        source = Path(scratch) / "solution.zip"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("README.md", "Offline packaging check")
        report = Path(scratch) / "report.md"
        report.write_text("# 오프라인 제출 확인\n", encoding="utf-8")
        submission = submit.Submitter(config).preview("234567890123456789", submit.load_files(source, report))
        if submission["username"] != "테스트 · Codex" or len(submission["files"]) != 2:
            raise RuntimeError("Submission preview failed")
    return {"ok": True, "version": VERSION, "frozen": bool(getattr(sys, "frozen", False)), "network_used": False,
            "category_id": reader.DEFAULT_CATEGORY_ID, "ca_count": len(context.get_ca_certs())}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print("PQC Discord " + VERSION + "\nCommands: read, submit, publish, setup, install, self-test, --version\n"
              "Example: pqc-discord read channels\nExample: pqc-discord submit preview --channel-id ID --source-zip solution.zip --report report.md")
        return 0
    command, rest = argv[0], argv[1:]
    try:
        if command == "--version":
            print(VERSION)
            return 0
        if command in ("read", "submit", "publish", "setup"):
            if command == "read":
                import discord_reader as module
            elif command == "publish":
                import discord_publish as module
            elif command == "submit":
                import discord_submit as module
            else:
                import discord_setup as module
            return module.main(rest)
        if rest:
            raise InstallError("이 명령에는 추가 인자가 필요하지 않습니다.")
        if command == "install":
            result = install_skill()
        elif command == "self-test":
            result = self_test()
        else:
            raise InstallError("지원하지 않는 명령입니다. --help를 확인하세요.")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except InstallError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError):
        print("실행을 완료하지 못했습니다. 배포 파일·설치 경로를 확인하세요.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
