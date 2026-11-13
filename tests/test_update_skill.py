"""Offline release/CLI regression tests; never read real user configuration."""

from __future__ import annotations

from contextlib import contextmanager
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest
from unittest.mock import patch
from urllib.error import URLError
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills/imagegen-api"
SPEC = importlib.util.spec_from_file_location("tested_updater", SOURCE / "scripts/update_skill.py")
UPDATER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPDATER)
REVISION = "a" * 40
REFS_URL = f"https://github.com/{UPDATER.REPOSITORY}.git/info/refs?service=git-upload-pack"
OLD_CONFIG = b'''# Private configuration (test values only)
[api]
base_url = "https://images.example.invalid/v1"
api_key = "fake-regression-key"

[models]
generate = "gpt-image-2.5-flare"
edit = "gpt-image-2.5-sunburst"

[defaults]
quality = "high"
size = "1024x1024"
output_format = "png"
'''


def release():
    manifest = json.loads((SOURCE / "version.json").read_text())
    files = {name: (SOURCE / name).read_bytes() for name in manifest["files"]}
    files["version.json"] = (SOURCE / "version.json").read_bytes()
    return manifest, files


def archive_bytes(files, revision=REVISION):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in files.items():
            archive.writestr(f"imagegen-api-{revision}/skills/imagegen-api/{name}", data)
    return stream.getvalue()


def git_advertisement(revision=REVISION, branch="main"):
    """Git smart HTTP v0 advertisement, including exact hexadecimal packet sizes."""
    def packet(payload):
        return f"{len(payload) + 4:04x}".encode() + payload
    return (
        packet(b"# service=git-upload-pack\n") + b"0000"
        + packet(f"{revision} HEAD\0multi_ack thin-pack side-band side-band-64k ofs-delta symref=HEAD:refs/heads/{branch} agent=git/test\n".encode())
        + packet(f"{'c' * 40} refs/heads/another-branch\n".encode())
        + packet(f"{revision} refs/heads/{branch}\n".encode()) + b"0000"
    )


def snapshot(directory):
    return {str(p.relative_to(directory)): (p.read_bytes(), p.stat().st_mode & 0o777)
            for p in directory.rglob("*") if p.is_file()}


class UpdateSkillTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "work").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="update-regression-", dir=ROOT / "work")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.destination = self.root / "skills/imagegen-api"
        self.manifest, self.files = release()

    @contextmanager
    def remote(self, files=None, failure=None, revision=REVISION, refs=None):
        payload = archive_bytes(self.files if files is None else files, revision)
        def response(request, timeout):
            if failure:
                raise URLError(failure)
            url = request.full_url
            if url == REFS_URL:
                return io.BytesIO(git_advertisement(revision) if refs is None else refs)
            if url == f"https://codeload.github.com/{UPDATER.REPOSITORY}/zip/{revision}":
                return io.BytesIO(payload)
            raise AssertionError(f"Unexpected network request: {url}")
        with patch.object(UPDATER, "urlopen", side_effect=response) as mocked:
            yield mocked

    def legacy_install(self):
        self.destination.mkdir(parents=True)
        (self.destination / "SKILL.md").write_text("old installed skill")
        (self.destination / "scripts").mkdir()
        (self.destination / "scripts/image_gen.py").write_text("# legacy script")
        (self.destination / "config.local.toml").write_bytes(OLD_CONFIG)
        (self.destination / "config.local.toml").chmod(0o600)
        (self.destination / "personal-notes.txt").write_text("preserve personal notes")
        (self.destination / "scripts/user-helper.py").write_text("# preserve user helper")

    def assert_config(self, path):
        before = tomllib.loads(OLD_CONFIG.decode())
        after = tomllib.loads(path.read_text())
        self.assertEqual(after, dict(before, models=self.manifest["models"]))
        self.assertIn(b"# Private configuration (test values only)", path.read_bytes())

    def test_fresh_install_creates_current_release_and_private_config(self):
        with self.remote():
            result = UPDATER.update(self.destination)
        self.assertTrue(result["changed"])
        for name, data in self.files.items():
            self.assertEqual((self.destination / name).read_bytes(), data)
        config = self.destination / "config.local.toml"
        self.assertEqual(tomllib.loads(config.read_text())["models"], self.manifest["models"])
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        self.assertIsNone(result["backup"])

    def test_versionless_legacy_install_updates_models_and_preserves_user_files(self):
        self.legacy_install()
        with self.remote():
            result = UPDATER.update(self.destination)
        self.assert_config(self.destination / "config.local.toml")
        self.assertEqual((self.destination / "personal-notes.txt").read_text(), "preserve personal notes")
        self.assertEqual((self.destination / "scripts/user-helper.py").read_text(), "# preserve user helper")
        self.assertEqual((self.destination / "scripts/image_gen.py").read_bytes(), self.files["scripts/image_gen.py"])
        backup = Path(result["backup"])
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        with zipfile.ZipFile(backup) as archive:
            self.assertEqual(archive.read("config.local.toml"), OLD_CONFIG)
            self.assertEqual(archive.read("SKILL.md"), b"old installed skill")

    def test_repeat_install_is_idempotent_and_uses_verified_local_archive(self):
        self.legacy_install()
        with self.remote():
            UPDATER.update(self.destination)
        before = snapshot(self.destination)
        with self.remote() as network:
            result = UPDATER.update(self.destination)
        self.assertFalse(result["changed"])
        self.assertIsNone(result["backup"])
        self.assertEqual(snapshot(self.destination), before)
        self.assertEqual(network.call_count, 1)

    def test_changed_managed_file_is_repaired_on_repeat_install(self):
        with self.remote():
            UPDATER.update(self.destination)
        (self.destination / "SKILL.md").write_text("corrupt managed file")
        with self.remote() as network:
            result = UPDATER.update(self.destination)
        self.assertTrue(result["changed"])
        self.assertEqual(network.call_count, 2)
        self.assertEqual((self.destination / "SKILL.md").read_bytes(), self.files["SKILL.md"])

    def test_explicit_external_config_is_migrated_alongside_local_config(self):
        self.legacy_install()
        external = self.root / "selected-config.toml"
        external.write_bytes(OLD_CONFIG)
        with self.remote():
            UPDATER.update(self.destination, external)
        self.assert_config(external)
        self.assert_config(self.destination / "config.local.toml")

    def test_config_migration_retains_crlf_and_adds_missing_models(self):
        crlf = OLD_CONFIG.replace(b"\n", b"\r\n")
        migrated = UPDATER.migrate_config(crlf, self.manifest["models"])
        self.assertNotIn(b"\n", migrated.replace(b"\r\n", b""))
        before = tomllib.loads(OLD_CONFIG.decode())
        self.assertEqual(tomllib.loads(migrated.decode()), dict(before, models=self.manifest["models"]))
        no_models = b'[api]\nbase_url = "https://example.invalid"\napi_key = "fake"\n'
        result = UPDATER.migrate_config(no_models, self.manifest["models"])
        self.assertEqual(tomllib.loads(result.decode())["api"], tomllib.loads(no_models.decode())["api"])
        self.assertEqual(tomllib.loads(result.decode())["models"], self.manifest["models"])

    def test_network_failure_does_not_change_existing_files(self):
        self.legacy_install()
        before = snapshot(self.destination)
        with self.remote(failure="offline"), self.assertRaises(UPDATER.UpdateError):
            UPDATER.update(self.destination)
        self.assertEqual(snapshot(self.destination), before)

    def test_invalid_git_advertisement_does_not_change_existing_files(self):
        self.legacy_install()
        before = snapshot(self.destination)
        responses = {
            "not-git": b"<html>upstream error</html>",
            "missing-main": git_advertisement(branch="other"),
            "invalid-sha": git_advertisement(revision="z" * 40),
            "missing-packet-framing": f"{REVISION} refs/heads/main\n".encode(),
            "invalid-packet-length": git_advertisement().replace(b"001e# service=git-upload-pack", b"0005# service=git-upload-pack"),
            "truncated-packet": git_advertisement()[:-8],
            "missing-final-flush": git_advertisement()[:-4],
            "html-with-reference": b"<html>" + f"{REVISION} refs/heads/main\n".encode() + b"</html>",
        }
        for name, response in responses.items():
            with self.subTest(response=name):
                with self.remote(refs=response) as network, self.assertRaises(UPDATER.UpdateError):
                    UPDATER.update(self.destination)
                self.assertEqual(network.call_count, 1)
                self.assertEqual(snapshot(self.destination), before)

    def test_incomplete_archive_does_not_change_existing_files(self):
        self.legacy_install()
        before = snapshot(self.destination)
        broken = dict(self.files)
        del broken["scripts/image_gen.py"]
        with self.remote(files=broken), self.assertRaises(UPDATER.UpdateError):
            UPDATER.update(self.destination)
        self.assertEqual(snapshot(self.destination), before)

    def test_invalid_local_config_aborts_before_changing_release_files(self):
        self.legacy_install()
        (self.destination / "config.local.toml").write_text("not valid TOML")
        before = snapshot(self.destination)
        with self.remote(), self.assertRaises(UPDATER.UpdateError):
            UPDATER.update(self.destination)
        self.assertEqual(snapshot(self.destination), before)

    def test_write_failure_rolls_back_all_prior_writes(self):
        self.legacy_install()
        before = snapshot(self.destination)
        real_write = UPDATER._atomic_write
        calls = 0
        def fail_once(path, content, mode):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise OSError("simulated disk write failure")
            real_write(path, content, mode)
        with self.remote(), patch.object(UPDATER, "_atomic_write", side_effect=fail_once):
            with self.assertRaises(UPDATER.UpdateError):
                UPDATER.update(self.destination)
        self.assertEqual(snapshot(self.destination), before)
        self.assertFalse((self.destination.parent / ".imagegen-api.update.lock").exists())

    def test_downgrade_is_rejected_without_changes(self):
        with self.remote():
            UPDATER.update(self.destination)
        current = copy.deepcopy(self.manifest)
        current["version"] = "999.0.0"
        (self.destination / "version.json").write_text(json.dumps(current))
        before = snapshot(self.destination)
        with self.remote(), self.assertRaises(UPDATER.UpdateError):
            UPDATER.update(self.destination)
        self.assertEqual(snapshot(self.destination), before)

    def cli_environment(self, fail=False, files=None, revision=REVISION, refs=None):
        """sitecustomize survives execv; sockets are blocked even if mocks regress."""
        support = self.root / "fake-modules"
        support.mkdir(exist_ok=True)
        fixture = self.root / "release.zip"
        fixture.write_bytes(archive_bytes(self.files if files is None else files, revision))
        refs_fixture = self.root / "git-refs.bin"
        refs_fixture.write_bytes(git_advertisement(revision) if refs is None else refs)
        event_file = self.root / "events.jsonl"
        (support / "sitecustomize.py").write_text(textwrap.dedent('''
            import base64, io, json, os, socket, sys, types, urllib.request
            from pathlib import Path
            from urllib.error import URLError
            def event(value):
                with open(os.environ["REGRESSION_EVENTS"], "a") as stream:
                    stream.write(json.dumps(value) + "\\n")
            def blocked(*args, **kwargs):
                raise AssertionError("Real network is disabled in regression tests")
            socket.socket.connect = blocked
            socket.create_connection = blocked
            def urlopen(request, timeout):
                earlier = Path(os.environ["REGRESSION_EVENTS"])
                update_count = sum(json.loads(line)["kind"] == "update" for line in earlier.read_text().splitlines()) if earlier.exists() else 0
                event({"kind": "update", "url": request.full_url})
                if os.environ.get("REGRESSION_OFFLINE") == "1" or update_count >= int(os.environ.get("REGRESSION_FAIL_AFTER", "999")):
                    raise URLError("simulated offline")
                if request.full_url == os.environ["REGRESSION_REFS_URL"]:
                    return io.BytesIO(Path(os.environ["REGRESSION_REFS"]).read_bytes())
                if request.full_url.endswith("/zip/" + os.environ["REGRESSION_REVISION"]):
                    return io.BytesIO(Path(os.environ["REGRESSION_ARCHIVE"]).read_bytes())
                raise AssertionError("Unexpected URL: " + request.full_url)
            urllib.request.urlopen = urlopen
            def result(operation, kwargs):
                event({"kind": "image", "operation": operation,
                       "model": kwargs["model"], "quality": kwargs["quality"], "size": kwargs["size"],
                       "output_format": kwargs["output_format"]})
                return types.SimpleNamespace(data=[types.SimpleNamespace(
                    b64_json=base64.b64encode(b"offline mock image").decode(), url=None)])
            class Images:
                def generate(self, **kwargs): return result("generate", kwargs)
                def edit(self, **kwargs): return result("edit", kwargs)
            class AsyncImages:
                async def generate(self, **kwargs): return result("generate-batch", kwargs)
            class OpenAI:
                def __init__(self, **kwargs):
                    assert kwargs["base_url"] == "https://images.example.invalid/v1"
                    assert kwargs["api_key"] == "fake-regression-key"
                    self.images = Images()
            class AsyncOpenAI(OpenAI):
                def __init__(self, **kwargs):
                    super().__init__(**kwargs)
                    self.images = AsyncImages()
            sys.modules["openai"] = types.SimpleNamespace(OpenAI=OpenAI, AsyncOpenAI=AsyncOpenAI)
        '''))
        env = dict(os.environ, PYTHONPATH=str(support), PYTHONDONTWRITEBYTECODE="1",
                   REGRESSION_ARCHIVE=str(fixture), REGRESSION_EVENTS=str(event_file),
                   REGRESSION_REVISION=revision,
                   REGRESSION_REFS=str(refs_fixture), REGRESSION_REFS_URL=REFS_URL,
                   REGRESSION_OFFLINE="1" if fail else "0")
        return env, event_file

    def cli(self, command, fail=False, flags=(), fail_after=None, files=None, revision=REVISION, refs=None):
        env, event_file = self.cli_environment(fail, files, revision, refs)
        if fail_after is not None:
            env["REGRESSION_FAIL_AFTER"] = str(fail_after)
        output = self.root / f"result-{command}.png"
        args = [sys.executable, str(self.destination / "scripts/image_gen.py"), command]
        if command == "generate-batch":
            jobs = self.root / "jobs.jsonl"
            jobs.write_text('{"prompt": "test prompt"}\n')
            args += ["--input", str(jobs), "--out-dir", str(self.root / "batch")]
        elif command != "check-config":
            args += ["--prompt", "test prompt", "--out", str(output)]
            if command == "edit":
                reference = self.root / "reference.png"
                reference.write_bytes(b"offline mock input")
                args += ["--image", str(reference)]
        process = subprocess.run(args + list(flags), cwd=self.root, env=env,
                                 capture_output=True, text=True, timeout=30)
        events = [json.loads(line) for line in event_file.read_text().splitlines()] if event_file.exists() else []
        return process, events

    def copy_current_with_old_config(self):
        shutil.copytree(SOURCE, self.destination, ignore=shutil.ignore_patterns("config.local.toml", "__pycache__"))
        (self.destination / "config.local.toml").write_bytes(OLD_CONFIG)

    def test_actual_cli_updates_and_reexecutes_before_generate_edit_and_batch(self):
        for command, model_key in [("generate", "generate"), ("edit", "edit"), ("generate-batch", "generate")]:
            with self.subTest(command=command):
                if self.destination.exists():
                    shutil.rmtree(self.destination)
                event_file = self.root / "events.jsonl"
                event_file.unlink(missing_ok=True)
                self.copy_current_with_old_config()
                older_manifest = copy.deepcopy(self.manifest)
                older_manifest["version"] = "1.0.0"
                older_manifest["models"] = tomllib.loads(OLD_CONFIG.decode())["models"]
                (self.destination / "version.json").write_text(json.dumps(older_manifest))
                process, events = self.cli(command)
                self.assertEqual(process.returncode, 0, process.stderr)
                images = [entry for entry in events if entry["kind"] == "image"]
                self.assertEqual(len(images), 1, events)
                self.assertEqual(images[0]["model"], self.manifest["models"][model_key])
                self.assertEqual(images[0]["quality"], "high")
                self.assertEqual(images[0]["size"], "1024x1024")
                self.assertEqual(events[-1]["kind"], "image")
                self.assertGreaterEqual(len([event for event in events if event["kind"] == "update"]), 3)
                self.assertIn("reloading", process.stderr)
                self.assert_config(self.destination / "config.local.toml")

    def test_actual_cli_update_failure_never_calls_image_endpoint(self):
        self.copy_current_with_old_config()
        before = snapshot(self.destination)
        for command in ("generate", "edit", "generate-batch"):
            with self.subTest(command=command):
                process, events = self.cli(command, fail=True)
                self.assertNotEqual(process.returncode, 0)
                self.assertIn("simulated offline", process.stderr)
                self.assertFalse(any(entry["kind"] == "image" for entry in events))
                self.assertEqual(snapshot(self.destination), before)

    def test_actual_cli_invalid_git_advertisement_never_calls_image_endpoint(self):
        self.copy_current_with_old_config()
        before = snapshot(self.destination)
        for invalid_refs in (git_advertisement(branch="other"), b"<html>upstream error</html>", git_advertisement()[:-8]):
            for command in ("generate", "edit", "generate-batch"):
                with self.subTest(command=command, refs=invalid_refs[:20]):
                    (self.root / "events.jsonl").unlink(missing_ok=True)
                    process, events = self.cli(command, refs=invalid_refs)
                    self.assertNotEqual(process.returncode, 0)
                    self.assertEqual(events, [{"kind": "update", "url": REFS_URL}])
                    self.assertEqual(snapshot(self.destination), before)

    def test_update_check_failure_after_reexec_still_blocks_image_request(self):
        self.copy_current_with_old_config()
        process, events = self.cli("generate", fail_after=2)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("reloading", process.stderr)
        self.assertIn("simulated offline", process.stderr)
        self.assertEqual(len(events), 3)
        self.assertTrue(all(event["kind"] == "update" for event in events))
        self.assert_config(self.destination / "config.local.toml")

    def test_explicit_legacy_model_and_removed_fidelity_option_never_request_images(self):
        self.copy_current_with_old_config()
        for flags in [("--model", "gpt-image-2.5-flare"), ("--input-fidelity", "high")]:
            with self.subTest(flags=flags):
                process, events = self.cli("edit", flags=flags)
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse(any(event["kind"] == "image" for event in events))

    def test_check_config_and_dry_run_do_not_use_network_or_update(self):
        self.copy_current_with_old_config()
        (self.destination / "config.local.toml").write_bytes(
            UPDATER.migrate_config(OLD_CONFIG, self.manifest["models"]))
        before = snapshot(self.destination)
        for command, flags in [("check-config", ()), ("generate", ("--dry-run",))]:
            with self.subTest(command=command):
                process, events = self.cli(command, fail=True, flags=flags)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(events, [])
                self.assertEqual(snapshot(self.destination), before)

    def test_install_command_handles_fresh_legacy_and_repeated_install(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                if self.destination.exists():
                    shutil.rmtree(self.destination)
                if legacy:
                    self.legacy_install()
                env, _ = self.cli_environment()
                args = [sys.executable, str(SOURCE / "scripts/update_skill.py"),
                        "install", "--dest", str(self.destination)]
                process = subprocess.run(args, cwd=self.root, env=env,
                                         capture_output=True, text=True, timeout=30)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertTrue(json.loads(process.stdout)["changed"])
                if legacy:
                    self.assert_config(self.destination / "config.local.toml")
                before = snapshot(self.destination)
                process = subprocess.run(args, cwd=self.root, env=env,
                                         capture_output=True, text=True, timeout=30)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertFalse(json.loads(process.stdout)["changed"])
                self.assertEqual(snapshot(self.destination), before)

    def test_future_release_reloads_changed_code_and_models_then_remains_idempotent(self):
        """Two actual releases, different SHAs, and observable new Python code."""
        initial_version = self.manifest["version"]
        next_revision = "b" * 40
        next_manifest = copy.deepcopy(self.manifest)
        next_manifest.update(version="1.2.0", models={
            "generate": "gpt-image-test-next-flare",
            "edit": "gpt-image-test-next-sunburst",
        })
        next_files = dict(self.files)
        next_files["version.json"] = json.dumps(next_manifest).encode()
        next_files["config.example.toml"] = UPDATER.migrate_config(
            next_files["config.example.toml"], next_manifest["models"])
        marker = "REGRESSION: running simulated release 1.2.0 code"
        anchor = b"    global ACTIVE_CONFIG\n"
        self.assertEqual(next_files["scripts/image_gen.py"].count(anchor), 1)
        next_files["scripts/image_gen.py"] = next_files["scripts/image_gen.py"].replace(
            anchor, anchor + f"    print({marker!r}, file=sys.stderr)\n".encode())
        backup_directory = self.destination.parent / ".imagegen-api-backups"
        event_file = self.root / "events.jsonl"

        for command, model_key in [("generate", "generate"), ("edit", "edit"), ("generate-batch", "generate")]:
            with self.subTest(command=command):
                if self.destination.exists():
                    shutil.rmtree(self.destination)
                event_file.unlink(missing_ok=True)
                env, _ = self.cli_environment()
                installed = subprocess.run(
                    [sys.executable, str(SOURCE / "scripts/update_skill.py"),
                     "install", "--dest", str(self.destination)],
                    cwd=self.root, env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(installed.returncode, 0, installed.stderr)
                self.assertEqual(json.loads(installed.stdout)["version"], initial_version)
                self.assertEqual(json.loads((self.destination / UPDATER.STATE_FILE).read_text())["revision"], REVISION)
                config_path = self.destination / "config.local.toml"
                initial_config = UPDATER.migrate_config(OLD_CONFIG, self.manifest["models"])
                config_path.write_bytes(initial_config)
                before_config = tomllib.loads(initial_config.decode())
                before_backups = set(backup_directory.glob("*.zip"))
                event_file.unlink()

                process, events = self.cli(command, files=next_files, revision=next_revision)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(process.stderr.count(marker), 1, process.stderr)
                self.assertIn("Updated imagegen-api to 1.2.0; reloading", process.stderr)
                updates = [event["url"] for event in events if event["kind"] == "update"]
                self.assertEqual(updates, [
                    REFS_URL,
                    f"https://codeload.github.com/{UPDATER.REPOSITORY}/zip/{next_revision}",
                    REFS_URL,
                ])
                images = [event for event in events if event["kind"] == "image"]
                self.assertEqual(images, [{
                    "kind": "image", "operation": command,
                    "model": next_manifest["models"][model_key],
                    "quality": "high", "size": "1024x1024", "output_format": "png",
                }])
                self.assertEqual(events[-1]["kind"], "image")
                self.assertEqual(tomllib.loads(config_path.read_text()),
                                 dict(before_config, models=next_manifest["models"]))
                self.assertEqual((self.destination / "scripts/image_gen.py").read_bytes(),
                                 next_files["scripts/image_gen.py"])
                state = json.loads((self.destination / UPDATER.STATE_FILE).read_text())
                self.assertEqual((state["version"], state["revision"]), ("1.2.0", next_revision))
                new_backups = set(backup_directory.glob("*.zip")) - before_backups
                self.assertEqual(len(new_backups), 1)
                with zipfile.ZipFile(next(iter(new_backups))) as archive:
                    self.assertEqual(archive.read("config.local.toml"), initial_config)
                    self.assertEqual(archive.read("scripts/image_gen.py"), self.files["scripts/image_gen.py"])

                after_snapshot = snapshot(self.destination)
                after_times = {str(path.relative_to(self.destination)): path.stat().st_mtime_ns
                               for path in self.destination.rglob("*") if path.is_file()}
                after_backups = snapshot(backup_directory)
                event_file.unlink()
                repeated, events = self.cli(command, flags=("--force",), files=next_files, revision=next_revision)
                self.assertEqual(repeated.returncode, 0, repeated.stderr)
                self.assertEqual(repeated.stderr.count(marker), 1, repeated.stderr)
                self.assertNotIn("reloading", repeated.stderr)
                self.assertEqual([event for event in events if event["kind"] == "update"], [{
                    "kind": "update", "url": REFS_URL,
                }])
                self.assertEqual([event for event in events if event["kind"] == "image"], images)
                self.assertEqual(snapshot(self.destination), after_snapshot)
                self.assertEqual({str(path.relative_to(self.destination)): path.stat().st_mtime_ns
                                  for path in self.destination.rglob("*") if path.is_file()}, after_times)
                self.assertEqual(snapshot(backup_directory), after_backups)


if __name__ == "__main__":
    unittest.main()
