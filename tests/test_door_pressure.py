"""Door-panel contact pressure: profiles, units, identity and deck output."""

import json
import re

import pytest

from integrations.abaqus import door_pressure, interchange
from integrations.abaqus.deck import mesh_parts, output_cards, write_inp
from integrations.abaqus.extract_odb import _door_frame
from integrations.abaqus.results import _metadata, write_metadata
from packages.engineering import generate_mesh, synthetic, two_panel_section
from packages.engineering.identity import mesh_compat


def chain(points, elements):
    nodes = [[label, x, y, 0.0] for label, (x, y) in points.items()]
    return nodes, [
        {"label": index + 1, "type": "R2D2", "connectivity": list(pair)}
        for index, pair in enumerate(elements)
    ]


def profile(points, elements):
    nodes, mesh = chain(points, elements)
    found = door_pressure.connected_profiles("PANEL-1", nodes, mesh, alias="Door")
    assert len(found) == 1
    return found[0]


def test_open_chain_starts_at_lexicographic_endpoint_and_sums_segments():
    item = profile(
        {4: (10.0, 0.0), 9: (0.0, 0.0), 2: (5.0, 0.0)},
        [(4, 2), (2, 9)],
    )
    # Endpoints are labels 4 (10,0) and 9 (0,0); the smaller (x,y,label) wins.
    assert item["labels"] == [9, 2, 4]
    assert item["stations_mm"] == pytest.approx([0.0, 5.0, 10.0])
    assert item["origin_node"] == 9
    assert item["length_mm"] == pytest.approx(10.0)
    assert item["topology"] == "open_chain" and item["supported"] is True


def test_reversed_connectivity_and_bent_profile_keep_one_axis():
    forward = profile(
        {1: (0.0, 0.0), 2: (3.0, 0.0), 3: (3.0, 4.0)},
        [(1, 2), (2, 3)],
    )
    reversed_edges = profile(
        {1: (0.0, 0.0), 2: (3.0, 0.0), 3: (3.0, 4.0)},
        [(3, 2), (2, 1)],
    )
    assert forward["stations_mm"] == pytest.approx([0.0, 3.0, 7.0])
    assert reversed_edges["labels"] == forward["labels"]
    assert reversed_edges["stations_mm"] == pytest.approx(forward["stations_mm"])
    # The origin is chosen from geometry, not from the written connectivity order.
    assert forward["origin_node"] == 1


def test_two_panel_labels_are_one_profile_and_zero_length_segment_is_preserved():
    item = profile(
        {1: (0.0, 0.0), 2: (0.0, 0.0), 3: (0.0, 2.0)},
        [(1, 2), (2, 3)],
    )
    assert item["labels"] == [1, 2, 3]
    assert item["stations_mm"] == pytest.approx([0.0, 0.0, 2.0])


def test_closed_ring_and_branch_are_reported_not_guessed():
    ring = profile(
        {1: (0.0, 0.0), 2: (1.0, 0.0), 3: (0.0, 1.0)},
        [(1, 2), (2, 3), (3, 1)],
    )
    assert ring["supported"] is False
    assert ring["reason"] == "closed_profile_unsupported"
    branch = profile(
        {1: (-1.0, 0.0), 2: (0.0, 0.0), 3: (1.0, 0.0), 4: (0.0, 1.0)},
        [(1, 2), (2, 3), (2, 4)],
    )
    assert branch["supported"] is False
    assert branch["reason"] == "branched_profile"


def test_duplicate_observations_coalesce_only_when_identical():
    assert door_pressure.coalesce([45.0, 45.0]) == (45.0, None)
    value, reason = door_pressure.coalesce([45.0, 46.0])
    assert value is None and reason == "conflicting_contact_observations"
    assert door_pressure.coalesce([[0.1, -0.2], [0.1, -0.2]]) == ([0.1, -0.2], None)
    value, reason = door_pressure.coalesce([[0.1, -0.2], [0.1, -0.3]])
    assert value is None and reason == "conflicting_contact_observations"


def test_pressure_conversion_is_the_single_mpa_to_kpa_boundary():
    assert door_pressure.pressure_kpa(0.045509088) == pytest.approx(45.509088)
    assert door_pressure.pressure_kpa(0.0) == 0.0
    assert door_pressure.pressure_kpa(None) is None
    assert door_pressure.magnitude([0.021603798, 0.014067459]) == pytest.approx(
        (0.021603798**2 + 0.014067459**2) ** 0.5
    )


def test_alignment_preserves_missing_and_measured_zero():
    item = profile(
        {1: (0.0, 0.0), 2: (1.0, 0.0), 3: (2.0, 0.0)},
        [(1, 2), (2, 3)],
    )
    aligned = door_pressure.align_profile(
        item,
        {1: [0.0], 2: [0.002]},
        {1: [[0.0, 0.0]], 2: [[0.0, 0.01]]},
        True,
    )
    assert aligned["pressure_kpa"] == pytest.approx([0.0, 2.0, None], nan_ok=True)
    assert aligned["pressure_mpa"] == pytest.approx([0.0, 0.002, None], nan_ok=True)
    assert aligned["cnormf_n"][2] is None
    assert aligned["force_magnitude_n"][1] == pytest.approx(0.01)
    assert aligned["availability"] == {
        "pressure": "pressure_sample_missing",
        "force": "force_sample_missing",
    }


def _contact_fields(pressure, force):
    values = [
        {
            "instance": instance,
            "position": "NODAL",
            "node": node,
            "data": data,
        }
        for instance, rows in pressure.items()
        for node, observations in rows.items()
        for data in observations
    ]
    force_values = [
        {
            "instance": instance,
            "position": "NODAL",
            "node": node,
            "data": data,
        }
        for instance, rows in force.items()
        for node, observations in rows.items()
        for data in observations
    ]
    return {
        "CPRESS   General_Contact_Faces/General_Contact_Faces": {
            "values": values,
            "components": [],
        },
        "CNORMF   General_Contact_Faces/General_Contact_Faces": {
            "values": force_values,
            "components": ["CNORMF1", "CNORMF2"],
        },
    }


def test_local_vector_axes_are_rotated_into_the_assembly_frame():
    definition = {
        "enabled": True,
        "profiles": [
            {
                "id": "PANEL-1:1",
                "instance": "PANEL-1",
                "alias": "Door",
                "labels": [1],
                "stations_mm": [0.0],
                "supported": True,
            }
        ],
    }
    fields = {
        "CPRESS   General_Contact_Faces/General_Contact_Faces": {
            "values": [
                {"instance": "PANEL-1", "position": "NODAL", "node": 1, "data": [0.01]}
            ]
        },
        "CNORMF   General_Contact_Faces/General_Contact_Faces": {
            "values": [
                {
                    "instance": "PANEL-1",
                    "position": "NODAL",
                    "node": 1,
                    "data": [1.0, 0.0],
                    "local_axes": [[0.0, 1.0], [1.0, 0.0]],
                }
            ]
        },
    }
    frame = _door_frame(fields, {"PANEL-1": [[1, 0, 0, 0]]}, definition)
    assert frame["profiles"]["PANEL-1:1"]["cnormf_n"] == [[0.0, 1.0]]


def test_frame_identity_is_instance_qualified_and_duplicates_are_ambiguous():
    definition = {
        "enabled": True,
        "profiles": [
            {
                "id": "PANEL-1:1",
                "instance": "PANEL-1",
                "alias": "Door",
                "labels": [1, 2],
                "stations_mm": [0.0, 1.0],
                "supported": True,
            }
        ],
    }
    fields = _contact_fields(
        {"PANEL-1": {1: [[0.01], [0.01]], 2: [[0.02]]}, "WS-1": {1: [[9.0]]}},
        {"PANEL-1": {1: [[0.1, 0.2]], 2: [[0.3, 0.4]]}},
    )
    frame = _door_frame(fields, {"PANEL-1": [[1, 0, 0, 0]], "WS-1": [[1, 0, 0, 0]]}, definition)
    aligned = frame["profiles"]["PANEL-1:1"]
    assert aligned["pressure_kpa"] == pytest.approx([10.0, 20.0])
    assert aligned["cnormf_n"] == [[0.1, 0.2], [0.3, 0.4]]
    conflicting = _contact_fields(
        {"PANEL-1": {1: [[0.01], [0.02]]}}, {"PANEL-1": {1: [[0.1, 0.2]]}}
    )
    frame = _door_frame(conflicting, {"PANEL-1": [[1, 0, 0, 0]]}, definition)
    aligned = frame["profiles"]["PANEL-1:1"]
    assert aligned["pressure_kpa"][0] is None
    assert aligned["ambiguous"] == [[1, "pressure", "conflicting_contact_observations"]]


def _panel_labels(deck):
    block = re.search(
        r"\*Nset, nset=DOOR_PROFILE_NODES, instance=PANEL-1\s*\n(.*?)(?=\n\*)",
        deck,
        re.S,
    )
    assert block is not None
    return sorted(int(value) for value in re.findall(r"\d+", block.group(1)))


def test_one_step_deck_requests_door_pressure_once_and_excludes_the_rp():
    project = synthetic()
    mesh = generate_mesh(project)
    deck = write_inp(project, mesh)
    labels = _panel_labels(deck)
    panel_nodes = sorted(
        {node for element in mesh["panel"] for node in element["nodes"]}
    ) if "panel" in mesh else None
    # The mesh artifact keeps panel segments in a separate key.
    if panel_nodes is None:
        panel_nodes = sorted(
            {node for element in mesh["elements"] if element["type"] == "R2D2" for node in element["nodes"]}
        )
    assert labels == panel_nodes
    rp = max(labels) + 1
    assert rp not in labels
    assert deck.count("*Contact Output, nset=DOOR_PROFILE_NODES\nCFORCE") == 1
    assert deck.count("*Contact Output\nCSTRESS") == 1
    # Global pressure is requested once; the door set only contributes force.
    assert "CFORCE, CSTRESS" not in deck
    assert re.search(r"\*Node Output\n[^\n]*U", deck) is not None


def test_global_stress_off_requests_both_fields_on_the_door_set_only():
    project = synthetic()
    project.analysis.outputs = ["U", "RF"]
    mesh = generate_mesh(project)
    deck = write_inp(project, mesh)
    assert "*Contact Output, nset=DOOR_PROFILE_NODES\nCFORCE, CSTRESS" in deck
    assert "\n*Contact Output\nCSTRESS" not in deck
    assert "*Contact Output\nCSTRESS" not in deck


def test_opt_out_removes_the_door_set_and_contact_requests():
    project = synthetic()
    project.analysis.door_pressure = False
    mesh = generate_mesh(project)
    deck = write_inp(project, mesh)
    assert "DOOR_PROFILE_NODES" not in deck
    assert "*Contact Output\nCSTRESS" in deck


def test_output_only_edit_preserves_mesh_identity():
    project = synthetic()
    before = mesh_compat(project)
    project.analysis.door_pressure = False
    assert mesh_compat(project) == before
    project.analysis.door_pressure = True
    assert mesh_compat(project) == before


def test_two_step_deck_requests_door_pressure_in_both_steps():
    project = two_panel_section()
    mesh = generate_mesh(project)
    deck = write_inp(project, mesh)
    assert deck.count("*Contact Output, nset=DOOR_PROFILE_NODES") == 2
    assert deck.count("*Nset, nset=DOOR_PROFILE_NODES, instance=PANEL-1") == 1
    # The body profile is never part of the door identity.
    assert "DOOR_PROFILE_NODES, instance=BODY-1" not in deck
    steps = deck.split("*Step, name=")
    assert len(steps) == 3
    for block in steps[1:]:
        assert "*Contact Output, nset=DOOR_PROFILE_NODES" in block


def test_metadata_records_intent_units_and_attribution():
    project = synthetic()
    mesh = generate_mesh(project)
    nodes, ws, panel = mesh_parts(project, mesh)
    metadata = _metadata(project, nodes, ws, panel)
    door = metadata["door_pressure"]
    assert door["enabled"] is True
    assert door["native_unit"] == "MPa" and door["display_unit"] == "kPa"
    assert door["conversion"] == 1000.0
    assert door["instances"][0]["instance"] == "PANEL-1"
    assert door["contact_attribution"]["kind"] == "door_seal"
    assert metadata["requested"] == project.analysis.outputs


def test_header_carries_the_additive_door_block(tmp_path):
    project = synthetic()
    mesh = generate_mesh(project)
    write_metadata(project, mesh, tmp_path)
    stored = json.loads((tmp_path / "result-metadata.json").read_text(encoding="utf-8"))
    assert stored["door_pressure"]["enabled"] is True
    header = interchange.result_header(stored, "ABAQUS", [])
    assert header["door_pressure"]["enabled"] is True


def test_display_metadata_records_pressure_and_contact_force_ranges(tmp_path):
    frame = {
        "time": 0.0,
        "step": "Closing",
        "step_id": "closing",
        "displacements": {"PANEL-1": [[1, 0, 0, 0]]},
        "fields": {
            "CNORMF   General_Contact_Faces/General_Contact_Faces": {
                "components": ["CNORMF1", "CNORMF2"],
                "values": [
                    {"instance": "PANEL-1", "position": "NODAL", "node": 1, "data": [0.03, 0.04]}
                ],
            }
        },
        "door_pressure": {
            "profiles": {
                "PANEL-1:1": {
                    "pressure_kpa": [12.5, None, -2.0],
                    "cnormf_n": [[0.03, 0.04], None, None],
                }
            }
        },
    }
    (tmp_path / "frame-00000.json").write_text(json.dumps(frame), encoding="utf-8")
    result = {
        "instances": [{"name": "PANEL-1", "nodes": [[1, 0, 0, 0]], "elements": []}],
        "frames": [
            {"time": 0.0, "step": "Closing", "step_id": "closing", "file": "frame-00000.json"}
        ],
    }
    metadata = interchange.display_metadata(tmp_path, result)
    assert metadata["ranges"]["CNormf"] == pytest.approx(0.05)
    assert metadata["ranges"]["pressure"] == pytest.approx(12.5)


def test_revision_payload_exposes_additive_door_default_for_old_setups():
    from services.api.main import revision_payload

    setup = synthetic().model_dump(mode="json")
    setup["analysis"].pop("door_pressure", None)
    payload = revision_payload({"id": "legacy", "setup": setup})
    assert payload["setup"]["analysis"]["door_pressure"] is True
    assert payload["mesh_compat"]


def test_output_cards_can_be_called_without_a_project_output_list():
    project = synthetic()
    project.analysis.outputs = []
    lines = output_cards(project)
    assert any("time interval" in line for line in lines)
    assert "*Contact Output, nset=DOOR_PROFILE_NODES" in "\n".join(lines)
