"""Supported 2-D vertical closing template. User strings never become INP keywords."""

from collections import defaultdict
from math import hypot, isfinite

from packages.engineering import fixture as fixtures
from shapely.affinity import translate

from packages.engineering import motion as motion_policy

ELEMENT_SIZES = {"CPS3": 3, "CPS4": 4, "CPS4R": 4, "R2D2": 2}

# mm. A profile closer than this counts as touching. Anything deeper into the
# seal is a genuine initial penetration and is rejected, never clamped.
CLEARANCE_TOLERANCE = 1e-7


class PreparationError(ValueError):
    """A deck-preparation rejection with one shared, typed explanation.

    ``code`` is stable and localized by the browser; ``stage`` names the
    workflow stage that owns the repair and ``role`` the engineering role
    (``door``/``body``/``seal``) when the condition belongs to one. ``details``
    carries measured quantities only, never prose the caller has to parse.

    Readiness and the deck worker both raise and catch this type, so the app
    cannot say "Ready to prepare" for geometry the writer will refuse.
    """

    def __init__(self, code, message, *, stage="action", role=None, **details):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.role = role
        # The browser localizes ``label`` (door/body) in the structured params.
        # A typed rejection with a role always carries it so no raw ``{label}``
        # placeholder can reach the interface.
        if role is not None:
            details.setdefault("label", role)
        self.details = details


class ClearanceError(PreparationError):
    """A geometric clearance/motion rejection, owned by the Motion stage."""

    def __init__(self, code, message, **details):
        super().__init__(
            code,
            message,
            stage="motion",
            role=details.get("label"),
            **details,
        )


def scalar(value):
    value = float(value)
    if not isfinite(value):
        raise ValueError("Input data must contain only finite numbers.")
    return format(value, ".15g")


def set_lines(keyword, labels):
    labels = sorted(set(labels))
    if not labels:
        raise ValueError("An empty mesh set cannot define a solver assignment.")
    return [keyword] + [", ".join(map(str, labels[i : i + 16])) for i in range(0, len(labels), 16)]


def panel_order(panel, nodes, role="moving_panel", label="moving panel"):
    """Follow one open R2D2 chain and return its elements in walk order.

    This function is deliberately *only* topological. A curved panel may turn
    back in X, contain vertical portions, or have two endpoints with the same X;
    none of those change which element comes next in a degree-two open chain.
    Contact-side orientation is a separate decision made against the measured
    seal geometry (``orient_toward``), never by rejecting a local X reversal.

    The walk starts at the endpoint with the largest ``(x, y, label)`` to keep
    the historical door/body element order for straight profiles. Because the
    station axis used by Results is derived from the assembled ODB connectivity
    (lexicographic-minimum endpoint), reversing these element pairs later never
    moves a reported station.
    """
    neighbors = defaultdict(list)
    seen_elements = {}
    for element in panel:
        try:
            a, b = element["nodes"]
        except (KeyError, TypeError, ValueError) as exc:
            raise PreparationError(
                "panel.malformed_profile",
                f"The {label} profile has an element without two nodes.",
                stage="components",
                role=role,
                element=element.get("id"),
            ) from exc
        if a == b:
            raise PreparationError(
                "panel.degenerate_profile",
                f"The {label} profile element {element['id']} has repeated nodes.",
                stage="components",
                role=role,
                element=element["id"],
            )
        if element["id"] in seen_elements:
            raise PreparationError(
                "panel.repeated_element",
                f"The {label} profile repeats element {element['id']}; every original "
                "element must appear exactly once.",
                stage="components",
                role=role,
                element=element["id"],
            )
        seen_elements[element["id"]] = element
        first, second = nodes.get(a), nodes.get(b)
        if first is None or second is None:
            raise PreparationError(
                "panel.missing_coordinates",
                f"The {label} profile element {element['id']} refers to a node "
                "without coordinates.",
                stage="components",
                role=role,
                element=element["id"],
            )
        length = hypot(second[0] - first[0], second[1] - first[1])
        if length <= CLEARANCE_TOLERANCE:
            raise PreparationError(
                "panel.degenerate_profile",
                f"The {label} profile element {element['id']} has zero length.",
                stage="components",
                role=role,
                element=element["id"],
            )
        neighbors[a].append((b, element))
        neighbors[b].append((a, element))

    if not neighbors:
        raise PreparationError(
            "panel.missing_profile",
            f"The {label} profile has no elements.",
            stage="components",
            role=role,
        )

    # Disconnected islands and branches are actual topology defects with a
    # different repair from a curved (but valid) chain.
    reached = set()
    components = 0
    for start in sorted(neighbors):
        if start in reached:
            continue
        components += 1
        stack = [start]
        reached.add(start)
        while stack:
            node = stack.pop()
            for neighbour, _ in neighbors[node]:
                if neighbour not in reached:
                    reached.add(neighbour)
                    stack.append(neighbour)
    if components > 1:
        raise PreparationError(
            "panel.disconnected_profile",
            f"The {label} profile contains {components} disconnected chains; the "
            "template needs one connected open profile.",
            stage="components",
            role=role,
            components=components,
        )
    branched = sorted(node for node, adjacent in neighbors.items() if len(adjacent) > 2)
    if branched:
        raise PreparationError(
            "panel.branched_profile",
            f"The {label} profile branches at node {branched[0]}; the template needs "
            "one open chain without branches.",
            stage="components",
            role=role,
            node=branched[0],
            count=len(branched),
        )
    ends = sorted(
        (node for node, adjacent in neighbors.items() if len(adjacent) == 1),
        key=lambda node: (nodes[node][0], nodes[node][1], node),
    )
    if len(ends) != 2:
        raise PreparationError(
            "panel.closed_profile",
            f"The {label} profile is closed; the template needs one open chain with "
            "two endpoints.",
            stage="components",
            role=role,
            endpoints=len(ends),
        )

    current = ends[-1]
    previous = None
    ordered = []
    visited = set()
    while True:
        next_segment = [(n, e) for n, e in neighbors[current] if n != previous]
        if not next_segment:
            break
        n, element = next_segment[0]
        if element["id"] in visited:
            raise PreparationError(
                "panel.repeated_element",
                f"The {label} profile revisits element {element['id']}; every original "
                "element must appear exactly once.",
                stage="components",
                role=role,
                element=element["id"],
            )
        visited.add(element["id"])
        ordered.append(dict(element, nodes=[current, n]))
        previous, current = current, n
    if len(ordered) != len(panel):
        raise PreparationError(
            "panel.disconnected_profile",
            f"The {label} profile has {len(panel) - len(ordered)} element(s) outside "
            "its open chain.",
            stage="components",
            role=role,
        )
    _reject_self_intersection(ordered, nodes, role, label)
    return ordered


def _reject_self_intersection(ordered, nodes, role, label):
    """A self-intersecting moving profile has no single physical contact side."""
    from shapely.geometry import LineString

    points = [nodes[ordered[0]["nodes"][0]]] + [nodes[element["nodes"][1]] for element in ordered]
    line = LineString([(float(point[0]), float(point[1])) for point in points])
    if not line.is_simple:
        raise PreparationError(
            "panel.self_intersecting_profile",
            f"The {label} profile intersects itself; the template cannot assign one "
            "contact side along a self-crossing chain.",
            stage="components",
            role=role,
        )


def surface_normal(nodes, element):
    """Unit normal of the SPOS side of one R2D2 segment.

    Abaqus puts SPOS on the local-2 side, i.e. 90 degrees counter-clockwise
    from the node-1-to-node-2 direction in the XY plane. The tests verify the
    generated connectivity against this definition rather than trusting the
    ``SPOS`` keyword.
    """
    a, b = nodes[element["nodes"][0]], nodes[element["nodes"][1]]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = hypot(dx, dy)
    if length <= 0:
        raise ValueError("A rigid segment has zero length.")
    return (-dy / length, dx / length)


def orient_for_contact(ordered, side):
    """Order R2D2 connectivity so the SPOS side of every segment faces the seal.

    ``panel_order`` walks right-to-left, so SPOS faces down: correct for a door
    above the seal, wrong for a body below it. Reversing both the element order
    and each node pair turns the chain around without changing its node set or
    its element set, and leaves the body's SPOS side facing up toward the seal.
    """
    if side == "above":
        return ordered
    if side == "below":
        return [
            dict(element, nodes=[element["nodes"][1], element["nodes"][0]])
            for element in reversed(ordered)
        ]
    raise ValueError("Unsupported rigid profile contact side: " + str(side))


def mesh_parts(project, mesh):
    nodes, ws, panel, _ = _mesh_parts(project, mesh)
    return nodes, ws, panel


def _mesh_parts(project, mesh):
    if project.dimension != "2D" or project.formulation != "plane_stress":
        raise PreparationError(
            "template.unsupported",
            "Only the 2D plane-stress closing template can generate a solver input.",
            stage="import",
        )
    if project.units != "N-mm-s-tonne":
        raise PreparationError(
            "template.units",
            "Confirm N-mm-s-tonne units before generating this input.",
            stage="import",
        )
    # Travel 0 is a valid hold; a nonzero travel is checked against the measured
    # contact side below, so the template never substitutes an epsilon motion.
    nodes = {n["id"]: n["xyz"] for n in mesh["nodes"]}
    if len(nodes) != len(mesh["nodes"]):
        raise PreparationError(
            "mesh.duplicate_node",
            "Duplicate mesh node label.",
            stage="mesh",
        )
    roles = {c.id: c.role for c in project.components}
    faces = {f.id: f for f in project.faces}
    materials = {m.id: m for m in project.materials}
    if sum(role == "moving_panel" for role in roles.values()) != 1:
        raise PreparationError(
            "components.one_moving_panel",
            "Select exactly one moving panel.",
            stage="components",
        )
    if any(role not in ("seal", "moving_panel", "vehicle_body") for role in roles.values()):
        raise PreparationError(
            "components.unsupported_role",
            "This solver template supports seal regions, one moving panel and an "
            "excluded body profile.",
            stage="components",
        )
    ws, panel, body = [], [], []
    element_ids = set()
    for e in mesh["elements"]:
        node_ids = e["nodes"]
        kind = e["type"]
        if (
            kind not in ELEMENT_SIZES
            or len(node_ids) != ELEMENT_SIZES[kind]
            or len(set(node_ids)) != len(node_ids)
            or any(n not in nodes for n in node_ids)
            or e["id"] in element_ids
            or e["id"] <= 0
            or min(node_ids) <= 0
        ):
            raise PreparationError(
                "mesh.invalid_element",
                "Unsupported element type, duplicate label, or invalid connectivity.",
                stage="mesh",
                element=e.get("id"),
            )
        element_ids.add(e["id"])
        if kind == "R2D2":
            role = roles.get(e["component"])
            if role == "moving_panel":
                panel.append(e)
            elif role == "vehicle_body" and project.analysis.mode == "body_then_door":
                body.append(e)
            else:
                raise PreparationError(
                    "components.rigid_role",
                    "A rigid edge must belong to an analysed rigid profile.",
                    stage="components",
                )
        else:
            face = faces.get(e["entity"])
            if (
                face is None
                or roles.get(e["component"]) != "seal"
                or face.component != e["component"]
            ):
                raise PreparationError(
                    "mesh.invalid_region",
                    "Every continuum element must refer to a CAD region of its seal.",
                    stage="mesh",
                    element=e["id"],
                )
            # Rubber quadrilaterals are always reduced integration. A forged or
            # legacy mesh that reaches the writer as CPS4 is rejected rather
            # than silently relabelled.
            material = materials.get(face.material) if face.material else None
            if (
                kind == "CPS4"
                and material is not None
                and material.model in ("hyperfoam_test", "neo_hookean")
            ):
                raise PreparationError(
                    "mesh.integration_rule",
                    f"Rubber quadrilateral element {e['id']} is CPS4; rubber uses "
                    "reduced integration (CPS4R). Regenerate the mesh.",
                    stage="mesh",
                    element=e["id"],
                )
            if (
                kind == "CPS4R"
                and material is not None
                and getattr(material, "family", "polymer") == "metal"
            ):
                raise PreparationError(
                    "mesh.integration_rule",
                    f"Metal quadrilateral element {e['id']} is CPS4R; deformable metal uses "
                    "full integration (CPS4). Regenerate the mesh.",
                    stage="mesh",
                    element=e["id"],
                )
            points = [nodes[n] for n in node_ids]
            for i, point in enumerate(points):
                prev, nxt = points[i - 1], points[(i + 1) % len(points)]
                cross = (point[0] - prev[0]) * (nxt[1] - point[1]) - (point[1] - prev[1]) * (
                    nxt[0] - point[0]
                )
                if not isfinite(cross) or cross <= 0:
                    raise PreparationError(
                        "mesh.inverted_element",
                        "A seal element has inverted or degenerate connectivity.",
                        stage="mesh",
                        element=e["id"],
                    )
            ws.append(e)
    if not ws or not panel:
        raise PreparationError(
            "mesh.missing_part",
            "Both a deformable seal mesh and a moving rigid profile are required.",
            stage="mesh",
        )
    if project.analysis.mode == "body_then_door" and not body:
        raise PreparationError(
            "components.no_moving_body",
            "Body-then-door analysis needs a meshed moving body profile.",
            stage="components",
            role="body",
        )
    return (
        nodes,
        ws,
        panel_order(panel, nodes, role="door", label="door"),
        panel_order(body, nodes, role="body", label="body") if body else [],
    )


def exterior(ws):
    sides = defaultdict(list)
    for e in ws:
        for i, n in enumerate(e["nodes"]):
            side = tuple(sorted((n, e["nodes"][(i + 1) % len(e["nodes"])])))
            sides[side].append((e["id"], i + 1))
    if any(len(entries) > 2 for entries in sides.values()):
        raise ValueError("Non-manifold seal mesh.")
    return {side: entries[0] for side, entries in sides.items() if len(entries) == 1}


def _segments(nodes, pairs):
    """Piecewise-linear segments as ``(x0, y0, x1, y1)`` with ``x0 <= x1``."""
    segments = []
    for first, second in pairs:
        a, b = nodes[first], nodes[second]
        x0, y0, x1, y1 = float(a[0]), float(a[1]), float(b[0]), float(b[1])
        if x0 > x1:
            x0, y0, x1, y1 = x1, y1, x0, y0
        segments.append((x0, y0, x1, y1))
    segments.sort()
    return segments


def _boundary_segments(nodes, boundary):
    """Exterior seal sides as left-to-right segments on the assembled mesh."""
    return _segments(nodes, list(boundary))


def _profile_segments(nodes, elements):
    """A rigid profile's FE surface as left-to-right segments."""
    return _segments(nodes, [element["nodes"] for element in elements])


def _height(segment, x, choose):
    """Y of one segment at ``x``; a vertical segment yields its extreme Y.

    A vertical seal side is a Y interval at a single X. The nearest point for a
    panel above is the top of that interval, so ``choose`` selects ``max`` for
    the minimum separation and ``min`` for the maximum.
    """
    x0, y0, x1, y1 = segment
    if x1 - x0 <= CLEARANCE_TOLERANCE:
        return choose(y0, y1)
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _separation(profile, seal, label):
    """Extremes of ``profile_y - seal_y`` over the profiles' shared X range.

    ``minimum`` is the closest approach when the profile is above the seal and
    ``-maximum`` is the closest approach when it is below. No absolute value is
    taken: a profile drawn on the wrong side keeps a negative separation. Each
    difference is affine between segment endpoints, so its extreme lies at an
    endpoint of the overlap; sloped and curved FE segments are evaluated
    exactly at those endpoints.
    """
    if not profile or not seal:
        raise ClearanceError(
            "unsupported_geometry",
            f"The {label} profile or the seal boundary has no measurable surface.",
            label=label,
        )
    left = max(min(s[0] for s in profile), min(s[0] for s in seal))
    right = min(max(s[2] for s in profile), max(s[2] for s in seal))
    if right - left <= CLEARANCE_TOLERANCE:
        raise ClearanceError(
            "no_x_overlap",
            f"The {label} profile does not overlap the seal in X, so no vertical "
            "clearance can be measured.",
            label=label,
            overlap=round(max(0.0, right - left), 9),
        )
    minimum, maximum = float("inf"), float("-inf")
    for p in profile:
        for s in seal:
            low = max(p[0], s[0])
            high = min(p[2], s[2])
            if high < low - CLEARANCE_TOLERANCE:
                continue
            samples = (low,) if high - low <= CLEARANCE_TOLERANCE else (low, high)
            for x in samples:
                minimum = min(minimum, _height(p, x, min) - _height(s, x, max))
                maximum = max(maximum, _height(p, x, max) - _height(s, x, min))
    return minimum, maximum


def _profile_points(profile):
    """Sample points along the assembled profile, including segment midpoints."""
    points = []
    for x0, y0, x1, y1 in profile:
        points.append((x0, y0))
        points.append(((x0 + x1) / 2.0, (y0 + y1) / 2.0))
    if profile:
        points.append((profile[-1][2], profile[-1][3]))
    return points


def _inside_material(points, seal):
    """Even-odd point-in-region test against the seal's exterior sides.

    The exterior set includes the cavity boundary, so a point inside a hole is
    outside the material. This is what separates a real intersection from a
    profile that merely sits between the upper and lower exterior surfaces. A
    point lying exactly on the boundary is touching, not penetrating: the
    half-open ray test alone would depend on which endpoint the ray crosses.
    """
    for x, y in points:
        if _point_on_boundary(x, y, seal):
            continue
        inside = False
        for x0, y0, x1, y1 in seal:
            if (y0 > y) != (y1 > y):
                crossing = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                if crossing > x:
                    inside = not inside
        if inside:
            return True
    return False


def _assembled_side(profile, seal, minimum, maximum, label):
    """Assembled contact side, or a specific intersection/ambiguity rejection."""
    if minimum >= -CLEARANCE_TOLERANCE:
        return "above"
    if maximum <= CLEARANCE_TOLERANCE:
        return "below"
    # The profile has points on both sides of some exterior surface. If it
    # actually enters the material it is an initial penetration; a profile that
    # only lies between the upper and lower surfaces (for example inside a
    # cavity) has no unambiguous contact side.
    if _inside_material(_profile_points(profile), seal):
        depth = min(-minimum, maximum)
        raise ClearanceError(
            "initial_penetration",
            f"The {label} intersects the seal: {format(depth, '.6g')} mm initial "
            "penetration. Review its initial Y offset.",
            label=label,
            depth=round(depth, 9),
        )
    raise ClearanceError(
        "side_ambiguous",
        f"The {label} profile is neither clearly above nor below the seal, so its "
        "contact side is ambiguous. This template needs one vertical contact side.",
        label=label,
    )


def motion_direction(side):
    """Unit Y motion that moves a profile on ``side`` toward the seal."""
    if side == "above":
        return [0.0, -1.0]
    if side == "below":
        return [0.0, 1.0]
    raise ValueError("Unsupported rigid profile contact side: " + str(side))


def _require_motion_toward_seal(side, travel, label):
    # Zero travel is a hold: the panel keeps its assembled position for the
    # full positive step duration. Only a nonzero travel must point at the seal.
    if travel == 0:
        return
    if (side == "above" and travel < 0) or (side == "below" and travel > 0):
        return
    raise ClearanceError(
        "motion_away",
        f"The {label} travel moves away from the seal: this {label} is {side} the "
        f"seal, so its travel must be {'negative' if side == 'above' else 'positive'}.",
        label=label,
        side=side,
        travel=round(float(travel), 9),
    )


def clearance_report(nodes, boundary, panel, offset, travel=None, label="panel"):
    """Role-aware initial clearance of one rigid profile against the seal.

    The initial Y offset is applied *before* the side and the signed clearance
    are decided: the assembled placement is what the solver and the reader see.
    A horizontal body drawn above the seal and offset below it is therefore a
    valid bottom panel with a positive clearance, not a penetration. A profile
    that genuinely crosses the seal after its offset is reported as an initial
    penetration; an ambiguous side and a missing X overlap have their own
    errors. ``clearance`` is a positive separation convention for both sides.
    """
    profile = _profile_segments(nodes, panel)
    if offset:
        # A rigid translation along Y shifts every segment exactly; it also
        # decides the assembled side, so it cannot be applied afterwards.
        profile = [(x0, y0 + offset, x1, y1 + offset) for x0, y0, x1, y1 in profile]
    seal = _boundary_segments(nodes, boundary)
    minimum, maximum = _separation(profile, seal, label)
    side = _assembled_side(profile, seal, minimum, maximum, label)
    signed = minimum if side == "above" else -maximum
    if travel is not None:
        _require_motion_toward_seal(side, travel, label)
    return {"side": side, "clearance": max(0.0, signed), "direction": motion_direction(side)}


def vertical_gap(nodes, boundary, panel, offset):
    """Minimum positive vertical separation between assembled FE profiles.

    Compatibility wrapper for the door template. The sign follows the measured
    assembled side, so a profile below the seal reports the same positive
    clearance as one above it; it is not an absolute value.
    """
    return clearance_report(nodes, boundary, panel, offset)["clearance"]


def _closest_on_segment(px, py, segment):
    x0, y0, x1, y1 = segment
    dx, dy = x1 - x0, y1 - y0
    length2 = dx * dx + dy * dy
    if length2 <= CLEARANCE_TOLERANCE**2:
        return x0, y0
    t = ((px - x0) * dx + (py - y0) * dy) / length2
    t = max(0.0, min(1.0, t))
    return x0 + t * dx, y0 + t * dy


def _segment_distance(first, second):
    """Minimum Euclidean distance between two segments and its closest pair."""
    best = None
    for px, py, other in (
        (first[0], first[1], second),
        (first[2], first[3], second),
        (second[0], second[1], first),
        (second[2], second[3], first),
    ):
        cx, cy = _closest_on_segment(px, py, other)
        distance = hypot(px - cx, py - cy)
        if best is None or distance < best[0]:
            best = (distance, (px, py), (cx, cy))
    return best


# Fraction of the prescribed stroke that counts as the same first-contact instant.
# A flat face can produce many equal fractions; 1e-6 of a 4 mm stroke is 4e-6 mm,
# far below the mesh tolerance but wide enough for floating-point ties.
CONTACT_TIE_FRACTION = 1e-6
# A hit at or below this fraction is present in the initial pose, not reached by
# the prescribed motion.
CONTACT_INITIAL_FRACTION = 1e-9
# Pull the moving segment back by this fraction of the stroke before measuring
# the approaching side, so a corner/endpoint hit is measured in open space.
CONTACT_BACKOFF_FRACTION = 1e-6
# Tied hits within this much of the dominant motion alignment are the same
# contact face. A corner/side hit at a flat-face tie is far less aligned and is
# not allowed to make the whole contact ambiguous.
CONTACT_ALIGNMENT_TOLERANCE = 1e-3


def _cross(ax, ay, bx, by):
    return ax * by - ay * bx


def _unit(dx, dy):
    length = hypot(dx, dy)
    if length <= CLEARANCE_TOLERANCE:
        return None
    return [dx / length, dy / length]


def _segment_normal(segment):
    x0, y0, x1, y1 = segment
    return _unit(-(y1 - y0), x1 - x0)


def _translate_segment(segment, delta, fraction):
    dx, dy = delta
    return (
        segment[0] + dx * fraction,
        segment[1] + dy * fraction,
        segment[2] + dx * fraction,
        segment[3] + dy * fraction,
    )


def _point_on_boundary(x, y, seal, tolerance=CLEARANCE_TOLERANCE):
    """True when (x, y) lies on a seal boundary segment within tolerance."""
    for segment in seal:
        cx, cy = _closest_on_segment(x, y, segment)
        if hypot(x - cx, y - cy) <= tolerance:
            return True
    return False


def _segment_toi(segment, delta, seal_segment):
    """Earliest ``t`` in [0, 1] where a translated segment meets a seal segment.

    The prescribed translation is linear, so the earliest intersection is solved
    exactly instead of sampled. Parallel and non-parallel pairs are separate
    cases: a parallel segment can only touch when its supporting line becomes
    collinear with the seal segment, and the projections must overlap.
    """
    ax, ay, bx, by = segment
    cx, cy, ex, ey = seal_segment
    e1x, e1y = bx - ax, by - ay
    e2x, e2y = ex - cx, ey - cy
    len1, len2 = hypot(e1x, e1y), hypot(e2x, e2y)
    if len1 <= CLEARANCE_TOLERANCE or len2 <= CLEARANCE_TOLERANCE:
        return None
    wx, wy = cx - ax, cy - ay
    den = _cross(e1x, e1y, e2x, e2y)
    if abs(den) > 1e-12 * max(1.0, len1 * len2):
        s0 = _cross(wx, wy, e2x, e2y)
        s1 = -_cross(delta[0], delta[1], e2x, e2y)
        u0 = _cross(wx, wy, e1x, e1y)
        u1 = -_cross(delta[0], delta[1], e1x, e1y)
        low, high = 0.0, 1.0
        low_value, high_value = (0.0, den) if den > 0 else (den, 0.0)
        for c0, c1 in ((s0, s1), (u0, u1)):
            if abs(c1) <= 1e-12 * max(1.0, abs(c0), abs(low_value), abs(high_value)):
                if not (low_value - 1e-9 <= c0 <= high_value + 1e-9):
                    return None
                continue
            first_t = (low_value - c0) / c1
            last_t = (high_value - c0) / c1
            if c1 < 0:
                first_t, last_t = last_t, first_t
            low = max(low, min(first_t, last_t))
            high = min(high, max(first_t, last_t))
        if high < low - 1e-9:
            return None
        t = max(0.0, low)
        if t > 1.0 + 1e-9:
            return None
        t = min(1.0, t)
        mx, my = ax + t * delta[0], ay + t * delta[1]
        scale = e2x * e2x + e2y * e2y
        u = max(0.0, min(1.0, ((mx - cx) * e2x + (my - cy) * e2y) / scale))
        return {
            "fraction": t,
            "moving": (mx, my),
            "static": (cx + u * e2x, cy + u * e2y),
            "method": "nonparallel",
        }
    # Parallel segments: only a collinearity crossing can produce a hit.
    de = _cross(delta[0], delta[1], e2x, e2y)
    if abs(de) <= 1e-12 * max(1.0, hypot(delta[0], delta[1]) * len2):
        if abs(_cross(wx, wy, e2x, e2y)) > CLEARANCE_TOLERANCE * len2:
            return None
        t = 0.0
    else:
        t = _cross(wx, wy, e2x, e2y) / de
        if t < -1e-9 or t > 1.0 + 1e-9:
            return None
        t = max(0.0, min(1.0, t))
    ax_t = ax + t * delta[0] - cx
    ay_t = ay + t * delta[1] - cy
    bx_t = bx + t * delta[0] - cx
    by_t = by + t * delta[1] - cy
    scale = e2x * e2x + e2y * e2y
    ua = (ax_t * e2x + ay_t * e2y) / scale
    ub = (bx_t * e2x + by_t * e2y) / scale
    low, high = min(ua, ub), max(ua, ub)
    if high < -1e-9 or low > 1.0 + 1e-9:
        return None
    u = max(0.0, min(1.0, low))
    span = ub - ua
    s = 0.0 if abs(span) <= 1e-15 else max(0.0, min(1.0, (u - ua) / span))
    mx = ax + s * e1x + t * delta[0]
    my = ay + s * e1y + t * delta[1]
    return {
        "fraction": t,
        "moving": (mx, my),
        "static": (cx + u * e2x, cy + u * e2y),
        "method": "parallel",
    }


def _surface_approach(element_segment, delta, seal_segment, seal, hit_point=None):
    """Direction from the element to the hit seal surface.

    The hit segment's tangent normal is the stable contact side at a face, a
    corner or an endpoint-only hit. A material probe on either side of the hit
    point decides which normal points out of the seal; the returned direction
    points from the element toward the seal (the direction SPOS must face).
    The witness vector is only a fallback for a degenerate probe.
    """
    normal = _segment_normal(seal_segment)
    if normal is None:
        return None
    x0, y0, x1, y1 = element_segment
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    if hit_point is None:
        hit_point = _closest_on_segment(mx, my, seal_segment)
    hx, hy = float(hit_point[0]), float(hit_point[1])
    cx, cy, dx, dy = seal_segment
    seal_length = hypot(dx - cx, dy - cy)
    step = min(1e-3, max(1e-7, 1e-4 * max(seal_length, 1.0)))
    # At a segment endpoint the normal probe can land on the adjacent boundary
    # and be skipped as "on the boundary". Move the probe base a small distance
    # along this *seal* segment so the material side is well defined. Using the
    # moving element's tangent here would step the wrong way for a reversed
    # element pair.
    if seal_length > CLEARANCE_TOLERANCE:
        ex, ey = dx - cx, dy - cy
        parameter = ((hx - cx) * ex + (hy - cy) * ey) / (seal_length * seal_length)
        margin = min(0.49, step / seal_length)
        if parameter < margin:
            parameter = margin
        elif parameter > 1.0 - margin:
            parameter = 1.0 - margin
        hx, hy = cx + parameter * ex, cy + parameter * ey
    plus = (hx + normal[0] * step, hy + normal[1] * step)
    minus = (hx - normal[0] * step, hy - normal[1] * step)
    inside_plus = _inside_material([plus], seal)
    inside_minus = _inside_material([minus], seal)
    if inside_plus and not inside_minus:
        return normal
    if inside_minus and not inside_plus:
        return [-normal[0], -normal[1]]
    # Degenerate or thin-seal probe: use the witness vector from the element.
    direction = _unit(hx - mx, hy - my)
    if direction is not None:
        return direction
    along = delta[0] * normal[0] + delta[1] * normal[1]
    if abs(along) <= CLEARANCE_TOLERANCE:
        return None
    return normal if along > 0 else [-normal[0], -normal[1]]


def _initial_touch_approach(element_segment, delta, seal_segment, seal):
    """Approach direction for a segment already touching the seal at t = 0."""
    x0, y0, x1, y1 = element_segment
    cx, cy = _closest_on_segment((x0 + x1) / 2.0, (y0 + y1) / 2.0, seal_segment)
    return _surface_approach(element_segment, delta, seal_segment, seal, (cx, cy))


def _approach_at_contact(element_segment, delta, fraction, seal_segment, seal, hit_point=None):
    """Direction from the element to the hit seal surface just before contact."""
    backoff = min(CONTACT_BACKOFF_FRACTION, fraction / 2.0 if fraction > 0 else 0.0)
    before = _translate_segment(element_segment, delta, max(0.0, fraction - backoff))
    if hit_point is None:
        x0, y0, x1, y1 = before
        hit_point = _closest_on_segment(
            (x0 + x1) / 2.0, (y0 + y1) / 2.0, seal_segment
        )
    return _surface_approach(before, delta, seal_segment, seal, hit_point)


def _combine_directions(directions):
    """One deterministic direction, or an ambiguity when the hits oppose."""
    vectors = [direction for direction in directions if direction is not None]
    if not vectors:
        return None, True
    for index, first in enumerate(vectors):
        for second in vectors[index + 1 :]:
            if first[0] * second[0] + first[1] * second[1] < -1e-6:
                return None, True
    total = [sum(direction[0] for direction in vectors), sum(direction[1] for direction in vectors)]
    combined = _unit(total[0], total[1])
    if combined is None:
        return None, True
    if any(first[0] * combined[0] + first[1] * combined[1] <= 1e-6 for first in vectors):
        return None, True
    return combined, False


def _select_dominant_hits(hits, delta):
    """Pick the tied hits that belong to the dominant contact face.

    ``hits`` is ``[(seal_index, result, direction), ...]``. At a flat-face tie
    the end/corner segments are also touched at the same instant; their tangent
    normals are nearly perpendicular to the motion and must not make the whole
    contact ambiguous. The face with the largest alignment to the prescribed
    motion wins. Genuinely opposing faces at the same alignment stay ambiguous.
    """
    length = hypot(delta[0], delta[1])
    if length <= CLEARANCE_TOLERANCE:
        return [], True
    ux, uy = delta[0] / length, delta[1] / length
    scored = []
    for seal_index, result, direction in hits:
        if direction is None:
            continue
        alignment = abs(direction[0] * ux + direction[1] * uy)
        scored.append((alignment, seal_index, result, direction))
    if not scored:
        return [], True
    best = max(item[0] for item in scored)
    if best <= 1e-9:
        # No component along the motion, but a single (or consistently oriented)
        # side contact is still a valid contact side. Only genuinely opposing
        # tied faces remain ambiguous.
        selected = [(seal_index, result, direction) for _alignment, seal_index, result, direction in scored]
    else:
        selected = [
            (seal_index, result, direction)
            for alignment, seal_index, result, direction in scored
            if alignment >= best - CONTACT_ALIGNMENT_TOLERANCE
        ]
    _combined, ambiguous = _combine_directions([item[2] for item in selected])
    if ambiguous:
        return [], True
    return selected, False


def _segment_first_contact(profile_segments, seal_segments, delta):
    """Exact first contact of a translating segment list with the seal.

    Initial hits that move *into* the touched surface are a t = 0 contact.
    Initial hits that move away are ignored; the first new hit at t > 0 is the
    target (the lower-lip case). If there is no new hit, the path has no contact.
    """
    if hypot(delta[0], delta[1]) <= CLEARANCE_TOLERANCE:
        return {"kind": "none", "fraction": None, "hits": [], "all": []}
    all_hits = []
    for profile_index, profile_segment in enumerate(profile_segments):
        for seal_index, seal_segment in enumerate(seal_segments):
            result = _segment_toi(profile_segment, delta, seal_segment)
            if result is not None:
                all_hits.append((profile_index, seal_index, result))
    if not all_hits:
        return {"kind": "none", "fraction": None, "hits": [], "all": []}
    initial = [hit for hit in all_hits if hit[2]["fraction"] <= CONTACT_INITIAL_FRACTION]
    later = [hit for hit in all_hits if hit[2]["fraction"] > CONTACT_INITIAL_FRACTION]
    initial_into = []
    for profile_index, seal_index, result in initial:
        approach = _initial_touch_approach(
            profile_segments[profile_index], delta, seal_segments[seal_index], seal_segments
        )
        if approach is not None and (
            delta[0] * approach[0] + delta[1] * approach[1] > CLEARANCE_TOLERANCE
        ):
            initial_into.append((profile_index, seal_index, result))
    if initial_into:
        return {"kind": "touching", "fraction": 0.0, "hits": initial_into, "all": all_hits}
    if later:
        fraction = min(hit[2]["fraction"] for hit in later)
        tied = [
            hit for hit in later if hit[2]["fraction"] <= fraction + CONTACT_TIE_FRACTION
        ]
        return {"kind": "contact", "fraction": fraction, "hits": tied, "all": all_hits}
    return {"kind": "none", "fraction": None, "hits": [], "all": all_hits}


def _element_contact_target(nodes, elements, seal, offset=0.0, delta=(0.0, 0.0)):
    """First-contact target keyed by element, with the approach at contact time.

    ``element_approaches`` is per element's own first non-initial contact. For an
    element that belongs to the global first-contact set the global hit is used
    (so an initial touch that moves away does not win over the new contact).
    """
    segments = []
    for element in elements:
        first = nodes[element["nodes"][0]]
        second = nodes[element["nodes"][1]]
        segments.append(
            (
                float(first[0]),
                float(first[1]) + offset,
                float(second[0]),
                float(second[1]) + offset,
            )
        )
    first = _segment_first_contact(segments, seal, delta)
    by_element = defaultdict(list)
    for profile_index, seal_index, result in first["all"]:
        by_element[profile_index].append((seal_index, result))
    target_hits_by_element = defaultdict(list)
    for profile_index, seal_index, result in first["hits"]:
        target_hits_by_element[profile_index].append((seal_index, result))
    target_ids = []
    for profile_index, _seal_index, _result in first["hits"]:
        element_id = elements[profile_index]["id"]
        if element_id not in target_ids:
            target_ids.append(element_id)
    approaches = {}
    for profile_index, hits in by_element.items():
        element_id = elements[profile_index]["id"]
        later = [(seal_index, result) for seal_index, result in hits if result["fraction"] > CONTACT_INITIAL_FRACTION]
        if element_id in target_ids:
            tied = target_hits_by_element[profile_index]
            fraction = first["fraction"]
            pairs = []
            if first["kind"] == "touching":
                for seal_index, _result in tied:
                    pairs.append(
                        (
                            seal_index,
                            _result,
                            _initial_touch_approach(
                                segments[profile_index], delta, seal[seal_index], seal
                            ),
                        )
                    )
                fraction = 0.0
            else:
                for seal_index, result in tied:
                    pairs.append(
                        (
                            seal_index,
                            result,
                            _approach_at_contact(
                                segments[profile_index],
                                delta,
                                fraction,
                                seal[seal_index],
                                seal,
                                result["static"],
                            ),
                        )
                    )
            selected, selection_ambiguous = _select_dominant_hits(pairs, delta)
            direction, combine_ambiguous = _combine_directions(
                [item[2] for item in selected]
            )
            approaches[element_id] = {
                "fraction": fraction,
                "direction": direction,
                "ambiguous": selection_ambiguous or combine_ambiguous,
                "initial_only": False,
                "target": True,
                "seal_segments": [seal[item[0]] for item in selected],
            }
        elif later:
            fraction = min(result["fraction"] for _seal_index, result in later)
            tied = [
                (seal_index, result)
                for seal_index, result in later
                if result["fraction"] <= fraction + CONTACT_TIE_FRACTION
            ]
            pairs = [
                (
                    seal_index,
                    result,
                    _approach_at_contact(
                        segments[profile_index],
                        delta,
                        fraction,
                        seal[seal_index],
                        seal,
                        result["static"],
                    ),
                )
                for seal_index, result in tied
            ]
            selected, selection_ambiguous = _select_dominant_hits(pairs, delta)
            direction, combine_ambiguous = _combine_directions(
                [item[2] for item in selected]
            )
            approaches[element_id] = {
                "fraction": fraction,
                "direction": direction,
                "ambiguous": selection_ambiguous or combine_ambiguous,
                "initial_only": False,
                "target": False,
                "seal_segments": [seal[item[0]] for item in selected],
            }
        else:
            pairs = [
                (
                    seal_index,
                    _result,
                    _initial_touch_approach(
                        segments[profile_index], delta, seal[seal_index], seal
                    ),
                )
                for seal_index, _result in hits
            ]
            selected, selection_ambiguous = _select_dominant_hits(pairs, delta)
            direction, combine_ambiguous = _combine_directions(
                [item[2] for item in selected]
            )
            approaches[element_id] = {
                "fraction": 0.0,
                "direction": direction,
                "ambiguous": selection_ambiguous or combine_ambiguous,
                "initial_only": True,
                "target": False,
                "seal_segments": [seal[item[0]] for item in selected],
            }
    target_directions = [
        approaches[element_id]["direction"]
        for element_id in target_ids
        if element_id in approaches
    ]
    target_direction, target_ambiguous = _combine_directions(target_directions)
    ambiguous = target_ambiguous or any(
        approaches[element_id]["ambiguous"]
        for element_id in target_ids
        if element_id in approaches
    )
    return {
        "kind": first["kind"],
        "fraction": first["fraction"],
        "hits": first["hits"],
        "all_hits": first["all"],
        "element_ids": target_ids,
        "element_approaches": approaches,
        "direction": target_direction,
        "ambiguous": ambiguous,
    }


def _geometry_segments(geometry):
    """LineString/MultiLineString -> (x0, y0, x1, y1) segments."""
    lines = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    segments = []
    for line in lines:
        coordinates = list(line.coords)
        for first, second in zip(coordinates, coordinates[1:]):
            segments.append((first[0], first[1], second[0], second[1]))
    return segments


def _polyline(segments):
    """A multi-segment polyline for geometric distance and nearest-point work."""
    from shapely.geometry import MultiLineString

    return MultiLineString([[(s[0], s[1]), (s[2], s[3])] for s in segments])


def _swept_contact(profile_geom, seal_geom, delta, samples=200):
    """First fraction of the prescribed path that touches the seal, if any.

    First contact is solved exactly from the segment sweep. The sampled distance
    remains only as the closest-approach value for a genuine miss; it never
    decides orientation or the first-contact fraction.
    """
    dx, dy = delta
    if hypot(dx, dy) <= CLEARANCE_TOLERANCE:
        return None, 0.0
    first = _segment_first_contact(
        _geometry_segments(profile_geom), _geometry_segments(seal_geom), delta
    )
    if first["kind"] in ("contact", "touching"):
        return first["fraction"], 0.0
    closest = (profile_geom.distance(seal_geom), 0.0)
    for index in range(1, samples + 1):
        t = index / samples
        distance = translate(profile_geom, dx * t, dy * t).distance(seal_geom)
        if distance < closest[0]:
            closest = (distance, t)
    return None, closest[0]


def _direction_to_seal(profile_geom, seal_geom):
    """Unit vector from the assembled profile toward its nearest seal surface."""
    from shapely.ops import nearest_points

    on_profile, on_seal = nearest_points(profile_geom, seal_geom)
    dx, dy = on_seal.x - on_profile.x, on_seal.y - on_profile.y
    length = hypot(dx, dy)
    if length <= CLEARANCE_TOLERANCE:
        return None
    return [dx / length, dy / length]


def _side_from_direction(direction):
    """Describe where the profile sits relative to the seal surface it faces."""
    if direction is None:
        return None
    if abs(direction[1]) >= abs(direction[0]):
        # The seal lies below an "above" profile, so the direction points down.
        return "above" if direction[1] < 0 else "below"
    return "left" if direction[0] > 0 else "right"


def side_phrase(side):
    """Readable placement phrase for headings and diagnostics."""
    return {
        "above": "above the seal",
        "below": "below the seal",
        "left": "to the left of the seal",
        "right": "to the right of the seal",
    }.get(side, str(side))


def directional_motion_assessment(nodes, boundary, elements, motion, role, instance, label):
    """Geometric assessment along the swept segment for an arbitrary angle.

    Works in model coordinates for any in-plane direction: the prescribed path,
    its first geometric intersection with the seal and the closest approach are
    distinct quantities. Nothing is inferred from a solver status.
    """
    profile = _profile_segments(nodes, elements)
    offset = motion.offset
    if offset:
        profile = [(x0, y0 + offset, x1, y1 + offset) for x0, y0, x1, y1 in profile]
    seal = _boundary_segments(nodes, boundary)
    if not profile or not seal:
        raise ClearanceError(
            "unsupported_geometry",
            f"The {label} profile or the seal boundary has no measurable surface.",
            label=label,
        )
    resolved = motion_policy.resolve(motion, 4)
    delta = resolved["delta"]
    profile_geom = _polyline(profile)
    seal_geom = _polyline(seal)
    if _inside_material(_profile_points(profile), seal):
        minimum, maximum = _separation(profile, seal, label)
        depth = min(-minimum, maximum)
        raise ClearanceError(
            "initial_penetration",
            f"The {label} intersects the seal: {format(depth, '.6g')} mm initial penetration. "
            "Review its initial placement.",
            label=label,
            depth=round(depth, 9),
        )
    initial_direction = _direction_to_seal(profile_geom, seal_geom)
    initial_side = _side_from_direction(initial_direction)
    initial = profile_geom.distance(seal_geom)
    target = _element_contact_target(nodes, elements, seal, offset, delta)
    contact = target["kind"] in ("contact", "touching")
    first_t = target["fraction"] if contact else None
    contact_direction = target["direction"] if contact else None
    contact_side = _side_from_direction(contact_direction)
    if contact and (target["ambiguous"] or contact_direction is None):
        raise ClearanceError(
            "panel.contact_side_ambiguous",
            f"The {label} first-contact neighborhood does not have one unambiguous "
            "seal-facing side. Review the drawing or its placement.",
            label=label,
            fraction=target["fraction"],
            elements=target["element_ids"],
            attempts=[
                {
                    "element": element_id,
                    "fraction": info["fraction"],
                    "direction": info["direction"],
                }
                for element_id, info in target["element_approaches"].items()
                if element_id in target["element_ids"]
            ],
        )
    if contact:
        direction = contact_direction
    else:
        direction = initial_direction
        if direction is None and target["all_hits"]:
            direction, _ = _combine_directions(
                [
                    info["direction"]
                    for info in target["element_approaches"].values()
                    if info["direction"] is not None
                ]
            )
    side = initial_side if initial_side is not None else contact_side
    if side is None:
        side = _side_from_direction(direction)
    if direction is None:
        raise ClearanceError(
            "side_ambiguous",
            f"The {label} profile touches or crosses the nearest seal surface, so its "
            "contact normal is ambiguous. Review its initial placement.",
            label=label,
        )
    final = translate(profile_geom, delta[0], delta[1]).distance(seal_geom)
    approaching = final < initial - CLEARANCE_TOLERANCE
    left = max(min(s[0] for s in profile), min(s[0] for s in seal))
    right = min(max(s[2] for s in profile), max(s[2] for s in seal))
    x_overlap = right - left > CLEARANCE_TOLERANCE
    if first_t is None and not x_overlap:
        raise ClearanceError(
            "no_x_overlap",
            f"The {label} profile does not overlap the seal in X and its prescribed path "
            "never reaches it.",
            label=label,
            overlap=round(max(0.0, right - left), 9),
        )
    if resolved["stroke"] > 0 and first_t is None and not approaching:
        raise ClearanceError(
            "motion_away",
            f"The {label} prescribed motion at {resolved['angle']:g} deg does not approach "
            f"the seal: the closest approach grows from {initial:.6g} mm to {final:.6g} mm.",
            label=label,
            side=side,
            angle=resolved["angle"],
            stroke=resolved["stroke"],
        )
    contact_target = None
    nearest_surface_is_target = None
    if contact:
        element_segments = {}
        for element in elements:
            first = nodes[element["nodes"][0]]
            second = nodes[element["nodes"][1]]
            element_segments[element["id"]] = (
                float(first[0]),
                float(first[1]) + offset,
                float(second[0]),
                float(second[1]) + offset,
            )
        gaps = []
        witness = None
        hit_segments = []
        for profile_index, seal_index, _result in target["hits"]:
            element_id = elements[profile_index]["id"]
            element_segment = element_segments[element_id]
            gaps.append(_segment_distance(element_segment, seal[seal_index])[0])
            if tuple(seal[seal_index]) not in hit_segments:
                hit_segments.append(tuple(seal[seal_index]))
            if witness is None:
                if first_t > 0:
                    before = _translate_segment(
                        element_segment, delta, max(0.0, first_t - CONTACT_BACKOFF_FRACTION)
                    )
                    _distance, _on_element, on_seal = _segment_distance(
                        before, seal[seal_index]
                    )
                    witness = [on_seal[0], on_seal[1]]
                else:
                    x0, y0, x1, y1 = element_segment
                    cx, cy = _closest_on_segment(
                        (x0 + x1) / 2.0, (y0 + y1) / 2.0, seal[seal_index]
                    )
                    witness = [cx, cy]
        contact_target = {
            "element_ids": target["element_ids"],
            "seal_segments": [list(segment) for segment in hit_segments],
            "approach": contact_direction,
            "fraction": first_t,
            "travel_mm": first_t * hypot(delta[0], delta[1]),
            "initial_gap_mm": min(gaps) if gaps else None,
            "witness_mm": witness,
        }
        same_distance = abs(initial - contact_target["initial_gap_mm"]) <= max(
            1e-6, 1e-3 * max(initial, contact_target["initial_gap_mm"])
        )
        same_direction = (
            initial_direction is None
            or contact_direction is None
            or (
                initial_direction[0] * contact_direction[0]
                + initial_direction[1] * contact_direction[1]
                > 0.99
            )
        )
        nearest_surface_is_target = bool(same_distance and same_direction)
    path = (
        "hold"
        if resolved["stroke"] == 0
        else (
            "touching"
            if first_t == 0.0
            else ("contact" if first_t is not None else ("approaching" if approaching else "missed"))
        )
    )
    if first_t is not None:
        closest = 0.0
    else:
        _first_t, closest = _swept_contact(profile_geom, seal_geom, delta)
    # A zero stroke is a hold: report the assembled role direction (the way the
    # panel faces the seal) rather than an arbitrary draft angle.
    if resolved["stroke"] == 0:
        shown_direction = direction
        shown_angle = motion_policy.angle_of(direction)
    else:
        shown_direction = motion_policy.unit_vector(resolved["angle"])
        shown_angle = resolved["angle"]
    return {
        "role": role,
        "instance": instance,
        "side": side,
        "direction": shown_direction,
        "direction_to_seal": direction,
        "angle_deg": shown_angle,
        "stroke_mm": resolved["stroke"],
        "delta_mm": delta,
        "initial_offset_mm": offset,
        "clearance_mm": max(0.0, initial),
        "travel_mm": resolved["delta"][1],
        "duration_s": motion.duration,
        "hold": resolved["stroke"] == 0,
        "first_contact_fraction": first_t,
        "closest_after_mm": closest,
        "reaches_initial_gap": first_t is not None,
        "path": path,
        "legacy": False,
        "contact_side": contact_side,
        "initial_side": initial_side,
        "initial_direction_to_seal": initial_direction,
        "contact_target": contact_target,
        "nearest_surface_is_target": nearest_surface_is_target,
    }


def motion_assessment(nodes, boundary, elements, motion, role, instance, label, schema_version=3):
    """Clearance, assembled side, direction and hold/gap reach for one profile."""
    if schema_version >= 4:
        return directional_motion_assessment(
            nodes, boundary, elements, motion, role, instance, label
        )
    # Zero travel is a hold and has no direction check; measuring it here must
    # not be reported as motion away from the seal.
    report = clearance_report(
        nodes, boundary, elements, motion.offset, motion.travel or None, label
    )
    return {
        "role": role,
        "instance": instance,
        "side": report["side"],
        "direction": report["direction"],
        "initial_offset_mm": motion.offset,
        "clearance_mm": report["clearance"],
        "travel_mm": motion.travel,
        "duration_s": motion.duration,
        "hold": motion.travel == 0,
        # Necessary to cross the measured gap, never a guarantee of contact.
        "reaches_initial_gap": motion.travel != 0
        and abs(motion.travel) >= report["clearance"],
        "angle_deg": motion_policy.legacy_angle(motion.travel),
        "stroke_mm": abs(motion.travel),
        "delta_mm": [0.0, motion.travel],
        "first_contact_fraction": None,
        "path": "hold" if motion.travel == 0 else "prescribed",
        "legacy": True,
    }


def assembly_assessment(project, mesh):
    """Door and body clearance, contact side and motion direction on one mesh.

    Pure geometry on a queued mesh: no deck, artifact or solver state is
    written. Raises :class:`ClearanceError` for a real geometric rejection so
    the caller can report the same condition the deck writer enforces.
    """
    nodes, ws, panel, body = _mesh_parts(project, mesh)
    boundary = exterior(ws)
    result = {
        "door": motion_assessment(
            nodes, boundary, panel, project.motion, role="door", instance="PANEL-1",
            label="door", schema_version=project.schema_version,
        ),
        "body": None,
    }
    if body:
        result["body"] = motion_assessment(
            nodes, boundary, body, project.motion.body, role="body", instance="BODY-1",
            label="body", schema_version=project.schema_version,
        )
    if project.schema_version >= 4:
        # The deck writer refuses an ambiguous first-contact neighborhood with a
        # typed code. Readiness runs the same check, so it can never show
        # "ready" for geometry the writer rejects.
        seal_segments = _boundary_segments(nodes, boundary)
        orient_toward(
            panel,
            nodes,
            result["door"]["direction_to_seal"],
            seal=seal_segments,
            role="door",
            label="door",
            offset=project.motion.offset,
            delta=result["door"]["delta_mm"],
        )
        if body:
            orient_toward(
                body,
                nodes,
                result["body"]["direction_to_seal"],
                seal=seal_segments,
                role="body",
                label="body",
                offset=project.motion.body.offset,
                delta=result["body"]["delta_mm"],
            )
    return result


def _table(rows):
    return [", ".join(scalar(value) for value in row) for row in rows]


def _hyperfoam_lines(block):
    """Emit one ``*Hyperfoam`` card exactly as its registered source defines it.

    Test-data input keeps the supplied columns; lateral nominal strain is written
    only when the source says it was measured, never because a storage column was
    zero-filled. Direct coefficients keep their modulus time basis.
    """
    options = [f"n={block.n}"]
    if block.moduli == "INSTANTANEOUS":
        options.append("moduli=INSTANTANEOUS")
    if block.test_data:
        options.append("test data input")
    if block.poisson is not None:
        options.append(f"poisson={scalar(block.poisson)}")
    lines = ["*Hyperfoam, " + ", ".join(options)]
    if block.test_data:
        lines.append("*Uniaxial Test Data")
        return lines + _table(block.uniaxial)
    # The registered row is already in keyword order: mu_1, alpha_1, ...,
    # mu_N, alpha_N, nu_1 ... nu_N. Abaqus reads at most eight values per data
    # line, so the row is packed, not reordered (verified against CAE 2024).
    emitted = []
    for row in block.table:
        for start in range(0, len(row), 8):
            emitted.append(", ".join(scalar(value) for value in row[start : start + 8]))
    return lines + emitted


def _mullins_definition(definition):
    """Map the registered source token to the Abaqus ``*Mullins Effect`` options.

    CAE 2024's material editor stores the direct Ogden-Roxburgh constants as
    "CONSTANTS", but its keyword reader rejects a ``DEFINITION`` parameter on this
    option (verified with writeInput/import): the constants form is the bare
    keyword, and only test-data input adds a parameter.
    """
    return {
        "CONSTANTS": "",
        "TEST_DATA": "test data input",
        "EXPONENTIAL": "definition=EXPONENTIAL",
        "SLOW_DECAY": "definition=SLOW DECAY",
        "USER": "definition=USER",
    }.get(definition, "")


def _hyperelastic_lines(block):
    name = {
        "MARLOW": "marlow",
        "YEOH": "yeoh",
        "OGDEN": "ogden",
        "POLYNOMIAL": "polynomial",
        "NEO_HOOKE": "neo hooke",
    }[block.type]
    options = [name]
    if block.type in ("OGDEN", "POLYNOMIAL") and block.n != 1:
        options.append(f"n={block.n}")
    if block.moduli_time_scale == "INSTANTANEOUS":
        options.append("moduli=INSTANTANEOUS")
    if block.test_data:
        options.append("test data input")
    lines = ["*Hyperelastic, " + ", ".join(options)]
    if block.test_data:
        lines.append("*Uniaxial Test Data")
        return lines + _table(block.uniaxial)
    return lines + _table(block.table)


def material_cards(material, name):
    """Emit the exact submitted material definition.

    A card registered from a CAE library reproduces its source law, options,
    active columns and every numerical row. Missing inputs are refused by name
    instead of being substituted; a registered card alone is never evidence that
    its law is complete for this procedure.
    """
    if material.density is None or material.density <= 0:
        raise ValueError(
            f"Material {material.name!r} has no density. Add a density in a new "
            "registered library version before preparing an implicit-dynamics deck."
        )
    lines = [f"*Material, name={name}", "*Density", scalar(material.density)]
    if material.model == "linear_elastic":
        if (
            material.young is None
            or material.poisson is None
            or not (-1 < material.poisson < 0.5)
            or material.young <= 0
        ):
            raise ValueError("Elastic material requires E > 0 and -1 < Poisson ratio < 0.5.")
        lines += ["*Elastic", f"{scalar(material.young)}, {scalar(material.poisson)}"]
    elif material.model == "hyperfoam_test":
        if len(material.test_data) < 3:
            raise ValueError(
                "Supply at least three uniaxial stress, axial strain and lateral strain samples."
            )
        lines += ["*Hyperfoam, N=1, test data input", "*Uniaxial Test Data"]
        lines.extend(", ".join(map(scalar, row)) for row in material.test_data)
    elif material.model == "neo_hookean":
        # Abaqus/Standard 2024 compressible neo-Hookean: C10 in MPa and D1 in
        # MPa^-1 on one data line. D1 > 0 keeps the law compressible.
        if material.c10 is None or material.d1 is None or material.c10 <= 0 or material.d1 <= 0:
            raise ValueError(
                "A compressible neo-Hookean card needs C10 (MPa) and D1 (MPa^-1), both > 0."
            )
        lines += ["*Hyperelastic, neo Hooke", f"{scalar(material.c10)}, {scalar(material.d1)}"]
    elif material.model == "cae_law":
        if not material.structural_law:
            raise ValueError(
                f"Material {material.name!r} has no structural law; only thermal data is "
                "registered. Add an elastic, hyperelastic or hyperfoam law in a new version."
            )
        if material.young is not None and material.poisson is not None:
            lines += ["*Elastic", f"{scalar(material.young)}, {scalar(material.poisson)}"]
        if material.hyperfoam:
            lines += _hyperfoam_lines(material.hyperfoam)
        if material.hyperelastic:
            lines += _hyperelastic_lines(material.hyperelastic)
        if material.viscoelastic:
            options = ["time=" + material.viscoelastic.time]
            lines += ["*Viscoelastic, " + ", ".join(options)]
            lines += _table(material.viscoelastic.table)
        if material.mullins:
            suffix = _mullins_definition(material.mullins.definition)
            lines += ["*Mullins Effect" + (", " + suffix if suffix else "")]
            lines += _table(material.mullins.table)
        if material.plastic:
            lines += [f"*Plastic, hardening={material.plastic.hardening}"]
            lines += _table(material.plastic.table)
        if material.thermal:
            if material.thermal.conductivity:
                lines += ["*Conductivity"] + _table(material.thermal.conductivity)
            if material.thermal.specific_heat:
                lines += ["*Specific Heat"] + _table(material.thermal.specific_heat)
    else:
        raise ValueError("Unsupported material model.")
    return lines


def fixed_nodes(project, mesh, fixture):
    """Return the fixed seal node labels from a reviewed mesh node set.

    ``fixture`` is the list of instance-qualified labels reviewed on this exact
    mesh. ``None`` keeps the editable legacy path: the stored CAD-edge mounting
    selection is resolved to nodes of the known mesh.
    """
    if fixture is None:
        selection = next(
            (s for s in project.selections if s.id == project.mounting.selection), None
        )
        if not selection or not selection.entities:
            raise ValueError(
                "Select the fixed weatherstrip nodes, or a mounting boundary, "
                "before generating the input."
            )
        try:
            labels = fixtures.from_edges(mesh, selection.entities)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        nodes = [int(label.split(":")[1]) for label in labels]
    else:
        labels = fixtures.normalize(fixture, mesh)
        if not labels:
            raise ValueError(
                "Select at least one fixed weatherstrip node before preparing the input deck."
            )
        nodes = [int(label.split(":")[1]) for label in labels]
    deformable = fixtures.deformable_nodes(mesh)
    stray = sorted(set(nodes) - deformable)
    if stray:
        raise ValueError(
            "Fixed nodes must belong to the deformable weatherstrip: "
            + ", ".join(map(str, stray[:8]))
            + "."
        )
    return nodes


def _reverse_chain(ordered):
    """Turn a chain around without changing any node or element identity."""
    return [
        dict(element, nodes=[element["nodes"][1], element["nodes"][0]])
        for element in reversed(ordered)
    ]


def _contact_alignment(ordered, nodes, seal, offset=0.0, delta=None, target=None):
    """Signed local alignment of every SPOS normal with its contact-time surface.

    For a prescribed sweep each element is measured at its own exact first
    contact: the direction comes from the witness on the seal segment actually
    hit just before touch, not from the nearest surface in the undeformed pose.
    The persisted placement offset is applied. A static call (``delta`` absent
    or zero) keeps the historical nearest-point measurement.
    """
    from shapely.geometry import LineString, Point
    from shapely.ops import nearest_points

    seal_geom = _polyline(seal)
    swept = delta is not None and hypot(float(delta[0]), float(delta[1])) > CLEARANCE_TOLERANCE
    if swept and target is None:
        target = _element_contact_target(nodes, ordered, seal, offset, delta)
    rows = []
    for element in ordered:
        first = nodes[element["nodes"][0]]
        second = nodes[element["nodes"][1]]
        placed = Point(
            (first[0] + second[0]) / 2.0, (first[1] + second[1]) / 2.0 + offset
        )
        distance = placed.distance(seal_geom)
        sweep_distance = distance
        contact_fraction = None
        direction = None
        ambiguous = False
        hit_segments = []
        if swept:
            end = (placed.x + delta[0], placed.y + delta[1])
            path = LineString([(placed.x, placed.y), end])
            sweep_distance = path.distance(seal_geom)
            info = (
                target["element_approaches"].get(element["id"]) if target is not None else None
            )
            if info is not None and target["kind"] in ("contact", "touching"):
                if not info.get("initial_only"):
                    contact_fraction = info["fraction"]
                direction = info["direction"]
                ambiguous = info["ambiguous"]
                hit_segments = info.get("seal_segments", [])
            elif info is not None:
                direction = info["direction"]
                ambiguous = info["ambiguous"]
                hit_segments = info.get("seal_segments", [])
            if direction is None and distance > CLEARANCE_TOLERANCE:
                on_profile, on_seal = nearest_points(placed, seal_geom)
                dx, dy = on_seal.x - on_profile.x, on_seal.y - on_profile.y
                direction = _unit(dx, dy)
        elif distance > CLEARANCE_TOLERANCE:
            on_profile, on_seal = nearest_points(placed, seal_geom)
            dx, dy = on_seal.x - on_profile.x, on_seal.y - on_profile.y
            direction = _unit(dx, dy)
        normal = surface_normal(nodes, element)
        dot = (
            0.0
            if direction is None
            else normal[0] * direction[0] + normal[1] * direction[1]
        )
        rows.append(
            {
                "element": element,
                "distance": distance,
                "sweep_distance": sweep_distance,
                "contact_fraction": contact_fraction,
                "direction": direction,
                "dot": dot,
                "ambiguous": ambiguous,
                "seal_segments": hit_segments,
            }
        )
    return rows


# mm. The predicted first-contact neighborhood: elements within this distance of
# the closest element. Static/no-contact callers use it; a swept contact uses the
# exact first-contact tie instead.
CONTACT_NEIGHBORHOOD_MM = 0.5


def _first_contact(rows):
    if not rows:
        return []
    # A swept contact selects the exact earliest tie. The 5 % band is retained
    # only for a static/no-contact fallback, where a curved return can otherwise
    # pull in segments that never touch first.
    fractions = [row["contact_fraction"] for row in rows if row.get("contact_fraction") is not None]
    if fractions:
        earliest = min(fractions)
        band = [
            row
            for row in rows
            if row.get("contact_fraction") is not None
            and row["contact_fraction"] <= earliest + CONTACT_TIE_FRACTION
        ]
        if band:
            return band
    metric = "sweep_distance" if any("sweep_distance" in row for row in rows) else "distance"
    closest = min(row[metric] for row in rows)
    limit = closest + max(CONTACT_NEIGHBORHOOD_MM, closest * 0.02)
    return [row for row in rows if row[metric] <= limit + CLEARANCE_TOLERANCE]


def _ambiguous_error(target, role, label):
    return PreparationError(
        "panel.contact_side_ambiguous",
        f"The {label} profile's first-contact neighborhood does not have one "
        "unambiguous seal-facing side. Review the drawing or its placement.",
        stage="components",
        role=role,
        label=label,
        fraction=target.get("fraction") if target else None,
        elements=target.get("element_ids") if target else [],
        attempts=[
            {
                "element": element_id,
                "fraction": info["fraction"],
                "direction": info["direction"],
            }
            for element_id, info in (target or {}).get("element_approaches", {}).items()
            if info.get("target")
        ],
    )


def orient_toward(
    ordered,
    nodes,
    direction,
    seal=None,
    role=None,
    label="moving panel",
    offset=0.0,
    delta=None,
):
    """Order R2D2 connectivity so the measured contact side faces the seal.

    With ``seal`` and a prescribed sweep the decision is made at each element's
    exact first contact on the *assembled* profile: the hit seal segment, its
    witness and the approaching side just before touch decide the orientation.
    The persisted offset and motion vector are therefore part of the decision.
    A static call keeps the historical nearest-point projection; without any
    seal the historical global projection is kept.
    """
    if seal is None:
        if direction is None:
            raise PreparationError(
                "panel.contact_side_ambiguous",
                f"The {label} profile touches or crosses the nearest seal surface, so its "
                "contact side cannot be measured.",
                stage="components",
                role=role,
                label=label,
            )
        total = 0.0
        for element in ordered:
            normal = surface_normal(nodes, element)
            total += normal[0] * direction[0] + normal[1] * direction[1]
        return _reverse_chain(ordered) if total < 0 else ordered

    swept = delta is not None and hypot(float(delta[0]), float(delta[1])) > CLEARANCE_TOLERANCE
    if swept:
        target = _element_contact_target(nodes, ordered, seal, offset, delta)
        if target["kind"] in ("contact", "touching") and (
            target["ambiguous"] or target["direction"] is None
        ):
            raise _ambiguous_error(target, role, label)
        rows = _first_contact(
            _contact_alignment(ordered, nodes, seal, offset, delta, target=target)
        )
        score = sum(row["dot"] for row in rows)
        oriented = _reverse_chain(ordered) if score < 0 else ordered
        # Re-measure the oriented connectivity against the same contact-time
        # directions. Every first-contact element must now face the seal.
        check = _first_contact(
            _contact_alignment(oriented, nodes, seal, offset, delta, target=target)
        )
        if not check or sum(row["dot"] for row in check) <= 1e-9:
            raise _ambiguous_error(target, role, label)
        for row in check:
            if row.get("ambiguous"):
                raise _ambiguous_error(target, role, label)
            if row["direction"] is not None and row["dot"] < -1e-9:
                raise PreparationError(
                    "panel.contact_side_ambiguous",
                    f"The {label} profile element {row['element']['id']} faces away from "
                    "the seal in the predicted first-contact neighborhood.",
                    stage="components",
                    role=role,
                    label=label,
                    element=row["element"]["id"],
                    fraction=row.get("contact_fraction"),
                    direction=row["direction"],
                )
        return oriented

    if direction is None:
        raise PreparationError(
            "panel.contact_side_ambiguous",
            f"The {label} profile touches or crosses the nearest seal surface, so its "
            "contact side cannot be measured.",
            stage="components",
            role=role,
            label=label,
        )
    rows = _first_contact(_contact_alignment(ordered, nodes, seal, offset, delta))
    score = sum(row["dot"] for row in rows)
    oriented = _reverse_chain(ordered) if score < 0 else ordered
    check = _first_contact(_contact_alignment(oriented, nodes, seal, offset, delta))
    if not check or sum(row["dot"] for row in check) <= 1e-9:
        raise PreparationError(
            "panel.contact_side_ambiguous",
            f"The {label} profile's first-contact neighborhood does not have one "
            "unambiguous seal-facing side. Review the drawing or its placement.",
            stage="components",
            role=role,
            label=label,
        )
    for row in check:
        if row["direction"] is not None and row["dot"] < -1e-6:
            raise PreparationError(
                "panel.contact_side_ambiguous",
                f"The {label} profile element {row['element']['id']} faces away from "
                "the seal in the predicted first-contact neighborhood.",
                stage="components",
                role=role,
                label=label,
                element=row["element"]["id"],
            )
    return oriented


def _contact_properties(project, has_body):
    """Contact interactions and surface assignments for the selected basis.

    Legacy revisions keep the exact single ``SEAL_CONTACT`` property and
    ``all exterior`` domain they were solved with. New setups declare the three
    independent interfaces explicitly: door panel to seal, body panel to seal
    when the body participates, and seal self-contact. The interior bonded
    partition seam is not part of ``SEAL_EXTERIOR``, and no rigid-to-rigid
    pairing is included.
    """
    contact = project.contact
    legacy = project.schema_version < 4 or contact.friction is not None
    if legacy:
        mu = contact.friction if contact.friction is not None else 0.3
        return [
            "*Surface Interaction, name=SEAL_CONTACT",
            scalar(project.analysis.thickness),
            "*Surface Behavior, pressure-overclosure=HARD",
            "*Friction, slip tolerance=0.005",
            scalar(mu),
            "*Contact",
            "*Contact Inclusions, all exterior",
            "*Contact Property Assignment",
            ", , SEAL_CONTACT",
        ]
    # Abaqus creates assembly-level surfaces named <assembly>_<instance>_<name>;
    # general contact data must reference those, not the part-level source names.
    seal = "ASSEMBLY_WS-1_SEAL_EXTERIOR"
    door = "ASSEMBLY_PANEL-1_PANEL_FACE"
    body = "ASSEMBLY_BODY-1_BODY_FACE"
    pairs = []
    lines = []
    for name, mu in (
        ("DOOR_SEAL", contact.door_seal),
        *((("BODY_SEAL", contact.body_seal),) if has_body else ()),
        ("SEAL_SELF", contact.seal_self),
    ):
        lines += [
            f"*Surface Interaction, name={name}",
            scalar(project.analysis.thickness),
            "*Surface Behavior, pressure-overclosure=HARD",
            "*Friction, slip tolerance=0.005",
            scalar(mu),
        ]
        pairs.append((name, mu))
    lines.append("*Contact")
    lines.append("*Contact Inclusions")
    lines.append(f"{seal}, {door}")
    if has_body:
        lines.append(f"{seal}, {body}")
    lines.append(f"{seal}, {seal}")
    lines.append("*Contact Property Assignment")
    lines.append(f"{seal}, {door}, DOOR_SEAL")
    if has_body:
        lines.append(f"{seal}, {body}, BODY_SEAL")
    lines.append(f"{seal}, , SEAL_SELF")
    return lines


def _motion_boundary_lines(resolved, reference):
    """Prescribed U1/U2 targets; both components are always written for v4."""
    dx, dy = resolved["delta"]
    return [f"{reference}, 1, 1, {scalar(dx)}", f"{reference}, 2, 2, {scalar(dy)}"]


def _motion_boundary_legacy(travel, reference):
    return [f"{reference}, 2, 2, {scalar(travel)}"]


def write_inp(project, mesh, fixture=None):
    if project.analysis.mode == "body_then_door":
        return write_two_step_inp(project, mesh, fixture)
    nodes, ws, panel = mesh_parts(project, mesh)
    boundary = exterior(ws)
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
    clearance = door["clearance_mm"]
    resolved = motion_policy.resolve(project.motion, project.schema_version)
    # SPOS must face the seal; a door mounted above it keeps the legacy order and
    # an oblique/curved setup follows the locally measured direction to the
    # nearest surface, verified at the predicted first-contact neighborhood.
    if project.schema_version >= 4:
        panel = orient_toward(
            panel,
            nodes,
            door["direction_to_seal"],
            seal=_boundary_segments(nodes, boundary),
            role="door",
            label="door",
            offset=project.motion.offset,
            delta=door["delta_mm"],
        )
    else:
        panel = orient_for_contact(panel, door["side"])
    seal_nodes = sorted({n for e in ws for n in e["nodes"]})
    panel_nodes = sorted({n for e in panel for n in e["nodes"]})
    seal_node_set = set(seal_nodes)
    fixed = set(fixed_nodes(project, mesh, fixture))
    if not fixed <= seal_node_set:
        raise ValueError("A fixed node is missing from the seal mesh. Review the fixture.")
    source = "reviewed mesh nodes" if fixture is not None else "legacy mounting edges"

    lines = [
        "*Heading",
        "Abaqus QOL 2D plane stress / implicit dynamic closing",
        "** Units: N, mm, s, tonne. Panel RF2 is total reaction for the specified thickness.",
        f"** Initial nearest clearance on the assembled mesh: {scalar(clearance)} mm"
        f" ({side_phrase(door.get('initial_side') or door['side'])}).",
        (
            f"** First contact at {scalar(door['first_contact_fraction'])} of travel "
            f"({scalar(door['contact_target']['travel_mm'])} mm) on seal segment "
            f"[{', '.join(scalar(value) for value in door['contact_target']['seal_segments'][0])}] mm; "
            f"approach [{', '.join(scalar(value) for value in door['contact_target']['approach'])}]."
            if door.get("contact_target")
            else "** No first contact on the prescribed path."
        ),
        f"** Door travel direction: [{', '.join(scalar(v) for v in door['direction'])}]; "
        f"contact side: {side_phrase(door.get('contact_side') or 'not reached')}.",
        f"** Prescribed motion: {scalar(resolved['stroke'])} mm at "
        f"{scalar(resolved['angle'])} deg; delta "
        f"[{', '.join(scalar(v) for v in resolved['delta'])}] mm from initial placement.",
        f"** Fixed weatherstrip nodes: {len(fixed)} from {source}.",
        "*Part, name=WS",
        "*Node",
    ]
    lines += [f"{n}, {scalar(nodes[n][0])}, {scalar(nodes[n][1])}" for n in seal_nodes]
    by_face = defaultdict(list)
    for kind in ("CPS3", "CPS4", "CPS4R"):
        elements = [e for e in ws if e["type"] == kind]
        if elements:
            lines.append(f"*Element, type={kind}")
            for e in elements:
                lines.append(", ".join(map(str, [e["id"], *e["nodes"]])))
                by_face[e["entity"]].append(e["id"])
    mat_names = {m.id: f"MAT_{i + 1}" for i, m in enumerate(project.materials)}
    for i, face in enumerate(project.faces, 1):
        if face.id not in by_face:
            continue  # Material-free cavity and other non-meshed faces have no section.
        if face.material not in mat_names:
            raise ValueError("Assign a material to every meshed seal region.")
        name = f"REGION_{i}"
        lines += set_lines(f"*Elset, elset={name}", by_face[face.id])
        lines += [
            f"*Solid Section, elset={name}, material={mat_names[face.material]}",
            f"{scalar(project.analysis.thickness)},",
        ]
    edge_sets = defaultdict(list)
    component_role = {c.id: c.role for c in project.components}
    for i, edge in enumerate(project.edges, 1):
        if edge.id in mesh["edge_nodes"]:
            edge_sets[component_role[edge.component]].extend(
                set_lines(f"*Nset, nset=EDGE_{i}", mesh["edge_nodes"][edge.id])
            )
    lines += edge_sets["seal"]
    lines += ["*Surface, type=ELEMENT, name=SEAL_EXTERIOR"]
    lines += [f"{eid}, S{side}" for eid, side in boundary.values()]
    lines += ["*End Part", "*Part, name=PANEL", "*Node"]
    lines += [f"{n}, {scalar(nodes[n][0])}, {scalar(nodes[n][1])}" for n in panel_nodes]
    rp = max(panel_nodes) + 1
    midpoint = [sum(nodes[n][axis] for n in panel_nodes) / len(panel_nodes) for axis in (0, 1)]
    lines += [
        f"{rp}, {scalar(midpoint[0])}, {scalar(midpoint[1])}",
        "*Element, type=R2D2, elset=PROFILE",
    ]
    lines += [", ".join(map(str, [e["id"], *e["nodes"]])) for e in panel]
    lines += edge_sets["moving_panel"]
    lines += [
        "*Surface, type=ELEMENT, name=PANEL_FACE",
        "PROFILE, SPOS",
        "*End Part",
        "*Assembly, name=ASSEMBLY",
        "*Instance, name=WS-1, part=WS",
        "*End Instance",
        "*Instance, name=PANEL-1, part=PANEL",
        f"0., {scalar(project.motion.offset)}, 0.",
        "*End Instance",
        "*Nset, nset=PANEL_RP, instance=PANEL-1",
        str(rp),
    ]
    if getattr(project.analysis, "door_pressure", False):
        lines += set_lines(
            "*Nset, nset=DOOR_PROFILE_NODES, instance=PANEL-1", door_profile_labels(panel)
        )
    lines += set_lines("*Nset, nset=WSFIX, instance=WS-1", fixed)
    lines += ["*Rigid Body, ref node=PANEL_RP, elset=PANEL-1.PROFILE", "*End Assembly"]
    assigned = {face.material for face in project.faces if face.id in by_face}
    for material in project.materials:
        if material.id in assigned:
            lines += material_cards(material, mat_names[material.id])
    lines += _contact_properties(project, has_body=False)
    lines += [
        "*Boundary",
        "WSFIX, ENCASTRE",
        "PANEL_RP, 1, 2",
        "PANEL_RP, 6, 6",
        "*Step, name=Closing, nlgeom=YES, amplitude=RAMP, inc=100000, unsymm=YES",
        "*Dynamic",
        f"{scalar(min(0.0001, project.motion.duration / 100))}, {scalar(project.motion.duration)}, 1e-13",
        "*Boundary",
    ]
    if project.schema_version >= 4:
        lines += _motion_boundary_lines(resolved, "PANEL_RP")
    else:
        lines += _motion_boundary_legacy(project.motion.travel, "PANEL_RP")
    lines += output_cards(project)
    return "\n".join(lines + ["*End Step", ""])


def write_two_step_inp(project, mesh, fixture=None):
    """Body seating followed by door closing in one analysis.

    Step 1 moves the body reference point and holds the door; step 2 holds the
    body at its attained position and moves the door. A zero body or door travel
    is a valid hold, written as an explicit zero displacement, never an epsilon.
    Boundary conditions are propagated by Abaqus, so the seal deformation and
    contact state from step 1 are the starting state of step 2. No second
    analysis or ``op=NEW`` reset is used.
    """
    nodes, ws, panel, body = _mesh_parts(project, mesh)
    boundary = exterior(ws)
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
    seated = motion_assessment(
        nodes,
        boundary,
        body,
        project.motion.body,
        role="body",
        instance="BODY-1",
        label="body",
        schema_version=project.schema_version,
    )
    door_motion = motion_policy.resolve(project.motion, project.schema_version)
    body_motion = motion_policy.resolve(project.motion.body, project.schema_version, body=True)
    # Each rigid part is oriented independently: the door above the seal keeps
    # the legacy right-to-left order, the body below it is turned around so its
    # SPOS side faces up toward the seal. Curved returns are decided and checked
    # at the predicted first-contact neighborhood.
    if project.schema_version >= 4:
        seal_segments = _boundary_segments(nodes, boundary)
        panel = orient_toward(
            panel,
            nodes,
            door["direction_to_seal"],
            seal=seal_segments,
            role="door",
            label="door",
            offset=project.motion.offset,
            delta=door["delta_mm"],
        )
        body = orient_toward(
            body,
            nodes,
            seated["direction_to_seal"],
            seal=seal_segments,
            role="body",
            label="body",
            offset=project.motion.body.offset,
            delta=seated["delta_mm"],
        )
    else:
        panel = orient_for_contact(panel, door["side"])
        body = orient_for_contact(body, seated["side"])
    seal_nodes = sorted({n for e in ws for n in e["nodes"]})
    panel_nodes = sorted({n for e in panel for n in e["nodes"]})
    body_nodes = sorted({n for e in body for n in e["nodes"]})
    seal_node_set = set(seal_nodes)
    fixed = set(fixed_nodes(project, mesh, fixture))
    if not fixed <= seal_node_set:
        raise ValueError("A fixed node is missing from the seal mesh. Review the fixture.")
    source = "reviewed mesh nodes" if fixture is not None else "legacy mounting edges"

    component_role = {c.id: c.role for c in project.components}
    edge_sets = defaultdict(list)
    for i, edge in enumerate(project.edges, 1):
        if edge.id in mesh["edge_nodes"]:
            edge_sets[component_role[edge.component]].extend(
                set_lines(f"*Nset, nset=EDGE_{i}", mesh["edge_nodes"][edge.id])
            )

    lines = [
        "*Heading",
        "Abaqus QOL 2D plane stress / implicit dynamic body seating then door closing",
        "** Units: N, mm, s, tonne. RF2 is total reaction for the specified thickness.",
        f"** Initial door clearance on the assembled mesh: {scalar(door['clearance_mm'])} mm; "
        f"door is {side_phrase(door['side'])}.",
        f"** Initial body clearance on the assembled mesh: {scalar(seated['clearance_mm'])} mm; "
        f"body is {side_phrase(seated['side'])}.",
        f"** Step 1 body motion: {scalar(body_motion['stroke'])} mm at "
        f"{scalar(body_motion['angle'])} deg over {scalar(project.motion.body.duration)} s; "
        f"delta [{', '.join(scalar(v) for v in body_motion['delta'])}] mm. Door held.",
        f"** Step 2 door motion: {scalar(door_motion['stroke'])} mm at "
        f"{scalar(door_motion['angle'])} deg over {scalar(project.motion.duration)} s; "
        f"delta [{', '.join(scalar(v) for v in door_motion['delta'])}] mm. Body held at its seated position.",
        f"** Fixed weatherstrip nodes: {len(fixed)} from {source}.",
        "*Part, name=WS",
        "*Node",
    ]
    lines += [f"{n}, {scalar(nodes[n][0])}, {scalar(nodes[n][1])}" for n in seal_nodes]
    by_face = defaultdict(list)
    for kind in ("CPS3", "CPS4", "CPS4R"):
        elements = [e for e in ws if e["type"] == kind]
        if elements:
            lines.append(f"*Element, type={kind}")
            for e in elements:
                lines.append(", ".join(map(str, [e["id"], *e["nodes"]])))
                by_face[e["entity"]].append(e["id"])
    mat_names = {m.id: f"MAT_{i + 1}" for i, m in enumerate(project.materials)}
    for i, face in enumerate(project.faces, 1):
        if face.id not in by_face:
            continue
        if face.material not in mat_names:
            raise ValueError("Assign a material to every meshed seal region.")
        name = f"REGION_{i}"
        lines += set_lines(f"*Elset, elset={name}", by_face[face.id])
        lines += [
            f"*Solid Section, elset={name}, material={mat_names[face.material]}",
            f"{scalar(project.analysis.thickness)},",
        ]
    lines += edge_sets["seal"]
    lines += ["*Surface, type=ELEMENT, name=SEAL_EXTERIOR"]
    lines += [f"{eid}, S{side}" for eid, side in boundary.values()]

    def rigid_part(part, elements, element_nodes, surface, extra_sets, side):
        lines_local = ["*End Part", f"*Part, name={part}", "*Node"]
        lines_local += [
            f"{n}, {scalar(nodes[n][0])}, {scalar(nodes[n][1])}" for n in element_nodes
        ]
        reference = max(element_nodes) + 1
        midpoint = [
            sum(nodes[n][axis] for n in element_nodes) / len(element_nodes) for axis in (0, 1)
        ]
        lines_local += [
            f"{reference}, {scalar(midpoint[0])}, {scalar(midpoint[1])}",
            "*Element, type=R2D2, elset=PROFILE",
        ]
        lines_local += [
            ", ".join(map(str, [e["id"], *e["nodes"]])) for e in elements
        ]
        lines_local += extra_sets
        lines_local += [
            # Connectivity was ordered above so SPOS faces the seal; the test
            # suite recomputes each normal from this connectivity.
            f"** {part} is {side_phrase(side)}; SPOS faces the seal.",
            f"*Surface, type=ELEMENT, name={surface}",
            "PROFILE, SPOS",
        ]
        return lines_local, reference

    panel_part, panel_rp = rigid_part(
        "PANEL", panel, panel_nodes, "PANEL_FACE", edge_sets["moving_panel"], door["side"]
    )
    lines += panel_part
    body_part, body_rp = rigid_part(
        "BODY", body, body_nodes, "BODY_FACE", edge_sets["vehicle_body"], seated["side"]
    )
    lines += body_part
    lines += [
        "*End Part",
        "*Assembly, name=ASSEMBLY",
        "*Instance, name=WS-1, part=WS",
        "*End Instance",
        "*Instance, name=PANEL-1, part=PANEL",
        f"0., {scalar(project.motion.offset)}, 0.",
        "*End Instance",
        "*Instance, name=BODY-1, part=BODY",
        f"0., {scalar(project.motion.body.offset)}, 0.",
        "*End Instance",
        "*Nset, nset=PANEL_RP, instance=PANEL-1",
        str(panel_rp),
        "*Nset, nset=BODY_RP, instance=BODY-1",
        str(body_rp),
    ]
    if getattr(project.analysis, "door_pressure", False):
        lines += set_lines(
            "*Nset, nset=DOOR_PROFILE_NODES, instance=PANEL-1", door_profile_labels(panel)
        )
    lines += set_lines("*Nset, nset=WSFIX, instance=WS-1", fixed)
    lines += [
        "*Rigid Body, ref node=PANEL_RP, elset=PANEL-1.PROFILE",
        "*Rigid Body, ref node=BODY_RP, elset=BODY-1.PROFILE",
        "*End Assembly",
    ]
    assigned = {face.material for face in project.faces if face.id in by_face}
    for material in project.materials:
        if material.id in assigned:
            lines += material_cards(material, mat_names[material.id])
    lines += _contact_properties(project, has_body=True)
    lines += [
        "*Boundary",
        "WSFIX, ENCASTRE",
        "PANEL_RP, 1, 2",
        "PANEL_RP, 6, 6",
        "BODY_RP, 1, 2",
        "BODY_RP, 6, 6",
        "*Step, name=Body seating, nlgeom=YES, amplitude=RAMP, inc=100000, unsymm=YES",
        "*Dynamic",
        f"{scalar(min(0.0001, project.motion.body.duration / 100))}, "
        f"{scalar(project.motion.body.duration)}, 1e-13",
        "*Boundary",
    ]
    if project.schema_version >= 4:
        lines += _motion_boundary_lines(body_motion, "BODY_RP")
        lines += _motion_boundary_lines(
            {"delta": [0.0, 0.0]}, "PANEL_RP"
        )
    else:
        lines += [
            f"BODY_RP, 2, 2, {scalar(project.motion.body.travel)}",
            "PANEL_RP, 2, 2, 0.",
        ]
    lines += output_cards(
        project,
        duration=project.motion.body.duration,
        references=("BODY_RP", "PANEL_RP"),
    )
    lines += [
        "*End Step",
        "*Step, name=Closing, nlgeom=YES, amplitude=RAMP, inc=100000, unsymm=YES",
        "*Dynamic",
        f"{scalar(min(0.0001, project.motion.duration / 100))}, "
        f"{scalar(project.motion.duration)}, 1e-13",
        "*Boundary",
    ]
    if project.schema_version >= 4:
        # Hold the body at the position reached in step 1 in both components;
        # the door ramps closed along its prescribed direction.
        lines += _motion_boundary_lines(body_motion, "BODY_RP")
        lines += _motion_boundary_lines(door_motion, "PANEL_RP")
    else:
        # Hold the body at the position reached in step 1; the door ramps closed.
        lines += [
            f"BODY_RP, 2, 2, {scalar(project.motion.body.travel)}",
            f"PANEL_RP, 2, 2, {scalar(project.motion.travel)}",
        ]
    lines += output_cards(
        project,
        duration=project.motion.duration,
        references=("BODY_RP", "PANEL_RP"),
    )
    return "\n".join(lines + ["*End Step", ""])


def door_profile_labels(panel):
    """Every geometric door-profile node once. The rigid RP is not an element node."""
    return sorted({node for element in panel for node in element["nodes"]})


def output_cards(project, duration=None, references=("PANEL_RP",)):
    """Field/history output for one step.

    Door-panel contact pressure is requested once per step. When global
    ``CSTRESS`` is selected the door NSET asks only for ``CFORCE`` so the same
    pressure identity is never requested twice; otherwise the door NSET asks for
    ``CFORCE, CSTRESS`` together. That is the pattern whose duplicate and
    single-request behaviour was measured in the licensed pilots.
    """
    duration = project.motion.duration if duration is None else duration
    interval = scalar(min(0.02, duration / 20))
    outputs = set(project.analysis.outputs)
    door = bool(getattr(project.analysis, "door_pressure", False))
    lines = [f"*Output, field, time interval={interval}"] if outputs or door else []
    node_outputs = set(outputs.intersection({"U", "RF"}))
    if door:
        # The deformed arrow anchor needs door U even if the wider U field is off.
        node_outputs.add("U")
    if node_outputs:
        lines += ["*Node Output", ", ".join(sorted(node_outputs))]
    element_outputs = sorted(outputs.intersection({"S", "LE"}))
    if element_outputs:
        lines += ["*Element Output", ", ".join(element_outputs)]
    if door:
        if "CSTRESS" in outputs:
            lines += ["*Contact Output", "CSTRESS"]
            lines += ["*Contact Output, nset=DOOR_PROFILE_NODES", "CFORCE"]
        else:
            lines += ["*Contact Output, nset=DOOR_PROFILE_NODES", "CFORCE, CSTRESS"]
    elif "CSTRESS" in outputs:
        lines += ["*Contact Output", "CSTRESS"]
    lines.append(f"*Output, history, time interval={interval}")
    for reference in references:
        lines += [
            f"*Node Output, nset={reference}",
            # Signed global components are retained; the chart projects them onto
            # the configured motion direction without altering this raw history.
            "U1, U2, RF1, RF2",
        ]
    return lines
