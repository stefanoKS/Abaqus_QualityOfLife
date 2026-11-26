"""Empty models, drawing isolation and Abaqus-only submission."""

import hashlib
import json
import time
from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient

from packages.engineering import synthetic
from services import store
from services.api.main import app
from services.worker.__main__ import once
from fake_abaqus import install as install_fake_abaqus
from support import create_model, post, prepared, start_run


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    monkeypatch.setenv("SIMPLIFY_ABAQUS_LAUNCHER", str(install_fake_abaqus(tmp_path)))
    monkeypatch.delenv("SEAL_ODA", raising=False)
    with TestClient(app, base_url="http://127.0.0.1") as api:
        yield api


def drawing(path, cavity):
    """Two redistributable drawings that share a basename but differ visibly."""
    doc = ezdxf.new("R2010", units=4)
    space = doc.modelspace()
    space.add_lwpolyline([(0, 0), (20, 0), (20, 10), (0, 10)], close=True)
    if cavity:
        space.add_circle((10, 5), 3)
    space.add_line((0, -5), (20, -5), dxfattribs={"layer": "PANEL"})
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)
    return path


def upload(client, revision, path, name="section.dxf"):
    response = client.post(
        "/api/projects/" + revision["project"] + "/drawing",
        data={"base": revision["id"], "units": "N-mm-s-tonne"},
        files={"file": (name, path.read_bytes())},
    )
    assert response.is_success, response.text
    job = response.json()
    assert once("import-test")
    return client.get("/api/jobs/" + job["id"] + "/imported").raise_for_status().json()


def test_clean_installation_has_no_seeded_model(client):
    assert client.get("/api/groups").json() == []
    assert client.get("/api/projects").json() == []
    assert client.get("/api/runs").json() == []


@pytest.mark.parametrize("dimension", ["2D", "3D"])
def test_new_model_is_explicitly_empty_and_round_trips(client, dimension):
    r = post(client, "/api/projects", {"name": "Draft " + dimension, "dimension": dimension})
    setup = r["setup"]
    assert setup["source"]["kind"] == "empty"
    assert setup["source"]["filename"] == "" and setup["source"]["digest"] == ""
    assert setup["vertices"] == setup["edges"] == setup["faces"] == []
    assert setup["components"] == setup["materials"] == setup["selections"] == []
    assert setup["dimension"] == dimension
    # Rename, save, close and reopen before anything is imported.
    edited = json.loads(json.dumps(setup))
    edited["name"] = "Renamed " + dimension
    saved = client.put(
        "/api/projects/" + r["project"], json={"base": r["id"], "setup": edited}
    )
    assert saved.is_success, saved.text
    assert client.get("/api/revisions/" + saved.json()["id"]).json()["setup"]["name"] == (
        "Renamed " + dimension
    )
    copy = post(client, "/api/projects/" + r["project"] + "/duplicate", {})
    assert copy["setup"]["source"]["kind"] == "empty"
    assert copy["setup"]["name"].endswith(" · copy")
    assert client.post("/api/display", json=copy["setup"]).json()["primitives"] == []


def test_empty_model_rejects_mesh_deck_and_run_clearly(client):
    r = create_model(client, "Nothing yet", example=False)
    mesh = client.post("/api/meshes", json={"revision": r["id"], "token": store.new_id()})
    assert mesh.status_code == 422 and "Import a DXF or DWG" in mesh.json()["detail"]
    deck = client.post(
        "/api/decks", json={"revision": r["id"], "token": store.new_id(), "mesh": store.new_id()}
    )
    assert deck.status_code == 422 and "no drawing" in deck.json()["detail"]
    run = client.post(
        "/api/runs",
        json={
            "revision": r["id"],
            "token": store.new_id(),
            "name": "empty",
            "deck": store.new_id(),
            "mode": "ABAQUS",
        },
    )
    assert run.status_code == 422 and "no drawing" in run.json()["detail"]
    assert client.get("/api/meshes").json() == []
    assert client.get("/api/runs").json() == []


def test_failed_first_import_leaves_the_model_empty(client):
    r = create_model(client, "Never imported", example=False)
    response = client.post(
        "/api/projects/" + r["project"] + "/drawing",
        data={"base": r["id"], "units": "N-mm-s-tonne"},
        files={"file": ("section.dxf", b"this is not a drawing")},
    )
    assert response.is_success
    assert once("import-test")
    assert store.job(response.json()["id"])["status"] == "Failed"
    head = {model["id"]: model for model in client.get("/api/projects").json()}[r["project"]]
    assert head["revision"] == r["id"]
    revision = store.revision(r["id"])
    assert revision["setup"]["source"]["kind"] == "empty"
    assert client.post("/api/display", json=revision["setup"]).json()["primitives"] == []


def test_same_filename_drawings_bind_to_their_own_models(client, tmp_path):
    group = client.post("/api/groups", json={"name": "5q45"}).json()
    a = create_model(client, "Door A", example=False, group=group["id"])
    b = create_model(client, "Door B", example=False, group=group["id"])
    c = create_model(client, "Other group model", example=False)
    for model in (a, b, c):
        assert model["setup"]["source"]["kind"] == "empty"

    first = drawing(tmp_path / "a" / "section.dxf", cavity=True)
    second = drawing(tmp_path / "b" / "section.dxf", cavity=False)
    assert first.read_bytes() != second.read_bytes()
    imported_a = upload(client, a, first)
    imported_b = upload(client, b, second)

    assert imported_a["project"] == a["project"] and imported_b["project"] == b["project"]
    # The display name is identical; identity is the digest and the source revision.
    assert imported_a["setup"]["source"]["filename"] == "section.dxf"
    assert imported_b["setup"]["source"]["filename"] == "section.dxf"
    assert imported_a["setup"]["source"]["digest"] != imported_b["setup"]["source"]["digest"]
    for revision, path in ((imported_a, first), (imported_b, second)):
        original = client.get("/api/revisions/" + revision["id"] + "/drawing").content
        assert hashlib.sha256(original).hexdigest() == hashlib.sha256(path.read_bytes()).hexdigest()
    # A filename assertion cannot pass this: the imported geometry differs.
    assert len(imported_a["setup"]["faces"]) != len(imported_b["setup"]["faces"])
    display_a = client.post("/api/display", json=imported_a["setup"]).json()
    display_b = client.post("/api/display", json=imported_b["setup"]).json()
    assert display_a["primitives"] != display_b["primitives"]

    assert store.revision(c["id"])["setup"]["source"]["kind"] == "empty"

    # A failed replacement leaves the last good drawing, bytes and head intact.
    broken = client.post(
        "/api/projects/" + imported_a["project"] + "/drawing",
        data={"base": imported_a["id"], "units": "N-mm-s-tonne"},
        files={"file": ("section.dxf", b"not a drawing")},
    )
    assert broken.is_success
    assert once("import-test")
    assert store.job(broken.json()["id"])["status"] == "Failed"
    reopened = store.revision(imported_a["id"])
    assert reopened["setup"]["source"]["digest"] == imported_a["setup"]["source"]["digest"]
    assert client.get("/api/revisions/" + imported_a["id"] + "/drawing").content == first.read_bytes()


def test_import_preserves_the_3d_preview_dimension(client, tmp_path):
    r = create_model(client, "Preview panel", example=False, dimension="3D")
    setup = json.loads(json.dumps(r["setup"]))
    setup["extrusion"]["length"] = 22
    saved = client.put(
        "/api/projects/" + r["project"], json={"base": r["id"], "setup": setup}
    ).raise_for_status().json()
    imported = upload(client, saved, drawing(tmp_path / "section.dxf", cavity=False))
    assert imported["setup"]["dimension"] == "3D"
    assert imported["setup"]["formulation"] == "extrusion_preview"
    assert imported["setup"]["extrusion"]["length"] == 22
    # The extrusion remains a preview: meshing is a 2D analysis step.
    mesh = client.post("/api/meshes", json={"revision": imported["id"], "token": store.new_id()})
    assert mesh.status_code == 422 and "extrusion" in mesh.json()["detail"]


def test_demo_submission_is_rejected_without_queueing_and_history_stays_readable(client):
    r, deck, _ = prepared(client)
    before = store.jobs()
    rejected = client.post(
        "/api/runs",
        json={
            "revision": r["id"],
            "deck": deck["id"],
            "token": store.new_id(),
            "name": "demo",
            "mode": "DEMO",
        },
    )
    assert rejected.status_code == 422
    assert "withdrawn" in rejected.json()["detail"]
    assert store.jobs() == before

    # An omitted mode resolves to ABAQUS.
    run = post(
        client,
        "/api/runs",
        {"revision": r["id"], "deck": deck["id"], "token": store.new_id(), "name": "default"},
    )
    assert run["mode"] == "ABAQUS"
    assert once("test") and once("test")
    assert store.job(run["id"])["status"] == "Completed"


def test_queued_legacy_demo_is_retired_and_completed_demo_stays_readable(client):
    r, deck, _ = prepared(client)
    now = time.time()
    queued, finished = store.new_id(), store.new_id()
    with store.connection(True) as db:
        db.execute(
            "INSERT INTO jobs(id,revision,name,mode,scenario,cpus,token,build,created) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (queued, r["id"], "Legacy queued demo", "DEMO", "success", 1, store.new_id(),
             deck["id"], now),
        )
        db.execute(
            "INSERT INTO jobs(id,revision,name,mode,scenario,cpus,token,build,created,solver,"
            "extraction,phase) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (finished, r["id"], "Legacy finished demo", "DEMO", "success", 1, store.new_id(),
             deck["id"], now - 10, "Succeeded", "Succeeded", "Results ready"),
        )
    store.initialize()
    retired = store.job(queued)
    assert retired["solver"] == "Failed" and retired["phase"] == "Withdrawn"
    assert "retired" in retired["diagnostic"]
    # It is never claimed, converted or relaunched.
    assert store.claim("test") is None
    assert store.job(finished)["status"] == "Completed"
    listed = {job["id"]: job for job in client.get("/api/runs").json()}
    assert listed[finished]["mode"] == "DEMO" and listed[finished]["status"] == "Completed"


def test_display_metadata_is_recorded_and_derived_without_rewriting_artifacts(client):
    r, deck, _ = prepared(client)
    run = start_run(client, r, deck)
    assert once("test") and once("test")
    index = client.get("/api/jobs/" + run["id"] + "/artifacts/results.json").json()
    assert index["display"]["bounds"]["extent"]
    assert "magnitude" in index["display"]["ranges"]
    recorded = client.get("/api/jobs/" + run["id"] + "/display-metadata").json()
    assert recorded["source"] == "recorded"

    # Emulate a retained flat-file result produced before generations and before
    # display metadata was recorded.
    with store.connection(True) as db:
        db.execute(
            "UPDATE jobs SET result_generation=0,result_dir=NULL WHERE id=?", (run["id"],)
        )
    path = store.job_dir(run["id"]) / "results.json"
    older = json.loads(path.read_text(encoding="utf-8"))
    older.pop("display")
    path.write_text(store.encoded(older), encoding="utf-8")
    before = path.read_bytes()
    derived = client.get("/api/jobs/" + run["id"] + "/display-metadata").json()
    assert derived["source"] in {"derived", "cache"}
    assert derived["bounds"]["extent"]
    cached = client.get("/api/jobs/" + run["id"] + "/display-metadata").json()
    assert cached["source"] == "cache"
    assert path.read_bytes() == before


def test_existing_legacy_synthetic_model_still_opens(client):
    stored = store.save(synthetic("Legacy bulb").model_dump(mode="json"))
    assert client.get("/api/revisions/" + stored["id"]).is_success
    display = client.post("/api/display", json=stored["setup"]).json()
    assert display["primitives"]
