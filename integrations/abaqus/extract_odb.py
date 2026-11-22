"""Run with 'abaqus python extract_odb.py' in the run directory. No application packages."""

import json
from pathlib import Path

if __package__:
    from .interchange import (
        align_histories,
        canonical_step,
        finish,
        mises_from_components,
        result_header,
        save_frame,
    )
else:
    from interchange import (
        align_histories,
        canonical_step,
        finish,
        mises_from_components,
        result_header,
        save_frame,
    )


def _data(value):
    raw = value.dataDouble if str(value.precision) == "DOUBLE_PRECISION" else value.data
    return [float(x) for x in raw] if hasattr(raw, "__len__") else [float(raw)]


def _coordinates(values, dimension):
    xyz = [float(x) for x in values]
    if dimension == "2D" and len(xyz) == 2:
        xyz.append(0.0)  # Out-of-plane kinematics in this plane-stress template.
    if len(xyz) != 3:
        raise ValueError("Unrecognized nodal coordinate or displacement dimension.")
    return xyz


def _sample_key(value):
    """Identity of one field sample, used to align the Mises invariant with S."""
    section = getattr(value, "sectionPoint", None)
    return (
        value.instance.name if value.instance is not None else None,
        str(value.position),
        getattr(value, "elementLabel", None),
        getattr(value, "nodeLabel", None),
        getattr(value, "integrationPoint", None),
        section.number if section is not None else None,
    )


def _mises_invariant(field):
    """The ODB's own invariant when this Abaqus runtime provides it."""
    try:
        from abaqusConstants import MISES

        scalar = field.getScalarField(invariant=MISES)
    except Exception:
        return {}
    try:
        return {_sample_key(value): _data(value)[0] for value in scalar.values}
    except Exception:
        return {}


def _fields(frame, requested, dimension):
    displacement, fields, seen = {}, {}, set()
    for name in frame.fieldOutputs.keys():
        key = name.split()[0]
        if key not in requested:
            continue
        field = frame.fieldOutputs[name]
        raw = {
            "components": list(field.componentLabels),
            "type": str(field.type),
            "averaging": "as_stored",
            "values": [],
        }
        invariant = _mises_invariant(field) if key == "S" else {}
        mises_values = []
        for value in field.values:
            instance = value.instance
            if instance is None:
                continue
            position = str(value.position)
            data = _data(value)
            if key == "U" and position == "NODAL":
                displacement.setdefault(instance.name, []).append(
                    [value.nodeLabel, *_coordinates(data, dimension)]
                )
            else:
                entry = {"instance": instance.name, "position": position, "data": data}
                if position in ("NODAL", "ELEMENT_NODAL"):
                    entry["node"] = value.nodeLabel
                if position != "NODAL":
                    entry["element"] = value.elementLabel
                if position == "INTEGRATION_POINT":
                    entry["integration_point"] = value.integrationPoint
                section = getattr(value, "sectionPoint", None)
                if section is not None:
                    entry["section_point"] = section.number
                orientation = (
                    value.localCoordSystemDouble
                    if str(value.precision) == "DOUBLE_PRECISION"
                    else value.localCoordSystem
                )
                if orientation is not None:
                    entry["local_axes"] = [[float(x) for x in axis] for axis in orientation]
                raw["values"].append(entry)
                if key == "S":
                    # Prefer the solver's own invariant; fall back to a
                    # component-label-aware plane/3D calculation. The sample
                    # identity (instance, element, IP, section point) is kept.
                    mises = invariant.get(_sample_key(value))
                    if mises is None:
                        mises = mises_from_components(field.componentLabels, data)
                    if mises is not None:
                        sample = {
                            "instance": instance.name,
                            "position": position,
                            "data": [float(mises)],
                        }
                        if position in ("NODAL", "ELEMENT_NODAL"):
                            sample["node"] = value.nodeLabel
                        if position != "NODAL":
                            sample["element"] = value.elementLabel
                        if position == "INTEGRATION_POINT":
                            sample["integration_point"] = value.integrationPoint
                        if section is not None:
                            sample["section_point"] = section.number
                        mises_values.append(sample)
            seen.add(key)
        if raw["values"]:
            fields[name] = raw
        if mises_values:
            fields["Mises"] = {
                "components": ["Mises"],
                "type": "SCALAR",
                "averaging": "as_stored",
                "values": mises_values,
            }
    return displacement, fields, seen


def _history(step, metadata, start_time):
    """History from the reference point that owns this step.

    Legacy metadata has only ``panel_reference``/``closing``; two-step metadata
    names a body reference in step 1 and the door reference in step 2. Each
    step carries its own projection direction, so the body's upward seating is
    never projected onto the door's downward closing axis.
    """
    steps = metadata.get("steps") or []
    step_id = canonical_step(step.name)
    motion = next(
        (
            entry
            for entry in steps
            if canonical_step(entry.get("name")) == step_id
            or canonical_step(entry.get("id")) == step_id
        ),
        None,
    )
    if steps and motion is None:
        # Never project an unknown step onto the door reference: that would
        # label body seating as a door response.
        return []
    ref = (
        {"instance": motion["instance"], "label": motion["reference_label"]}
        if motion and "reference_label" in motion
        else metadata["panel_reference"]
    )
    motion = motion or metadata.get("closing")
    display = motion.get("name") if motion and motion.get("name") else step.name
    region = "Node {}.{}".format(ref["instance"], ref["label"]).upper()
    for name in step.historyRegions.keys():
        if name.upper() != region:
            continue
        outputs = step.historyRegions[name].historyOutputs
        series = {
            key: outputs[key].data for key in ("U1", "U2", "RF1", "RF2") if key in outputs
        }
        if series:
            return align_histories(
                series,
                metadata,
                start_time,
                step=display,
                step_id=step_id,
                motion=motion,
            )
    return []


def extract(odb, metadata, directory):
    instances = []
    for name in odb.rootAssembly.instances.keys():
        inst = odb.rootAssembly.instances[name]
        regions = metadata["regions"].get(name, {})
        instances.append(
            {
                "name": name,
                "nodes": [
                    [n.label, *_coordinates(n.coordinates, metadata["dimension"])]
                    for n in inst.nodes
                ],
                "elements": [
                    {
                        "label": e.label,
                        "type": e.type,
                        "connectivity": list(e.connectivity),
                        "region": regions.get(str(e.label)),
                    }
                    for e in inst.elements
                ],
            }
        )
    result = result_header(metadata, "ABAQUS", instances)
    # Normalize every step identity to the one canonical form used by frames,
    # histories, the plot selector and CSV rows. Older metadata may carry an
    # identifier produced by an earlier canonicalization.
    for entry in result.get("steps") or []:
        entry["id"] = canonical_step(entry.get("name"))
    requested = set(metadata["requested"])
    if "CSTRESS" in requested:
        requested.remove("CSTRESS")
        requested.update(("CPRESS", "CSHEAR1"))
    if "U" not in requested:
        result["unavailable"].append("U (not requested)")
    seen = set()
    for name in odb.steps.keys():
        step = odb.steps[name]
        step_id = canonical_step(name)
        matched = next(
            (
                entry
                for entry in metadata.get("steps") or []
                if canonical_step(entry.get("name")) == step_id
                or canonical_step(entry.get("id")) == step_id
            ),
            None,
        )
        # Display/provenance uses the configured name; the ODB's own label is
        # retained separately where Abaqus has stripped its whitespace.
        display_name = matched.get("name") if matched else name
        for frame in step.frames:
            displacement, fields, available = _fields(frame, requested, metadata["dimension"])
            frame_time = step.totalTime + frame.frameValue
            save_frame(
                directory,
                result,
                {
                    "time": frame_time,
                    "step": display_name,
                    "step_id": step_id,
                    "odb_step": name,
                    "displacements": displacement,
                    "fields": fields,
                    "unavailable": sorted(requested - available),
                },
            )
            seen.update(available)
        result["history"].extend(_history(step, metadata, step.totalTime))
    result["unavailable"].extend(sorted(requested - seen))
    if not result["history"]:
        result["unavailable"].append("Panel U2/RF2 history on a common time interval")
    finish(directory, result)


def main():
    from odbAccess import openOdb

    with Path("result-metadata.json").open(encoding="utf-8") as f:
        metadata = json.load(f)
    if metadata.get("version") != 1:
        raise ValueError("Unsupported extractor metadata version.")
    odb = openOdb(path="analysis.odb", readOnly=True)
    try:
        extract(odb, metadata, Path.cwd())
    finally:
        odb.close()


if __name__ == "__main__":
    main()
