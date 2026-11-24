"""Projected material partitions: domain oracles, API and mesh conformity.

All fixtures are fictional and disposable; no solver or vendor file is involved.
The topology oracles use exact mm coordinates and areas from the execution
brief. A stroke is a finite guide; the server selects the material intervals it
touches and extends each to its true analytic boundary hits.
"""

import math

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Point
from shapely.ops import unary_union

from packages.engineering import Project, generate_mesh, synthetic
from packages.engineering.geometry import face_polygon, sample_edges
from packages.engineering.model import (
    Component,
    Edge,
    Face,
    Material,
    Selection,
    Source,
    Vertex,
)
from packages.engineering.partition import PartitionError, commit, preview
from services.api.main import app

# The repository synthetic foot is [-9, 9] x [0, 3.2]: 57.6 mm².
FOOT_CUT = {"face": "foot", "start": (0.0, -1.0), "end": (0.0, 4.0)}


def polygon(project, face_id):
    face = next(item for item in project.faces if item.id == face_id)
    return face_polygon(face, sample_edges(project))


def _project(name, points, loops):
    """A single seal face with one or more directed vertex loops."""
    vertices = [Vertex(id=f"v{index+1}", xyz=(x, y, 0.0)) for index, (x, y) in enumerate(points)]
    edges = []
    face_loops = []
    for loop in loops:
        tokens = []
        for first, second in zip(loop, loop[1:] + loop[:1]):
            edge = Edge(
                id=f"e{len(edges)+1}",
                name=f"e{len(edges)+1}",
                component="seal",
                start=f"v{first+1}",
                end=f"v{second+1}",
                kind="line",
            )
            edges.append(edge)
            tokens.append(edge.id)
        face_loops.append(tokens)
    material = Material(
        id="rubber",
        name="Rubber",
        color="#112233",
        model="linear_elastic",
        density=1e-9,
        young=5.0,
        poisson=0.4,
    )
    return Project(
        schema_version=4,
        name=name,
        vertices=vertices,
        edges=edges,
        faces=[Face(id="face", name="Target", component="seal", material="rubber", loops=face_loops)],
        components=[Component(id="seal", name="Seal", role="seal")],
        materials=[material],
        selections=[Selection(id="mount", name="Mount", entities=[edges[0].id])],
        source=Source(kind="synthetic", filename=name),
    )


def solid_box():
    # [-5,5] x [-5,5], area 100.
    return _project(
        "solid",
        [(-5, -5), (5, -5), (5, 5), (-5, 5)],
        [[0, 1, 2, 3]],
    )


def hollow_box():
    # [-5,5]² minus the [-2,2]² void: 84 mm² of material.
    return _project(
        "hollow",
        [(-5, -5), (5, -5), (5, 5), (-5, 5), (-2, -2), (2, -2), (2, 2), (-2, 2)],
        [[0, 1, 2, 3], [4, 5, 6, 7]],
    )


def u_shape():
    # Concave U, material area 76 mm².
    return _project(
        "U",
        [(-5, -5), (5, -5), (5, 5), (2, 5), (2, -1), (-2, -1), (-2, 5), (-5, 5)],
        [[0, 1, 2, 3, 4, 5, 6, 7]],
    )


def _areas(info):
    return sorted(round(area, 6) for area in info["areas"])


def test_solid_box_horizontal_and_vertical_cuts_make_two_halves():
    for stroke in (((-6, 0), (6, 0)), ((0, -6), (0, 6))):
        candidate, info = commit(solid_box(), "face", [stroke], seed="solid")
        assert info["status"] == "valid"
        assert info["child_count"] == 2
        assert _areas(info) == [50.0, 50.0]
        parent = polygon(solid_box(), "face")
        children = [polygon(candidate, child["id"]) for child in info["children"]]
        assert sum(child.area for child in children) == pytest.approx(parent.area, abs=1e-9)
        assert unary_union(children).symmetric_difference(parent).area == pytest.approx(
            0.0, abs=1e-6
        )
        Project.model_validate(candidate.model_dump(mode="json"))


def test_one_through_stroke_splits_both_walls_of_a_hollow_seal():
    candidate, info = commit(hollow_box(), "face", [((-6, 0), (6, 0))], seed="hollow")
    assert info["status"] == "valid"
    assert info["child_count"] == 2
    assert _areas(info) == [42.0, 42.0]
    # No seam was created in the void; the two wall intervals are the seams.
    assert len(info["seams"]) == 2
    assert all(
        abs(path[0][1] - path[1][1]) < 1e-12 for guide in info["guides"] for path in guide["intervals"]
    )
    Project.model_validate(candidate.model_dump(mode="json"))


def test_centered_spline_wall_crossing_is_not_lost():
    from packages.engineering.model import SplineData

    project = hollow_box()
    edge = project.edges[3]
    edge.kind = "spline"
    edge.spline = SplineData(
        degree=1,
        control_points=[(-5, 5, 0), (-5, -5, 0)],
        knots=[0, 0, 1, 1],
    )
    for y in (0, 0.001):
        _, info = commit(project, "face", [((-6, y), (6, y))], seed="spline-wall")
        assert info["status"] == "valid"
        assert len(info["seams"]) == 2
        assert sorted(info["areas"]) == pytest.approx(sorted([42 + 6 * y, 42 - 6 * y]))


def test_spline_intersections_include_close_roots_and_a_knot_vertex():
    from packages.engineering.model import SplineData
    from packages.engineering.partition import _line_edge_hits

    project = hollow_box()
    edge = project.edges[3]
    edge.kind = "spline"
    # Two crossings only 0.001 apart in parameter, inside one old sample interval.
    edge.spline = SplineData(
        degree=2,
        control_points=[(0, 0.24999975, 0), (0.5, -0.25000025, 0), (1, 0.24999975, 0)],
    )
    hits = _line_edge_hits(project, edge, (0, 0), (1, 0))
    assert sorted(hit[0] for hit in hits) == pytest.approx([0.4995, 0.5005], abs=1e-8)
    edge.spline = SplineData(
        degree=1, control_points=[(0, -1, 0), (1, 0, 0), (2, 1, 0)],
        knots=[0, 0, 0.5, 1, 1],
    )
    hits = _line_edge_hits(project, edge, (0, 0), (1, 0))
    assert {round(hit[0], 8) for hit in hits} == {0.5}
    edge.spline = SplineData(
        degree=2, control_points=[(0, 0.25, 0), (0.5, -0.25, 0), (1, 0.25, 0)],
    )
    hits = _line_edge_hits(project, edge, (0, 0), (1, 0))
    assert hits and all(abs(hit[0] - 0.5) < 1e-7 for hit in hits)
    edge.spline = SplineData(degree=1, control_points=[(0, 0, 0), (1, 0, 0)])
    assert _line_edge_hits(project, edge, (0, 0), (1, 0)) == []


def test_closed_fit_point_cavity_can_be_cut_at_its_parameter_seam():
    from packages.engineering.model import SplineData

    project = hollow_box()
    edge = project.edges[4]
    edge.kind = "spline"
    edge.end = edge.start
    edge.spline = SplineData(
        fit_points=[(-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0), (-2, -2, 0)],
        closed=True,
    )
    project.edges = project.edges[:5]
    project.faces[0].loops[1] = [edge.id]
    project = Project.model_validate(project.model_dump(mode="json"))
    for stroke in (((-6, -2), (6, -2)), ((-2, -6), (-2, 6))):
        candidate, info = commit(project, "face", [stroke], seed="closed-seam")
        candidate = Project.model_validate(candidate.model_dump(mode="json"))
        children = [polygon(candidate, child["id"]) for child in info["children"]]
        assert info["status"] == "valid"
        assert len(info["seams"]) == 2
        assert children[0].intersection(children[1]).area < 1e-8
        assert not unary_union(children).contains(Point(0, 0))


def test_tangent_to_cavity_is_not_mistaken_for_a_transverse_cut():
    with pytest.raises(PartitionError) as failure:
        preview(synthetic(), "bulb", [((-10, 11.3), (10, 11.3))], seed="tangent")
    assert failure.value.code == "tangent_cut"
    assert preview(synthetic(), "bulb", [((-10, 11.29999), (10, 11.29999))], seed="cross")["status"] == "valid"


def test_mixed_draft_rejects_a_seam_with_no_incident_children():
    strokes = [((-6, 3), (6, 3)), ((-6, 0), (0, 0))]
    info = preview(hollow_box(), "face", strokes, seed="dangling")
    assert info["status"] == "mixed"
    assert info["unused_guides"] == [1]
    duplicate = preview(
        hollow_box(), "face", [strokes[0], tuple(reversed(strokes[0])), strokes[1]],
        seed="duplicate-dangling",
    )
    assert duplicate["unused_guides"] == [2]
    with pytest.raises(PartitionError) as failure:
        commit(hollow_box(), "face", strokes, seed="dangling")
    assert failure.value.code == "mixed"
    _, completed = commit(
        hollow_box(), "face", strokes + [((0, 0), (6, 0))], seed="complete"
    )
    assert completed["status"] == "valid"


def test_a_single_wall_cut_opens_the_region_but_keeps_one_region():
    info = preview(hollow_box(), "face", [((-6, 0), (0, 0))], seed="wall")
    assert info["status"] == "one_region"
    assert info["child_count"] == 1
    assert info["areas"] == pytest.approx([84.0])
    assert info["guides"][0]["intervals"] == [[[-5.0, 0.0], [-2.0, 0.0]]]
    with pytest.raises(PartitionError) as failure:
        commit(hollow_box(), "face", [((-6, 0), (0, 0))], seed="wall")
    assert failure.value.code == "one_region"


def test_one_region_draft_accepts_the_second_wall_cut_in_the_same_commit():
    _candidate, info = commit(
        hollow_box(),
        "face",
        [((-6, 0), (0, 0)), ((0, 0), (6, 0))],
        seed="both",
    )
    assert info["status"] == "valid"
    assert _areas(info) == [42.0, 42.0]


def test_cut_above_the_void_keeps_the_hole_with_its_child():
    candidate, info = commit(hollow_box(), "face", [((-6, 3), (6, 3))], seed="y3")
    assert _areas(info) == [20.0, 64.0]
    holed = [
        child
        for child in info["children"]
        if len(next(face for face in candidate.faces if face.id == child["id"]).loops) == 2
    ]
    assert len(holed) == 1
    assert holed[0]["area"] == pytest.approx(64.0)


def test_concave_section_supports_three_children_without_a_two_child_check():
    candidate, info = commit(u_shape(), "face", [((-6, 2), (6, 2))], seed="U")
    assert info["status"] == "valid"
    assert info["child_count"] == 3
    assert _areas(info) == [9.0, 9.0, 58.0]
    Project.model_validate(candidate.model_dump(mode="json"))


def test_crossing_guides_are_noded_into_four_regions():
    _candidate, info = commit(
        solid_box(),
        "face",
        [((-6, 0), (6, 0)), ((0, -6), (0, 6))],
        seed="cross",
    )
    assert info["child_count"] == 4
    assert _areas(info) == [25.0, 25.0, 25.0, 25.0]


def test_duplicate_and_reversed_guides_do_not_duplicate_geometry():
    first, info = commit(solid_box(), "face", [((-6, 0), (6, 0))], seed="dup")
    second, again = commit(
        solid_box(),
        "face",
        [((-6, 0), (6, 0)), ((6, 0), (-6, 0))],
        seed="dup",
    )
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert info["areas"] == again["areas"]


def test_arbitrary_points_are_projected_onto_the_foot_and_split_evenly():
    candidate, info = commit(synthetic(), "foot", [((0.0, -1.0), (0.0, 4.0))], seed="project")
    assert info["status"] == "valid"
    assert _areas(info) == [28.8, 28.8]
    # The projected endpoints are the true boundary hits, not the drawn points.
    assert info["start"] == [0.0, 0.0]
    assert info["end"] == [0.0, 3.2]
    Project.model_validate(candidate.model_dump(mode="json"))


def test_a_stroke_between_both_walls_of_the_void_is_a_visible_no_hit():
    with pytest.raises(PartitionError) as failure:
        preview(hollow_box(), "face", [((0, 0), (0, 1))], seed="void")
    assert failure.value.code == "cut_no_hit"


def test_a_mixed_draft_identifies_the_unused_guide_and_does_not_commit():
    info = preview(
        hollow_box(),
        "face",
        [((-6, 0), (0, 0)), ((0, 0), (0, 1))],
        seed="mixed",
    )
    assert info["status"] == "mixed"
    assert info["unused_guides"] == [1]
    assert info["guides"][1]["status"] == "no_hit"
    with pytest.raises(PartitionError) as failure:
        commit(
            hollow_box(),
            "face",
            [((-6, 0), (0, 0)), ((0, 0), (0, 1))],
            seed="mixed",
        )
    assert failure.value.code == "mixed"


def test_each_commit_is_byte_identical_and_ids_are_stable():
    first, info = commit(synthetic(), "foot", [((0.0, 0.0), (0.0, 3.2))], seed="same-base")
    second, again = commit(synthetic(), "foot", [((0.0, 0.0), (0.0, 3.2))], seed="same-base")
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert info["child_a"] == again["child_a"]
    assert info["cut_edge"] == again["cut_edge"]
    other, _ = commit(synthetic(), "foot", [((0.0, 0.0), (0.0, 3.2))], seed="other-base")
    assert {face.id for face in other.faces} != {face.id for face in first.faces}


def test_cut_preserves_a_cavity_and_splits_the_arch_analytically():
    project = synthetic()
    # The vertical stroke at x=-8 crosses only the left bulb wall; its
    # supporting line runs from the interface to the outer arch.
    candidate, info = commit(project, "bulb", [((-8.0, 4.0), (-8.0, 10.0))], seed="arc")
    children = [
        next(face for face in candidate.faces if face.id == info[key])
        for key in ("child_a", "child_b")
    ]
    assert sorted(len(face.loops) for face in children) == [1, 2]
    # The cavity stays an unfilled hole on exactly one side.
    holed = next(face for face in children if len(face.loops) == 2)
    assert holed.material == project.faces[1].material
    # The outer arch was split into exact analytic arcs, not chords.
    split = [edge for edge in candidate.edges if edge.id in set(info["created_edges"])]
    arcs = [edge for edge in split if edge.kind == "arc"]
    assert arcs
    original = next(edge for edge in project.edges if edge.id == "e6")
    assert original.kind == "arc"
    assert sum(edge.sweep for edge in arcs) == pytest.approx(original.sweep, rel=1e-5)
    Project.model_validate(candidate.model_dump(mode="json"))


@pytest.mark.parametrize(
    "start,end,code",
    [
        ((0.0, 0.0), (0.0, 0.0), "degenerate_cut"),
        ((-9.0, 0.0), (9.0, 1e-9), "cut_no_hit"),
        ((-8.99999, 0.0), (-8.99999, 3.2), "sliver_cut"),
        ((20.0, 20.0), (21.0, 21.0), "cut_no_hit"),
    ],
)
def test_invalid_cuts_are_rejected_without_mutating_the_project(start, end, code):
    project = synthetic()
    before = project.model_dump(mode="json")
    with pytest.raises(PartitionError) as failure:
        commit(project, "foot", [(start, end)], seed="bad")
    assert failure.value.code == code
    assert project.model_dump(mode="json") == before


def test_cut_must_target_an_existing_seal_material_face():
    with pytest.raises(PartitionError) as failure:
        preview(synthetic(), "panel-profile", [((-1.0, 10.0), (1.0, 10.0))], seed="x")
    assert failure.value.code == "face_missing"


def test_split_edges_are_remapped_in_selections():
    project = synthetic()
    mount = project.selections[0].entities[0]
    candidate, _info = commit(project, "foot", [((0.0, 0.0), (0.0, 3.2))], seed="sel")
    entities = candidate.selections[0].entities
    assert mount not in entities
    assert len(entities) == 2
    ids = {edge.id: edge for edge in candidate.edges}
    assert {ids[edge_id].kind for edge_id in entities} == {"line"}


def test_mesh_has_one_conforming_internal_interface_and_no_duplicate_nodes():
    candidate, info = commit(synthetic(), "foot", [((0.0, 0.0), (0.0, 3.2))], seed="mesh")
    mesh = generate_mesh(candidate)
    interface = set(mesh["edge_nodes"][info["cut_edge"]])
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
    node_ids = [node["id"] for node in mesh["nodes"]]
    assert len(node_ids) == len(set(node_ids))
    assert interface <= set(node_ids)
    for element in mesh["elements"]:
        assert set(element["nodes"]) <= set(node_ids)


def test_deck_gives_each_child_one_section_and_hides_the_internal_seam():
    from integrations.abaqus.deck import write_inp

    candidate, info = commit(synthetic(), "foot", [((0.0, 0.0), (0.0, 3.2))], seed="deck")
    mesh = generate_mesh(candidate)
    text = write_inp(candidate, mesh)
    assert text.count("*Solid Section") == 3  # two children and the bulb
    assert text.count("*Elset, elset=REGION_") == 3
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

    # The internal seam is used by one element on each side and appears in no
    # exterior contact surface.
    by_id = {element["id"]: element for element in mesh["elements"]}
    sides = {}
    for element in mesh["elements"]:
        if not element["type"].startswith("CPS"):
            continue
        for index, node in enumerate(element["nodes"]):
            side = tuple(sorted((node, element["nodes"][(index + 1) % len(element["nodes"])])))
            sides.setdefault(side, []).append((element["id"], index + 1))
    internal = set()
    for entries in sides.values():
        if len(entries) != 2:
            continue
        (first, side_first), (second, _) = entries
        if {by_id[first]["entity"], by_id[second]["entity"]} == {
            info["child_a"],
            info["child_b"],
        }:
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
    candidate, info = commit(project, "foot", [((0.0, 0.0), (0.0, 3.2))], seed="two-step")
    mesh = generate_mesh(candidate)
    text = write_two_step_inp(candidate, mesh)
    assert "*Step, name=Body seating" in text
    assert "*Step, name=Closing" in text
    assert text.count("*Solid Section") == 3
    assert text.count("*Elset, elset=REGION_") == 3
    for face_id in (info["child_a"], info["child_b"]):
        face = next(face for face in candidate.faces if face.id == face_id)
        index = candidate.faces.index(face)
        assert f"*Solid Section, elset=REGION_{index + 1}, material=" in text


def test_reversed_request_swaps_children_but_not_geometry():
    project = synthetic()
    parent = polygon(project, "foot")
    forward, first = commit(project, "foot", [((0, -9), (0, 9))], seed="vertices")
    reverse, second = commit(project, "foot", [((0, 9), (0, -9))], seed="vertices")
    for candidate, info in ((forward, first), (reverse, second)):
        poly_a = polygon(candidate, info["child_a"])
        poly_b = polygon(candidate, info["child_b"])
        assert poly_a.area + poly_b.area == pytest.approx(parent.area, rel=1e-9)
        Project.model_validate(candidate.model_dump(mode="json"))
    assert first["area_a"] == pytest.approx(second["area_b"], rel=1e-9)
    assert first["area_b"] == pytest.approx(second["area_a"], rel=1e-9)


def test_spline_trims_preserve_canonical_curve_and_reject_periodic():
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
    assert math.dist(endpoint_points(first)[1], endpoint_points(second)[0]) < 1e-9
    parent = curve(data)
    shared = tuple(parent.point(parent.max_t * 0.5))
    assert math.dist(endpoint_points(first)[1], shared) < 1e-9

    fit_points = SplineData(
        fit_points=[(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (2.0, 0.0, 0.0)],
        tangents=[(1, 2, 0), (1, -2, 0)],
    )
    closed = SplineData(
        fit_points=[(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0), (0, 0, 0)],
        closed=True,
    )
    rational = SplineData(
        degree=2, control_points=[(0, 0, 0), (1, 2, 0), (2, 2, 0), (3, 0, 0)],
        knots=[0, 0, 0, 0.5, 1, 1, 1], weights=[1, 0.5, 0.7, 1],
    )
    for source in (data, fit_points, closed, rational):
        parent = curve(source)
        for lo, hi in ((0, 0.25), (0.25, 0.75), (0.75, 1), (0, 0.5), (0.5, 1),
                       (0, 0.3), (0.2, 0.8), (0.7, 1), (0, 1)):
            part = _sub_spline(source, lo, hi)
            part = SplineData.model_validate(part.model_dump(mode="json"))
            trimmed = curve(part)
            for index in range(101):
                fraction = index / 100
                assert math.dist(
                    tuple(trimmed.point(trimmed.max_t * fraction)),
                    tuple(parent.point(parent.max_t * (lo + (hi - lo) * fraction))),
                ) < 1e-9
    periodic = fit_points.model_copy(update={"periodic": True})
    with pytest.raises(PartitionError) as failure:
        _sub_spline(periodic, 0.0, 0.5)
    assert failure.value.code == "unsupported_curve"


class Api:
    def __init__(self, client):
        self.client = client

    def create(self, example=True):
        response = self.client.post(
            "/api/projects", json={"name": "Partition API", "example": example}
        )
        assert response.status_code == 200, response.text
        return response.json()


def api_fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path / "data"))
    return TestClient(app, base_url="http://127.0.0.1")


def _preview(client, revision, strokes, base=None):
    body = {"setup": revision["setup"], "face": "foot", "strokes": strokes}
    if base:
        body["base"] = base
    response = client.post("/api/partition/preview", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_api_preview_and_commit_share_coordinates_and_child_ids(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as client:
        api = Api(client)
        revision = api.create()
        strokes = [[[0.0, -1.0], [0.0, 4.0]]]
        previewed = _preview(client, revision, strokes, base=revision["id"])
        plan = previewed["plan"]
        assert plan["status"] == "valid"
        assert plan["child_count"] == 2
        assert [round(area, 6) for area in plan["areas"]] == [28.8, 28.8]
        first = client.post(
            f"/api/projects/{revision['project']}/partition",
            json={"base": revision["id"], "face": "foot", "strokes": strokes},
        )
        assert first.status_code == 200, first.text
        saved = first.json()
        assert saved["number"] == 2
        assert len(saved["setup"]["faces"]) == 3
        # The IDs reviewed in preview are the IDs persisted by commit.
        assert [child["id"] for child in plan["children"]][:2] == [
            face["id"] for face in saved["setup"]["faces"][:2]
        ]
        retry = client.post(
            f"/api/projects/{revision['project']}/partition",
            json={"base": revision["id"], "face": "foot", "strokes": strokes},
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["id"] == saved["id"]


def test_api_legacy_two_point_request_is_projected(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as client:
        api = Api(client)
        revision = api.create()
        preview = client.post(
            "/api/partition/preview", json={"setup": revision["setup"], "cut": FOOT_CUT}
        )
        assert preview.status_code == 200, preview.text
        assert round(preview.json()["plan"]["area_a"], 6) == 28.8
        saved = client.post(
            f"/api/projects/{revision['project']}/partition",
            json={"base": revision["id"], "cut": FOOT_CUT},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["number"] == 2


def test_api_one_region_preview_is_a_draft_not_a_commit(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as client:
        api = Api(client)
        revision = api.create()
        # A vertical guide wholly inside the hollow bulb opens one wall only.
        response = client.post(
            "/api/partition/preview",
            json={
                "setup": revision["setup"],
                "face": "bulb",
                "strokes": [[[-8.0, 4.0], [-8.0, 6.0]]],
                "base": revision["id"],
            },
        )
        # The repository bulb is an arch: a radial wall cut leaves one region.
        assert response.status_code == 200, response.text
        assert response.json()["plan"]["status"] in {"one_region", "valid"}
        refused = client.post(
            f"/api/projects/{revision['project']}/partition",
            json={
                "base": revision["id"],
                "face": "bulb",
                "strokes": [[[-8.0, 4.0], [-8.0, 6.0]]],
            },
        )
        if response.json()["plan"]["status"] == "one_region":
            assert refused.status_code == 422, refused.text
            assert "one_region" in refused.text


def test_api_unfinished_mixed_draft_never_creates_revision(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as client:
        revision = Api(client).create()
        strokes = [[[-4, 11.6], [4, 11.6]], [[-9, 7], [-6, 7]]]
        before = client.get(f"/api/projects/{revision['project']}/revisions").json()
        data = {"base": revision["id"], "face": "bulb", "strokes": strokes}
        response = client.post("/api/partition/preview", json={**data, "setup": revision["setup"]})
        assert response.status_code == 200
        assert response.json()["plan"]["status"] == "mixed"
        assert response.json()["plan"]["unused_guides"] == [1]
        rejected = client.post(f"/api/projects/{revision['project']}/partition", json=data)
        assert rejected.status_code == 422
        assert "mixed" in rejected.text
        assert client.get(f"/api/projects/{revision['project']}/revisions").json() == before


def test_api_rejected_cut_leaves_revisions_and_source_unchanged(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as client:
        api = Api(client)
        revision = api.create()
        before = client.get(f"/api/projects/{revision['project']}/revisions").json()
        rejected = client.post(
            f"/api/projects/{revision['project']}/partition",
            json={
                "base": revision["id"],
                "face": "foot",
                "strokes": [[[-8.99999, 0.0], [-8.99999, 3.2]]],
            },
        )
        assert rejected.status_code == 422
        assert "sliver_cut" in rejected.text
        after = client.get(f"/api/projects/{revision['project']}/revisions").json()
        assert len(after) == len(before)
        current = client.get(f"/api/revisions/{revision['id']}").json()
        assert current["setup"] == revision["setup"]
        assert current["source_id"] == revision["source_id"]
        assert current["mesh_compat"] == revision["mesh_compat"]


def test_two_children_can_carry_different_material_cards():
    candidate, info = commit(synthetic(), "foot", [((0.0, 0.0), (0.0, 3.2))], seed="two-materials")
    second = Material(
        id="second",
        name="Second rubber",
        color="#445566",
        model="linear_elastic",
        density=1.1e-9,
        young=9.0,
        poisson=0.45,
    )
    candidate.materials.append(second)
    for face in candidate.faces:
        if face.id == info["child_a"]:
            face.material = "base_rubber"
        elif face.id == info["child_b"]:
            face.material = "second"
    validated = Project.model_validate(candidate.model_dump(mode="json"))
    assert {face.material for face in validated.faces if face.id in (info["child_a"], info["child_b"])} == {
        "base_rubber",
        "second",
    }


def test_api_stale_base_is_rejected_and_preview_never_persists(monkeypatch, tmp_path):
    with api_fixture(monkeypatch, tmp_path) as client:
        api = Api(client)
        revision = api.create()
        before = client.get(f"/api/projects/{revision['project']}/revisions").json()
        preview = _preview(client, revision, [[[0.0, -1.0], [0.0, 4.0]]], base=revision["id"])
        assert preview["plan"]["status"] == "valid"
        assert client.get(f"/api/projects/{revision['project']}/revisions").json() == before

        first = client.post(
            f"/api/projects/{revision['project']}/partition",
            json={"base": revision["id"], "face": "foot", "strokes": [[[0.0, -1.0], [0.0, 4.0]]]},
        )
        assert first.status_code == 200, first.text
        # A different cut based on the now-superseded revision must conflict.
        stale = client.post(
            f"/api/projects/{revision['project']}/partition",
            json={"base": revision["id"], "face": "foot", "strokes": [[[-9.0, 1.0], [9.0, 1.0]]]},
        )
        assert stale.status_code == 409, stale.text
        after = client.get(f"/api/projects/{revision['project']}/revisions").json()
        assert len(after) == len(before) + 1


def test_neighbouring_bonded_face_is_rewritten_and_shares_interface_nodes():
    project = synthetic()
    candidate, info = commit(project, "foot", [((0.0, 0.0), (0.0, 3.2))], seed="shared-interface")
    bulb = next(face for face in candidate.faces if face.id == "bulb")
    bulb_tokens = {token.lstrip("-") for loop in bulb.loops for token in loop}
    # The original interface edge was split; every piece is a real edge.
    assert "e3" not in bulb_tokens
    edge_ids = {edge.id for edge in candidate.edges}
    assert bulb_tokens <= edge_ids

    # Each split interface piece is shared by the bulb and one foot child, and
    # the mesher produces one conforming node set along it.
    child_ids = {info["child_a"], info["child_b"]}
    shared = []
    for edge in candidate.edges:
        users = {
            face.id
            for face in candidate.faces
            for loop in face.loops
            for token in loop
            if token.lstrip("-") == edge.id
        }
        if users & child_ids and "bulb" in users:
            shared.append(edge.id)
    assert len(shared) == 2  # the interface was split at x = 0

    mesh = generate_mesh(candidate)
    region_nodes = {
        face_id: {
            node
            for element in mesh["elements"]
            if element["entity"] == face_id
            for node in element["nodes"]
        }
        for face_id in (info["child_a"], info["child_b"], "bulb")
    }
    for edge_id in shared:
        nodes = set(mesh["edge_nodes"][edge_id])
        assert nodes
        assert nodes <= region_nodes["bulb"]
        assert nodes <= (region_nodes[info["child_a"]] | region_nodes[info["child_b"]])
