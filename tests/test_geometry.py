import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ezdxf
import pytest
from pydantic import ValidationError

from packages.engineering import Project, display, generate_mesh, import_dxf, mesh_compat, synthetic
from packages.engineering.geometry import face_polygon, sample_edges
from packages.engineering.mesh import _check_element

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "hollow-section.dxf"


def assigned_drawing():
    p = import_dxf(EXAMPLE, "Imported section")
    for component in p.components:
        component.role = "moving_panel" if component.id == "panel" else "seal"
    for face, material in zip(p.material_regions, p.materials):
        face.material = material.id
    return p


@pytest.mark.parametrize("factory", [synthetic, assigned_drawing])
def test_conforming_occ_mesh_with_cavity_and_ordered_boundaries(factory):
    p = factory()
    # Also exercise Gmsh initialization from a non-main application thread.
    with ThreadPoolExecutor(max_workers=1) as pool:
        mesh = pool.submit(generate_mesh, p).result()
    assert mesh["counts"].get("CPS4R", 0) > 0 and mesh["counts"]["R2D2"] > 0
    a, b = p.material_regions
    used = {f.id: {t.lstrip("-") for loop in f.loops for t in loop} for f in p.faces}
    (shared,) = used[a.id] & used[b.id]
    region_nodes = {
        f.id: {n for e in mesh["elements"] if e["entity"] == f.id for n in e["nodes"]}
        for f in p.faces
    }
    assert region_nodes[a.id] & region_nodes[b.id] == set(mesh["edge_nodes"][shared])
    curve_by_id = sample_edges(p)
    xyz = {n["id"]: n["xyz"] for n in mesh["nodes"]}
    for edge in p.edges:
        chain = mesh["edge_nodes"][edge.id]
        assert math.dist(xyz[chain[0]], curve_by_id[edge.id][0]) < 1e-7
        assert math.dist(xyz[chain[-1]], curve_by_id[edge.id][-1]) < 1e-7
    # The OSS mesher is using the analytic arcs; allow a small chord error.
    expected = sum(face_polygon(f, curve_by_id).area for f in p.material_regions)
    area = 0
    for elem in mesh["elements"]:
        if elem["type"] == "R2D2":
            continue
        pts = [xyz[n] for n in elem["nodes"]]
        area += 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
    assert area == pytest.approx(expected, rel=0.02)
    assert len(xyz) == len({n for e in mesh["elements"] for n in e["nodes"]})


def test_mesh_sizing_triangles_and_validation():
    p = synthetic()
    edge = p.selections[0].entities[0]
    p.mesh.recombine = False
    p.mesh.local[edge] = 0.25
    mesh = generate_mesh(p)
    assert set(mesh["counts"]) == {"CPS3", "R2D2"}
    assert len(mesh["edge_nodes"][edge]) >= 73
    p.faces[0].material = None
    with pytest.raises(ValueError, match="material"):
        generate_mesh(p)
    p = synthetic()
    p.mesh.size = 0.01
    with pytest.raises(ValueError, match="budget"):
        generate_mesh(p)


def test_synthetic_display_extrusion_and_offset_only_for_panel():
    p = synthetic()
    p.dimension, p.formulation = "3D", "extrusion_preview"
    p.motion.offset = 2
    data = display(p)
    assert data["bounds"] == [-12, 12, 0, 16, 0, p.extrusion.length]
    assert {s["section"] for s in data["solids"]} == {"bulb", "foot"}
    assert any(x["entity"] == "top-bulb" and x["source"] == "bulb" for x in data["primitives"])
    assert all(x["id"] != x["entity"] for x in data["primitives"])
    with pytest.raises(ValueError, match="3D extrusion"):
        generate_mesh(p)


def test_dxf_requires_assignment_and_preserves_source():
    project = import_dxf(EXAMPLE, "DWG converted section")
    assert all(c.role == "unassigned" for c in project.components)
    assert all(f.material is None for f in project.faces)
    assert len(project.material_regions) == 2
    assert len(project.faces) == 3
    assert sorted(len(f.loops) for f in project.material_regions) == [1, 2]
    assert all(e.source_handle and e.layer for e in project.edges)
    assert len(project.source.digest) == 64
    with pytest.raises(ValueError, match="material"):
        generate_mesh(project)


def save_drawing(tmp_path, build, units=4):
    doc = ezdxf.new("R2010", units=units)
    build(doc.modelspace())
    path = tmp_path / "section.dxf"
    doc.saveas(path)
    return path


@pytest.mark.parametrize(
    ("build", "message"),
    [
        (lambda m: m.add_point((0, 0)), "POINT"),
        (lambda m: m.add_blockref("unresolved", (0, 0)), "INSERT"),
        (lambda m: m.add_line((0, 0, 1), (1, 0, 1)), "XY plane"),
        (lambda m: m.add_line((0, 0), (1, 0)), "gaps"),
        (lambda m: m.add_lwpolyline([(0, 0), (0, 1), (1, 1)]), "open"),
        (
            lambda m: m.add_lwpolyline([(0, 0), (1, 1), (0, 1), (1, 0)], close=True),
            "cross or overlap",
        ),
    ],
)
def test_dxf_rejects_entire_ambiguous_drawing(tmp_path, build, message):
    with pytest.raises(ValueError, match=message):
        import_dxf(save_drawing(tmp_path, build), "Invalid")


def test_dxf_bulge_and_units(tmp_path):
    def bulge(m):
        m.add_lwpolyline([(-1, 0, 0), (1, 0, 1)], format="xyb", close=True)

    p = import_dxf(save_drawing(tmp_path, bulge), "Semicircle")
    assert p.source.unit_basis == "declared_mm"
    assert len(p.faces) == 1
    assert sum(e.sweep for e in p.edges if e.kind == "arc") == pytest.approx(math.pi)
    assert face_polygon(p.faces[0], sample_edges(p)).area == pytest.approx(math.pi / 2, rel=0.005)
    with pytest.raises(ValueError):
        import_dxf(save_drawing(tmp_path, bulge, units=99), "Bad")
    # A declared inch drawing converts once and keeps the same physical arc.
    inches = import_dxf(save_drawing(tmp_path, bulge, units=1), "Inches")
    assert inches.source.unit_basis == "converted_to_mm"
    assert inches.source.unit_factor == pytest.approx(25.4)
    assert sum(e.sweep for e in inches.edges if e.kind == "arc") == pytest.approx(math.pi)
    assert face_polygon(inches.faces[0], sample_edges(inches)).area == pytest.approx(
        math.pi / 2 * 25.4**2, rel=0.005
    )


def test_project_rejects_stale_selections_and_nonplanar_points():
    p = synthetic().model_dump()
    p["selections"][0]["entities"] = ["unknownEdge"]
    with pytest.raises(ValidationError, match="Rebuild selections"):
        Project.model_validate(p)
    p = synthetic().model_dump()
    p["vertices"][0]["xyz"] = (1, 1, 1)
    with pytest.raises(ValidationError, match="XY plane"):
        Project.model_validate(p)


def test_mesh_identity_tracks_mesh_inputs_only():
    from packages.engineering.identity import mesh_inputs

    p = synthetic()
    base = mesh_compat(p)
    other = p.model_copy(deep=True)
    other.motion.travel = -9
    other.motion.duration = 3
    other.contact.friction = 0.9
    other.analysis.thickness = 4
    other.materials[0].young = 12
    other.edges[0].name = "Renamed edge"
    assert mesh_compat(other) == base
    # Geometry, roles, cavity fill and mesh controls do change the identity.
    p.mesh.size = 0.9
    assert mesh_compat(p) != base
    p = synthetic()
    p.mesh.local["e1"] = 0.5
    assert mesh_compat(p) != base
    p = synthetic()
    p.components[1].role = "vehicle_body"
    assert mesh_compat(p) != base
    p = synthetic()
    p.faces[0].material = None
    assert mesh_compat(p) != base
    # The recorded inputs are reviewable, not opaque.
    inputs = mesh_inputs(synthetic())
    assert {"vertices", "edges", "faces", "components", "mesh"} <= set(inputs)


@pytest.mark.parametrize("conn", [[1, 2, 2], [1, 3, 2], [1, 2, 3, 4]])
def test_invalid_element_rejected(conn):
    with pytest.raises(ValueError):
        _check_element(42, conn, {1: (0, 0, 0), 2: (1, 0, 0), 3: (0, 1, 0), 4: (1, 1, 0)})


def test_optional_nested_material_fills_only_on_assignment():
    project = assigned_drawing()
    (cavity,) = (f for f in project.faces if f.cavity)
    original = generate_mesh(project)
    assert cavity.id not in original["face_elements"]
    assert not any(v["entity"] == cavity.id for v in display(project)["primitives"])
    cavity.material = project.materials[1].id
    filled = generate_mesh(project)
    assert filled["face_elements"][cavity.id]
    assert any(v["entity"] == cavity.id for v in display(project)["primitives"])
    region_nodes = {n for e in filled["elements"] if e["entity"] == cavity.id for n in e["nodes"]}
    boundary = {n for t in cavity.loops[0] for n in filled["edge_nodes"][t.lstrip("-")]}
    assert boundary < region_nodes
    assert boundary <= {
        n for e in filled["elements"] if e["entity"] != cavity.id for n in e["nodes"]
    }


def test_disconnected_bonded_regions_require_shared_edges(tmp_path):
    def drawing(m):
        m.add_circle((0, 0), 1)
        m.add_circle((5, 0), 1)
        m.add_line((-2, 3), (7, 3), dxfattribs={"layer": "PANEL"})

    p = import_dxf(save_drawing(tmp_path, drawing), "Disconnected regions")
    for c in p.components:
        c.role = "moving_panel" if c.id == "panel" else "seal"
    for f in p.faces:
        f.material = p.materials[0].id
    with pytest.raises(ValueError, match="Disconnected seal regions"):
        generate_mesh(p)


def test_true_arc_intersection_between_display_samples(tmp_path):
    def drawing(m):
        m.add_circle((0, 0), 1)
        # The line crosses the true circle near 2 degrees, outside its display chord.
        phi = math.radians(2)
        u, v = (math.cos(phi), math.sin(phi)), (-math.sin(phi), math.cos(phi))
        m.add_line(
            tuple(0.99995 * a - 0.009 * b for a, b in zip(u, v)),
            tuple(0.99995 * a + 0.009 * b for a, b in zip(u, v)),
            dxfattribs={"layer": "PANEL"},
        )
        # Extend far enough along the tangential direction to cross the true arc.
        m.add_line(
            tuple(0.99995 * a + 0.009 * b for a, b in zip(u, v)),
            tuple(0.99995 * a + 0.012 * b for a, b in zip(u, v)),
            dxfattribs={"layer": "PANEL"},
        )

    with pytest.raises(ValueError, match="cross or overlap"):
        import_dxf(save_drawing(tmp_path, drawing), "Analytic intersections")
