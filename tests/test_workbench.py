import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from services import store
from services.api.main import app
from services.worker.__main__ import once
from fake_abaqus import install as install_fake_abaqus
from support import create_model, legacy_fixture, save_fixture, start_run


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    monkeypatch.setenv("SIMPLIFY_ABAQUS_LAUNCHER", str(install_fake_abaqus(tmp_path)))
    monkeypatch.delenv("SEAL_ODA", raising=False)
    with TestClient(app, base_url="http://127.0.0.1") as api:
        yield api


def post(api, path, data):
    res = api.post(path, json=data)
    assert res.is_success, res.text
    return res.json()


def prepared(api, revision=None):
    """Create (if needed) a model with a completed mesh, reviewed fixture and deck."""
    if revision is None:
        revision = create_model(api, "Section")
    mesh = post(api, "/api/meshes", {"revision": revision["id"], "token": store.new_id()})
    assert once("test")
    assert store.job(mesh["id"])["status"] == "Completed", store.job(mesh["id"])["diagnostic"]
    labels = legacy_fixture(api, mesh["id"])["labels"]
    save_fixture(api, mesh["id"], labels)
    deck = post(
        api, "/api/decks", {"revision": revision["id"], "token": store.new_id(), "mesh": mesh["id"]}
    )
    assert once("test")
    result = store.job(deck["id"])
    assert result["status"] == "Completed", result["diagnostic"]
    return revision, result


def request_run(api, r, deck, name="Test run"):
    return start_run(api, r, deck, name=name)


def test_persisted_revisions_and_safe_topology(client):
    r = create_model(client, "Original")
    edited = copy.deepcopy(r["setup"])
    edited["motion"]["stroke"] = 4.0
    edited["motion"]["angle"] = -90.0
    edited["motion"]["travel"] = -4.0
    payload = {"setup": edited, "base": r["id"]}
    saved = client.put("/api/projects/" + r["project"], json=payload)
    assert saved.is_success
    assert client.put("/api/projects/" + r["project"], json=payload).status_code == 409
    with TestClient(app, base_url="http://127.0.0.1") as fresh:
        assert fresh.get("/api/revisions/" + r["id"]).json()["setup"]["motion"]["travel"] != -4
        current = saved.json()
        assert fresh.get("/api/revisions/" + current["id"]).json()["setup"] == edited
        edited["edges"][0]["name"] = "Invented topology"
        assert (
            fresh.put(
                "/api/projects/" + r["project"], json={"base": current["id"], "setup": edited}
            ).status_code
            == 422
        )


def test_claim_retry_reconcile_and_idempotency(client):
    r = create_model(client, "Concurrent")
    body = {"revision": r["id"], "token": store.new_id()}
    first = post(client, "/api/meshes", body)
    assert post(client, "/api/meshes", body)["id"] == first["id"]
    with ThreadPoolExecutor(4) as pool:
        claimed = list(pool.map(store.claim, ["a", "b", "c", "d"]))
    winners = [c for c in claimed if c]
    assert len(winners) == 1
    owner = winners[0]["owner"]
    store.update(first["id"], owner, heartbeat=time.time() - 80)
    assert store.job(first["id"])["status"] == "Unknown / worker disconnected"
    assert store.claim("replacement") is None
    assert client.post("/api/jobs/" + first["id"] + "/retry").status_code == 409
    assert (
        client.post("/api/jobs/" + first["id"] + "/cancel").json()["status"]
        == "Unknown / worker disconnected"
    )


def test_jobs_cancel_fail_reextract_and_immutable_artifacts(client, monkeypatch):
    r, b = prepared(client)
    # A run can be cancelled before the worker claims it.
    queued = request_run(client, r, b, "Queued")
    assert client.post("/api/jobs/" + queued["id"] + "/cancel").json()["status"] == "Cancelled"
    # Solver failure is signalled to the launcher double by a marker in the job.
    fail = request_run(client, r, b, "Failing solve")
    store.job_dir(fail["id"]).mkdir(parents=True, exist_ok=True)
    (store.job_dir(fail["id"]) / "fail-solver").write_text("", encoding="ascii")
    assert once("test")
    assert store.job(fail["id"])["solver"] == "Failed"
    # A slow manufactured solve is cancelled while it is actually running.
    monkeypatch.setenv("ABAQUS_QOL_FAKE_SOLVE_SECONDS", "3")
    slow = request_run(client, r, b, "Slow")
    with ThreadPoolExecutor(1) as pool:
        work = pool.submit(once, "test")
        for _ in range(200):
            if store.job(slow["id"])["solver"] == "Running":
                break
            time.sleep(0.02)
        assert store.job(slow["id"])["solver"] == "Running"
        assert store.cancel(slow["id"])["status"] in {"Cancel requested", "Cancelled"}
        assert work.result(timeout=30)
    assert store.job(slow["id"])["status"] == "Cancelled"
    monkeypatch.setenv("ABAQUS_QOL_FAKE_SOLVE_SECONDS", "0.2")
    # Extraction fails once, keeps its solver evidence, and succeeds on retry.
    run = request_run(client, r, b, "Extract retry")
    store.job_dir(run["id"]).mkdir(parents=True, exist_ok=True)
    (store.job_dir(run["id"]) / "fail-extract-once").write_text("", encoding="ascii")
    assert once("test")  # solver
    assert once("test")  # extraction fails
    before = store.job(run["id"])
    assert before["solver"] == "Succeeded" and before["extraction"] == "Failed"
    assert store.retry(run["id"])["solver"] == "Succeeded"
    assert once("test")
    job = store.job(run["id"])
    assert job["status"] == "Completed" and job["started"] == before["started"]
    path = "/api/jobs/" + job["id"] + "/artifacts/"
    assert client.get(path + "history.csv").status_code == 200
    index = client.get(path + "results.json").json()
    assert index["mode"] == "ABAQUS" and len(index["frames"]) == 31
    assert index["manufactured"] is True
    assert index["display"]["bounds"]["extent"]
    assert client.get(path + "workbench.sqlite3").status_code == 404
    assert (
        client.get(path + "analysis.inp").content
        == client.get("/api/jobs/" + b["id"] + "/artifacts/analysis.inp").content
    )
    r["setup"]["motion"]["travel"] = -9
    assert client.put(
        "/api/projects/" + r["project"], json={"setup": r["setup"], "base": r["id"]}
    ).is_success
    duplicate = post(client, "/api/jobs/" + job["id"] + "/duplicate", {})
    assert (
        duplicate["setup"]["motion"]["travel"]
        == client.get(path + "setup.json").json()["motion"]["travel"]
        != -9
    )


def test_upload_confined_and_capability_diagnostics(client):
    r = create_model(client, "Drawing", example=False)
    url = "/api/projects/" + r["project"] + "/drawing"
    fields = {"base": r["id"], "units": "N-mm-s-tonne"}
    assert client.get("/api/capabilities").json()["dwg"] == "Configured"
    assert client.get("/api/capabilities").json()["odaRequired"] is False
    for name in ["../escape.dxf", "bad.step"]:
        response = client.post(url, data=fields, files={"file": (name, b"bad content")})
        assert response.status_code == 422, response.text
    # A corrupt DWG is accepted for decoding and then fails as a job with a clear
    # message; it must never damage the revisions that already exist.
    corrupt_dwg = client.post(url, data=fields, files={"file": ("corrupt.dwg", b"AC1032 rubbish")})
    assert corrupt_dwg.is_success, corrupt_dwg.text
    broken = client.post(url, data=fields, files={"file": ("broken.dxf", b"bad content")}).json()
    for _ in range(3):
        once("import-test")
    assert store.job(broken["id"])["status"] == "Failed"
    corrupt = store.job(corrupt_dwg.json()["id"])
    assert corrupt["status"] == "Failed"
    assert "DWG" in corrupt["diagnostic"] or "drawing" in corrupt["diagnostic"].lower()
    assert client.get("/api/revisions/" + r["id"]).is_success
    path = Path(__file__).resolve().parents[1] / "examples/hollow-section.dxf"
    response = client.post(url, data=fields, files={"file": ("new.dxf", path.read_bytes())})
    assert response.is_success, response.text
    import_job = response.json()
    assert once("import-test")
    new = client.get("/api/jobs/" + import_job["id"] + "/imported").raise_for_status().json()
    assert client.get("/api/revisions/" + new["id"] + "/drawing").content == path.read_bytes()
    assert (
        new["setup"]["source"]["filename"] == "new.dxf" and new["setup"]["source"]["kind"] == "dxf"
    )
    assert not new["setup"]["selections"][0]["entities"]
    assert all(f["material"] is None for f in new["setup"]["faces"])
    assert (
        client.post(
            "/api/projects",
            json={"name": "unauthorized"},
            headers={"Origin": "https://example.com"},
        ).status_code
        == 403
    )
    assert client.get("/api/projects", headers={"Host": "example.com"}).status_code == 400
    capabilities = client.get("/api/capabilities").json()
    # Either a discovered installation or an actionable explanation must be present.
    assert capabilities["abaqus"] == "Configured" or "Abaqus launcher" in capabilities["abaqus"]
    assert capabilities["abaqusSource"]
    assert capabilities["odaRequired"] is False
    assert capabilities["schemaVersion"] >= 2
    # Complete the imported assembly through the same saved-project / worker path.
    setup = new["setup"]
    for c in setup["components"]:
        c["role"] = "moving_panel" if c["id"] == "panel" else "seal"
    for f in setup["faces"]:
        if not f["cavity"]:
            f["material"] = setup["materials"][0]["id"]
    setup["selections"][0]["entities"] = [
        next(e["id"] for e in setup["edges"] if e["component"] != "panel")
    ]
    setup["materials"][0]["density"] *= 1.01
    saved = (
        client.put("/api/projects/" + new["project"], json={"setup": setup, "base": new["id"]})
        .raise_for_status()
        .json()
    )
    assert saved["setup"]["materials"][0]["version"] == 2
    mesh = post(client, "/api/meshes", {"revision": saved["id"], "token": store.new_id()})
    assert once("mesh-test")
    mesh_job = store.job(mesh["id"])
    assert mesh_job["status"] == "Completed", mesh_job["diagnostic"]
    labels = legacy_fixture(client, mesh["id"])["labels"]
    save_fixture(client, mesh["id"], labels)
    deck = post(
        client, "/api/decks", {"revision": saved["id"], "token": store.new_id(), "mesh": mesh["id"]}
    )
    assert once("mesh-test")
    job = store.job(deck["id"])
    assert job["status"] == "Completed", job["diagnostic"]
    assert "*Solid Section" in (store.job_dir(deck["id"]) / "analysis.inp").read_text()
