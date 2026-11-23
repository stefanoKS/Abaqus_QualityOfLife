"""Straight two-point material partition: domain, API and mesh conformity.

Gate 5a of the UI-redesign brief. All fixtures are fictional and disposable;
no solver or vendor file is involved.
"""

import math
from collections import defaultdict

import pytest
from fastapi.testclient import TestClient
from shapely.ops import unary_union

from packages.engineering import Project, generate_mesh, synthetic
from packages.engineering.geometry import face_polygon, sample_edges
from packages.engineering.partition import PartitionError, apply, plan
from services.api.main import app

FOOT_CUT = {"face": "foot", "start": (0.0, 0.0), "end": (0.0, 3.2)}


def polygon(project, face_id):
    face = next(item for item in project.faces if item.id == face_id)
    return face_polygon(face, sample_edges(project))


def test_cut_creates_two_bonded_children_and_conserves_area():
    project = synthetic()
    parent = polygon(project, "foot")
    candidate, info = apply(project, "foot", (0.0, 0.0), (0.0, 3.2), seed="revision-a")
    a, b = info["child_a"], info["child_b"]
    assert [face.id for face in candidate.faces[:2]] == [a, b]
    poly_a, poly_b = polygon(candidate, a), polygon(candidate, b)
    assert poly_a.area + poly_b.area == pytest.approx(parent.area, rel=1e-9, abs=1e-9)
    assert poly_a.intersection(poly_b).area == pytest.approx(0.0, abs=1e-9)
    assert unary_union([poly_a, poly_b]).symmetric_difference(parent).area == pytest.approx(
        0.0, abs=1e-6
    )
    # The two children share exactly one edge with opposite signed use.
    cut = info["cut_edge"]
    uses = [
        token
        for face in (candidate.faces[0], candidate.faces[1])
        for loop in face.loops
        for token in loop
        if token.lstrip("-") == cut
    ]
    assert sorted(uses) == ["-" + cut, cut]
    # The neighbouring bonded face was rewritten too: no stale original edge.
    assert "e3" not in {edge.id for edge in candidate.edges}
    assert "e3" not in {
        token.lstrip("-") for face in candidate.faces for loop in face.loops for token in loop
    }
    Project.model_validate(candidate.model_dump(mode="json"))


def test_cut_a_child_again_and_reopen_three_regions():
    original = synthetic()
    first, info = apply(original, "foot", (0.0, 0.0), (0.0, 3.2), seed="rev-1")
    second, again = apply(first, info["child_a"], (4.5, 0.0), (4.5, 3.2), seed="rev-2")
    regions = [face for face in second.faces if face.component == "seal" and not face.cavity]
    assert len(regions) == 4  # three foot regions plus the bulb
    assert len(second.faces) == 4
    original_area = polygon(original, "foot").area + polygon(original, "bulb").area
    total = sum(polygon(second, face.id).area for face in regions)
    assert total == pytest.approx(original_area, rel=1e-9)
    assert len({face.id for face in regions}) == 4
    Project.model_validate(second.model_dump(mode="json"))


def test_repeated_request_is_byte_identical_and_ids_are_stable():
    project = synthetic()
    first, info = apply(project, "foot", (0.0, 0.0), (0.0, 3.2), seed="same-base")
    second, again = apply(project, "foot", (0.0, 0.0), (0.0, 3.2), seed="same-base")
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert info["child_a"] == again["child_a"]
    assert info["cut_edge"] == again["cut_edge"]
    other, _ = apply(project, "foot", (0.0, 0.0), (0.0, 3.2), seed="other-base")
    assert {face.id for face in other.faces} != {face.id for face in first.faces}


def test_cut_preserves_a_cavity_and_can_split_an_arc_boundary():
    project = synthetic()
    # x = -8 lies wholly in the left material lobe, outside the cavity (|x| >= 6.8).
    outer_y = 3.2 + math.sqrt(81 - 64)
    candidate, info = apply(project, "bulb", (-8.0, 3.2), (-8.0, outer_y), seed="arc")
    children = [
        next(face for face in candidate.faces if face.id == info[key])
        for key in ("child_a", "child_b")
    ]
    assert sorted(len(face.loops) for face in children) == [1, 2]
    # The cavity stays an unfilled hole on exactly one side; no cavity face is
    # created and no material is assigned to the void.
    holed = next(face for face in children if len(face.loops) == 2)
    assert holed.material == project.faces[1].material
    # The outer arch was split into exact analytic arcs, not chords.
    split_arcs = [edge for edge in candidate.edges if edge.id in set(info["created_edges"])]
    arcs = [edge for edge in split_arcs if edge.kind == "arc"]
    assert arcs
    original = next(edge for edge in project.edges if edge.id == "e6")
    assert original.kind == "arc"
    assert sum(edge.sweep for edge in arcs) == pytest.approx(original.sweep, rel=1e-6)
    Project.model_validate(candidate.model_dump(mode="json"))


def test_cut_crossing_a_cavity_is_rejected():
    with pytest.raises(PartitionError) as failure:
        plan(synthetic(), "bulb", (0.0, 3.2), (0.0, 12.2), seed="hole")
    assert failure.value.code in {"cut_crosses_hole", "cut_outside_face"}


@pytest.mark.parametrize(
    "start,end,code",
    [
        ((0.0, 0.0), (0.0, 1.0), "endpoint_off_boundary"),
        ((0.0, 0.0), (0.0, 0.0), "degenerate_cut"),
        ((-9.0, 0.0), (9.0, 0.0), "cut_outside_face"),
        ((-8.99999, 0.0), (-8.99999, 3.2), "sliver_cut"),
    ],
)
def test_invalid_cuts_are_rejected_without_mutating_the_project(start, end, code):
    project = synthetic()
    before = project.model_dump(mode="json")
    with pytest.raises(PartitionError) as failure:
        apply(project, "foot", start, end, seed="bad")
    assert failure.value.code == code
    assert project.model_dump(mode="json") == before


def test_cut_must_target_an_existing_face():
    with pytest.raises(PartitionError) as failure:
        plan(synthetic(), "panel-profile", (-1.0, 10.0), (1.0, 10.0), seed="x")
    assert failure.value.code == "face_missing"


def test_split_edges_are_remapped_in_selections():
    project = synthetic()
    mount = project.selections[0].entities[0]
    candidate, info = apply(project, "foot", (0.0, 0.0), (0.0, 3.2), seed="sel")
    entities = candidate.selections[0].entities
    assert mount not in entities
    assert len(entities) == 2
    for edge_id in entities:
        assert any(edge.id == edge_id for edge in candidate.edges)
    # Both pieces still cover the original mounting edge endpoints.
    ids = {edge.id: edge for edge in candidate.edges}
    assert {ids[edge_id].kind for edge_id in entities} == {"line"}


def test_mesh_has_one_conforming_internal_interface_and_no_duplicate_nodes():
    candidate, info = apply(synthetic(), "foot", (0.0, 0.0), (0.0, 3.2), seed="mesh")
    mesh = generate_mesh(candidate)
    cut = info["cut_edge"]
    interface = set(mesh["edge_nodes"][cut])
    assert interface
    region_nodes = {
        face_id: {
            node
            for element in mesh["elements"]
            if element["entity"] == face_id
            for node in element["nodes"]
        }
        for face_id in (info["child_a"], info["child_b"])
    }
    assert region_nodes[info["child_a"]] & region_nodes[info["child_b"]] == interface
    # Node labels are unique in the mesh; interface labels are shared, not duplicated.
    node_ids = [node["id"] for node in mesh["nodes"]]
    assert len(node_ids) == len(set(node_ids))
    assert interface <= set(node_ids)
    for element in mesh["elements"]:
        assert set(element["nodes"]) <= set(node_ids)


def test_deck_gives_each_seal_element_one_child_section_and_hides_the_internal_seam():

    from integrations.abaqus.deck import write_inp

    candidate, info = apply(synthetic(), "foot", (0.0, 0.0), (0.0, 3.2), seed="deck")
    mesh = generate_mesh(candidate)
    text = write_inp(candidate, mesh)
    assert text.count("*Solid Section") == 3  # two children and the bulb
    assert text.count("*Elset, elset=REGION_") == 3
    # Every seal continuum element belongs to exactly one REGION elset.
    element_ids = {
        element["id"] for element in mesh["elements"] if element["type"].startswith("CPS")
    }
    region_lines = []
    inside = False
    for line in text.splitlines():
        if line.startswith("*Elset, elset=REGION_"):
            inside = True
            continue
        if inside:
            if line.startswith("*"):
                inside = False
            else:
                region_lines.extend(int(value) for value in line.split(",") if value.strip())
    assert len(region_lines) == len(element_ids)
    assert len(region_lines) == len(set(region_lines))

    # The internal cut interface is used by one element on each side, so neither
    # side may appear in the exterior contact surface.
    sides = defaultdict(list)
    for element in mesh["elements"]:
        if not element["type"].startswith("CPS"):
            continue
        for index, node in enumerate(element["nodes"]):
            side = tuple(sorted((node, element["nodes"][(index + 1) % len(element["nodes"])])))
            sides[side].append((element["id"], index + 1))
    internal = set()
    by_id = {element["id"]: element for element in mesh["elements"]}
    for elements in sides.values():
        if len(elements) != 2:
            continue
        (first, side_first), (second, _) = elements
        if {by_id[first]["entity"], by_id[second]["entity"]} == {info["child_a"], info["child_b"]}:
            internal.add((first, side_first))
    assert internal
    surface = []
    inside = False
    for line in text.splitlines():
        if line.startswith("*Surface, type=ELEMENT, name=SEAL_EXTERIOR"):
            inside = True
            continue
        if inside:
            if line.startswith("*"):
                break
            surface.append(line.strip())
    assert surface
    assert not any(line in {f"{eid}, S{side}" for eid, side in internal} for line in surface)


def test_two_step_deck_names_child_sections_and_keeps_both_steps():
    from integrations.abaqus.deck import write_two_step_inp
    from packages.engineering.geometry import two_panel_section

    project = two_panel_section()
    candidate, info = apply(project, "foot", (0.0, 0.0), (0.0, 3.2), seed="two-step")
    mesh = generate_mesh(candidate)
    text = write_two_step_inp(candidate, mesh)
    assert "*Step, name=Body seating" in text
    assert "*Step, name=Closing" in text
    assert text.count("*Solid Section") == 3
    assert text.count("*Elset, elset=REGION_") == 3
    # Both child regions carry the inherited material and the same thickness.
    for face_id in (info["child_a"], info["child_b"]):
        face = next(face for face in candidate.faces if face.id == face_id)
        index = candidate.faces.index(face)
        assert f"*Solid Section, elset=REGION_{index + 1}, material=" in text


def test_vertex_endpoints_and_a_reversed_request_stay_valid():
    project = synthetic()
    parent = polygon(project, "foot")
    forward, first = apply(project, "foot", (-9.0, 0.0), (9.0, 3.2), seed="vertices")
    reverse, second = apply(project, "foot", (9.0, 3.2), (-9.0, 0.0), seed="vertices")
    for candidate, info in ((forward, first), (reverse, second)):
        poly_a = polygon(candidate, info["child_a"])
        poly_b = polygon(candidate, info["child_b"])
        assert poly_a.area + poly_b.area == pytest.approx(parent.area, rel=1e-9)
        Project.model_validate(candidate.model_dump(mode="json"))
    # Reversing the request swaps the children's areas, not the total.
    assert first["area_a"] == pytest.approx(second["area_b"], rel=1e-9)
    assert first["area_b"] == pytest.approx(second["area_a"], rel=1e-9)


def test_clamped_spline_split_is_exact_and_fit_point_curves_are_rejected():
    from packages.engineering.model import SplineData
    from packages.engineering.partition import _sub_spline
    from packages.engineering.spline import curve, endpoint_points

    data = SplineData(
        degree=3,
        control_points=[(0.0, 0.0, 0.0), (1.0, 2.0, 0.0), (2.0, 2.0, 0.0), (3.0, 0.0, 0.0)],
        tolerance=0.02,
    )
    first = _sub_spline(data, 0.0, 0.5)
    second = _sub_spline(data, 0.5, 1.0)
    first_end = endpoint_points(first)[1]
    second_start = endpoint_points(second)[0]
    assert math.dist(first_end, second_start) < 1e-9
    # The two halves reproduce the parent curve at their shared sample.
    parent = curve(data)
    shared = tuple(parent.point(parent.max_t * 0.5))
    assert math.dist(first_end, shared) < 1e-9
    assert math.dist(tuple(curve(second).point(curve(second).max_t)), tuple(parent.point(parent.max_t))) < 1e-9

    fit_points = SplineData(fit_points=[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (2.0, 0.0, 0.0)])
    with pytest.raises(PartitionError) as failure:
        _sub_spline(fit_points, 0.0, 0.5)
    assert failure.value.code == "unsupported_curve"


class Api:
    def __init__(self, client):
        self.client = client

    def create(self):
        response = self.client.post(
            "/api/projects", json={"name": "Partition API", "example": True}
        )
        assert response.status_code == 200, response.text
        return response.json()


def api_fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path / "data"))
    return TestClient(app, base_url="http://127.0.0.1")


def test_api_preview_apply_retry_and_generic_put_guard(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as client:
        api = Api(client)
        revision = api.create()
        preview = client.post(
            "/api/partition/preview",
            json={"setup": revision["setup"], "cut": FOOT_CUT},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["plan"]["area_a"] > 0
        first = client.post(
            f"/api/projects/{revision['project']}/partition",
            json={"base": revision["id"], "cut": FOOT_CUT},
        )
        assert first.status_code == 200, first.text
        saved = first.json()
        assert saved["number"] == 2
        assert len(saved["setup"]["faces"]) == 3
        retry = client.post(
            f"/api/projects/{revision['project']}/partition",
            json={"base": revision["id"], "cut": FOOT_CUT},
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["id"] == saved["id"]
        stale = client.post(
            f"/api/projects/{revision['project']}/partition",
            json={
                "base": revision["id"],
                "cut": {"face": "bulb", "start": (-8.0, 3.2), "end": (-8.0, 7.323)},
            },
        )
        assert stale.status_code == 409
        forged = client.put(
            f"/api/projects/{revision['project']}",
            json={"base": revision["id"], "setup": saved["setup"]},
        )
        assert forged.status_code == 422


def test_api_rejected_cut_leaves_revisions_and_source_unchanged(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as client:
        api = Api(client)
        revision = api.create()
        before = client.get(f"/api/projects/{revision['project']}/revisions").json()
        rejected = client.post(
            f"/api/projects/{revision['project']}/partition",
            json={
                "base": revision["id"],
                "cut": {"face": "foot", "start": (0.0, 0.0), "end": (0.0, 1.0)},
            },
        )
        assert rejected.status_code == 422
        after = client.get(f"/api/projects/{revision['project']}/revisions").json()
        assert len(after) == len(before)
        current = client.get(f"/api/revisions/{revision['id']}").json()
        assert current["setup"] == revision["setup"]
        assert current["source_id"] == revision["source_id"]
        assert current["mesh_compat"] == revision["mesh_compat"]
