"""Run with 'abaqus python extract_odb.py' in the run directory. No application packages."""

import json
from pathlib import Path

if __package__:
    from . import door_pressure
    from .interchange import (
        align_histories,
        canonical_step,
        finish,
        mises_from_components,
        reset_staging,
        result_header,
        save_frame,
    )
else:
    import door_pressure
    from interchange import (
        align_histories,
        canonical_step,
        finish,
        mises_from_components,
        reset_staging,
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


def _field_keys(fields, variables):
    wanted = {name.upper() for name in variables}
    return [name for name in fields if name.split()[0].upper() in wanted]


def _contact_samples(fields, name, scalar=False, transform=False):
    """instance -> node label -> list of observations, NODAL only.

    ``CPRESS`` is a stored scalar; the ODB exposes it through a one-element data
    array, so it is unwrapped here. ``CNORMF`` keeps its signed components. A
    vector stored in a local coordinate system is rotated into the assembly
    frame before it reaches the arrow direction.
    """
    samples = {}
    for value in fields[name].get("values") or []:
        if value.get("position") != "NODAL":
            continue
        instance = value.get("instance")
        label = value.get("node")
        if instance is None or label is None:
            continue
        data = value.get("data") or []
        axes = value.get("local_axes")
        if transform and axes and data:
            rows = [[float(item) for item in row] for row in axes]
            width = min(len(data), len(rows))
            columns = min(len(data), len(rows[0]) if rows else 0)
            if width and columns:
                data = [
                    sum(float(data[row]) * rows[row][column] for row in range(width))
                    for column in range(columns)
                ]
        observation = data[0] if scalar and data else data
        samples.setdefault(instance, {}).setdefault(label, []).append(observation)
    return samples


def _coverage(samples):
    return {name: sum(len(nodes) for nodes in by_instance.values()) for name, by_instance in samples.items()}


def _select_domain(keys, samples):
    """Pick one contact domain deterministically and report the alternatives.

    A general-contact aggregate (``General_Contact_Faces``) is the total on the
    mapped door and is preferred when it carries samples. Named-pair keys are
    never combined with it: a different contact domain is a different identity.
    """
    if not keys:
        return None
    coverage = _coverage({name: samples[name] for name in keys})
    preferred = next((name for name in keys if "General_Contact_Faces" in name), None)
    if preferred is not None and coverage.get(preferred):
        return preferred
    return max(keys, key=lambda name: (coverage.get(name, 0), name))


def _door_frame(fields, displacement, door):
    if not door or not door.get("enabled"):
        return None
    profiles = door.get("profiles") or []
    pressure_keys = _field_keys(fields, ("CPRESS",))
    force_keys = _field_keys(fields, ("CNORMF", "CFORCE"))
    pressure_samples = {
        name: _contact_samples(fields, name, scalar=True) for name in pressure_keys
    }
    force_samples = {
        name: _contact_samples(fields, name, transform=True) for name in force_keys
    }
    pressure_domain = _select_domain(pressure_keys, pressure_samples)
    force_domain = _select_domain(force_keys, force_samples)
    pressure_coverage = _coverage(pressure_samples)
    force_coverage = _coverage(force_samples)
    frame = {
        "profiles": {},
        "pressure_domain": pressure_domain,
        "force_domain": force_domain,
        "domains": {
            "pressure": sorted(pressure_keys),
            "force": sorted(force_keys),
        },
        "coverage": {
            "pressure": pressure_coverage,
            "force": force_coverage,
        },
        "unavailable": [],
    }
    if not pressure_keys:
        frame["unavailable"].append("pressure_field_missing")
    if not force_keys:
        frame["unavailable"].append("force_field_missing")
    for profile in profiles:
        identifier = profile.get("id")
        if not profile.get("supported"):
            frame["profiles"][identifier] = {
                "supported": False,
                "reason": profile.get("reason"),
            }
            continue
        instance = profile["instance"]
        pressure = (pressure_samples.get(pressure_domain) or {}).get(instance, {})
        force = (force_samples.get(force_domain) or {}).get(instance, {})
        aligned = door_pressure.align_profile(
            profile,
            pressure,
            force,
            bool(displacement.get(instance)),
        )
        aligned["supported"] = True
        if not pressure_keys:
            aligned["availability"]["pressure"] = "pressure_field_missing"
        elif not pressure:
            aligned["availability"]["pressure"] = "pressure_not_reported_for_instance"
        if not force_keys:
            aligned["availability"]["force"] = "force_field_missing"
        elif not force:
            aligned["availability"]["force"] = "force_not_reported_for_instance"
        frame["profiles"][identifier] = aligned
    return frame


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
    reset_staging(directory)
    # The door profile axis is derived once from the ODB's own assembled R2D2
    # connectivity, so translating or rotating the door and changing frames or
    # zoom cannot move a station. No profile is invented for an absent instance.
    door = dict(metadata.get("door_pressure") or {"enabled": False})
    if door.get("enabled"):
        door["profiles"] = door_pressure.profile_definitions(
            instances, door.get("instances") or []
        )
        door["field_location"] = "NODAL"
        door["fields"] = {"pressure": [], "force": []}
    result["door_pressure"] = door
    # Normalize every step identity to the one canonical form used by frames,
    # histories, the plot selector and CSV rows. Older metadata may carry an
    # identifier produced by an earlier canonicalization.
    for entry in result.get("steps") or []:
        entry["id"] = canonical_step(entry.get("name"))
    requested = set(metadata["requested"])
    if "CSTRESS" in requested:
        requested.remove("CSTRESS")
        requested.update(("CPRESS", "CSHEAR1"))
    if door.get("enabled"):
        # The graph and the arrow anchor need exactly these three fields. U is
        # added by the deck writer when the wider U field was deselected.
        requested.update(("CPRESS", "CNORMF", "U"))
    if "U" not in requested:
        result["unavailable"].append("U (not requested)")
    seen = set()
    contact_fields = {"pressure": set(), "force": set()}
    profile_max = {
        profile.get("id"): 0.0
        for profile in (door.get("profiles") or [])
        if profile.get("supported")
    }
    frame_ordinal = 0
    skipped = []
    planned_steps = [
        canonical_step(entry.get("name")) for entry in (metadata.get("steps") or [])
    ]
    present_steps = set()
    for step_ordinal, name in enumerate(odb.steps.keys()):
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
        for step_frame_ordinal, frame in enumerate(step.frames):
            # Every visited record keeps its ordinal, even when it cannot be
            # read, so a skipped trailing record never renumbers the readable
            # ones and a duplicate recovery frame keeps its own identity.
            ordinal = frame_ordinal
            frame_ordinal += 1
            increment = getattr(frame, "incrementNumber", None)
            native_id = getattr(frame, "frameId", None)
            try:
                displacement, fields, available = _fields(
                    frame, requested, metadata["dimension"]
                )
            except Exception as error:  # noqa: BLE001 - reported, never hidden
                skipped.append(
                    {
                        "step": display_name,
                        "step_id": step_id,
                        "step_ordinal": step_ordinal,
                        "step_frame_ordinal": step_frame_ordinal,
                        "frame_ordinal": ordinal,
                        "native_frame_id": native_id,
                        "increment": increment,
                        "reason": f"{type(error).__name__}: {error}",
                    }
                )
                continue
            local_time = float(frame.frameValue)
            total_time = step.totalTime + local_time
            payload = {
                "time": total_time,
                "step": display_name,
                "step_id": step_id,
                "odb_step": name,
                "step_ordinal": step_ordinal,
                "step_frame_ordinal": step_frame_ordinal,
                "frame_ordinal": ordinal,
                "native_frame_id": native_id,
                "increment": increment,
                "local_time": local_time,
                "total_time": total_time,
                "displacements": displacement,
                "fields": fields,
                # Optional fields absent from this frame stay identifiable
                # instead of being interpolated from a neighbour.
                "unavailable": sorted(requested - available),
            }
            present_steps.add(step_id)
            if door.get("enabled"):
                payload["door_pressure"] = _door_frame(fields, displacement, door)
                for category, variables in (
                    ("pressure", ("CPRESS",)),
                    ("force", ("CNORMF", "CFORCE")),
                ):
                    contact_fields[category].update(_field_keys(fields, variables))
                for identifier, aligned in payload["door_pressure"]["profiles"].items():
                    for value in aligned.get("pressure_kpa") or []:
                        if value is not None:
                            profile_max[identifier] = max(
                                profile_max.get(identifier, 0.0), abs(float(value))
                            )
            save_frame(
                directory,
                result,
                payload,
            )
            seen.update(available)
        try:
            result["history"].extend(_history(step, metadata, step.totalTime))
        except Exception as error:  # noqa: BLE001 - a missing history keeps its reason
            skipped.append(
                {
                    "step": display_name,
                    "step_id": step_id,
                    "step_ordinal": step_ordinal,
                    "reason": f"history: {type(error).__name__}: {error}",
                }
            )
    if door.get("enabled"):
        door["fields"] = {
            "pressure": sorted(contact_fields["pressure"]),
            "force": sorted(contact_fields["force"]),
        }
        for profile in door.get("profiles") or []:
            if profile.get("supported"):
                profile["maximum_pressure_kpa"] = profile_max.get(profile.get("id"), 0.0)
    result["unavailable"].extend(sorted(requested - seen))
    if not result["history"]:
        result["unavailable"].append("Panel U2/RF2 history on a common time interval")
    result["skipped_frames"] = skipped
    result["gaps"] = [
        {
            "kind": "unreadable_frame",
            "frame_ordinal": entry.get("frame_ordinal"),
            "reason": entry.get("reason"),
        }
        for entry in skipped
        if "frame_ordinal" in entry
    ]
    # Completeness is only claimed from positive evidence: a successful solver,
    # no unreadable records and every planned step present. A planned step that
    # never ran (for example Closing after a Body seating failure) makes the
    # generation partial; it is never inferred from duration or interval.
    outcome = metadata.get("solver_outcome") or "Succeeded"
    complete = (
        outcome == "Succeeded"
        and not skipped
        and bool(result["frames"])
        and all(step in present_steps for step in planned_steps)
    )
    result["solver_outcome"] = outcome
    result["failure_reason"] = metadata.get("failure_reason") or ""
    finish(
        directory,
        result,
        availability="complete" if complete else "partial",
        require_frames=outcome == "Succeeded",
    )


def main():
    from odbAccess import openOdb

    with Path("result-metadata.json").open(encoding="utf-8") as f:
        metadata = json.load(f)
    if metadata.get("version") != 1:
        raise ValueError("Unsupported extractor metadata version.")
    # Terminal solver facts are attempt-scoped and never rewrite the submitted
    # metadata artifact.
    context_path = Path("extraction-context.json")
    if context_path.is_file():
        with context_path.open(encoding="utf-8") as f:
            context = json.load(f)
        for key in ("solver_outcome", "failure_reason"):
            if context.get(key):
                metadata[key] = context[key]
    odb = openOdb(path="analysis.odb", readOnly=True)
    try:
        extract(odb, metadata, Path.cwd())
    finally:
        odb.close()


if __name__ == "__main__":
    main()
