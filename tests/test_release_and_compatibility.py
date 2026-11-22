"""Matched browser/API releases, compatibility refusal and atomic creation.

These tests are license-free and use a disposable SQLite/artifact directory. The
release tests operate on temporary build trees; nothing here touches the live
``dist`` directory or the publisher's data root.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services import release, store
from services.api.main import app
from support import create_model, legacy_fixture, prepare_mesh, prepared, save_fixture

ROOT = Path(__file__).resolve().parents[1]


def publish(web: Path, release_id: str, entry: str, api: int = 3):
    dist = web / "dist"
    directory = web / "releases" / release_id
    (directory / "assets").mkdir(parents=True)
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (directory / "index.html").write_text(
        f'<script type="module" src="/assets/{entry}"></script>', encoding="utf-8"
    )
    (directory / "assets" / entry).write_text(f"// {release_id}", encoding="utf-8")
    (dist / "release.json").write_text(
        json.dumps({"id": release_id, "entry": entry, "css": "", "api": api}),
        encoding="utf-8",
    )
    return directory


def test_release_is_pinned_and_a_later_build_does_not_replace_it(tmp_path):
    web = tmp_path / "web"
    first = publish(web, "aaaaaaaaaaaa", "index-A.js")
    pinned = release.resolve(web)
    assert pinned.id == "aaaaaaaaaaaa"
    assert pinned.entry == "index-A.js"
    assert pinned.legacy is False

    publish(web, "bbbbbbbbbbbb", "index-B.js")
    later = release.resolve(web)
    assert later.id == "bbbbbbbbbbbb"

    # The release object the running API holds still points at A's files.
    assert pinned.directory == first
    assert (pinned.directory / "assets" / pinned.entry).read_text(encoding="utf-8") == "// aaaaaaaaaaaa"
    assert later.id != pinned.id


def test_release_without_a_manifest_reports_itself_legacy(tmp_path):
    web = tmp_path / "web"
    dist = web / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<script type="module" src="/assets/index-OLD.js"></script>', encoding="utf-8"
    )
    found = release.resolve(web)
    assert found.legacy is True
    assert found.entry == "index-OLD.js"
    assert found.directory == dist


def test_health_reports_the_pinned_release_and_api_generation(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        payload = api.get("/api/health").json()
    assert payload["api"] == 3
    assert payload["release"]
    assert payload["frontend"]
    assert payload["data"] == store.data_identity()
    assert payload["status"] == "ready"


def test_a_tab_from_a_different_release_cannot_write(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        stale = api.post(
            "/api/projects",
            json={"name": "Refused", "example": False},
            headers={"X-Abaqus-QOL-Client": "index-OLD.js", "X-Abaqus-QOL-Api": "3"},
        )
        assert stale.status_code == 409
        assert "different release" in stale.json()["detail"]

        wrong_api = api.post(
            "/api/projects",
            json={"name": "Refused", "example": False},
            headers={"X-Abaqus-QOL-Api": "99"},
        )
        assert wrong_api.status_code == 409
        assert "does not match" in wrong_api.json()["detail"]

        # An unidentified script keeps the original contract.
        allowed = api.post("/api/projects", json={"name": "Allowed", "example": False})
        assert allowed.status_code == 200


def test_create_project_group_is_idempotent_and_never_orphans(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    token = "11111111-1111-4111-8111-111111111111"
    body = {"name": "5q45", "model_name": "Door A", "example": False, "token": token}
    with TestClient(app, base_url="http://127.0.0.1") as api:
        first = api.post("/api/project-groups", json=body)
        assert first.status_code == 201
        again = api.post("/api/project-groups", json=body)
        assert again.status_code == 201
        one, two = first.json(), again.json()
        assert one["group"]["id"] == two["group"]["id"]
        assert one["model"]["id"] == two["model"]["id"]
        assert one["model"]["project"] == two["model"]["project"]
        assert len(api.get("/api/groups").json()) == 1
        assert len(api.get("/api/projects").json()) == 1
        assert api.get("/api/projects").json()[0]["group"] == one["group"]["id"]

        # A different token is a different user action and creates a new pair.
        other = dict(body, token="22222222-2222-4222-8222-222222222222")
        third = api.post("/api/project-groups", json=other)
        assert third.json()["group"]["id"] != one["group"]["id"]


def test_a_failed_first_model_leaves_no_empty_group(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    token = "33333333-3333-4333-8333-333333333333"

    def explode(*args, **kwargs):
        raise RuntimeError("simulated write failure after the group insert")

    with TestClient(
        app, base_url="http://127.0.0.1", raise_server_exceptions=False
    ) as api:
        monkeypatch.setattr(store, "append_revision", explode)
        failed = api.post(
            "/api/project-groups",
            json={"name": "Broken", "model_name": "Door", "token": token},
        )
        assert failed.status_code == 500
        assert api.get("/api/groups").json() == []
        assert api.get("/api/projects").json() == []


def test_readiness_of_an_empty_model_points_at_import(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        revision = api.post("/api/projects", json={"name": "Empty", "example": False}).json()
        readiness = api.get(f"/api/revisions/{revision['id']}/readiness").json()
    assert readiness["state"] == "empty"
    assert readiness["first_blocker"]["code"] == "drawing.missing"
    assert readiness["first_blocker"]["stage"] == "import"
    assert readiness["next_action"] == {"stage": "import", "action": "import"}
    assert readiness["number"] == revision["number"]


def test_readiness_never_reuses_a_mesh_after_mesh_inputs_change(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    monkeypatch.setenv("SIMPLIFY_ABAQUS_LAUNCHER", str(tmp_path / "fake.bat"))
    (tmp_path / "fake.bat").write_text("@echo off\n", encoding="utf-8")
    with TestClient(app, base_url="http://127.0.0.1") as api:
        revision = create_model(api, "Section", example=True)
        blocked = api.get(f"/api/revisions/{revision['id']}/readiness").json()
        assert blocked["state"] == "blocked"
        assert blocked["first_blocker"]["code"] in {"mesh.missing", "mounting.missing"}
        assert "mesh.missing" in {f["code"] for f in blocked["findings"]}

        prepared(api, revision)
        ready = api.get(f"/api/revisions/{revision['id']}/readiness").json()
        assert ready["state"] == "ready", ready["findings"]
        assert ready["first_blocker"] is None
        assert ready["counts"]["fixture_count"] > 0
        assert ready["counts"]["deck"]

        # A mesh-control change makes the previous mesh incompatible. Readiness
        # must fall back to Mesh even though an older mesh still exists. 0.75 is
        # deliberately different from the 0.5 mm new-model default.
        setup = dict(revision["setup"])
        setup["mesh"] = dict(setup["mesh"], size=0.75)
        changed = api.put(
            f"/api/projects/{revision['project']}",
            json={"base": revision["id"], "setup": setup},
        )
        assert changed.status_code == 200, changed.text
        after = api.get(f"/api/revisions/{changed.json()['id']}/readiness").json()
        assert after["state"] == "blocked"
        codes = {f["code"] for f in after["findings"]}
        assert "mesh.missing" in codes
        assert after["first_blocker"]["stage"] == "mesh"


def test_missing_or_corrupt_active_mesh_names_the_recovery(monkeypatch, tmp_path):
    """Readiness, deck preparation and the history agree about a broken mesh."""
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    monkeypatch.setenv("SIMPLIFY_ABAQUS_LAUNCHER", str(tmp_path / "fake.bat"))
    (tmp_path / "fake.bat").write_text("@echo off\n", encoding="utf-8")
    with TestClient(app, base_url="http://127.0.0.1") as api:
        revision = create_model(api, "Broken mesh", example=True)
        _, deck_job, mesh = prepared(api, revision)
        ready = api.get(f"/api/revisions/{revision['id']}/readiness").json()
        assert ready["state"] == "ready", ready["findings"]
        mesh_id = ready["counts"]["mesh"]
        fixture_hash = ready["counts"]["fixture_hash"]
        artifact = store.job_dir(mesh_id) / "mesh.json"
        original = artifact.read_bytes()
        payload = {
            "revision": revision["id"],
            "mesh": mesh_id,
            "fixture_hash": fixture_hash,
            "token": store.new_id(),
        }

        artifact.unlink()
        missing = api.get(f"/api/revisions/{revision['id']}/readiness").json()
        assert missing["first_blocker"]["code"] == "mesh.artifact_missing"
        assert missing["first_blocker"]["stage"] == "mesh"
        assert missing["first_blocker"]["artifact"] == "mesh:" + mesh_id
        refused = api.post("/api/decks", json=payload)
        assert refused.status_code == 409, refused.text
        assert "mesh file is missing" in refused.text

        artifact.write_text("{not a mesh", encoding="utf-8")
        corrupt = api.get(f"/api/revisions/{revision['id']}/readiness").json()
        assert corrupt["first_blocker"]["code"] == "mesh.artifact_corrupt"
        refused = api.post("/api/decks", json=payload)
        assert refused.status_code == 409, refused.text
        assert "unreadable" in refused.text

        # Historical decks and their completed jobs remain readable; the broken
        # active mesh is not silently replaced or removed.
        assert api.get(f"/api/jobs/{deck_job['id']}").json()["status"] == "Completed"
        artifact.write_bytes(original)

def test_a_stale_fixture_and_a_stale_deck_are_rejected_without_mutation(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        revision = create_model(api, "Two tabs", example=True)
        mesh = prepare_mesh(api, revision)
        labels = legacy_fixture(api, mesh["id"])["labels"]
        first = save_fixture(api, mesh["id"], labels)
        stale = first["fixture"]["hash"]
        assert stale

        # Another tab saves a different reviewed set.
        other = labels[: max(1, len(labels) - 1)]
        changed = api.put(
            f"/api/meshes/{mesh['id']}/fixture",
            json={"labels": other, "expected_hash": stale},
        )
        assert changed.status_code == 200, changed.text
        current = store.fixture(mesh["id"])
        assert current["hash"] != stale

        # The first tab's save is now stale: refuse it and leave the store alone.
        refused = api.put(
            f"/api/meshes/{mesh['id']}/fixture",
            json={"labels": labels, "expected_hash": stale},
        )
        assert refused.status_code == 409
        assert "changed by another tab" in refused.json()["detail"]
        assert store.fixture(mesh["id"])["hash"] == current["hash"]
        assert store.fixture(mesh["id"])["labels"] == other

        # A deck prepared from the stale reviewed fixture must not enqueue.
        stale_deck = api.post(
            "/api/decks",
            json={
                "revision": revision["id"],
                "token": store.new_id(),
                "mesh": mesh["id"],
                "fixture_hash": stale,
            },
        )
        assert stale_deck.status_code == 409
        assert "changed after you reviewed" in stale_deck.json()["detail"]
        assert [j for j in api.get("/api/decks").json() if j["revision"] == revision["id"]] == []

        # The current fixture prepares normally.
        ok = api.post(
            "/api/decks",
            json={
                "revision": revision["id"],
                "token": store.new_id(),
                "mesh": mesh["id"],
                "fixture_hash": current["hash"],
            },
        )
        assert ok.status_code == 200, ok.text
