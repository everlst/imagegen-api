#!/usr/bin/env python3
"""Install/update ImageGen API and migrate model settings. Python 3.11+, stdlib only."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import tomllib
from urllib.error import URLError
from urllib.request import Request, urlopen
import uuid
import zipfile

REPOSITORY = "everlst/imagegen-api"
SKILL_PATH = "skills/imagegen-api"
STATE_FILE = ".update-state.json"
MAX_DOWNLOAD = 32 * 1024 * 1024


class UpdateError(Exception):
    pass


def _version(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise UpdateError("Invalid skill version; expected major.minor.patch.")
    return tuple(map(int, value.split(".")))


def validate_manifest(value: dict) -> dict:
    if value.get("schema") != 1 or value.get("name") != "imagegen-api":
        raise UpdateError("Unsupported imagegen-api release manifest.")
    _version(value.get("version"))
    models = value.get("models", {})
    if set(models) != {"generate", "edit"} or any(
        not isinstance(model, str) or not re.fullmatch(r"gpt-image-[\w.\-]+", model)
        for model in models.values()
    ):
        raise UpdateError("Release manifest must specify the current generation and edit models.")
    files = value.get("files")
    if not isinstance(files, list) or len(files) != len(set(files)):
        raise UpdateError("Invalid managed file list.")
    required = {"SKILL.md", "config.example.toml", "scripts/image_gen.py", "scripts/update_skill.py"}
    if not required.issubset(files):
        raise UpdateError("Release is missing required skill files.")
    for name in files:
        path = PurePosixPath(name)
        if (
            path.is_absolute() or ".." in path.parts or "\\" in name
            or str(path) != name or name in {STATE_FILE, "config.local.toml", "version.json"}
            or not (name in {".gitignore", "SKILL.md", "config.example.toml", "requirements.txt"}
                    or path.parts[0] in {"scripts", "references", "agents", "assets"})
        ):
            raise UpdateError("Release contains an invalid managed file path.")
    return value


def _read_manifest(path: Path) -> dict:
    try:
        return validate_manifest(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        raise UpdateError(f"Cannot read release manifest at {path}.") from exc


def _download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "imagegen-api-updater", "Accept": "application/vnd.github+json"})
    try:
        with urlopen(request, timeout=15) as response:
            payload = response.read(MAX_DOWNLOAD + 1)
    except (URLError, OSError) as exc:
        raise UpdateError(f"Cannot check/download {REPOSITORY}: {exc}. No image request was sent.") from exc
    if len(payload) > MAX_DOWNLOAD:
        raise UpdateError("Update download exceeds the size limit.")
    return payload


def latest_revision() -> str:
    try:
        revision = json.loads(_download(f"https://api.github.com/repos/{REPOSITORY}/commits/main"))["sha"]
    except (ValueError, TypeError, KeyError) as exc:
        raise UpdateError("GitHub returned an invalid revision.") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise UpdateError("GitHub returned an invalid commit SHA.")
    return revision


def download_release(revision: str) -> tuple[dict, dict[str, bytes]]:
    payload = _download(f"https://codeload.github.com/{REPOSITORY}/zip/{revision}")
    prefix = f"imagegen-api-{revision}/{SKILL_PATH}/"
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            def read_file(name: str) -> bytes:
                info = archive.getinfo(prefix + name)
                if stat.S_ISLNK(info.external_attr >> 16) or info.file_size > MAX_DOWNLOAD:
                    raise UpdateError("Release contains an invalid file.")
                return archive.read(info)

            manifest_bytes = read_file("version.json")
            manifest = validate_manifest(json.loads(manifest_bytes))
            files = {name: read_file(name) for name in manifest["files"]}
            files["version.json"] = manifest_bytes
            if sum(map(len, files.values())) > MAX_DOWNLOAD:
                raise UpdateError("Unpacked release exceeds the size limit.")
            return manifest, files
    except (zipfile.BadZipFile, KeyError, ValueError, TypeError, AttributeError) as exc:
        raise UpdateError("Downloaded release is incomplete or invalid; installed files were not changed.") from exc


def migrate_config(original: bytes, models: dict[str, str]) -> bytes:
    """Change only the models table, retaining credentials, defaults and other text."""
    try:
        text = original.decode("utf-8")
        before = tomllib.loads(text)
        previous = before.get("models", {})
        if not isinstance(previous, dict):
            raise ValueError()
        if all(previous.get(key) == value for key, value in models.items()):
            return original
        updated = dict(previous, **models)
        if any(not isinstance(value, str) for value in updated.values()):
            raise ValueError()
        newline = "\r\n" if "\r\n" in text else "\n"
        table = "[models]" + newline + newline.join(
            f"{json.dumps(key)} = {json.dumps(value, ensure_ascii=False)}" for key, value in updated.items()
        ) + newline + newline
        header = re.search(r"(?m)^[ \t]*\[models\][ \t]*(?:#[^\r\n]*)?\r?$", text)
        if header:
            next_header = re.search(r"(?m)^[ \t]*\[", text[header.end():])
            end = header.end() + next_header.start() if next_header else len(text)
            candidate = text[:header.start()] + table + text[end:]
        elif "models" not in before:
            candidate = text.rstrip("\r\n") + newline + newline + table
        else:
            raise ValueError()
        expected = dict(before, models=updated)
        if tomllib.loads(candidate) != expected:
            raise ValueError()
        return candidate.encode("utf-8")
    except (UnicodeError, ValueError, TypeError) as exc:
        raise UpdateError("Cannot safely migrate config.local.toml; use a standard [models] table. Original configuration retained.") from exc


def _atomic_write(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".imagegen-update-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _lock(destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.parent / f".{destination.name}.update.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise UpdateError(f"An update lock exists: {lock}. Wait for the other updater; remove it only if that process has stopped.") from exc
    os.close(fd)
    try:
        yield
    finally:
        lock.unlink()


def _managed_path(destination: Path, name: str) -> Path:
    path = destination / name
    for component in [path, *path.parents]:
        if component == destination:
            break
        if component.is_symlink():
            raise UpdateError(f"Managed path is a symlink: {path}. No update applied.")
    return path


def apply_release(destination: Path, manifest: dict, files: dict[str, bytes], revision: str,
                  config_path: Path | None = None) -> dict:
    """Caller holds the update lock. Back up before writes and roll back a failed apply."""
    if (destination / "version.json").exists():
        installed = _read_manifest(destination / "version.json")
        if _version(manifest["version"]) < _version(installed["version"]):
            raise UpdateError("Remote release is older than the installed version; refusing a downgrade.")
    planned = {_managed_path(destination, name): data for name, data in files.items()}
    configs = {destination / "config.local.toml"}
    if config_path:
        configs.add(config_path.expanduser().resolve())
    for path in configs:
        if path.is_symlink():
            raise UpdateError(f"Configuration is a symlink: {path}. Specify its resolved path explicitly.")
        original = path.read_bytes() if path.exists() else files["config.example.toml"]
        planned[path] = migrate_config(original, manifest["models"])
    state_path = _managed_path(destination, STATE_FILE)
    state = {"version": manifest["version"], "revision": revision,
             "hashes": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    planned[state_path] = (json.dumps(state, indent=2, sort_keys=True) + "\n").encode()
    changes = {path: data for path, data in planned.items() if not path.exists() or path.read_bytes() != data}
    previous = {path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) if path.exists() else None for path in changes}
    backup = None
    if any(value is not None for value in previous.values()):
        folder = destination.parent / f".{destination.name}-backups"
        folder.mkdir(mode=0o700, exist_ok=True)
        backup = folder / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.zip"
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream, zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, value in previous.items():
                if value is not None:
                    label = str(path.relative_to(destination)) if path.is_relative_to(destination) else "external-config.toml"
                    archive.writestr(label, value[0])
    written = []
    try:
        for path, data in changes.items():
            mode = previous[path][1] if previous[path] else (0o600 if path in configs or path == state_path else 0o644)
            _atomic_write(path, data, mode)
            written.append(path)
    except OSError as exc:
        for path in reversed(written):
            if previous[path] is None:
                path.unlink()
            else:
                _atomic_write(path, *previous[path])
        raise UpdateError(f"Update failed and prior files were restored. Backup: {backup}") from exc
    return {"version": manifest["version"], "models": manifest["models"], "revision": revision,
            "destination": str(destination), "changed": any(path != state_path for path in changes),
            "backup": str(backup) if backup else None, "automatic_updates": True}


def update(destination: Path, config_path: Path | None = None) -> dict:
    destination = destination.expanduser().resolve()
    with _lock(destination):
        revision = latest_revision()
        files = None
        try:
            state = json.loads((destination / STATE_FILE).read_text(encoding="utf-8"))
            manifest = _read_manifest(destination / "version.json")
            names = [*manifest["files"], "version.json"]
            if state["revision"] == revision and set(state["hashes"]) == set(names):
                candidate = {name: _managed_path(destination, name).read_bytes() for name in names}
                if all(hashlib.sha256(data).hexdigest() == state["hashes"][name] for name, data in candidate.items()):
                    files = candidate
        except (OSError, ValueError, KeyError, TypeError, UpdateError):
            pass
        if files is None:
            manifest, files = download_release(revision)
        return apply_release(destination, manifest, files, revision, config_path)


def install_destination() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    candidates = [codex_home / "skills/imagegen-api", Path.home() / ".agents/skills/imagegen-api"]
    existing = list(dict.fromkeys(path.resolve() for path in candidates if path.exists()))
    if len(existing) > 1:
        raise UpdateError("Multiple installations found; choose the active skill with --dest: " + ", ".join(map(str, existing)))
    return existing[0] if existing else candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["install", "update"])
    parser.add_argument("--dest", type=Path, help="Exact skill directory (existing installations are updated in place)")
    parser.add_argument("--config", type=Path, help="Also migrate a separately selected configuration")
    args = parser.parse_args()
    destination = args.dest or (install_destination() if args.command == "install" else Path(__file__).resolve().parents[1])
    if args.command == "update" and not (destination / "SKILL.md").exists():
        raise UpdateError("Cannot locate the installed skill. Use install or pass --dest.")
    result = update(destination, args.config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (UpdateError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
