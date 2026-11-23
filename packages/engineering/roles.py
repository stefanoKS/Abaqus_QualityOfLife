"""Role-derived step sequence for new editable setups.

The step sequence is a property of the engineering roles the user assigned, not
a separate manual switch. One valid seal assembly plus a door panel closes; a
single participating body panel seats first and then the door closes. Roles are
counted by component: a rigid panel participates through its profile edges, a
seal assembly participates through at least one solid (non-cavity) region, and
partition children or multiple material regions still belong to one seal.

Ambiguous assignments never silently drop a body: they keep the legacy door-only
step sequence and return a finding code that readiness and the browser can show.
Historical revisions keep their stored mode; this module is only applied to
new-format setups.
"""

from typing import Iterable, Mapping

SEAL = "seal"
DOOR = "moving_panel"
BODY = "vehicle_body"
UNASSIGNED = "unassigned"

BODY_THEN_DOOR = "body_then_door"
DOOR_ONLY = "door_only"


def _value(item, name, default=None):
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _id(item):
    return _value(item, "id")


def _role(item):
    return _value(item, "role")


def counts(components: Iterable, edges: Iterable, faces: Iterable) -> dict[str, int]:
    """Count participating components per role.

    ``edges`` and ``faces`` are the project's owned geometry. A component with no
    geometry at all is not participating yet; a seal without a solid region is
    not a valid seal assembly.
    """
    curved = {_value(edge, "component") for edge in edges}
    solid = {_value(face, "component") for face in faces if not _value(face, "cavity", False)}
    participating = curved | solid
    result = {SEAL: 0, DOOR: 0, BODY: 0, UNASSIGNED: 0}
    for component in components:
        identifier = _id(component)
        role = _role(component)
        if role not in result:
            continue
        if role == SEAL:
            if identifier in solid:
                result[SEAL] += 1
        elif identifier in participating:
            result[role] += 1
    return result


def findings(components: Iterable, edges: Iterable, faces: Iterable) -> list[dict]:
    """Actionable, code-bearing role findings for readiness and the browser."""
    tally = counts(components, edges, faces)
    result: list[dict] = []
    if tally[UNASSIGNED]:
        result.append({"code": "components.unassigned", "count": tally[UNASSIGNED]})
    if tally[SEAL] == 0:
        result.append({"code": "components.no_seal", "count": 0})
    if tally[DOOR] == 0:
        result.append({"code": "components.no_moving_panel", "count": 0})
    elif tally[DOOR] > 1:
        result.append({"code": "components.duplicate_moving_panel", "count": tally[DOOR]})
    if tally[BODY] > 1:
        result.append({"code": "components.duplicate_moving_body", "count": tally[BODY]})
    return result


def derive_mode(components: Iterable, edges: Iterable, faces: Iterable) -> str:
    """The step sequence implied by the participating roles.

    Only a complete, unambiguous assignment enables the two-step template. Every
    other combination keeps the legacy door-only sequence, so an incomplete or
    duplicated assignment is actionable rather than a partially built analysis.
    """
    tally = counts(components, edges, faces)
    if (
        tally[SEAL] >= 1
        and tally[DOOR] == 1
        and tally[BODY] == 1
        and tally[UNASSIGNED] == 0
    ):
        return BODY_THEN_DOOR
    return DOOR_ONLY


def step_plan(components: Iterable, edges: Iterable, faces: Iterable) -> dict:
    """A readable summary of the derived sequence (mode, steps, findings)."""
    mode = derive_mode(components, edges, faces)
    steps = (
        [
            {"id": "bodyseating", "name": "Body seating", "role": "body"},
            {"id": "closing", "name": "Closing", "role": "door"},
        ]
        if mode == BODY_THEN_DOOR
        else [{"id": "closing", "name": "Closing", "role": "door"}]
    )
    return {
        "mode": mode,
        "steps": steps,
        "counts": counts(components, edges, faces),
        "findings": findings(components, edges, faces),
    }
