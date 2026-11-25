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
    profile that merely sits between the upper and lower exterior surfaces.
    """
    for x, y in points:
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


def _polyline(segments):
    """A multi-segment polyline for geometric distance and nearest-point work."""
    from shapely.geometry import MultiLineString

    return MultiLineString([[(s[0], s[1]), (s[2], s[3])] for s in segments])


def _swept_contact(profile_geom, seal_geom, delta, samples=200):
    """First fraction of the prescribed path that touches the seal, if any.

    The translated profile's Euclidean distance to the seal surface is sampled
    along the swept segment and bracketed to a tight tolerance. A path that
    passes through the seal between two samples is still caught because the
    sample spacing is far below any engineering feature in this template.
    """
    dx, dy = delta
    if hypot(dx, dy) <= CLEARANCE_TOLERANCE:
        return None, 0.0
    if profile_geom.distance(seal_geom) <= CLEARANCE_TOLERANCE:
        return 0.0, 0.0
    previous_t, previous_d = 0.0, profile_geom.distance(seal_geom)
    closest = (previous_d, 0.0)
    for index in range(1, samples + 1):
        t = index / samples
        distance = translate(profile_geom, dx * t, dy * t).distance(seal_geom)
        if distance < closest[0]:
            closest = (distance, t)
        if distance <= 1e-6:
            low, high = previous_t, t
            for _ in range(60):
                middle = (low + high) / 2.0
                if (
                    translate(profile_geom, dx * middle, dy * middle).distance(seal_geom)
                    <= 1e-6
                ):
                    high = middle
                else:
                    low = middle
            return high, closest[0]
        previous_t, previous_d = t, distance
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
    direction = _direction_to_seal(profile_geom, seal_geom)
    side = _side_from_direction(direction)
    if side is None:
        raise ClearanceError(
            "side_ambiguous",
            f"The {label} profile touches or crosses the nearest seal surface, so its "
            "contact normal is ambiguous. Review its initial placement.",
            label=label,
        )
    initial = profile_geom.distance(seal_geom)
    first_t, closest = _swept_contact(profile_geom, seal_geom, delta)
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
    path = (
        "hold"
        if resolved["stroke"] == 0
        else (
            "touching"
            if first_t == 0.0
            else ("contact" if first_t is not None else ("approaching" if approaching else "missed"))
        )
    )
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


def _contact_alignment(ordered, nodes, seal, offset=0.0, delta=None):
    """Signed local alignment of every SPOS normal with its nearest seal point.

    A single global average is not enough evidence on a curved return: each
    element is measured against the direction from its *assembled* midpoint to
    the closest seal surface, and the predicted first-contact neighborhood is
    selected by the actual swept distance rather than by the undeformed drawing.
    The persisted placement offset and motion vector therefore decide the
    orientation, not the drawing's original coordinates.
    """
    from shapely.geometry import LineString, Point
    from shapely.ops import nearest_points

    seal_geom = _polyline(seal)
    swept = delta is not None and hypot(float(delta[0]), float(delta[1])) > CLEARANCE_TOLERANCE
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
        if swept:
            from shapely.geometry import LineString
            from shapely.ops import nearest_points as _nearest

            end = (placed.x + delta[0], placed.y + delta[1])
            path = LineString([(placed.x, placed.y), end])
            sweep_distance = path.distance(seal_geom)
            on_path, _on_seal = _nearest(path, seal_geom)
            dx, dy = end[0] - placed.x, end[1] - placed.y
            denominator = dx * dx + dy * dy
            contact_fraction = (
                max(
                    0.0,
                    min(
                        1.0,
                        ((on_path.x - placed.x) * dx + (on_path.y - placed.y) * dy)
                        / denominator,
                    ),
                )
                if denominator > 0
                else 0.0
            )
        if distance <= CLEARANCE_TOLERANCE:
            direction = None
            dot = 0.0
        else:
            on_profile, on_seal = nearest_points(placed, seal_geom)
            dx, dy = on_seal.x - on_profile.x, on_seal.y - on_profile.y
            length = hypot(dx, dy)
            direction = None if length <= CLEARANCE_TOLERANCE else [dx / length, dy / length]
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
            }
        )
    return rows


# mm. The predicted first-contact neighborhood: elements within this distance of
# the closest element. Orientation and its independent verification both use it.
CONTACT_NEIGHBORHOOD_MM = 0.5


def _first_contact(rows):
    if not rows:
        return []
    # The first-contact neighborhood is the earliest band along the prescribed
    # sweep, not every element whose path eventually crosses the seal: a curved
    # return can otherwise pull in segments that face away and never touch
    # first. The 5% band is measured on the actual stroke.
    fractions = [row["contact_fraction"] for row in rows if row.get("contact_fraction") is not None]
    if fractions:
        earliest = min(fractions)
        band = [
            row
            for row in rows
            if row.get("contact_fraction") is not None
            and row["contact_fraction"] <= earliest + 0.05
        ]
        if band:
            return band
    metric = "sweep_distance" if any("sweep_distance" in row for row in rows) else "distance"
    closest = min(row[metric] for row in rows)
    limit = closest + max(CONTACT_NEIGHBORHOOD_MM, closest * 0.02)
    return [row for row in rows if row[metric] <= limit + CLEARANCE_TOLERANCE]


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

    With ``seal`` (the exterior seal segments) the decision is made at the
    predicted first-contact neighborhood of the *assembled* profile including
    its persisted offset and motion sweep, not from one global average or from
    the drawing's original coordinates. The oriented normals are re-checked
    there. Without it the historical global projection is kept for callers that
    have no boundary at hand.
    """
    if direction is None:
        raise PreparationError(
            "panel.contact_side_ambiguous",
            f"The {label} profile touches or crosses the nearest seal surface, so its "
            "contact side cannot be measured.",
            stage="components",
            role=role,
            label=label,
        )
    if seal is None:
        total = 0.0
        for element in ordered:
            normal = surface_normal(nodes, element)
            total += normal[0] * direction[0] + normal[1] * direction[1]
        return _reverse_chain(ordered) if total < 0 else ordered

    rows = _first_contact(_contact_alignment(ordered, nodes, seal, offset, delta))
    score = sum(row["dot"] for row in rows)
    oriented = _reverse_chain(ordered) if score < 0 else ordered
    # Re-measure the oriented connectivity. This is the independent local check
    # the brief requires: every element in the predicted first-contact
    # neighborhood must now face the seal, not merely their average.
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
        f"** Initial clearance on the assembled mesh: {scalar(clearance)} mm.",
        f"** Door is {side_phrase(door['side'])}; the contact normal and travel direction are "
        f"[{', '.join(scalar(v) for v in door['direction'])}].",
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
