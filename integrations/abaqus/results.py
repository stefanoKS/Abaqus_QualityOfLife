"""Host-side manifest preparation and deterministic synthetic playback."""

from pathlib import Path

from .deck import (
    _mesh_parts,
    exterior,
    fixed_nodes,
    mesh_parts,
    motion_assessment,
)
from packages.engineering import motion as motion_policy
from .interchange import (
    align_histories,
    canonical_step,
    finish,
    result_header,
    save_frame,
    write_json,
)


def _force_basis(project):
    """Displayed-force basis recorded with every new run.

    ``legacy_unscaled`` means the run predates the reporting width; its own
    solver thickness was the whole basis. New setups record the represented
    width explicitly so the chart, export and documentation agree.
    """
    if project.schema_version < 4 or project.analysis.reporting_width_basis == "legacy_thickness":
        return "legacy_unscaled"
    return "per_mm" if project.analysis.force_normalization == "per_mm" else "total_width"


def _metadata(project, nodes, ws, panel, fixture=None, body=None):
    roles = {c.id: c.role for c in project.components}
    instance = {c: "PANEL-1" if role == "moving_panel" else "WS-1" for c, role in roles.items()}
    if body is not None:
        instance = {
            c: (
                "PANEL-1"
                if role == "moving_panel"
                else "BODY-1"
                if role == "vehicle_body"
                else "WS-1"
            )
            for c, role in roles.items()
        }
    reference = max(n for e in panel for n in e["nodes"]) + 1

    def label(component_id):
        return next(
            (
                component.alias.strip() or component.name
                for component in project.components
                if component.id == component_id
            ),
            component_id,
        )

    boundary = exterior(ws)
    # Each rigid profile keeps its own measured contact side and projection
    # direction. A bottom-mounted body projects along +Y while the door above
    # it projects along -Y; neither direction is assumed from the other.
    door = motion_assessment(
        nodes,
        boundary,
        panel,
        project.motion,
        role="door",
        instance="PANEL-1",
        label="door",
        schema_version=project.schema_version,
    )
    seated = (
        motion_assessment(
            nodes,
            boundary,
            body,
            project.motion.body,
            role="body",
            instance="BODY-1",
            label="body",
            schema_version=project.schema_version,
        )
        if body
        else None
    )
    door_motion = motion_policy.resolve(project.motion, project.schema_version)
    body_motion = motion_policy.resolve(project.motion.body, project.schema_version, body=True)
    closing = {
        "panel": panel[0]["component"],
        "panel_name": label(panel[0]["component"]),
        "instance": "PANEL-1",
        "reference_label": reference,
        "direction": door["direction"],
        "distance_mm": door_motion["stroke"],
        "angle_deg": door_motion["angle"],
        "delta_mm": door_motion["delta"],
        "measure_from_step_start": True,
        "steps": [{"name": "Closing", "role": "door"}],
    }
    steps = [
        {
            "name": "Closing",
            # Canonical identity shared by ODB steps, frames, histories, the
            # plot selector and CSV rows; the display name is preserved above.
            "id": canonical_step("Closing"),
            "role": "door",
            "instance": "PANEL-1",
            "reference_label": reference,
            "direction": door["direction"],
            "distance_mm": door_motion["stroke"],
            "angle_deg": door_motion["angle"],
            "delta_mm": door_motion["delta"],
            "travel_mm": door_motion["delta"][1],
            "stroke_mm": door_motion["stroke"],
            "duration_s": project.motion.duration,
        }
    ]
    placement = {
        "initial_offset_y_mm": project.motion.offset,
        "initial_vertical_mesh_clearance_mm": door["clearance_mm"],
        "prescribed_panel_travel_y_mm": door_motion["delta"][1],
        # Role-aware additions; the legacy key above keeps its exact meaning.
        "door_side": door["side"],
        "door_direction": door["direction"],
        "door_angle_deg": door_motion["angle"],
        "door_stroke_mm": door_motion["stroke"],
        "door_delta_mm": door_motion["delta"],
        "initial_door_clearance_mm": door["clearance_mm"],
        "door_reaches_initial_gap": door["reaches_initial_gap"],
        "door_hold": door["hold"],
    }
    regions = {
        "WS-1": {str(e["id"]): e["entity"] for e in ws},
        "PANEL-1": {str(e["id"]): e["entity"] for e in panel},
    }
    result = {
        # Extractors accept version 1; new fields are additive and optional.
        "version": 1,
        "schema_version": project.schema_version,
        "units": project.units,
        "dimension": project.dimension,
        "thickness": project.analysis.thickness,
        "thickness_mm": project.analysis.thickness,
        "reporting_width_mm": project.analysis.reporting_width,
        "reporting_width_basis": project.analysis.reporting_width_basis,
        "force_basis": _force_basis(project),
        "force_normalization": project.analysis.force_normalization,
        "contact": {
            "basis": "legacy" if project.contact.friction is not None else "named_pairs",
            "door_seal": project.contact.door_seal,
            "body_seal": project.contact.body_seal,
            "seal_self": project.contact.seal_self,
            "legacy_scalar": project.contact.friction,
        },
        "requested": project.analysis.outputs,
        "placement": placement,
        "assembly": {"door": door, "body": seated},
        "fixture": {
            "source": "cad-edge-selection" if fixture is None else "mesh-node-selection",
            "count": None if fixture is None else len(fixture),
            "nodes": None if fixture is None else list(fixture),
        },
        "closing": closing,
        "steps": steps,
        "sets": {
            "edges": {
                e.id: f"{instance[e.component]}.EDGE_{i}" for i, e in enumerate(project.edges, 1)
            },
            "regions": {
                f.id: f"WS-1.REGION_{i}" for i, f in enumerate(project.faces, 1) if f.material
            },
            "mounting": {project.mounting.selection: "WSFIX"},
        },
        "panel_reference": {
            "instance": "PANEL-1",
            "label": reference,
        },
        "regions": regions,
    }
    if seated is not None:
        body_reference = max(n for e in body for n in e["nodes"]) + 1
        body_component = body[0]["component"]
        body_block = {
            "panel": body_component,
            "panel_name": label(body_component),
            "instance": "BODY-1",
            "reference_label": body_reference,
            "direction": seated["direction"],
            "distance_mm": body_motion["stroke"],
            "angle_deg": body_motion["angle"],
            "delta_mm": body_motion["delta"],
            "travel_mm": body_motion["delta"][1],
            "stroke_mm": body_motion["stroke"],
            "duration_s": project.motion.body.duration,
            "measure_from_step_start": True,
            "side": seated["side"],
        }
        placement.update(
            {
                "initial_body_offset_y_mm": project.motion.body.offset,
                "initial_body_vertical_mesh_clearance_mm": seated["clearance_mm"],
                "prescribed_body_travel_y_mm": body_motion["delta"][1],
                "body_side": seated["side"],
                "body_direction": seated["direction"],
                "body_angle_deg": body_motion["angle"],
                "body_stroke_mm": body_motion["stroke"],
                "body_delta_mm": body_motion["delta"],
                "initial_body_clearance_mm": seated["clearance_mm"],
                "body_reaches_initial_gap": seated["reaches_initial_gap"],
                "body_hold": seated["hold"],
            }
        )
        steps = [
            {
                "name": "Body seating",
                "id": canonical_step("Body seating"),
                "role": "body",
                "instance": "BODY-1",
                "reference_label": body_block["reference_label"],
                "direction": seated["direction"],
                "distance_mm": body_motion["stroke"],
                "angle_deg": body_motion["angle"],
                "delta_mm": body_motion["delta"],
                "travel_mm": body_motion["delta"][1],
                "stroke_mm": body_motion["stroke"],
                "duration_s": project.motion.body.duration,
            },
            steps[0],
        ]
        result["steps"] = steps
        result["body"] = body_block
        result["body_reference"] = {"instance": "BODY-1", "label": body_block["reference_label"]}
        result["closing"]["steps"] = steps
        regions["BODY-1"] = {str(e["id"]): e["entity"] for e in body}
    return result


def write_metadata(project, mesh, job_dir, fixture=None):
    nodes, ws, panel, body = _mesh_parts(project, mesh)
    write_json(
        Path(job_dir) / "result-metadata.json",
        _metadata(project, nodes, ws, panel, fixture, body if body else None),
    )


def write_playback(project, mesh, job_dir, fixture=None, mode="DEMO", notice=None):
    """Write a deterministic playback dataset.

    ``mode="DEMO"`` is the retained historical format. Tests use
    ``mode="ABAQUS"`` with a manufactured result at the extractor boundary;
    ``notice`` then makes the manufactured provenance explicit. The library is
    never reachable through the HTTP API for a new submission.
    """
    if project.analysis.mode == "body_then_door":
        raise ValueError(
            "Manufactured playback does not model body-then-door contact; "
            "a licensed Abaqus run is required for this mode."
        )
    nodes, ws, panel = mesh_parts(project, mesh)
    metadata = _metadata(project, nodes, ws, panel, fixture)
    instances = []
    for name, elements in (("WS-1", ws), ("PANEL-1", panel)):
        labels = sorted({n for element in elements for n in element["nodes"]})
        offset = project.motion.offset if name == "PANEL-1" else 0
        points = [[n, nodes[n][0], nodes[n][1] + offset, nodes[n][2]] for n in labels]
        if name == "PANEL-1":
            reference = metadata["panel_reference"]["label"]
            points.append(
                [reference, *(sum(p[i] for p in points) / len(points) for i in (1, 2, 3))]
            )
        instances.append(
            {
                "name": name,
                "nodes": points,
                "elements": [
                    {
                        "label": e["id"],
                        "type": e["type"],
                        "connectivity": e["nodes"],
                        "region": e["entity"],
                    }
                    for e in elements
                ],
            }
        )

    result = result_header(metadata, mode, instances)
    if notice:
        result["notice"] = notice
        result["manufactured"] = True
    result["averaging"] = "Analytic synthetic nodal displacements for playback."
    result["unavailable"] = ["RF field", "S", "LE", "CPRESS"]
    seal = instances[0]["nodes"]
    ymin, ymax = min(n[2] for n in seal), max(n[2] for n in seal)
    xmin, xmax = min(n[1] for n in seal), max(n[1] for n in seal)
    fixed = set(fixed_nodes(project, mesh, fixture))
    gap = metadata["placement"]["initial_vertical_mesh_clearance_mm"]
    door_motion = motion_policy.resolve(project.motion, project.schema_version)
    direction = door_motion["delta"]
    length = (direction[0] ** 2 + direction[1] ** 2) ** 0.5
    unit = (
        [direction[0] / length, direction[1] / length] if length > 1e-12 else [0.0, -1.0]
    )
    perpendicular = [-unit[1], unit[0]]
    travel = {"U1": {}, "U2": {}, "RF1": {}, "RF2": {}}
    for i in range(31):
        fraction = i / 30
        time = project.motion.duration * fraction
        movement = [value * fraction for value in door_motion["delta"]]
        along = movement[0] * unit[0] + movement[1] * unit[1]
        synthetic_closure = max(0, along - gap)
        dy_max = min(synthetic_closure, (ymax - ymin) * 0.8)
        field = {}
        if "U" in project.analysis.outputs:
            field["PANEL-1"] = [[n[0], movement[0], movement[1], 0] for n in instances[1]["nodes"]]
            field["WS-1"] = []
            for label, x, y, _ in seal:
                weight = 0 if label in fixed else (y - ymin) / (ymax - ymin)
                bulge = (x - (xmin + xmax) / 2) / (xmax - xmin) * 0.24 * dy_max * weight
                field["WS-1"].append(
                    [
                        label,
                        weight * dy_max * unit[0] + bulge * perpendicular[0],
                        weight * dy_max * unit[1] + bulge * perpendicular[1],
                        0,
                    ]
                )
        save_frame(
            job_dir,
            result,
            {
                "time": time,
                "step": "Closing",
                "displacements": field,
                "fields": {},
                "unavailable": ["RF", "S", "LE", "CPRESS"] + ([] if field else ["U"]),
            },
        )
        # Free illustrative curve; coefficients are not measured material parameters.
        # The reaction on the rigid panel opposes its prescribed travel, so the
        # projection onto the travel direction is positive and grows with closure.
        force = project.analysis.thickness * (
            1.6 * synthetic_closure + 0.4 * synthetic_closure**2
        )
        travel["U1"][time] = movement[0]
        travel["U2"][time] = movement[1]
        travel["RF1"][time] = force * unit[0]
        travel["RF2"][time] = force * unit[1]
    if "U" not in project.analysis.outputs:
        result["unavailable"].append("U")
    result["history"] = align_histories(travel, metadata, step="Closing")
    finish(job_dir, result)


def write_demo(project, mesh, job_dir, fixture=None):
    write_playback(project, mesh, job_dir, fixture, mode="DEMO")
