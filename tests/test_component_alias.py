"""Component display names are aliases: persisted, display-only, never remesh.

``name`` stays the authoritative drawing/import label. ``alias`` is excluded
from the mesh-compatibility digest, so renaming a component must reuse geometry,
mesh and fixture and must not alter saved history.
"""

import json

import pytest
from fastapi.testclient import TestClient

from integrations.abaqus import deck, results
from packages import engineering
from packages.engineering.mesh import generate_mesh
from packages.engineering.model import Component, Project
from services import store
from services.api.main import app
from support import create_model, prepare_mesh


def test_alias_persists_and_keeps_mesh_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        revision = create_model(api, "Alias model", example=True)
        before = revision["mesh_compat"]
        setup = revision["setup"]
        panel = next(c for c in setup["components"] if c["role"] == "moving_panel")
        original_name = panel["name"]
        panel["alias"] = "Door · renamed"

        saved = api.put(
            f"/api/projects/{revision['project']}",
            json={"base": revision["id"], "setup": setup},
        ).json()
        stored = next(c for c in saved["setup"]["components"] if c["id"] == panel["id"])
        assert stored["alias"] == "Door · renamed"
        assert stored["name"] == original_name
        # Display-only: the mesh-determining digest is unchanged.
        assert saved["mesh_compat"] == before

        mesh = prepare_mesh(api, saved)
        project = Project.model_validate(saved["setup"])
        mesh_data = json.loads(
            (store.job_dir(mesh["id"]) / "mesh.json").read_text(encoding="utf-8")
        )
        nodes, ws, panel_elements = deck.mesh_parts(project, mesh_data)
        metadata = results._metadata(project, nodes, ws, panel_elements)
        assert metadata["closing"]["panel_name"] == "Door · renamed"
        # The stable CAD/component identity is untouched.
        assert metadata["closing"]["panel"] == panel["id"]


def test_a_reviewed_body_profile_is_excluded_not_a_failed_mesh():
    project = engineering.synthetic("Body excluded")
    project.components.append(
        Component(id="body", name="Body profile", alias="Body shell", role="vehicle_body")
    )
    mesh = generate_mesh(project)
    assert [row["component"] for row in mesh["excluded"]] == ["body"]
    assert "not analysed in this revision" in mesh["excluded"][0]["reason"]
    # An excluded component contributes no elements and does not make the mesh
    # fail; every produced element still belongs to an included component.
    body_elements = [e for e in mesh["elements"] if e["component"] == "body"]
    assert body_elements == []
    assert sum(mesh["counts"].values()) == len(mesh["elements"])


def test_historical_revision_keeps_its_own_alias(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        revision = create_model(api, "Alias history", example=True)
        setup = revision["setup"]
        panel = next(c for c in setup["components"] if c["role"] == "moving_panel")
        panel["alias"] = "First name"
        first = api.put(
            f"/api/projects/{revision['project']}",
            json={"base": revision["id"], "setup": setup},
        ).json()

        again = first["setup"]
        next(c for c in again["components"] if c["id"] == panel["id"])["alias"] = "Second name"
        second = api.put(
            f"/api/projects/{revision['project']}",
            json={"base": first["id"], "setup": again},
        ).json()
        assert second["number"] == first["number"] + 1

        original = api.get(f"/api/revisions/{first['id']}").json()
        assert next(c for c in original["setup"]["components"] if c["id"] == panel["id"])[
            "alias"
        ] == "First name"
