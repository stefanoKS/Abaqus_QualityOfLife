import copy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

import pytest
from fastapi.testclient import TestClient

from services import store
from services.api.main import app
from services.worker.__main__ import once


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    monkeypatch.delenv("SIMPLIFY_ABAQUS_LAUNCHER", raising=False)
    monkeypatch.delenv("SEAL_ODA", raising=False)
    with TestClient(app, base_url="http://127.0.0.1") as api:
        yield api


def post(api, path, data):
    res = api.post(path, json=data)
    assert res.is_success, res.text
    return res.json()


def built(api):
    r = post(api, "/api/projects", {"name": "Section"})
    build = post(api, "/api/builds", {"revision": r["id"], "token": store.new_id()})
    assert once("test")
    result = store.job(build["id"])
    assert result["status"] == "Completed", result["diagnostic"]
    return r, result


def request_run(api, r, b, scenario):
    return post(
        api,
        "/api/runs",
        dict(
            revision=r["id"],
            build=b["id"],
            token=store.new_id(),
            scenario=scenario,
            mode="DEMO",
            name="Test run",
        ),
    )


def test_persisted_revisions_and_safe_topology(client):
    r = post(client, "/api/projects", {"name": "Original"})
    edited = copy.deepcopy(r["setup"])
    edited["motion"]["travel"] = -4
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
    r = post(client, "/api/projects", {"name": "Concurrent"})
    body = {"revision": r["id"], "token": store.new_id()}
    first = post(client, "/api/builds", body)
    assert post(client, "/api/builds", body)["id"] == first["id"]
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


def test_jobs_cancel_fail_reextract_and_immutable_artifacts(client):
    r, b = built(client)
    queued = request_run(client, r, b, "slow")
    assert client.post("/api/jobs/" + queued["id"] + "/cancel").json()["status"] == "Cancelled"
    fail = request_run(client, r, b, "failure")
    assert once("test")
    assert store.job(fail["id"])["solver"] == "Failed"
    slow = request_run(client, r, b, "slow")
    with ThreadPoolExecutor(1) as pool:
        work = pool.submit(once, "test")
        for _ in range(100):
            if store.job(slow["id"])["solver"] == "Running":
                break
            time.sleep(0.05)
        assert store.job(slow["id"])["solver"] == "Running"
        assert store.cancel(slow["id"])["status"] in {"Cancel requested", "Cancelled"}
        assert work.result(timeout=10)
    assert store.job(slow["id"])["status"] == "Cancelled"
    run = request_run(client, r, b, "extraction_failure")
    assert once("test") and once("test")
    before = store.job(run["id"])
    assert before["solver"] == "Succeeded" and before["extraction"] == "Failed"
    assert store.retry(run["id"])["solver"] == "Succeeded"
    assert once("test")
    job = store.job(run["id"])
    assert job["status"] == "Completed" and job["started"] == before["started"]
    path = "/api/jobs/" + job["id"] + "/artifacts/"
    assert client.get(path + "history.csv").status_code == 200
    index = client.get(path + "results.json").json()
    assert index["mode"] == "DEMO" and len(index["frames"]) == 31
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
    r = post(client, "/api/projects", {"name": "Drawing"})
    url = "/api/projects/" + r["project"] + "/drawing"
    fields = {"base": r["id"], "units": "N-mm-s-tonne"}
    assert "DWG converter not configured" in client.get("/api/capabilities").json()["dwg"]
    for name in ["example.dwg", "../escape.dxf", "bad.step"]:
        response = client.post(url, data=fields, files={"file": (name, b"bad content")})
        assert response.status_code == 422, response.text
    broken = client.post(url, data=fields, files={"file": ("broken.dxf", b"bad content")}).json()
    assert once("import-test")
    assert store.job(broken["id"])["status"] == "Failed"
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
    assert "not configured" in client.get("/api/capabilities").json()["abaqus"]
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
    build = post(client, "/api/builds", {"revision": saved["id"], "token": store.new_id()})
    assert once("mesh-test")
    job = store.job(build["id"])
    assert job["status"] == "Completed", job["diagnostic"]
    assert "*Solid Section" in (store.job_dir(build["id"]) / "analysis.inp").read_text()
