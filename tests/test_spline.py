"""Spline fidelity: the drawing's curve survives import, display and meshing."""

import math

import ezdxf
import pytest
from shapely.geometry import LineString, Point

from packages.engineering.dxf import import_dxf
from packages.engineering.geometry import Builder, example_materials, sample_edges
from packages.engineering.identity import mesh_compat
from packages.engineering.mesh import generate_mesh
from packages.engineering.model import (
    Component,
    Face,
    Project,
    Selection,
    Source,
    SplineData,
)
from packages.engineering.spline import curve, deviation

KNOTS = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
POLES = [(0.0, 4.0, 0.0), (4.0, 6.0, 0.0), (7.0, 2.0, 0.0), (10.0, 4.0, 0.0)]


def wavy():
    """Rectangle whose top boundary is a spline, so every mesh has a curved edge."""
    data = SplineData(degree=3, control_points=POLES, knots=KNOTS)
    b = Builder()
    bottom = b.edge((0, 0, 0), (10, 0, 0), "seal", name="bottom")
    left = b.edge((0, 0, 0), (0, 4, 0), "seal", name="left")
    right = b.edge((10, 4, 0), (10, 0, 0), "seal", name="right")
    top = b.spline(data, "seal", name="wavy top", handle="A1")
    b.edge((0, 12, 0), (10, 12, 0), "panel", name="panel")
    project = Project(
        name="Spline patch",
        vertices=b.vertices,
        edges=b.edges,
        faces=[
            Face(
                id="f1",
                name="Region",
                component="seal",
                material="base_rubber",
                loops=[[bottom, "-" + right, "-" + top, "-" + left]],
            )
        ],
        components=[
            Component(id="seal", name="Seal", role="seal"),
            Component(id="panel", name="Panel", role="moving_panel"),
        ],
        materials=example_materials(),
        selections=[Selection(id="mount", name="Mount", entities=[bottom])],
        source=Source(kind="synthetic", filename="Spline patch"),
    )
    return project, top, data


def distance_to_curve(data, points, samples=4000):
    """Worst distance from candidate points to the true curve, in millimetres."""
    spline = curve(data)
    max_t = spline.max_t
    line = LineString(
        [tuple(spline.point(max_t * i / (samples - 1)))[:2] for i in range(samples)]
    )
    return max(Point(p[:2]).distance(line) for p in points)


def test_tessellation_stays_within_declared_deviation():
    data = SplineData(degree=3, control_points=POLES, knots=KNOTS, tolerance=0.02)
    project, top, _ = wavy()
    polyline = sample_edges(project)[top]
    assert deviation(data, polyline) <= data.tolerance
    assert polyline[0] == (0.0, 4.0, 0.0)
    assert polyline[-1] == (10.0, 4.0, 0.0)


def test_exact_mesh_follows_the_spline_not_a_chord():
    project, top, data = wavy()
    mesh = generate_mesh(project)
    assert mesh["counts"]["CPS4R"] > 0
    coords = {node["id"]: node["xyz"] for node in mesh["nodes"]}
    boundary = [coords[node] for node in mesh["edge_nodes"][top]]
    assert len(boundary) >= 5
    assert distance_to_curve(data, boundary) <= data.tolerance
    # A straight chord between the end points would be 0.58 mm away from the curve.
    chord = [(0.0, 4.0, 0.0), (10.0, 4.0, 0.0)]
    assert deviation(data, chord) > 0.4
    ordered = [coords[node][0] for node in mesh["edge_nodes"][top]]
    assert ordered == sorted(ordered)


def test_closed_spline_region_meshes_through_its_approximation():
    ring = [
        (5 + 5 * math.cos(math.tau * i / 8), 5 + 5 * math.sin(math.tau * i / 8), 0.0)
        for i in range(8)
    ]
    data = SplineData(degree=3, control_points=[*ring, ring[0]], closed=True)
    b = Builder()
    token = b.spline(data, "seal", name="Bulb outline", handle="B1")
    b.edge((16, 0, 0), (16, 1, 0), "panel", name="panel")
    project = Project(
        name="Closed spline",
        vertices=b.vertices,
        edges=b.edges,
        faces=[Face(id="f1", name="Bulb", component="seal", material="base_rubber", loops=[[token]])],
        components=[
            Component(id="seal", name="Seal", role="seal"),
            Component(id="panel", name="Panel", role="moving_panel"),
        ],
        materials=example_materials(),
        selections=[Selection(id="mount", name="Mount", entities=[token])],
        source=Source(kind="synthetic", filename="Closed spline"),
    )
    mesh = generate_mesh(project)
    assert mesh["counts"]["CPS4R"] > 100
    coords = {node["id"]: node["xyz"] for node in mesh["nodes"]}
    boundary = [coords[node] for node in mesh["edge_nodes"][token]]
    assert len(boundary) > 20
    assert distance_to_curve(data, boundary) <= data.tolerance


def test_dxf_spline_import_keeps_control_polygon_and_joins_vertices(tmp_path):
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0))
    msp.add_line((10, 0), (10, 4))
    msp.add_line((0, 4), (0, 0))
    msp.add_open_spline(control_points=POLES, degree=3, knots=KNOTS)
    path = tmp_path / "spline.dxf"
    doc.saveas(path)

    project = import_dxf(path, "Spline DXF")
    spline = next(edge for edge in project.edges if edge.kind == "spline")
    assert spline.spline.control_points == POLES
    assert spline.spline.degree == 3
    assert spline.source_handle
    assert len(project.vertices) == 4  # the spline's ends snapped onto the lines' ends
    assert len(project.faces) == 1
    polyline = sample_edges(project)[spline.id]
    assert deviation(spline.spline, polyline) <= spline.spline.tolerance


def test_fit_point_spline_import_passes_through_its_fit_points(tmp_path):
    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    fits = [(0, 4, 0), (2, 7, 0), (5, 8, 0), (8, 7, 0), (10, 4, 0)]
    msp.add_spline(fit_points=fits, degree=3)
    msp.add_line((0, 0), (10, 0))
    msp.add_line((10, 0), (10, 4))
    msp.add_line((0, 4), (0, 0))
    path = tmp_path / "fits.dxf"
    doc.saveas(path)

    project = import_dxf(path, "Fit points")
    spline = next(edge for edge in project.edges if edge.kind == "spline")
    polyline = LineString([p[:2] for p in sample_edges(project)[spline.id]])
    for index, point in enumerate(fits):
        assert polyline.distance(Point(point[:2])) < 0.05, (
            f"fit point {index} is not on the reconstructed curve"
        )
    assert deviation(spline.spline, sample_edges(project)[spline.id]) <= spline.spline.tolerance


def test_spline_rejects_inconsistent_definition_and_endpoints():
    with pytest.raises(ValueError, match="knot vector length"):
        SplineData(degree=3, control_points=POLES, knots=[0.0, 1.0])
    with pytest.raises(ValueError, match="exactly one of control points or fit points"):
        SplineData(degree=3, control_points=POLES, fit_points=[(0, 0, 0), (1, 1, 0)])
    with pytest.raises(ValueError, match="weights"):
        SplineData(degree=3, control_points=POLES, knots=KNOTS, weights=[1.0, -1.0, 1.0, 1.0])

    project, top, data = wavy()
    moved = data.model_copy(update={"control_points": [(0, 9, 0), *POLES[1:]]})
    payload = project.model_dump()
    payload["edges"] = [
        {**edge, "spline": (moved.model_dump() if edge["id"] == top else edge["spline"])}
        for edge in payload["edges"]
    ]
    with pytest.raises(ValueError, match="spline endpoints disagree"):
        Project.model_validate(payload)


def test_mesh_identity_tracks_the_spline_curve():
    project, top, data = wavy()
    baseline = mesh_compat(project)
    renamed = project.model_dump()
    renamed["edges"] = [
        {**edge, "name": "Renamed"} if edge["id"] == top else edge for edge in renamed["edges"]
    ]
    assert mesh_compat(Project.model_validate(renamed)) == baseline
    reshaped = project.model_dump()
    tighter = data.model_copy(update={"tolerance": 0.05}).model_dump()
    reshaped["edges"] = [
        {**edge, "spline": tighter} if edge["id"] == top else edge for edge in reshaped["edges"]
    ]
    assert mesh_compat(Project.model_validate(reshaped)) != baseline


def test_spline_drawing_reaches_a_deck_through_the_api(monkeypatch, tmp_path):
    """Upload a spline DXF, assign roles, mesh and write the deck through the real paths."""
    from fastapi.testclient import TestClient

    from services import store
    from services.api.main import app
    from services.worker.__main__ import once
    from support import legacy_fixture, prepare_mesh, save_fixture

    monkeypatch.setenv("SEAL_DATA", str(tmp_path / "data"))
    monkeypatch.delenv("SIMPLIFY_ABAQUS_LAUNCHER", raising=False)

    drawing = ezdxf.new("R2018", setup=True)
    drawing.units = ezdxf.units.MM
    drawing.layers.add("PANEL")
    space = drawing.modelspace()
    space.add_line((0, 0), (10, 0))
    space.add_line((10, 0), (10, 4))
    space.add_line((0, 4), (0, 0))
    space.add_open_spline(control_points=POLES, degree=3, knots=KNOTS)
    space.add_line((0, 12, 0), (10, 12, 0), dxfattribs={"layer": "PANEL"})
    path = tmp_path / "spline-section.dxf"
    drawing.saveas(path)

    with TestClient(app, base_url="http://127.0.0.1") as api:
        project = api.post("/api/projects", json={"name": "Spline"}).raise_for_status().json()
        url = "/api/projects/" + project["project"] + "/drawing"
        upload = api.post(
            url,
            data={"base": project["id"], "units": "N-mm-s-tonne"},
            files={"file": ("spline-section.dxf", path.read_bytes())},
        )
        assert upload.is_success, upload.text
        assert once("spline")
        revision = api.get("/api/jobs/" + upload.json()["id"] + "/imported").json()
        setup = revision["setup"]
        assert any(edge["kind"] == "spline" for edge in setup["edges"])

        for component in setup["components"]:
            component["role"] = "moving_panel" if component["id"] == "panel" else "seal"
        for face in setup["faces"]:
            face["material"] = setup["materials"][0]["id"] if not face["cavity"] else None
        setup["selections"][0]["entities"] = [setup["edges"][0]["id"]]
        saved = api.put(
            "/api/projects/" + revision["project"], json={"setup": setup, "base": revision["id"]}
        ).raise_for_status().json()

        mesh_job = prepare_mesh(api, saved, "spline")
        labels = legacy_fixture(api, mesh_job["id"])["labels"]
        save_fixture(api, mesh_job["id"], labels)
        deck = api.post(
            "/api/decks",
            json={"revision": saved["id"], "token": store.new_id(), "mesh": mesh_job["id"]},
        )
        assert deck.is_success, deck.text
        assert once("spline")
        deck_job = store.job(deck.json()["id"])
        assert deck_job["status"] == "Completed", deck_job["diagnostic"]
        text = (store.job_dir(deck_job["id"]) / "analysis.inp").read_text()
        assert "*Nset, nset=WSFIX" in text
        assert labels and len(labels) == len(set(labels))
