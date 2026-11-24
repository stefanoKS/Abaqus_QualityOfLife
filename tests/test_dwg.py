"""Native DWG import: reading, mapping to the canonical model and error paths.

The synthetic inventory in this module reproduces the *structure* ACadSharp
returns (fit-point splines, bulged polylines, separate body lines on one layer)
without any private drawing data. The original drawing is only read when it is
present locally, and it is never copied into the repository.
"""

from hashlib import sha256
import json
import math
import os
from pathlib import Path

import pytest

from integrations import dwg
from packages.engineering.dwg import import_inventory
from packages.engineering.geometry import sample_edges
from packages.engineering.mesh import generate_mesh

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "examples" / "hollow-section_2.dwg"
ORIGINAL_SHA256 = "8592c3c2aa59530e7b937d58f6354f6beeb24b6bc56cfcb6d37945e483aac771"


def circle_points(cx, cy, radius, count, start=0.0):
    return [
        [round(cx + radius * math.cos(start + math.tau * index / count), 6),
         round(cy + radius * math.sin(start + math.tau * index / count), 6),
         0.0]
        for index in range(count)
    ]


def closed_spline(handle, points):
    """A closed B-spline entity the way the reader reports one.

    The control polygon repeats its first point, which is what makes the
    evaluated endpoints coincide and the edge a closed loop.
    """
    poles = [[point[0], point[1], 0.0] for point in points]
    poles.append(poles[0])
    return {
        "handle": handle,
        "type": "SPLINE",
        "layer": "0",
        "degree": 3,
        "controlPoints": poles,
        "fitPoints": [],
        "closed": True,
        "periodic": False,
    }


def inventory(entities, units=4):
    return {
        "reader": {"name": "ACadSharp", "version": "3.8.35", "license": "MIT"},
        "source": {
            "path": "synthetic.dwg",
            "bytes": 4096,
            "sha256": "0" * 64,
            "version": "AC1032",
            "insUnits": units,
            "insUnitsName": "Millimeters" if units == 4 else "Inches",
        },
        "counts": {},
        "unknown": {},
        "unknownHandles": [],
        "layers": [{"name": "0", "on": True, "entities": len(entities)}],
        "blocks": [],
        "entities": entities,
        "warnings": [],
    }


def hollow_section():
    """Hollow seal (outer + cavity spline), spline door, body as separate lines."""
    outer = circle_points(0, 0, 10, 12)
    cavity = circle_points(0, 0, 5, 10)
    body_points = [[-20, -6, 0], [-20, -14, 0], [20, -14, 0], [20, -6, 0]]
    entities = [
        closed_spline("A1", outer),
        closed_spline("A2", cavity),
        {
            "handle": "B1",
            "type": "SPLINE",
            "layer": "0",
            "degree": 3,
            "controlPoints": [],
            "fitPoints": [[-8, 20, 0], [0, 24, 0], [8, 20, 0]],
            "closed": False,
            "periodic": False,
        },
    ]
    # Body written as individual, unordered and partly reversed LINE entities that
    # stay open, so they must never be mistaken for a filled region.
    order = [(1, 0), (2, 1), (3, 2)]
    for index, (start, end) in enumerate(order):
        entities.append(
            {
                "handle": f"C{index + 1}",
                "type": "LINE",
                "layer": "0",
                "start": body_points[start],
                "end": body_points[end],
            }
        )
    return entities


def test_imported_fit_point_lip_can_be_partitioned():
    from packages.engineering.partition import commit

    entities = [
        {"handle": "L", "type": "LINE", "layer": "0", "start": [-5, -5, 0], "end": [5, -5, 0]},
        {"handle": "O", "type": "SPLINE", "layer": "0", "degree": 3,
         "controlPoints": [], "fitPoints": [[5, -5, 0], [7, -4, 0], [7, -2, 0],
                                               [5, -2, 0], [5, 5, 0], [-5, 5, 0], [-5, -5, 0]],
         "closed": False, "periodic": False},
        {"handle": "H", "type": "SPLINE", "layer": "0", "degree": 3,
         "controlPoints": [], "fitPoints": [[-2, -2, 0], [2, -2, 0], [2, 2, 0],
                                               [-2, 2, 0], [-2, -2, 0]],
         "closed": True, "periodic": False},
    ]
    project, _ = import_inventory(inventory(entities), "Manufactured lip")
    face = next(face for face in project.faces if not face.cavity)
    next(component for component in project.components if component.id == face.component).role = "seal"
    splines = {edge.source_handle: edge.spline for edge in project.edges if edge.kind == "spline"}
    assert splines["O"].fit_points and not splines["O"].closed
    assert splines["H"].fit_points and splines["H"].closed and not splines["H"].periodic
    candidate, info = commit(project, face.id, [((6, -5), (6, 0))], seed="lip")
    assert info["status"] == "valid"
    assert info["child_count"] == 2
    children = [face for face in candidate.faces if face.id in {child["id"] for child in info["children"]}]
    assert sorted(len(child.loops) for child in children) == [1, 2]


def test_inventory_maps_hollow_seal_spline_door_and_body_lines():
    project, report = import_inventory(inventory(hollow_section()), "Hollow section")
    assert len([face for face in project.faces if not face.cavity]) == 1
    assert len([face for face in project.faces if face.cavity]) == 1
    assert len(project.components) == 3
    assert report["splines"] == 3
    assert report["splineProvenance"] == {"control_points": 2, "fit_points": 1}
    assert report["openChains"] == 2
    assert report["regions"] == 1 and report["cavities"] == 1
    assert report["filledArea"] > 100
    assert any("open profile" in item["reason"] for item in report["excluded"])
    assert report["entityCounts"] == {"LINE": 3, "SPLINE": 3}
    assert project.source.kind == "dwg"


def test_body_lines_join_by_connectivity_but_stay_apart_from_the_door():
    project, report = import_inventory(inventory(hollow_section()), "Hollow section")
    by_component = {}
    for edge in project.edges:
        by_component.setdefault(edge.component, []).append(edge)
    body = [edges for edges in by_component.values() if len(edges) == 3]
    assert len(body) == 1, "the three body lines must form one chain"
    # The chain is traced through reversed segments, so it is a single open profile.
    assert len({edge.source_handle for edge in body[0]}) == 3
    door = [edges for edges in by_component.values() if len(edges) == 1]
    assert len(door) == 1 and door[0][0].kind == "spline"
    assert door[0][0].component != body[0][0].component


def test_hollow_seal_meshes_with_an_empty_cavity():
    project, _report = import_inventory(inventory(hollow_section()), "Hollow section")
    region = [face for face in project.faces if not face.cavity][0]
    panel = next(
        edge
        for edge in project.edges
        if edge.kind == "spline" and edge.component != region.component
    )
    payload = project.model_dump()
    roles = {}
    for component in payload["components"]:
        if component["id"] == region.component:
            roles[component["id"]] = "seal"
        elif component["id"] == panel.component:
            roles[component["id"]] = "moving_panel"
        else:
            roles[component["id"]] = "vehicle_body"
    for component in payload["components"]:
        component["role"] = roles[component["id"]]
    for face in payload["faces"]:
        face["material"] = "bulb_foam" if not face["cavity"] else None
    project = type(project).model_validate(payload)
    mesh = generate_mesh(project)
    assert mesh["counts"]["CPS4R"] > 50
    assert mesh["counts"]["R2D2"] > 0
    # A component assigned the vehicle-body role now participates: the role-derived
    # sequence is body-then-door, so nothing is silently excluded from the mesh.
    assert mesh["excluded"] == []
    assert project.analysis.mode == "body_then_door"
    samples = sample_edges(project)
    cavity_edge = [edge for edge in project.edges if edge.component == region.component][-1]
    ring = samples[cavity_edge.id]
    from shapely.geometry import Point, Polygon

    hole = Polygon([point[:2] for point in ring])
    coordinates = {node["id"]: node["xyz"] for node in mesh["nodes"]}
    inside = 0
    for element in mesh["elements"]:
        if element["type"] == "R2D2":
            continue
        points = [coordinates[node] for node in element["nodes"]]
        if hole.contains(Point(sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))):
            inside += 1
    assert inside == 0, "material elements must not fill the hollow cavity"


def test_bulged_polyline_keeps_its_arc_direction():
    entity = {
        "handle": "D1",
        "type": "LWPOLYLINE",
        "layer": "0",
        "closed": False,
        "vertices": [
            {"x": 0.0, "y": 0.0, "bulge": 0.0},
            {"x": 10.0, "y": 0.0, "bulge": -0.2},
            {"x": 20.0, "y": 0.0, "bulge": 0.0},
        ],
    }
    seal = closed_spline("A1", circle_points(10, 40, 6, 10))
    project, _report = _import_without_regions([entity, seal])
    edges = [edge for edge in project.edges if edge.kind == "arc"]
    assert len(edges) == 1
    vertices = {vertex.id: vertex.xyz for vertex in project.vertices}
    arc = edges[0]
    radius = math.dist(vertices[arc.start], arc.center)
    # The arc must sweep from (10, 0) to (20, 0) the short way through the low side.
    end = (
        arc.center[0] + radius * math.cos(math.atan2(-arc.center[1], 10 - arc.center[0]) - arc.sweep),
        arc.center[1] + radius * math.sin(math.atan2(-arc.center[1], 10 - arc.center[0]) - arc.sweep),
    )
    assert math.dist(end, (20.0, 0.0)) < 1e-6
    assert arc.center[1] < 0, "a negative bulge curves below the chord"


def _import_without_regions(entities):
    """Import entities without requiring a closed region (the splash test path)."""
    import packages.engineering.dwg as module

    original = module.assemble

    def relaxed(builder, name, source, *, allow_open_profiles=False):
        project, report = original(builder, name, source, allow_open_profiles=True)
        return project, report

    module.assemble = relaxed
    try:
        return import_inventory(inventory(entities), "Bulge probe")
    finally:
        module.assemble = original


def test_declared_inches_are_converted_once():
    project, report = import_inventory(inventory(hollow_section(), units=1), "Inches")
    assert project.source.unit_basis == "converted_to_mm"
    assert project.source.unit_factor == pytest.approx(25.4)
    assert report["unitDeclaration"] == "inches"
    mm_project, _ = import_inventory(inventory(hollow_section(), units=4), "Ref")
    assert max(v.xyz[0] for v in project.vertices) == pytest.approx(
        25.4 * max(v.xyz[0] for v in mm_project.vertices), rel=1e-9
    )
    reopened = type(project).model_validate(project.model_dump(mode="json"))
    assert reopened.source.unit_factor == pytest.approx(25.4)
    assert max(v.xyz[0] for v in reopened.vertices) == pytest.approx(
        max(v.xyz[0] for v in project.vertices), abs=1e-9
    )


def test_corrupt_and_foreign_files_fail_actionably(tmp_path):
    corrupt = tmp_path / "broken.dwg"
    corrupt.write_bytes(b"not a drawing at all")
    with pytest.raises(dwg.DwgError) as error:
        dwg.read(corrupt)
    assert "not a readable DWG" in str(error.value) or "no usable result" in str(error.value)

    ancient = tmp_path / "ancient.dwg"
    ancient.write_bytes(b"AC1009" + bytes(2000))
    with pytest.raises(dwg.DwgError):
        dwg.read(ancient)


def test_missing_helper_is_reported_not_crashed(monkeypatch):
    monkeypatch.setattr(dwg, "HELPER", ROOT / "integrations" / "dwg" / "bin" / "absent.exe")
    with pytest.raises(dwg.DwgError, match="native DWG reader is missing"):
        dwg.read(ORIGINAL if ORIGINAL.is_file() else Path(__file__))


requires_original = pytest.mark.skipif(
    not ORIGINAL.is_file() or sha256(ORIGINAL.read_bytes()).hexdigest() != ORIGINAL_SHA256,
    reason="the reviewed original drawing is not present locally",
)


@requires_original
def test_original_drawing_inventory_accounts_for_every_entity():
    payload = dwg.read(ORIGINAL)
    assert payload["source"]["sha256"] == ORIGINAL_SHA256
    assert payload["source"]["version"] == "AC1032"
    assert payload["source"]["insUnits"] == 4
    assert payload["unknown"] == {}, "unknown entities would be an unaccounted gap"
    assert payload["counts"] == {"LINE": 1, "LWPOLYLINE": 1, "SPLINE": 3}
    for entity in payload["entities"]:
        if entity["type"] == "SPLINE":
            assert entity["fitPoints"], "the drawing stores fit points, not control points"
            assert not entity["controlPoints"]
    assert all(entity["layer"] == "0" for entity in payload["entities"])


@requires_original
def test_original_lip_partition_geometry_and_mesh():
    from shapely.geometry import Point, Polygon
    from packages.engineering.geometry import face_polygon
    from packages.engineering.model import Project
    from packages.engineering.partition import PartitionError, _line_edge_hits, commit, preview
    from packages.engineering.spline import curve

    project, _ = import_inventory(dwg.read(ORIGINAL), "Local native partition")
    target = next(face for face in project.faces if not face.cavity)
    next(component for component in project.components if component.id == target.component).role = "seal"
    target.material = "bulb_foam"
    vertices = {vertex.id: vertex.xyz for vertex in project.vertices}
    others = [component for component in project.components if component.id != target.component]
    door = max(others, key=lambda component: sum(
        vertices[edge.start][1] for edge in project.edges if edge.component == component.id
    ) / sum(edge.component == component.id for edge in project.edges))
    for component in others:
        component.role = "moving_panel" if component.id == door.id else "vehicle_body"
    cases = [
        ([((27, 6), (27, 9))], "valid", 1),
        ([((13.4, 6), (13.4, 9))], "valid", 1),
        ([((10, 7.5), (30, 7.5))], "valid", 1),
        ([((9, 12), (18, 12))], "one_region", 1),
        ([((9, 12), (30, 12))], "valid", 2),
        ([((9, 12), (18, 12)), ((22, 12), (30, 12))], "valid", 2),
    ]
    for strokes, status, count in cases:
        plan = preview(project, target.id, strokes, seed="native")
        assert plan["status"] == status
        assert sum(len(guide["intervals"]) for guide in plan["guides"]) == count
    with pytest.raises(PartitionError, match="cut_no_hit"):
        preview(project, target.id, [((18, 14), (21, 14))], seed="native")

    result, info = commit(project, target.id, [((27, 6), (27, 9))], seed="native")
    result = Project.model_validate(result.model_dump(mode="json"))
    children = [face for face in result.faces if face.id in {child["id"] for child in info["children"]}]
    assert sorted(len(child.loops) for child in children) == [1, 2]
    samples = sample_edges(result)
    assert face_polygon(children[0], samples).intersection(face_polygon(children[1], samples)).area < 1e-8

    def area(model, face):
        edges = {edge.id: edge for edge in model.edges}
        vertices = {vertex.id: vertex.xyz for vertex in model.vertices}
        total = 0.0
        for loop in face.loops:
            points = []
            for token in loop:
                edge = edges[token.lstrip("-")]
                if edge.kind == "spline":
                    spline = curve(edge.spline)
                    sampled = [tuple(spline.point(spline.max_t * i / 10000)) for i in range(10001)]
                else:
                    sampled = [vertices[edge.start], vertices[edge.end]]
                if token.startswith("-"):
                    sampled.reverse()
                points.extend(sampled[:-1])
            total += sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1])) / 2
        return abs(total)

    measured = sorted(area(result, child) for child in children)
    assert measured == pytest.approx([2.432070, 95.823642], abs=1e-4)
    assert sum(measured) == pytest.approx(area(project, target), abs=1e-4)
    original = next(edge for edge in project.edges if edge.kind == "spline" and not edge.spline.closed and edge.component == target.component)
    endpoints = info["guides"][0]["intervals"][0]
    hits = _line_edge_hits(project, original, (27, 6), (0, 1))
    intervals = [0.0] + sorted(
        t for t, point in hits if any(math.dist(point, endpoint) < 1e-6 for endpoint in endpoints)
    ) + [1.0]
    parts = [edge for edge in result.edges if edge.source_handle == original.source_handle]
    assert len(parts) == len(intervals) - 1
    parent_curve = curve(original.spline)
    worst = 0.0
    for edge, lo, hi in zip(parts, intervals, intervals[1:]):
        child_curve = curve(edge.spline)
        for i in range(101):
            fraction = i / 100
            worst = max(worst, math.dist(
                tuple(child_curve.point(child_curve.max_t * fraction)),
                tuple(parent_curve.point(parent_curve.max_t * (lo + (hi - lo) * fraction))),
            ))
    assert worst < 1e-9
    rounded, rounded_info = commit(
        project, target.id,
        [((26.98331976538329, 5.981999036157906), (26.995723734790698, 8.996442989076519))],
        seed="pointer",
    )
    for label, model, plan in (("exact", result, info), ("pointer", rounded, rounded_info)):
        regions = [face for face in model.faces if face.id in {child["id"] for child in plan["children"]}]
        mesh = generate_mesh(model)
        cavity = next(face for face in model.faces if face.cavity)
        hole = face_polygon(cavity, sample_edges(model)).buffer(-0.02)
        nodes = {node["id"]: node["xyz"] for node in mesh["nodes"]}
        elements = [element for element in mesh["elements"] if element["entity"] in {child.id for child in regions}]
        for element in elements:
            center = [sum(nodes[node][axis] for node in element["nodes"]) / len(element["nodes"]) for axis in (0, 1)]
            assert not hole.contains(Point(center))
            polygon = Polygon([nodes[node][:2] for node in element["nodes"]])
            assert polygon.intersection(hole).area < 1e-8
        child_nodes = [{node for element in elements if element["entity"] == child.id for node in element["nodes"]} for child in regions]
        assert child_nodes[0] & child_nodes[1] == set(mesh["edge_nodes"][plan["seams"][0]])
        assert mesh["boundary"]["worst"] <= 0.02
        print("native", label, "curve areas", [area(model, face) for face in regions],
              "curve deviation", worst, "nodes", len(mesh["nodes"]), "elements", len(elements),
              "seam nodes", len(child_nodes[0] & child_nodes[1]),
              "boundary deviation", mesh["boundary"]["worst"])


@requires_original
def test_original_drawing_reaches_a_deck_without_any_converter(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from integrations import drawings
    from services import store
    from services.api.main import app
    from services.worker.__main__ import once
    from support import prepare_deck, prepare_mesh, save_fixture

    def forbidden(*_args, **_kwargs):
        raise AssertionError("the ODA converter must not be used by the native path")

    monkeypatch.setattr(drawings, "convert", forbidden)
    monkeypatch.setattr(drawings, "oda", forbidden)
    monkeypatch.setenv("SEAL_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("SEAL_ODA", raising=False)
    monkeypatch.delenv("ABAQUS_QOL_ODA", raising=False)

    with TestClient(app, base_url="http://127.0.0.1") as api:
        project = api.post("/api/projects", json={"name": "DWG"}).raise_for_status().json()
        upload = api.post(
            "/api/projects/" + project["project"] + "/drawing",
            data={"base": project["id"], "units": "N-mm-s-tonne"},
            files={"file": (ORIGINAL.name, ORIGINAL.read_bytes())},
        )
        assert upload.is_success, upload.text
        assert once("dwg")
        job = store.job(upload.json()["id"])
        assert job["status"] == "Completed", job["diagnostic"]
        report = json.loads((store.job_dir(job["id"]) / "import-report.json").read_text())
        assert report["sourceSha256"] == ORIGINAL_SHA256
        assert report["regions"] == 1 and report["cavities"] == 1
        assert report["unknownEntities"] == {}
        assert (store.job_dir(job["id"]) / "dwg-inventory.json").is_file()

        revision = api.get("/api/jobs/" + upload.json()["id"] + "/imported").json()
        setup = revision["setup"]
        seal = [face["component"] for face in setup["faces"] if not face["cavity"]][0]
        vertices = {vertex["id"]: vertex["xyz"] for vertex in setup["vertices"]}
        panels = {}
        for edge in setup["edges"]:
            if edge["component"] != seal:
                panels.setdefault(edge["component"], []).append(
                    vertices[edge["start"]][1]
                )
        door = max(panels, key=lambda key: sum(panels[key]) / len(panels[key]))
        for component in setup["components"]:
            component["role"] = (
                "seal"
                if component["id"] == seal
                else "moving_panel"
                if component["id"] == door
                else "vehicle_body"
            )
        for face in setup["faces"]:
            face["material"] = "bulb_foam" if not face["cavity"] else None
        saved = api.put(
            "/api/projects/" + revision["project"],
            json={"setup": setup, "base": revision["id"]},
        ).raise_for_status().json()
        mesh = prepare_mesh(api, saved, "dwg")
        mesh_data = json.loads((store.job_dir(mesh["id"]) / "mesh.json").read_text())
        seal_edges = {
            edge["id"] for edge in setup["edges"] if edge["component"] == seal
        }
        labels = [
            f"WS-1:{node}"
            for edge_id, nodes in mesh_data["edge_nodes"].items()
            if edge_id in seal_edges
            for node in nodes
        ]
        labels = sorted(set(labels))[:12]
        save_fixture(api, mesh["id"], labels)
        deck = prepare_deck(api, saved, mesh["id"], "dwg")
        text = (store.job_dir(deck["id"]) / "analysis.inp").read_text()
        import re

        block = re.search(r"\*Nset, nset=WSFIX.*?\n(.*?)(?=\n\*|\Z)", text, re.S | re.I)
        written = {int(value) for value in re.findall(r"\d+", block.group(1))}
        assert written == {int(label.split(":")[1]) for label in labels}
