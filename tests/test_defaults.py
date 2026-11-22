"""New-model defaults and version-1 compatibility.

Version 2 sets a 0.5 mm global mesh size and a 1.0 s new step. A stored
version-1 payload whose defaulted fields were omitted must keep its original
effective 1.0 mm / 1.3 s values, and explicitly saved values are never
rewritten.
"""

from fastapi.testclient import TestClient

from packages import engineering
from packages.engineering.model import MeshSpec, Project
from services.api.main import app


def legacy_payload():
    payload = engineering.synthetic("Legacy defaults").model_dump(mode="json")
    payload["schema_version"] = 1
    payload["mesh"].pop("size", None)
    payload["motion"].pop("duration", None)
    payload["motion"]["body"].pop("duration", None)
    return payload


def test_new_models_use_the_milestone_defaults():
    for project in (engineering.empty("Blank"), engineering.synthetic("Example")):
        assert project.schema_version == 2
        assert project.mesh.size == 0.5
        assert project.motion.duration == 1.0
        assert project.motion.body.duration == 1.0
    # A named example that intentionally specifies a control keeps it.
    explicit = engineering.synthetic("Explicit example")
    explicit.mesh = MeshSpec(size=1.5)
    assert Project.model_validate(explicit.model_dump(mode="json")).mesh.size == 1.5


def test_version_1_payload_keeps_its_original_defaults():
    project = Project.model_validate(legacy_payload())
    assert project.mesh.size == 1.0
    assert project.motion.duration == 1.3
    assert project.motion.body.duration == 1.0
    # Saving a new revision writes the effective values explicitly; re-reading
    # them never applies the version-2 defaults.
    again = Project.model_validate(project.model_dump(mode="json"))
    assert again.mesh.size == 1.0
    assert again.motion.duration == 1.3


def test_version_1_explicit_values_are_never_rewritten():
    payload = legacy_payload()
    payload["mesh"]["size"] = 0.25
    payload["motion"]["duration"] = 2.5
    payload["motion"]["body"]["duration"] = 0.75
    project = Project.model_validate(payload)
    assert project.mesh.size == 0.25
    assert project.motion.duration == 2.5
    assert project.motion.body.duration == 0.75


def test_api_creation_and_duplication_keep_effective_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        revision = api.post(
            "/api/projects", json={"name": "Default model", "example": False}
        ).json()
        setup = revision["setup"]
        assert setup["schema_version"] == 2
        assert setup["mesh"]["size"] == 0.5
        assert setup["motion"]["duration"] == 1.0
        assert setup["motion"]["body"]["duration"] == 1.0

        # An older client omitted the defaulted fields and declared v1.
        legacy = dict(setup)
        legacy["schema_version"] = 1
        legacy["mesh"] = {k: v for k, v in setup["mesh"].items() if k != "size"}
        legacy["motion"] = {
            k: v for k, v in setup["motion"].items() if k != "duration"
        }
        saved = api.put(
            f"/api/projects/{revision['project']}",
            json={"base": revision["id"], "setup": legacy},
        )
        assert saved.status_code == 200, saved.text
        stored = saved.json()["setup"]
        assert stored["mesh"]["size"] == 1.0
        assert stored["motion"]["duration"] == 1.3

        duplicate = api.post(f"/api/projects/{revision['project']}/duplicate").json()
        assert duplicate["setup"]["mesh"]["size"] == 1.0
        assert duplicate["setup"]["motion"]["duration"] == 1.3


def test_two_panel_template_is_explicit_and_reproducible(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        revision = api.post(
            "/api/projects",
            json={"name": "Two panel", "example": True, "template": "two-panel"},
        ).json()
        setup = revision["setup"]
        assert setup["analysis"]["mode"] == "body_then_door"
        assert setup["schema_version"] == 2
        assert setup["mesh"]["size"] == 0.5
        assert setup["motion"]["body"]["travel"] == 5.0
        assert setup["motion"]["body"]["duration"] == 1.0
        # The historical two-panel scenario keeps its explicit 1.3 s door step.
        assert setup["motion"]["duration"] == 1.3
        roles = [component["role"] for component in setup["components"]]
        assert roles.count("vehicle_body") == 1
        assert roles.count("moving_panel") == 1

        # The default example is still the hollow bulb without a body.
        hollow = api.post(
            "/api/projects", json={"name": "Hollow", "example": True}
        ).json()
        assert hollow["setup"]["analysis"]["mode"] == "door_only"
        assert "vehicle_body" not in [
            component["role"] for component in hollow["setup"]["components"]
        ]
