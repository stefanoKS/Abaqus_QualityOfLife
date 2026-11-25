"""Result format v1. Standard library only; also imported by Abaqus Python."""

from bisect import bisect_left
import csv
import json
import os
from pathlib import Path
import shutil

DEMO_NOTICE = "DEMO — synthetic results, not an Abaqus analysis."
STAGING = ".extract-staging"


def reset_staging(directory):
    """Start one extraction attempt in a private staging directory.

    Frames are written there and only moved into the run directory when the
    whole generation validates, so a failed attempt cannot overwrite the last
    usable frames or index.
    """
    path = Path(directory) / STAGING
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def mises_from_components(labels, data):
    """Mises invariant from stored stress components, by their labels.

    Plane stress typically stores S11, S22, S33 and S12; a 3D tensor adds S13
    and S23. Missing shear components are zero, so the formula stays valid for
    the supported formulations. Returns ``None`` when no stress component is
    recognizable.
    """
    index = {str(label).upper(): position for position, label in enumerate(labels)}
    if not ({"S11", "S22"} & set(index)):
        return None
    try:
        s11 = data[index["S11"]] if "S11" in index else 0.0
        s22 = data[index["S22"]] if "S22" in index else 0.0
        s33 = data[index["S33"]] if "S33" in index else 0.0
        s12 = data[index["S12"]] if "S12" in index else 0.0
        s13 = data[index["S13"]] if "S13" in index else 0.0
        s23 = data[index["S23"]] if "S23" in index else 0.0
    except (IndexError, KeyError):
        return None
    value = 0.5 * ((s11 - s22) ** 2 + (s22 - s33) ** 2 + (s33 - s11) ** 2) + 3.0 * (
        s12**2 + s13**2 + s23**2
    )
    return max(0.0, value) ** 0.5


def canonical_step(name):
    """One canonical step identifier; the display name stays untouched.

    Abaqus removes whitespace from ``*Step, name=`` labels (``Body seating`` is
    stored in the ODB as ``Bodyseating``), so case and every whitespace
    character are ignored here. The configured name remains the display name.
    """
    return "".join(str(name or "").split()).casefold()


def align_histories(series, metadata, start_time=0, step=None, motion=None, step_id=None):
    """Align every component on the two closing histories' common time domain.

    ``series`` maps ``U1``/``U2``/``RF1``/``RF2`` to ``{time: value}``. Rows keep
    the raw signed global components and add the door response projected along
    the configured closing direction, measured from the start of this step.
    Projecting a reaction whose raw sign opposes the travel (a resisting seal)
    yields a positive closing-force curve; see docs/engineering-validation.md.

    A component that was never measured is stored as ``None``, never as an
    invented zero; a measured zero stays ``0.0``. A projection still works when
    only its unused lateral component is absent. Rows are skipped when a
    component the projection actually needs is missing.
    """
    series = {name: dict(values) for name, values in series.items() if values}
    thickness = float(metadata.get("thickness_mm", metadata.get("thickness", 1.0)) or 1.0)
    if thickness <= 0:
        thickness = 1.0
    per_length = metadata["force_normalization"] == "per_mm"
    width = float(metadata.get("reporting_width_mm", thickness) or thickness)
    basis = metadata.get("force_basis", "legacy_unscaled")
    if basis == "total_width":
        # (RF . d) * W / t_s, scaled once from the raw measured global reaction.
        scale = 1.0 if per_length else width / thickness
    elif basis == "per_mm":
        scale = 1.0 / thickness
    else:
        # Legacy evidence: preserve its original basis; never imply the new W.
        scale = 1.0 / thickness if per_length else 1.0
    closing = motion or metadata.get("closing") or {}
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
    # The common domain is set by the components the projection uses.
    lower = max(ordered[name][0] for name in required)
    upper = min(ordered[name][-1] for name in required)
    if upper < lower:
        return []
    origin = {
        name: (series[name][points[0]] if points else 0.0) for name, points in ordered.items()
    }
    times = sorted({t for values in ordered.values() for t in values if lower <= t <= upper})
    identifier = step_id or canonical_step(step)
    rows = []
    for t in times:
        values = {}
        usable = True
        for name in COMPONENTS:
            points = ordered.get(name)
            if not points:
                # Absent measurement: preserve the absence.
                values[name] = None
                continue
            if not (points[0] <= t <= points[-1]):
                usable = False
                break
            values[name] = _sample(series[name], points, t)
        if not usable:
            continue
        total = sum(
            (values[name] or 0.0) * weight for name, weight in (("RF1", dx), ("RF2", dy))
        )
        # Travel is measured from this step's first sample so a later closing
        # step reports closing displacement, not cumulative assembly travel.
        travel = sum(
            ((values[name] or 0.0) - origin.get(name, 0.0)) * weight
            for name, weight in (("U1", dx), ("U2", dy))
        )
        rows.append(
            {
                "time": start_time + t,
                "step": step,
                "step_id": identifier,
                "role": closing.get("role"),
                "displacement": travel,
                "force": total * scale,
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
        # Version 1 remains readable by the installed Abaqus-Python extractor;
        # the reporting-width and contact fields are additive.
        "version": 1,
        "mode": mode,
        "notice": DEMO_NOTICE if mode == "DEMO" else "ABAQUS",
        "units": metadata["units"],
        "dimension": metadata["dimension"],
        "placement": metadata["placement"],
        "sets": metadata["sets"],
        "thickness": metadata["thickness"],
        # Solver thickness and the represented reporting width are separate
        # quantities. The deck still solves a plane-stress section of thickness
        # t_s; total displayed force uses W/t_s.
        "thickness_mm": metadata.get("thickness_mm", metadata["thickness"]),
        "reporting_width_mm": metadata.get("reporting_width_mm", 1.0),
        "reporting_width_basis": metadata.get("reporting_width_basis", "legacy_thickness"),
        "force_basis": metadata.get(
            "force_basis", "legacy_unscaled" if metadata.get("schema_version", 3) < 4 else "total_width"
        ),
        "force_normalization": metadata["force_normalization"],
        "force_unit": "N/mm" if per_length else "N",
        "schema_version": metadata.get("schema_version", 3),
        "closing": metadata.get("closing"),
        "steps": metadata.get("steps"),
        "body": metadata.get("body"),
        # Door-panel contact pressure intent and profile metadata. The
        # extractor replaces this with the ODB-derived profile axis and fields.
        "door_pressure": metadata.get("door_pressure"),
        # Measured per-profile clearance, contact side and projection direction.
        "assembly": metadata.get("assembly"),
        "fixture": metadata.get("fixture"),
        "history_components": list(COMPONENTS),
        "history_description": (
            "Door reference point U1/U2/RF1/RF2 aligned by time within each step; "
            "the chart projects reaction and travel onto the closing direction."
        ),
        "field_locations": {
            "U": "NODAL",
            "RF": "NODAL",
            "CPRESS": "NODAL",
            "CNORMF": "NODAL",
        },
        "averaging": "ODB field values retain their stored output position without spatial averaging.",
        "instances": instances,
        "frames": [],
        "history": [],
        "unavailable": [],
        # Solver outcome, extraction outcome and availability stay separate. A
        # failed solver can still publish a partial, validated generation.
        "availability": "complete",
        "solver_outcome": metadata.get("solver_outcome"),
        "failure_reason": metadata.get("failure_reason") or "",
        "history_only": False,
        "initial_only": False,
        "skipped_frames": [],
        "gaps": [],
    }


def display_metadata(directory, result, base=None):
    """Run-wide camera bounds and per-component colour ranges.

    Computed once from the stored frames so playback never rescales the legend
    or refits the camera per frame, and never needs the whole history in the
    browser. The values are display metadata; the recorded fields are untouched.
    ``base`` is the staging directory while an attempt is being validated.
    """
    directory = Path(directory)
    base = Path(base) if base is not None else directory
    undeformed = [float("inf"), float("-inf")] * 3
    deformed = [float("inf"), float("-inf")] * 3
    ranges = {
        name: 0.0
        for name in ("magnitude", "U1", "U2", "U3", "mises", "S11", "S22", "S33", "S12")
    }
    present = set()
    for entry in result["frames"]:
        frame = json.loads((base / entry["file"]).read_text(encoding="utf-8"))
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
        # Stress ranges are run-wide so the colour scale never jumps during
        # playback. Mises is preferred from the extractor; historical tensors
        # fall back to the component-label-aware invariant.
        fields = frame.get("fields") or {}
        mises_field = fields.get("Mises")
        if mises_field:
            for value in mises_field.get("values") or []:
                data = value.get("data") or []
                if data:
                    ranges["mises"] = max(ranges["mises"], abs(float(data[0])))
                    present.add("mises")
        stress = fields.get("S")
        if stress:
            labels = stress.get("components") or []
            index = {str(label).upper(): position for position, label in enumerate(labels)}
            for value in stress.get("values") or []:
                data = value.get("data") or []
                for name in ("S11", "S22", "S33", "S12"):
                    if name in index and index[name] < len(data):
                        ranges[name] = max(ranges[name], abs(float(data[index[name]])))
                        present.add(name)
                if not mises_field:
                    derived = mises_from_components(labels, data)
                    if derived is not None:
                        ranges["mises"] = max(ranges["mises"], derived)
                        present.add("mises")
        # Contact normal force is displayed as a nodal magnitude while its signed
        # stored components stay available to the probe.
        for name, field in fields.items():
            if name.split()[0].upper() != "CNORMF":
                continue
            for value in field.get("values") or []:
                data = value.get("data") or []
                if data:
                    ranges["CNormf"] = max(
                        ranges.get("CNormf", 0.0),
                        (sum(float(component) ** 2 for component in data)) ** 0.5,
                    )
                    present.add("CNormf")
        # Door-panel pressure is stored in the frame in display kPa. The run-wide
        # maximum sets one arrow scale and one graph bound across every frame.
        door = frame.get("door_pressure") or {}
        has_pressure = False
        for profile in (door.get("profiles") or {}).values():
            for value in profile.get("pressure_kpa") or []:
                if value is None:
                    continue
                has_pressure = True
                ranges["pressure"] = max(ranges.get("pressure", 0.0), abs(float(value)))
        if has_pressure:
            present.add("pressure")
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
    """Stage one readable frame and record its step/frame identity.

    ``frame_ordinal`` walks every record the reader visited; ``step_ordinal`` is
    its position inside the ODB step. A duplicate recovery frame or an equal-time
    step boundary therefore keeps its own identity instead of collapsing on time.
    """
    filename = f"frame-{len(result['frames']):05d}.json"
    frame.update({"version": 1, "mode": result["mode"], "notice": result["notice"]})
    write_json(Path(directory) / STAGING / filename, frame)
    entry = {
        "time": frame["time"],
        "step": frame["step"],
        "step_id": frame.get("step_id") or canonical_step(frame["step"]),
        "file": filename,
    }
    for key in (
        "odb_step",
        "step_ordinal",
        "step_frame_ordinal",
        "frame_ordinal",
        "native_frame_id",
        "increment",
        "local_time",
        "total_time",
    ):
        if key in frame:
            entry[key] = frame[key]
    result["frames"].append(entry)


def _validate_generation(base, result):
    """Prove every listed frame is the record the index says it is."""
    for entry in result["frames"]:
        name = entry.get("file", "")
        if not name.startswith("frame-") or not name.endswith(".json"):
            raise ValueError(f"Invalid frame name {name!r}.")
        path = Path(base) / name
        if not path.is_file():
            raise ValueError(f"Frame {name!r} was listed but not written.")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("time") != entry.get("time"):
            raise ValueError(f"Frame {name!r} does not match its recorded time.")
        if (payload.get("step_id") or canonical_step(payload.get("step"))) != entry.get(
            "step_id"
        ):
            raise ValueError(f"Frame {name!r} does not match its recorded step.")


def finish(directory, result, availability=None, require_frames=False):
    """Validate one attempt and publish it as a single consistent generation.

    Frames and history are written to a private staging directory first; they
    replace the canonical files only after the index-to-frame identity, step
    order and units have been checked. A history-only recovery is published
    explicitly and never invents a contour or a frame cursor.
    """
    directory = Path(directory)
    staging = directory / STAGING
    if not result["frames"] and not result.get("history"):
        if require_frames:
            raise ValueError("The ODB contains no readable result frames.")
        raise ValueError("The ODB contains no readable field frames or history.")
    if not result["frames"]:
        result["history_only"] = True
        result["initial_only"] = False
    else:
        result["history_only"] = False
        if all(
            abs(float(entry.get("total_time", entry.get("time", 0.0)))) <= 1e-12
            for entry in result["frames"]
        ):
            result["initial_only"] = True
    if availability is None:
        availability = result.get("availability") or "complete"
    result["availability"] = "partial" if availability == "partial" else "complete"
    # A caller may hand already-written frames directly (retained fixtures and
    # unit tests); staged attempts are preferred and moved into place only after
    # the whole generation validates.
    staged = bool(result["frames"]) and all(
        (staging / entry["file"]).is_file() for entry in result["frames"]
    )
    base = staging if staged else directory
    _validate_generation(base, result)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "history.csv"
    tmp = directory / "history.csv.tmp"
    multi_step = len(result.get("steps") or []) > 1
    header = [
        "execution",
        "step",
        "step_id",
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
    if multi_step:
        header.append("role")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in result["history"]:
            signed = row.get("rf2")
            values = [
                result["notice"],
                row.get("step") or "",
                row.get("step_id") or "",
                row["time"],
                # A measurement that was absent stays an empty cell; a measured
                # zero stays numeric zero.
                row.get("u1"),
                row.get("u2"),
                row.get("rf1"),
                signed,
                # Signed global RF2 and its projection are distinct: the old
                # writer put the projected total in this column.
                signed,
                row["displacement"],
                row["force"],
                row["total_force_N"],
            ]
            if multi_step:
                values.append(row.get("role") or "")
            writer.writerow(values)
    os.replace(tmp, path)
    # A single bounded pass over the staged frames records the run-wide camera
    # bounds and colour ranges before the index is published.
    result["display"] = display_metadata(directory, result, base=base)
    if result["frames"]:
        last = result["frames"][-1]
        result["last_frame_ordinal"] = last.get("frame_ordinal", len(result["frames"]) - 1)
        result["last_native_frame_id"] = last.get("native_frame_id")
        result["last_increment"] = last.get("increment")
        result["last_step"] = last.get("step")
        result["last_step_id"] = last.get("step_id")
        result["last_local_s"] = last.get("local_time")
        result["last_total_s"] = last.get("total_time", last.get("time"))
    else:
        result["last_frame_ordinal"] = None
        result["last_native_frame_id"] = None
        result["last_increment"] = None
        last_history = result["history"][-1] if result["history"] else None
        result["last_step"] = last_history.get("step") if last_history else None
        result["last_step_id"] = last_history.get("step_id") if last_history else None
        result["last_local_s"] = None
        result["last_total_s"] = last_history.get("time") if last_history else None
    # Move validated frames into place, then publish the index last.
    if staged:
        for entry in result["frames"]:
            os.replace(staging / entry["file"], directory / entry["file"])
    write_json(directory / "results.json", result)
    shutil.rmtree(staging, ignore_errors=True)
