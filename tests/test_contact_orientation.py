"""Contact-side orientation on the assembled, swept geometry (audit fix D1)."""

import pytest

from integrations.abaqus.deck import (
    PreparationError,
    _boundary_segments,
    _mesh_parts,
    assembly_assessment,
    exterior,
    orient_toward,
    surface_normal,
    write_inp,
)
from packages.engineering import generate_mesh, synthetic


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
