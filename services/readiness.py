"""One revision-specific readiness calculation for every surface.

The workflow sidebar, the workspace action group and the HTTP API all ask this
module the same question: *what is the next action that actually unblocks this
revision, and why?* Each finding carries a stable reason code, the owning
stage, the affected actions and the artifact it refers to, so the browser can
translate the explanation without guessing from prose.

The decision is action-specific. ``can_prepare`` covers only engineering setup
inputs (roles, materials, mesh artifact, reviewed fixture, motion, contact).
A missing or stale deck never blocks preparation. ``can_submit`` adds the
current prepared deck. Geometry warnings such as ``motion.path_misses_seal``
stay warnings under the existing policy and never disable an action.

This is deliberately conservative. A previous mesh never makes a changed
revision ready, an empty drawing is never Import-complete, and a deck prepared
against a superseded mesh or fixture is reported as stale rather than usable.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from packages.engineering.model import Project
from packages.engineering.roles import findings as role_findings
from packages.engineering.roles import step_plan
from services import store

# Severity vocabulary: only ``blocker`` prevents an action.
BLOCKER = "blocker"
WARNING = "warning"
INFO = "info"

# Stable stage identities shared with the browser. ``action`` owns Prepare and
# Submit; it is not a navigation stage any more.
STAGE_ACTION = {
    "import": "import",
    "components": "assign_roles",
    "materials": "assign_material",
    "mesh": "generate_mesh",
    "mounting": "select_fixed_nodes",
    "contact": "review_contact",
    "motion": "review_motion",
    "action": "prepare_or_submit",
    "results": "open_results",
}

ACTION_STAGES = {"import", "components", "materials", "mesh", "mounting", "contact", "motion"}

# A clearance rejection is a motion defect: the deck writer refuses the same
# condition, so readiness names it before the engineer tries to prepare a deck.
CLEARANCE_FINDINGS = {
    "no_x_overlap": "motion.no_x_overlap",
    "side_ambiguous": "motion.side_ambiguous",
    "initial_penetration": "motion.initial_penetration",
    "motion_away": "motion.direction_away",
    "unsupported_geometry": "motion.unsupported_geometry",
}


def finding(code, stage, severity, params=None, artifact=None, actions=None):
    if actions is None:
        if severity != BLOCKER:
            actions = []
        elif stage == "action":
            actions = ["submit"]
        else:
            actions = ["prepare", "submit"]
    return {
        "code": code,
        "stage": stage,
        "action": STAGE_ACTION.get(stage, stage),
        "severity": severity,
        "artifact": artifact,
        "params": params or {},
        "actions": list(actions),
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


def _motion_issues(setup):
    """Validate the stored effective motion under its own schema policy.

    Version 4 is stroke + direction angle; a positive delta-Y is valid when the
    measured geometry permits it. Only a historical version uses its signed
    travel field, and even then the sign is a geometry question for the deck
    writer, not an unconditional readiness rejection.
    """
    issues = []
    v4 = setup.schema_version >= 4

    def check(motion, label):
        try:
            duration = float(motion.duration)
            if not duration > 0:
                raise ValueError("duration")
            if v4:
                stroke = float(motion.stroke)
                angle = float(motion.angle)
                if not (stroke >= 0 and stroke < float("inf")):
                    raise ValueError("stroke")
                if not (abs(angle) <= 360):
                    raise ValueError("angle")
            else:
                travel = float(motion.travel)
                if not abs(travel) <= 10000:
                    raise ValueError("travel")
        except (TypeError, ValueError):
            issues.append(
                finding(
                    "motion.invalid",
                    "motion",
                    BLOCKER,
                    {"label": label},
                    artifact="revision",
                )
            )

    check(setup.motion, "door")
    if setup.analysis.mode == "body_then_door":
        check(setup.motion.body, "body")
    return issues


def _assembly(active, setup, findings):
    """Measured door/body clearance for the Motion diagnosis.

    Returns ``None`` before a compatible mesh exists. A real geometric
    rejection becomes a motion blocker carrying the same stable code the deck
    writer raises, so the browser explains the condition before an engineer
    tries to prepare a deck that would be refused.
    """
    if active is None:
        return None
    import json

    from integrations.abaqus.deck import ClearanceError, assembly_assessment

    try:
        mesh = json.loads(
            (store.job_dir(active["id"]) / "mesh.json").read_text(encoding="utf-8")
        )
        result = assembly_assessment(setup, mesh)
        # A prescribed path that never meets the seal is a legitimate setup but
        # worth an explicit, non-blocking explanation: it must not be mistaken
        # for measured contact.
        for role in ("door", "body"):
            part = result.get(role)
            if (
                part
                and not part.get("reaches_initial_gap")
                and part.get("path") in {"missed", "approaching"}
            ):
                findings.append(
                    finding(
                        "motion.path_misses_seal",
                        "motion",
                        WARNING,
                        {
                            "role": role,
                            "closest_mm": part.get("closest_after_mm"),
                            "stroke_mm": part.get("stroke_mm"),
                        },
                        artifact="mesh:" + active["id"],
                    )
                )
        return result
    except ClearanceError as exc:
        findings.append(
            finding(
                CLEARANCE_FINDINGS.get(exc.code, "motion.unsupported_geometry"),
                "motion",
                BLOCKER,
                dict(exc.details),
                artifact="mesh:" + active["id"],
            )
        )
        return {
            "door": None,
            "body": None,
            "code": exc.code,
            "error": str(exc),
            "details": dict(exc.details),
        }
    except (OSError, ValueError, KeyError) as exc:
        return {"door": None, "body": None, "error": str(exc)}


def evaluate(rid):
    """Return the readiness document for one revision."""
    revision = store.revision(rid)
    setup = Project.model_validate(revision["setup"])
    project = revision["project"]
    heads = store.projects()
    head_row = next((p for p in heads if p["id"] == project), None)
    head_id = head_row["revision"] if head_row else str(rid)
    is_head = head_id == str(rid)
    archived = bool(revision.get("archived") or revision.get("group_archived"))
    jobs = [j for j in store.jobs(("MESH", "DECK", "ABAQUS")) if j["project"] == project]
    mesh_jobs = [j for j in jobs if j["mode"] == "MESH"]
    deck_jobs = [j for j in jobs if j["mode"] == "DECK" and j["revision"] == str(rid)]
    run_jobs = [j for j in jobs if j["mode"] == "ABAQUS" and j["revision"] == str(rid)]
    findings = []

    if setup.is_empty:
        findings.append(finding("drawing.missing", "import", BLOCKER))
        return _document(
            revision, setup, findings, {}, None, head_id, None, archived=archived
        )

    if setup.dimension != "2D":
        findings.append(finding("drawing.extrusion_preview", "import", BLOCKER))

    source = setup.source
    unassigned_components = [c.id for c in setup.components if c.role == "unassigned"]
    if source.kind in {"dxf", "dwg"} and not source.digest:
        findings.append(finding("drawing.digest_missing", "import", WARNING))

    # An open-only drawing is a valid, inspectable model (curves are selectable
    # and saveable) but it has no closed structural seal. Name the condition
    # before any other stage so the engineer knows simulation is blocked by
    # geometry, not by a missing role or material.
    if source.kind in {"dxf", "dwg"} and not setup.faces:
        face_components = {face.component for face in setup.faces}
        open_profiles = [
            component
            for component in setup.components
            if component.id not in face_components
            and any(edge.component == component.id for edge in setup.edges)
        ]
        findings.append(
            finding(
                "drawing.no_closed_region",
                "import",
                BLOCKER,
                {"open_profiles": len(open_profiles), "curves": len(setup.edges)},
                artifact="revision:" + str(rid),
            )
        )
        # Simulation is blocked by the drawing itself. Returning here avoids a
        # cascade of misleading downstream blockers (a missing mesh, fixture or
        # deck) that cannot be repaired while the seal is still open.
        counts = {
            "components": len(setup.components),
            "unassigned_components": len(unassigned_components),
            "regions": 0,
            "unassigned_regions": 0,
            "materials": len(setup.materials),
            "mesh": None,
            "mesh_digest": None,
            "mesh_compat": None,
            "mesh_artifact": None,
            "fixture_count": 0,
            "fixture_hash": None,
            "deck": None,
            "deck_status": None,
            "deck_mesh": None,
            "deck_fixture_hash": None,
            "run": None,
            "revision": str(rid),
            "head": head_id,
            "archived": archived,
            "head_revision": is_head,
        }
        return _document(
            revision,
            setup,
            findings,
            counts,
            None,
            head_id,
            None,
            archived=archived,
        )

    unassigned_components = [c.id for c in setup.components if c.role == "unassigned"]
    for entry in role_findings(setup.components, setup.edges, setup.faces):
        code = entry["code"]
        severity = BLOCKER
        params = {"count": entry.get("count", 0)}
        if code == "components.unassigned":
            params["components"] = unassigned_components[:8]
        findings.append(
            finding(code, "components", severity, params, artifact="revision:" + str(rid))
        )

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
    # A registered CAE record may legitimately omit its density or describe only
    # thermal behaviour. Registration keeps it; a *new run* needs both, and the
    # missing input is named instead of being guessed.
    missing_density = [
        material.name
        for material in setup.materials
        if material.density is None or material.density <= 0
    ]
    if missing_density:
        findings.append(
            finding(
                "material.missing_density",
                "materials",
                BLOCKER,
                {"materials": missing_density[:8], "count": len(missing_density)},
                artifact="revision:" + str(rid),
            )
        )
    no_law = [material.name for material in setup.materials if not material.structural_law]
    if no_law:
        findings.append(
            finding(
                "material.no_structural_law",
                "materials",
                BLOCKER,
                {"materials": no_law[:8], "count": len(no_law)},
                artifact="revision:" + str(rid),
            )
        )
    unregistered = [
        material.name for material in setup.materials if not material.library_id
    ]
    if unregistered:
        # Legacy model-local cards stay usable in this phase; the finding is a
        # warning so the engineer knows the card is not a pinned library version.
        findings.append(
            finding(
                "material.unregistered",
                "materials",
                WARNING,
                {"materials": unregistered[:8], "count": len(unregistered)},
                artifact="revision:" + str(rid),
            )
        )

    findings.extend(_motion_issues(setup))

    active, latest, compat = _mesh_state(project, setup, mesh_jobs)
    artifact = (
        store.mesh_artifact_state(active["id"], active.get("mesh_digest")) if active else None
    )
    if active is not None and artifact != "ok":
        findings.append(
            finding(
                "mesh.artifact_missing" if artifact == "missing" else "mesh.artifact_corrupt",
                "mesh",
                BLOCKER,
                {"job": active["id"]},
                artifact="mesh:" + active["id"],
            )
        )
    mesh_usable = active is not None and artifact == "ok"
    fixture = store.fixture(active["id"]) if mesh_usable else None
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

    if mesh_usable and fixture_count == 0:
        findings.append(finding("mounting.missing", "mounting", BLOCKER))
    if mesh_usable and fixture_count:
        findings.append(
            finding(
                "mounting.reviewed",
                "mounting",
                INFO,
                {"count": fixture_count, "mesh": active["id"]},
                artifact="mesh:" + active["id"],
            )
        )

    # Motion is measured after the mesh exists: side, clearance and direction
    # depend on the assembled geometry, and a zero travel is a valid hold.
    assembly = _assembly(active if mesh_usable else None, setup, findings)

    # The newest deck for this revision is the only submittable one. Deck state
    # belongs to Submit; it never disables Prepare.
    latest_deck = deck_jobs[0] if deck_jobs else None
    current_deck = None
    if latest_deck is None:
        findings.append(
            finding(
                "deck.missing",
                "action",
                BLOCKER,
                actions=["submit"],
            )
        )
    elif latest_deck["status"] in {"Queued", "Running", "Cancel requested"}:
        findings.append(
            finding(
                "deck.preparing",
                "action",
                BLOCKER,
                {"job": latest_deck["id"], "status": latest_deck["status"]},
                artifact="job:" + latest_deck["id"],
                actions=["submit"],
            )
        )
    elif latest_deck["status"] != "Completed":
        findings.append(
            finding(
                "deck.failed",
                "action",
                BLOCKER,
                {"job": latest_deck["id"], "status": latest_deck["status"]},
                artifact="job:" + latest_deck["id"],
                actions=["submit"],
            )
        )
    else:
        current_deck = latest_deck
        if current_deck.get("mesh") and active and current_deck["mesh"] != active["id"]:
            findings.append(
                finding(
                    "deck.superseded_mesh",
                    "action",
                    BLOCKER,
                    {
                        "deck": current_deck["id"],
                        "mesh": current_deck["mesh"],
                        "active": active["id"],
                    },
                    artifact="job:" + current_deck["id"],
                    actions=["submit"],
                )
            )
        if current_deck.get("fixture_hash") and fixture and current_deck["fixture_hash"] != fixture["hash"]:
            findings.append(
                finding(
                    "deck.stale_fixture",
                    "action",
                    BLOCKER,
                    {"deck": current_deck["id"]},
                    artifact="job:" + current_deck["id"],
                    actions=["submit"],
                )
            )

    latest_run = run_jobs[0] if run_jobs else None
    if latest_run and latest_run["status"] in {"Queued", "Running", "Cancel requested"}:
        findings.append(
            finding(
                "run.active",
                "action",
                INFO,
                {"job": latest_run["id"], "status": latest_run["status"]},
                artifact="job:" + latest_run["id"],
            )
        )
    elif latest_run and latest_run["status"] == "Failed":
        findings.append(
            finding(
                "run.failed",
                "action",
                WARNING,
                {"job": latest_run["id"]},
                artifact="job:" + latest_run["id"],
            )
        )

    if not is_head:
        findings.append(
            finding(
                "revision.historical",
                "action",
                WARNING,
                {"number": revision["number"]},
                artifact="revision:" + str(rid),
                actions=["prepare", "submit"],
            )
        )
    if archived:
        findings.append(
            finding(
                "project.archived",
                "action",
                BLOCKER,
                {},
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
        "mesh_compat": compat,
        "mesh_artifact": artifact,
        "fixture_count": fixture_count,
        "fixture_hash": fixture["hash"] if fixture else None,
        "deck": current_deck["id"] if current_deck else None,
        "deck_status": latest_deck["status"] if latest_deck else None,
        "deck_mesh": current_deck.get("mesh") if current_deck else None,
        "deck_fixture_hash": current_deck.get("fixture_hash") if current_deck else None,
        "run": latest_run["id"] if latest_run else None,
        "revision": str(rid),
        "head": head_id,
        "archived": archived,
        "head_revision": is_head,
    }
    return _document(
        revision,
        setup,
        findings,
        counts,
        latest_run,
        head_id,
        assembly,
        archived=archived,
    )


def _stage_states(setup, findings, fixture_count, mesh_usable, geometry_ready, can_prepare,
                  can_submit, latest_run):
    """Sidebar badges from the same revision snapshot as the actions."""
    # Missing-but-actionable inputs read as "incomplete"; the padlock is
    # reserved for a genuine read-only restriction (for example the unsupported
    # 3D extrusion preview). Every role, material, mesh, mounting and motion
    # defect is repaired by editing the stage that owns it, so it must never be
    # rendered as a lock: that hid an editable role selector behind a padlock.
    incomplete_codes = {
        "drawing.missing",
        "drawing.no_closed_region",
        "mesh.missing",
        "mesh.artifact_missing",
        "mesh.artifact_corrupt",
        "mounting.missing",
        "mounting.awaiting_mesh",
        "material.unassigned",
        "material.none",
        "material.missing_density",
        "material.no_structural_law",
        "motion.invalid",
        "motion.initial_penetration",
        "motion.direction_away",
        "motion.no_x_overlap",
        "motion.side_ambiguous",
        "motion.unsupported_geometry",
        "components.roles",
        "components.unassigned",
        "components.no_seal",
        "components.no_moving_panel",
        "components.duplicate_moving_panel",
        "components.duplicate_moving_body",
        "deck.missing",
    }
    by_stage = {}
    for item in findings:
        if item["severity"] == BLOCKER:
            by_stage.setdefault(item["stage"], item)
    warning = {}
    for item in findings:
        if item["severity"] == WARNING:
            warning.setdefault(item["stage"], item)

    def state(stage, complete, incomplete_code=None):
        blocked = by_stage.get(stage)
        if blocked:
            return {
                "state": "incomplete" if blocked["code"] in incomplete_codes else "blocked",
                "code": blocked["code"],
            }
        if complete:
            entry = {"state": "complete"}
            if stage in warning:
                entry["warning"] = warning[stage]["code"]
            return entry
        return {"state": "incomplete", "code": incomplete_code}

    states = {
        # Import owns the deferred 3D extrusion: that is the one genuine,
        # read-only restriction in this phase, so it is the one padlock.
        "import": (
            {"state": "incomplete", "code": "drawing.missing"}
            if setup.is_empty
            else {"state": "blocked", "code": "drawing.extrusion_preview"}
            if setup.dimension != "2D"
            else {"state": "incomplete", "code": "drawing.no_closed_region"}
            if not setup.faces
            else {"state": "complete"}
        ),
        "components": state("components", geometry_ready, "components.roles"),
        "materials": state(
            "materials",
            all(face.material for face in setup.faces if not face.cavity)
            and bool([face for face in setup.faces if not face.cavity]),
            "drawing.no_closed_region" if not setup.faces else "material.unassigned",
        ),
        # A mesh is always repairable in Mesh; a missing prerequisite is an
        # incomplete stage, never a read-only lock. The hint names the input that
        # actually unblocks meshing (a drawing, then roles).
        "mesh": state(
            "mesh",
            mesh_usable,
            "drawing.missing"
            if setup.is_empty
            else "drawing.no_closed_region"
            if not setup.faces
            else "components.roles"
            if not geometry_ready
            else "mesh.missing",
        ),
        "mounting": state(
            "mounting",
            fixture_count > 0,
            "mounting.awaiting_mesh" if not mesh_usable else "mounting.missing",
        ),
        "contact": state("contact", True, "contact.invalid"),
        "motion": state("motion", not by_stage.get("motion"), "motion.invalid"),
        "action": (
            {"state": "complete", "code": "action.submitReady"}
            if can_submit
            else {"state": "blocked", "code": "action.prepareRequired"}
            if not can_prepare
            else {"state": "incomplete", "code": "deck.missing"}
        ),
        "results": (
            {"state": "complete"}
            if latest_run and latest_run.get("status") == "Completed"
            else {"state": "incomplete", "code": "results.missing"}
        ),
    }
    return states


def _document(revision, setup, findings, counts, latest_run, head_id, assembly=None, *, archived=False):
    blockers = [f for f in findings if f["severity"] == BLOCKER]
    empty = setup.is_empty
    if empty:
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

    def actions_for(name):
        return [
            item
            for item in findings
            if item["severity"] == BLOCKER and name in item.get("actions", [])
        ]

    prepare_issues = actions_for("prepare")
    submit_issues = actions_for("submit")
    head = counts.get("head_revision", True) if counts else True
    dim2d = setup.dimension == "2D"
    can_prepare = bool(
        not empty
        and dim2d
        and head
        and not archived
        and not prepare_issues
    )
    can_submit = bool(can_prepare and not submit_issues)

    roles = [c.role for c in setup.components]
    geometry_ready = (
        bool(setup.faces)
        and bool(roles)
        and "unassigned" not in roles
        and roles.count("moving_panel") == 1
    )
    mesh_usable = (counts or {}).get("mesh_artifact") == "ok"
    fixture_count = (counts or {}).get("fixture_count", 0) or 0
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
        # Action-specific decisions: a missing deck blocks Submit only.
        "can_prepare": can_prepare,
        "can_submit": can_submit,
        "setup_issues": prepare_issues,
        "submit_issues": submit_issues,
        "actions": {
            "prepare": {"allowed": can_prepare, "issues": prepare_issues},
            "submit": {"allowed": can_submit, "issues": submit_issues},
        },
        "stage_states": _stage_states(
            setup,
            findings,
            fixture_count,
            mesh_usable,
            geometry_ready,
            can_prepare,
            can_submit,
            latest_run,
        ),
        # Measured assembly geometry; nothing here is solver evidence.
        "assembly": assembly,
        # The derived step sequence and role findings, so the browser shows the
        # same plan the server stores instead of a separate manual switch.
        "steps": step_plan(setup.components, setup.edges, setup.faces),
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
        "can_prepare": document.get("can_prepare", False),
        "can_submit": document.get("can_submit", False),
    }
