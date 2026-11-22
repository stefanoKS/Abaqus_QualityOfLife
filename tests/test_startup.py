"""Startup identity, instance reuse and Abaqus launcher discovery.

These tests are license-free: discovery only inspects paths, and the instance
compatibility check works on recorded health payloads.
"""

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from integrations.abaqus import launcher
from integrations import dwg
from services import store

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("serve", ROOT / "scripts" / "serve.py")
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


@pytest.fixture()
def clean_env(monkeypatch):
    for name in (launcher.ENV_LAUNCHER, launcher.ENV_LAUNCHER_ALIAS, "SEAL_DATA"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def launcher_file(directory, name="abq2024.bat"):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("@echo off\n", encoding="utf-8")
    return path


def test_explicit_override_wins(clean_env, tmp_path):
    path = launcher_file(tmp_path / "custom", "abq2024.bat")
    clean_env.setenv(launcher.ENV_LAUNCHER, str(path))
    resolved = launcher.resolve_launcher()
    assert resolved["path"] == str(path.resolve())
    assert resolved["source"].startswith("override")
    assert "validated" in resolved["detail"]


def test_alias_override_is_honoured(clean_env, tmp_path):
    path = launcher_file(tmp_path / "alias")
    clean_env.setenv(launcher.ENV_LAUNCHER_ALIAS, str(path))
    resolved = launcher.resolve_launcher()
    assert resolved["path"] == str(path.resolve())
    assert launcher.ENV_LAUNCHER_ALIAS in resolved["source"]


def test_invalid_override_names_the_path_and_the_reason(clean_env, tmp_path):
    missing = tmp_path / "nope" / "abq2024.bat"
    clean_env.setenv(launcher.ENV_LAUNCHER, str(missing))
    with pytest.raises(ValueError) as error:
        launcher.resolve_launcher()
    message = str(error.value)
    assert str(missing) in message
    assert "not a usable launcher" in message
    assert launcher.ENV_LAUNCHER in message
    assert "automatically" in message


def test_versioned_launcher_is_preferred_on_path(clean_env, monkeypatch, tmp_path):
    versioned = launcher_file(tmp_path / "bin", "abq2024.bat")
    generic = launcher_file(tmp_path / "bin", "abaqus.bat")
    monkeypatch.setattr(
        launcher.shutil,
        "which",
        lambda name: str(versioned) if name == "abq2024" else str(generic),
    )
    resolved = launcher.resolve_launcher()
    assert resolved["path"] == str(versioned.resolve())
    assert "abq2024" in resolved["source"]


def test_generic_launcher_is_used_when_versioned_is_absent(clean_env, monkeypatch, tmp_path):
    generic = launcher_file(tmp_path / "bin", "abaqus.bat")
    monkeypatch.setattr(
        launcher.shutil, "which", lambda name: str(generic) if name == "abaqus" else None
    )
    monkeypatch.setattr(launcher, "DISCOVERY_DIRS", ())
    resolved = launcher.resolve_launcher()
    assert resolved["path"] == str(generic.resolve())
    assert "abaqus" in resolved["source"]


def test_standard_installation_directory_is_found_without_a_variable(clean_env, monkeypatch, tmp_path):
    installed = launcher_file(tmp_path / "SIMULIA" / "Commands", "abq2024.bat")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    monkeypatch.setattr(launcher, "DISCOVERY_DIRS", (installed.parent,))
    resolved = launcher.resolve_launcher()
    assert resolved["path"] == str(installed.resolve())
    assert resolved["source"].startswith("known location")


def test_multiple_versions_pick_the_supported_one(clean_env, monkeypatch, tmp_path):
    directory = tmp_path / "SIMULIA" / "Commands"
    launcher_file(directory, "abq2022.bat")
    supported = launcher_file(directory, "abq2024.bat")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    monkeypatch.setattr(launcher, "DISCOVERY_DIRS", (directory,))
    assert launcher.resolve_launcher()["path"] == str(supported.resolve())


def test_missing_installation_explains_what_was_searched(clean_env, monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    monkeypatch.setattr(launcher, "DISCOVERY_DIRS", (tmp_path / "absent",))
    with pytest.raises(ValueError) as error:
        launcher.resolve_launcher()
    message = str(error.value)
    assert "No Abaqus launcher found" in message
    assert "abq2024" in message and "abaqus" in message
    assert launcher.ENV_LAUNCHER in message


def test_executable_inside_the_job_data_is_never_selected(clean_env, monkeypatch, tmp_path):
    data = tmp_path / "data"
    uploaded = launcher_file(data / "drawings", "abq2024.bat")
    clean_env.setenv("SEAL_DATA", str(data))
    monkeypatch.setattr(launcher.shutil, "which", lambda name: str(uploaded))
    monkeypatch.setattr(launcher, "DISCOVERY_DIRS", ())
    with pytest.raises(ValueError, match="No Abaqus launcher found"):
        launcher.resolve_launcher()


def test_native_reader_readiness_names_the_missing_component(monkeypatch, tmp_path):
    ready = dwg.status()
    assert ready["ready"] is True
    assert ready["message"] == "Native DWG reader ready"
    library = dwg.HELPER.parent / "ACadSharp.dll"
    monkeypatch.setattr(dwg, "HELPER", tmp_path / "dwg-inventory.exe")
    broken = dwg.status()
    assert broken["ready"] is False
    assert "dwg-inventory.exe" in broken["missing"]
    assert "ACadSharp.dll" in broken["missing"]
    assert "Restore the files" in broken["message"]
    assert library.exists()  # the real packaged library is present


def test_instance_compatibility_distinguishes_releases(monkeypatch):
    current = {"product": "Abaqus QOL", "build": "abc123", "api": 3, "data": "d1"}
    monkeypatch.setattr(
        serve,
        "local_identity",
        lambda: {"build": "abc123", "frontend": "x.js", "api": 3, "data": "d1"},
    )
    assert serve.compatibility(current) == "current"
    assert serve.compatibility({"product": "Abaqus QOL", "pid": 1}) == "legacy"
    assert (
        serve.compatibility({"product": "Abaqus QOL", "build": "abc123", "api": 2, "data": "d1"})
        == "different-api"
    )
    assert (
        serve.compatibility({"product": "Abaqus QOL", "build": "abc123", "api": 3, "data": "d2"})
        == "different-data"
    )
    assert (
        serve.compatibility({"product": "Abaqus QOL", "build": "old", "api": 3, "data": "d1"})
        == "different-build"
    )
    assert serve.compatibility(None) == "not-ours"


def test_custom_port_has_its_own_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(serve, "lock_path", lambda port: tmp_path / f"serve-{port}.lock")
    monkeypatch.setattr(serve, "health", lambda port, timeout=1.0: None)
    assert serve.acquire_lock(8897) is True
    record = json.loads((tmp_path / "serve-8897.lock").read_text(encoding="utf-8"))
    assert record["port"] == 8897
    assert not (tmp_path / "serve-8765.lock").exists()


def test_stale_instance_is_not_reused_and_explains_why(monkeypatch, capsys):
    legacy = {"product": "Abaqus QOL", "status": "ready", "version": "0.2.0", "pid": 10468}
    monkeypatch.setattr(serve, "health", lambda port, timeout=1.0: legacy)
    monkeypatch.setattr(serve, "active_jobs", lambda port: [])
    monkeypatch.setattr(serve, "ensure_dependencies", lambda: None)
    monkeypatch.setattr(serve, "ensure_web", lambda rebuild=False: None)
    monkeypatch.setattr(serve, "local_identity", lambda: {"build": "abc123", "frontend": "x.js"})
    code = serve.main(["--port", "8765", "--no-browser"])
    output = capsys.readouterr().out
    assert code == 3
    assert "different instance" in output
    assert "older release" in output
    assert "Nothing was stopped" in output
    assert "--takeover" in output


def test_takeover_refuses_while_a_job_is_active(monkeypatch):
    legacy = {"product": "Abaqus QOL", "pid": 10468}
    monkeypatch.setattr(serve, "health", lambda port, timeout=1.0: legacy)
    monkeypatch.setattr(serve, "active_jobs", lambda port: [{"name": "Closing", "status": "Running"}])
    monkeypatch.setattr(serve, "ensure_dependencies", lambda: None)
    monkeypatch.setattr(serve, "ensure_web", lambda rebuild=False: None)
    monkeypatch.setattr(serve, "local_identity", lambda: {"build": "abc123", "frontend": "x.js"})
    stopped = []
    monkeypatch.setattr(serve, "stop_instance", lambda port: stopped.append(port) or [])
    with pytest.raises(SystemExit) as exit_info:
        serve.main(["--port", "8765", "--no-browser", "--takeover"])
    assert "refusing to stop" in str(exit_info.value)
    assert stopped == []

def test_launcher_identifies_itself_from_any_working_directory(tmp_path):
    """`python scripts/serve.py` must find `services` without help from the CWD.

    Regression: without the repository root on sys.path the identity import was
    swallowed, `api` became 0, and a second launch reported "different-api"
    instead of reusing the healthy instance.
    """
    code = (
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('serve', r'{ROOT / 'scripts' / 'serve.py'}')\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "import json\n"
        "identity = module.local_identity()\n"
        "print('IDENTITY ' + json.dumps(identity, sort_keys=True))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "SEAL_DATA": str(tmp_path), "PYTHONIOENCODING": "utf-8"},
    )
    assert completed.returncode == 0, completed.stderr
    payload = next(
        line.removeprefix("IDENTITY ")
        for line in completed.stdout.splitlines()
        if line.startswith("IDENTITY ")
    )
    identity = json.loads(payload)
    assert identity["api"] >= 3
    assert identity["build"] and identity["data"]


def test_open_when_ready_opens_the_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(serve, "health", lambda port, timeout=1.0: {"product": "Abaqus QOL"})
    monkeypatch.setattr(serve.webbrowser, "open", lambda url: opened.append(url))
    serve.open_when_ready(8899, "the workbench")
    assert opened == ["http://127.0.0.1:8899"]


def test_no_browser_flag_is_the_only_reason_nothing_opens(monkeypatch):
    existing = {
        "product": "Abaqus QOL",
        "status": "ready",
        "build": "abc123",
        "api": 3,
        "data": "d1",
        "pid": 1,
    }
    identity = {"build": "abc123", "frontend": "index-x.js", "api": 3, "data": "d1"}
    monkeypatch.setattr(serve, "health", lambda port, timeout=1.0: existing)
    monkeypatch.setattr(serve, "local_identity", lambda: identity)
    monkeypatch.setattr(serve, "ensure_dependencies", lambda: None)
    monkeypatch.setattr(serve, "ensure_web", lambda rebuild=False: None)
    opened = []
    monkeypatch.setattr(serve.webbrowser, "open", lambda url: opened.append(url))

    assert serve.main(["--port", "8765", "--no-browser"]) == 0
    assert opened == []

    # Without --no-browser the reuse path opens the running instance.
    assert serve.main(["--port", "8765"]) == 0
    assert opened == ["http://127.0.0.1:8765"]


def test_a_booting_launch_keeps_its_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(serve, "lock_path", lambda port: tmp_path / f"serve-{port}.lock")
    path = tmp_path / "serve-8897.lock"
    path.write_text(
        json.dumps({"pid": 4242, "port": 8897, "started": time.time()}), encoding="utf-8"
    )
    monkeypatch.setattr(serve, "health", lambda port, timeout=1.0: None)
    monkeypatch.setattr(serve, "pid_alive", lambda pid: int(pid) == 4242)
    owner = serve.acquire_lock(8897)
    assert owner["pid"] == 4242
    assert path.exists()


def test_a_crashed_launch_lock_is_taken_over(monkeypatch, tmp_path):
    monkeypatch.setattr(serve, "lock_path", lambda port: tmp_path / f"serve-{port}.lock")
    path = tmp_path / "serve-8897.lock"
    path.write_text(json.dumps({"pid": 4242, "port": 8897, "started": 0}), encoding="utf-8")
    monkeypatch.setattr(serve, "health", lambda port, timeout=1.0: None)
    monkeypatch.setattr(serve, "pid_alive", lambda pid: False)
    assert serve.acquire_lock(8897) is True
    assert json.loads(path.read_text(encoding="utf-8"))["pid"] == os.getpid()


def test_one_data_root_has_one_owner(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    monkeypatch.setattr(store, "pid_alive", lambda pid: int(pid) == 1001)
    store.claim_data_root(1001, 8765)
    with pytest.raises(store.Conflict) as refused:
        store.claim_data_root(2002, 8766)
    assert "already owned" in str(refused.value)
    assert "Nothing was stopped" in str(refused.value)
    # The same process may re-enter (API lifespan after the launcher claim).
    assert store.claim_data_root(1001, 8765)["port"] == 8765
    store.release_data_root(1001)
    assert store.claim_data_root(2002, 8766)["pid"] == 2002
    store.release_data_root(2002)


def test_zero_activity_is_reported_as_known_idle(monkeypatch):
    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *arguments):
            return False

    def urlopen(url, timeout):
        calls.append(url)
        return Response([])

    monkeypatch.setattr(serve.urllib.request, "urlopen", urlopen)
    assert serve.active_jobs(8897) == []
    assert calls and calls[0].endswith("/api/jobs")

def test_takeover_refuses_when_job_state_cannot_be_read(monkeypatch):
    legacy = {"product": "Abaqus QOL", "pid": 10468}
    monkeypatch.setattr(serve, "health", lambda port, timeout=1.0: legacy)
    monkeypatch.setattr(serve, "active_jobs", lambda port: None)
    monkeypatch.setattr(serve, "ensure_dependencies", lambda: None)
    monkeypatch.setattr(serve, "ensure_web", lambda rebuild=False: None)
    monkeypatch.setattr(serve, "local_identity", lambda: {"build": "abc123", "frontend": "x.js"})
    stopped = []
    monkeypatch.setattr(serve, "stop_instance", lambda port: stopped.append(port) or [])
    with pytest.raises(SystemExit) as exit_info:
        serve.main(["--port", "8765", "--no-browser", "--takeover"])
    assert "job state could not be established" in str(exit_info.value)
    assert stopped == []
