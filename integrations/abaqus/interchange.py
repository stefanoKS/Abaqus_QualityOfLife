"""Result format v1. Standard library only; also imported by Abaqus Python."""

from bisect import bisect_left
import csv
import json
import os
from pathlib import Path

DEMO_NOTICE = "DEMO — synthetic results, not an Abaqus analysis."


def write_json(path, data):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), allow_nan=False)
    os.replace(temp, path)


def _sample(series, times, t):
    index = bisect_left(times, t)
    if times[index] == t:
        return series[t]
    a, b = times[index - 1], times[index]
    return series[a] + (t - a) * (series[b] - series[a]) / (b - a)


def align_histories(displacements, reactions, metadata, start_time=0):
    """Piecewise linear interpolation only over the two histories' common time domain."""
    u, rf = dict(displacements), dict(reactions)
    if not u or not rf:
        return []
    tu, tr = sorted(u), sorted(rf)
    lower, upper = max(tu[0], tr[0]), min(tu[-1], tr[-1])
    divisor = metadata["thickness"] if metadata["force_normalization"] == "per_mm" else 1.0
    values = []
    for t in sorted(set(tu) | set(tr)):
        if lower <= t <= upper:
            total = _sample(rf, tr, t)
            values.append(
                {
                    "time": start_time + t,
                    "displacement": _sample(u, tu, t),
                    "force": total / divisor,
                    "total_force_N": total,
                }
            )
    return values


def result_header(metadata, mode, instances):
    per_length = metadata["force_normalization"] == "per_mm"
    return {
        "version": 1,
        "mode": mode,
        "notice": DEMO_NOTICE if mode == "DEMO" else "ABAQUS",
        "units": metadata["units"],
        "dimension": metadata["dimension"],
        "placement": metadata["placement"],
        "sets": metadata["sets"],
        "thickness": metadata["thickness"],
        "force_normalization": metadata["force_normalization"],
        "force_unit": "N/mm" if per_length else "N",
        "history_description": "Panel reference point U2 and signed RF2, aligned by time within overlap",
        "field_locations": {"U": "NODAL", "RF": "NODAL"},
        "averaging": "ODB field values retain their stored output position without spatial averaging.",
        "instances": instances,
        "frames": [],
        "history": [],
        "unavailable": [],
    }


def save_frame(directory, result, frame):
    filename = f"frame-{len(result['frames']):05d}.json"
    frame.update({"version": 1, "mode": result["mode"], "notice": result["notice"]})
    write_json(Path(directory) / filename, frame)
    result["frames"].append({"time": frame["time"], "step": frame["step"], "file": filename})


def finish(directory, result):
    if not result["frames"]:
        raise ValueError("The ODB contains no extractable result frames.")
    directory = Path(directory)
    path = directory / "history.csv"
    tmp = directory / "history.csv.tmp"
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "execution",
                "time_s",
                "panel_U2_mm",
                "panel_RF2_" + result["force_unit"],
                "panel_total_RF2_N",
            ]
        )
        for row in result["history"]:
            writer.writerow(
                [
                    result["notice"],
                    row["time"],
                    row["displacement"],
                    row["force"],
                    row["total_force_N"],
                ]
            )
    os.replace(tmp, path)
    # Publish the index only after every listed frame and history has reached disk.
    write_json(directory / "results.json", result)
