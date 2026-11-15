#!/usr/bin/env python3
"""Safely extract source ZIPs and package a complete, reviewed project snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import unicodedata
import zipfile

MAX_FILES = 10000
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
EXCLUDED_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "node_modules", "__pycache__",
                 ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDED_FILES = {".DS_Store", "publisher.json", ".npmrc", ".pypirc", "credentials.json"}
ENV_EXAMPLES = {".env.example", ".env.sample", ".env.template"}
RESERVED = {"con", "prn", "aux", "nul", *[f"com{i}" for i in range(1, 10)],
            *[f"lpt{i}" for i in range(1, 10)]}


class WorkspaceError(Exception):
    pass


def _safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise WorkspaceError("Archive contains an unsafe path.")
    parts = name.rstrip("/").split("/")
    for part in parts:
        if (not part or part in (".", "..") or part[-1:] in (".", " ")
                or any(ord(char) < 32 or char in ':<>"|?*' for char in part)
                or part.split(".", 1)[0].casefold() in RESERVED):
            raise WorkspaceError("Archive contains a path unsupported on macOS or Windows.")
    return PurePosixPath(*parts).as_posix()


def _key(name):
    return unicodedata.normalize("NFC", name).casefold()


def _new_output(path):
    path = Path(path).expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise WorkspaceError("Output already exists; choose a new path.")
    return path.parent.resolve() / path.name


def _digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_manifest(path, data):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        try:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        except Exception:
            handle.close()
            path.unlink()
            raise


def _register_spelling(name, spellings):
    parts = name.split("/")
    for length in range(1, len(parts) + 1):
        prefix = "/".join(parts[:length])
        key = _key(prefix)
        if key in spellings and spellings[key] != prefix:
            raise WorkspaceError("Paths collide after case or Unicode normalization.")
        spellings[key] = prefix


def _check_entries(archive):
    items = archive.infolist()
    if len(items) > MAX_FILES:
        raise WorkspaceError("Archive exceeds 10000 entries.")
    seen, files, total, spellings = set(), set(), 0, {}
    entries = []
    for item in items:
        name = _safe_name(item.orig_filename)
        _register_spelling(name, spellings)
        key = _key(name)
        if key in seen:
            raise WorkspaceError("Archive contains duplicate or case-colliding paths.")
        seen.add(key)
        mode = item.external_attr >> 16
        kind = stat.S_IFMT(mode)
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or item.flag_bits & 1:
            raise WorkspaceError("Encrypted archives, links and special files are unsupported.")
        if item.file_size > MAX_FILE_BYTES:
            raise WorkspaceError("An archive entry exceeds 128 MiB.")
        total += item.file_size
        if total > MAX_TOTAL_BYTES:
            raise WorkspaceError("Expanded archive exceeds 512 MiB.")
        if not item.is_dir():
            files.add(key)
        entries.append((item, name, mode))
    for _, name, _ in entries:
        if any(_key(parent.as_posix()) in files for parent in PurePosixPath(name).parents
               if parent != PurePosixPath(".")):
            raise WorkspaceError("Archive has conflicting file and directory paths.")
    return entries


def extract_archive(archive_path, output):
    archive_path = Path(archive_path).expanduser()
    output = _new_output(output)
    manifest_path = _new_output(str(output) + ".extraction.json")
    if not archive_path.is_file():
        raise WorkspaceError("Choose an existing source ZIP.")
    source_hash = _digest(archive_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".pqc-extract-", dir=output.parent))
    try:
        files = []
        with zipfile.ZipFile(archive_path) as archive:
            entries = _check_entries(archive)
            for item, name, mode in entries:
                destination = stage.joinpath(*PurePosixPath(name).parts)
                if item.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest, size = hashlib.sha256(), 0
                with archive.open(item) as source, destination.open("xb") as target:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        size += len(block)
                        if size > item.file_size or size > MAX_FILE_BYTES:
                            raise WorkspaceError("Expanded size does not match archive metadata.")
                        target.write(block)
                        digest.update(block)
                if size != item.file_size:
                    raise WorkspaceError("Expanded size does not match archive metadata.")
                executable = bool(mode & 0o111)
                destination.chmod(0o700 if executable else 0o600)
                files.append({"path": name, "size": size, "sha256": digest.hexdigest(), "executable": executable})
        if source_hash != _digest(archive_path):
            raise WorkspaceError("Source ZIP changed during extraction.")
        result = {"operation": "extract", "archive_path": str(archive_path.absolute()),
                  "archive_sha256": source_hash, "output_directory": str(output),
                  "file_count": len(files), "total_bytes": sum(f["size"] for f in files),
                  "manifest_path": str(manifest_path), "files": files}
        # Create the final directory exclusively. Roll back only directories made here.
        output.mkdir(mode=0o700)
        try:
            for child in stage.iterdir():
                child.rename(output / child.name)
            _write_manifest(manifest_path, result)
        except Exception:
            shutil.rmtree(output)
            raise
        return {key: value for key, value in result.items() if key != "files"}
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _project_files(project):
    files, excluded, seen, total, spellings, folders = [], [], set(), 0, {}, []
    def traversal_error(error):
        raise WorkspaceError("Cannot read a project directory; refusing an incomplete archive.") from None
    for folder, directories, filenames in os.walk(project, followlinks=False, onerror=traversal_error):
        root = Path(folder)
        for name in sorted(directories[:]):
            path = root / name
            relative = path.relative_to(project).as_posix()
            if name.casefold() in EXCLUDED_DIRS:
                directories.remove(name)
                excluded.append({"path": relative + "/", "reason": "VCS, dependency environment or cache"})
            elif path.is_symlink():
                raise WorkspaceError("Project contains a symbolic link; replace it with reviewed project files.")
            else:
                relative = _safe_name(relative)
                _register_spelling(relative, spellings)
                folders.append(relative)
        for name in sorted(filenames):
            path = root / name
            relative = path.relative_to(project).as_posix()
            normalized_name = name.casefold()
            if (normalized_name in {item.casefold() for item in EXCLUDED_FILES} or normalized_name.endswith((".pyc", ".pyo"))
                    or (normalized_name.startswith(".env") and normalized_name not in ENV_EXAMPLES)):
                excluded.append({"path": relative, "reason": "Local configuration, credentials or cache"})
                continue
            if path.is_symlink() or not path.is_file():
                raise WorkspaceError("Project contains a link or special file.")
            relative = _safe_name(relative)
            _register_spelling(relative, spellings)
            key = _key(relative)
            if key in seen:
                raise WorkspaceError("Project paths collide on macOS or Windows.")
            seen.add(key)
            info = path.stat()
            total += info.st_size
            if info.st_size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or len(files) >= MAX_FILES:
                raise WorkspaceError("Project exceeds archive limits; review large/generated files explicitly.")
            with path.open("rb") as source:
                prefix = source.read(16384)
            if (b"PRIVATE KEY-----" in prefix or name.lower().endswith((".p12", ".pfx", ".jks", ".keystore"))):
                raise WorkspaceError("Possible private key/keystore found. Remove secrets from the submission copy.")
            files.append((relative, path, info))
    if not files:
        raise WorkspaceError("The project contains no packageable files.")
    if len(files) + len(folders) > MAX_FILES:
        raise WorkspaceError("Project exceeds 10000 entries.")
    return sorted(files), sorted(excluded, key=lambda item: item["path"]), sorted(folders)


def pack_project(project, output):
    project = Path(project).expanduser().absolute()
    output = _new_output(output)
    manifest_path = _new_output(str(output) + ".manifest.json")
    if project.is_symlink() or not project.is_dir():
        raise WorkspaceError("Choose an existing project directory, not a symbolic link.")
    project = project.resolve()
    try:
        output.resolve().relative_to(project)
    except ValueError:
        pass
    else:
        raise WorkspaceError("Write the ZIP outside the project directory.")
    entries, excluded, folders = _project_files(project)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".pqc-pack-", suffix=".zip", dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary)
    try:
        files = []
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for folder in folders:
                item = zipfile.ZipInfo(folder + "/", date_time=(1980, 1, 1, 0, 0, 0))
                item.create_system = 3
                item.external_attr = (stat.S_IFDIR | 0o755) << 16
                archive.writestr(item, b"")
            for relative, source, before in entries:
                item = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                executable = bool(before.st_mode & 0o111)
                item.create_system = 3
                item.external_attr = (stat.S_IFREG | (0o755 if executable else 0o644)) << 16
                item.compress_type = zipfile.ZIP_DEFLATED
                digest, size = hashlib.sha256(), 0
                with source.open("rb") as handle, archive.open(item, "w") as target:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        size += len(block)
                        if size > before.st_size:
                            raise WorkspaceError("Project changed during packaging; freeze the source snapshot first.")
                        digest.update(block)
                        target.write(block)
                after = source.stat()
                if size != before.st_size or (after.st_size, after.st_mtime_ns, after.st_ino) != (before.st_size, before.st_mtime_ns, before.st_ino):
                    raise WorkspaceError("Project changed during packaging; freeze the source snapshot first.")
                files.append({"path": relative, "size": size, "sha256": digest.hexdigest(), "executable": executable})
        result = {"operation": "pack", "archive_path": str(output), "archive_sha256": _digest(temporary),
                  "file_count": len(files), "total_bytes": sum(f["size"] for f in files),
                  "archive_bytes": temporary.stat().st_size, "manifest_path": str(manifest_path),
                  "files": files, "directories": folders, "excluded": excluded,
                  "secret_review": "Required: exclusions and PEM checks do not detect every secret."}
        created = False
        try:
            with output.open("xb") as target, temporary.open("rb") as source:
                created = True
                shutil.copyfileobj(source, target)
            _write_manifest(manifest_path, result)
        except Exception:
            if created:
                output.unlink()
            raise
        return {key: value for key, value in result.items() if key != "files"}
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="Extract a ZIP to a new directory without executing it")
    extract.add_argument("--archive", required=True)
    extract.add_argument("--output", required=True)
    pack = commands.add_parser("pack", help="Package the whole reviewed project, with exclusion/hash manifest")
    pack.add_argument("--project", required=True)
    pack.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = extract_archive(args.archive, args.output) if args.command == "extract" else pack_project(args.project, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except WorkspaceError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile, EOFError):
        print("Cannot prepare project archive. Check paths, ZIP integrity and available disk space.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
