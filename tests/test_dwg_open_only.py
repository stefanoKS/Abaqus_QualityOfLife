"""Gate 3: open-only drawings, endpoint joins and both spline representations.

The private native drawings stay local. These tests use manufactured inventories
with the same record shape the DWG reader returns, plus the two repository
example drawings whose hashes identify the documented positive cases.
"""

import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.engineering.dwg import import_inventory
from packages.engineering.geometry import Builder, face_polygon, sample_edges
from packages.engineering.model import Project
from packages.engineering.partition import arrange
from packages.engineering.section import JOIN_TOLERANCE
from packages.engineering.spline import curve
from services import store
from services.api.main import app
from services.worker.__main__ import once

from support import create_model

ROOT = Path(__file__).resolve().parents[1]
ROOT_SHA = "0" * 64


def inventory(entities, units=4):
    return {
        "reader": {"name": "ACadSharp", "version": "3.8.35", "license": "MIT"},
        "source": {
            "path": "manufactured.dwg",
            "bytes": 4096,
            "sha256": ROOT_SHA,
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


def fit_spline(handle, points, closed=False):
    """Open (or closed) fit-point-only cubic, the BE representation."""
    return {
        "handle": handle,
        "type": "SPLINE",
        "layer": "0",
        "degree": 3,
        "controlPoints": [],
        "fitPoints": [[point[0], point[1], 0.0] for point in points],
        "closed": closed,
        "periodic": False,
    }


def control_spline(handle, poles, closed=False, knots=None, weights=None):
    """Control-point (pole) cubic, the BF representation."""
    return {
        "handle": handle,
        "type": "SPLINE",
        "layer": "0",
        "degree": 3,
        "controlPoints": [[point[0], point[1], 0.0] for point in poles],
        "fitPoints": [],
        "knots": list(knots or []),
        "weights": list(weights or []),
        "closed": closed,
        "periodic": False,
    }


def line(handle, start, end):
    return {
        "handle": handle,
        "type": "LINE",
        "layer": "0",
        "start": [start[0], start[1], 0.0],
        "end": [end[0], end[1], 0.0],
    }


def open_pair():
    """Two disconnected open splines: one fit-point, one control-point."""
    return [
        fit_spline("BE", [[0, 0], [5, 1], [10, -1], [15, 0.5], [20, 0]]),
        control_spline(
            "BF", [[30, 0], [34, 3], [38, -3], [42, 3], [46, -3], [50, 0]]
        ),
    ]


def test_open_only_drawing_imports_as_an_inspectable_model():
    project, report = import_inventory(inventory(open_pair()), "Open only")

    # Zero closed material faces, both source curves preserved.
    assert project.faces == []
    assert len(project.edges) == 2
    assert {edge.source_handle for edge in project.edges} == {"BE", "BF"}
    assert all(edge.kind == "spline" for edge in project.edges)
    assert report["closedRegions"] == 0
    assert report["regions"] == 0
    assert report["cavities"] == 0
    assert report["openChains"] == 2
    assert report["readiness"]["code"] == "drawing.no_closed_region"
    assert len(report["openProfiles"]) == 2
    # Two selectable components: the curves are not merged into one profile.
    with_edges = [
        component
        for component in project.components
        if any(edge.component == component.id for edge in project.edges)
    ]
    assert len(with_edges) == 2
    assert all(component.role == "unassigned" for component in with_edges)

    # Each representation keeps its own authoritative data.
    be = next(edge for edge in project.edges if edge.source_handle == "BE")
    bf = next(edge for edge in project.edges if edge.source_handle == "BF")
    assert be.spline.fit_points and not be.spline.control_points
    assert bf.spline.control_points and not bf.spline.fit_points
    assert len(bf.spline.knots) == len(bf.spline.control_points) + bf.spline.degree + 1
    assert bf.spline.closed is False


def test_open_only_import_is_deterministic_and_round_trips():
    first, first_report = import_inventory(inventory(open_pair()), "Open only")
    second, second_report = import_inventory(inventory(open_pair()), "Open only")
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first_report == second_report
    # Reversing the entity order keeps the same topology, curves and area. Entity
    # identifiers are assigned in reading order, so their labels differ by design.
    reversed_project, reversed_report = import_inventory(
        inventory(list(reversed(open_pair()))), "Open only"
    )
    assert len(reversed_project.edges) == len(first.edges)
    assert reversed_project.faces == first.faces == []
    assert reversed_report["openChains"] == first_report["openChains"]
    assert sorted(edge.source_handle for edge in reversed_project.edges) == ["BE", "BF"]
    for handle in ("BE", "BF"):
        original = next(edge for edge in first.edges if edge.source_handle == handle)
        reordered = next(edge for edge in reversed_project.edges if edge.source_handle == handle)
        assert original.spline == reordered.spline
    # The document round-trips without losing curves or provenance.
    restored = Project.model_validate(first.model_dump(mode="json"))
    assert restored.model_dump(mode="json") == first.model_dump(mode="json")
    assert restored.source.digest == ROOT_SHA


def test_open_only_drawing_is_saved_and_blocked_with_a_specific_reason(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path / "data"))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        revision = create_model(api, "Open drawing")
        project, _report = import_inventory(inventory(open_pair()), "Open drawing")
        from services import store

        saved = store.save(
            project.model_dump(mode="json"),
            project=revision["project"],
            base=revision["id"],
            source_id=None,
        )
        document = api.get("/api/revisions/" + saved["id"] + "/readiness").json()
        assert document["can_prepare"] is False
        assert document["can_submit"] is False
        codes = [item["code"] for item in document["findings"] if item["severity"] == "blocker"]
        assert codes[0] == "drawing.no_closed_region"
        blocker = document["findings"][0]
        assert blocker["stage"] == "import"
        assert blocker["params"]["open_profiles"] == 2
        assert document["counts"]["regions"] == 0
        assert document["stage_states"]["import"] == {
            "state": "incomplete",
            "code": "drawing.no_closed_region",
        }
        assert document["stage_states"]["materials"]["code"] == "drawing.no_closed_region"
        assert document["stage_states"]["mesh"]["code"] == "drawing.no_closed_region"

        # The engineer can still open, inspect and save the curves: renaming the
        # model keeps both splines, zero faces and the reading order.
        current = api.get("/api/revisions/" + saved["id"]).json()
        setup = current["setup"]
        setup["name"] = "Open drawing inspected"
        response = api.put(
            "/api/projects/" + revision["project"],
            json={"base": saved["id"], "setup": setup},
        )
        assert response.is_success, response.text
        edited = response.json()
        assert edited["setup"]["name"] == "Open drawing inspected"
        assert len(edited["setup"]["edges"]) == 2
        assert edited["setup"]["faces"] == []
        assert {edge["kind"] for edge in edited["setup"]["edges"]} == {"spline"}
        # Simulation is still blocked after the editable save.
        again = api.get("/api/revisions/" + edited["id"] + "/readiness").json()
        assert again["can_prepare"] is False


def _rectangular_wire(gap):
    """Fit spline + control spline + two lines, with an optional end gap."""
    start = (10 + gap, 0)
    return [
        fit_spline("B1", [[0, 0], [4, 1], [7, -1], [10, 0]]),
        control_spline("B2", [start, (start[0], 2), (start[0], 4), (start[0], 6)]),
        line("L1", (0, 0), (0, 6)),
        line("L2", (0, 6), (start[0], 6)),
    ]


def _area(project):
    samples = sample_edges(project)
    return sum(
        face_polygon(face, samples).area for face in project.faces if not face.cavity
    )


def test_endpoints_within_the_spline_tolerance_join_into_one_region():
    # The fit spline's evaluated end and the pole spline's first point differ by
    # half the existing 1e-6 mm join tolerance.
    project, report = import_inventory(inventory(_rectangular_wire(5e-7)), "Near miss")
    assert report["joins"]["tolerance"] == JOIN_TOLERANCE
    assert report["joins"]["snapped"] + report["joins"]["merged"] >= 1
    assert report["joins"]["maxGap"] <= JOIN_TOLERANCE
    assert report["joins"]["gaps"]
    assert report["closedRegions"] == 1
    assert len([face for face in project.faces if not face.cavity]) == 1
    assert len(project.edges) == 4
    assert _area(project) > 30


def test_a_gap_outside_the_tolerance_is_reported_not_bridged():
    project, report = import_inventory(inventory(_rectangular_wire(1e-3)), "Real gap")
    assert report["joins"]["merged"] == 0
    assert report["joins"]["snapped"] == 0
    assert report["joins"]["nearestGap"] >= 9e-4
    assert report["closedRegions"] == 0
    assert project.faces == []
    assert report["openChains"] == 1
    assert report["readiness"]["code"] == "drawing.no_closed_region"
    # The measurement is reported by endpoint id, not invented as material.
    assert len(report["joins"]["nearestPair"]) == 2


def test_closed_mixed_spline_loop_with_a_cavity():
    outer = [
        [10 * math.cos(math.tau * i / 12), 10 * math.sin(math.tau * i / 12)] for i in range(12)
    ]
    inner = [
        [5 * math.cos(math.tau * i / 10), 5 * math.sin(math.tau * i / 10)] for i in range(10)
    ]
    entities = [
        control_spline("OUT", outer + [outer[0]], closed=True),
        fit_spline("IN", inner + [inner[0]], closed=True),
    ]
    project, report = import_inventory(inventory(entities), "Mixed cavity")
    assert report["closedRegions"] == 1
    assert len([face for face in project.faces if not face.cavity]) == 1
    assert len([face for face in project.faces if face.cavity]) == 1
    outer_area = report["filledArea"]
    cavity = next(face for face in project.faces if face.cavity)
    cavity_area = face_polygon(cavity, sample_edges(project)).area
    # The cavity keeps its own classified loop and is excluded from filled area.
    assert 25 < cavity_area < 100
    assert outer_area > cavity_area * 2


def test_join_is_independent_of_entity_order_and_parameter_direction():
    forward, forward_report = import_inventory(inventory(_rectangular_wire(5e-7)), "Near miss")
    reversed_entities = list(reversed(_rectangular_wire(5e-7)))
    backward, backward_report = import_inventory(inventory(reversed_entities), "Near miss")
    assert forward_report["regions"] == backward_report["regions"] == 1
    # Declared agreement between reading orders: 1e-4 mm² on a ~59 mm² region.
    assert abs(_area(forward) - _area(backward)) <= 1e-4
    # Reversing the pole order describes the same curve backwards.
    reversed_poles = control_spline(
        "B2", [(10 + 5e-7, 6), (10 + 5e-7, 4), (10 + 5e-7, 2), (10 + 5e-7, 0)]
    )
    entities = [
        fit_spline("B1", [[0, 0], [4, 1], [7, -1], [10, 0]]),
        reversed_poles,
        line("L1", (0, 0), (0, 6)),
        line("L2", (0, 6), (10 + 5e-7, 6)),
    ]
    reversed_curve, reversed_curve_report = import_inventory(inventory(entities), "Near miss")
    assert reversed_curve_report["regions"] == 1
    assert abs(_area(reversed_curve) - _area(forward)) <= 1e-4


def test_fit_only_curve_passes_through_its_fit_points_and_poles_match_de_boor():
    fits = [[0, 0], [5, 2], [10, -1], [15, 3], [20, 0]]
    project, _report = import_inventory(inventory([fit_spline("BE", fits)]), "Fit check")
    edge = next(edge for edge in project.edges if edge.source_handle == "BE")
    spline = curve(edge.spline)
    samples = [tuple(spline.point(spline.max_t * i / 4000))[:2] for i in range(4001)]
    # Declared fit residual for fit-only CAD reconstruction: 0.01 mm.
    for point in fits:
        nearest = min(math.dist(point, sample) for sample in samples)
        assert nearest <= 0.01, (point, nearest)

    poles = [[0, 0], [3, 4], [7, -4], [10, 0], [13, 4], [16, 0]]
    knots = [0, 0, 0, 0, 0.3, 0.6, 1, 1, 1, 1]
    project, _ = import_inventory(
        inventory([control_spline("BF", poles, knots=knots)]), "Pole check"
    )
    edge = next(edge for edge in project.edges if edge.source_handle == "BF")
    assert edge.spline.knots == [float(knot) for knot in knots]
    spline = curve(edge.spline)
    for index in range(1, 20):
        t = spline.max_t * index / 20
        expected = de_boor(poles, knots, 3, index / 20)
        actual = tuple(spline.point(t))[:2]
        assert math.dist(expected, actual) <= 1e-9, (index, expected, actual)


def de_boor(poles, knots, degree, u):
    """Independent textbook de Boor recurrence used only as a reference."""
    n = len(poles) - 1
    span = degree
    while span < n and not (knots[span] <= u < knots[span + 1]):
        span += 1
    d = [list(poles[span - degree + j]) for j in range(degree + 1)]
    for r in range(1, degree + 1):
        for j in range(degree, r - 1, -1):
            left = knots[span - degree + j]
            right = knots[span + 1 + j - r]
            alpha = 0.0 if right == left else (u - left) / (right - left)
            d[j] = [
                (1 - alpha) * d[j - 1][axis] + alpha * d[j][axis] for axis in range(2)
            ]
    return tuple(d[degree][:2])


@pytest.mark.parametrize(
    "source,upload_name,sha_prefix,handles",
    [
        ("spline_test.dwg", "spline_test.dwg", "b874fa5168", {"BF", "C3"}),
        # The backup is DWG bytes under a temporary upload name.
        ("spline_test.bak", "spline_test_backup.dwg", "5a4b114f42", {"BE", "BF"}),
    ],
)
def test_documented_spline_drawings_import_through_the_normal_worker(
    monkeypatch, tmp_path, source, upload_name, sha_prefix, handles
):
    """The two passing cases in Gate 3 stay passing through upload → worker."""
    path = ROOT / "examples" / source
    if not path.is_file():
        pytest.skip("the local native drawing fixture is absent")
    monkeypatch.setenv("SEAL_DATA", str(tmp_path / "data"))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        project = api.post("/api/projects", json={"name": "Spline drawing"}).json()
        upload = api.post(
            "/api/projects/" + project["project"] + "/drawing",
            data={"base": project["id"], "units": "N-mm-s-tonne"},
            files={"file": (upload_name, path.read_bytes())},
        )
        assert upload.is_success, upload.text
        assert once("dwg")
        job = store.job(upload.json()["id"])
        assert job["status"] == "Completed", job["diagnostic"]
        report = json.loads((store.job_dir(job["id"]) / "import-report.json").read_text())
        assert report["sourceSha256"].startswith(sha_prefix)
        assert report["splines"] == 2
        revision = api.get("/api/jobs/" + job["id"] + "/imported").json()
        setup = revision["setup"]
        splines = [edge for edge in setup["edges"] if edge["kind"] == "spline"]
        assert {edge["source_handle"] for edge in splines} == handles
        assert len(splines) == 2
        assert len(setup["faces"]) == 1
        assert report["closedRegions"] == 1


def test_a_non_separating_wall_cut_leaves_the_topology_intact():
    outer = [
        [10 * math.cos(math.tau * i / 12), 10 * math.sin(math.tau * i / 12)] for i in range(12)
    ]
    inner = [
        [5 * math.cos(math.tau * i / 10), 5 * math.sin(math.tau * i / 10)] for i in range(10)
    ]
    project, _report = import_inventory(
        inventory(
            [
                control_spline("OUT", outer + [outer[0]], closed=True),
                fit_spline("IN", inner + [inner[0]], closed=True),
            ]
        ),
        "Wall cut",
    )
    face = next(face for face in project.faces if not face.cavity)
    next(component for component in project.components if component.id == face.component).role = "seal"
    before = [(item.id, len(item.loops)) for item in project.faces]
    result = arrange(project, face.id, [((10, 0), (6, 0))], seed="wall")
    # A cut that starts and ends on the same boundary does not separate material.
    assert result["status"] == "one_region"
    assert [(item.id, len(item.loops)) for item in project.faces] == before
