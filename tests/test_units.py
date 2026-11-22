"""Drawing unit policy: declared mm, unitless-as-mm, missing header, other units.

The policy is recorded on the imported revision. A unitless drawing is
interpreted as project millimetres and recorded as such; a drawing declaring
another unit is rejected with that unit named; no drawing is silently
converted.
"""

from pathlib import Path

import ezdxf
import pytest
from fastapi.testclient import TestClient

from packages import engineering
from packages.engineering import units as units_policy
from packages.engineering.dwg import _drawing_units
from services import store
from services.api.main import app
from support import create_model, run_worker


def write_dxf(path: Path, unit_code="__missing__"):
    """A minimal closed section plus a rigid PANEL line."""
    doc = ezdxf.new("R2010")
    if unit_code == "__missing__":
        if "$INSUNITS" in doc.header:
            del doc.header["$INSUNITS"]
    else:
        doc.header["$INSUNITS"] = unit_code
    model = doc.modelspace()
    model.add_lwpolyline(
        [(0, 0), (10, 0), (10, 4), (0, 4)],
        close=True,
        dxfattribs={"layer": "SECTION"},
    )
    model.add_line((0, 8), (10, 8), dxfattribs={"layer": "PANEL"})
    doc.saveas(path)
    return path


def test_unit_policy_values():
    assert units_policy.interpret(None) == (
        units_policy.HEADER_MISSING_AS_MM,
        units_policy.MISSING_NOTE,
    )
    assert units_policy.interpret(0) == (
        units_policy.UNITLESS_AS_MM,
        units_policy.UNITLESS_NOTE,
    )
    assert units_policy.interpret(4)[0] == units_policy.DECLARED_MM
    assert units_policy.interpret("Millimeters")[0] == units_policy.DECLARED_MM
    with pytest.raises(ValueError, match="inches"):
        units_policy.interpret(1)
    with pytest.raises(ValueError, match="unreadable"):
        units_policy.interpret(99)


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


def test_dxf_rejects_inches_and_unreadable_headers_by_name(tmp_path):
    with pytest.raises(ValueError, match="inches"):
        engineering.import_dxf(write_dxf(tmp_path / "inches.dxf", 1), "Inches")
    with pytest.raises(ValueError, match="unreadable"):
        engineering.import_dxf(write_dxf(tmp_path / "bad.dxf", 99), "Bad")


def test_dwg_unit_basis_uses_the_same_policy():
    assert _drawing_units({"insUnits": 4})[0] == "declared_mm"
    assert _drawing_units({"insUnits": 0})[0] == "unitless_as_mm"
    assert _drawing_units({})[0] == "header_missing_as_mm"
    assert _drawing_units({"insUnits": None, "insUnitsName": "Millimeters"})[0] == "declared_mm"
    with pytest.raises(ValueError, match="inches"):
        _drawing_units({"insUnits": 1})
    with pytest.raises(ValueError, match="banana"):
        _drawing_units({"insUnits": "banana"})


def test_api_import_needs_no_checkbox_and_records_units(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path / "data"))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        revision = create_model(api, "Units", example=False)
        url = f"/api/projects/{revision['project']}/drawing"

        # No `units` form field at all: current clients are not asked to confirm.
        unitless = write_dxf(tmp_path / "unitless.dxf", 0)
        response = api.post(
            url,
            data={"base": revision["id"]},
            files={"file": ("unitless.dxf", unitless.read_bytes())},
        )
        assert response.status_code == 202, response.text
        run_worker("units")
        imported = api.get(f"/api/jobs/{response.json()['id']}/imported").json()
        assert imported["setup"]["source"]["unit_basis"] == "unitless_as_mm"
        assert (
            imported["setup"]["source"]["drawing_units"]
            == "unitless drawing interpreted as mm"
        )

        # Declared millimetres import directly.
        mm_dxf = write_dxf(tmp_path / "mm.dxf", 4)
        response = api.post(
            url,
            data={"base": imported["id"]},
            files={"file": ("mm.dxf", mm_dxf.read_bytes())},
        )
        assert response.status_code == 202, response.text
        run_worker("units")
        declared = api.get(f"/api/jobs/{response.json()['id']}/imported").json()
        assert declared["setup"]["source"]["unit_basis"] == "declared_mm"

        # A drawing in inches is refused by name and never replaces the model.
        inches = write_dxf(tmp_path / "inches.dxf", 1)
        response = api.post(
            url,
            data={"base": declared["id"]},
            files={"file": ("inches.dxf", inches.read_bytes())},
        )
        assert response.is_success, response.text
        run_worker("units")
        job = store.job(response.json()["id"])
        assert job["status"] == "Failed"
        assert "inches" in job["diagnostic"]
        assert api.get(f"/api/revisions/{declared['id']}").is_success

        # A corrupt file fails as a job and leaves the saved drawing intact.
        broken = api.post(
            url,
            data={"base": declared["id"]},
            files={"file": ("broken.dxf", b"not a dxf")},
        )
        assert broken.is_success, broken.text
        run_worker("units")
        assert store.job(broken.json()["id"])["status"] == "Failed"
        assert (
            api.get(f"/api/revisions/{declared['id']}").json()["setup"]["source"]["filename"]
            == "mm.dxf"
        )

