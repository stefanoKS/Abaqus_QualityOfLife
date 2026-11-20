"""Supported 2-D vertical closing template. User strings never become INP keywords."""

from bisect import bisect_left, bisect_right
from collections import defaultdict
from math import isfinite

ELEMENT_SIZES = {"CPS3": 3, "CPS4": 4, "CPS4R": 4, "R2D2": 2}


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
    """Follow one open chain from its right end; SPOS faces down on a horizontal panel."""
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


def mesh_parts(project, mesh):
    if project.dimension != "2D" or project.formulation != "plane_stress":
        raise ValueError("Only the 2D plane-stress closing template can generate a solver input.")
    if project.units != "N-mm-s-tonne":
        raise ValueError("Confirm N-mm-s-tonne units before generating this input.")
    if project.motion.travel >= 0:
        raise ValueError("Set a negative Y travel for the vertical closing template.")
    nodes = {n["id"]: n["xyz"] for n in mesh["nodes"]}
    if len(nodes) != len(mesh["nodes"]):
        raise ValueError("Duplicate mesh node label.")
    roles = {c.id: c.role for c in project.components}
    faces = {f.id: f for f in project.faces}
    if sum(role == "moving_panel" for role in roles.values()) != 1:
        raise ValueError("Select exactly one moving panel.")
    if any(role not in ("seal", "moving_panel") for role in roles.values()):
        raise ValueError("This solver template supports seal regions and one moving panel.")
    ws, panel = [], []
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
            if roles.get(e["component"]) != "moving_panel":
                raise ValueError("A rigid edge must belong to the moving panel.")
            panel.append(e)
        else:
            face = faces.get(e["entity"])
            if (
                face is None
                or roles.get(e["component"]) != "seal"
                or face.component != e["component"]
            ):
                raise ValueError("Every continuum element must refer to a CAD region of its seal.")
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
    return nodes, ws, panel_order(panel, nodes)


def exterior(ws):
    sides = defaultdict(list)
    for e in ws:
        for i, n in enumerate(e["nodes"]):
            side = tuple(sorted((n, e["nodes"][(i + 1) % len(e["nodes"])])))
            sides[side].append((e["id"], i + 1))
    if any(len(entries) > 2 for entries in sides.values()):
        raise ValueError("Non-manifold seal mesh.")
    return {side: entries[0] for side, entries in sides.items() if len(entries) == 1}


def vertical_gap(nodes, boundary, panel, offset):
    """Minimum signed vertical separation between assembled piecewise-linear FE profiles."""
    segments = [(nodes[e["nodes"][1]], nodes[e["nodes"][0]]) for e in reversed(panel)]
    starts = [a[0] for a, _ in segments]
    ends = [b[0] for _, b in segments]

    def height(a, b, x, vertical):
        if b[0] == a[0]:
            return vertical(a[1], b[1])
        return a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])

    minimum = float("inf")
    for i, j in boundary:
        a, b = sorted((nodes[i], nodes[j]), key=lambda p: p[0])
        left = bisect_left(ends, a[0])
        right = bisect_right(starts, b[0])
        for c, d in segments[left:right]:
            # Each difference is affine between segment endpoints, so its minimum is at an end.
            for x in (max(a[0], c[0]), min(b[0], d[0])):
                minimum = min(minimum, height(c, d, x, min) + offset - height(a, b, x, max))
    if not isfinite(minimum):
        raise ValueError("The panel must overlap the seal in X for vertical closing.")
    if minimum < -1e-7:
        raise ValueError("The panel starts below the seal exterior. Review its initial Y offset.")
    return max(0.0, minimum)


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
    else:
        raise ValueError("Unsupported material model.")
    return lines


def write_inp(project, mesh):
    nodes, ws, panel = mesh_parts(project, mesh)
    boundary = exterior(ws)
    clearance = vertical_gap(nodes, boundary, panel, project.motion.offset)
    seal_nodes = sorted({n for e in ws for n in e["nodes"]})
    panel_nodes = sorted({n for e in panel for n in e["nodes"]})
    selection = next((s for s in project.selections if s.id == project.mounting.selection), None)
    if not selection or not selection.entities:
        raise ValueError("Select a seal mounting boundary before generating the input.")
    fixed = set()
    seal_node_set = set(seal_nodes)
    for edge in selection.entities:
        edge_nodes = mesh["edge_nodes"].get(edge)
        if not edge_nodes or not set(edge_nodes) <= seal_node_set:
            raise ValueError("A mounting edge is missing from the seal mesh. Review the selection.")
        fixed.update(edge_nodes)

    lines = [
        "*Heading",
        "Abaqus QOL 2D plane stress / implicit dynamic closing",
        "** Units: N, mm, s, tonne. Panel RF2 is total reaction for the specified thickness.",
        f"** Initial vertical clearance on the assembled mesh: {scalar(clearance)} mm.",
        f"** Prescribed Y travel: {scalar(project.motion.travel)} mm; measured from initial placement.",
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


def output_cards(project):
    interval = scalar(min(0.02, project.motion.duration / 20))
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
    lines += [
        f"*Output, history, time interval={interval}",
        "*Node Output, nset=PANEL_RP",
        "U2, RF2",
    ]
    return lines
