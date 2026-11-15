"""Locate bundled assets and install an independently runnable Codex skill."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile

VERSION = "0.1.0"
SKILL_NAME = "discord-channel-reader"
MANIFEST_NAME = ".desktop-install.json"


class InstallError(Exception):
    pass


def skill_payload():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "skills" / SKILL_NAME
    return Path(__file__).resolve().parents[1]


def runtime_directory():
    if not getattr(sys, "frozen", False):
        raise InstallError("실행 파일 배포판에서 설치하세요. 소스 실행은 Python이 필요합니다.")
    executable = Path(sys.executable).resolve()
    if executable.name.lower() in ("pqc-discord", "pqc-discord.exe"):
        return executable.parent
    if sys.platform == "darwin":
        return executable.parents[3] / "pqc-discord"
    return executable.parents[1] / "pqc-discord"


def _fingerprint(path):
    if path.is_symlink():
        return "link:" + os.readlink(path)
    if not path.is_file():
        raise InstallError("설치 대상에 일반 파일이 아닌 항목이 있습니다.")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _entries(root, prefix=Path()):
    root = root.resolve()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in ("__pycache__", ".git", "bin", ".venv") for part in relative.parts):
            continue
        if path.name.startswith(".env") or path.name in ("publisher.json", MANIFEST_NAME):
            continue
        if path.suffix in (".pyc", ".pyo"):
            continue
        if path.is_symlink():
            if os.path.isabs(os.readlink(path)):
                raise InstallError("배포 파일에 이동할 수 없는 절대 경로 링크가 있습니다.")
            try:
                path.resolve(strict=True).relative_to(root)
            except (ValueError, OSError):
                raise InstallError("배포 파일에 외부 경로를 가리키는 링크가 있습니다.") from None
            yield prefix / relative, path
        elif path.is_file():
            yield prefix / relative, path


def _check_parents(target, relative):
    current = target
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            raise InstallError("설치 경로에 충돌하는 파일이나 링크가 있습니다. 기존 파일을 보존했습니다.")


def install_skill(target=None, payload=None, runtime=None):
    """Atomically replace managed files; reject locally modified files before any write."""
    payload = Path(payload) if payload is not None else skill_payload()
    runtime = Path(runtime) if runtime is not None else runtime_directory()
    if target is None:
        configured_home = os.environ.get("CODEX_HOME")
        codex_root = Path(configured_home).expanduser() if configured_home else Path.home() / ".codex"
        target = codex_root / "skills" / SKILL_NAME
    else:
        target = Path(target)
    executable_name = "pqc-discord.exe" if sys.platform == "win32" else "pqc-discord"
    if not (payload / "SKILL.md").is_file() or not (runtime / executable_name).is_file():
        raise InstallError("설치 파일이 없습니다. 압축을 모두 풀고 앱과 pqc-discord 폴더를 함께 보관하세요.")
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise InstallError("기존 스킬 경로가 폴더가 아닙니다. 기존 파일을 보존했습니다.")
    prior = {}
    manifest = target / MANIFEST_NAME
    if manifest.exists():
        try:
            if manifest.is_symlink():
                raise ValueError()
            prior = json.loads(manifest.read_text(encoding="utf-8"))["files"]
            if not isinstance(prior, dict):
                raise ValueError()
        except (ValueError, KeyError, OSError):
            raise InstallError("기존 설치 기록을 읽을 수 없습니다. 기존 스킬을 보존했습니다.") from None
    legacy = {}
    legacy_file = payload / "assets" / "legacy-skill-hashes.json"
    if legacy_file.is_file():
        legacy = json.loads(legacy_file.read_text(encoding="utf-8"))
    entries = list(_entries(payload)) + list(_entries(runtime, Path("bin")))
    fingerprints = {}
    for relative, source in entries:
        key = relative.as_posix()
        fingerprint = _fingerprint(source)
        fingerprints[key] = fingerprint
        _check_parents(target, relative)
        destination = target / relative
        if destination.exists() or destination.is_symlink():
            old = _fingerprint(destination)
            allowed = {fingerprint, prior.get(key)}
            allowed.update("sha256:" + digest for digest in legacy.get(key, []))
            if old not in allowed:
                raise InstallError("직접 수정한 스킬 파일이 있어 덮어쓰지 않았습니다: " + key)
    stage = backup = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".discord-install-", dir=target.parent))
        if target.exists():
            shutil.copytree(target, stage, dirs_exist_ok=True, symlinks=True)
        for relative, source in entries:
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_symlink():
                destination.unlink()
            if source.is_symlink():
                if destination.exists():
                    destination.unlink()
                destination.symlink_to(os.readlink(source), target_is_directory=source.is_dir())
            else:
                shutil.copy2(source, destination)
        (stage / MANIFEST_NAME).write_text(json.dumps({"version": VERSION, "files": fingerprints}, indent=2) + "\n", encoding="utf-8")
        if target.exists():
            backup = Path(tempfile.mkdtemp(prefix=".discord-previous-", dir=target.parent))
            backup.rmdir()
            target.rename(backup)
        try:
            stage.rename(target)
            stage = None
        except OSError:
            if backup is not None:
                backup.rename(target)
                backup = None
            raise
        if backup is not None:
            shutil.rmtree(backup)
            backup = None
        return {"installed": True, "path": str(target), "runtime": str(target / "bin" / executable_name), "version": VERSION}
    except OSError:
        raise InstallError("스킬 설치를 완료하지 못했습니다. 폴더 권한과 남은 공간을 확인하세요.") from None
    finally:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
