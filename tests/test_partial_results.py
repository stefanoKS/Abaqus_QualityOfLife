"""Partial-result lifecycle on the real store, API and worker.

The launcher/ODB-reader double is clearly labelled manufactured test evidence in
every artifact it writes. No solver, license or native ODB is involved.
"""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from services import store
from services.api.main import app
from fake_abaqus import install as install_fake_abaqus
from support import (
    create_model,
    prepare_deck,
    prepare_mesh,
    run_worker,
    save_fixture,
    start_run,
)


def api_for(monkeypatch, data: Path, launcher):
    monkeypatch.setenv("SEAL_DATA", str(data))
    monkeypatch.setenv("SIMPLIFY_ABAQUS_LAUNCHER", str(launcher))
    return TestClient(app, base_url="http://127.0.0.1")


def prepared(api, revision=None, two_panel=False):
    if revision is None:
        if two_panel:
            revision = api.post(
                "/api/projects",
                json={
                    "name": "Two panel",
                    "dimension": "2D",
                    "example": True,
                    "template": "two-panel",
                },
            ).json()
        else:
            revision = create_model(api, "One panel", example=True)
    mesh = prepare_mesh(api, revision)
    labels = api.post(
        "/api/meshes/" + mesh["id"] + "/fixture/edges", json={}
    ).json()["labels"]
    save_fixture(api, mesh["id"], labels)
    return revision, prepare_deck(api, revision, mesh["id"])


def run_with(api, revision, deck, name, marker):
    run = start_run(api, revision, deck, name=name)
    directory = store.job_dir(run["id"])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / marker).touch()
    return run


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_failed_solver_auto_salvages_and_packages_a_partial_result(
    monkeypatch, tmp_path
):
    launcher = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = prepared(api)
        run = run_with(api, revision, deck, "Failing solve", "fail-solver-with-odb")
        run_worker()
        job = store.job(run["id"])
        # A terminal solver failure queues exactly one extraction-only attempt.
        assert job["solver"] == "Failed"
        assert job["extraction"] == "Queued"
        assert job["salvage"] == 1
        assert job["ended"] is None
        run_worker()
        job = store.job(run["id"])
        assert job["solver"] == "Failed"
        assert job["extraction"] == "Succeeded"
        assert job["result_state"] == "partial"
        assert job["result"]["available"] is True
        summary = job["result"]["summary"]
        assert summary["availability"] == "partial"
        assert summary["solver_outcome"] == "Failed"
        assert summary["frames"] > 0
        assert job["status"] == "Failed"
        # The same API exposes the partial generation for display and download.
        assert api.get("/api/jobs/" + run["id"] + "/display-metadata").status_code == 200
        index = api.get("/api/jobs/" + run["id"] + "/artifacts/results.json")
        assert index.status_code == 200
        assert json.loads(index.text)["availability"] == "partial"
        # Solver, deck and mesh artifacts stay byte-identical.
        directory = store.job_dir(run["id"])
        before = {
            name: sha(directory / name)
            for name in ("analysis.inp", "mesh.json", "analysis.odb", "setup.json")
        }
        published = api.post(
            "/api/files/result/package",
            json={"job": run["id"], "folder": str(tmp_path)},
        )
        assert published.is_success, published.text
        path = Path(published.json()["path"])
        assert path.name.endswith("-partial.aqresult")
        after = {name: sha(directory / name) for name in before}
        assert after == before
        # A fresh data root reopens the same partial evidence without a solve.
        with api_for(monkeypatch, tmp_path / "fresh", launcher) as fresh:
            opened = fresh.post("/api/files/result/open", json={"path": str(path)})
            assert opened.is_success, opened.text
            reopened = opened.json()
            assert reopened["result_state"] == "partial"
            assert reopened["result"]["available"] is True
            assert reopened["result"]["summary"]["frames"] == summary["frames"]
            assert (
                fresh.get(
                    "/api/jobs/" + reopened["id"] + "/artifacts/results.json"
                ).status_code
                == 200
            )
            assert fresh.get("/api/jobs/" + reopened["id"] + "/display-metadata").status_code == 200


def test_two_panel_failure_before_closing_and_at_closing(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = prepared(api, two_panel=True)
        body_only = run_with(
            api, revision, deck, "Body seating fails", "partial-body-only"
        )
        (store.job_dir(body_only["id"]) / "fail-solver-with-odb").touch()
        run_worker()
        run_worker()
        job = store.job(body_only["id"])
        assert job["result_state"] == "partial"
        summary = job["result"]["summary"]
        assert summary["last_step"] == "Body seating"
        assert summary["last_role"] == "body"
        # No Closing frame was ever published.
        index = json.loads(
            (store.job_dir(body_only["id"]) / "results.json").read_text(encoding="utf-8")
        )
        assert all(frame["step_id"] != "closing" for frame in index["frames"])
        assert summary["last_local_s"] is not None
        assert summary["last_total_s"] is not None

        closing = run_with(
            api, revision, deck, "Closing fails", "partial-closing"
        )
        (store.job_dir(closing["id"]) / "fail-solver-with-odb").touch()
        run_worker()
        run_worker()
        later = store.job(closing["id"])
        assert later["result_state"] == "partial"
        closing_summary = later["result"]["summary"]
        assert closing_summary["last_step"] == "Closing"
        assert closing_summary["last_role"] == "door"
        # The last saved total time includes the completed Body seating step.
        assert closing_summary["last_total_s"] > closing_summary["last_local_s"]


def test_history_only_initial_only_and_unreadable_tail(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = prepared(api)
        cases = {
            "partial-history-only": {"history_only": True, "frames": 0},
            "partial-initial-only": {"initial_only": True},
            "partial-unreadable-last": {"skipped": 1},
        }
        for plan, expected in cases.items():
            run = run_with(api, revision, deck, plan, plan)
            (store.job_dir(run["id"]) / "fail-solver-with-odb").touch()
            run_worker()
            run_worker()
            job = store.job(run["id"])
            assert job["result_state"] == "partial", job["diagnostic"]
            summary = job["result"]["summary"]
            for key, value in expected.items():
                assert summary[key] == value, (plan, key, summary)
            assert api.get("/api/jobs/" + run["id"] + "/display-metadata").status_code == 200


def test_extraction_retry_never_relaunches_the_solver(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = prepared(api)
        run = run_with(api, revision, deck, "Retry extraction", "partial-closing")
        (store.job_dir(run["id"]) / "fail-solver-with-odb").touch()
        run_worker()
        run_worker()
        job = store.job(run["id"])
        assert job["result_state"] == "partial"
        directory = store.job_dir(run["id"])
        index_before = sha(directory / "results.json")
        frames_before = sorted(p.name for p in directory.glob("frame-*.json"))
        # One extraction attempt fails; the prior generation must stay readable.
        (directory / "fail-extract-once").touch()
        queued = api.post("/api/jobs/" + run["id"] + "/retry")
        assert queued.is_success, queued.text
        run_worker()
        failed = store.job(run["id"])
        assert failed["extraction"] == "Failed"
        assert failed["extraction_error"]
        assert failed["result_state"] == "partial"
        assert failed["result"]["available"] is True
        assert sha(directory / "results.json") == index_before
        assert sorted(p.name for p in directory.glob("frame-*.json")) == frames_before
        # Retry again succeeds and still never invokes the solver.
        recovered = api.post("/api/jobs/" + run["id"] + "/retry")
        assert recovered.is_success, recovered.text
        run_worker()
        final = store.job(run["id"])
        assert final["extraction"] == "Succeeded"
        assert final["result"]["available"] is True
        solver_log = (directory / "solver.log").read_text(encoding="utf-8", errors="replace")
        assert solver_log.count("Manufactured solver failure") == 1
        extract_log = (directory / "extract.log").read_text(encoding="utf-8", errors="replace")
        assert extract_log.count("Manufactured extraction failure") == 1


def test_no_odb_candidate_leaves_no_partial_and_no_solver_relaunch(
    monkeypatch, tmp_path
):
    launcher = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = prepared(api)
        run = run_with(api, revision, deck, "No saved ODB", "fail-solver")
        run_worker()
        job = store.job(run["id"])
        assert job["solver"] == "Failed"
        assert job["extraction"] == "Pending"
        assert job["result_state"] == "none"
        response = api.post("/api/jobs/" + run["id"] + "/extract")
        assert not response.is_success
        assert "ODB" in response.text or "native" in response.text.lower()


def test_duplicate_equal_time_frames_keep_ordinal_identity(tmp_path):
    from integrations.abaqus.interchange import finish, reset_staging, save_frame

    directory = tmp_path
    reset_staging(directory)
    result = {
        "mode": "ABAQUS",
        "notice": "MANUFACTURED TEST EVIDENCE",
        "frames": [],
        "history": [],
        "steps": [],
        "instances": [],
        "force_unit": "N",
    }
    for ordinal in range(3):
        save_frame(
            directory,
            result,
            {
                "time": 0.6 if ordinal else 0.0,
                "step": "Closing",
                "step_id": "closing",
                "frame_ordinal": ordinal,
                "step_frame_ordinal": ordinal,
                "step_ordinal": 0,
                "native_frame_id": 10 + ordinal,
                "increment": ordinal,
                "local_time": 0.6 if ordinal else 0.0,
                "total_time": 0.6 if ordinal else 0.0,
                "displacements": {},
                "fields": {},
            },
        )
    finish(directory, result, availability="partial")
    index = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    assert [frame["frame_ordinal"] for frame in index["frames"]] == [0, 1, 2]
    assert [frame["native_frame_id"] for frame in index["frames"]] == [10, 11, 12]
    assert index["frames"][1]["time"] == index["frames"][2]["time"] == 0.6
    assert index["last_frame_ordinal"] == 2
