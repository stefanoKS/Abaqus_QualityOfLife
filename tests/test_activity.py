"""Startup activity must cover every durable job mode and fail closed.

A queued MESH/DECK/IMPORT job is work that a takeover would destroy, and an
inconsistent or stale job is not safe inactivity. These tests exercise the
classifier, the `/api/jobs` coverage and the launcher's refusal decisions.
"""

import json
import time

import pytest
from fastapi.testclient import TestClient

from packages import engineering
from services import activity, store
from services.api.main import app


def add_job(db, revision, mode, **fields):
    jid = store.new_id()
    columns = ["id", "revision", "name", "mode", "scenario", "cpus", "token", "created"]
    values = [jid, revision, f"{mode} job", mode, "success", 1, store.new_id(), time.time()]
    for key, value in fields.items():
        columns.append(key)
        values.append(value)
    db.execute(
        f"INSERT INTO jobs({','.join(columns)}) VALUES ({','.join('?' * len(values))})",
        values,
    )
    return jid


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        yield api


def revision_id():
    setup = engineering.empty("Activity model").model_dump(mode="json")
    return store.save(setup)["id"]


def test_api_jobs_covers_every_mode_and_reports_activity(client, monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    rid = revision_id()
    with store.connection(True) as db:
        for mode in ("IMPORT", "MESH", "DECK", "ABAQUS", "DEMO"):
            add_job(db, rid, mode, solver="Queued", phase="Preparing input")
    response = client.get("/api/jobs")
    assert response.headers["x-abaqus-qol-jobs"] == "all-modes-v1"
    jobs = response.json()
    assert {job["mode"] for job in jobs} == {"IMPORT", "MESH", "DECK", "ABAQUS", "DEMO"}
    assert all(job["activity"] == "active" for job in jobs)
    assert all("owner" in job and "heartbeat" in job for job in jobs)


@pytest.mark.parametrize(
    "fields,expected",
    [
        ({"solver": "Queued"}, activity.ACTIVE),
        ({"solver": "Preparing"}, activity.ACTIVE),
        ({"solver": "Waiting for license"}, activity.ACTIVE),
        ({"solver": "Running"}, activity.ACTIVE),
        ({"solver": "Succeeded", "extraction": "Queued"}, activity.ACTIVE),
        ({"solver": "Succeeded", "extraction": "Running"}, activity.ACTIVE),
        (
            {
                "solver": "Succeeded",
                "extraction": "Succeeded",
                "owner": "worker",
                "heartbeat": time.time(),
                "cancelled": 1,
            },
            activity.UNCERTAIN,
        ),
        ({"solver": "Succeeded", "extraction": "Succeeded"}, activity.TERMINAL),
        ({"solver": "Failed", "extraction": "Failed"}, activity.TERMINAL),
        ({"solver": "Cancelled", "extraction": "Cancelled"}, activity.TERMINAL),
        (
            {"solver": "Running", "owner": "worker", "heartbeat": time.time() - 120},
            activity.UNCERTAIN,
        ),
        (
            {"solver": "Running", "phase": "Process termination unconfirmed"},
            activity.UNCERTAIN,
        ),
        (
            {
                "solver": "Succeeded",
                "extraction": "Succeeded",
                "owner": "worker",
                "heartbeat": time.time(),
            },
            activity.UNCERTAIN,
        ),
        # A completed solver with inconsistent extraction is not "idle".
        ({"solver": "Succeeded", "extraction": "Pending"}, activity.UNCERTAIN),
        ({"solver": "Something new"}, activity.UNCERTAIN),
    ],
)
def test_activity_classification(fields, expected):
    assert activity.classify({"name": "x", **fields}) == expected


def test_cancel_requested_is_not_safe_inactivity():
    job = {
        "solver": "Running",
        "extraction": "Pending",
        "status": "Cancel requested",
        "owner": "worker",
        "heartbeat": time.time(),
    }
    assert activity.classify(job) == activity.UNCERTAIN


def test_unknown_worker_state_is_uncertain():
    job = {
        "solver": "Running",
        "extraction": "Pending",
        "status": "Unknown / worker disconnected",
    }
    assert activity.classify(job) == activity.UNCERTAIN


def test_queued_mesh_deck_import_are_reported_as_unsafe(client, monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    rid = revision_id()
    with store.connection(True) as db:
        for mode in ("MESH", "DECK", "IMPORT"):
            add_job(db, rid, mode, solver="Queued")
    unsafe = client.get("/api/jobs").json()
    assert {job["mode"] for job in unsafe} == {"MESH", "DECK", "IMPORT"}
    assert all(job["activity"] == "active" for job in unsafe)


def _payload(**overrides):
    job = {
        "id": "j1",
        "mode": "MESH",
        "activity": "active",
        "solver": "Queued",
        "extraction": "Pending",
        "status": "Queued",
    }
    job.update(overrides)
    return job


def test_launcher_treats_an_unclassified_older_api_as_unreadable(monkeypatch):
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("serve_activity", root / "scripts" / "serve.py")
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)

    class Response:
        def __init__(self, payload, coverage='all-modes-v1'):
            self.payload = payload
            self.headers = {'X-Abaqus-QOL-Jobs': coverage}

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *arguments):
            return False

    def urlopen(url, timeout):
        return Response([{"id": "j1", "mode": "MESH", "status": "Queued"}])

    monkeypatch.setattr(serve.urllib.request, "urlopen", urlopen)
    assert serve.active_jobs(8897) is None


def test_an_empty_list_without_a_coverage_header_is_unreadable(monkeypatch):
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("serve_activity3", root / "scripts" / "serve.py")
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)

    class Response:
        def __init__(self):
            self.headers = {}

        def read(self):
            return b"[]"

        def __enter__(self):
            return self

        def __exit__(self, *arguments):
            return False

    monkeypatch.setattr(serve.urllib.request, "urlopen", lambda url, timeout: Response())
    assert serve.active_jobs(8897) is None


def test_launcher_returns_only_unsafe_jobs(monkeypatch):
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("serve_activity2", root / "scripts" / "serve.py")
    serve = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(serve)

    class Response:
        def __init__(self, payload, coverage='all-modes-v1'):
            self.payload = payload
            self.headers = {'X-Abaqus-QOL-Jobs': coverage}

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *arguments):
            return False

    monkeypatch.setattr(
        serve.urllib.request,
        "urlopen",
        lambda url, timeout: Response(
            [
                _payload(id="a", activity="active"),
                _payload(id="t", mode="ABAQUS", activity="terminal", solver="Succeeded", extraction="Succeeded"),
            ]
        ),
    )
    unsafe = serve.active_jobs(8897)
    assert [job["id"] for job in unsafe] == ["a"]
