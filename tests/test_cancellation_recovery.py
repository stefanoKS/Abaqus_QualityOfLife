"""Cancellation settlement, recovery and portable provenance.

Manufactured evidence only: the launcher double writes labelled synthetic
results; no solver, license or ODB is involved.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from services import store
from services.api.main import app
from services.worker.__main__ import once
from fake_abaqus import install as install_fake_abaqus
from support import (
    create_model,
    prepare_deck,
    prepare_mesh,
    run_worker,
    save_fixture,
    start_run,
)

from packages.engineering import portable


def api_for(monkeypatch, data, launcher):
    monkeypatch.setenv("SEAL_DATA", str(data))
    monkeypatch.setenv("SIMPLIFY_ABAQUS_LAUNCHER", str(launcher))
    monkeypatch.setenv("ABAQUS_QOL_FAKE_EXTRACT_SECONDS", "0")
    return TestClient(app, base_url="http://127.0.0.1")


def one_panel(api, name="Recovery"):
    revision = create_model(api, name, example=True)
    mesh = prepare_mesh(api, revision)
    labels = api.post("/api/meshes/" + mesh["id"] + "/fixture/edges", json={}).json()["labels"]
    save_fixture(api, mesh["id"], labels)
    return revision, prepare_deck(api, revision, mesh["id"])


def raw(jid):
    with store.connection() as db:
        return dict(db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())


def wait_for(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def cancel_running_solver(api, jid, directory, marker=None):
    if marker:
        (directory / marker).touch()
    with ThreadPoolExecutor(1) as pool:
        work = pool.submit(run_worker)
        assert wait_for(lambda: store.job(jid)["solver"] == "Running")
        if marker == "odb-before-slow":
            assert wait_for(lambda: (directory / "analysis.odb").is_file())
        time.sleep(0.5)
        response = api.post("/api/jobs/" + jid + "/cancel")
        assert response.is_success, response.text
        first = response.json()
        work.result(timeout=60)
    return first


def test_cancelled_solver_queues_one_recovery_and_reopens_cancelled(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    output = tmp_path / "out"
    output.mkdir()
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = one_panel(api)
        monkeypatch.setenv("ABAQUS_QOL_FAKE_SOLVE_SECONDS", "20")
        run = start_run(api, revision, deck, name="Cancel with ODB")
        jid = run["id"]
        directory = Path(store.job_dir(jid))
        directory.mkdir(parents=True, exist_ok=True)
        first = cancel_running_solver(api, jid, directory, "odb-before-slow")
        assert first["status"] in {"Cancel requested", "Cancelled"}

        job = store.job(jid)
        assert job["solver"] == "Cancelled"
        # A verified stop plus a safe candidate queues exactly one recovery.
        assert job["extraction"] == "Queued"
        assert job["salvage"] == 1
        assert job["cancel_scope"] is None
        assert job["ended"] is None
        assert raw(jid)["cancelled"] == 0
        # The recovery reads whatever the ODB saved.
        (directory / "partial-closing").touch()
        # The next worker claims that one attempt.
        run_worker()
        assert not once("probe")
        recovered = store.job(jid)
        assert recovered["extraction"] == "Succeeded"
        assert recovered["result_state"] == "partial"
        assert recovered["result"]["generation"] == 1
        assert recovered["result"]["summary"]["solver_outcome"] == "Cancelled"
        assert recovered["result"]["summary"]["extraction_outcome"] == "Succeeded"
        solver_log = (directory / "solver.log").read_text(encoding="utf-8", errors="replace")
        assert solver_log.count("Manufactured solve started") == 1

        packaged = api.post(
            "/api/files/result/package", json={"job": jid, "folder": str(output)}
        )
        assert packaged.is_success, packaged.text
        path = Path(packaged.json()["path"])

    with api_for(monkeypatch, tmp_path / "fresh", launcher) as fresh:
        opened = fresh.post("/api/files/result/open", json={"path": str(path)})
        assert opened.is_success, opened.text
        reopened = opened.json()
        # A Cancelled solver stays Cancelled through packaging and reopening.
        assert reopened["solver"] == "Cancelled"
        assert reopened["status"] == "Cancelled"
        assert reopened["extraction"] == "Succeeded"
        assert reopened["result"]["available"] is True
        assert reopened["result"]["generation"] == 1
        assert reopened["result"]["summary"]["solver_outcome"] == "Cancelled"
        assert reopened["result"]["summary"]["extraction_outcome"] == "Succeeded"
        assert reopened["result"]["summary"]["provenance_complete"] is True
        assert fresh.get(
            f"/api/jobs/{reopened['id']}/results/1/results.json"
        ).status_code == 200


def test_repeated_cancel_is_idempotent_and_no_candidate_reports_reason(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = one_panel(api)
        monkeypatch.setenv("ABAQUS_QOL_FAKE_SOLVE_SECONDS", "20")
        run = start_run(api, revision, deck, name="Cancel without ODB")
        jid = run["id"]
        directory = Path(store.job_dir(jid))
        directory.mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(1) as pool:
            work = pool.submit(run_worker)
            assert wait_for(lambda: store.job(jid)["solver"] == "Running")
            time.sleep(0.4)
            first = api.post("/api/jobs/" + jid + "/cancel")
            second = api.post("/api/jobs/" + jid + "/cancel")
            assert first.is_success and second.is_success
            work.result(timeout=60)
        job = store.job(jid)
        assert job["solver"] == "Cancelled"
        assert job["extraction"] == "Pending"
        assert job["salvage"] == 0
        assert job["status"] == "Cancelled"
        # Actionable persisted reason, not only a worker.log line.
        assert "ODB" in job["diagnostic"] or "candidate" in job["diagnostic"]


def test_failed_partial_reopens_as_failed(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    output = tmp_path / "out"
    output.mkdir()
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = one_panel(api)
        run = start_run(api, revision, deck, name="Failed partial")
        jid = run["id"]
        directory = Path(store.job_dir(jid))
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "fail-solver-with-odb").touch()
        (directory / "partial-closing").touch()
        run_worker()
        run_worker()
        packaged = api.post(
            "/api/files/result/package", json={"job": jid, "folder": str(output)}
        )
        assert packaged.is_success, packaged.text
        path = Path(packaged.json()["path"])

    with api_for(monkeypatch, tmp_path / "fresh", launcher) as fresh:
        reopened = fresh.post("/api/files/result/open", json={"path": str(path)}).json()
        assert reopened["solver"] == "Failed"
        assert reopened["status"] == "Failed"
        assert reopened["result"]["summary"]["solver_outcome"] == "Failed"
        assert reopened["result"]["summary"]["availability"] == "partial"


def test_legacy_package_without_facts_opens_as_unknown(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    output = tmp_path / "out"
    output.mkdir()
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = one_panel(api)
        run = start_run(api, revision, deck, name="Legacy facts")
        jid = run["id"]
        directory = Path(store.job_dir(jid))
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "fail-solver-with-odb").touch()
        (directory / "partial-closing").touch()
        run_worker()
        run_worker()
        packaged = api.post(
            "/api/files/result/package", json={"job": jid, "folder": str(output)}
        )
        assert packaged.is_success, packaged.text
        container = portable.read_container(
            Path(packaged.json()["path"]), portable.RESULT_KIND
        )
        members = dict(container["members"])
        index = json.loads(members["results.json"])
        index.pop("solver_outcome", None)
        index.pop("failure_reason", None)
        index.pop("extraction_outcome", None)
        members["results.json"] = json.dumps(index).encode("utf-8")
        provenance = json.loads(members["provenance.json"])
        provenance.pop("result", None)
        provenance["job"].pop("solver", None)
        provenance["job"].pop("extraction", None)
        members["provenance.json"] = json.dumps(provenance).encode("utf-8")
        legacy = tmp_path / "legacy.aqresult"
        portable.write_container(
            legacy,
            portable.RESULT_KIND,
            members,
            {"name": "Legacy", "job": jid, "revision": revision["id"], "availability": "partial"},
        )

    with api_for(monkeypatch, tmp_path / "fresh", launcher) as fresh:
        opened = fresh.post("/api/files/result/open", json={"path": str(legacy)})
        assert opened.is_success, opened.text
        reopened = opened.json()
        # Missing facts are explicit Unknown, never a guessed Failed.
        assert reopened["solver"] == "Unknown"
        assert reopened["status"] == "Unknown"
        assert reopened["result"]["summary"]["solver_outcome"] == "Unknown"
        assert reopened["result"]["summary"]["provenance_complete"] is False


def test_auto_package_records_the_committed_generation(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    output = tmp_path / "auto"
    output.mkdir()
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = one_panel(api)
        run = api.post(
            "/api/runs",
            json={
                "revision": revision["id"],
                "deck": deck["id"],
                "token": store.new_id(),
                "name": "Auto package",
                "mode": "ABAQUS",
                "cpus": 1,
                "output_dir": str(output),
            },
        ).json()
        jid = run["id"]
        directory = Path(store.job_dir(jid))
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "fail-solver-with-odb").touch()
        (directory / "partial-closing").touch()
        run_worker()
        run_worker()
        job = store.job(jid)
        assert job["publication"] == "Saved"
        path = Path(job["result_file"])
        provenance = json.loads(
            portable.read_container(path, portable.RESULT_KIND)["members"]["provenance.json"]
        )
        # Provenance describes the committed row, not the pre-commit attempt.
        assert provenance["job"]["extraction"] == "Succeeded"
        assert provenance["result"]["extraction_outcome"] == "Succeeded"
        assert provenance["result"]["generation"] == 1
        base, _ = store.result_generation_dir(jid)
        assert provenance["result"]["index_sha256"] == store.digest(Path(base) / "results.json")
