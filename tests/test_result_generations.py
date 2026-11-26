"""Immutable result generations: publication, pinning and recovery.

Manufactured evidence only: the launcher double writes labelled synthetic
results; no solver, license or ODB is involved.
"""

import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

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


def api_for(monkeypatch, data, launcher):
    monkeypatch.setenv("SEAL_DATA", str(data))
    monkeypatch.setenv("SIMPLIFY_ABAQUS_LAUNCHER", str(launcher))
    monkeypatch.setenv("ABAQUS_QOL_FAKE_EXTRACT_SECONDS", "0")
    return TestClient(app, base_url="http://127.0.0.1")


def one_panel(api, name="Generation"):
    revision = create_model(api, name, example=True)
    mesh = prepare_mesh(api, revision)
    labels = api.post("/api/meshes/" + mesh["id"] + "/fixture/edges", json={}).json()["labels"]
    save_fixture(api, mesh["id"], labels)
    return revision, prepare_deck(api, revision, mesh["id"])


def partial_job(api, revision, deck, plan, name, extra=()):
    run = start_run(api, revision, deck, name=name)
    directory = Path(store.job_dir(run["id"]))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "fail-solver-with-odb").touch()
    (directory / plan).touch()
    for marker in extra:
        (directory / marker).touch()
    return run, directory


def published(jid):
    base, generation = store.result_generation_dir(jid)
    return Path(base), generation


def generation_dirs(jid):
    root = Path(store.job_dir(jid)) / "results"
    return sorted(p.name for p in root.glob("gen-*")) if root.is_dir() else []


def test_retry_pins_reads_to_the_previous_generation(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = one_panel(api)
        run, directory = partial_job(api, revision, deck, "partial-initial-only", "Pinned")
        run_worker()
        run_worker()
        jid = run["id"]
        job = store.job(jid)
        assert job["result"]["generation"] == 1
        assert job["result"]["dir"].startswith("results/gen-1-")
        base, _ = published(jid)
        old_index = (base / "results.json").read_bytes()
        old_frame = (base / "frame-00000.json").read_bytes()
        old_history = (base / "history.csv").read_bytes()
        assert json.loads(old_index)["last_step"] == "Closing"

        # A deliberately slow retry that really reuses frame-00000 with a
        # different payload and changes the frame count and history.
        monkeypatch.setenv("ABAQUS_QOL_FAKE_EXTRACT_SECONDS", "3")
        (directory / "partial-initial-only").unlink()
        (directory / "partial-closing").touch()
        (directory / "mutate-overlap").touch()
        queued = api.post("/api/jobs/" + jid + "/retry")
        assert queued.is_success, queued.text
        with ThreadPoolExecutor(1) as pool:
            work = pool.submit(run_worker)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and store.job(jid)["extraction"] != "Running":
                time.sleep(0.02)
            assert store.job(jid)["extraction"] == "Running"
            # Every multi-request read stays on generation 1 while the retry runs.
            assert api.get(f"/api/jobs/{jid}/results/1/results.json").content == old_index
            assert api.get(f"/api/jobs/{jid}/results/1/frame-00000.json").content == old_frame
            assert api.get(f"/api/jobs/{jid}/results/1/history.csv").content == old_history
            assert api.get("/api/jobs/" + jid + "/artifacts/results.json").content == old_index
            assert api.get("/api/jobs/" + jid + "/display-metadata").status_code == 200
            assert api.get(f"/api/jobs/{jid}/results/1/display-metadata").status_code == 200
            assert api.get(f"/api/jobs/{jid}/results/2/results.json").status_code == 404
            work.result(timeout=60)

        job = store.job(jid)
        assert job["result"]["generation"] == 2
        assert job["result"]["summary"]["frames"] == 3
        second = Path(store.job_dir(jid)) / job["result"]["dir"]
        assert (second / "frame-00000.json").read_bytes() != old_frame
        assert (second / "history.csv").read_bytes() != old_history
        # The prior generation is still complete and byte-identical.
        old, _ = store.result_generation_dir(jid, 1)
        assert (Path(old) / "results.json").read_bytes() == old_index
        assert (Path(old) / "frame-00000.json").read_bytes() == old_frame
        assert api.get(f"/api/jobs/{jid}/results/1/results.json").content == old_index

        solver_log = (directory / "solver.log").read_text(encoding="utf-8", errors="replace")
        assert solver_log.count("Manufactured solve started") == 1


def test_fenced_publish_keeps_the_previous_generation(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = one_panel(api)
        run, _directory = partial_job(api, revision, deck, "partial-closing", "Fenced")
        run_worker()
        run_worker()
        jid = run["id"]
        base, _ = published(jid)
        old_index = (base / "results.json").read_bytes()

        original = store.publish_result_generation
        fence = {"on": True}

        def maybe_fence(*args, **kwargs):
            if fence["on"]:
                return "generation"
            return original(*args, **kwargs)

        monkeypatch.setattr(store, "publish_result_generation", maybe_fence)
        assert api.post("/api/jobs/" + jid + "/retry").is_success
        run_worker()
        job = store.job(jid)
        # The attempt is rejected as superseded; no newer generation exists.
        assert job["extraction"] == "Failed"
        assert job["result"]["generation"] == 1
        assert job["result"]["available"] is True
        assert generation_dirs(jid) == [base.name]
        assert (base / "results.json").read_bytes() == old_index
        assert api.get(f"/api/jobs/{jid}/results/2/results.json").status_code == 404

        # A later retry is still possible and publishes generation 2.
        fence["on"] = False
        assert api.post("/api/jobs/" + jid + "/retry").is_success
        run_worker()
        assert store.job(jid)["result"]["generation"] == 2
        assert len(generation_dirs(jid)) == 2


def test_cancelled_retry_keeps_the_previous_generation(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = one_panel(api)
        run, _directory = partial_job(api, revision, deck, "partial-closing", "Cancel retry")
        run_worker()
        run_worker()
        jid = run["id"]
        base, _ = published(jid)
        old_index = (base / "results.json").read_bytes()

        monkeypatch.setenv("ABAQUS_QOL_FAKE_EXTRACT_SECONDS", "3")
        assert api.post("/api/jobs/" + jid + "/retry").is_success
        with ThreadPoolExecutor(1) as pool:
            work = pool.submit(run_worker)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and store.job(jid)["extraction"] != "Running":
                time.sleep(0.02)
            time.sleep(0.2)
            assert api.post("/api/jobs/" + jid + "/cancel").is_success
            work.result(timeout=60)
        job = store.job(jid)
        assert job["extraction"] == "Cancelled"
        assert job["result"]["generation"] == 1
        assert job["result"]["available"] is True
        assert generation_dirs(jid) == [base.name]
        assert (base / "results.json").read_bytes() == old_index

        # A deliberate later Retry is still possible.
        monkeypatch.setenv("ABAQUS_QOL_FAKE_EXTRACT_SECONDS", "0")
        assert api.post("/api/jobs/" + jid + "/retry").is_success
        run_worker()
        assert store.job(jid)["result"]["generation"] == 2


def test_legacy_flat_row_stays_readable(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = one_panel(api)
        run, _directory = partial_job(api, revision, deck, "partial-closing", "Legacy")
        run_worker()
        run_worker()
        jid = run["id"]
        directory = Path(store.job_dir(jid))
        flat_index = (directory / "results.json").read_bytes()
        with store.connection(True) as db:
            db.execute(
                "UPDATE jobs SET result_generation=0,result_dir=NULL WHERE id=?", (jid,)
            )
        job = store.job(jid)
        assert job["result"]["generation"] == 0
        assert job["result"]["dir"] == ""
        assert job["result"]["base"] == ""
        assert api.get("/api/jobs/" + jid + "/artifacts/results.json").content == flat_index
        assert api.get("/api/jobs/" + jid + "/display-metadata").status_code == 200
        assert api.get(f"/api/jobs/{jid}/results/1/results.json").status_code == 404


def test_pre_generation_flat_row_keeps_its_published_generation(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = one_panel(api)
        run, _directory = partial_job(api, revision, deck, "partial-closing", "Old flat")
        run_worker()
        run_worker()
        jid = run["id"]
        directory = Path(store.job_dir(jid))
        flat_index = (directory / "results.json").read_bytes()
        flat_frame = (directory / "frame-00000.json").read_bytes()
        # Emulate a row written before generation directories: only the flat
        # files exist, while the row still says generation 1.
        shutil.rmtree(directory / "results")
        with store.connection(True) as db:
            db.execute(
                "UPDATE jobs SET result_generation=1,result_dir=NULL WHERE id=?", (jid,)
            )
        assert api.get(f"/api/jobs/{jid}/results/1/results.json").content == flat_index

        # The first new publication snapshots that exact generation before the
        # flat mirror moves to generation 2.
        assert api.post("/api/jobs/" + jid + "/retry").is_success
        run_worker()
        job = store.job(jid)
        assert job["result"]["generation"] == 2
        old, generation = store.result_generation_dir(jid, 1)
        assert generation == 1
        assert Path(old).name.startswith("gen-1-")
        assert (Path(old) / "results.json").read_bytes() == flat_index
        assert (Path(old) / "frame-00000.json").read_bytes() == flat_frame
        assert api.get(f"/api/jobs/{jid}/results/1/results.json").content == flat_index


def test_crash_between_finalize_and_commit_leaves_a_safe_candidate(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = one_panel(api)
        run, _directory = partial_job(api, revision, deck, "partial-closing", "Crash")
        run_worker()
        run_worker()
        jid = run["id"]
        base, _ = published(jid)
        old_index = (base / "results.json").read_bytes()

        def crash(*_args, **_kwargs):
            # Simulate a worker crash after the directory was finalized but
            # before the durable pointer transaction.
            raise KeyboardInterrupt()

        monkeypatch.setattr(store, "publish_result_generation", crash)
        assert api.post("/api/jobs/" + jid + "/retry").is_success
        with pytest.raises(KeyboardInterrupt):
            run_worker()

        job = store.job(jid)
        assert job["result"]["generation"] == 1
        assert job["result"]["available"] is True
        assert (base / "results.json").read_bytes() == old_index
        assert api.get(f"/api/jobs/{jid}/results/1/results.json").content == old_index
        # The finalized candidate exists but is not referenced by the pointer.
        unreferenced = [
            name for name in generation_dirs(jid) if name.startswith("gen-2-")
        ]
        assert len(unreferenced) == 1
        candidate = Path(store.job_dir(jid)) / "results" / unreferenced[0]
        assert (candidate / "results.json").is_file()
        assert (candidate / "summary.json").is_file()
        assert api.get(f"/api/jobs/{jid}/results/2/results.json").status_code == 404


def test_failed_retry_keeps_the_previous_generation(monkeypatch, tmp_path):
    launcher = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = one_panel(api)
        run, directory = partial_job(api, revision, deck, "partial-closing", "Failed retry")
        run_worker()
        run_worker()
        jid = run["id"]
        base, _ = published(jid)
        old_index = (base / "results.json").read_bytes()
        (directory / "fail-extract-once").touch()
        assert api.post("/api/jobs/" + jid + "/retry").is_success
        run_worker()
        job = store.job(jid)
        assert job["extraction"] == "Failed"
        assert job["result"]["generation"] == 1
        assert generation_dirs(jid) == [base.name]
        assert api.get(f"/api/jobs/{jid}/results/1/results.json").content == old_index
        # A deliberate later retry succeeds and publishes generation 2.
        assert api.post("/api/jobs/" + jid + "/retry").is_success
        run_worker()
        assert store.job(jid)["result"]["generation"] == 2


def test_package_pins_the_published_generation(monkeypatch, tmp_path):
    from packages.engineering import portable

    launcher = install_fake_abaqus(tmp_path / "launch")
    output = tmp_path / "out"
    output.mkdir()
    with api_for(monkeypatch, tmp_path / "data", launcher) as api:
        revision, deck = one_panel(api)
        run, _directory = partial_job(api, revision, deck, "partial-closing", "Package")
        run_worker()
        run_worker()
        jid = run["id"]
        base, _ = published(jid)
        index_sha = store.digest(base / "results.json")
        packaged = api.post(
            "/api/files/result/package", json={"job": jid, "folder": str(output)}
        )
        assert packaged.is_success, packaged.text
        path = Path(packaged.json()["path"])
        container = portable.read_container(path, portable.RESULT_KIND)
        provenance = json.loads(container["members"]["provenance.json"])
        assert provenance["result"]["generation"] == 1
        assert provenance["result"]["result_dir"].startswith("results/gen-1-")
        assert provenance["result"]["index_sha256"] == index_sha
        assert provenance["job"]["extraction"] == "Succeeded"

    # A fresh data root opens the packaged generation read-only and pinned.
    with api_for(monkeypatch, tmp_path / "fresh", launcher) as fresh:
        opened = fresh.post("/api/files/result/open", json={"path": str(path)})
        assert opened.is_success, opened.text
        job = opened.json()
        assert job["result"]["generation"] == 1
        assert job["result"]["dir"].startswith("results/gen-1-")
        assert fresh.get(f"/api/jobs/{job['id']}/results/1/results.json").status_code == 200
        assert fresh.get(f"/api/jobs/{job['id']}/results/1/frame-00000.json").status_code == 200
