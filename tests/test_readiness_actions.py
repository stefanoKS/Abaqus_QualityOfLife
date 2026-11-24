"""Action-specific readiness: Prepare versus Submit, and the v4 motion policy.

The reported failures were a reporting-width revert that disabled Prepare and a
valid positive-delta-Y motion rejected by the browser's legacy signed-travel
predicate. These tests exercise the server decision and the queued deck.
"""

import re

import pytest
from fastapi.testclient import TestClient

from services.api.main import app

from support import create_model, legacy_fixture, prepare_deck, prepare_mesh, save_fixture


def api_fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path / "data"))
    return TestClient(app, base_url="http://127.0.0.1")


def test_prepare_is_allowed_without_a_deck_and_submit_is_not(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as api:
        revision = create_model(api, "Readiness actions", example=True)
        mesh = prepare_mesh(api, revision)
        save_fixture(api, mesh["id"], legacy_fixture(api, mesh["id"])["labels"])

        document = api.get(f"/api/revisions/{revision['id']}/readiness").json()
        # Prepare depends only on engineering inputs.
        assert document["can_prepare"] is True
        assert document["setup_issues"] == []
        # Submit additionally needs the current prepared deck.
        assert document["can_submit"] is False
        assert [item["code"] for item in document["submit_issues"]] == ["deck.missing"]
        assert all("submit" in item["actions"] for item in document["submit_issues"])
        assert document["actions"]["prepare"]["allowed"] is True
        assert document["actions"]["submit"]["allowed"] is False
        assert document["stage_states"]["action"]["state"] == "incomplete"

        deck = prepare_deck(api, revision, mesh["id"])
        after = api.get(f"/api/revisions/{revision['id']}/readiness").json()
        assert after["can_submit"] is True
        assert after["actions"]["submit"]["allowed"] is True
        assert after["counts"]["deck"] == deck["id"]


def test_positive_delta_y_motion_from_below_is_valid_and_writes_the_deck(
    monkeypatch, tmp_path
):
    with api_fixture(monkeypatch, tmp_path) as api:
        created = api.post(
            "/api/projects",
            json={"name": "Positive delta Y", "example": True, "template": "two-panel"},
        ).json()
        setup = created["setup"]
        # The public template places the door above and the body below. Swap the
        # roles so the moving panel is the profile below the seal.
        for component in setup["components"]:
            if component["id"] == "panel":
                component["role"] = "vehicle_body"
            if component["id"] == "body":
                component["role"] = "moving_panel"
        setup["motion"]["stroke"] = 3.0
        setup["motion"]["angle"] = 90.0
        setup["motion"]["duration"] = 1.0
        setup["motion"]["body"]["stroke"] = 0.0
        setup["motion"]["body"]["angle"] = 0.0
        setup["motion"]["body"]["duration"] = 1.0
        saved = api.put(
            f"/api/projects/{created['project']}",
            json={"base": created["id"], "setup": setup},
        ).json()
        # Version 4 stores the signed Y component for old readers: +3, not -3.
        assert saved["setup"]["motion"]["travel"] == pytest.approx(3.0)
        assert saved["setup"]["analysis"]["mode"] == "body_then_door"

        mesh = prepare_mesh(api, saved)
        save_fixture(api, mesh["id"], legacy_fixture(api, mesh["id"])["labels"])
        document = api.get(f"/api/revisions/{saved['id']}/readiness").json()
        assert document["can_prepare"] is True, document["setup_issues"]
        assert not [
            item
            for item in document["findings"]
            if item["stage"] == "motion" and item["severity"] == "blocker"
        ]

        deck = prepare_deck(api, saved, mesh["id"])
        inp = api.get(f"/api/jobs/{deck['id']}/artifacts/analysis.inp").text
        assert re.search(r"PANEL_RP,\s*2,\s*2,\s*3(?:\.0*)?", inp)
        # The first (body-hold) step keeps true zeros and the second moves +3.
        assert "*Step, name=Body seating" in inp
        assert "*Step, name=Closing" in inp
        assert inp.count("PANEL_RP, 1, 2") >= 1


def test_a_mesh_only_readiness_document_keeps_legacy_signed_policy(monkeypatch, tmp_path):
    """A historical signed-travel revision is not judged by the v4 stroke rule."""
    with api_fixture(monkeypatch, tmp_path) as api:
        created = api.post(
            "/api/projects", json={"name": "Legacy motion", "example": False}
        ).json()
        # An empty model has no motion blocker, only the drawing blocker.
        document = api.get(f"/api/revisions/{created['id']}/readiness").json()
        assert document["state"] == "empty"
        assert [item["code"] for item in document["findings"]] == ["drawing.missing"]
        assert document["can_prepare"] is False


def test_correctable_prerequisites_are_incomplete_and_only_unsupported_3d_locks(
    monkeypatch, tmp_path
):
    """A padlock is a read-only restriction, not a missing input.

    The reported defect was a Components padlock beside an enabled role selector.
    Every role, mesh and mounting prerequisite is repaired by editing its own
    stage, so those stages must read ``incomplete`` with a reason. The deferred
    3D extrusion is the only genuine restriction in this phase.
    """
    with api_fixture(monkeypatch, tmp_path) as api:
        empty = api.post("/api/projects", json={"name": "Empty stage states"}).json()
        document = api.get(f"/api/revisions/{empty['id']}/readiness").json()
        assert document["stage_states"]["import"]["state"] == "incomplete"
        assert document["stage_states"]["mesh"]["state"] == "incomplete"
        assert document["stage_states"]["mesh"]["code"] == "drawing.missing"
        assert not [
            stage
            for stage, state in document["stage_states"].items()
            if state["state"] == "blocked" and stage in {"components", "materials", "mesh", "mounting"}
        ]

        created = create_model(api, "Role stage states", example=True)
        setup = created["setup"]
        for component in setup["components"]:
            component["role"] = "unassigned"
        saved = api.put(
            f"/api/projects/{created['project']}",
            json={"base": created["id"], "setup": setup},
        ).json()
        roles = api.get(f"/api/revisions/{saved['id']}/readiness").json()
        # Role and mesh prerequisites are correctable inputs, never a lock.
        assert roles["stage_states"]["components"]["state"] == "incomplete"
        assert roles["stage_states"]["components"]["code"].startswith("components.")
        assert roles["stage_states"]["mesh"]["state"] == "incomplete"
        # The blocker code names the missing artifact; the point is that the
        # stage is incomplete and repairable, never padlocked.
        assert roles["stage_states"]["mesh"]["code"] in {"mesh.missing", "components.roles"}
        assert roles["stage_states"]["mounting"]["state"] == "incomplete"
        assert roles["stage_states"]["mounting"]["code"] == "mounting.awaiting_mesh"
        assert roles["stage_states"]["motion"]["state"] != "blocked"
        assert roles["can_prepare"] is False

        three = api.post(
            "/api/projects",
            json={"name": "Deferred 3D", "example": True, "dimension": "3D"},
        ).json()
        deferred = api.get(f"/api/revisions/{three['id']}/readiness").json()
        # The only padlock in this phase is the deferred 3D extrusion preview.
        assert deferred["stage_states"]["import"]["state"] == "blocked"
        assert deferred["setup_issues"][0]["code"] == "drawing.extrusion_preview"
