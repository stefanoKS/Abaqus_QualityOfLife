"""Archive, restore and safe permanent deletion for models and project groups.

Ordinary deletion is a reversible tombstone. Permanent deletion is explicit,
blocked while work is active, journals its artifact cleanup, and never removes
shared drawings or library materials.
"""

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages import engineering
from services import store
from services.api.main import app
from support import create_model, prepared


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        yield api


def create_group(api, name):
    return api.post("/api/groups", json={"name": name}).json()


def test_archive_and_restore_a_model_keeps_history_readable(client, tmp_path):
    revision = create_model(client, "Archive model", example=True)
    _, deck, _ = prepared(client, revision)
    artifact = f"/api/jobs/{deck['id']}/artifacts/analysis.inp"
    assert client.get(artifact).status_code == 200

    archived = client.post(f"/api/projects/{revision['project']}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert client.get("/api/projects").json() == []
    listed = client.get("/api/projects?include_archived=true").json()
    assert [row["id"] for row in listed] == [revision["project"]]
    # Historical evidence stays readable and downloadable.
    assert client.get(f"/api/revisions/{revision['id']}").status_code == 200
    assert client.get(artifact).status_code == 200
    # Archived means read-only: no new setup, import, mesh, deck or run.
    setup = revision["setup"]
    assert (
        client.put(
            f"/api/projects/{revision['project']}",
            json={"base": revision["id"], "setup": setup},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/meshes", json={"revision": revision["id"], "token": store.new_id()}
        ).status_code
        == 409
    )

    restored = client.post(f"/api/projects/{revision['project']}/restore")
    assert restored.json()["archived"] is False
    assert [row["id"] for row in client.get("/api/projects").json()] == [revision["project"]]
    assert (
        client.put(
            f"/api/projects/{revision['project']}",
            json={"base": revision["id"], "setup": setup},
        ).status_code
        == 200
    )


def test_archive_and_restore_a_project_group(client):
    group = create_group(client, "Archive project")
    revision = create_model(client, "Group model", example=True, group=group["id"])
    archived = client.post(f"/api/groups/{group['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    assert client.get("/api/projects").json() == []
    assert client.get("/api/groups").json() == []
    visible = client.get("/api/groups?include_archived=true").json()
    assert visible[0]["archived"] is True
    assert [row["id"] for row in visible[0]["models"]] == [revision["project"]]
    # A model cannot be added to an archived project.
    added = client.post(
        "/api/projects",
        json={"name": "Nope", "group": group["id"], "example": False},
    )
    assert added.status_code == 409
    assert client.get(f"/api/revisions/{revision['id']}").status_code == 200

    restored = client.post(f"/api/groups/{group['id']}/restore")
    assert restored.json()["archived"] is False
    assert len(client.get("/api/projects").json()) == 1


def test_archiving_one_duplicate_leaves_the_other_independent(client):
    revision = create_model(client, "Original", example=True)
    copy = client.post(f"/api/projects/{revision['project']}/duplicate", json={}).json()
    assert copy["project"] != revision["project"]
    client.post(f"/api/projects/{revision['project']}/archive")
    visible = client.get("/api/projects").json()
    assert [row["id"] for row in visible] == [copy["project"]]
    assert client.get(f"/api/revisions/{copy['id']}").status_code == 200


def test_permanent_delete_is_blocked_by_active_work(client):
    revision = create_model(client, "Busy model", example=True)
    job = client.post(
        "/api/meshes", json={"revision": revision["id"], "token": store.new_id()}
    ).json()
    assert job["status"] == "Queued"
    client.post(f"/api/projects/{revision['project']}/archive")
    info = client.get(f"/api/projects/{revision['project']}/deletion-info").json()
    assert info["deletable"] is False
    assert info["active_jobs"]
    refused = client.post(
        f"/api/projects/{revision['project']}/delete", json={"confirm": "Busy model"}
    )
    assert refused.status_code == 409
    assert "active or unresolved" in refused.json()["detail"]
    assert client.get(f"/api/jobs/{job['id']}").status_code == 200


def test_permanent_delete_requires_confirmation_and_removes_artifacts(client, tmp_path):
    revision = create_model(client, "Permanent model", example=True)
    _, deck, mesh = prepared(client, revision)
    job_dirs = [store.job_dir(mesh["id"]), store.job_dir(deck["id"])]
    assert all(path.exists() for path in job_dirs)
    client.post(f"/api/projects/{revision['project']}/archive")

    wrong = client.post(
        f"/api/projects/{revision['project']}/delete", json={"confirm": "wrong name"}
    )
    assert wrong.status_code == 409
    assert client.get(f"/api/revisions/{revision['id']}").status_code == 200

    deleted = client.post(
        f"/api/projects/{revision['project']}/delete",
        json={"confirm": revision["setup"]["name"]},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["cleanup"] == "done"
    assert client.get(f"/api/revisions/{revision['id']}").status_code == 404
    assert client.get(f"/api/jobs/{mesh['id']}").status_code == 404
    assert all(not path.exists() for path in job_dirs)
    assert client.get("/api/projects?include_archived=true").json() == []


def test_shared_drawing_and_library_material_survive_a_model_purge(client, tmp_path):
    setup = engineering.synthetic("Shared drawing").model_dump(mode="json")
    source = store.new_id()
    directory = store.root() / "drawings" / source
    directory.mkdir(parents=True)
    (directory / "drawing.dxf").write_text("0\n", encoding="utf-8")
    setup["source"] = {
        "kind": "dxf",
        "filename": "drawing.dxf",
        "digest": "a" * 64,
        "drawing_units": "millimetres",
    }
    first = store.save(setup, source_id=source)
    copy = client.post(f"/api/projects/{first['project']}/duplicate", json={}).json()
    assert copy["source_id"] == source

    material = client.post(
        "/api/materials",
        json={
            "name": "Shared EPDM",
            "card": {
                "model": "linear_elastic",
                "color": "#336655",
                "density": 1.1e-9,
                "young": 5,
                "poisson": 0.49,
                "test_data": [],
            },
        },
    ).json()

    client.post(f"/api/projects/{first['project']}/archive")
    deleted = client.post(
        f"/api/projects/{first['project']}/delete", json={"confirm": "Shared drawing"}
    )
    assert deleted.status_code == 200, deleted.text
    # The duplicated model still references the drawing directory.
    assert directory.exists()
    assert client.get(f"/api/revisions/{copy['id']}").status_code == 200
    assert any(row["id"] == material["id"] for row in client.get("/api/materials").json())

    # Deleting the sibling releases the last reference and removes the directory.
    client.post(f"/api/projects/{copy['project']}/archive")
    client.post(
        f"/api/projects/{copy['project']}/delete", json={"confirm": copy["setup"]["name"]}
    )
    assert not directory.exists()


def test_interrupted_cleanup_is_recovered_on_next_start(client, monkeypatch):
    revision = create_model(client, "Interrupted", example=True)
    _, deck, mesh = prepared(client, revision)
    client.post(f"/api/projects/{revision['project']}/archive")
    job_dir = store.job_dir(mesh["id"])

    def fail(path):
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr(store, "_safe_remove_job", fail)
    result = client.post(
        f"/api/projects/{revision['project']}/delete",
        json={"confirm": revision["setup"]["name"]},
    )
    assert result.status_code == 200
    assert result.json()["cleanup"] == "pending"
    assert job_dir.exists()

    # The database rows are gone, so the journal can finish the artifact cleanup.
    monkeypatch.setattr(
        store, "_safe_remove_job", lambda job_id: __import__("shutil").rmtree(store.job_dir(job_id))
    )
    store.recover_deletions()
    assert not job_dir.exists()
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM deletions").fetchone()[0] == 0


def test_a_pending_journal_without_a_committed_delete_changes_nothing(client):
    revision = create_model(client, "No delete", example=True)
    job = client.post(
        "/api/meshes", json={"revision": revision["id"], "token": store.new_id()}
    ).json()
    token = store.new_id()
    store._write_journal(
        token,
        "model",
        revision["project"],
        {"jobs": [job["id"]], "sources": []},
        "pending",
    )
    store.recover_deletions()
    assert client.get(f"/api/revisions/{revision['id']}").status_code == 200
    with store.connection() as db:
        assert (
            db.execute("SELECT 1 FROM deletions WHERE token=?", (token,)).fetchone() is None
        )


def test_an_unarchived_model_can_be_deleted_directly(client):
    revision = create_model(client, "Direct delete", example=True)
    name = revision["setup"]["name"]
    result = client.post(
        f"/api/projects/{revision['project']}/delete", json={"confirm": name}
    )
    assert result.status_code == 200, result.text
    assert result.json()["cleanup"] == "done"
    assert client.get(f"/api/revisions/{revision['id']}").status_code == 404
    assert client.get("/api/projects?include_archived=true").json() == []


def test_an_unarchived_mixed_group_deletes_its_children(client):
    group = create_group(client, "Mixed group")
    first = create_model(client, "Mixed one", example=True, group=group["id"])
    second = create_model(client, "Mixed two", example=True, group=group["id"])
    client.post(f"/api/projects/{first['project']}/archive")
    info = client.get(f"/api/groups/{group['id']}/deletion-info").json()
    assert info["models"] == 2
    assert info["deletable"] is True
    result = client.post(
        f"/api/groups/{group['id']}/delete", json={"confirm": "Mixed group"}
    )
    assert result.status_code == 200, result.text
    assert result.json()["removed_models"] == 2
    assert client.get("/api/groups?include_archived=true").json() == []
    assert client.get("/api/projects?include_archived=true").json() == []


def test_revised_deletion_scope_is_refused_before_execution(client):
    group = create_group(client, "Scope group")
    create_model(client, "Scope one", example=True, group=group["id"])
    preview = client.get(f"/api/groups/{group['id']}/deletion-info").json()
    create_model(client, "Scope two", example=True, group=group["id"])
    refused = client.post(
        f"/api/groups/{group['id']}/delete",
        json={"confirm": "Scope group", "expected_models": preview["models"]},
    )
    assert refused.status_code == 409
    assert "impact changed" in refused.json()["detail"]
    # Nothing was removed, and the revised scope is still visible.
    assert len(client.get("/api/groups").json()) == 1
    assert len(client.get("/api/projects").json()) == 2


def test_enqueue_that_loses_the_race_cannot_join_a_deleted_model(client, monkeypatch):
    revision = create_model(client, "Race delete", example=True)
    errors = []
    deleted = []
    inside = threading.Event()
    writer_started = threading.Event()
    original = store._unsafe_rows

    def gate(db, project_ids):
        # The deleting write transaction is already open. Let the test start a
        # competing enqueue only now, so that it must block on the write lock.
        inside.set()
        writer_started.wait(5)
        return original(db, project_ids)

    monkeypatch.setattr(store, "_unsafe_rows", gate)

    def enqueue():
        writer_started.set()
        try:
            store.submit(
                revision["id"], "Racing mesh", "MESH", store.new_id(), compat="racing"
            )
        except Exception as error:  # noqa: BLE001 - the failure mode is the assertion
            errors.append(error)

    def delete():
        deleted.append(
            store.purge_project(revision["project"], revision["setup"]["name"])
        )

    remover = threading.Thread(target=delete)
    remover.start()
    assert inside.wait(5), "the deleting transaction never started"
    writer = threading.Thread(target=enqueue)
    writer.start()
    remover.join(10)
    writer.join(10)
    assert not remover.is_alive() and not writer.is_alive()
    assert deleted and deleted[0]["cleanup"] == "done"
    assert errors, "the competing enqueue must not silently succeed"
    assert isinstance(errors[0], (KeyError, store.Conflict))
    with store.connection() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM jobs WHERE revision=?", (revision["id"],)
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute(
                "SELECT COUNT(*) FROM projects WHERE id=?", (revision["project"],)
            ).fetchone()[0]
            == 0
        )


def test_a_group_membership_change_after_preview_is_refused(client):
    group = create_group(client, "Membership group")
    create_model(client, "Membership one", example=True, group=group["id"])
    preview = client.get(f"/api/groups/{group['id']}/deletion-info").json()
    create_model(client, "Membership two", example=True, group=group["id"])
    refused = client.post(
        f"/api/groups/{group['id']}/delete",
        json={
            "confirm": "Membership group",
            "expected_models": preview["models"],
            "expected_revisions": preview["revisions"],
            "expected_jobs": preview["jobs"],
        },
    )
    assert refused.status_code == 409
    assert len(client.get("/api/projects").json()) == 2
    # The group itself is intact and can be deleted once the user re-confirms.
    assert len(client.get("/api/groups").json()) == 1
