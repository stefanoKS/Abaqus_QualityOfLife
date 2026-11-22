"""One revision-specific readiness calculation for every surface.

The workflow sidebar, the workspace footer, Review / Run and the HTTP API all ask
this module the same question: *what is the next action that actually unblocks
this revision, and why?* Each finding carries a stable reason code, the owning
stage, the affected action and the artifact it refers to, so the browser can
translate the explanation without guessing from prose.

This is deliberately conservative. A previous mesh never makes a changed
revision ready, an empty drawing is never Import-complete, and a deck prepared
against a superseded mesh or fixture is reported as stale rather than usable.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from packages.engineering.model import Project
from services import store

# Severity vocabulary: only ``blocker`` prevents the next engineering action.
BLOCKER = "blocker"
WARNING = "warning"
INFO = "info"

STAGE_ACTION = {
    "import": "import",
    "components": "assign_roles",
    "materials": "assign_material",
    "mesh": "generate_mesh",
    "mounting": "select_fixed_nodes",
    "contact": "review_contact",
    "motion": "review_motion",
    "review": "prepare_or_submit",
    "results": "open_results",
}


def finding(code, stage, severity, params=None, artifact=None):
    return {
        "code": code,
        "stage": stage,
        "action": STAGE_ACTION.get(stage, stage),
        "severity": severity,
        "artifact": artifact,
        "params": params or {},
    }


def _iso(seconds):
    if not seconds:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def _mesh_state(project, setup, jobs):
    compat = None
    try:
        from packages import engineering

        compat = engineering.mesh_compat(setup)
    except (ValueError, KeyError):
        compat = None
    compat_jobs = [j for j in jobs if j.get("mode") == "MESH" and j.get("mesh_compat") == compat]
    completed = [j for j in compat_jobs if j["status"] == "Completed"]
    active = completed[0] if completed else None
    latest = compat_jobs[0] if compat_jobs else None
    return active, latest, compat


def evaluate(rid):
    """Return the readiness document for one revision."""
    revision = store.revision(rid)
    setup = Project.model_validate(revision["setup"])
    project = revision["project"]
    heads = store.projects()
    head_row = next((p for p in heads if p["id"] == project), None)
    head_id = head_row["revision"] if head_row else str(rid)
    is_head = head_id == str(rid)
    jobs = [j for j in store.jobs(("MESH", "DECK", "ABAQUS")) if j["project"] == project]
    mesh_jobs = [j for j in jobs if j["mode"] == "MESH"]
    deck_jobs = [j for j in jobs if j["mode"] == "DECK" and j["revision"] == str(rid)]
    run_jobs = [j for j in jobs if j["mode"] == "ABAQUS" and j["revision"] == str(rid)]
    findings = []

    if setup.is_empty:
        findings.append(finding("drawing.missing", "import", BLOCKER))
        return _document(revision, setup, findings, {}, None, head_id)

    if setup.dimension != "2D":
        findings.append(finding("drawing.extrusion_preview", "import", BLOCKER))

    source = setup.source
    if source.kind in {"dxf", "dwg"} and not source.digest:
        findings.append(finding("drawing.digest_missing", "import", WARNING))

    unassigned_components = [c.id for c in setup.components if c.role == "unassigned"]
    if unassigned_components:
        findings.append(
            finding(
                "components.unassigned",
                "components",
                BLOCKER,
                {"count": len(unassigned_components), "components": unassigned_components[:8]},
                artifact="revision:" + str(rid),
            )
        )
    panel_roles = {c.role for c in setup.components}
    if "moving_panel" not in panel_roles:
        findings.append(finding("components.no_moving_panel", "components", BLOCKER))
    if "seal" not in panel_roles:
        findings.append(finding("components.no_seal", "components", BLOCKER))
    if setup.analysis.mode == "body_then_door" and "vehicle_body" not in panel_roles:
        findings.append(finding("components.no_moving_body", "components", BLOCKER))

    regions = [f for f in setup.faces if not f.cavity]
    unassigned_regions = [f.id for f in regions if not f.material]
    if unassigned_regions:
        findings.append(
            finding(
                "material.unassigned",
                "materials",
                BLOCKER,
                {"count": len(unassigned_regions), "regions": unassigned_regions[:8]},
                artifact="revision:" + str(rid),
            )
        )
    if not setup.materials:
        findings.append(finding("material.none", "materials", BLOCKER))

    active, latest, compat = _mesh_state(project, setup, mesh_jobs)
    fixture = store.fixture(active["id"]) if active else None
    fixture_count = len(fixture["labels"]) if fixture else 0

    if active is None:
        findings.append(finding("mesh.missing", "mesh", BLOCKER))
        if latest and latest["status"] in {"Failed", "Cancelled"}:
            findings.append(
                finding(
                    "mesh.latest_attempt_failed",
                    "mesh",
                    WARNING,
                    {"status": latest["status"], "job": latest["id"]},
                    artifact="job:" + latest["id"],
                )
            )
    elif latest and latest["id"] != active["id"] and latest["status"] in {"Failed", "Cancelled"}:
        findings.append(
            finding(
                "mesh.previous_attempt_failed",
                "mesh",
                WARNING,
                {"status": latest["status"], "job": latest["id"], "mesh": active["id"]},
                artifact="job:" + latest["id"],
            )
        )

    if active and fixture_count == 0:
        findings.append(finding("mounting.missing", "mounting", BLOCKER))
    if fixture_count:
        findings.append(
            finding(
                "mounting.reviewed",
                "mounting",
                INFO,
                {"count": fixture_count, "mesh": active["id"]},
                artifact="mesh:" + active["id"],
            )
        )

    if setup.motion.travel >= 0:
        findings.append(finding("motion.travel_not_closing", "motion", BLOCKER))
    if setup.analysis.mode == "body_then_door" and setup.motion.body.travel == 0:
        findings.append(finding("motion.body_travel_missing", "motion", BLOCKER))

    deck = next((j for j in deck_jobs if j["status"] == "Completed"), None)
    if deck is None:
        findings.append(finding("deck.missing", "review", BLOCKER))
    else:
        if deck.get("mesh") and active and deck["mesh"] != active["id"]:
            findings.append(
                finding(
                    "deck.superseded_mesh",
                    "review",
                    BLOCKER,
                    {"deck": deck["id"], "mesh": deck["mesh"], "active": active["id"]},
                    artifact="job:" + deck["id"],
                )
            )
        if deck.get("fixture_hash") and fixture and deck["fixture_hash"] != fixture["hash"]:
            findings.append(
                finding(
                    "deck.stale_fixture",
                    "review",
                    BLOCKER,
                    {"deck": deck["id"]},
                    artifact="job:" + deck["id"],
                )
            )

    latest_run = run_jobs[0] if run_jobs else None
    if latest_run and latest_run["status"] in {"Queued", "Running", "Cancel requested"}:
        findings.append(
            finding(
                "run.active",
                "review",
                INFO,
                {"job": latest_run["id"], "status": latest_run["status"]},
                artifact="job:" + latest_run["id"],
            )
        )
    elif latest_run and latest_run["status"] == "Failed":
        findings.append(
            finding(
                "run.failed",
                "review",
                WARNING,
                {"job": latest_run["id"]},
                artifact="job:" + latest_run["id"],
            )
        )

    if not is_head:
        findings.append(
            finding(
                "revision.historical",
                "review",
                WARNING,
                {"number": revision["number"]},
                artifact="revision:" + str(rid),
            )
        )

    counts = {
        "components": len(setup.components),
        "unassigned_components": len(unassigned_components),
        "regions": len(regions),
        "unassigned_regions": len(unassigned_regions),
        "materials": len(setup.materials),
        "mesh": active["id"] if active else None,
        "mesh_digest": active.get("mesh_digest") if active else None,
        "fixture_count": fixture_count,
        "fixture_hash": fixture["hash"] if fixture else None,
        "deck": deck["id"] if deck else None,
        "run": latest_run["id"] if latest_run else None,
    }
    return _document(revision, setup, findings, counts, latest_run, head_id)


def _document(revision, setup, findings, counts, latest_run, head_id):
    blockers = [f for f in findings if f["severity"] == BLOCKER]
    if setup.is_empty:
        state = "empty"
    elif latest_run and latest_run["status"] in {"Queued", "Running", "Cancel requested"}:
        state = "running"
    elif blockers:
        state = "blocked"
    elif latest_run and latest_run["status"] == "Failed":
        state = "failed"
    else:
        state = "ready"
    first = blockers[0] if blockers else None
    return {
        "revision": str(revision["id"]),
        "project": revision["project"],
        "number": revision["number"],
        "head": head_id,
        "state": state,
        "findings": findings,
        "first_blocker": first,
        "next_action": (
            {"stage": first["stage"], "action": first["action"]} if first else None
        ),
        "counts": counts,
        "updated": _iso(time.time()),
        "setup_updated": _iso(revision["created"]),
    }


def persisted_summary(document):
    """Compact form embedded in job/Revision payloads where a full list is noise."""
    return {
        "state": document["state"],
        "first_code": (document["first_blocker"] or {}).get("code"),
        "next_stage": (document["next_action"] or {}).get("stage"),
        "blocker_count": sum(1 for f in document["findings"] if f["severity"] == BLOCKER),
    }
