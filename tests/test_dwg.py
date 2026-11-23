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
