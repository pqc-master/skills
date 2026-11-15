"""Locate bundled resources and install the complete PQC skill set."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

VERSION = "0.2.1"
SKILL_NAME = "discord-channel-reader"
SKILL_NAMES = (SKILL_NAME, "pqc-discord-workflow", "pqc-identify", "pqc-migrate", "pqc-report")
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


def _default_skills_directory():
    configured_home = os.environ.get("CODEX_HOME")
    codex_root = Path(configured_home).expanduser() if configured_home else Path.home() / ".codex"
    return codex_root / "skills"


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


def _plan_install(payload, target, runtime=None):
    if payload.is_symlink() or not (payload / "SKILL.md").is_file():
        raise InstallError("필수 스킬이 배포 파일에 없습니다: " + payload.name)
    executable_name = "pqc-discord.exe" if sys.platform == "win32" else "pqc-discord"
    if runtime is not None and not (runtime / executable_name).is_file():
        raise InstallError("실행 파일이 없습니다. 압축을 모두 풀고 앱과 pqc-discord 폴더를 함께 보관하세요.")
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise InstallError("기존 스킬 경로가 폴더가 아닙니다. 기존 파일을 보존했습니다.")
    prior = {}
    manifest = target / MANIFEST_NAME
    if manifest.exists() or manifest.is_symlink():
        try:
            if manifest.is_symlink():
                raise ValueError()
            prior = json.loads(manifest.read_text(encoding="utf-8"))["files"]
            if not isinstance(prior, dict) or not all(isinstance(key, str) and isinstance(value, str)
                                                     for key, value in prior.items()):
                raise ValueError()
        except (ValueError, KeyError, TypeError, OSError):
            raise InstallError("기존 설치 기록을 읽을 수 없습니다. 기존 스킬을 보존했습니다.") from None
    legacy = {}
    legacy_file = payload / "assets" / "legacy-skill-hashes.json"
    if legacy_file.is_file():
        try:
            legacy = json.loads(legacy_file.read_text(encoding="utf-8"))
            if not isinstance(legacy, dict) or not all(isinstance(key, str) and isinstance(values, list)
                                                       and all(isinstance(value, str) for value in values)
                                                       for key, values in legacy.items()):
                raise ValueError()
        except (ValueError, TypeError, OSError):
            raise InstallError("배포 파일의 이전 버전 정보를 읽을 수 없습니다.") from None
    entries = list(_entries(payload))
    if runtime is not None:
        entries += list(_entries(runtime, Path("bin")))
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
                raise InstallError("직접 수정한 스킬 파일이 있어 덮어쓰지 않았습니다: " + target.name + "/" + key)
    return {"target": target, "entries": entries, "fingerprints": fingerprints}


def _stage_plan(plan):
    target = plan["target"]
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".pqc-install-", dir=target.parent))
    try:
        if target.exists():
            shutil.copytree(target, stage, dirs_exist_ok=True, symlinks=True)
        for relative, source in plan["entries"]:
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
        (stage / MANIFEST_NAME).write_text(
            json.dumps({"version": VERSION, "files": plan["fingerprints"]}, indent=2) + "\n", encoding="utf-8")
        return stage
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _apply_plans(plans):
    """Stage every skill first, then replace; recover all previous targets on failure."""
    stages = {}
    changes = []
    try:
        # In particular, this finishes copying an installed CLI before replacing it.
        for plan in plans:
            stages[plan["target"]] = _stage_plan(plan)
        for plan in plans:
            target = plan["target"]
            backup = None
            if target.exists():
                backup = Path(tempfile.mkdtemp(prefix=".pqc-previous-", dir=target.parent))
                backup.rmdir()
                target.rename(backup)
            changes.append((target, backup))
            stages[target].rename(target)
            del stages[target]
    except BaseException as error:
        recovery_errors = []
        for target, backup in reversed(changes):
            try:
                if target.exists():
                    shutil.rmtree(target)
                if backup is not None:
                    backup.rename(target)
            except OSError:
                # Keep the backup untouched if recovery itself cannot finish.
                recovery_errors.append(str(backup or target))
        if recovery_errors:
            raise InstallError("설치 복구를 완료하지 못했습니다. 이전 파일을 보관한 경로: "
                               + ", ".join(recovery_errors)) from None
        if isinstance(error, (OSError, shutil.Error)):
            raise InstallError("스킬 설치를 완료하지 못했습니다. 기존 스킬을 복원했습니다. 폴더 권한과 남은 공간을 확인하세요.") from None
        raise
    finally:
        for stage in stages.values():
            shutil.rmtree(stage, ignore_errors=True)
    # Backup cleanup is best effort; an otherwise successful installation is usable.
    for _, backup in changes:
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)


def install_bundle(target_directory=None, payload_directory=None, runtime=None, include_runtime=True):
    """Install all five sibling skills after checking the entire set for conflicts."""
    target_directory = Path(target_directory) if target_directory is not None else _default_skills_directory()
    payload_directory = Path(payload_directory) if payload_directory is not None else skill_payload().parent
    runtime = (Path(runtime) if runtime is not None else runtime_directory()) if include_runtime else None
    if target_directory.is_symlink() or (target_directory.exists() and not target_directory.is_dir()):
        raise InstallError("스킬 설치 위치가 일반 폴더가 아닙니다. 기존 파일을 보존했습니다.")
    if not include_runtime and (target_directory / SKILL_NAME / "bin").exists():
        raise InstallError("실행 파일로 설치된 스킬입니다. 새 앱으로 갱신하거나 별도의 소스 설치 경로를 지정하세요.")
    plans = [_plan_install(payload_directory / name, target_directory / name,
                           runtime if name == SKILL_NAME else None) for name in SKILL_NAMES]
    _apply_plans(plans)
    executable_name = "pqc-discord.exe" if sys.platform == "win32" else "pqc-discord"
    target = target_directory / SKILL_NAME
    return {"installed": True, "path": str(target),
            "runtime": str(target / "bin" / executable_name) if include_runtime else None,
            "version": VERSION, "skills": list(SKILL_NAMES),
            "skill_paths": {name: str(target_directory / name) for name in SKILL_NAMES}}


def install_skill(target=None, payload=None, runtime=None):
    """Default app action installs the bundle; explicit arguments retain single-skill use."""
    if target is None and payload is None and runtime is None:
        return install_bundle()
    payload = Path(payload) if payload is not None else skill_payload()
    runtime = Path(runtime) if runtime is not None else runtime_directory()
    target = Path(target) if target is not None else _default_skills_directory() / SKILL_NAME
    plan = _plan_install(payload, target, runtime)
    _apply_plans([plan])
    executable_name = "pqc-discord.exe" if sys.platform == "win32" else "pqc-discord"
    return {"installed": True, "path": str(target), "runtime": str(target / "bin" / executable_name), "version": VERSION}


def install_smoke_test():
    """Check the frozen installer and copied executable without touching user settings."""
    runtime = runtime_directory()  # Source mode must not claim a Python-free installation.
    with tempfile.TemporaryDirectory(prefix="pqc-bundle-install-test-") as temporary:
        result = install_bundle(target_directory=Path(temporary) / "skills", runtime=runtime)
        if result["skills"] != list(SKILL_NAMES):
            raise InstallError("필수 스킬 설치 확인에 실패했습니다.")
        for path in result["skill_paths"].values():
            if not (Path(path) / "SKILL.md").is_file():
                raise InstallError("필수 스킬 설치 확인에 실패했습니다.")
        try:
            check = subprocess.run([result["runtime"], "self-test"], check=True, capture_output=True,
                                   text=True, timeout=120)
            data = json.loads(check.stdout)
            if data.get("ok") is not True or data.get("frozen") is not True:
                raise ValueError()
        except (OSError, ValueError, subprocess.SubprocessError):
            raise InstallError("설치된 실행 파일의 자체 검사에 실패했습니다.") from None
    return {"ok": True, "version": VERSION, "skills": list(SKILL_NAMES), "network_used": False}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Install all five PQC skills from a source checkout.")
    parser.add_argument("--source", action="store_true", required=True,
                        help="Install source skills; their commands require Python 3.9 or later")
    parser.add_argument("--target-skills-dir", type=Path, help="Optional explicit skills directory")
    args = parser.parse_args(argv)
    try:
        result = install_bundle(target_directory=args.target_skills_dir, include_runtime=False)
    except (OSError, InstallError) as error:
        parser.exit(1, str(error) + "\n" if isinstance(error, InstallError) else "스킬 설치를 완료하지 못했습니다.\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
