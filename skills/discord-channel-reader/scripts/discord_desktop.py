#!/usr/bin/env python3
"""Native bot and author settings for submissions to the current problem channel."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import webbrowser

SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)
import discord_reader as reader
import discord_publish as publisher
import discord_setup as setup


DEFAULT_GUILD_ID = reader.DEFAULT_GUILD_ID
DEFAULT_CATEGORY_ID = reader.DEFAULT_CATEGORY_ID
GUIDE_URL = "https://github.com/pqc-master/skills/blob/main/skills/discord-channel-reader/references/setup.md"


class DesktopError(Exception):
    """A settings error with no credential values in its message."""


def _safe_error(error):
    if isinstance(error, (DesktopError, reader.ReaderError, publisher.PublisherError, setup.SetupError)):
        return str(error)
    return "설정을 완료하지 못했습니다. 입력한 정보, 파일 권한과 네트워크 연결을 확인하세요."


class SetupService:
    """Headless settings service; all returned values are safe to display."""

    def __init__(self, config_dir=None, reader_factory=None, webhook_api=None,
                 environ=None, installer=None, use_legacy=None):
        self.config_dir = Path(config_dir) if config_dir is not None else Path.home() / ".config/discord-channel-reader"
        self.bot_path = self.config_dir / ".env"
        self.publisher_path = self.config_dir / "publisher.json"
        self.reader_factory = reader_factory if reader_factory is not None else lambda token: reader.Reader(reader.DiscordAPI(token))
        self.webhook_api = webhook_api if webhook_api is not None else publisher.WebhookAPI()
        self.environ = dict(os.environ if environ is None else environ)
        self.installer = installer
        self.use_legacy = (config_dir is None) if use_legacy is None else use_legacy

    def _load_bot(self):
        if any(self.environ.get(key, "").strip() for key in setup.TOKEN_VARIABLES):
            return reader.load_token(str(self.bot_path), environ=self.environ)
        if self.bot_path.exists() or self.bot_path.is_symlink():
            return reader.load_token(str(self.bot_path), environ=self.environ)
        if self.use_legacy:
            legacy = Path.home() / ".fiesta-discord/.env"
            if legacy.exists() or legacy.is_symlink():
                return reader.load_token(str(legacy), environ=self.environ)
        return None, None

    def inspect(self):
        state = {
            "bot_status": "아직 저장된 봇 토큰이 없습니다.",
            "bot_source": None,
            "display_name": "",
            "channel_ids": [],
            "publisher_status": "결과를 올릴 때 사용할 표시 이름을 입력하세요.",
            "server_id": DEFAULT_GUILD_ID,
            "category_id": DEFAULT_CATEGORY_ID,
            "errors": [],
        }
        try:
            token, source = self._load_bot()
            if token is not None:
                state["bot_source"] = source
                state["bot_status"] = "기존 봇 토큰을 사용합니다. 변경하지 않으려면 입력란을 비워 두세요."
                if source == "process environment":
                    state["bot_status"] = "환경변수의 봇 토큰이 우선 사용됩니다. 이 창에서 토큰을 바꾸려면 환경변수를 해제하고 앱을 다시 여세요."
                elif self.use_legacy and str(source) == str(Path.home() / ".fiesta-discord/.env"):
                    state["bot_status"] = "기존 Fiesta 설정의 봇 토큰을 사용합니다. 새 토큰을 입력하면 이 앱의 전용 설정에 저장합니다."
        except (reader.ReaderError, OSError) as error:
            state["errors"].append(_safe_error(error))
            state["bot_status"] = "기존 봇 설정을 읽지 못했습니다. 아래 상태 안내를 확인하세요."
        try:
            config = publisher.load_config(self.publisher_path, missing_ok=True)
            state["display_name"] = config["display_name"]
            state["channel_ids"] = list(config["webhooks"])
            if state["display_name"]:
                state["publisher_status"] = "저장된 표시 이름을 사용합니다. 게시할 문제 채널은 작업할 때 정합니다."
        except (publisher.PublisherError, OSError) as error:
            state["errors"].append(_safe_error(error))
            state["publisher_status"] = "기존 표시 이름을 읽지 못했습니다. 아래 상태 안내를 확인하세요."
        return state

    def _bot_stage(self, token):
        if token:
            if any(self.environ.get(key, "").strip() for key in setup.TOKEN_VARIABLES):
                raise DesktopError(
                    "환경변수 DISCORD_BOT_TOKEN 또는 FIESTA_RELAY_BOT_TOKEN이 파일보다 우선합니다. "
                    "해당 환경변수를 해제하고 앱을 다시 연 뒤 토큰을 저장하세요. 기존 설정은 변경하지 않았습니다."
                )
            if any(character.isspace() for character in token):
                raise DesktopError("봇 토큰만 입력하세요. 'Bot ' 접두사는 제외합니다.")
            diagnosis = self.reader_factory(token).doctor()
            setup.save_bot_token(token, self.bot_path, replace=self.bot_path.exists() or self.bot_path.is_symlink())
            source = str(self.bot_path)
            status, message = "configured", "새 봇 토큰을 확인하고 저장했습니다."
        else:
            token, source = self._load_bot()
            if token is None:
                return {"status": "skipped", "message": "봇 토큰이 아직 없습니다. 문제 채널에 결과를 올리려면 봇 토큰을 설정하세요."}
            diagnosis = self.reader_factory(token).doctor()
            status, message = "verified", "기존 봇 연결을 확인했습니다. 토큰은 변경하지 않았습니다."
            if source == "process environment":
                message = "환경변수의 봇 연결을 확인했습니다. 로컬 파일에 토큰을 복사하지 않았습니다."
            elif self.use_legacy and str(source) == str(Path.home() / ".fiesta-discord/.env"):
                message = "기존 Fiesta 봇 연결을 확인했습니다. 해당 설정 파일은 변경하지 않았습니다."
        result = {"status": status, "message": message, "credential_source": source}
        for key in ("bot_id", "username", "bot_authentication", "message_content_intent", "warning", "channel_access"):
            if key in diagnosis:
                result[key] = diagnosis[key]
        return result

    def _publisher_stage(self, name, webhook_url):
        config = publisher.load_config(self.publisher_path, missing_ok=True)
        if not webhook_url and not name:
            return {
                "status": "preserved" if config["display_name"] else "skipped",
                "message": "기존 표시 이름을 유지합니다." if config["display_name"] else "결과를 올릴 때 사용할 표시 이름을 입력하세요.",
                "display_name": config["display_name"] or None,
                "username": publisher.display_username(config["display_name"]) if config["display_name"] else None,
                "channel_ids": list(config["webhooks"]),
                "access_checked": False,
            }
        chosen_name = name or config["display_name"]
        if not chosen_name:
            raise DesktopError("웹훅을 등록하려면 표시 이름을 입력하세요.")
        username = publisher.display_username(chosen_name)
        if not webhook_url:
            if not config["webhooks"]:
                config["display_name"] = chosen_name
                publisher.save_config(config, self.publisher_path)
                status, message = "profile_updated", "표시 이름을 저장했습니다. 문제 채널에 결과를 올릴 때 이 이름을 사용합니다."
            elif chosen_name != config["display_name"]:
                publisher.update_profile(chosen_name, self.publisher_path)
                status, message = "profile_updated", "표시 이름을 변경했습니다."
            else:
                status, message = "preserved", "기존 표시 이름을 유지합니다."
            return {"status": status, "message": message, "display_name": chosen_name, "username": username,
                    "channel_ids": list(config["webhooks"]), "access_checked": False}
        url, webhook_id = publisher.normalize_webhook_url(webhook_url)
        metadata = publisher.validate_metadata(self.webhook_api.get(url), webhook_id, DEFAULT_GUILD_ID)
        config["display_name"] = chosen_name
        config["webhooks"][metadata["channel_id"]] = {
            "guild_id": metadata["guild_id"], "webhook_id": webhook_id, "url": url,
        }
        publisher.save_config(config, self.publisher_path)
        return {"status": "configured", "message": "웹훅 연결을 확인하고 작성자 이름과 게시 채널을 저장했습니다.",
                "username": username, "channel_ids": list(config["webhooks"]), "access_checked": True}

    def save(self, bot_token="", display_name="", webhook_url=""):
        result = {"complete": True, "message_sent": False}
        values = (bot_token, display_name, webhook_url)
        if not all(isinstance(value, str) for value in values):
            return {"complete": False, "message_sent": False, "summary": "입력값을 확인하세요.",
                    "bot": {"status": "failed", "message": "설정값은 문자열이어야 합니다."},
                    "publishing": {"status": "skipped", "message": "설정값을 저장하지 않았습니다."}}
        for key, operation in (
            ("bot", lambda: self._bot_stage(bot_token.strip())),
            ("publishing", lambda: self._publisher_stage(display_name.strip(), webhook_url.strip())),
        ):
            try:
                result[key] = operation()
            except Exception as error:
                # Never expose transport exception reprs or remote response bodies: URLs contain secrets.
                result[key] = {"status": "failed", "message": _safe_error(error)}
                result["complete"] = False
        if result["complete"] and all(result[key]["status"] == "skipped" for key in ("bot", "publishing")):
            result["complete"] = False
            result["summary"] = "봇 토큰과 표시 이름을 입력하세요. 저장된 설정은 변경하지 않았습니다."
        elif result["complete"] and result["bot"]["status"] == "skipped":
            result["summary"] = "표시 이름을 저장했습니다. 문제 채널에 결과를 올리려면 봇 토큰도 설정하세요."
        elif result["complete"] and result["publishing"]["status"] == "skipped":
            result["summary"] = "봇 연결을 확인했습니다. 결과 작성자를 구분하려면 표시 이름도 입력하세요."
        elif result["complete"]:
            result["summary"] = "설정이 완료되었습니다. 메시지는 전송하지 않았습니다."
        else:
            result["summary"] = "일부 설정을 완료하지 못했습니다. 성공한 단계는 저장되어 있으니 실패한 항목만 확인하세요. 메시지는 전송하지 않았습니다."
        return result

    def install(self):
        if self.installer is None:
            raise DesktopError("Codex 스킬 설치는 실행 파일 배포본에서 사용할 수 있습니다.")
        try:
            return self.installer()
        except Exception as error:
            from desktop_runtime import InstallError
            if isinstance(error, InstallError):
                raise DesktopError(str(error)) from None
            raise DesktopError(_safe_error(error)) from None


def _create_root():
    import tkinter as tk
    return tk.Tk()


def _create_smoke_view(root):
    class SmokeService:
        installer = None

        def inspect(self):
            return {"bot_status": "오프라인 실행 확인", "publisher_status": "가상 표시 이름",
                    "display_name": "테스트", "errors": []}

    return DiscordDesktop(root, SmokeService(), demo=True)


def smoke_test():
    """Render the real form with fake state; no credentials, home lookup or network."""
    root = _create_root()
    try:
        root.title("PQC Discord")
        root.geometry("360x120")
        _create_smoke_view(root)
        root.update_idletasks()
        root.update()
    finally:
        root.destroy()
    return 0


class DiscordDesktop:
    def __init__(self, root, service, guide_url=GUIDE_URL, demo=False):
        import tkinter as tk
        from tkinter import ttk
        self.root = root
        self.service = service
        self.guide_url = guide_url
        self.events = queue.Queue()
        self.closed = False
        self.busy = False
        self.tk = tk
        self.root.title("PQC Discord")
        self.root.geometry("760x620")
        self.root.minsize(660, 560)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.token = tk.StringVar()
        self.name = tk.StringVar()
        self.bot_status = tk.StringVar()
        self.name_status = tk.StringVar()
        self.activity = tk.StringVar(value="설정을 입력한 뒤 저장하세요.")
        frame = ttk.Frame(root, padding=(24, 20))
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(11, weight=1)
        ttk.Label(frame, text="PQC Discord", font=("TkDefaultFont", 20, "bold")).grid(row=0, column=0, sticky="w")
        subtitle = "봇 연결과 작성자 이름을 설정합니다. 결과는 작업한 문제 채널에 올립니다."
        if demo:
            subtitle = "데모 화면 · 실제 계정이나 채널에 연결하지 않습니다."
        ttk.Label(frame, text=subtitle).grid(row=1, column=0, sticky="w", pady=(6, 12))
        ttk.Label(frame, text=f"서버  {DEFAULT_GUILD_ID}     카테고리  {DEFAULT_CATEGORY_ID}").grid(row=2, column=0, sticky="w", pady=(0, 16))
        ttk.Label(frame, text="봇 토큰 · 문제 채널 조회와 결과 게시").grid(row=3, column=0, sticky="w")
        self.token_entry = ttk.Entry(frame, textvariable=self.token, show="*")
        self.token_entry.grid(row=4, column=0, sticky="ew", pady=(5, 4))
        ttk.Label(frame, textvariable=self.bot_status, wraplength=690).grid(row=5, column=0, sticky="w", pady=(0, 12))
        ttk.Label(frame, text="표시 이름 · 게시물 상단에 ‘이름 · Codex’로 표시됩니다").grid(row=6, column=0, sticky="w")
        self.name_entry = ttk.Entry(frame, textvariable=self.name)
        self.name_entry.grid(row=7, column=0, sticky="ew", pady=(5, 12))
        ttk.Label(frame, textvariable=self.name_status, wraplength=690).grid(row=8, column=0, sticky="w")
        ttk.Label(frame, text="봇 토큰은 비워 두면 기존 값을 유지합니다. 결과는 작업한 문제 채널에 제출하며 봇에 ‘웹후크 관리’ 권한이 필요합니다. 설정 중에는 글을 올리지 않습니다.", wraplength=690).grid(row=9, column=0, sticky="w", pady=(6, 12))
        actions = ttk.Frame(frame)
        actions.grid(row=10, column=0, sticky="ew", pady=(0, 12))
        self.save_button = ttk.Button(actions, text="저장하고 연결 확인", command=self._save)
        self.save_button.pack(side="left")
        self.install_button = ttk.Button(actions, text="Codex에 스킬 설치", command=self._install)
        self.install_button.pack(side="left", padx=8)
        ttk.Button(actions, text="설정 가이드 열기", command=self._open_guide).pack(side="left")
        if self.service.installer is None:
            self.install_button.state(["disabled"])
        status_frame = ttk.LabelFrame(frame, text="진행 상태", padding=8)
        status_frame.grid(row=11, column=0, sticky="nsew")
        status_frame.columnconfigure(0, weight=1)
        status_frame.rowconfigure(1, weight=1)
        ttk.Label(status_frame, textvariable=self.activity).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.log = tk.Text(status_frame, wrap="word", height=8, state="disabled", relief="flat")
        self.log.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(status_frame, orient="vertical", command=self.log.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)
        self._refresh_state()
        if self.service.installer is None and not demo:
            self._append("Codex 스킬 설치는 실행 파일 배포본에서 사용할 수 있습니다.")
        self.root.after(100, self._poll_events)

    def _refresh_state(self):
        state = self.service.inspect()
        self.bot_status.set(state["bot_status"])
        self.name_status.set(state["publisher_status"])
        self.name.set(state["display_name"])
        for error in state["errors"]:
            self._append(error)

    def _append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", str(text) + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_busy(self, busy):
        self.busy = busy
        for widget in (self.token_entry, self.name_entry, self.save_button):
            widget.state(["disabled"] if busy else ["!disabled"])
        self.install_button.state(["disabled"] if busy or self.service.installer is None else ["!disabled"])

    def _start(self, kind, operation):
        if self.busy:
            return
        self._set_busy(True)
        self.activity.set("연결을 확인하고 있습니다…" if kind == "save" else "Codex 스킬을 설치하고 있습니다…")
        def work():
            try:
                result = operation()
                self.events.put((kind, result, None))
            except Exception as error:
                self.events.put((kind, None, _safe_error(error)))
        threading.Thread(target=work, daemon=True).start()

    def _save(self):
        if self.busy:
            return
        token, name = self.token.get(), self.name.get()
        self.token.set("")
        self._start("save", lambda: self.service.save(token, name))

    def _install(self):
        self._start("install", self.service.install)

    def _poll_events(self):
        if self.closed:
            return
        try:
            while True:
                kind, result, error = self.events.get_nowait()
                self._set_busy(False)
                if error:
                    self.activity.set("작업을 완료하지 못했습니다.")
                    self._append(error)
                elif kind == "save":
                    self.activity.set("설정 완료" if result["complete"] else "확인이 필요한 항목이 있습니다.")
                    for key, label in (("bot", "봇 연결"), ("publishing", "작성자 이름")):
                        stage = result[key]
                        self._append(f"[{label}] {stage['message']}")
                        shown_name = stage.get("display_name") if key == "publishing" else stage.get("username")
                        if shown_name:
                            self._append("이름: " + str(shown_name))
                        if stage.get("credential_source"):
                            self._append("사용한 설정: " + str(stage["credential_source"]))
                        if stage.get("message_content_intent") is False:
                            self._append("대화 본문을 읽으려면 Developer Portal에서 Message Content Intent를 켜세요.")
                        if stage.get("warning"):
                            self._append(stage["warning"])
                    self._append(result["summary"])
                    self._refresh_state()
                else:
                    self.activity.set("Codex 스킬 설치 완료")
                    self._append("Codex 스킬을 설치했습니다. 새 대화에서 $pqc-discord-workflow를 사용하세요.")
                    if isinstance(result, dict):
                        if result.get("skills"):
                            self._append("설치한 스킬: " + ", ".join(result["skills"]))
                        for key in ("path", "skill_path", "runtime", "runtime_path", "count"):
                            if key in result:
                                self._append(f"{key}: {result[key]}")
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _open_guide(self):
        try:
            webbrowser.open(self.guide_url)
        except Exception:
            self._append("브라우저를 열지 못했습니다. GitHub의 pqc-master/skills 설정 가이드를 확인하세요.")

    def _close(self):
        self.closed = True
        self.root.destroy()


def _demo_service(config_dir):
    channel_id, webhook_id = "123456789012345678", "234567890123456789"
    class DemoReader:
        def doctor(self):
            return {"bot_id": "345678901234567890", "username": "데모 봇", "bot_authentication": "ok",
                    "message_content_intent": True, "warning": None, "channel_access": "not tested"}
    class DemoWebhook:
        def get(self, url):
            _, identifier = publisher.normalize_webhook_url(url)
            return {"type": 1, "id": identifier, "guild_id": DEFAULT_GUILD_ID, "channel_id": channel_id}
    directory = Path(config_dir)
    setup.save_bot_token("demo-bot-token-not-real", directory / ".env")
    publisher.save_config({"version": 1, "display_name": "홍길동", "webhooks": {
        channel_id: {"guild_id": DEFAULT_GUILD_ID, "webhook_id": webhook_id,
                     "url": f"https://discord.com/api/webhooks/{webhook_id}/demo-webhook-token-not-real"},
    }}, directory / "publisher.json")
    return SetupService(directory, reader_factory=lambda token: DemoReader(), webhook_api=DemoWebhook(),
                        environ={}, use_legacy=False)


def _run_window(service, demo=False):
    root = _create_root()
    DiscordDesktop(root, service, demo=demo)
    root.mainloop()
    return 0


def main(argv=None, installer=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-test", action="store_true", help="Render and close an isolated Tk window without reading credentials")
    parser.add_argument("--demo", action="store_true", help="Open an isolated demonstration with fake local settings and no network")
    args = parser.parse_args(argv)
    try:
        if args.smoke_test:
            return smoke_test()
        if args.demo:
            with tempfile.TemporaryDirectory(prefix="pqc-discord-demo-") as directory:
                return _run_window(_demo_service(directory), demo=True)
        if installer is None and getattr(sys, "frozen", False):
            from desktop_runtime import install_skill
            installer = install_skill
        return _run_window(SetupService(installer=installer))
    except Exception:
        print("PQC Discord를 열지 못했습니다. 운영체제에 맞는 실행 파일인지 확인하세요.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
