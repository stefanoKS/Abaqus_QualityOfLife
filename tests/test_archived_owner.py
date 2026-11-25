"""Gate A: standalone file ownership and the archived migration group.

Reproduces the operator's configuration: the historical ``Imported projects``
group is archived. A newly created or opened file document must still be
independently editable, the archived history must stay untouched, and the
internal file owner must not be reachable through the user archive/delete
controls. Every database is disposable.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.engineering import portable
from packages.engineering.geometry import synthetic
from services import portable_files, store
from services.api.main import app


def api_fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path / "data"))
    return TestClient(app, base_url="http://127.0.0.1")


def archive_migration_group():
    """Archive the historical migration group exactly as the operator has it."""
    with store.connection(True) as db:
        gid = store.legacy_group(db)
        db.execute("UPDATE groups SET archived=1 WHERE id=?", (gid,))
    return gid


def edit_width(api, revision, width=111.0):
    setup = json.loads(json.dumps(revision["setup"]))
    setup["analysis"]["reporting_width"] = width
    return api.put(
        "/api/projects/" + revision["project"],
        json={"base": revision["id"], "setup": setup},
    )


def test_empty_installation_creates_an_editable_file_document(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as api:
        assert api.get("/api/groups").json() == []
        assert api.get("/api/projects").json() == []
        revision = api.post("/api/projects", json={"name": "First file"}).json()
        assert revision["archived"] is False
        assert revision["group_archived"] is False
        assert revision["group_name"] == store.FILE_GROUP_NAME
        assert edit_width(api, revision).is_success
        # A restart re-initializes the same data root without changing ownership.
        store.initialize()
        again = api.get("/api/revisions/" + revision["id"]).json()
        assert again["group"] == revision["group"]
        assert again["group_archived"] is False
        head = store.revision(store.head_revision(revision["project"]))
        assert edit_width(api, head).is_success


def test_new_file_is_editable_while_the_migration_group_is_archived(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as api:
        legacy = archive_migration_group()
        created = api.post("/api/projects", json={"name": "Standalone file"})
        assert created.is_success, created.text
        revision = created.json()
        # Both archive flags the workspace honours are false, so no banner and an
        # enabled Save: the head owns itself rather than the archived history.
        assert revision["archived"] is False
        assert revision["group_archived"] is False
        assert revision["group"] and revision["group"] != legacy
        assert revision["group_name"] == store.FILE_GROUP_NAME
        assert store.project_locked(revision["project"]) is False

        saved = edit_width(api, revision)
        assert saved.is_success, saved.text
        assert saved.json()["setup"]["analysis"]["reporting_width"] == pytest.approx(111.0)
        # The archived migration group stays archived and unchanged.
        assert store.group_archived(legacy) is True


def test_file_created_before_the_group_was_archived_stays_editable(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as api:
        first = api.post("/api/projects", json={"name": "Earlier file"}).json()
        archive_migration_group()
        assert edit_width(api, first).is_success
        # A file opened afterwards is also independent of the archived history.
        second = api.post("/api/projects", json={"name": "Later file"}).json()
        assert second["group_archived"] is False
        assert edit_width(api, second).is_success


def test_opened_portable_file_is_editable_while_the_migration_group_is_archived(
    monkeypatch, tmp_path
):
    with api_fixture(monkeypatch, tmp_path) as api:
        source = api.post("/api/projects", json={"name": "Portable", "example": True}).json()
        target = tmp_path / "portable.aqmodel"
        assert portable_files.save_model(source["id"], str(target))["bytes"] > 0
        archive_migration_group()

        opened = api.post("/api/files/model/open-info", json={"path": str(target)})
        assert opened.is_success, opened.text
        payload = opened.json()
        revision = payload["revision"]
        assert revision["archived"] is False
        assert revision["group_archived"] is False
        assert revision["project"] != source["project"]
        assert edit_width(api, revision).is_success


def test_explicit_creation_in_the_archived_group_is_still_rejected(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as api:
        legacy = archive_migration_group()
        refused = api.post(
            "/api/projects", json={"name": "Stranded", "group": legacy, "example": True}
        )
        assert refused.status_code == 409
        assert "archived" in refused.text
        # A direct store call is refused inside the same write transaction too.
        with pytest.raises(store.Conflict):
            store.save(synthetic("Direct").model_dump(mode="json"), group=legacy)


def test_archived_model_history_stays_read_only(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as api:
        group = store.create_group("Household")["id"]
        model = api.post(
            "/api/projects", json={"name": "Archive me", "group": group, "example": True}
        ).json()
        assert store.set_group_archived(group, True)["archived"] is True
        locked = edit_width(api, model)
        assert locked.status_code == 409
        assert store.project_locked(model["project"]) is True


def test_internal_owner_is_single_under_concurrent_creation(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as api:
        archive_migration_group()
        results: list[int] = []

        def create():
            results.append(api.post("/api/projects", json={"name": "Concurrent"}).status_code)

        threads = [threading.Thread(target=create) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert results == [200] * 8
        with store.connection() as db:
            internal = db.execute("SELECT id FROM groups WHERE internal=1").fetchall()
            named = db.execute(
                "SELECT id FROM groups WHERE name=?", (store.FILE_GROUP_NAME,)
            ).fetchall()
            owned = db.execute(
                "SELECT COUNT(*) FROM projects WHERE group_id=?", (internal[0]["id"],)
            ).fetchone()[0]
        assert len(internal) == 1
        assert len(named) == 1
        assert owned == 8


def test_internal_owner_cannot_be_archived_or_deleted(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as api:
        revision = api.post("/api/projects", json={"name": "Owned"}).json()
        internal = revision["group"]
        assert api.post(f"/api/groups/{internal}/archive").status_code == 409
        assert api.post(f"/api/groups/{internal}/delete", json={"confirm": "x"}).status_code == 409
        assert store.group_archived(internal) is False
        # The individual document remains deletable, so nothing is trapped.
        info = api.get(f"/api/projects/{revision['project']}/deletion-info").json()
        assert info["deletable"] is True


def test_same_name_groups_do_not_decide_file_ownership(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as api:
        with store.connection(True) as db:
            for _ in range(2):
                db.execute(
                    "INSERT INTO groups(id,name,created,archived,internal) VALUES (?,?,?,1,0)",
                    (store.new_id(), store.LEGACY_GROUP_NAME, store.time.time()),
                )
        revision = api.post("/api/projects", json={"name": "Name independent"}).json()
        assert revision["group_name"] == store.FILE_GROUP_NAME
        assert revision["group_archived"] is False
        assert edit_width(api, revision).is_success


def test_recovery_creates_a_distinct_editable_identity(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as api:
        group = store.create_group("Old household")["id"]
        original = api.post(
            "/api/projects", json={"name": "Stranded", "group": group, "example": True}
        ).json()
        store.set_group_archived(group, True)
        recovered = api.post(f"/api/projects/{original['project']}/recover")
        assert recovered.status_code == 201, recovered.text
        copy = recovered.json()
        assert copy["project"] != original["project"]
        assert copy["id"] != original["id"]
        assert copy["archived"] is False
        assert copy["group_archived"] is False
        assert copy["group_name"] == store.FILE_GROUP_NAME
        assert store.project_locked(copy["project"]) is False
        assert edit_width(api, copy).is_success
        # The original history, its revision and its archive state are untouched.
        assert store.project_locked(original["project"]) is True
        history = api.get(f"/api/projects/{original['project']}/revisions").json()
        assert len(history) == 1


def test_duplicate_of_a_stranded_model_is_editable(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as api:
        group = store.create_group("Archived household")["id"]
        original = api.post(
            "/api/projects", json={"name": "Stranded copy", "group": group, "example": True}
        ).json()
        store.set_group_archived(group, True)
        duplicate = api.post(f"/api/projects/{original['project']}/duplicate", json={})
        assert duplicate.is_success, duplicate.text
        body = duplicate.json()
        assert body["project"] != original["project"]
        assert body["group_archived"] is False
        assert edit_width(api, body).is_success


def test_recovery_of_an_active_model_keeps_its_group(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as api:
        group = store.create_group("Active household")["id"]
        original = api.post(
            "/api/projects", json={"name": "Active", "group": group, "example": True}
        ).json()
        recovered = api.post(f"/api/projects/{original['project']}/recover").json()
        assert recovered["group"] == group
        assert recovered["project"] != original["project"]
