"""Startup identity, instance reuse and Abaqus launcher discovery.

These tests are license-free: discovery only inspects paths, and the instance
compatibility check works on recorded health payloads.
"""

import importlib.util
import os
from pathlib import Path

import pytest

from integrations.abaqus import launcher
from integrations import dwg

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
    current = {"product": "Abaqus QOL", "build": "abc123", "api": 2}
    monkeypatch.setattr(serve, "local_identity", lambda: {"build": "abc123", "frontend": "x.js"})
    assert serve.compatibility(current) == "current"
    assert serve.compatibility({"product": "Abaqus QOL", "pid": 1}) == "legacy"
    assert serve.compatibility({"product": "Abaqus QOL", "build": "old", "api": 2}) == "different-build"
    assert serve.compatibility(None) == "not-ours"


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
