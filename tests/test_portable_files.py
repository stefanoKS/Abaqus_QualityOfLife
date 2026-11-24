"""Gate 6: folder-based portable model and result files.

Every write goes to a disposable data root and a temporary folder. The portable
files are reopened in a second, fresh data root to prove they do not depend on
the database or on an absolute path.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.engineering import portable
from services import store
from services.api.main import app
from support import create_model, prepared, run_worker, start_run

from fake_abaqus import install as install_fake_abaqus


def api_for(monkeypatch, data: Path, launcher=None):
    monkeypatch.setenv("SEAL_DATA", str(data))
    monkeypatch.setenv(
        "SIMPLIFY_ABAQUS_LAUNCHER",
        str(launcher or install_fake_abaqus(data.parent / "launcher")),
    )
    return TestClient(app, base_url="http://127.0.0.1")


def save_model(api, revision, path, **extra):
    return api.post(
        "/api/files/model/save",
        json={"revision": revision["id"], "path": str(path), **extra},
    )


def test_model_round_trip_after_moving_to_a_fresh_data_root(monkeypatch, tmp_path):
    launch = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "first", launch) as api:
        revision = create_model(api, "Portable model", example=True)
        original = revision["setup"]
        path = tmp_path / "folder" / "portable.aqmodel"
        saved = save_model(api, revision, path)
        assert saved.is_success, saved.text
        body = saved.json()
        assert body["path"].endswith(".aqmodel")
        assert body["members"] >= 2
        assert len(body["sha256"]) == 64
        assert path.is_file()

    # A fresh installation: new database directory, same file folder.
    with api_for(monkeypatch, tmp_path / "second", launch) as api:
        opened = api.post("/api/files/model/open", json={"path": str(path)})
        assert opened.is_success, opened.text
        restored = opened.json()
        assert restored["project"] not in (None, "")
        setup = restored["setup"]
        assert setup["name"] == original["name"]
        assert len(setup["edges"]) == len(original["edges"])
        assert len(setup["faces"]) == len(original["faces"])
        assert setup["source"]["kind"] == original["source"]["kind"]
        # The reopened model is editable and becomes a new independent head.
        head = api.get("/api/projects").json()
        assert any(row["id"] == restored["project"] for row in head)


def test_save_as_keeps_the_original_bytes_and_overwrite_is_explicit(monkeypatch, tmp_path):
    launch = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launch) as api:
        revision = create_model(api, "Save as model", example=True)
        first = tmp_path / "a.aqmodel"
        second = tmp_path / "b.aqmodel"
        one = save_model(api, revision, first)
        assert one.is_success, one.text
        original = first.read_bytes()
        two = save_model(api, revision, second)
        assert two.is_success, two.text
        # Save As created an independent copy and did not touch the original.
        assert first.read_bytes() == original
        assert second.read_bytes() != original

        # An external edit to the file is a conflict until overwrite is explicit.
        first.write_bytes(original + b"external")
        conflict = save_model(api, revision, first, base_sha=one.json()["sha256"])
        assert conflict.status_code == 409
        assert len(conflict.json()["currentSha"]) == 64
        forced = save_model(
            api, revision, first, base_sha=one.json()["sha256"], overwrite=True
        )
        assert forced.is_success, forced.text
        assert portable.read_container(first, portable.MODEL_KIND)["manifest"]["kind"] == (
            portable.MODEL_KIND
        )


def test_a_renamed_file_is_not_a_portable_container(monkeypatch, tmp_path):
    launch = install_fake_abaqus(tmp_path / "launch")
    fake = tmp_path / "fake.aqmodel"
    fake.write_text(json.dumps({"name": "not a container"}), encoding="utf-8")
    with api_for(monkeypatch, tmp_path / "data", launch) as api:
        response = api.post("/api/files/model/open", json={"path": str(fake)})
        assert not response.is_success
        assert "not a readable portable container" in response.text.lower()


def test_result_file_is_published_after_extraction_and_opens_read_only(
    monkeypatch, tmp_path
):
    launch = install_fake_abaqus(tmp_path / "launch")
    output = tmp_path / "results"
    output.mkdir()
    with api_for(monkeypatch, tmp_path / "first", launch) as api:
        revision = create_model(api, "Portable result", example=True)
        _, deck, _ = prepared(api, revision)
        run = start_run(api, revision, deck)
        # Capture the output folder at submit time, on the same job row.
        submitted = api.get("/api/jobs/" + run["id"]).json()
        assert submitted["output_dir"] is None
        run_worker()
        run_worker()
        completed = store.job(run["id"])
        assert completed["status"] == "Completed", completed["diagnostic"]
        packaged = api.post(
            "/api/files/result/package", json={"job": run["id"], "folder": str(output)}
        )
        assert packaged.is_success, packaged.text
        path = Path(packaged.json()["path"])
        assert path.is_file() and path.suffix == ".aqresult"
        index = json.loads((store.job_dir(run["id"]) / "results.json").read_text())
        frame_names = [frame["file"] for frame in index["frames"]]

    # A fresh installation opens only the result file and displays the evidence.
    with api_for(monkeypatch, tmp_path / "second", launch) as api:
        opened = api.post("/api/files/result/open", json={"path": str(path)})
        assert opened.is_success, opened.text
        job = opened.json()
        assert job["status"] == "Completed"
        assert job["scenario"] == "imported"
        assert job["publication"] == "Imported"
        stored = api.get("/api/jobs/" + job["id"] + "/artifacts/results.json")
        assert stored.is_success, stored.text
        restored = stored.json()
        assert [frame["file"] for frame in restored["frames"]] == frame_names
        for frame in frame_names:
            assert api.get(f"/api/jobs/{job['id']}/artifacts/{frame}").is_success
        assert api.get(f"/api/jobs/{job['id']}/artifacts/history.csv").is_success


def test_truncated_and_unsupported_result_files_leave_the_document_intact(
    monkeypatch, tmp_path
):
    launch = install_fake_abaqus(tmp_path / "launch")
    output = tmp_path / "results"
    output.mkdir()
    with api_for(monkeypatch, tmp_path / "data", launch) as api:
        revision = create_model(api, "Bad result", example=True)
        _, deck, _ = prepared(api, revision)
        run = start_run(api, revision, deck)
        run_worker()
        run_worker()
        packaged = api.post(
            "/api/files/result/package", json={"job": run["id"], "folder": str(output)}
        ).json()
        good = Path(packaged["path"]).read_bytes()

        truncated = tmp_path / "truncated.aqresult"
        truncated.write_bytes(good[: len(good) // 2])
        assert not api.post(
            "/api/files/result/open", json={"path": str(truncated)}
        ).is_success

        # Patch only the manifest version, leaving the members intact.
        import zipfile

        patched = tmp_path / "patched.aqresult"
        with zipfile.ZipFile(Path(packaged["path"])) as source, zipfile.ZipFile(
            patched, "w"
        ) as target:
            for info in source.infolist():
                payload = source.read(info.filename)
                if info.filename == "manifest.json":
                    manifest = json.loads(payload)
                    manifest["version"] = 99
                    payload = json.dumps(manifest).encode("utf-8")
                target.writestr(info.filename, payload)
        response = api.post("/api/files/result/open", json={"path": str(patched)})
        assert not response.is_success
        assert "version" in response.text.lower()
        # The original document is still open and untouched.
        assert api.get("/api/jobs/" + run["id"]).json()["status"] == "Completed"


def test_the_worker_publishes_two_distinct_results_without_a_browser(monkeypatch, tmp_path):
    launch = install_fake_abaqus(tmp_path / "launch")
    output = tmp_path / "auto"
    output.mkdir()
    with api_for(monkeypatch, tmp_path / "data", launch) as api:
        # Prepare both inputs first, so the queue holds only the two runs when the
        # worker starts (a queued run must not be claimed as someone's mesh).
        inputs = []
        for index in range(2):
            revision = create_model(api, f"Auto result {index}", example=True)
            _, deck, _ = prepared(api, revision)
            inputs.append((revision, deck))
        runs = []
        for index, (revision, deck) in enumerate(inputs):
            run = api.post(
                "/api/runs",
                json={
                    "revision": revision["id"],
                    "deck": deck["id"],
                    "token": store.new_id(),
                    "name": f"Auto run {index}",
                    "mode": "ABAQUS",
                    "cpus": 1,
                    "output_dir": str(output),
                },
            ).json()
            runs.append((run, revision))
        # The worker is the only actor from here: no browser request is needed.
        from services.worker.__main__ import once

        while once("portable"):
            pass
        files = []
        for run, _revision in runs:
            job = store.job(run["id"])
            assert job["status"] == "Completed", job["diagnostic"]
            log = store.job_dir(run["id"]) / "worker.log"
            assert job["publication"] == "Saved", (
                job.get("diagnostic") or "",
                log.read_text(encoding="utf-8", errors="replace")[-800:] if log.is_file() else "",
            )
            assert job["result_file"] and Path(job["result_file"]).is_file()
            files.append(job["result_file"])
        # Distinct collision-safe names, never replacing an earlier result.
        assert files[0] != files[1]
        assert len(list(output.glob("*.aqresult"))) == 2
        for path in files:
            assert portable.read_container(Path(path), portable.RESULT_KIND)["manifest"][
                "kind"
            ] == portable.RESULT_KIND


def test_failed_extraction_refuses_to_publish_a_result_file(monkeypatch, tmp_path):
    launch = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "data", launch) as api:
        revision = create_model(api, "No extraction", example=True)
        _, deck, _ = prepared(api, revision)
        run = start_run(api, revision, deck)
        run_worker()
        # Simulate a completed solve whose extraction failed without relaunching.
        with store.connection(True) as db:
            db.execute("UPDATE jobs SET extraction='Failed' WHERE id=?", (run["id"],))
        response = api.post(
            "/api/files/result/package",
            json={"job": run["id"], "folder": str(tmp_path)},
        )
        assert not response.is_success
        assert "extraction" in response.text.lower()
