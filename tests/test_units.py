"""Drawing unit policy: normalize every imported world length to mm exactly once.

Physically identical geometry declared in millimetres, inches, centimetres,
metres and US survey feet must land on the same project millimetres. The
original declaration, numeric factor and provenance are recorded beside the
source digest, and reopening or duplicating a saved revision never scales again.

No licensed solver is used here.
"""

from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient

from packages import engineering
from packages.engineering import units as units_policy
from packages.engineering.dwg import _drawing_units
from packages.engineering.model import Project
from packages.engineering.mesh import generate_mesh
from services import store
from services.api.main import app
from support import create_model, run_worker

MM_PER_INCH = 25.4


def write_dxf(path: Path, unit_code="__missing__", *, scale=1.0, measurement=None, shapes=None):
    """A minimal closed section plus a rigid PANEL line, in drawing units."""
    doc = ezdxf.new("R2010")
    if unit_code == "__missing__":
        if "$INSUNITS" in doc.header:
            del doc.header["$INSUNITS"]
    else:
        doc.header["$INSUNITS"] = unit_code
    if measurement is not None:
        doc.header["$MEASUREMENT"] = measurement
    model = doc.modelspace()
    box = [(0, 0), (10, 0), (10, 4), (0, 4)]
    model.add_lwpolyline(
        [(x / scale, y / scale) for x, y in box],
        close=True,
        dxfattribs={"layer": "SECTION"},
    )
    model.add_line((0, 9 / scale), (10 / scale, 9 / scale), dxfattribs={"layer": "PANEL"})
    if shapes == "arc_spline":
        model.add_arc(
            center=(5 / scale, 4 / scale),
            radius=2 / scale,
            start_angle=0,
            end_angle=180,
            dxfattribs={"layer": "SECTION"},
        )
        model.add_spline(
            [(1 / scale, 6 / scale), (4 / scale, 7 / scale), (8 / scale, 6 / scale)],
            dxfattribs={"layer": "SECTION"},
        )
    doc.saveas(path)
    return path


def bounds(project):
    xs = [vertex.xyz[0] for vertex in project.vertices]
    ys = [vertex.xyz[1] for vertex in project.vertices]
    return (min(xs), max(xs), min(ys), max(ys))


def test_unit_policy_values():
    assert units_policy.interpret(None).basis == units_policy.HEADER_MISSING_AS_MM
    assert units_policy.interpret(None).factor == 1.0
    assert units_policy.interpret(0).basis == units_policy.UNITLESS_AS_MM
    assert units_policy.interpret(0).note == units_policy.UNITLESS_NOTE
    mm = units_policy.interpret(4)
    assert mm.basis == units_policy.DECLARED_MM and mm.factor == 1.0
    assert units_policy.interpret("Millimeters").basis == units_policy.DECLARED_MM

    inches = units_policy.interpret(1)
    assert inches.factor == pytest.approx(25.4)
    assert inches.basis == units_policy.CONVERTED_TO_MM
    assert "inches" in inches.note

    assert units_policy.interpret(5).factor == pytest.approx(10.0)
    assert units_policy.interpret(6).factor == pytest.approx(1000.0)
    assert units_policy.interpret(13).factor == pytest.approx(0.001)
    assert units_policy.interpret(21).factor == pytest.approx(304.8006096012192)
    assert units_policy.interpret("US Survey Inch").factor == pytest.approx(
        25.4000508001016, abs=1e-9
    )
    assert units_policy.interpret("µm").factor == pytest.approx(0.001)
    # ACadSharp emits enum names rather than numbers for the DWG inventory.
    assert units_policy.interpret("USSurveyFeet").factor == pytest.approx(304.8006096012192)
    assert units_policy.interpret("Inches").factor == pytest.approx(25.4)

    with pytest.raises(ValueError, match="unreadable"):
        units_policy.interpret(99)
    with pytest.raises(ValueError, match="banana"):
        units_policy.interpret("banana")
    mixed = units_policy.interpret(1, "DXF", measurement=1)
    assert mixed.factor == pytest.approx(25.4)
    assert "inconsistency" in mixed.warning


def test_interpretation_records_and_range_checks():
    inches = units_policy.interpret(1)
    assert inches.apply(2.0) == pytest.approx(50.8)
    assert inches.point((1.0, 2.0, 0.0)) == pytest.approx((25.4, 50.8, 0.0))
    with pytest.raises(ValueError, match="project range"):
        inches.apply(1e7)
    with pytest.raises(ValueError, match="non-finite"):
        inches.apply(float("nan"))


@pytest.mark.parametrize(
    "code,basis,note",
    [
        (4, "declared_mm", "millimetres"),
        (0, "unitless_as_mm", "unitless drawing interpreted as mm"),
        ("__missing__", "header_missing_as_mm", "unit header missing"),
    ],
)
def test_dxf_records_the_unit_basis(tmp_path, code, basis, note):
    path = write_dxf(tmp_path / "section.dxf", code)
    project = engineering.import_dxf(path, "Units")
    assert project.source.unit_basis == basis
    assert note in project.source.drawing_units
    assert project.source.unit_declaration
    assert project.source.unit_provenance


@pytest.mark.parametrize(
    "code,scale",
    [
        (1, MM_PER_INCH),
        (5, 10.0),
        (6, 1000.0),
        (21, 304.8006096012192),
    ],
)
def test_inch_cm_metre_and_survey_geometry_match_the_mm_reference(tmp_path, code, scale):
    """Cross-format paired fixture: same physical shape, four declarations."""
    mm_project = engineering.import_dxf(write_dxf(tmp_path / "mm.dxf", 4), "Reference")
    project = engineering.import_dxf(
        write_dxf(tmp_path / f"unit{code}.dxf", code, scale=scale), "Converted"
    )
    assert bounds(project) == pytest.approx(bounds(mm_project), abs=1e-6)
    assert project.source.unit_factor == pytest.approx(scale)
    assert project.source.unit_basis == "converted_to_mm"
    # Areas, representative points and the derived mesh extents agree.
    mm_face = next(face for face in mm_project.faces if not face.cavity)
    face = next(face for face in project.faces if not face.cavity)
    from packages.engineering import partition

    def assign_engineering_roles(candidate, candidate_face):
        for candidate_component in candidate.components:
            candidate_component.role = "unassigned"
        for candidate_region in candidate.faces:
            if not candidate_region.cavity:
                candidate_region.material = candidate.materials[0].id
        next(
            c for c in candidate.components if c.id == candidate_face.component
        ).role = "seal"
        panel_component = next(
            edge.component for edge in candidate.edges if edge.component != candidate_face.component
        )
        next(c for c in candidate.components if c.id == panel_component).role = "moving_panel"
        # Reader-side helper components without geometry still carry a supported
        # role; they own no region and therefore do not change the step plan.
        for candidate_component in candidate.components:
            if candidate_component.role == "unassigned":
                candidate_component.role = "seal"

    assign_engineering_roles(mm_project, mm_face)
    assign_engineering_roles(project, face)
    mm_plan = partition.plan(mm_project, mm_face.id, (5.0, 0.0), (5.0, 4.0), seed="units")
    plan = partition.plan(project, face.id, (5.0, 0.0), (5.0, 4.0), seed="units")
    assert plan["area_a"] == pytest.approx(mm_plan["area_a"], rel=1e-9)
    assert plan["area_b"] == pytest.approx(mm_plan["area_b"], rel=1e-9)
    assert [v for point in plan["line"] for v in point] == pytest.approx(
        [v for point in mm_plan["line"] for v in point], abs=1e-9
    )
    mm_mesh = generate_mesh(mm_project)
    mesh = generate_mesh(project)
    # The converted boundary values differ from the reference by ~1e-15 mm; the
    # mesher may place one extra row of elements at that boundary. Physical
    # extents and the element family are what must agree.
    assert set(mesh["counts"]) == set(mm_mesh["counts"])
    for kind, count in mesh["counts"].items():
        assert count == pytest.approx(mm_mesh["counts"][kind], rel=0.05)
    mm_extent = [v for node in mm_mesh["nodes"] for v in node["xyz"][:2]]
    extent = [v for node in mesh["nodes"] for v in node["xyz"][:2]]
    assert min(extent) == pytest.approx(min(mm_extent), abs=1e-6)
    assert max(extent) == pytest.approx(max(mm_extent), abs=1e-6)
    # Physical mesh extents agree within the drawing's conversion tolerance.
    assert max(extent) - min(extent) == pytest.approx(
        max(mm_extent) - min(mm_extent), abs=1e-6
    )
    # A saved and reopened revision is still millimetres: no second scaling.
    reopened = Project.model_validate(project.model_dump(mode="json"))
    assert bounds(reopened) == pytest.approx(bounds(project), abs=1e-9)
    assert reopened.source.unit_factor == pytest.approx(scale)


def _inventory(scale, units_code):
    def p(x, y):
        return [x / scale, y / scale, 0.0]

    return {
        "source": {"insUnits": units_code, "sha256": "b" * 64, "path": "drawing.dwg"},
        "entities": [
            {"type": "LINE", "handle": "L1", "layer": "SECTION", "start": p(0, 0), "end": p(10, 0)},
            {"type": "LINE", "handle": "L2", "layer": "SECTION", "start": p(10, 0), "end": p(10, 4)},
            {"type": "LINE", "handle": "L3", "layer": "SECTION", "start": p(10, 4), "end": p(0, 4)},
            {"type": "LINE", "handle": "L4", "layer": "SECTION", "start": p(0, 4), "end": p(0, 0)},
            {
                "type": "ARC",
                "handle": "A1",
                "layer": "PANEL",
                "center": p(5, 8),
                "radius": 2 / scale,
                "startAngle": 0.0,
                "endAngle": 3.141592653589793,
            },
            {
                "type": "SPLINE",
                "handle": "S1",
                "layer": "PANEL",
                "degree": 3,
                "controlPoints": [p(0, 12), p(4, 14), p(7, 11), p(10, 13)],
                "knots": [],
                "weights": [],
            },
            {"type": "LINE", "handle": "P1", "layer": "PANEL", "start": p(0, 20), "end": p(10, 20)},
        ],
    }


def test_dwg_arc_and_spline_are_scaled_once():
    mm_project, _ = engineering.dwg.import_inventory(_inventory(1.0, 4), "Reference")
    inch_project, inch_report = engineering.dwg.import_inventory(
        _inventory(MM_PER_INCH, 1), "Inch"
    )
    assert bounds(inch_project) == pytest.approx(bounds(mm_project), abs=1e-6)
    assert inch_project.source.unit_factor == pytest.approx(MM_PER_INCH)
    assert inch_report["unitFactor"] == pytest.approx(MM_PER_INCH)
    mm_arc = next(edge for edge in mm_project.edges if edge.kind == "arc")
    arc = next(edge for edge in inch_project.edges if edge.kind == "arc")
    assert arc.center == pytest.approx(mm_arc.center, abs=1e-6)
    assert arc.sweep == pytest.approx(mm_arc.sweep)
    mm_spline = next(edge for edge in mm_project.edges if edge.kind == "spline")
    spline = next(edge for edge in inch_project.edges if edge.kind == "spline")
    assert [v for point in spline.spline.control_points for v in point] == pytest.approx(
        [v for point in mm_spline.spline.control_points for v in point], abs=1e-6
    )
    assert spline.spline.knots == pytest.approx(mm_spline.spline.knots)


def test_unreadable_and_inconsistent_headers_are_named(tmp_path):
    with pytest.raises(ValueError, match="unreadable"):
        engineering.import_dxf(write_dxf(tmp_path / "bad.dxf", 99), "Bad")
    # Contradictory $MEASUREMENT is reported, not silently used to rescale.
    mixed = engineering.import_dxf(write_dxf(tmp_path / "mixed.dxf", 1, measurement=1), "Mixed")
    assert mixed.source.unit_factor == pytest.approx(25.4)
    assert "inconsistency" in mixed.source.unit_provenance
    # Converted coordinates outside the project range are refused, not clamped.
    with pytest.raises(ValueError, match="project range"):
        engineering.import_dxf(
            write_dxf(tmp_path / "huge.dxf", 3), "Huge"
        )


def test_dwg_unit_basis_uses_the_same_policy():
    assert _drawing_units({"insUnits": 4}).basis == "declared_mm"
    assert _drawing_units({"insUnits": 0}).basis == "unitless_as_mm"
    assert _drawing_units({}).basis == "header_missing_as_mm"
    assert _drawing_units({"insUnits": None, "insUnitsName": "Millimeters"}).basis == "declared_mm"
    inches = _drawing_units({"insUnits": 1})
    assert inches.factor == pytest.approx(25.4)
    with pytest.raises(ValueError, match="banana"):
        _drawing_units({"insUnits": "banana"})


def test_dwg_inventory_scaling_is_applied_exactly_once():
    inventory = {
        "source": {"insUnits": 1, "sha256": "a" * 64, "path": "inch.dwg"},
        "entities": [
            {
                "type": "LINE",
                "handle": "A",
                "layer": "SECTION",
                "start": [0.0, 0.0, 0.0],
                "end": [10.0, 0.0, 0.0],
            },
            {
                "type": "LINE",
                "handle": "B",
                "layer": "SECTION",
                "start": [10.0, 0.0, 0.0],
                "end": [10.0, 4.0, 0.0],
            },
            {
                "type": "LINE",
                "handle": "C",
                "layer": "SECTION",
                "start": [10.0, 4.0, 0.0],
                "end": [0.0, 0.0, 0.0],
            },
            {
                "type": "LINE",
                "handle": "D",
                "layer": "PANEL",
                "start": [0.0, 9.0, 0.0],
                "end": [10.0, 9.0, 0.0],
            },
        ],
    }
    project, report = engineering.dwg.import_inventory(inventory, "Inch DWG")
    assert project.source.unit_factor == pytest.approx(25.4)
    assert bounds(project)[:2] == pytest.approx((0.0, 254.0), abs=1e-6)
    assert report["unitFactor"] == pytest.approx(25.4)
    reopened = Project.model_validate(project.model_dump(mode="json"))
    assert bounds(reopened)[:2] == pytest.approx((0.0, 254.0), abs=1e-6)


def test_api_import_converts_and_records_units(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path / "data"))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        revision = create_model(api, "Units", example=False)
        url = f"/api/projects/{revision['project']}/drawing"

        # No unit form field: the drawing's own declaration decides the factor.
        # 10 drawing inches on each side: 254 mm after the recorded conversion.
        inches = write_dxf(tmp_path / "inches.dxf", 1, scale=1.0)
        response = api.post(
            url,
            data={"base": revision["id"]},
            files={"file": ("inches.dxf", inches.read_bytes())},
        )
        assert response.status_code == 202, response.text
        run_worker("units")
        imported = api.get(f"/api/jobs/{response.json()['id']}/imported").json()
        setup = imported["setup"]
        assert setup["source"]["unit_basis"] == "converted_to_mm"
        assert setup["source"]["unit_factor"] == pytest.approx(25.4)
        assert setup["source"]["unit_declaration"] == "inches"
        xs = [vertex["xyz"][0] for vertex in setup["vertices"]]
        assert max(xs) == pytest.approx(254.0)

        # Re-saving the revision must not scale a second time.
        saved = api.put(
            f"/api/projects/{revision['project']}",
            json={"base": imported["id"], "setup": setup},
        )
        assert saved.status_code == 200, saved.text
        again = api.get(f"/api/revisions/{saved.json()['id']}").json()
        assert max(vertex["xyz"][0] for vertex in again["setup"]["vertices"]) == pytest.approx(254.0)

        # A corrupt file fails as a job and leaves the saved drawing intact.
        broken = api.post(
            url,
            data={"base": again["id"]},
            files={"file": ("broken.dxf", b"not a dxf")},
        )
        assert broken.is_success, broken.text
        run_worker("units")
        assert store.job(broken.json()["id"])["status"] == "Failed"
        assert (
            api.get(f"/api/revisions/{again['id']}").json()["setup"]["source"]["filename"]
            == "inches.dxf"
        )
