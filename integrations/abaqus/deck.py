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


class ClearanceError(ValueError):
    """A geometric clearance rejection with a stable code for diagnostics.

    ``details`` carries the measured quantities (panel label, penetration
    depth, contact side) so the API can explain the same condition the deck
    writer refuses, without the caller parsing prose.
    """

    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.details = details


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


def panel_order(panel, nodes):
    """Follow one open chain from its right end.

    For an R2D2 segment whose nodes run from 1 to 2 the SPOS side is 90 degrees
    counter-clockwise from the 1-to-2 direction, which is the lower side for a
    horizontal panel read right-to-left. ``orient_for_contact`` reverses this
    ordering for a profile mounted below the seal.
    """
    neighbors = defaultdict(list)
    for e in panel:
        a, b = e["nodes"]
        neighbors[a].append((b, e))
        neighbors[b].append((a, e))
    ends = [n for n, adjacent in neighbors.items() if len(adjacent) == 1]
    if len(ends) != 2 or any(len(adjacent) > 2 for adjacent in neighbors.values()):
        raise ValueError("Use one open, unbranched moving panel profile.")
    if nodes[ends[0]][0] == nodes[ends[1]][0]:
        raise ValueError(
            "The vertical closing template needs panel endpoints at different X positions."
        )
    current = max(ends, key=lambda n: nodes[n][0])
    previous = None
    ordered = []
    while True:
        next_segment = [(n, e) for n, e in neighbors[current] if n != previous]
        if not next_segment:
            break
        n, element = next_segment[0]
        if nodes[n][0] > nodes[current][0] + 1e-9:
            raise ValueError(
                "The vertical closing template requires a panel without a folded-back profile."
            )
        ordered.append(dict(element, nodes=[current, n]))
        previous, current = current, n
    if len(ordered) != len(panel):
        raise ValueError("The moving panel has disconnected paths.")
    return ordered


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
        raise ValueError("Only the 2D plane-stress closing template can generate a solver input.")
    if project.units != "N-mm-s-tonne":
        raise ValueError("Confirm N-mm-s-tonne units before generating this input.")
    # Travel 0 is a valid hold; a nonzero travel is checked against the measured
    # contact side below, so the template never substitutes an epsilon motion.
    nodes = {n["id"]: n["xyz"] for n in mesh["nodes"]}
    if len(nodes) != len(mesh["nodes"]):
        raise ValueError("Duplicate mesh node label.")
    roles = {c.id: c.role for c in project.components}
    faces = {f.id: f for f in project.faces}
    materials = {m.id: m for m in project.materials}
    if sum(role == "moving_panel" for role in roles.values()) != 1:
        raise ValueError("Select exactly one moving panel.")
    if any(role not in ("seal", "moving_panel", "vehicle_body") for role in roles.values()):
        raise ValueError(
            "This solver template supports seal regions, one moving panel and an excluded body profile."
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
            raise ValueError("Unsupported element type, duplicate label, or invalid connectivity.")
        element_ids.add(e["id"])
        if kind == "R2D2":
            role = roles.get(e["component"])
            if role == "moving_panel":
                panel.append(e)
            elif role == "vehicle_body" and project.analysis.mode == "body_then_door":
                body.append(e)
            else:
                raise ValueError("A rigid edge must belong to an analysed rigid profile.")
        else:
            face = faces.get(e["entity"])
            if (
                face is None
                or roles.get(e["component"]) != "seal"
                or face.component != e["component"]
            ):
                raise ValueError("Every continuum element must refer to a CAD region of its seal.")
            # Rubber quadrilaterals are always reduced integration. A forged or
            # legacy mesh that reaches the writer as CPS4 is rejected rather
            # than silently relabelled.
            material = materials.get(face.material) if face.material else None
            if (
                kind == "CPS4"
                and material is not None
                and material.model in ("hyperfoam_test", "neo_hookean")
            ):
                raise ValueError(
                    f"Rubber quadrilateral element {e['id']} is CPS4; rubber uses "
                    "reduced integration (CPS4R). Regenerate the mesh."
                )
            if (
                kind == "CPS4R"
                and material is not None
                and getattr(material, "family", "polymer") == "metal"
            ):
                raise ValueError(
                    f"Metal quadrilateral element {e['id']} is CPS4R; deformable metal uses "
                    "full integration (CPS4). Regenerate the mesh."
                )
            points = [nodes[n] for n in node_ids]
            for i, point in enumerate(points):
                prev, nxt = points[i - 1], points[(i + 1) % len(points)]
                cross = (point[0] - prev[0]) * (nxt[1] - point[1]) - (point[1] - prev[1]) * (
                    nxt[0] - point[0]
                )
                if not isfinite(cross) or cross <= 0:
                    raise ValueError("A seal element has inverted or degenerate connectivity.")
            ws.append(e)
    if not ws or not panel:
        raise ValueError("Both a deformable seal mesh and a moving rigid profile are required.")
    if project.analysis.mode == "body_then_door" and not body:
        raise ValueError("Body-then-door analysis needs a meshed moving body profile.")
    return (
        nodes,
        ws,
        panel_order(panel, nodes),
        panel_order(body, nodes) if body else [],
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
    return result


def material_cards(material, name):
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


def orient_toward(ordered, nodes, direction):
    """Order R2D2 connectivity so SPOS faces an explicit model-space direction.

    Used for an oblique setup, where "above/below" is not sufficient: the
    assembly assessor supplies the unit vector from the assembled profile to its
    nearest seal surface, and the connectivity is reversed only when the mean
    SPOS normal points away from it.
    """
    if direction is None:
        raise ValueError("An oblique rigid profile needs a measured contact direction.")
    total = 0.0
    for element in ordered:
        normal = surface_normal(nodes, element)
        total += normal[0] * direction[0] + normal[1] * direction[1]
    if total >= 0:
        return ordered
    return [
        dict(element, nodes=[element["nodes"][1], element["nodes"][0]])
        for element in reversed(ordered)
    ]


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
    # an oblique setup follows the measured direction to the nearest surface.
    if project.schema_version >= 4:
        panel = orient_toward(panel, nodes, door["direction_to_seal"])
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
        f"** Door is {door['side']} the seal; the contact normal and travel direction are "
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
    # SPOS side faces up toward the seal.
    if project.schema_version >= 4:
        panel = orient_toward(panel, nodes, door["direction_to_seal"])
        body = orient_toward(body, nodes, seated["direction_to_seal"])
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
        f"door is {door['side']} the seal.",
        f"** Initial body clearance on the assembled mesh: {scalar(seated['clearance_mm'])} mm; "
        f"body is {seated['side']} the seal.",
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
            f"** {part} is {side} the seal; SPOS faces the seal.",
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


def output_cards(project, duration=None, references=("PANEL_RP",)):
    duration = project.motion.duration if duration is None else duration
    interval = scalar(min(0.02, duration / 20))
    outputs = set(project.analysis.outputs)
    lines = [f"*Output, field, time interval={interval}"] if outputs else []
    node_outputs = sorted(outputs.intersection({"U", "RF"}))
    if node_outputs:
        lines += ["*Node Output", ", ".join(node_outputs)]
    element_outputs = sorted(outputs.intersection({"S", "LE"}))
    if element_outputs:
        lines += ["*Element Output", ", ".join(element_outputs)]
    if "CSTRESS" in outputs:
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
