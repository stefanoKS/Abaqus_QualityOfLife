"""Gate B: a compatible portable model keeps its mesh and reviewed fixture.

The file carries the exact mesh bytes, their identity record and the reviewed
fixed-node list. Reopening in a fresh data root must retain Prepare readiness
without another node selection, and a mismatched or truncated artifact must
never produce a silently valid fixture.
"""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient

from packages.engineering import portable
from services import store
from services.api.main import app
from support import (
    create_model,
    legacy_fixture,
    prepare_mesh,
    run_worker,
    save_fixture,
)

from fake_abaqus import install as install_fake_abaqus


def api_for(monkeypatch, data: Path, launcher):
    monkeypatch.setenv("SEAL_DATA", str(data))
    monkeypatch.setenv("SIMPLIFY_ABAQUS_LAUNCHER", str(launcher))
    return TestClient(app, base_url="http://127.0.0.1")


def tamper(source: Path, target: Path, changes: dict[str, bytes | None]) -> Path:
    """Rewrite a container with specific members replaced (``None`` removes one)."""
    container = portable.read_container(source, portable.MODEL_KIND)
    members = dict(container["members"])
    for name, payload in changes.items():
        if payload is None:
            members.pop(name, None)
        else:
            members[name] = payload
    portable.write_container(
        target, portable.MODEL_KIND, members, {"name": "tampered", "api": 3}
    )
    return target


@pytest.fixture()
def packaged(tmp_path, monkeypatch):
    launch = install_fake_abaqus(tmp_path / "launch")
    with api_for(monkeypatch, tmp_path / "first", launch) as api:
        revision = create_model(api, "Portable fixture", example=True)
        mesh = prepare_mesh(api, revision)
        labels = legacy_fixture(api, mesh["id"])["labels"][:37]
        save_fixture(api, mesh["id"], labels)
        assert store.fixture(mesh["id"])["count"] == 37
        path = tmp_path / "fixture.aqmodel"
        exported = api.post(
            "/api/files/model/save",
            json={"revision": revision["id"], "path": str(path)},
        )
        assert exported.is_success, exported.text
        assert exported.json()["members"] >= 4
    return {"path": path, "labels": sorted(labels), "launcher": launch}


def test_compatible_mesh_and_fixture_survive_a_fresh_data_root(
    packaged, tmp_path, monkeypatch
):
    assert packaged["path"].is_file()
    with api_for(monkeypatch, tmp_path / "second", packaged["launcher"]) as api:
        opened = api.post(
            "/api/files/model/open-info", json={"path": str(packaged["path"])}
        )
        assert opened.is_success, opened.text
        body = opened.json()
        assert body["restore"] == {
            "mesh": "restored",
            "fixture": "restored",
            # The synthetic example section has no original drawing to restore.
            "source": "absent",
            "items": [],
        }
        revision = body["revision"]
        document = api.get(f"/api/revisions/{revision['id']}/readiness").json()
        codes = {finding["code"] for finding in document["findings"]}
        assert "mesh.missing" not in codes
        assert "mounting.missing" not in codes
        reviewed = next(
            finding for finding in document["findings"] if finding["code"] == "mounting.reviewed"
        )
        assert reviewed["params"]["count"] == 37
        # Prepare is ready without selecting any node again; only the deck is new.
        assert document["can_prepare"] is True
        assert "deck.missing" in {
            finding["code"] for finding in document["actions"]["submit"]["issues"]
        }
        # The restored fixture is the packaged one, not a recomputed guess.
        fixtures = api.get("/api/meshes").json()
        assert fixtures and store.fixture(fixtures[0]["id"])["count"] == 37


def test_incompatible_mesh_requires_regeneration(packaged, tmp_path, monkeypatch):
    container = portable.read_container(packaged["path"], portable.MODEL_KIND)
    identity = json.loads(container["members"]["mesh-identity.json"])
    identity["compat"] = "0" * 64
    bad = tamper(
        packaged["path"],
        tmp_path / "incompatible.aqmodel",
        {"mesh-identity.json": json.dumps(identity).encode("utf-8")},
    )
    with api_for(monkeypatch, tmp_path / "third", packaged["launcher"]) as api:
        body = api.post("/api/files/model/open-info", json={"path": str(bad)}).json()
        assert body["restore"]["mesh"] == "incompatible"
        assert body["restore"]["fixture"] == "invalid"
        assert [item["code"] for item in body["restore"]["items"]] == [
            "portable.mesh_incompatible"
        ]
        document = api.get(f"/api/revisions/{body['revision']['id']}/readiness").json()
        assert "mesh.missing" in {finding["code"] for finding in document["findings"]}
        assert document["can_prepare"] is False


def test_truncated_mesh_is_not_adopted(packaged, tmp_path, monkeypatch):
    bad = tamper(
        packaged["path"],
        tmp_path / "truncated.aqmodel",
        {"mesh.json": b'{"nodes": [], "elements": []}'},
    )
    with api_for(monkeypatch, tmp_path / "fourth", packaged["launcher"]) as api:
        body = api.post("/api/files/model/open-info", json={"path": str(bad)}).json()
        assert body["restore"]["mesh"] == "invalid"
        assert body["restore"]["items"][0]["code"] == "portable.mesh_empty"
        fixtures = api.get("/api/meshes").json()
        assert fixtures == []


def test_fixture_from_another_mesh_is_rejected(packaged, tmp_path, monkeypatch):
    container = portable.read_container(packaged["path"], portable.MODEL_KIND)
    fixture = json.loads(container["members"]["fixture.json"])
    fixture["mesh_digest"] = "f" * 64
    bad = tamper(
        packaged["path"],
        tmp_path / "wrong-fixture.aqmodel",
        {"fixture.json": json.dumps(fixture).encode("utf-8")},
    )
    with api_for(monkeypatch, tmp_path / "fifth", packaged["launcher"]) as api:
        body = api.post("/api/files/model/open-info", json={"path": str(bad)}).json()
        assert body["restore"]["mesh"] == "restored"
        assert body["restore"]["fixture"] == "invalid"
        assert body["restore"]["items"][0]["code"] == "portable.fixture_invalid"
        document = api.get(f"/api/revisions/{body['revision']['id']}/readiness").json()
        codes = {finding["code"] for finding in document["findings"]}
        assert "mounting.missing" in codes
        assert document["can_prepare"] is False


def test_mesh_without_identity_is_not_trusted(packaged, tmp_path, monkeypatch):
    bad = tamper(
        packaged["path"],
        tmp_path / "no-identity.aqmodel",
        {"mesh-identity.json": None},
    )
    with api_for(monkeypatch, tmp_path / "sixth", packaged["launcher"]) as api:
        body = api.post("/api/files/model/open-info", json={"path": str(bad)}).json()
        assert body["restore"]["mesh"] == "invalid"
        assert body["restore"]["items"][0]["code"] == "portable.mesh_identity_missing"


def test_original_drawing_is_restored_with_the_container(tmp_path, monkeypatch):
    """An imported drawing travels with the file and comes back byte-identical."""
    import ezdxf

    launch = install_fake_abaqus(tmp_path / "launch")
    drawing = tmp_path / "section.dxf"
    document = ezdxf.new("R2010", units=4)
    document.modelspace().add_lwpolyline([(0, 0), (20, 0), (20, 10), (0, 10)], close=True)
    document.saveas(drawing)
    original = drawing.read_bytes()
    packaged_path = tmp_path / "drawing.aqmodel"
    with api_for(monkeypatch, tmp_path / "source-root", launch) as api:
        revision = create_model(api, "Imported drawing", example=False)
        upload = api.post(
            "/api/projects/" + revision["project"] + "/drawing",
            data={"base": revision["id"], "units": "N-mm-s-tonne"},
            files={"file": ("section.dxf", original)},
        )
        assert upload.is_success, upload.text
        run_worker("import-test")
        imported = api.get(
            "/api/jobs/" + upload.json()["id"] + "/imported"
        ).raise_for_status().json()
        exported = api.post(
            "/api/files/model/save",
            json={"revision": imported["id"], "path": str(packaged_path)},
        )
        assert exported.is_success, exported.text

    with api_for(monkeypatch, tmp_path / "fresh-root", launch) as api:
        body = api.post(
            "/api/files/model/open-info", json={"path": str(packaged_path)}
        ).json()
        assert body["restore"]["source"] == "restored"
        reopened = api.get("/api/revisions/" + body["revision"]["id"] + "/drawing")
        assert reopened.is_success, reopened.text
        assert reopened.content == original
