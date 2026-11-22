"""Project groups sit logically above model histories without moving data."""

import json
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.engineering import synthetic
from services import store
from services.api.main import app


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    monkeypatch.setenv("SIMPLIFY_ABAQUS_LAUNCHER", str(__import__("fake_abaqus").install(tmp_path)))
    monkeypatch.delenv("SEAL_ODA", raising=False)
    with TestClient(app, base_url="http://127.0.0.1") as api:
        yield api


def test_group_holds_named_models_and_duplicate_stays_inside(client):
    group = client.post("/api/groups", json={"name": "5q45"})
    assert group.status_code == 201
    gid = group.json()["id"]
    two = client.post("/api/projects", json={"name": "Door 2D", "group": gid, "example": True}).json()
    three = client.post(
        "/api/projects", json={"name": "Door 3D", "dimension": "3D", "group": gid, "example": True}
    ).json()
    assert two["project"] != three["project"]

    listing = client.get("/api/groups").json()
    (only,) = [g for g in listing if g["id"] == gid]
    assert {m["name"] for m in only["models"]} == {"Door 2D", "Door 3D"}
    assert all(m["group"] == gid and m["group_name"] == "5q45" for m in only["models"])
    # A clean installation has no implicit group: the new group is the only one.
    assert [g["name"] for g in listing] == ["5q45"]

    copy = client.post("/api/projects/" + two["project"] + "/duplicate", json={}).json()
    assert copy["project"] != two["project"]
    assert copy["number"] == 1
    assert copy["setup"]["name"].endswith(" · copy")
    assert copy["setup"]["source"]["digest"] == two["setup"]["source"]["digest"]
    after = {m["id"]: m for m in client.get("/api/projects").json()}
    assert after[copy["project"]]["group"] == gid
    assert after[two["project"]]["revisions"] == 1

    named = client.post(
        "/api/projects/" + two["project"] + "/duplicate", json={"name": "Door 2D variant"}
    ).json()
    assert named["setup"]["name"] == "Door 2D variant"

    assert client.post("/api/projects", json={"name": "Orphan", "group": store.new_id()}).status_code == 404


def test_model_revision_history_is_newest_first(client):
    r = client.post("/api/projects", json={"name": "History", "example": True}).json()
    first, second = r["setup"], json.loads(json.dumps(r["setup"]))
    second["motion"]["travel"] = -4
    saved = client.put(
        "/api/projects/" + r["project"], json={"base": r["id"], "setup": second}
    )
    assert saved.is_success, saved.text
    history = client.get("/api/projects/" + r["project"] + "/revisions").json()
    assert [row["number"] for row in history] == [2, 1]
    assert history[0]["id"] == saved.json()["id"]
    assert all(row["name"] == "History" for row in history)


LEGACY_SCHEMA = """
CREATE TABLE projects(id TEXT PRIMARY KEY, head TEXT NOT NULL);
CREATE TABLE revisions(
  id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id),
  number INTEGER NOT NULL, created REAL NOT NULL, setup TEXT NOT NULL,
  source_id TEXT, UNIQUE(project, number));
CREATE TABLE jobs(
  id TEXT PRIMARY KEY, revision TEXT NOT NULL REFERENCES revisions(id),
  name TEXT NOT NULL, mode TEXT NOT NULL, scenario TEXT NOT NULL,
  cpus INTEGER NOT NULL, token TEXT NOT NULL UNIQUE, build TEXT REFERENCES jobs(id),
  created REAL NOT NULL, started REAL, ended REAL, heartbeat REAL, owner TEXT,
  pid INTEGER, process_started REAL, solver TEXT NOT NULL DEFAULT 'Queued',
  extraction TEXT NOT NULL DEFAULT 'Pending', cancelled INTEGER DEFAULT 0,
  phase TEXT NOT NULL DEFAULT 'Awaiting worker', step TEXT, increment INTEGER, step_time REAL,
  exit_code INTEGER, extraction_exit INTEGER, diagnostic TEXT NOT NULL DEFAULT '',
  input_hash TEXT, manifest TEXT NOT NULL DEFAULT '[]');
"""


def test_populated_legacy_database_migrates_once_without_moving_identities(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    project, revision, job_id, source_id = store.new_id(), store.new_id(), store.new_id(), store.new_id()
    setup = synthetic("Legacy bulb").model_dump(mode="json")
    setup["source"] = {
        "kind": "dxf",
        "filename": "old.dxf",
        "digest": "0" * 64,
        "drawing_units": "millimetres",
    }
    drawing = tmp_path / "drawings" / source_id
    drawing.mkdir(parents=True)
    (drawing / "drawing.dxf").write_bytes(b"legacy drawing bytes")
    db = sqlite3.connect(tmp_path / "workbench.sqlite3")
    db.executescript(LEGACY_SCHEMA)
    db.execute("INSERT INTO projects VALUES (?,?)", (project, revision))
    db.execute(
        "INSERT INTO revisions VALUES (?,?,?,?,?,?)",
        (revision, project, 1, time.time(), store.encoded(setup), source_id),
    )
    db.execute(
        "INSERT INTO jobs(id,revision,name,mode,scenario,cpus,token,created,solver,extraction,"
        "phase,manifest) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (job_id, revision, "Legacy run", "DEMO", "success", 1, "token-1", time.time(),
         "Succeeded", "Succeeded", "Results ready", '["results.json"]'),
    )
    db.commit()
    db.close()

    store.initialize()
    store.initialize()  # Idempotent: a second start must not create another group.

    groups = store.groups()
    assert len(groups) == 1
    assert groups[0]["name"] == store.LEGACY_GROUP_NAME
    assert [m["id"] for m in groups[0]["models"]] == [project]

    # Revision identity, run identity and the original drawing all survive.
    assert store.revision(revision)["setup"]["name"] == "Legacy bulb"
    assert [r["id"] for r in store.revision_history(project)] == [revision]
    assert store.job(job_id)["name"] == "Legacy run"

    with TestClient(app, base_url="http://127.0.0.1") as api:
        assert api.get("/api/revisions/" + revision).json()["setup"]["name"] == "Legacy bulb"
        assert api.get("/api/revisions/" + revision + "/drawing").content == b"legacy drawing bytes"
        assert api.get("/api/runs").json()[0]["id"] == job_id
        assert api.get("/api/jobs/" + job_id).json()["status"] == "Completed"
        model = api.get("/api/projects").json()[0]
        assert model["group_name"] == store.LEGACY_GROUP_NAME

    # A third start after the migration leaves the schema and rows untouched.
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM groups").fetchone()[0] == 1
        assert (
            db.execute("SELECT COUNT(*) FROM projects WHERE group_id IS NULL").fetchone()[0] == 0
        )


def test_group_rename_keeps_artifact_directories_in_place(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    store.initialize()
    r = store.save(synthetic("Grouped").model_dump(mode="json"))
    before = store.job_dir(store.new_id()).parent
    with store.connection() as db:
        db.execute("UPDATE groups SET name='Renamed'")
    assert store.projects()[0]["group_name"] == "Renamed"
    assert store.job_dir(store.new_id()).parent == before == Path(store.root()) / "jobs"
