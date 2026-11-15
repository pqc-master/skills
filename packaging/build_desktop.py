#!/usr/bin/env python3
"""Build, archive, extract, and smoke-test the standalone desktop and CLI apps."""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
SKILL = REPOSITORY / "skills/discord-channel-reader"
SCRIPTS = SKILL / "scripts"
PINS = {"pyinstaller": "6.22.3", "certifi": "2026.10.23"}
TARGETS = {"macos-arm64": ("darwin", {"arm64", "aarch64"}),
           "windows-x64": ("win32", {"amd64", "x86_64"})}


def run(arguments, *, cwd=None, env=None, timeout=None):
    print("+ " + " ".join(str(value) for value in arguments), flush=True)
    return subprocess.run([str(value) for value in arguments], cwd=cwd, env=env,
                          timeout=timeout, check=True)


def detect_target():
    machine = platform.machine().lower()
    for target, (operating_system, architectures) in TARGETS.items():
        if sys.platform == operating_system and machine in architectures:
            return target
    raise RuntimeError("Build on native macOS arm64 or Windows x64; cross-compilation is unsupported.")


def check_build_environment(target):
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("Use Python 3.13 to build the distributed application.")
    if detect_target() != target:
        raise RuntimeError("The requested target does not match this Python interpreter's OS and architecture.")
    for dependency, expected in PINS.items():
        if metadata.version(dependency) != expected:
            raise RuntimeError("Install the exact versions in packaging/requirements-build.txt.")
    import tkinter
    tkinter.Tcl()  # Fail early if the Python installation lacks its Tcl runtime.
    for filename in ("discord_desktop.py", "discord_cli.py", "discord_submit.py", "desktop_runtime.py"):
        if not (SCRIPTS / filename).is_file():
            raise RuntimeError("Missing desktop source: " + filename)


def stage_skill(destination):
    """Only package skill resources; never copy an installed bin or local settings."""
    destination.mkdir(parents=True)
    shutil.copy2(SKILL / "SKILL.md", destination / "SKILL.md")
    excluded = shutil.ignore_patterns(
        "__pycache__", "*.pyc", "*.pyo", ".env", ".env.*", "publisher.json",
        "*.sqlite", "*.sqlite-*", "messages.jsonl", "transcript.md", "metadata.json",
        "bin", "output", "exports", ".DS_Store",
    )
    for name in ("agents", "assets", "references", "scripts", "tests"):
        source = SKILL / name
        if not source.exists():
            continue
        if any(path.is_symlink() for path in [source, *source.rglob("*")]):
            raise RuntimeError("Skill resources must not contain symlinks to external files.")
        shutil.copytree(source, destination / name, ignore=excluded)


def build_entrypoint(entrypoint, name, *, windowed, workspace, skill_data, target):
    output = workspace / ("gui" if windowed else "cli")
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--noupx", "--name", name, "--distpath", output / "dist",
            "--workpath", output / "work", "--specpath", output / "spec",
            "--paths", SCRIPTS, "--add-data", str(skill_data) + ":skills/discord-channel-reader",
            "--collect-data", "certifi", "--hidden-import", "certifi"]
    # Dynamic dispatch in the CLI and installer must retain these Python modules.
    for module in ("discord_reader", "discord_submit", "discord_publish", "discord_setup", "desktop_runtime"):
        args.extend(["--hidden-import", module])
    if windowed:
        args.append("--windowed")
    else:
        args.append("--console")
    if target == "macos-arm64":
        args.extend(["--target-architecture", "arm64"])
        if windowed:
            args.extend(["--osx-bundle-identifier", "org.pqc-master.discord"])
    args.append(SCRIPTS / entrypoint)
    environment = dict(os.environ)
    environment["PYINSTALLER_CONFIG_DIR"] = str(workspace / "pyinstaller-cache")
    run(args, cwd=REPOSITORY, env=environment)
    return output / "dist" / (name + ".app" if windowed and sys.platform == "darwin" else name)


def executable_paths(package, target):
    if target == "macos-arm64":
        return (package / "pqc-discord/pqc-discord",
                package / "PQC Discord.app/Contents/MacOS/PQC Discord")
    return (package / "pqc-discord/pqc-discord.exe",
            package / "PQC Discord/PQC Discord.exe")


def smoke_test(package, target):
    cli, gui = executable_paths(package, target)
    for executable in (cli, gui):
        if not executable.is_file():
            raise RuntimeError("The archive is missing an expected executable.")
    # No setup command is run. These entry points promise isolated, offline checks.
    environment = dict(os.environ)
    for key in ("DISCORD_BOT_TOKEN", "FIESTA_RELAY_BOT_TOKEN"):
        environment.pop(key, None)
    for arguments in ([cli, "--version"], [cli, "--help"], [cli, "read", "--help"],
                      [cli, "submit", "--help"],
                      [cli, "publish", "--help"], [cli, "setup", "--help"],
                      [cli, "self-test"], [gui, "--smoke-test"]):
        run(arguments, cwd=package, env=environment, timeout=120)


def copy_licenses(package):
    license_dir = package / "licenses"
    license_dir.mkdir()
    shutil.copy2(REPOSITORY / "LICENSE", license_dir / "PQC-Master-MIT.txt")
    python_candidates = [Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
                         Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE"]
    for candidate in python_candidates:
        if candidate.is_file():
            shutil.copy2(candidate, license_dir / "Python-LICENSE.txt")
            break
    else:
        raise RuntimeError("Python's license file is missing from the build interpreter.")
    certifi_distribution = metadata.distribution("certifi")
    for relative in certifi_distribution.files or []:
        if relative.name.upper() in ("LICENSE", "LICENSE.TXT"):
            shutil.copy2(certifi_distribution.locate_file(relative), license_dir / "certifi-LICENSE.txt")
            break
    else:
        raise RuntimeError("certifi's license file is missing from the build environment.")
    notices = (
        "PQC Discord bundles Python, Tcl/Tk, OpenSSL, and certifi.\n"
        "Python license: licenses/Python-LICENSE.txt.\n"
        "certifi: MPL-2.0; licenses/certifi-LICENSE.txt; https://github.com/certifi/python-certifi\n"
        "Tcl/Tk: https://www.tcl-lang.org/software/tcltk/license.html\n"
        "OpenSSL: https://www.openssl.org/source/license.html\n"
        "PyInstaller: https://pyinstaller.org/en/v6.22.3/license.html\n"
        "PyInstaller's bootloader exception permits distribution under the application/dependency licenses.\n"
        "Application source and build instructions: https://github.com/pqc-master/skills\n"
    )
    (package / "THIRD-PARTY-NOTICES.txt").write_text(notices, encoding="utf-8")


def write_manifest(package, target):
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY,
                              text=True, capture_output=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=REPOSITORY,
                               text=True, capture_output=True, check=True).stdout)
    manifest = {"target": target, "python": sys.version, "platform": platform.platform(),
                "source_commit": revision, "source_worktree_dirty": dirty,
                "build_dependencies": {name: metadata.version(name) for name in PINS},
                "dependency_versions": sorted(
                    {dist.metadata["Name"] + "==" + dist.version for dist in metadata.distributions()
                     if dist.metadata.get("Name")}),
                "signing": "ad-hoc; not notarized" if target.startswith("macos") else "unsigned",
                "live_discord_test": "NOT TESTED"}
    (package / "build-info.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def create_archive(package, destination, target):
    if target.startswith("macos"):
        # Native ditto keeps framework symlinks and executable modes in the .app.
        run(["/usr/bin/ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", package, destination])
    else:
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for item in sorted(package.rglob("*")):
                if item.is_file():
                    archive.write(item, item.relative_to(package.parent))


def unpack_archive(archive, destination, target):
    destination.mkdir()
    if target.startswith("macos"):
        run(["/usr/bin/ditto", "-x", "-k", archive, destination])
    else:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(destination)


def build(target, output_dir):
    check_build_environment(target)
    output_dir = output_dir.resolve() / target
    output_dir.mkdir(parents=True, exist_ok=True)
    package_name = "PQC-Discord-" + target
    with tempfile.TemporaryDirectory(prefix=".desktop-build-", dir=output_dir) as temporary:
        workspace = Path(temporary)
        skill_data = workspace / "skill-data/discord-channel-reader"
        stage_skill(skill_data)
        package = workspace / package_name
        package.mkdir()
        gui = build_entrypoint("discord_desktop.py", "PQC Discord", windowed=True,
                               workspace=workspace, skill_data=skill_data, target=target)
        cli = build_entrypoint("discord_cli.py", "pqc-discord", windowed=False,
                               workspace=workspace, skill_data=skill_data, target=target)
        shutil.copytree(gui, package / gui.name, symlinks=True)
        shutil.copytree(cli, package / cli.name, symlinks=True)
        copy_licenses(package)
        write_manifest(package, target)
        smoke_test(package, target)
        archive = workspace / (package_name + ".zip")
        create_archive(package, archive, target)
        unpacked = workspace / "archive-check"
        unpack_archive(archive, unpacked, target)
        smoke_test(unpacked / package_name, target)
        with archive.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        shutil.copy2(package / "build-info.json", output_dir / "build-info.json")
        os.replace(archive, output_dir / archive.name)
        (output_dir / "SHA256SUMS").write_text(digest + "  " + archive.name + "\n", encoding="ascii")
    print("Verified archive: " + str(output_dir / (package_name + ".zip")), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=sorted(TARGETS), help="Defaults to the native build platform")
    parser.add_argument("--output-dir", type=Path, default=REPOSITORY / "output/desktop")
    args = parser.parse_args(argv)
    try:
        build(args.target or detect_target(), args.output_dir)
    except (OSError, RuntimeError, metadata.PackageNotFoundError, subprocess.SubprocessError) as error:
        parser.exit(1, "Desktop build failed: " + str(error) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
