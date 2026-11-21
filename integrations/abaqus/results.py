"""Host-side manifest preparation and deterministic synthetic playback."""

from pathlib import Path

from .deck import exterior, fixed_nodes, mesh_parts, vertical_gap
from .interchange import align_histories, finish, result_header, save_frame, write_json


def _metadata(project, nodes, ws, panel, fixture=None):
    roles = {c.id: c.role for c in project.components}
    instance = {c: "PANEL-1" if role == "moving_panel" else "WS-1" for c, role in roles.items()}
    reference = max(n for e in panel for n in e["nodes"]) + 1
    # The vertical closing template moves the panel down Y; the direction is
    # normalized so the reported travel is a signed distance along it.
    direction = [0.0, -1.0]
    return {
        "version": 1,
        "units": project.units,
        "dimension": project.dimension,
        "thickness": project.analysis.thickness,
        "force_normalization": project.analysis.force_normalization,
        "requested": project.analysis.outputs,
        "placement": {
            "initial_offset_y_mm": project.motion.offset,
            "initial_vertical_mesh_clearance_mm": vertical_gap(
                nodes, exterior(ws), panel, project.motion.offset
            ),
            "prescribed_panel_travel_y_mm": project.motion.travel,
        },
        "fixture": {
            "source": "cad-edge-selection" if fixture is None else "mesh-node-selection",
            "count": None if fixture is None else len(fixture),
            "nodes": None if fixture is None else list(fixture),
        },
        "closing": {
            "panel": panel[0]["component"],
            "instance": "PANEL-1",
            "reference_label": reference,
            "direction": direction,
            "distance_mm": abs(project.motion.travel),
            "measure_from_step_start": True,
            "steps": [{"name": "Closing", "role": "door"}],
        },
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
        "regions": {
            name: {str(e["id"]): e["entity"] for e in group}
            for name, group in (("WS-1", ws), ("PANEL-1", panel))
        },
    }


def write_metadata(project, mesh, job_dir, fixture=None):
    nodes, ws, panel = mesh_parts(project, mesh)
    write_json(
        Path(job_dir) / "result-metadata.json", _metadata(project, nodes, ws, panel, fixture)
    )


def write_demo(project, mesh, job_dir, fixture=None):
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

    result = result_header(metadata, "DEMO", instances)
    result["averaging"] = "Analytic synthetic nodal displacements for playback."
    result["unavailable"] = ["RF field", "S", "LE", "CPRESS"]
    seal = instances[0]["nodes"]
    ymin, ymax = min(n[2] for n in seal), max(n[2] for n in seal)
    xmin, xmax = min(n[1] for n in seal), max(n[1] for n in seal)
    fixed = set(fixed_nodes(project, mesh, fixture))
    gap = metadata["placement"]["initial_vertical_mesh_clearance_mm"]
    travel = {"U1": {}, "U2": {}, "RF1": {}, "RF2": {}}
    for i in range(31):
        fraction = i / 30
        time = project.motion.duration * fraction
        movement = project.motion.travel * fraction
        synthetic_closure = max(0, -movement - gap)
        dy_max = min(synthetic_closure, (ymax - ymin) * 0.8)
        field = {}
        if "U" in project.analysis.outputs:
            field["PANEL-1"] = [[n[0], 0, movement, 0] for n in instances[1]["nodes"]]
            field["WS-1"] = []
            for label, x, y, _ in seal:
                weight = 0 if label in fixed else (y - ymin) / (ymax - ymin)
                bulge = (x - (xmin + xmax) / 2) / (xmax - xmin) * 0.24 * dy_max * weight
                field["WS-1"].append([label, bulge, -weight * dy_max, 0])
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
        # Measured convention: Abaqus reports RF2 < 0 while the seal resists the
        # downward stroke, so the force projected onto the closing direction is
        # positive and grows with travel.
        force = -project.analysis.thickness * (
            1.6 * synthetic_closure + 0.4 * synthetic_closure**2
        )
        travel["U1"][time] = 0.0
        travel["U2"][time] = movement
        travel["RF1"][time] = 0.0
        travel["RF2"][time] = force
    if "U" not in project.analysis.outputs:
        result["unavailable"].append("U")
    result["history"] = align_histories(travel, metadata, step="Closing")
    finish(job_dir, result)
