"""Native APLR door geometry and reflected-OCS regressions.

The original proprietary drawing is only read when it exists locally; it is never
copied into the repository. The synthetic cases use the same inventory contract as
``integrations/dwg/bin/dwg-inventory.exe`` and are redistributable.
"""

import math
from pathlib import Path
import subprocess

import pytest

from integrations import dwg
from packages.engineering.dwg import import_inventory
from packages.engineering.geometry import sample_edges

ROOT = Path(__file__).resolve().parents[1]
APLR = ROOT / "examples" / "APLR.dwg"
APLR_SHA256 = "18ef6c7a12f558dd882ddeba21f2e0e25a1ddea03465ce2ca50d43f1e97434fa"

# Native properties measured directly from ACadSharp on the original bytes.
NEGATIVE_NORMAL_ARCS = {"FA", "FC", "FE", "FF", "101"}


def inventory(entities, warnings=None):
    return {
        "reader": {"name": "ACadSharp", "version": "3.8.35", "license": "MIT"},
        "source": {
            "path": "synthetic.dwg",
            "bytes": 4096,
            "sha256": "0" * 64,
            "version": "AC1032",
            "insUnits": 4,
            "insUnitsName": "Millimeters",
        },
        "counts": {},
        "unknown": {},
        "unknownHandles": [],
        "layers": [],
        "blocks": [],
        "entities": entities,
        "warnings": warnings or [],
    }


def wcs_arc(handle, center, radius, start_angle, sweep, normal):
    """An ARC entity as the native helper now serializes it (WCS).

    ``start_angle`` and ``sweep`` are already WCS quantities; a reflected source
    plane produces a negative sweep.
    """
    cx, cy = center
    end_angle = start_angle + sweep
    start = [cx + radius * math.cos(start_angle), cy + radius * math.sin(start_angle), 0.0]
    end = [cx + radius * math.cos(end_angle), cy + radius * math.sin(end_angle), 0.0]
    mid_angle = start_angle + sweep / 2.0
    mid = [cx + radius * math.cos(mid_angle), cy + radius * math.sin(mid_angle), 0.0]
    return {
        "handle": handle,
        "type": "ARC",
        "layer": "0",
        "center": [cx, cy, 0.0],
        "radius": radius,
        "start": start,
        "end": end,
        "mid": mid,
        "sweep": sweep,
        "normal": list(normal),
        "startAngle": start_angle,
        "endAngle": end_angle,
    }


def line(handle, start, end):
    return {
        "handle": handle,
        "type": "LINE",
        "layer": "0",
        "start": [start[0], start[1], 0.0],
        "end": [end[0], end[1], 0.0],
    }


def degree_one(project, component):
    counts = {}
    for edge in project.edges:
        if edge.component == component:
            for vertex in (edge.start, edge.end):
                counts[vertex] = counts.get(vertex, 0) + 1
    vertices = {vertex.id: vertex.xyz for vertex in project.vertices}
    return [
        vertices[vertex]
        for vertex, degree in counts.items()
        if degree == 1
    ]


def assert_endpoints(actual, expected, tolerance=1e-6):
    assert len(actual) == len(expected)
    for point in expected:
        assert min(math.dist(tuple(item), point) for item in actual) <= tolerance, (point, actual)


def test_reflected_normals_join_as_one_open_profile_and_preserve_the_midpoint():
    # Two quarter arcs meet at (0, 2): the left one has a -Z extrusion and must be
    # traversed clockwise in WCS, the right one is a plain +Z arc. A line extends
    # the right end; the left end is deliberately separated from the next line by
    # a real 0.01 mm gap, which must stay a gap.
    left = wcs_arc("A1", (0.0, 0.0), 2.0, math.pi, -math.pi / 2, (0.0, 0.0, -1.0))
    right = wcs_arc("A2", (0.0, 0.0), 2.0, 0.0, math.pi / 2, (0.0, 0.0, 1.0))
    entities = [
        left,
        right,
        line("L1", (2.0, 0.0), (4.0, 0.0)),
        # starts 0.01 mm away from the reflected arc's free end at (-2, 0)
        line("L2", (-2.0, 0.01), (-4.0, 0.01)),
    ]
    project, report = import_inventory(inventory(entities), "Mixed normals")
    assert report["openChains"] == 2, report
    assert report["regions"] == 0 and report["cavities"] == 0
    by_handle = {}
    vertices = {vertex.id: vertex.xyz for vertex in project.vertices}
    for edge in project.edges:
        by_handle.setdefault(edge.source_handle, []).append(
            (vertices[edge.start], vertices[edge.end], edge.center, edge.sweep)
        )
    # The reflected quarter is canonicalized as a CCW sub-arc with its true WCS
    # midpoint at (-sqrt(2), sqrt(2)) and endpoints (-2, 0) and (0, 2).
    points = {point for start, end, _center, _sweep in by_handle["A1"] for point in (start, end)}
    assert any(math.dist(point, (-2.0, 0.0, 0.0)) < 1e-9 for point in points)
    assert any(math.dist(point, (0.0, 2.0, 0.0)) < 1e-9 for point in points)
    assert all(abs(edge[3] - math.pi / 2) < 1e-9 for edge in by_handle["A1"])
    samples = sample_edges(project)
    reflected_points = [
        point for edge in project.edges if edge.source_handle == "A1" for point in samples[edge.id]
    ]
    assert min(
        math.dist(point, (-math.sqrt(2.0), math.sqrt(2.0), 0.0)) for point in reflected_points
    ) < 0.1  # fixed 4-degree tessellation may not land exactly on the 135-degree midpoint
    # The deliberate gap is not snapped: the two components keep distinct ends.
    assert (-2.0, 0.01, 0.0) in {tuple(round(v, 9) for v in edge[0]) for edge in by_handle["L2"]}


def test_nonplanar_extrusion_is_a_typed_skip():
    entity = {
        "handle": "T1",
        "type": "ARC",
        "layer": "0",
        "transformError": "unsupported-nonplanar",
        "center": [0.0, 0.0, 0.0],
        "radius": 1.0,
    }
    project, report = import_inventory(
        inventory([entity, line("L1", (0.0, 0.0), (1.0, 0.0))]), "Tilted"
    )
    assert [item["reason"] for item in report["skipped"]] == ["unsupported-nonplanar"]
    assert any("unsupported-nonplanar" in warning for warning in report["warnings"])


@pytest.mark.skipif(not APLR.is_file(), reason="original APLR drawing is not present locally")
def test_aplr_imports_one_door_one_body_and_two_cavities():
    from hashlib import sha256

    assert sha256(APLR.read_bytes()).hexdigest() == APLR_SHA256
    native = dwg.read(APLR)
    assert native["source"]["bytes"] == 18946
    assert native["source"]["version"] == "AC1032"
    assert native["counts"] == {"ARC": 48, "LINE": 31}
    arcs = [entity for entity in native["entities"] if entity["type"] == "ARC"]
    assert {entity["handle"] for entity in arcs if entity["normal"][2] < 0} == NEGATIVE_NORMAL_ARCS
    assert all(abs(entity["normal"][2]) > 0.999999 for entity in arcs)

    project, report = import_inventory(native, "APLR", digest=APLR_SHA256)
    assert len(project.components) == 3
    assert {component.id for component in project.components} == {"section", "section2", "section3"}
    assert report["openChains"] == 2
    assert report["regions"] == 1 and report["cavities"] == 2
    assert report["filledArea"] == pytest.approx(121.06283, abs=1e-4)

    handles = {}
    for edge in project.edges:
        handles.setdefault(edge.component, set()).add(edge.source_handle)
    door = next(component for component in handles if handles[component] == {
        "FA", "FB", "FC", "FD", "FE", "FF", "100", "101"
    })
    body = next(component for component in handles if handles[component] >= {
        "102", "104", "106", "108", "10A", "10C", "10E", "110", "111"
    })
    seal = next(component for component in handles if component not in (door, body))
    assert len(handles[body]) >= 16
    assert sum(1 for edge in project.edges if edge.component == seal) >= 60

    # Exact measured free endpoints from the native source bytes (mm).
    assert_endpoints(
        degree_one(project, door),
        [(11.517131474, 62.337321442, 0.0), (30.741156722, 62.326254097, 0.0)],
    )
    assert_endpoints(
        degree_one(project, body),
        [(12.805847070, 28.486415157, 0.0), (36.317131474, 31.326254097, 0.0)],
    )

    # The mid-arc WCS point of every reflected handle is independently derived
    # from the native OCS centre, radius, angle and extrusion: for -Z the WCS
    # transform is (x, y) -> (-x, y).
    for entity in arcs:
        if entity["handle"] not in NEGATIVE_NORMAL_ARCS:
            continue
        # Independent of the helper's world conversion: take the native OCS
        # centre and angles it also reports, evaluate the interior point at half
        # the OCS sweep, then apply the -Z basis (x, y) -> (-x, y).
        ocs = entity["ocs"]
        start = ocs["startAngle"]
        sweep = (ocs["endAngle"] - start) % math.tau
        mid_angle = start + sweep / 2
        expected = (
            -(ocs["center"][0] + entity["radius"] * math.cos(mid_angle)),
            ocs["center"][1] + entity["radius"] * math.sin(mid_angle),
            0.0,
        )
        assert entity["sweep"] < 0
        assert math.dist(entity["mid"], expected) < 1e-6, entity["handle"]


@pytest.mark.skipif(not APLR.is_file(), reason="original APLR drawing is not present locally")
def test_shipped_helper_reports_planar_wcs_for_every_supported_primitive():
    completed = subprocess.run(
        [str(dwg.helper()), str(APLR)], capture_output=True, check=True, timeout=120
    )
    import json

    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["reader"]["name"] == "ACadSharp"
    for entity in payload["entities"]:
        if entity["type"] in {"ARC", "CIRCLE", "LWPOLYLINE"}:
            assert "normal" in entity
            assert "transformError" not in entity
        if entity["type"] == "ARC":
            assert "sweep" in entity and "mid" in entity
            assert abs(entity["sweep"]) > 0
