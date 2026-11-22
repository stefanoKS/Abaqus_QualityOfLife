"""Two-step body seating then door closing: model, mesh, deck and metadata.

License-free tests only. They prove the generated sequence and identities; they
do not claim physical validation (Gate 4B needs a licensed run).
"""

import pytest

from integrations.abaqus import deck, interchange, results
from packages import engineering
from packages.engineering import fixture as fixtures
from packages.engineering.mesh import generate_mesh
from packages.engineering.model import Component, Edge, Vertex


def two_step_project():
    project = engineering.synthetic("Two-panel section")
    panel = next(edge for edge in project.edges if edge.component == "panel")
    start = next(vertex for vertex in project.vertices if vertex.id == panel.start)
    end = next(vertex for vertex in project.vertices if vertex.id == panel.end)
    project.components.append(
        Component(id="body", name="Body profile", role="vehicle_body")
    )
    project.vertices.append(Vertex(id="body-v1", xyz=(start.xyz[0], start.xyz[1] + 6, 0)))
    project.vertices.append(Vertex(id="body-v2", xyz=(end.xyz[0], end.xyz[1] + 6, 0)))
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
    project.motion.body.travel = -3.0
    project.motion.body.duration = 1.0
    return project


def fixture_labels(project, mesh):
    selection = next(
        item for item in project.selections if item.id == project.mounting.selection
    )
    return fixtures.from_edges(mesh, selection.entities)


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


def test_two_step_validation_requires_a_body_and_body_travel():
    project = two_step_project()
    project.motion.body.travel = 0
    with pytest.raises(ValueError, match="body travel"):
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
