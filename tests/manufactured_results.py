"""Manufactured partial results for the launcher/ODB-reader double.

This module is imported only by ``tests/fake_abaqus.py``. It writes result
artifacts that exercise the *application* lifecycle (partial publication,
opening, retry, packaging) without a solver, license or real ODB. Every artifact
is labelled as manufactured test evidence; nothing here is solver evidence.
"""

import json
from pathlib import Path

from integrations.abaqus.deck import _mesh_parts
from integrations.abaqus.interchange import (
    align_histories,
    canonical_step,
    finish,
    reset_staging,
    result_header,
    save_frame,
)
from packages.engineering.model import Project

NOTICE = "MANUFACTURED TEST EVIDENCE - not an Abaqus analysis."


def _instances(project, mesh):
    nodes, ws, panel, body = _mesh_parts(project, mesh)
    groups = [("WS-1", ws, 0.0), ("PANEL-1", panel, project.motion.offset)]
    if body:
        groups.append(("BODY-1", body, project.motion.body.offset))
    instances = []
    for name, elements, offset in groups:
        labels = sorted({n for element in elements for n in element["nodes"]})
        points = [[n, nodes[n][0], nodes[n][1] + offset, nodes[n][2]] for n in labels]
        instances.append(
            {
                "name": name,
                "nodes": points,
                "elements": [
                    {
                        "label": element["id"],
                        "type": element["type"],
                        "connectivity": element["nodes"],
                        "region": element["entity"],
                    }
                    for element in elements
                ],
            }
        )
    return nodes, instances


def _frame(displacements, time, step, step_id, ordinal, step_ordinal, frame_ordinal, increment):
    return {
        "time": time,
        "step": step,
        "step_id": step_id,
        "odb_step": step.replace(" ", ""),
        "step_ordinal": step_ordinal,
        "step_frame_ordinal": frame_ordinal,
        "frame_ordinal": ordinal,
        "native_frame_id": 100 + ordinal,
        "increment": increment,
        "local_time": time,
        "total_time": time,
        "displacements": displacements,
        "fields": {},
        "unavailable": ["S", "CPRESS", "CNORMF"],
    }


def write(directory, plan="partial-closing"):
    """Write one manufactured partial generation under ``directory``."""
    directory = Path(directory)
    setup = Project.model_validate(json.loads((directory / "setup.json").read_text(encoding="utf-8")))
    mesh = json.loads((directory / "mesh.json").read_text(encoding="utf-8"))
    metadata = json.loads(
        (directory / "result-metadata.json").read_text(encoding="utf-8")
    )
    context = {}
    if (directory / "extraction-context.json").is_file():
        context = json.loads(
            (directory / "extraction-context.json").read_text(encoding="utf-8")
        )
    nodes, instances = _instances(setup, mesh)
    result = result_header(metadata, "ABAQUS", instances)
    result["notice"] = NOTICE
    result["manufactured"] = True
    result["averaging"] = "Manufactured nodal displacement for lifecycle verification."
    reset_staging(directory)
    steps = metadata.get("steps") or [{"name": "Closing", "role": "door"}]
    durations = []
    for entry in steps:
        name = entry.get("name") or entry.get("id") or "Step"
        duration = float(entry.get("duration_s") or 0.6)
        durations.append((name, canonical_step(name), duration, entry))
    total = 0.0
    ordinal = 0
    history = []
    plans = {
        "partial-body-only": {"Body seating"},
        "partial-closing": None,
        "partial-initial-only": {"__initial__"},
        "partial-history-only": set(),
        "partial-unreadable-last": None,
    }
    wanted = plans.get(plan, None)
    for step_ordinal, (name, step_id, duration, entry) in enumerate(durations):
        if plan == "partial-body-only" and entry.get("role") != "body":
            continue
        count = 1 if plan in {"partial-initial-only"} else 3
        if plan == "partial-history-only":
            count = 0
        span = duration
        # A Closing failure in the lifecycle evidence is saved at local 0.60 s;
        # the same case also exists for the two-step topology.
        if plan == "partial-closing" and entry.get("role") == "door":
            span = min(duration, 0.6)
        for frame_index in range(count):
            fraction = 0.0 if count <= 1 else frame_index / (count - 1)
            local = span * fraction
            displacements = {}
            for instance in instances:
                rows = []
                for node in instance["nodes"]:
                    dy = (
                        (0.6 * local * (1 if instance["name"] == "PANEL-1" else 0.5))
                        if step_ordinal >= 0
                        else 0.0
                    )
                    rows.append([node[0], 0.0, dy, 0.0])
                displacements[instance["name"]] = rows
            payload = _frame(
                displacements,
                total + local,
                name,
                step_id,
                ordinal,
                step_ordinal,
                frame_index,
                frame_index + 1,
            )
            payload["local_time"] = local
            payload["total_time"] = total + local
            save_frame(
                directory,
                result,
                payload,
            )
            ordinal += 1
        # History samples live at their own times and stay available even when
        # the field frames were truncated.
        travel = {"U1": {}, "U2": {}, "RF1": {}, "RF2": {}}
        for sample in range(3):
            t = duration * sample / 2
            travel["U1"][t] = 0.0
            travel["U2"][t] = -0.6 * t
            travel["RF1"][t] = 0.0
            travel["RF2"][t] = 2.0 * t
        history.extend(
            align_histories(
                travel,
                metadata,
                total,
                step=name,
                step_id=step_id,
                motion=entry,
            )
        )
        total += duration
    result["history"] = history
    result["solver_outcome"] = context.get("solver_outcome", "Failed")
    result["failure_reason"] = context.get("failure_reason", "")
    if plan == "partial-unreadable-last" and result["frames"]:
        removed = result["frames"].pop()
        (directory / ".extract-staging" / removed["file"]).unlink(missing_ok=True)
        result["skipped_frames"] = [
            {
                "step": removed.get("step"),
                "step_id": removed.get("step_id"),
                "frame_ordinal": removed.get("frame_ordinal"),
                "reason": "manufactured unreadable trailing frame",
            }
        ]
        result["gaps"] = [
            {
                "kind": "unreadable_frame",
                "frame_ordinal": removed.get("frame_ordinal"),
                "reason": "manufactured unreadable trailing frame",
            }
        ]
    if plan == "partial-history-only":
        result["frames"] = []
    finish(directory, result, availability="partial", require_frames=False)
