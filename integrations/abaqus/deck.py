"""Supported 2-D vertical closing template. User strings never become INP keywords."""

from collections import defaultdict
from math import hypot, isfinite

from packages.engineering import fixture as fixtures

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


def motion_assessment(nodes, boundary, elements, motion, role, instance, label):
    """Clearance, assembled side, direction and hold/gap reach for one profile."""
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
            label="door",
        ),
        "body": None,
    }
    if body:
        result["body"] = motion_assessment(
            nodes, boundary, body, project.motion.body, role="body", instance="BODY-1",
            label="body",
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


def write_inp(project, mesh, fixture=None):
    if project.analysis.mode == "body_then_door":
        return write_two_step_inp(project, mesh, fixture)
    nodes, ws, panel = mesh_parts(project, mesh)
    boundary = exterior(ws)
    door = motion_assessment(
        nodes, boundary, panel, project.motion, role="door", instance="PANEL-1", label="door"
    )
    clearance = door["clearance_mm"]
    # SPOS must face the seal; a door mounted above it keeps the legacy order.
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
        f"** Initial vertical clearance on the assembled mesh: {scalar(clearance)} mm.",
        f"** Door is {door['side']} the seal; the contact normal and travel direction are "
        f"[{', '.join(scalar(v) for v in door['direction'])}].",
        f"** Prescribed Y travel: {scalar(project.motion.travel)} mm; measured from initial placement.",
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
    lines += [
        "*Surface Interaction, name=SEAL_CONTACT",
        scalar(project.analysis.thickness),
        "*Surface Behavior, pressure-overclosure=HARD",
        "*Friction, slip tolerance=0.005",
        scalar(project.contact.friction),
        "*Contact",
        "*Contact Inclusions, all exterior",
        "*Contact Property Assignment",
        ", , SEAL_CONTACT",
        "*Boundary",
        "WSFIX, ENCASTRE",
        "PANEL_RP, 1, 2",
        "PANEL_RP, 6, 6",
        "*Step, name=Closing, nlgeom=YES, amplitude=RAMP, inc=100000, unsymm=YES",
        "*Dynamic",
        f"{scalar(min(0.0001, project.motion.duration / 100))}, {scalar(project.motion.duration)}, 1e-13",
        "*Boundary",
        f"PANEL_RP, 2, 2, {scalar(project.motion.travel)}",
    ]
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
        nodes, boundary, panel, project.motion, role="door", instance="PANEL-1", label="door"
    )
    seated = motion_assessment(
        nodes, boundary, body, project.motion.body, role="body", instance="BODY-1", label="body"
    )
    # Each rigid part is oriented independently: the door above the seal keeps
    # the legacy right-to-left order, the body below it is turned around so its
    # SPOS side faces up toward the seal.
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
        f"** Step 1 body travel: {scalar(project.motion.body.travel)} mm over "
        f"{scalar(project.motion.body.duration)} s; body direction "
        f"[{', '.join(scalar(v) for v in seated['direction'])}]. Door held.",
        f"** Step 2 door travel: {scalar(project.motion.travel)} mm over "
        f"{scalar(project.motion.duration)} s; door direction "
        f"[{', '.join(scalar(v) for v in door['direction'])}]. Body held at its seated position.",
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
    lines += [
        "*Surface Interaction, name=SEAL_CONTACT",
        scalar(project.analysis.thickness),
        "*Surface Behavior, pressure-overclosure=HARD",
        "*Friction, slip tolerance=0.005",
        scalar(project.contact.friction),
        "*Contact",
        "*Contact Inclusions, all exterior",
        "*Contact Property Assignment",
        ", , SEAL_CONTACT",
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
        # Hold the body at the position reached in step 1; the door ramps closed.
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
