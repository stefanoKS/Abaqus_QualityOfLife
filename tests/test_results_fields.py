"""Field semantics: Mises, missing measurements and canonical step identity."""

import csv
import json
from pathlib import Path

import pytest

from integrations.abaqus import interchange


PLANE = ["S11", "S22", "S33", "S12"]


def test_mises_zero_uniaxial_equibiaxial_and_pure_shear():
    assert interchange.mises_from_components(PLANE, [0, 0, 0, 0]) == pytest.approx(0.0)
    assert interchange.mises_from_components(PLANE, [100, 0, 0, 0]) == pytest.approx(100.0)
    assert interchange.mises_from_components(PLANE, [100, 100, 0, 0]) == pytest.approx(100.0)
    assert interchange.mises_from_components(PLANE, [0, 0, 0, 50]) == pytest.approx(
        3**0.5 * 50
    )
    # Component order comes from the stored labels, not the array position.
    reordered = ["S12", "S33", "S22", "S11"]
    assert interchange.mises_from_components(reordered, [50, 0, 0, 0]) == pytest.approx(
        3**0.5 * 50
    )
    assert interchange.mises_from_components(["UNKNOWN"], [1.0]) is None


def test_missing_components_are_preserved_not_zeroed():
    metadata = {"thickness": 1.0, "force_normalization": "total"}
    rows = interchange.align_histories(
        {"U2": {0.0: 0.0, 1.0: -5.0}, "RF2": {0.0: 0.0, 1.0: -2.0}},
        metadata,
        step="Closing",
        step_id="closing",
        motion={"role": "door", "direction": [0.0, -1.0]},
    )
    last = rows[-1]
    assert last["u1"] is None and last["rf1"] is None
    assert last["u2"] == pytest.approx(-5.0)
    assert last["rf2"] == pytest.approx(-2.0)
    # The vertical projection stays available without its lateral components.
    assert last["displacement"] == pytest.approx(5.0)
    assert last["force"] == pytest.approx(2.0)
    assert last["step_id"] == "closing"


def test_measured_zero_is_numeric_zero_not_missing():
    rows = interchange.align_histories(
        {
            "U1": {0.0: 0.0, 1.0: 0.0},
            "U2": {0.0: 0.0, 1.0: 0.0},
            "RF1": {0.0: 0.0, 1.0: 0.0},
            "RF2": {0.0: 0.0, 1.0: 0.0},
        },
        {"thickness": 1.0, "force_normalization": "total"},
        step="Closing",
        motion={"role": "door", "direction": [0.0, -1.0]},
    )
    assert rows[-1]["u1"] == 0.0
    assert rows[-1]["rf2"] == 0.0
    assert rows[-1]["force"] == 0.0


def test_x_only_projection_does_not_require_u2():
    rows = interchange.align_histories(
        {"U1": {0.0: 0.0, 1.0: 4.0}, "RF1": {0.0: 0.0, 1.0: -8.0}},
        {"thickness": 1.0, "force_normalization": "total"},
        step="Closing",
        motion={"role": "door", "direction": [1.0, 0.0]},
    )
    assert rows[-1]["displacement"] == pytest.approx(4.0)
    assert rows[-1]["force"] == pytest.approx(-8.0)
    assert rows[-1]["u2"] is None


def test_missing_required_component_has_no_projection():
    rows = interchange.align_histories(
        {"U2": {0.0: 0.0, 1.0: -5.0}},
        {"thickness": 1.0, "force_normalization": "total"},
        step="Closing",
        motion={"role": "door", "direction": [0.0, -1.0]},
    )
    assert rows == []


def test_canonical_step_identity_is_case_and_space_insensitive():
    assert (
        interchange.canonical_step("Body seating")
        == interchange.canonical_step("BODY SEATING")
        == interchange.canonical_step("Bodyseating")
        == "bodyseating"
    )
    assert interchange.canonical_step("  Closing ") == "closing"


def _result(directory: Path, history):
    (directory / "frame-00000.json").write_text(
        json.dumps(
            {
                "time": 0.0,
                "step": "Closing",
                "step_id": "closing",
                "displacements": {"WS-1": [[1, 0, 0, 0]]},
                "fields": {},
                "unavailable": [],
            }
        ),
        encoding="utf-8",
    )
    return {
        "version": 1,
        "mode": "ABAQUS",
        "notice": "ABAQUS",
        "units": "N-mm-s-tonne",
        "dimension": "2D",
        "thickness": 1.0,
        "force_normalization": "total",
        "force_unit": "N",
        "steps": [{"name": "Closing", "id": "closing", "role": "door"}],
        "instances": [
            {"name": "WS-1", "nodes": [[1, 0.0, 0.0, 0.0]], "elements": []}
        ],
        "frames": [
            {"time": 0.0, "step": "Closing", "step_id": "closing", "file": "frame-00000.json"}
        ],
        "history": history,
        "unavailable": [],
    }


def test_csv_exports_empty_cells_for_missing_values(tmp_path):
    history = interchange.align_histories(
        {"U2": {0.0: 0.0, 1.0: -5.0}, "RF2": {0.0: 0.0, 1.0: -2.0}},
        {"thickness": 1.0, "force_normalization": "total"},
        step="Closing",
        step_id="closing",
        motion={"role": "door", "direction": [0.0, -1.0]},
    )
    result = _result(tmp_path, history)
    interchange.finish(tmp_path, result)
    with (tmp_path / "history.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    last = rows[-1]
    assert last["step_id"] == "closing"
    assert last["panel_U1_mm"] == ""
    assert last["panel_RF1_N"] == ""
    assert float(last["panel_U2_mm"]) == pytest.approx(-5.0)
    assert float(last["panel_RF2_N"]) == pytest.approx(-2.0)
    assert float(last["closing_displacement_mm"]) == pytest.approx(5.0)


def test_display_metadata_records_run_wide_stress_ranges(tmp_path):
    frame = {
        "time": 0.0,
        "step": "Closing",
        "step_id": "closing",
        "displacements": {"WS-1": [[1, 0, 0, 0]]},
        "fields": {
            "S": {
                "components": PLANE,
                "type": "TENSOR_2D_PLANAR",
                "averaging": "as_stored",
                "values": [
                    {
                        "instance": "WS-1",
                        "position": "INTEGRATION_POINT",
                        "element": 1,
                        "integration_point": 1,
                        "data": [0.2, 0.0, 0.0, 0.0],
                    }
                ],
            }
        },
    }
    (tmp_path / "frame-00000.json").write_text(json.dumps(frame), encoding="utf-8")
    result = {
        "instances": [
            {"name": "WS-1", "nodes": [[1, 0.0, 0.0, 0.0]], "elements": []}
        ],
        "frames": [
            {"time": 0.0, "step": "Closing", "step_id": "closing", "file": "frame-00000.json"}
        ],
    }
    metadata = interchange.display_metadata(tmp_path, result)
    assert metadata["ranges"]["S11"] == pytest.approx(0.2)
    assert metadata["ranges"]["mises"] == pytest.approx(0.2)
