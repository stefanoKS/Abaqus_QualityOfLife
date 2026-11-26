"""Write manufactured ``.aqresult`` fixtures for browser acceptance.

Everything in these files is synthetic and labelled as manufactured test
evidence. No solver, license or ODB is used. They exercise display behaviour
(arrow geometry, result multiplier, gaps and partial opening) only.
"""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.engineering import portable, synthetic

NOTICE = "MANUFACTURED TEST EVIDENCE - not an Abaqus analysis."


def _base_index(availability="complete", solver="Succeeded"):
    return {
        "version": 1,
        "mode": "ABAQUS",
        "notice": NOTICE,
        "manufactured": True,
        "units": "N-mm-s-tonne",
        "dimension": "2D",
        "force_unit": "N",
        "force_normalization": "total",
        "force_basis": "legacy_unscaled",
        "thickness": 1.0,
        "thickness_mm": 1.0,
        "reporting_width_mm": 100.0,
        "reporting_width_basis": "legacy_thickness",
        "availability": availability,
        "solver_outcome": solver,
        "failure_reason": "Manufactured solver failure" if solver != "Succeeded" else "",
        "history_only": False,
        "initial_only": False,
        "closing": {
            "panel": "panel",
            "panel_name": "PANEL",
            "instance": "PANEL-1",
            "reference_label": 999,
            "direction": [0.0, -1.0],
            "distance_mm": 2.0,
            "angle_deg": -90.0,
            "measure_from_step_start": True,
        },
        "steps": [
            {
                "name": "Closing",
                "id": "closing",
                "role": "door",
                "instance": "PANEL-1",
                "reference_label": 999,
                "direction": [0.0, -1.0],
                "angle_deg": -90.0,
                "duration_s": 1.0,
            }
        ],
        "instances": [
            {
                "name": "PANEL-1",
                "nodes": [
                    [1, 2.0, 3.0, 0.0],
                    [2, 6.0, 3.0, 0.0],
                    [999, 0.0, 0.0, 0.0],
                ],
                "elements": [
                    {
                        "label": 1,
                        "type": "R2D2",
                        "connectivity": [1, 999],
                        "region": "e10",
                    },
                    {
                        "label": 2,
                        "type": "R2D2",
                        "connectivity": [2, 999],
                        "region": "e10",
                    },
                ],
            }
        ],
        "unavailable": [],
    }


def _profile(stations, pressures, labels, points):
    return {
        "enabled": True,
        "profiles": [
            {
                "id": "profile-1",
                "instance": "PANEL-1",
                "component": "panel",
                "alias": "PANEL",
                "origin_node": labels[0] if labels else 1,
                "labels": labels,
                "stations_mm": stations,
                "points_mm": points,
                "length_mm": 0.0,
                "topology": "open_chain",
                "supported": True,
                "maximum_pressure_kpa": max(pressures) if pressures else 0.0,
            }
        ],
        "instances": [{"instance": "PANEL-1", "component": "panel", "alias": "PANEL"}],
        "native_unit": "MPa",
        "display_unit": "kPa",
        "conversion": 1000.0,
        "force_unit": "N",
        "field_location": "NODAL",
        "fields": {"pressure": ["CPRESS"], "force": ["CNORMF"]},
        "unavailable": [],
    }


def _frame(index, pressure, force, mises, displacements=None):
    return {
        "version": 1,
        "mode": "ABAQUS",
        "notice": NOTICE,
        "time": 0.0,
        "step": "Closing",
        "step_id": "closing",
        "odb_step": "Closing",
        "step_ordinal": 0,
        "step_frame_ordinal": 0,
        "frame_ordinal": 0,
        "native_frame_id": 1,
        "increment": 1,
        "local_time": 0.0,
        "total_time": 0.0,
        "displacements": displacements
        or {
            "PANEL-1": [
                [1, 0.0, 0.0, 0.0],
                [2, 0.0, 0.0, 0.0],
                [999, 0.0, 0.0, 0.0],
            ]
        },
        "fields": {
            "Mises": {
                "components": ["Mises"],
                "type": "SCALAR",
                "averaging": "as_stored",
                "values": [
                    {
                        "instance": "PANEL-1",
                        "position": "ELEMENT_NODAL",
                        "element": 1,
                        "node": 1,
                        "data": [mises / 2],
                    },
                    {
                        "instance": "PANEL-1",
                        "position": "ELEMENT_NODAL",
                        "element": 2,
                        "node": 2,
                        "data": [mises],
                    },
                ],
            },
            "CNORMF": {
                "components": ["CNORMF1", "CNORMF2"],
                "type": "VECTOR",
                "averaging": "as_stored",
                "values": [
                    {
                        "instance": "PANEL-1",
                        "position": "NODAL",
                        "node": 1,
                        "data": list(force),
                    }
                ],
            },
        },
        "unavailable": [],
        "door_pressure": {
            "profiles": {
                "profile-1": {
                    "supported": True,
                    "labels": [1],
                    "pressure_mpa": [pressure / 1000.0],
                    "pressure_kpa": [pressure],
                    "cnormf_n": [force],
                    "force_magnitude_n": [
                        (force[0] ** 2 + force[1] ** 2) ** 0.5 if force else None
                    ],
                    "ambiguous": [],
                    "availability": {"pressure": "reported", "force": "reported"},
                }
            },
            "pressure_domain": "CPRESS",
            "force_domain": "CNORMF",
            "domains": {"pressure": ["CPRESS"], "force": ["CNORMF"]},
            "unavailable": [],
        },
    }


def _display(pressure=10.0, mises=0.2, cnormf=5.0):
    return {
        "version": 1,
        "bounds": {
            "undeformed": [0.0, 10.0, 0.0, 10.0, 0.0, 0.0],
            "deformed": [0.0, 10.0, 0.0, 10.0, 0.0, 0.0],
            "extent": [0.0, 10.0, 0.0, 10.0, 0.0, 0.0],
        },
        "ranges": {
            "magnitude": 0.0,
            "U1": 0.0,
            "U2": 0.0,
            "mises": mises,
            "pressure": pressure,
            "CNormf": cnormf,
        },
    }


def write_arrows(folder: Path):
    index = _base_index()
    index["door_pressure"] = _profile([0.0], [10.0], [1], [[2.0, 3.0]])
    index["frames"] = [
        {"time": 0.0, "step": "Closing", "step_id": "closing", "file": "frame-00000.json"},
        {"time": 0.5, "step": "Closing", "step_id": "closing", "file": "frame-00001.json"},
    ]
    index["history"] = [
        {
            "time": 0.0,
            "step": "Closing",
            "step_id": "closing",
            "displacement": 0.0,
            "force": 8.0,
            "total_force_N": 8.0,
            "u1": 0.0,
            "u2": 0.0,
            "rf1": 0.0,
            "rf2": -8.0,
        },
        {
            "time": 0.5,
            "step": "Closing",
            "step_id": "closing",
            "displacement": 1.0,
            "force": 12.0,
            "total_force_N": 12.0,
            "u1": 0.0,
            "u2": -1.0,
            "rf1": 0.0,
            "rf2": -12.0,
        },
    ]
    index["display"] = _display()
    frame = _frame(index, 10.0, [3.0, 4.0], 0.2)
    second = _frame(index, 10.0, [3.0, 4.0], 0.2)
    second.update(
        {
            "time": 0.5,
            "total_time": 0.5,
            "local_time": 0.5,
            "frame_ordinal": 1,
            "step_frame_ordinal": 1,
            "native_frame_id": 2,
            "increment": 2,
        }
    )
    return _publish(
        folder,
        "arrows",
        index,
        {"frame-00000.json": frame, "frame-00001.json": second},
    )


def write_permuted(folder: Path):
    """Gate 6: a clean label permutation with different payload per node.

    The profile axis is [1, 2] at [0, 3] mm. The frame stores native samples in
    the order [2, 1] with pressures [10, 0] kPa and CNORMF [(3,4), (0,0)] N, so
    positional consumption would attach node 2's measurements to node 1.
    """
    index = _base_index()
    index["door_pressure"] = _profile(
        [0.0, 3.0],
        [10.0, 0.0],
        [1, 2],
        [[2.0, 0.0], [2.0, 3.0]],
    )
    index["door_pressure"]["profiles"][0]["maximum_pressure_kpa"] = 10.0
    index["frames"] = [
        {"time": 0.0, "step": "Closing", "step_id": "closing", "file": "frame-00000.json"}
    ]
    index["history"] = [
        {
            "time": 0.0,
            "step": "Closing",
            "step_id": "closing",
            "displacement": 0.0,
            "force": 5.0,
            "total_force_N": 5.0,
            "u1": 0.0,
            "u2": 0.0,
            "rf1": 0.0,
            "rf2": -5.0,
        }
    ]
    index["display"] = _display()
    frame = _frame(index, 0.0, [0.0, 0.0], 0.0)
    frame["fields"]["CNORMF"]["values"] = [
        {
            "instance": "PANEL-1",
            "position": "NODAL",
            "node": 2,
            "data": [3.0, 4.0],
        },
        {
            "instance": "PANEL-1",
            "position": "NODAL",
            "node": 1,
            "data": [0.0, 0.0],
        },
    ]
    frame["door_pressure"]["profiles"]["profile-1"] = {
        "instance": "PANEL-1",
        "supported": True,
        # Native sample order, deliberately the reverse of the station order.
        "labels": [2, 1],
        "pressure_mpa": [0.01, 0.0],
        "pressure_kpa": [10.0, 0.0],
        "cnormf_n": [[3.0, 4.0], [0.0, 0.0]],
        "force_magnitude_n": [5.0, 0.0],
        "ambiguous": [],
        "availability": {"pressure": "reported", "force": "reported"},
    }
    return _publish(folder, "permuted", index, {"frame-00000.json": frame})


def write_history_only(folder: Path):
    """Measured history with no usable field frame: the CLD curve must still open."""
    index = _base_index(availability="partial", solver="Succeeded")
    index["history_only"] = True
    index["frames"] = []
    index["door_pressure"] = {"enabled": False}
    index["history"] = [
        {
            "time": 0.0,
            "step": "Closing",
            "step_id": "closing",
            "displacement": 0.0,
            "force": 0.0,
            "total_force_N": 0.0,
            "u1": 0.0,
            "u2": 0.0,
            "rf1": 0.0,
            "rf2": 0.0,
        },
        {
            "time": 1.0,
            "step": "Closing",
            "step_id": "closing",
            "displacement": 1.0,
            "force": 9.0,
            "total_force_N": 9.0,
            "u1": 0.0,
            "u2": -1.0,
            "rf1": 0.0,
            "rf2": -9.0,
        },
    ]
    index["last_step"] = "Closing"
    index["last_step_id"] = "closing"
    index["last_total_s"] = 1.0
    index["display"] = _display()
    return _publish(folder, "history-only", index, {})


def write_gaps(folder: Path):
    index = _base_index()
    # A shortened station axis against three labels: spatial plotting/export
    # must be disabled with a reason instead of inventing station zero.
    index["door_pressure"] = _profile([], [10.0, 20.0, 30.0], [1, 2, 3], [[1.0, 0.0], [2.0, 0.0], [3.0, 0.0]])
    index["door_pressure"]["profiles"][0]["stations_mm"] = []
    index["frames"] = [{"time": 0.0, "step": "Closing", "step_id": "closing", "file": "frame-00000.json"}]
    # Acquisition rows: 0, an unlocated 123, then 2. A 1 mm grid must produce
    # [0, blank, 40]; the middle row keeps its blank stroke in original mode.
    index["history"] = [
        {
            "time": 0.0,
            "step": "Closing",
            "step_id": "closing",
            "displacement": 0.0,
            "force": 0.0,
            "total_force_N": 0.0,
            "u1": 0.0,
            "u2": 0.0,
            "rf1": 0.0,
            "rf2": 0.0,
        },
        {
            "time": 0.5,
            "step": "Closing",
            "step_id": "closing",
            "displacement": None,
            "force": 123.0,
            "total_force_N": 123.0,
            "u1": None,
            "u2": None,
            "rf1": 0.0,
            "rf2": -123.0,
        },
        {
            "time": 1.0,
            "step": "Closing",
            "step_id": "closing",
            "displacement": 2.0,
            "force": 40.0,
            "total_force_N": 40.0,
            "u1": 2.0,
            "u2": 0.0,
            "rf1": 0.0,
            "rf2": -40.0,
        },
    ]
    index["display"] = _display()
    frame = _frame(index, 30.0, [3.0, 4.0], 0.2)
    return _publish(folder, "gaps", index, {"frame-00000.json": frame})


def write_partial(folder: Path):
    index = _base_index(availability="partial", solver="Failed")
    index["failure_reason"] = "Manufactured solver failure after accepted increments"
    index["door_pressure"] = _profile([0.0], [10.0], [1], [[2.0, 3.0]])
    index["frames"] = [
        {"time": 0.2, "step": "Closing", "step_id": "closing", "file": "frame-00000.json", "frame_ordinal": 0},
        {"time": 0.4, "step": "Closing", "step_id": "closing", "file": "frame-00001.json", "frame_ordinal": 1},
        {"time": 0.6, "step": "Closing", "step_id": "closing", "file": "frame-00002.json", "frame_ordinal": 2},
    ]
    index["history"] = [
        {
            "time": 0.0,
            "step": "Closing",
            "step_id": "closing",
            "displacement": 0.0,
            "force": 0.0,
            "total_force_N": 0.0,
            "u1": 0.0,
            "u2": 0.0,
            "rf1": 0.0,
            "rf2": 0.0,
        },
        {
            "time": 0.6,
            "step": "Closing",
            "step_id": "closing",
            "displacement": 0.6,
            "force": 4.8,
            "total_force_N": 4.8,
            "u1": 0.0,
            "u2": -0.6,
            "rf1": 0.0,
            "rf2": -4.8,
        },
    ]
    index["display"] = _display()
    index["last_frame_ordinal"] = 2
    index["last_native_frame_id"] = 3
    index["last_increment"] = 3
    index["last_step"] = "Closing"
    index["last_step_id"] = "closing"
    index["last_local_s"] = 0.6
    index["last_total_s"] = 0.6
    frames = {}
    for ordinal, time in enumerate((0.2, 0.4, 0.6)):
        frame = _frame(index, 10.0, [3.0, 4.0], 0.2)
        frame["time"] = time
        frame["local_time"] = time
        frame["total_time"] = time
        frame["frame_ordinal"] = ordinal
        frame["native_frame_id"] = ordinal + 1
        frame["increment"] = ordinal + 1
        frames[f"frame-{ordinal:05d}.json"] = frame
    return _publish(folder, "partial", index, frames)


def write_partial_body(folder: Path):
    """A two-step failure before any Closing frame, for curve selection."""
    index = _base_index(availability="partial", solver="Failed")
    index["steps"] = [
        {
            "name": "Body seating",
            "id": "bodyseating",
            "role": "body",
            "instance": "BODY-1",
            "reference_label": 998,
            "direction": [0.0, 1.0],
            "angle_deg": 90.0,
            "duration_s": 1.0,
        },
        {
            "name": "Closing",
            "id": "closing",
            "role": "door",
            "instance": "PANEL-1",
            "reference_label": 999,
            "direction": [0.0, -1.0],
            "angle_deg": -90.0,
            "duration_s": 1.3,
        },
    ]
    index["body"] = {
        "panel": "body",
        "panel_name": "BODY",
        "instance": "BODY-1",
        "reference_label": 998,
        "direction": [0.0, 1.0],
        "angle_deg": 90.0,
        "measure_from_step_start": True,
    }
    index["door_pressure"] = _profile([0.0], [0.0], [1], [[2.0, 3.0]])
    index["frames"] = [
        {
            "time": 0.6,
            "step": "Body seating",
            "step_id": "bodyseating",
            "file": "frame-00000.json",
            "frame_ordinal": 0,
        }
    ]
    index["history"] = [
        {
            "time": 0.0,
            "step": "Body seating",
            "step_id": "bodyseating",
            "displacement": 0.0,
            "force": 0.0,
            "total_force_N": 0.0,
            "u1": 0.0,
            "u2": 0.0,
            "rf1": 0.0,
            "rf2": 0.0,
        },
        {
            "time": 0.6,
            "step": "Body seating",
            "step_id": "bodyseating",
            "displacement": 0.6,
            "force": 4.8,
            "total_force_N": 4.8,
            "u1": 0.0,
            "u2": 0.6,
            "rf1": 0.0,
            "rf2": 4.8,
        },
    ]
    index["display"] = _display(pressure=0.0)
    index["last_frame_ordinal"] = 0
    index["last_native_frame_id"] = 1
    index["last_increment"] = 1
    index["last_step"] = "Body seating"
    index["last_step_id"] = "bodyseating"
    index["last_local_s"] = 0.6
    index["last_total_s"] = 0.6
    index["failure_reason"] = "Manufactured failure during Body seating"
    frame = _frame(index, 0.0, [0.0, 0.0], 0.2)
    frame["step"] = "Body seating"
    frame["step_id"] = "bodyseating"
    frame["time"] = 0.6
    frame["local_time"] = 0.6
    frame["total_time"] = 0.6
    return _publish(folder, "partial-body", index, {"frame-00000.json": frame})


def _publish(folder: Path, stem: str, index: dict, frames: dict[str, dict]):
    setup = synthetic().model_dump(mode="json")
    provenance = {
        "job": {
            "id": "manufactured-" + stem,
            "name": "Manufactured " + stem,
            "mode": "ABAQUS",
            "solver": index.get("solver_outcome"),
            "extraction": "Succeeded",
        },
        "result": {
            "availability": index["availability"],
            "solver_outcome": index.get("solver_outcome"),
            "failure_reason": index.get("failure_reason"),
            "last_step": index.get("last_step"),
            "last_local_s": index.get("last_local_s"),
            "frames": len(frames),
        },
    }
    members = portable.result_container(
        setup,
        index,
        b"",
        {name: json.dumps(frame).encode("utf-8") for name, frame in frames.items()},
        provenance,
    )
    target = folder / (stem + ".aqresult")
    portable.write_container(
        target,
        portable.RESULT_KIND,
        members,
        {"name": "Manufactured " + stem, "job": provenance["job"]["id"]},
    )
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True)
    args = parser.parse_args()
    folder = Path(args.folder)
    folder.mkdir(parents=True, exist_ok=True)
    for writer in (write_arrows, write_gaps, write_permuted, write_history_only, write_partial, write_partial_body):
        print(writer(folder))


if __name__ == "__main__":
    main()
