"""R2D2 profile topology and contact-side orientation.

The reported OTR failure was a valid curved, open body chain rejected because it
turned back in X. These tests separate topology (which element follows which)
from contact-side orientation (which side of the generated connectivity faces
the seal), and prove the genuinely invalid cases still fail with a typed reason.
"""

import json

import pytest

from integrations.abaqus import deck
from packages import engineering
from packages.engineering.mesh import generate_mesh
from services import readiness, store


def nodes_of(points):
    return {index + 1: (float(x), float(y), 0.0) for index, (x, y) in enumerate(points)}


def chain(points, *, shuffled=False, reversed_ids=()):
    elements = []
    for index in range(len(points) - 1):
        first, second = index + 1, index + 2
        if index in reversed_ids:
            first, second = second, first
        elements.append({"id": 100 + index, "type": "R2D2", "nodes": [first, second]})
    if shuffled:
        elements = list(reversed(elements))
    return elements


def test_curved_return_keeps_every_element_once_and_original_identity():
    """A local return in X is a shape, not a topology defect."""
    points = [(10.0, 0.0), (8.0, 0.5), (6.0, -0.5), (4.0, 1.0), (3.0, 3.0), (2.0, 1.0)]
    nodes = nodes_of(points)
    elements = chain(points, shuffled=True, reversed_ids=(0, 2, 4))
    ordered = deck.panel_order(elements, nodes, role="body", label="body")
    assert sorted(element["id"] for element in ordered) == sorted(
        element["id"] for element in elements
    )
    # Every node pair is an original pair in one of its two directions.
    original = {tuple(sorted(element["nodes"])) for element in elements}
    assert all(tuple(sorted(element["nodes"])) in original for element in ordered)
    # The walk is a real adjacency chain.
    for previous, current in zip(ordered, ordered[1:]):
        assert previous["nodes"][1] == current["nodes"][0]


def test_vertical_profile_with_equal_endpoint_x_is_supported():
    points = [(0.0, 0.0), (0.0, 2.0), (0.0, 4.0)]
    ordered = deck.panel_order(chain(points), nodes_of(points), role="door", label="door")
    assert len(ordered) == 2
    assert ordered[0]["nodes"][1] == ordered[1]["nodes"][0]


def test_orientation_flips_the_curved_body_toward_the_seal():
    """The body below/left of a seal flips as a unit; the local check passes."""
    body_points = [
        (6.0, -2.0),
        (4.0, -2.2),
        (2.0, -1.8),
        (0.5, -0.5),
        (0.4, 1.5),
        (0.4, 3.5),
    ]
    nodes = nodes_of(body_points)
    # A horizontal seal from x=1 to x=9 at y=0.
    nodes.update({50: (1.0, 0.0, 0.0), 51: (9.0, 0.0, 0.0)})
    seal = [(1.0, 0.0, 9.0, 0.0)]
    ordered = deck.panel_order(chain(body_points), nodes, role="body", label="body")
    oriented = deck.orient_toward(
        ordered,
        nodes,
        [0.0, 1.0],
        seal=seal,
        role="body",
        label="body",
    )
    rows = deck._first_contact(deck._contact_alignment(oriented, nodes, seal))
    assert rows
    assert min(row["dot"] for row in rows) > 0
    assert sorted(element["id"] for element in oriented) == sorted(
        element["id"] for element in ordered
    )


def test_straight_and_angled_legacy_ordering_is_unchanged():
    sloped_nodes = nodes_of([(10.0, 0.0), (0.0, 4.0)])
    sloped = [{"id": 1, "type": "R2D2", "nodes": [1, 2]}]
    ordered = deck.panel_order(sloped, sloped_nodes)
    # Historical right-to-left walk keeps the SPOS normal pointing down.
    assert deck.surface_normal(sloped_nodes, ordered[0])[1] < 0
    oriented = deck.orient_for_contact(ordered, "below")
    assert all(deck.surface_normal(sloped_nodes, element)[1] > 0 for element in oriented)

    flat_nodes = nodes_of([(10.0, 2.0), (0.0, 2.0)])
    flat = [{"id": 2, "type": "R2D2", "nodes": [1, 2]}]
    assert deck.panel_order(flat, flat_nodes)[0]["nodes"] == [1, 2]


def test_branch_disconnected_closed_repeated_and_degenerate_are_typed():
    nodes = nodes_of([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)])
    with pytest.raises(deck.PreparationError) as branch:
        deck.panel_order(
            [
                {"id": 1, "type": "R2D2", "nodes": [1, 2]},
                {"id": 2, "type": "R2D2", "nodes": [2, 3]},
                {"id": 3, "type": "R2D2", "nodes": [2, 4]},
            ],
            nodes,
            role="door",
            label="door",
        )
    assert branch.value.code == "panel.branched_profile"
    assert branch.value.stage == "components"

    with pytest.raises(deck.PreparationError) as disconnected:
        deck.panel_order(
            [
                {"id": 1, "type": "R2D2", "nodes": [1, 2]},
                {"id": 2, "type": "R2D2", "nodes": [3, 4]},
            ],
            nodes,
            role="door",
            label="door",
        )
    assert disconnected.value.code == "panel.disconnected_profile"

    ring_nodes = nodes_of([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
    with pytest.raises(deck.PreparationError) as closed:
        deck.panel_order(
            [
                {"id": 1, "type": "R2D2", "nodes": [1, 2]},
                {"id": 2, "type": "R2D2", "nodes": [2, 3]},
                {"id": 3, "type": "R2D2", "nodes": [3, 4]},
                {"id": 4, "type": "R2D2", "nodes": [4, 1]},
            ],
            ring_nodes,
            role="door",
            label="door",
        )
    assert closed.value.code == "panel.closed_profile"

    with pytest.raises(deck.PreparationError) as repeated:
        deck.panel_order(
            [
                {"id": 1, "type": "R2D2", "nodes": [1, 2]},
                {"id": 1, "type": "R2D2", "nodes": [2, 3]},
            ],
            nodes,
            role="door",
            label="door",
        )
    assert repeated.value.code == "panel.repeated_element"

    with pytest.raises(deck.PreparationError) as degenerate:
        deck.panel_order(
            [{"id": 1, "type": "R2D2", "nodes": [1, 2]}],
            nodes_of([(0.0, 0.0), (0.0, 0.0)]),
            role="door",
            label="door",
        )
    assert degenerate.value.code == "panel.degenerate_profile"


def test_self_intersecting_profile_is_rejected():
    points = [(0.0, 0.0), (2.0, 2.0), (0.0, 2.0), (2.0, 0.0)]
    with pytest.raises(deck.PreparationError) as error:
        deck.panel_order(chain(points), nodes_of(points), role="door", label="door")
    assert error.value.code == "panel.self_intersecting_profile"
    assert error.value.stage == "components"


def test_readiness_reports_the_same_typed_code_as_the_writer(monkeypatch, tmp_path):
    """Readiness must never say Ready when the writer deterministically refuses."""
    project = engineering.synthetic("Branched panel")
    mesh = generate_mesh(project)
    rigid = [
        element
        for element in mesh["elements"]
        if element["type"] == "R2D2" and element["component"] == "panel"
    ]
    # Attach an extra segment to the middle of the existing chain: a real branch.
    middle = rigid[len(rigid) // 2]["nodes"][0]
    extra = max(node["id"] for node in mesh["nodes"]) + 1
    mesh["nodes"].append({"id": extra, "xyz": [0.0, 50.0, 0.0]})
    mesh["elements"].append(
        {
            "id": max(element["id"] for element in mesh["elements"]) + 1,
            "type": "R2D2",
            "component": "panel",
            "entity": rigid[0].get("entity"),
            "nodes": [middle, extra],
        }
    )
    (tmp_path / "mesh.json").write_text(json.dumps(mesh), encoding="utf-8")
    monkeypatch.setattr(store, "job_dir", lambda _job: tmp_path)

    findings = []
    document = readiness._assembly({"id": "mesh-branch"}, project, findings)
    assert document["code"] == "panel.branched_profile"
    assert document["stage"] == "components"
    codes = [(item["code"], item["stage"]) for item in findings]
    assert ("panel.branched_profile", "components") in codes
    assert all(item["severity"] == "blocker" for item in findings)
    # The writer raises the same typed rejection for the same mesh.
    with pytest.raises(deck.PreparationError) as error:
        deck.assembly_assessment(project, mesh)
    assert error.value.code == "panel.branched_profile"


def test_worker_diagnostic_preserves_the_typed_code_and_stage():
    """A failed deck job carries the same stable reason readiness displayed."""
    from services.worker.__main__ import preparation_diagnostic

    error = deck.PreparationError(
        "panel.branched_profile",
        "The door profile branches at node 42.",
        stage="components",
        role="door",
        node=42,
    )
    diagnostic = preparation_diagnostic(error)
    assert diagnostic.startswith("panel.branched_profile [components]: ")
    assert "branches at node 42" in diagnostic
    # A failure without a typed code keeps its original message.
    assert preparation_diagnostic(ValueError("plain failure")) == "plain failure"
