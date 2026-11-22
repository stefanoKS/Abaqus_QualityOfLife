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


COMPONENTS = ("U1", "U2", "RF1", "RF2")


def align_histories(series, metadata, start_time=0, step=None):
    """Align every component on the two closing histories' common time domain.

    ``series`` maps ``U1``/``U2``/``RF1``/``RF2`` to ``{time: value}``. Rows keep
    the raw signed global components and add the door response projected along
    the configured closing direction, measured from the start of this step.
    Projecting a reaction whose raw sign opposes the travel (a resisting seal)
    yields a positive closing-force curve; see docs/engineering-validation.md.
    """
    series = {name: dict(values) for name, values in series.items() if values}
    u, rf = series.get("U2"), series.get("RF2")
    if not u or not rf:
        return []
    tu, tr = sorted(u), sorted(rf)
    lower, upper = max(tu[0], tr[0]), min(tu[-1], tr[-1])
    if upper < lower:
        return []
    divisor = metadata["thickness"] if metadata["force_normalization"] == "per_mm" else 1.0
    closing = metadata.get("closing") or {}
    direction = closing.get("direction") or [0.0, -1.0]
    dx, dy = float(direction[0]), float(direction[1])
    # Only the components the direction actually uses must exist; an X-only
    # direction must not depend on U2/RF2 being present.
    required = [
        name
        for name, weight in (("U1", dx), ("U2", dy), ("RF1", dx), ("RF2", dy))
        if weight
    ]
    if not required or any(name not in series for name in required):
        return []
    ordered = {name: sorted(values) for name, values in series.items()}
    origin = {
        name: (series[name][points[0]] if points else 0.0) for name, points in ordered.items()
    }
    times = sorted({t for values in ordered.values() for t in values if lower <= t <= upper})
    rows = []
    for t in times:
        values = {}
        for name in COMPONENTS:
            points = ordered.get(name)
            if not points:
                values[name] = 0.0
                continue
            if not (points[0] <= t <= points[-1]):
                values = None
                break
            values[name] = _sample(series[name], points, t)
        if values is None:
            continue
        total = values["RF1"] * dx + values["RF2"] * dy
        # Travel is measured from this step's first sample so a later closing
        # step reports closing displacement, not cumulative assembly travel.
        travel = (values["U1"] - origin.get("U1", 0.0)) * dx + (
            values["U2"] - origin.get("U2", 0.0)
        ) * dy
        rows.append(
            {
                "time": start_time + t,
                "step": step,
                "displacement": travel,
                "force": total / divisor,
                "total_force_N": total,
                "u1": values["U1"],
                "u2": values["U2"],
                "rf1": values["RF1"],
                "rf2": values["RF2"],
            }
        )
    return rows


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
        "closing": metadata.get("closing"),
        "fixture": metadata.get("fixture"),
        "history_components": list(COMPONENTS),
        "history_description": (
            "Door reference point U1/U2/RF1/RF2 aligned by time within each step; "
            "the chart projects reaction and travel onto the closing direction."
        ),
        "field_locations": {"U": "NODAL", "RF": "NODAL"},
        "averaging": "ODB field values retain their stored output position without spatial averaging.",
        "instances": instances,
        "frames": [],
        "history": [],
        "unavailable": [],
    }


def display_metadata(directory, result):
    """Run-wide camera bounds and per-component colour ranges.

    Computed once from the stored frames so playback never rescales the legend
    or refits the camera per frame, and never needs the whole history in the
    browser. The values are display metadata; the recorded fields are untouched.
    """
    directory = Path(directory)
    undeformed = [float("inf"), float("-inf")] * 3
    deformed = [float("inf"), float("-inf")] * 3
    ranges = {name: 0.0 for name in ("magnitude", "U1", "U2", "U3")}
    present = set()
    for entry in result["frames"]:
        frame = json.loads((directory / entry["file"]).read_text(encoding="utf-8"))
        displacements = frame.get("displacements") or {}
        for instance in result["instances"]:
            rows = displacements.get(instance["name"]) or []
            by_label = {row[0]: row for row in rows}
            for node in instance["nodes"]:
                label, x, y, z = node[0], node[1], node[2], node[3]
                for axis, value in enumerate((x, y, z)):
                    undeformed[2 * axis] = min(undeformed[2 * axis], value)
                    undeformed[2 * axis + 1] = max(undeformed[2 * axis + 1], value)
                row = by_label.get(label)
                if not row:
                    continue
                u = (row[1] if len(row) > 1 else 0.0, row[2] if len(row) > 2 else 0.0,
                     row[3] if len(row) > 3 else 0.0)
                present.update(("U1", "U2", "magnitude"))
                if len(row) > 3:
                    present.add("U3")
                for axis, value in enumerate((x + u[0], y + u[1], z + u[2])):
                    deformed[2 * axis] = min(deformed[2 * axis], value)
                    deformed[2 * axis + 1] = max(deformed[2 * axis + 1], value)
                for name, value in (
                    ("magnitude", (u[0] ** 2 + u[1] ** 2 + u[2] ** 2) ** 0.5),
                    ("U1", abs(u[0])),
                    ("U2", abs(u[1])),
                    ("U3", abs(u[2])),
                ):
                    ranges[name] = max(ranges[name], value)
    finite = lambda box: all(abs(v) != float("inf") for v in box)  # noqa: E731
    undeformed = undeformed if finite(undeformed) else [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    deformed = deformed if finite(deformed) else list(undeformed)
    extent = [
        min(undeformed[i], deformed[i]) if i % 2 == 0 else max(undeformed[i], deformed[i])
        for i in range(6)
    ]
    return {
        "version": 1,
        "bounds": {"undeformed": undeformed, "deformed": deformed, "extent": extent},
        "ranges": {name: value for name, value in ranges.items() if name in present},
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
                "step",
                "time_s",
                "panel_U1_mm",
                "panel_U2_mm",
                "panel_RF1_N",
                "panel_RF2_N",
                "panel_total_RF2_N",
                "closing_displacement_mm",
                "closing_force_" + result["force_unit"],
                "closing_total_force_N",
            ]
        )
        for row in result["history"]:
            signed = row.get("rf2", 0.0)
            writer.writerow(
                [
                    result["notice"],
                    row.get("step") or "",
                    row["time"],
                    row.get("u1", 0.0),
                    row.get("u2", row["displacement"]),
                    row.get("rf1", 0.0),
                    signed,
                    # Signed global RF2 and its projection are distinct: the old
                    # writer put the projected total in this column.
                    signed,
                    row["displacement"],
                    row["force"],
                    row["total_force_N"],
                ]
            )
    os.replace(tmp, path)
    # A single bounded pass over the stored frames records the run-wide camera
    # bounds and colour ranges before the index is published.
    result["display"] = display_metadata(directory, result)
    # Publish the index only after every listed frame and history has reached disk.
    write_json(directory / "results.json", result)
