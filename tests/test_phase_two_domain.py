"""Phase-two domain contracts: contact pairs, oblique motion, reporting width.

Unit-level and deck-generation checks only; no solver is launched. The licensed
counterpart is recorded separately in docs/engineering-validation.md.
"""

import math

import pytest

from integrations.abaqus import deck, interchange, results
from integrations.abaqus.deck import ClearanceError
from packages import engineering
from packages.engineering import motion as motion_policy
from packages.engineering.mesh import generate_mesh
from packages.engineering.model import Analysis, Contact, Project
from packages.engineering.roles import derive_mode, findings


def labels_for(project, mesh):
    from packages.engineering import fixture as fixtures

    selection = next(item for item in project.selections if item.id == project.mounting.selection)
    return fixtures.from_edges(mesh, selection.entities)


@pytest.fixture
def rigid():
    project = engineering.synthetic("Domain")
    mesh = generate_mesh(project)
    return project, mesh, labels_for(project, mesh)


def test_new_contact_coefficients_are_independent_and_named(rigid):
    project, mesh, labels = rigid
    project.contact.door_seal = 0.17
    project.contact.body_seal = 0.43
    project.contact.seal_self = 0.81
    text = deck.write_inp(project, mesh, labels)
    assert "*Surface Interaction, name=DOOR_SEAL" in text
    assert "*Surface Interaction, name=SEAL_SELF" in text
    assert "*Surface Interaction, name=BODY_SEAL" not in text  # no body participates
    assert "*Contact Inclusions" in text
    assert "ASSEMBLY_WS-1_SEAL_EXTERIOR, ASSEMBLY_PANEL-1_PANEL_FACE" in text
    assert "ASSEMBLY_WS-1_SEAL_EXTERIOR, ASSEMBLY_WS-1_SEAL_EXTERIOR" in text
    # Door/body rigid-to-rigid contact is not part of the declared domain.
    assert "PANEL_FACE, BODY_FACE" not in text
    blocks = text.split("*Surface Interaction, name=")
    door_block = next(block for block in blocks if block.startswith("DOOR_SEAL"))
    self_block = next(block for block in blocks if block.startswith("SEAL_SELF"))
    assert "\n0.17\n" in door_block.split("*Contact")[0]
    assert "\n0.81\n" in self_block.split("*Contact")[0]
    assert "*Contact Property Assignment\nASSEMBLY_WS-1_SEAL_EXTERIOR, ASSEMBLY_PANEL-1_PANEL_FACE, DOOR_SEAL" in text


def test_zero_coefficient_stays_frictionless(rigid):
    project, mesh, labels = rigid
    project.contact.door_seal = 0.0
    text = deck.write_inp(project, mesh, labels)
    block = text.split("*Surface Interaction, name=DOOR_SEAL")[1].split("*Contact")[0]
    assert "*Friction, slip tolerance=0.005\n0\n" in block


def test_two_step_declares_the_body_pair(rigid):
    project, mesh, _ = rigid
    two = engineering.two_panel_section("Two", body_y=-1.0, body_travel=5.0)
    mesh = generate_mesh(two)
    labels = labels_for(two, mesh)
    two.contact.door_seal = 0.17
    two.contact.body_seal = 0.43
    two.contact.seal_self = 0.81
    text = deck.write_inp(two, mesh, labels)
    assert "*Surface Interaction, name=BODY_SEAL" in text
    assert "ASSEMBLY_WS-1_SEAL_EXTERIOR, ASSEMBLY_BODY-1_BODY_FACE" in text
    assert "ASSEMBLY_WS-1_SEAL_EXTERIOR, ASSEMBLY_BODY-1_BODY_FACE, BODY_SEAL" in text
    body_block = text.split("*Surface Interaction, name=BODY_SEAL")[1].split("*Contact")[0]
    assert "\n0.43\n" in body_block


def test_legacy_scalar_friction_keeps_its_exact_effect(rigid):
    project, mesh, labels = rigid
    payload = project.model_dump(mode="json")
    payload["schema_version"] = 3
    payload["contact"] = {"normal": "hard", "scope": "all_exterior", "friction": 0.42}
    legacy = Project.model_validate(payload)
    text = deck.write_inp(legacy, mesh, labels)
    assert "*Surface Interaction, name=SEAL_CONTACT" in text
    assert "*Contact Inclusions, all exterior" in text
    assert "\n0.42\n" in text
    assert "*Surface Interaction, name=DOOR_SEAL" not in text

    # An explicitly zero legacy coefficient must not become the 0.7 default.
    payload["contact"]["friction"] = 0.0
    zero = Project.model_validate(payload)
    zero_text = deck.write_inp(zero, mesh, labels)
    assert "*Friction, slip tolerance=0.005\n0\n" in zero_text

    # An omitted legacy coefficient is backfilled to its historical 0.3.
    payload["contact"].pop("friction")
    omitted = Project.model_validate(payload)
    assert omitted.contact.friction == 0.3


def test_oblique_motion_writes_both_components(rigid):
    project, mesh, labels = rigid
    project.motion.angle = math.degrees(math.atan2(-0.8, 0.6))
    project.motion.stroke = 5.0
    text = deck.write_inp(project, mesh, labels)
    assert "PANEL_RP, 1, 1, 3" in text
    assert "PANEL_RP, 2, 2, -4" in text
    resolved = motion_policy.resolve(project.motion, 4)
    assert resolved["delta"] == pytest.approx([3.0, -4.0], abs=1e-9)
    assert text.count("PANEL_RP, 1, 1") == 1
    # The rigid rotation is still restrained and the prescribed path is explicit.
    assert "PANEL_RP, 6, 6" in text


def test_oblique_metadata_projects_both_components(rigid):
    project, mesh, labels = rigid
    project.motion.angle = math.degrees(math.atan2(-0.8, 0.6))
    project.motion.stroke = 5.0
    nodes, ws, panel, body = deck._mesh_parts(project, mesh)
    metadata = results._metadata(project, nodes, ws, panel, labels, body)
    closing = metadata["closing"]
    assert closing["direction"] == pytest.approx([0.6, -0.8], abs=1e-9)
    assert closing["delta_mm"] == pytest.approx([3.0, -4.0], abs=1e-9)
    assert closing["distance_mm"] == pytest.approx(5.0)
    assert metadata["reporting_width_mm"] == 100.0
    assert metadata["thickness_mm"] == 1.0
    assert metadata["force_basis"] == "total_width"


def test_legacy_vertical_motion_migrates_without_rewriting(rigid):
    project, mesh, labels = rigid
    payload = project.model_dump(mode="json")
    payload["schema_version"] = 3
    payload["motion"] = {
        "axis": "Y",
        "travel": -6.5,
        "offset": 0.0,
        "duration": 1.2,
        "body": {"travel": 0.0, "offset": 0.0, "duration": 1.0},
    }
    legacy = Project.model_validate(payload)
    assert legacy.motion.travel == -6.5
    resolved = motion_policy.resolve(legacy.motion, 3)
    assert resolved["angle"] == -90.0
    assert resolved["stroke"] == 6.5
    assert resolved["delta"] == [0.0, -6.5]
    text = deck.write_inp(legacy, mesh, labels)
    assert "PANEL_RP, 2, 2, -6.5" in text
    assert "PANEL_RP, 1, 1" not in text  # legacy deck keeps its single Y BC

    payload["motion"]["travel"] = 0.0
    hold = Project.model_validate(payload)
    hold_text = deck.write_inp(hold, mesh, labels)
    assert "PANEL_RP, 2, 2, 0" in hold_text


def test_oblique_path_that_misses_is_reported_not_invented(rigid):
    project, mesh, labels = rigid
    # Aim the door sideways so its swept path never meets the seal.
    project.motion.angle = 0.0
    project.motion.stroke = 5.0
    with pytest.raises(ClearanceError) as error:
        deck.write_inp(project, mesh, labels)
    assert error.value.code in {"no_x_overlap", "motion_away"}


def test_reporting_width_scales_force_once():
    metadata = {
        "thickness": 1.0,
        "thickness_mm": 1.0,
        "reporting_width_mm": 100.0,
        "reporting_width_basis": "default_100_mm",
        "force_basis": "total_width",
        "force_normalization": "total",
        "closing": {"direction": [0.6, -0.8]},
    }
    series = {
        "U1": {0.0: 0.0, 1.0: 3.0},
        "U2": {0.0: 0.0, 1.0: -4.0},
        "RF1": {0.0: 0.0, 1.0: 3.0},
        "RF2": {0.0: 0.0, 1.0: -4.0},
    }
    rows = interchange.align_histories(series, metadata, step="Closing")
    assert rows[0]["displacement"] == pytest.approx(0.0, abs=1e-12)
    assert rows[-1]["displacement"] == pytest.approx(5.0)
    # (RF . d) = 3*0.6 + (-4)(-0.8) = 5 N; total = 5 * 100 / 1 = 500 N.
    assert rows[-1]["total_force_N"] == pytest.approx(5.0)
    assert rows[-1]["force"] == pytest.approx(500.0)
    # The displacement magnitude is sqrt(3^2 + 4^2) = 5 mm, not the projection.
    assert math.hypot(rows[-1]["u1"], rows[-1]["u2"]) == pytest.approx(5.0)

    # Reversing the measured reaction reverses the signed displayed force.
    reversed_series = {
        **series,
        "RF1": {0.0: 0.0, 1.0: -3.0},
        "RF2": {0.0: 0.0, 1.0: 4.0},
    }
    flipped = interchange.align_histories(reversed_series, metadata, step="Closing")
    assert flipped[-1]["force"] == pytest.approx(-500.0)

    # Per-length basis is (RF . d)/t_s.
    per_mm = {**metadata, "force_basis": "per_mm", "force_normalization": "per_mm"}
    rows_mm = interchange.align_histories(series, per_mm, step="Closing")
    assert rows_mm[-1]["force"] == pytest.approx(5.0)

    # Legacy t_s = 2 mm with a known 100 mm basis: 10 N projected -> 500 N.
    legacy = {
        "thickness": 2.0,
        "thickness_mm": 2.0,
        "reporting_width_mm": 100.0,
        "reporting_width_basis": "legacy_thickness",
        "force_basis": "total_width",
        "force_normalization": "total",
        "closing": {"direction": [1.0, 0.0]},
    }
    legacy_rows = interchange.align_histories(
        {"U1": {0.0: 0.0, 1.0: 1.0}, "RF1": {0.0: 0.0, 1.0: 10.0}}, legacy, step="Closing"
    )
    assert legacy_rows[-1]["total_force_N"] == pytest.approx(10.0)
    assert legacy_rows[-1]["force"] == pytest.approx(500.0)

    # Ambiguous legacy evidence is not silently multiplied by the new width.
    unavailable = {**legacy, "reporting_width_mm": 2.0, "force_basis": "legacy_unscaled"}
    unavailable_rows = interchange.align_histories(
        {"U1": {0.0: 0.0, 1.0: 1.0}, "RF1": {0.0: 0.0, 1.0: 10.0}}, unavailable, step="Closing"
    )
    assert unavailable_rows[-1]["force"] == pytest.approx(10.0)


def test_changing_only_width_leaves_the_deck_identical(rigid):
    project, mesh, labels = rigid
    project.analysis.reporting_width = 50.0
    first = deck.write_inp(project, mesh, labels)
    project.analysis.reporting_width = 200.0
    second = deck.write_inp(project, mesh, labels)
    assert first == second
    # The solver thickness still appears in every section and interaction.
    assert first.count("*Solid Section") == 2
    sections = first.split("*Solid Section")[1:]
    assert all("\n1," in block.split("*Elset")[0] or "\n1," in block for block in sections)
    interaction = first.split("*Surface Interaction, name=DOOR_SEAL")[1].split("\n", 1)[1]
    assert interaction.splitlines()[0].strip() == "1"


def test_role_derived_steps_and_ambiguity(rigid):
    project, _, _ = rigid
    assert derive_mode(project.components, project.edges, project.faces) == "door_only"
    two = engineering.two_panel_section("Two", body_y=-1.0, body_travel=5.0)
    assert derive_mode(two.components, two.edges, two.faces) == "body_then_door"
    # A second door is ambiguous: the sequence stays door-only and the duplicate
    # is reported instead of silently choosing one panel.
    two.components.append(
        type(two.components[0])(id="door2", name="Second door", role="moving_panel")
    )
    two.edges.append(
        type(two.edges[0])(
            id="door2-edge",
            name="Second door profile",
            component="door2",
            start=two.vertices[0].id,
            end=two.vertices[1].id,
        )
    )
    validated = Project.model_validate(two.model_dump(mode="json"))
    assert validated.analysis.mode == "door_only"
    codes = [item["code"] for item in findings(validated.components, validated.edges, validated.faces)]
    assert "components.duplicate_moving_panel" in codes

    # Removing the body returns to one step and changes the mesh identity.
    without_body = engineering.synthetic("No body")
    assert derive_mode(without_body.components, without_body.edges, without_body.faces) == "door_only"
