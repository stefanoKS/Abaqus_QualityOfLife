"""Contact-side orientation on the assembled, swept geometry (audit fix D1)."""

import copy
import json
import math

import pytest

from integrations.abaqus.deck import (
    PreparationError,
    _boundary_segments,
    _mesh_parts,
    _segment_first_contact,
    _segment_toi,
    assembly_assessment,
    exterior,
    orient_toward,
    surface_normal,
    write_inp,
)
from packages.engineering import generate_mesh, synthetic
from packages.engineering.model import (
    Component,
    Edge,
    Face,
    Material,
    Motion,
    Project,
    Selection,
    Source,
    Vertex,
)

C_SECTION = [(-5, -1), (5, -1), (5, 0), (-4, 0), (-4, 4), (5, 4), (5, 5), (-5, 5)]


def c_section(door=((-1.0, 1.0), (1.0, 1.0)), stroke=4.0, angle=90.0, offset=0.0, reverse=False):
    """Closed C seal plus one straight rigid door, as the Gate 2 counterexample."""
    vertices = [
        Vertex(id=f"v{index + 1}", xyz=(float(x), float(y), 0))
        for index, (x, y) in enumerate(C_SECTION)
    ]
    edges = []
    for index in range(len(C_SECTION)):
        edges.append(
            Edge(
                id=f"e{index + 1}",
                name=f"Seal edge {index + 1}",
                component="seal",
                start=f"v{index + 1}",
                end=f"v{(index + 1) % len(C_SECTION) + 1}",
            )
        )
    loop = [f"e{index + 1}" for index in range(len(C_SECTION))]
    door_start, door_end = door
    if reverse:
        loop = [f"-e{index + 1}" for index in reversed(range(len(C_SECTION)))]
        edges.reverse()
        door_start, door_end = door_end, door_start
    vertices += [
        Vertex(id="dv1", xyz=(float(door_start[0]), float(door_start[1]), 0)),
        Vertex(id="dv2", xyz=(float(door_end[0]), float(door_end[1]), 0)),
    ]
    edges.append(
        Edge(id="door", name="Door contact profile", component="panel", start="dv1", end="dv2")
    )
    return Project(
        schema_version=4,
        name="Gate 2 C-section",
        vertices=vertices,
        edges=edges,
        faces=[
            Face(
                id="seal_region",
                name="C section seal",
                component="seal",
                material="rubber",
                loops=[loop],
            )
        ],
        components=[
            Component(id="seal", name="C seal", role="seal"),
            Component(id="panel", name="Straight door", role="moving_panel"),
        ],
        materials=[
            Material(
                id="rubber",
                name="Rubber",
                color="#888888",
                model="linear_elastic",
                density=1.15e-9,
                young=6.2,
                poisson=0.44,
            )
        ],
        selections=[Selection(id="mount", name="Fixed bottom edge", entities=["e1"])],
        source=Source(kind="synthetic", filename="Gate 2 C-section"),
        motion=Motion(offset=offset, stroke=stroke, angle=angle, duration=1.0),
    )


def panel_normals(text):
    """Emitted PANEL R2D2 label -> SPOS unit normal, from the written connectivity."""
    from scripts.acceptance_dwg import parse_rigid_parts

    panel = parse_rigid_parts(text)["PANEL"]
    normals = {}
    for element, first, second in panel["elements"]:
        a, b = panel["nodes"][first], panel["nodes"][second]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        normals[element] = (-dy / length, dx / length)
    return normals


def deck_and_normals(project):
    mesh = generate_mesh(project)
    text = write_inp(project, mesh)
    return mesh, text, panel_normals(text)


def test_exact_segment_sweep_handles_parallel_nonparallel_and_zero_travel():
    """Closed-form first contact, not sampling: parallel, crossing, zero travel."""
    # Non-parallel: horizontal moving segment rises into a vertical seal segment.
    crossing = _segment_toi((0.0, 0.0, 1.0, 0.0), (0.0, 2.0), (0.5, 0.5, 0.5, 1.5))
    assert crossing is not None
    assert crossing["fraction"] == pytest.approx(0.25, abs=1e-12)

    # Parallel face: the moving segment meets the matching seal segment at t=1.
    parallel = _segment_toi((-1.0, 0.0, 1.0, 0.0), (0.0, 1.0), (-0.5, 1.0, 0.5, 1.0))
    assert parallel is not None
    assert parallel["fraction"] == pytest.approx(1.0, abs=1e-12)

    # A collinear instant is caught exactly once.
    instant = _segment_toi((-0.5, 0.0, 0.5, 0.0), (0.0, 1.0), (-0.5, 1.0, 0.5, 1.0))
    assert instant is not None
    assert instant["fraction"] == pytest.approx(1.0, abs=1e-12)

    # Zero travel has no prescribed first contact.
    assert _segment_first_contact([((-1.0, 0.0), (1.0, 0.0))], [(-0.5, 1.0, 0.5, 1.0)], (0.0, 0.0))["kind"] == "none"


def test_c_section_first_contact_orients_to_the_upper_lip():
    """The counterexample: nearest surface is the lower lip, first hit is y=4."""
    project = c_section()
    mesh = generate_mesh(project)
    door = assembly_assessment(project, mesh)["door"]
    assert door["first_contact_fraction"] == pytest.approx(0.75, abs=1e-12)
    assert door["direction_to_seal"] == [0.0, 1.0]
    assert door["contact_target"]["initial_gap_mm"] == pytest.approx(3.0)
    assert door["nearest_surface_is_target"] is False
    assert all(segment[1] == pytest.approx(4.0) for segment in door["contact_target"]["seal_segments"])

    _, text, normals = deck_and_normals(project)
    assert normals
    assert min(normal[1] for normal in normals.values()) > 0.999
    assert min(normal[0] * 0.0 + normal[1] * 1.0 for normal in normals.values()) > 0.999


def test_slanted_endpoint_only_first_contact_orients_to_the_hit_endpoint():
    """Only the high endpoint of the slanted door reaches the upper lip first."""
    project = c_section(door=((-1.0, 1.0), (0.9, 0.6)))
    mesh = generate_mesh(project)
    door = assembly_assessment(project, mesh)["door"]
    assert door["first_contact_fraction"] == pytest.approx(0.75, abs=1e-12)
    assert len(door["contact_target"]["element_ids"]) == 1
    assert all(segment[1] == pytest.approx(4.0) for segment in door["contact_target"]["seal_segments"])

    _, text, normals = deck_and_normals(project)
    assert min(normal[0] * 0.0 + normal[1] * 1.0 for normal in normals.values()) > 0.9


def test_reversed_cad_edge_order_keeps_the_fixed_orientation():
    """The same contour traversed the other way must not change the decision."""
    project = c_section(reverse=True)
    mesh = generate_mesh(project)
    door = assembly_assessment(project, mesh)["door"]
    assert door["first_contact_fraction"] == pytest.approx(0.75, abs=1e-12)
    assert door["direction_to_seal"] == [0.0, 1.0]

    _, text, normals = deck_and_normals(project)
    assert min(normal[1] for normal in normals.values()) > 0.999


def test_initial_touch_on_lower_lip_reaches_upper_lip_at_one():
    """Touching the lower lip while moving up must target the upper lip, not be ambiguous."""
    project = c_section(door=((-1.0, 0.0), (1.0, 0.0)))
    mesh = generate_mesh(project)
    door = assembly_assessment(project, mesh)["door"]
    assert door["first_contact_fraction"] == pytest.approx(1.0, abs=1e-12)
    assert door["path"] == "contact"
    assert door["direction_to_seal"] == [0.0, 1.0]
    assert all(segment[1] == pytest.approx(4.0) for segment in door["contact_target"]["seal_segments"])

    _, text, normals = deck_and_normals(project)
    assert min(normal[1] for normal in normals.values()) > 0.999


def test_initial_touch_on_upper_lip_is_contact_at_zero():
    """A door already on the upper lip and moving into it is t=0 contact."""
    project = c_section(door=((-1.0, 4.0), (1.0, 4.0)))
    mesh = generate_mesh(project)
    door = assembly_assessment(project, mesh)["door"]
    assert door["first_contact_fraction"] == pytest.approx(0.0, abs=1e-12)
    assert door["path"] == "touching"
    assert door["direction_to_seal"] == [0.0, 1.0]
    assert door["contact_target"]["initial_gap_mm"] == pytest.approx(0.0, abs=1e-12)

    _, text, normals = deck_and_normals(project)
    assert min(normal[1] for normal in normals.values()) > 0.999


def test_near_miss_prepares_without_inventing_contact():
    """A path that stops just short keeps its documented no-contact behaviour."""
    project = c_section(stroke=2.99)
    mesh = generate_mesh(project)
    door = assembly_assessment(project, mesh)["door"]
    assert door["first_contact_fraction"] is None
    assert door["path"] == "approaching"
    assert door["reaches_initial_gap"] is False
    write_inp(project, mesh)  # still a supported deck


def test_acceptance_checker_rejects_the_old_c_section_orientation():
    """The updated acceptance check must fail a deck that still emits (0,-1)."""
    from scripts.acceptance_dwg import (
        _instance_translation,
        _motion_delta,
        parse_rigid_parts,
        rigid_spos_checks,
        seal_boundary_segments,
    )

    project = c_section()
    mesh = generate_mesh(project)
    text = write_inp(project, mesh)
    parts = parse_rigid_parts(text)
    nodes = {node["id"]: node["xyz"] for node in mesh["nodes"]}
    continuum = [element for element in mesh["elements"] if element["type"] != "R2D2"]
    setup = json.loads(project.model_dump_json())
    translations = {name: _instance_translation(text, f"{name}-1") for name in parts}
    deltas = {"PANEL": _motion_delta(setup["motion"], setup["schema_version"])}

    good = rigid_spos_checks(
        parts,
        seal_boundary_segments(nodes, continuum),
        instance_translations=translations,
        deltas=deltas,
    )
    assert good[0]["min_dot"] > 0.999
    assert good[0]["first_contact_fraction"] == pytest.approx(0.75, abs=1e-12)

    # Reproduce the audited defect: every emitted pair has the old order, hence
    # every SPOS normal is (0,-1) while first contact is still the upper lip.
    buggy = copy.deepcopy(parts)
    buggy["PANEL"]["elements"] = [
        (element, second, first) for element, first, second in buggy["PANEL"]["elements"]
    ]
    bad = rigid_spos_checks(
        buggy,
        seal_boundary_segments(nodes, continuum),
        instance_translations=translations,
        deltas=deltas,
    )
    assert bad[0]["min_dot"] < -0.999
    assert bad[0]["first_contact_fraction"] == pytest.approx(0.75, abs=1e-12)


def test_acceptance_checker_applies_instance_translation_for_offset_regression():
    """The acceptance check uses the PANEL-1 translation, not the drawn Y=14 pose."""
    from scripts.acceptance_dwg import (
        _instance_translation,
        _motion_delta,
        parse_rigid_parts,
        rigid_spos_checks,
        seal_boundary_segments,
    )

    project = synthetic()
    project.motion.offset = -15
    project.motion.angle = 90
    project.motion.stroke = 2
    mesh = generate_mesh(project)
    text = write_inp(project, mesh)
    parts = parse_rigid_parts(text)
    nodes = {node["id"]: node["xyz"] for node in mesh["nodes"]}
    continuum = [element for element in mesh["elements"] if element["type"] != "R2D2"]
    setup = json.loads(project.model_dump_json())
    checks = rigid_spos_checks(
        parts,
        seal_boundary_segments(nodes, continuum),
        instance_translations={name: _instance_translation(text, f"{name}-1") for name in parts},
        deltas={"PANEL": _motion_delta(setup["motion"], setup["schema_version"])},
    )
    panel = checks[0]
    assert panel["first_contact_fraction"] == pytest.approx(0.5, abs=1e-12)
    assert panel["min_dot"] > 0.99


def test_assembled_offset_and_upward_sweep_face_the_seal():
    """The reported case: door drawn at Y=14, offset −15 mm, upward 2 mm.

    The orientation must be decided on the assembled profile (Y≈−1 mm), not on
    the drawing's original coordinates. The baseline using original midpoints
    produced dot = −1; the assembled sweep faces the seal with dot ≈ +1 and the
    first geometric touch near 1 mm.
    """
    project = synthetic()
    project.motion.offset = -15
    project.motion.angle = 90
    project.motion.stroke = 2
    mesh = generate_mesh(project)
    nodes, ws, panel, _ = _mesh_parts(project, mesh)
    seal = _boundary_segments(nodes, exterior(ws))

    assessment = assembly_assessment(project, mesh)
    door = assessment["door"]
    assert door["initial_offset_mm"] == -15
    assert door["clearance_mm"] == pytest.approx(1.0, abs=1e-6)
    assert door["first_contact_fraction"] == pytest.approx(0.5, abs=1e-6)
    assert door["reaches_initial_gap"] is True

    oriented = orient_toward(
        panel,
        nodes,
        door["direction_to_seal"],
        seal=seal,
        role="door",
        label="door",
        offset=project.motion.offset,
        delta=door["delta_mm"],
    )
    dots = []
    for element in oriented:
        normal = surface_normal(nodes, element)
        dots.append(
            normal[0] * door["direction_to_seal"][0]
            + normal[1] * door["direction_to_seal"][1]
        )
    assert min(dots) > 0.999
    # The generated deck keeps the same orientation and every original element.
    deck = write_inp(project, mesh)
    assert "type=R2D2" in deck
    assert len(oriented) == len(panel)


def test_opposing_local_normals_are_ambiguous():
    """A first-contact neighborhood with opposing local normals is refused.

    The deck writer and readiness both call this one function, so one typed
    rejection is shared rather than a readiness/worker disagreement.
    """
    nodes = {
        1: [0.0, 0.0, 0.0],
        2: [1.0, 0.0, 0.0],
        3: [1.0, 1.0, 0.0],
        4: [2.0, 1.0, 0.0],
    }
    ordered = [
        {"id": 1, "nodes": [1, 2]},
        {"id": 2, "nodes": [3, 4]},
    ]
    # The seal passes between the two elements, so their nearest-seal directions
    # and SPOS normals genuinely oppose one another.
    seal = [(-1.0, 0.5, 3.0, 0.5)]
    with pytest.raises(PreparationError) as exc:
        orient_toward(
            ordered, nodes, [0.0, 1.0], seal=seal, role="door", label="door"
        )
    assert exc.value.code == "panel.contact_side_ambiguous"
    assert exc.value.stage == "components"
    # Readiness maps this exact typed code onto its blocker vocabulary.
    from services import readiness

    assert readiness.CLEARANCE_FINDINGS["side_ambiguous"] == "motion.side_ambiguous"
    assert "panel.contact_side_ambiguous" in readiness.CLEARANCE_FINDINGS


def test_stationary_no_contact_behaviour_is_preserved():
    """A hold away from the seal stays a valid stationary placement."""
    project = synthetic()
    project.motion.offset = 30
    project.motion.angle = 90
    project.motion.stroke = 0
    mesh = generate_mesh(project)
    assessment = assembly_assessment(project, mesh)
    assert assessment["door"]["hold"] is True
    assert assessment["door"]["first_contact_fraction"] is None
    write_inp(project, mesh)
