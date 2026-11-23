"""Two-step body seating then door closing: model, mesh, deck and metadata.

License-free tests only. They prove the generated sequence, identities and
geometry; they do not claim physical validation (Gate 4B needs a licensed run).
"""

import json
import math

import pytest
from fastapi.testclient import TestClient

from integrations.abaqus import deck, interchange, results
from integrations.abaqus.deck import ClearanceError
from packages import engineering
from packages.engineering import fixture as fixtures
from packages.engineering.mesh import generate_mesh
from packages.engineering.model import Component, Edge, Vertex
from services.api.main import app
from support import legacy_fixture, prepare_deck, prepare_mesh, save_fixture


def two_step_project(
    body_y=20.0,
    body_travel=-3.0,
    body_offset=0.0,
    door_offset=0.0,
    door_travel=-5.5,
    body_x=None,
):
    """Door above the seal plus a rigid body profile at ``body_y``.

    ``body_y`` above the seal is the original supported case; ``body_y`` below
    the seal is the bottom-mounted body that must seat upward.
    """
    project = engineering.synthetic("Two-panel section")
    panel = next(edge for edge in project.edges if edge.component == "panel")
    start = next(vertex for vertex in project.vertices if vertex.id == panel.start)
    end = next(vertex for vertex in project.vertices if vertex.id == panel.end)
    project.components.append(
        Component(id="body", name="Body profile", role="vehicle_body")
    )
    left = start.xyz[0] if body_x is None else body_x[0]
    right = end.xyz[0] if body_x is None else body_x[1]
    project.vertices.append(Vertex(id="body-v1", xyz=(left, body_y, 0)))
    project.vertices.append(Vertex(id="body-v2", xyz=(right, body_y, 0)))
    project.edges.append(
        Edge(
            id="body-profile",
            name="Body contact profile",
            component="body",
            start="body-v1",
            end="body-v2",
        )
    )
    project.analysis.mode = "body_then_door"
    project.motion.body.offset = body_offset
    project.motion.body.travel = body_travel
    project.motion.body.duration = 1.0
    project.motion.offset = door_offset
    project.motion.travel = door_travel
    project.motion.duration = 1.3
    return project


def fixture_labels(project, mesh):
    selection = next(
        item for item in project.selections if item.id == project.mounting.selection
    )
    return fixtures.from_edges(mesh, selection.entities)


def metadata_for(project, mesh, labels):
    nodes, ws, panel, body = deck._mesh_parts(project, mesh)
    return results._metadata(project, nodes, ws, panel, labels, body)


def steps_of(inp):
    blocks = []
    current = None
    for line in inp.splitlines():
        if line.startswith("*Step"):
            current = [line]
        elif current is not None:
            current.append(line)
            if line.strip() == "*End Step":
                blocks.append(current)
                current = None
    return blocks


@pytest.fixture(scope="module")
def built():
    project = two_step_project()
    mesh = generate_mesh(project)
    labels = fixture_labels(project, mesh)
    inp = deck.write_inp(project, mesh, labels)
    nodes, ws, panel, body = deck._mesh_parts(project, mesh)
    metadata = results._metadata(project, nodes, ws, panel, labels, body)
    return project, mesh, inp, metadata, labels


def test_mesh_includes_the_body_rigid_profile(built):
    project, mesh, _, _, _ = built
    rigid = [e for e in mesh["elements"] if e["type"] == "R2D2"]
    assert {e["component"] for e in rigid} == {"panel", "body"}
    assert mesh["excluded"] == []
    assert sum(mesh["counts"].values()) == len(mesh["elements"])


def test_two_step_deck_sequence_and_boundaries(built):
    _, _, inp, _, _ = built
    blocks = steps_of(inp)
    assert [block[0].split("name=")[1].split(",")[0] for block in blocks] == [
        "Body seating",
        "Closing",
    ]
    body_block, door_block = ("\n".join(block) for block in blocks)
    # Step 1 moves the body and holds the door at its initial position.
    assert "BODY_RP, 2, 2, -3" in body_block
    assert "PANEL_RP, 2, 2, 0." in body_block
    # Step 2 holds the body at the attained position and closes the door.
    assert "BODY_RP, 2, 2, -3" in door_block
    assert "PANEL_RP, 2, 2, -5.5" in door_block
    assert "op=NEW" not in inp
    assert inp.count("WSFIX, ENCASTRE") == 1
    assert "*Part, name=BODY" in inp
    assert "*Instance, name=BODY-1, part=BODY" in inp
    assert "*Rigid Body, ref node=BODY_RP" in inp
    assert "*Rigid Body, ref node=PANEL_RP" in inp
    assert "*Nset, nset=BODY_RP, instance=BODY-1" in inp
    assert "*Nset, nset=PANEL_RP, instance=PANEL-1" in inp
    # Both reference points are requested in both steps.
    assert body_block.count("nset=BODY_RP") == 1
    assert body_block.count("nset=PANEL_RP") == 1
    assert door_block.count("nset=BODY_RP") == 1
    assert door_block.count("nset=PANEL_RP") == 1
    assert "*Contact Inclusions, all exterior" in inp
    assert "BODY_FACE" in inp and "PANEL_FACE" in inp
    # The body starts above the seal; the reported clearance is physical.
    assert "Initial body clearance" in inp


def test_metadata_names_both_steps_and_references(built):
    _, _, _, metadata, _ = built
    assert [step["name"] for step in metadata["steps"]] == ["Body seating", "Closing"]
    assert [step["role"] for step in metadata["steps"]] == ["body", "door"]
    assert metadata["body"]["instance"] == "BODY-1"
    assert metadata["body"]["duration_s"] == 1.0
    assert metadata["placement"]["prescribed_body_travel_y_mm"] == -3.0
    assert metadata["placement"]["initial_body_vertical_mesh_clearance_mm"] > 0
    assert set(metadata["regions"]) == {"WS-1", "PANEL-1", "BODY-1"}
    assert metadata["closing"]["steps"] == metadata["steps"]


def test_legacy_door_only_deck_is_unchanged():
    project = engineering.synthetic("Door only")
    project.motion.travel = -5.5
    mesh = generate_mesh(project)
    labels = fixture_labels(project, mesh)
    inp = deck.write_inp(project, mesh, labels)
    blocks = steps_of(inp)
    assert len(blocks) == 1
    assert blocks[0][0].startswith("*Step, name=Closing")
    assert "*Part, name=BODY" not in inp
    assert "BODY_RP" not in inp
    assert "PANEL_RP, 2, 2, -5.5" in "\n".join(blocks[0])
    metadata = results._metadata(
        project,
        *deck._mesh_parts(project, mesh)[:3],
        fixture=labels,
    )
    assert [step["name"] for step in metadata["steps"]] == ["Closing"]
    assert "body" not in metadata


def test_mode_changes_mesh_identity_but_motion_does_not():
    project = two_step_project()
    before = engineering.mesh_compat(project)
    project.motion.travel = -6.5
    project.motion.body.travel = -4.0
    assert engineering.mesh_compat(project) == before
    project.analysis.mode = "door_only"
    assert engineering.mesh_compat(project) != before


def test_two_step_validation_accepts_a_zero_body_hold_and_requires_a_body():
    project = two_step_project()
    project.motion.body.travel = 0
    validated = type(project).model_validate(project.model_dump(mode="json"))
    assert validated.motion.body.travel == 0
    # A true zero is distinct from an invalid duration.
    project.motion.body.duration = 0
    with pytest.raises(ValueError, match="duration"):
        type(project).model_validate(project.model_dump(mode="json"))

    project = engineering.synthetic("No body")
    project.analysis.mode = "body_then_door"
    project.motion.body.travel = -1
    with pytest.raises(ValueError, match="moving door and one moving body"):
        type(project).model_validate(project.model_dump(mode="json"))


def test_history_projection_is_per_motion():
    metadata = {
        "thickness": 1.0,
        "force_normalization": "total",
        "closing": {"direction": [0.0, -1.0]},
    }
    series = {
        "U1": {0.0: 0.0, 1.0: 0.0},
        "U2": {0.0: 0.0, 1.0: -3.0},
        "RF1": {0.0: 0.0, 1.0: 0.0},
        "RF2": {0.0: 0.0, 1.0: -6.0},
    }
    body = interchange.align_histories(
        series,
        metadata,
        start_time=0.0,
        step="Body seating",
        motion={"role": "body", "direction": [0.0, -1.0]},
    )
    assert body and body[-1]["role"] == "body"
    assert body[-1]["displacement"] == pytest.approx(3.0)
    assert body[-1]["force"] == pytest.approx(6.0)
    door = interchange.align_histories(
        series,
        metadata,
        start_time=1.0,
        step="Closing",
        motion={"role": "door", "direction": [0.0, -1.0]},
    )
    assert door and door[-1]["role"] == "door"
    assert door[-1]["time"] == pytest.approx(2.0)


def test_manufactured_playback_refuses_two_step(built):
    project, mesh, _, _, labels = built
    with pytest.raises(ValueError, match="licensed Abaqus run"):
        results.write_playback(project, mesh, ".", labels)


# ---------------------------------------------------------------------------
# Fixtures A-M: role-aware clearance, contact normals, motion and projection.
# ---------------------------------------------------------------------------


def rigid_parts(inp):
    """Node coordinates and R2D2 connectivity for every generated part."""
    parts, part, mode = {}, None, None
    for line in inp.splitlines():
        if line.startswith("*Part, name="):
            part = line.split("name=")[1]
            parts[part] = {"nodes": {}, "elements": []}
        elif line.startswith("*End Part"):
            part, mode = None, None
        elif line.startswith("*Node"):
            mode = "nodes"
        elif line.startswith("*Element, type=R2D2"):
            mode = "elements"
        elif line.startswith("*"):
            mode = None
        elif part and mode == "nodes":
            label, x, y = line.split(",")[:3]
            parts[part]["nodes"][int(label)] = (float(x), float(y))
        elif part and mode == "elements":
            label, first, second = (int(value) for value in line.split(",")[:3])
            parts[part]["elements"].append((label, first, second))
    return parts


def rigid_normals(inp):
    """SPOS normals recomputed from the generated connectivity, not from the keyword."""
    normals = {}
    for name, part in rigid_parts(inp).items():
        rows = []
        for _, first, second in part["elements"]:
            a, b = part["nodes"][first], part["nodes"][second]
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            rows.append((-dy / length, dx / length))
        if rows:
            normals[name] = rows
    return normals


def plane_nodes(points):
    return {index + 1: (x, y, 0.0) for index, (x, y) in enumerate(points)}


@pytest.fixture(scope="module")
def bottom_body():
    """Door above the seal, body below it, body travelling upward (+5 mm)."""
    project = two_step_project(body_y=-1.0, body_travel=5.0)
    mesh = generate_mesh(project)
    return project, mesh, fixture_labels(project, mesh)


@pytest.fixture(scope="module")
def disjoint_body():
    """Body profile whose X range does not overlap the seal."""
    project = two_step_project(body_y=-1.0, body_travel=5.0, body_x=(20.0, 30.0))
    mesh = generate_mesh(project)
    return project, mesh, fixture_labels(project, mesh)


def test_a_door_above_moves_down_toward_the_seal(built):
    """A. Door above, moving downward (legacy geometry, two-panel mode)."""
    _, _, inp, metadata, _ = built
    door = metadata["assembly"]["door"]
    assert door["side"] == "above"
    assert door["direction"] == [0.0, -1.0]
    assert door["clearance_mm"] == pytest.approx(1.8, abs=1e-6)
    assert door["travel_mm"] < 0
    assert door["reaches_initial_gap"] is True
    normals = rigid_normals(inp)["PANEL"]
    assert all(n[1] < 0 for n in normals), normals


def test_b_body_below_moves_up_toward_the_seal(bottom_body):
    """B. Bottom-mounted body travels upward; the deck prepares successfully."""
    project, mesh, labels = bottom_body
    inp = deck.write_inp(project, mesh, labels)
    nodes, ws, panel, body = deck._mesh_parts(project, mesh)
    boundary = deck.exterior(ws)
    door = deck.motion_assessment(
        nodes, boundary, panel, project.motion, role="door", instance="PANEL-1", label="door"
    )
    seated = deck.motion_assessment(
        nodes, boundary, body, project.motion.body, role="body", instance="BODY-1",
        label="body",
    )
    assert door["side"] == "above" and door["direction"] == [0.0, -1.0]
    assert door["clearance_mm"] == pytest.approx(1.8, abs=1e-6)
    # Positive clearance convention: below the seal is not a negative gap.
    assert seated["side"] == "below"
    assert seated["direction"] == [0.0, 1.0]
    assert seated["clearance_mm"] == pytest.approx(1.0, abs=1e-6)
    assert seated["travel_mm"] == pytest.approx(5.0)
    assert seated["reaches_initial_gap"] is True
    normals = rigid_normals(inp)
    assert all(n[1] > 0 for n in normals["BODY"]), normals["BODY"]
    assert all(n[1] < 0 for n in normals["PANEL"]), normals["PANEL"]


def test_c_body_above_moves_down_toward_the_seal(built):
    """C. Body above, moving downward is still a supported arrangement."""
    _, _, inp, metadata, _ = built
    body = metadata["assembly"]["body"]
    assert body["side"] == "above"
    assert body["direction"] == [0.0, -1.0]
    assert body["clearance_mm"] == pytest.approx(7.8, abs=1e-6)
    assert all(n[1] < 0 for n in rigid_normals(inp)["BODY"])


def test_d_wrong_sign_travel_is_rejected(bottom_body):
    """D. Moving away from the seal is refused, not silently accepted."""
    project, mesh, labels = bottom_body
    away = two_step_project(body_y=-1.0, body_travel=-2.0)
    with pytest.raises(ClearanceError) as error:
        deck.write_inp(away, mesh, labels)
    assert error.value.code == "motion_away"
    assert error.value.details["label"] == "body"
    assert error.value.details["side"] == "below"

    # The same guard rejects a door travelling up while mounted above.
    nodes, ws, panel, _ = deck._mesh_parts(project, mesh)
    with pytest.raises(ClearanceError) as error:
        deck.clearance_report(
            nodes, deck.exterior(ws), panel, 0.0, travel=2.0, label="door"
        )
    assert error.value.code == "motion_away"


def test_e_initial_body_penetration_is_rejected(bottom_body):
    """E. An offset that buries the body inside the seal is a real penetration."""
    project, mesh, labels = bottom_body
    buried = two_step_project(body_y=-1.0, body_travel=5.0, body_offset=2.0)
    with pytest.raises(ClearanceError) as error:
        deck.write_inp(buried, mesh, labels)
    assert error.value.code == "initial_penetration"
    assert error.value.details["label"] == "body"
    assert error.value.details["depth"] == pytest.approx(1.0, abs=1e-6)


def test_f_initial_door_penetration_is_rejected(built):
    """F. A door offset below the seal crown is an initial penetration."""
    project, mesh, _, _, labels = built
    intrusive = two_step_project(body_y=20.0, body_travel=-3.0, door_offset=-3.0)
    with pytest.raises(ClearanceError) as error:
        deck.write_inp(intrusive, mesh, labels)
    assert error.value.code == "initial_penetration"
    assert error.value.details["label"] == "door"
    assert error.value.details["depth"] == pytest.approx(1.2, abs=1e-6)


def test_g_no_overlapping_x_range_is_rejected(disjoint_body):
    """G. A profile beside the seal has no vertical clearance to measure."""
    project, mesh, labels = disjoint_body
    with pytest.raises(ClearanceError) as error:
        deck.write_inp(project, mesh, labels)
    assert error.value.code == "no_x_overlap"
    assert error.value.details["label"] == "body"


def test_h_initial_offsets_change_the_measured_clearance(bottom_body):
    """H. Each profile applies its own offset to its own clearance."""
    project, mesh, labels = bottom_body
    shifted = two_step_project(
        body_y=-1.0, body_travel=5.0, body_offset=-2.0, door_offset=2.0
    )
    inp = deck.write_inp(shifted, mesh, labels)
    nodes, ws, panel, body = deck._mesh_parts(shifted, mesh)
    metadata = results._metadata(shifted, nodes, ws, panel, labels, body)
    placement = metadata["placement"]
    assert placement["initial_door_clearance_mm"] == pytest.approx(3.8, abs=1e-6)
    assert placement["initial_body_clearance_mm"] == pytest.approx(3.0, abs=1e-6)
    assert metadata["assembly"]["door"]["initial_offset_mm"] == 2.0
    assert metadata["assembly"]["body"]["initial_offset_mm"] == -2.0
    assert "*Instance, name=PANEL-1, part=PANEL\n0., 2, 0." in inp
    assert "*Instance, name=BODY-1, part=BODY\n0., -2, 0." in inp


def test_i_sloped_and_curved_profiles_are_measured_exactly():
    """I. Piecewise-linear FE surfaces, including sloped and curved segments."""
    seal = plane_nodes([(0.0, 0.0), (10.0, 0.0)])
    boundary = [(1, 2)]
    sloped_above = [{"id": 1, "nodes": [3, 4]}]
    nodes = {**seal, 3: (0.0, 5.0, 0.0), 4: (10.0, 3.0, 0.0)}
    assert deck.clearance_report(nodes, boundary, sloped_above, 0.0)["clearance"] == (
        pytest.approx(3.0)
    )

    sloped_below = [{"id": 2, "nodes": [5, 6]}]
    nodes = {**seal, 5: (0.0, -2.0, 0.0), 6: (10.0, -4.0, 0.0)}
    below = deck.clearance_report(nodes, boundary, sloped_below, 0.0)
    assert below["side"] == "below"
    assert below["clearance"] == pytest.approx(2.0)

    curved = [
        {"id": 3, "nodes": [7, 8]},
        {"id": 4, "nodes": [8, 9]},
        {"id": 5, "nodes": [9, 10]},
        {"id": 6, "nodes": [10, 11]},
    ]
    nodes = {
        **seal,
        7: (0.0, 5.0, 0.0),
        8: (2.0, 3.0, 0.0),
        9: (5.0, 2.5, 0.0),
        10: (8.0, 3.0, 0.0),
        11: (10.0, 5.0, 0.0),
    }
    curved_report = deck.clearance_report(nodes, boundary, curved, 0.0)
    assert curved_report["side"] == "above"
    assert curved_report["clearance"] == pytest.approx(2.5)

    # A vertical seal side is measured from its nearest point, not its midpoint.
    vertical_boundary = [(1, 2), (2, 12)]
    nodes = {**seal, 12: (10.0, 3.0, 0.0), 13: (0.0, -2.0, 0.0), 14: (10.0, -2.0, 0.0)}
    vertical = deck.clearance_report(
        nodes, vertical_boundary, [{"id": 7, "nodes": [13, 14]}], 0.0
    )
    assert vertical["side"] == "below"
    assert vertical["clearance"] == pytest.approx(2.0)


def test_j_contact_normals_point_at_the_seal_for_both_mounts(bottom_body, built):
    """J. Normals are verified geometrically from the generated connectivity."""
    bottom_project, bottom_mesh, bottom_labels = bottom_body
    bottom_inp = deck.write_inp(bottom_project, bottom_mesh, bottom_labels)
    _, _, above_inp, _, _ = built
    below_normals = rigid_normals(bottom_inp)
    above_normals = rigid_normals(above_inp)
    # Door above the seal: every SPOS normal points down toward it.
    assert all(n[1] < 0 for n in below_normals["PANEL"])
    assert all(n[1] < 0 for n in above_normals["PANEL"])
    # Body below: every SPOS normal points up toward it.
    assert all(n[1] > 0 for n in below_normals["BODY"])
    # Body above: it points down like the door.
    assert all(n[1] < 0 for n in above_normals["BODY"])
    # Turning the connectivity is not a node-set change.
    nodes, _, panel, body = deck._mesh_parts(bottom_project, bottom_mesh)
    assert sorted(n for e in body for n in e["nodes"]) == sorted(
        n for e in deck.orient_for_contact(body, "below") for n in e["nodes"]
    )
    assert sorted(e["id"] for e in body) == sorted(
        e["id"] for e in deck.orient_for_contact(body, "below")
    )
    # A sloped segment keeps the same contact-facing side after orientation.
    sloped = plane_nodes([(10.0, 0.0), (0.0, 4.0)])
    sloped_panel = [{"id": 1, "nodes": [1, 2]}]
    ordered = deck.panel_order(sloped_panel, sloped)
    assert deck.surface_normal(sloped, ordered[0])[1] < 0
    oriented = deck.orient_for_contact(ordered, "below")
    assert all(deck.surface_normal(sloped, e)[1] > 0 for e in oriented)


def test_l_projection_follows_each_motion_and_keeps_raw_signs():
    """L. Raw signed components are unchanged; projections use their own direction."""
    metadata = {"thickness": 1.0, "force_normalization": "total"}
    rising = {
        "U1": {0.0: 0.0, 1.0: 0.0},
        "U2": {0.0: 0.0, 1.0: 5.0},
        "RF1": {0.0: 0.0, 1.0: 0.0},
        "RF2": {0.0: 0.0, 1.0: 2.0},
    }
    body = interchange.align_histories(
        rising,
        metadata,
        step="Body seating",
        motion={"role": "body", "direction": [0.0, 1.0]},
    )
    assert body[-1]["role"] == "body"
    assert body[-1]["displacement"] == pytest.approx(5.0)
    assert body[-1]["force"] == pytest.approx(2.0)
    # The raw signed components are never rewritten to make the curve positive.
    assert body[-1]["u2"] == pytest.approx(5.0)
    assert body[-1]["rf2"] == pytest.approx(2.0)

    falling = {
        "U1": {0.0: 0.0, 1.0: 0.0},
        "U2": {0.0: 0.0, 1.0: -5.5},
        "RF1": {0.0: 0.0, 1.0: 0.0},
        "RF2": {0.0: 0.0, 1.0: -3.0},
    }
    door = interchange.align_histories(
        falling,
        metadata,
        start_time=1.0,
        step="Closing",
        motion={"role": "door", "direction": [0.0, -1.0]},
    )
    assert door[-1]["displacement"] == pytest.approx(5.5)
    assert door[-1]["force"] == pytest.approx(3.0)
    assert door[-1]["u2"] == pytest.approx(-5.5)
    assert door[-1]["rf2"] == pytest.approx(-3.0)
    assert door[-1]["time"] == pytest.approx(2.0)

    # Projecting the same rising raw history on the door direction stays negative:
    # only the motion direction decides the sign.
    wrong = interchange.align_histories(
        rising, metadata, step="Closing", motion={"role": "door", "direction": [0.0, -1.0]}
    )
    assert wrong[-1]["displacement"] == pytest.approx(-5.0)
    assert wrong[-1]["u2"] == pytest.approx(5.0)


def test_m_legacy_door_only_clearance_and_projection_are_unchanged():
    """M. The door-only template keeps its 1.80 mm gap and signed projection."""
    project = engineering.synthetic("Door only regression")
    project.motion.travel = -5.5
    mesh = generate_mesh(project)
    labels = fixture_labels(project, mesh)
    nodes, ws, panel = deck.mesh_parts(project, mesh)
    gap = deck.vertical_gap(nodes, deck.exterior(ws), panel, project.motion.offset)
    assert gap == pytest.approx(1.8, abs=1e-6)
    inp = deck.write_inp(project, mesh, labels)
    assert inp.count("*End Step") == 1
    assert "PANEL_RP, 2, 2, -5.5" in inp
    assert "*Part, name=BODY" not in inp
    metadata = results._metadata(project, nodes, ws, panel, labels)
    assert metadata["closing"]["direction"] == [0.0, -1.0]
    assert metadata["closing"]["steps"] == [{"name": "Closing", "role": "door"}]
    assert metadata["placement"]["initial_vertical_mesh_clearance_mm"] == pytest.approx(1.8)
    assert metadata["placement"]["door_side"] == "above"
    assert "body" not in metadata


@pytest.fixture(scope="module")
def distant_body():
    """Bottom body whose commanded travel is shorter than its initial gap."""
    project = two_step_project(body_y=-6.0, body_travel=5.0)
    mesh = generate_mesh(project)
    return project, mesh, fixture_labels(project, mesh)


def test_gap_shortfall_is_reported_without_claiming_contact(distant_body):
    """Travel that cannot reach the gap is reported as a shortfall, not contact."""
    project, mesh, labels = distant_body
    nodes, ws, panel, body = deck._mesh_parts(project, mesh)
    metadata = results._metadata(project, nodes, ws, panel, labels, body)
    body = metadata["assembly"]["body"]
    assert body["side"] == "below"
    assert body["clearance_mm"] == pytest.approx(6.0, abs=1e-6)
    assert body["travel_mm"] == pytest.approx(5.0)
    assert body["reaches_initial_gap"] is False
    # The gap shortfall is a diagnostic, not a deck refusal: the deck is valid.
    inp = deck.write_inp(project, mesh, labels)
    assert "Initial body clearance on the assembled mesh: 6" in inp


def test_two_step_metadata_projects_each_motion_independently(bottom_body):
    """Both motions keep their own direction in the written result metadata."""
    project, mesh, labels = bottom_body
    nodes, ws, panel, body = deck._mesh_parts(project, mesh)
    metadata = results._metadata(project, nodes, ws, panel, labels, body)
    assert [step["name"] for step in metadata["steps"]] == ["Body seating", "Closing"]
    assert metadata["steps"][0]["direction"] == [0.0, 1.0]
    assert metadata["steps"][1]["direction"] == [0.0, -1.0]
    assert metadata["body"]["direction"] == [0.0, 1.0]
    assert metadata["body"]["side"] == "below"
    assert metadata["closing"]["direction"] == [0.0, -1.0]
    assert metadata["placement"]["initial_body_clearance_mm"] == pytest.approx(1.0)
    assert metadata["placement"]["initial_door_clearance_mm"] == pytest.approx(1.8)
    assert metadata["placement"]["body_reaches_initial_gap"] is True
    header = interchange.result_header(metadata, "ABAQUS", [])
    assert header["assembly"]["body"]["direction"] == [0.0, 1.0]
    assert header["assembly"]["door"]["direction"] == [0.0, -1.0]


def test_user_bottom_body_upward_scenario_prepares_a_complete_deck(bottom_body):
    """The reported user case: door above -5.5 mm, body below +5 mm, 1.0/1.3 s."""
    project, mesh, labels = bottom_body
    inp = deck.write_inp(project, mesh, labels)
    for part in ("WS", "PANEL", "BODY"):
        assert f"*Part, name={part}" in inp
    for instance in ("WS-1", "PANEL-1", "BODY-1"):
        assert f"*Instance, name={instance}," in inp
    assert "*Nset, nset=BODY_RP, instance=BODY-1" in inp
    assert "*Nset, nset=PANEL_RP, instance=PANEL-1" in inp
    assert "*Rigid Body, ref node=PANEL_RP, elset=PANEL-1.PROFILE" in inp
    assert "*Rigid Body, ref node=BODY_RP, elset=BODY-1.PROFILE" in inp
    assert "*Surface, type=ELEMENT, name=BODY_FACE" in inp
    assert "*Surface, type=ELEMENT, name=PANEL_FACE" in inp
    assert "** BODY is below the seal; SPOS faces the seal." in inp
    assert "** PANEL is above the seal; SPOS faces the seal." in inp
    # Both initial placements are zero in the reported case.
    assert "*Instance, name=PANEL-1, part=PANEL\n0., 0, 0." in inp
    assert "*Instance, name=BODY-1, part=BODY\n0., 0, 0." in inp
    blocks = steps_of(inp)
    assert [block[0].split("name=")[1].split(",")[0] for block in blocks] == [
        "Body seating",
        "Closing",
    ]
    body_step, door_step = ("\n".join(block) for block in blocks)
    assert "*Dynamic\n0.0001, 1, 1e-13" in body_step
    assert "BODY_RP, 2, 2, 5" in body_step
    assert "PANEL_RP, 2, 2, 0." in body_step
    assert "*Dynamic\n0.0001, 1.3, 1e-13" in door_step
    assert "BODY_RP, 2, 2, 5" in door_step
    assert "PANEL_RP, 2, 2, -5.5" in door_step
    assert inp.count("WSFIX, ENCASTRE") == 1
    assert "op=NEW" not in inp


def test_readiness_exposes_the_bottom_body_measurement(monkeypatch, tmp_path):
    """Motion/Review diagnostics read the same measurement the deck writer uses."""
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    from services import store

    with TestClient(app, base_url="http://127.0.0.1") as api:
        # A body profile enters through import or a seeded drawing-backed setup;
        # this fixture seeds it directly rather than through the topology guard.
        created = store.save(
            two_step_project(body_y=-1.0, body_travel=5.0).model_dump(mode="json")
        )
        revision = store.revision(created["id"])
        mesh = prepare_mesh(api, revision)
        labels = legacy_fixture(api, mesh["id"])["labels"]
        save_fixture(api, mesh["id"], labels)
        document = api.get(f"/api/revisions/{revision['id']}/readiness").json()
        assembly = document["assembly"]
        assert assembly["door"]["side"] == "above"
        assert assembly["door"]["direction"] == [0.0, -1.0]
        assert assembly["door"]["clearance_mm"] == pytest.approx(1.8, abs=1e-6)
        assert assembly["body"]["side"] == "below"
        assert assembly["body"]["direction"] == [0.0, 1.0]
        assert assembly["body"]["clearance_mm"] == pytest.approx(1.0, abs=1e-6)
        assert assembly["body"]["reaches_initial_gap"] is True
        # Before the deck exists, only the missing deck blocks the revision.
        assert document["state"] == "blocked"
        assert "deck.missing" in {f["code"] for f in document["findings"]}
        # The exact user path that used to fail: the worker prepares the deck.
        deck_job = prepare_deck(api, revision, mesh["id"])
        assert deck_job["status"] == "Completed", deck_job["diagnostic"]
        text = (store.job_dir(deck_job["id"]) / "analysis.inp").read_text()
        assert "*Part, name=BODY" in text
        assert "*Nset, nset=BODY_RP, instance=BODY-1" in text
        assert "BODY_RP, 2, 2, 5" in text
        assert "PANEL_RP, 2, 2, -5.5" in text
        recorded = json.loads(
            (store.job_dir(deck_job["id"]) / "result-metadata.json").read_text()
        )
        assert [step["direction"] for step in recorded["steps"]] == [
            [0.0, 1.0],
            [0.0, -1.0],
        ]
        assert recorded["assembly"]["body"]["side"] == "below"
        # The deck now exists, so that blocker is gone.
        ready = api.get(f"/api/revisions/{revision['id']}/readiness").json()
        assert "deck.missing" not in {f["code"] for f in ready["findings"]}

        penetrated = store.save(
            two_step_project(
                body_y=-1.0, body_travel=5.0, body_offset=2.0
            ).model_dump(mode="json"),
            project=revision["project"],
            base=revision["id"],
        )
        blocked = api.get(f"/api/revisions/{penetrated['id']}/readiness").json()
        finding = next(
            f for f in blocked["findings"] if f["code"] == "motion.initial_penetration"
        )
        assert finding["stage"] == "motion"
        assert finding["severity"] == "blocker"
        assert finding["params"]["label"] == "body"
        assert finding["params"]["depth"] == pytest.approx(1.0)
        assert blocked["assembly"]["code"] == "initial_penetration"
        assert blocked["assembly"]["details"]["depth"] == pytest.approx(1.0)
        assert blocked["assembly"]["details"]["label"] == "body"


@pytest.mark.parametrize("body_travel", [0.0, 5.0])
def test_new_default_closing_travel_in_two_step_deck(bottom_body, body_travel):
    _, mesh, labels = bottom_body
    project = two_step_project(body_y=-1.0, body_travel=body_travel, door_travel=-10.0)
    project.motion.duration = 1.0
    inp = deck.write_inp(project, mesh, labels)
    body_step, door_step = ("\n".join(block) for block in steps_of(inp))
    assert f"BODY_RP, 2, 2, {body_travel:g}" in body_step
    assert f"BODY_RP, 2, 2, {body_travel:g}" in door_step
    assert "PANEL_RP, 2, 2, 0" in body_step
    assert "PANEL_RP, 2, 2, -10" in door_step
    assert "*Dynamic\n0.0001, 1, 1e-13" in door_step
    assert "*Contact Inclusions, all exterior" in inp
    assert "*Nset, nset=WSFIX" in inp


def test_zero_body_travel_seats_only_the_door_in_step_two(bottom_body):
    """0 body / -5.5 door: step 1 holds both, step 2 moves only the door."""
    _, mesh, labels = bottom_body
    project = two_step_project(body_y=-1.0, body_travel=0.0, door_travel=-5.5)
    inp = deck.write_inp(project, mesh, labels)
    body_step, door_step = ("\n".join(block) for block in steps_of(inp))
    assert "BODY_RP, 2, 2, 0" in body_step
    assert "PANEL_RP, 2, 2, 0." in body_step
    # The body stays at its assembled position while the door closes.
    assert "BODY_RP, 2, 2, 0" in door_step
    assert "PANEL_RP, 2, 2, -5.5" in door_step
    metadata = metadata_for(project, mesh, labels)
    assert metadata["assembly"]["body"]["hold"] is True
    assert metadata["assembly"]["body"]["travel_mm"] == 0
    assert metadata["steps"][0]["direction"] == [0.0, 1.0]
    assert metadata["steps"][1]["travel_mm"] == -5.5


def test_zero_door_travel_holds_the_attained_assembly(bottom_body):
    """+5 body / 0 door: step 1 seats the body, step 2 holds the assembly."""
    _, mesh, labels = bottom_body
    project = two_step_project(body_y=-1.0, body_travel=5.0, door_travel=0.0)
    inp = deck.write_inp(project, mesh, labels)
    body_step, door_step = ("\n".join(block) for block in steps_of(inp))
    assert "BODY_RP, 2, 2, 5" in body_step
    assert "PANEL_RP, 2, 2, 0." in body_step
    assert "BODY_RP, 2, 2, 5" in door_step
    assert "PANEL_RP, 2, 2, 0" in door_step
    metadata = metadata_for(project, mesh, labels)
    assert metadata["assembly"]["door"]["hold"] is True
    assert metadata["assembly"]["door"]["side"] == "above"
    assert metadata["assembly"]["door"]["direction"] == [0.0, -1.0]
    assert metadata["steps"][0]["travel_mm"] == 5.0


def test_zero_travel_on_both_steps_is_a_hold_only_analysis(bottom_body):
    """0 body / 0 door: both steps hold their assembled positions."""
    _, mesh, labels = bottom_body
    project = two_step_project(body_y=-1.0, body_travel=0.0, door_travel=0.0)
    inp = deck.write_inp(project, mesh, labels)
    body_step, door_step = ("\n".join(block) for block in steps_of(inp))
    for step in (body_step, door_step):
        assert "BODY_RP, 2, 2, 0" in step
        assert "PANEL_RP, 2, 2, 0" in step
        # A hold is a true zero, never an epsilon motion.
        assert "2, 2, 1e-" not in step
    metadata = metadata_for(project, mesh, labels)
    assert metadata["assembly"]["door"]["hold"] is True
    assert metadata["assembly"]["body"]["hold"] is True
    # A held panel still has a side and a defined reporting axis.
    assert metadata["assembly"]["door"]["side"] == "above"
    assert metadata["assembly"]["body"]["side"] == "below"
    assert metadata["steps"][0]["direction"] == [0.0, 1.0]
    assert metadata["steps"][1]["direction"] == [0.0, -1.0]


def test_door_only_zero_travel_is_an_explicit_hold():
    project = engineering.synthetic("Door hold")
    project.motion.travel = 0.0
    project.motion.duration = 1.0
    mesh = generate_mesh(project)
    labels = fixture_labels(project, mesh)
    nodes, ws, panel = deck.mesh_parts(project, mesh)
    metadata = results._metadata(project, nodes, ws, panel, labels)
    assert metadata["steps"][0]["travel_mm"] == 0
    assert metadata["assembly"]["door"]["hold"] is True
    assert metadata["assembly"]["door"]["side"] == "above"
    inp = deck.write_inp(project, mesh, labels)
    assert "*Step, name=Closing" in inp
    assert "PANEL_RP, 2, 2, 0" in inp
    assert inp.count("*End Step") == 1


def seal_box():
    nodes = {
        1: (0.0, 0.0, 0.0),
        2: (10.0, 0.0, 0.0),
        3: (10.0, 2.0, 0.0),
        4: (0.0, 2.0, 0.0),
    }
    boundary = [(1, 2), (2, 3), (3, 4), (4, 1)]
    return nodes, boundary


def test_assembled_offset_decides_the_side_after_placement():
    """A body drawn above but placed below is below, not a penetration error."""
    nodes, boundary = seal_box()
    nodes.update({5: (0.0, 3.0, 0.0), 6: (10.0, 3.0, 0.0)})
    panel = [{"nodes": [5, 6]}]
    report = deck.clearance_report(nodes, boundary, panel, -5.0)
    assert report["side"] == "below"
    assert report["clearance"] == pytest.approx(2.0)
    assert report["direction"] == [0.0, 1.0]


def test_placement_intersection_and_ambiguous_side_are_distinct():
    nodes, boundary = seal_box()
    nodes.update({5: (0.0, 3.0, 0.0), 6: (10.0, 3.0, 0.0)})
    panel = [{"nodes": [5, 6]}]
    # Offset -2 puts the profile at Y = 1, inside the 0-2 mm solid.
    with pytest.raises(ClearanceError) as intersection:
        deck.clearance_report(nodes, boundary, panel, -2.0)
    assert intersection.value.code == "initial_penetration"
    assert intersection.value.details["depth"] == pytest.approx(1.0)

    # A seal with a hole: a profile inside the hole has no contact side.
    cavity_nodes = {
        1: (0.0, 0.0, 0.0),
        2: (10.0, 0.0, 0.0),
        3: (10.0, 4.0, 0.0),
        4: (0.0, 4.0, 0.0),
        5: (2.0, 1.0, 0.0),
        6: (8.0, 1.0, 0.0),
        7: (8.0, 3.0, 0.0),
        8: (2.0, 3.0, 0.0),
        9: (3.0, 2.0, 0.0),
        10: (7.0, 2.0, 0.0),
    }
    cavity_boundary = [
        (1, 2), (2, 3), (3, 4), (4, 1),
        (5, 6), (6, 7), (7, 8), (8, 5),
    ]
    with pytest.raises(ClearanceError) as ambiguous:
        deck.clearance_report(
            cavity_nodes, cavity_boundary, [{"nodes": [9, 10]}], 0.0
        )
    assert ambiguous.value.code == "side_ambiguous"
