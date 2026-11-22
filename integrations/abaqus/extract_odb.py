"""Run with 'abaqus python extract_odb.py' in the run directory. No application packages."""

import json
from pathlib import Path

if __package__:
    from .interchange import align_histories, finish, result_header, save_frame
else:
    from interchange import align_histories, finish, result_header, save_frame


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
            seen.add(key)
        if raw["values"]:
            fields[name] = raw
    return displacement, fields, seen


def _history(step, metadata, start_time):
    """History from the reference point that owns this step.

    Legacy metadata has only ``panel_reference``/``closing``; two-step metadata
    names a body reference in step 1 and the door reference in step 2.
    """
    motion = next(
        (entry for entry in metadata.get("steps", []) if entry.get("name") == step.name),
        None,
    )
    ref = (
        {"instance": motion["instance"], "label": motion["reference_label"]}
        if motion and "reference_label" in motion
        else metadata["panel_reference"]
    )
    motion = motion or metadata.get("closing")
    target = "Node {}.{}".format(ref["instance"], ref["label"]).upper()
    for name in step.historyRegions.keys():
        if name.upper() != target:
            continue
        outputs = step.historyRegions[name].historyOutputs
        series = {
            key: outputs[key].data for key in ("U1", "U2", "RF1", "RF2") if key in outputs
        }
        if "U2" in series and "RF2" in series:
            return align_histories(
                series, metadata, start_time, step=step.name, motion=motion
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
    requested = set(metadata["requested"])
    if "CSTRESS" in requested:
        requested.remove("CSTRESS")
        requested.update(("CPRESS", "CSHEAR1"))
    if "U" not in requested:
        result["unavailable"].append("U (not requested)")
    seen = set()
    for name in odb.steps.keys():
        step = odb.steps[name]
        for frame in step.frames:
            displacement, fields, available = _fields(frame, requested, metadata["dimension"])
            frame_time = step.totalTime + frame.frameValue
            save_frame(
                directory,
                result,
                {
                    "time": frame_time,
                    "step": name,
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
