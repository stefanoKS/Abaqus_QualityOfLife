"""Conforming first-order planar mesh using a shared OCC wire model."""

from collections import Counter, defaultdict
import math
from threading import Lock

import gmsh

from .geometry import face_polygon, sample_edges
from .spline import occ_descriptor

_GMSH = Lock()  # Gmsh holds a process-global kernel and options.


def generate_mesh(project):
    if project.dimension != "2D" or project.formulation != "plane_stress":
        raise ValueError(
            "3D extrusion supports inspection only. Return to the 2D section to mesh and solve."
        )
    roles = {c.id: c.role for c in project.components}
    if not project.material_regions or any(
        roles[f.component] != "seal" or not f.material for f in project.material_regions
    ):
        raise ValueError(
            "Assign the seal role and a material to every section region before meshing."
        )
    if any(c.role not in ("seal", "moving_panel", "vehicle_body") for c in project.components):
        raise ValueError(
            "The mesh supports a seal, one moving panel and an optional body profile. "
            "Assign a supported component role."
        )
    panels = [c for c in project.components if c.role == "moving_panel"]
    if len(panels) != 1:
        raise ValueError("Assign exactly one open rigid profile as the moving panel.")
    body = [c.id for c in project.components if c.role == "vehicle_body"]
    excluded = [
        {
            "component": c.id,
            "name": c.name,
            "reason": "rigid body profile reviewed but not analysed in this revision",
        }
        for c in project.components
        if c.role == "vehicle_body"
    ]
    faces_at_edge = defaultdict(list)
    for face in project.material_regions:
        for loop in face.loops:
            for token in loop:
                faces_at_edge[token.lstrip("-")].append(face.id)
    if body and any(e.component in body and e.id in faces_at_edge for e in project.edges):
        raise ValueError(
            "A body profile cannot be part of a material region. Assign it to a separate component."
        )
    if any(len(ids) > 2 for ids in faces_at_edge.values()):
        raise ValueError("Non-manifold interface. At most two regions may use a section edge.")
    if any(e.id not in faces_at_edge for e in project.edges if roles[e.component] == "seal"):
        raise ValueError("Every seal edge must belong to a material region.")
    # Require a single bonded network. Point contact does not bond regions together.
    adjacency = defaultdict(set)
    for uses in faces_at_edge.values():
        if len(uses) == 2:
            a, b = uses
            adjacency[a].add(b)
            adjacency[b].add(a)
    pending, visited = [project.material_regions[0].id], set()
    while pending:
        face_id = pending.pop()
        if face_id not in visited:
            visited.add(face_id)
            pending.extend(adjacency[face_id] - visited)
    if len(visited) != len(project.material_regions):
        raise ValueError(
            "Disconnected seal regions. Bonded material regions must share a complete CAD edge."
        )
    curves = sample_edges(project)
    polygons = [face_polygon(face, curves) for face in project.material_regions]
    smallest = min([project.mesh.size, *project.mesh.local.values()])
    perimeter = sum(sum(math.dist(a, b) for a, b in zip(pts, pts[1:])) for pts in curves.values())
    cost = sum(p.area for p in polygons) / smallest**2 + perimeter / smallest
    if cost > 80000:
        raise ValueError(
            "Requested mesh exceeds the pilot mesh budget. Increase the minimum element size."
        )
    with _GMSH:
        gmsh.initialize([], readConfigFiles=False, interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("General.NumThreads", 1)
            return _build(project, faces_at_edge, excluded)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Gmsh could not mesh this section: {exc}") from exc
        finally:
            gmsh.finalize()


def _build(p, faces_at_edge, excluded=()):
    gmsh.model.add("section")
    occ = gmsh.model.occ
    nodes = {v.id: occ.addPoint(*v.xyz, meshSize=p.mesh.size) for v in p.vertices}
    xyz = {v.id: v.xyz for v in p.vertices}
    samples = sample_edges(p)
    curves = {}  # edge id -> OCC curve tags in start -> end order
    lengths = {}  # edge id -> per-tag lengths
    for e in p.edges:
        a, b = xyz[e.start], xyz[e.end]
        if e.kind == "line":
            tags = [occ.addLine(nodes[e.start], nodes[e.end])]
            sizes = [math.dist(a, b)]
        elif e.kind == "arc":
            radius = math.dist(a, e.center)
            angle = math.atan2(a[1] - e.center[1], a[0] - e.center[0]) + e.sweep / 2
            mid = occ.addPoint(
                e.center[0] + radius * math.cos(angle), e.center[1] + radius * math.sin(angle), 0
            )
            tags = [occ.addCircleArc(nodes[e.start], mid, nodes[e.end], center=False)]
            sizes = [radius * e.sweep]
        elif occ_descriptor(e.spline):
            spec = occ_descriptor(e.spline)
            # The end control points must be the shared CAD vertices, otherwise
            # OCC silently stitches the wire with duplicate points and the
            # surface no longer shares nodes with the boundary curve.
            poles = [nodes[e.start]]
            poles.extend(occ.addPoint(*pt) for pt in spec["poles"][1:-1])
            poles.append(nodes[e.end])
            tags = [
                occ.addBSpline(
                    poles,
                    degree=spec["degree"],
                    weights=spec["weights"],
                    knots=spec["knots"],
                    multiplicities=spec["multiplicities"],
                )
            ]
            sizes = [sum(math.dist(u, v) for u, v in zip(samples[e.id], samples[e.id][1:]))]
        else:
            # Approximation keeps the analytic spline canonical and the chord
            # within its declared deviation; the tag chain is meshed as one edge.
            pts = [nodes[e.start]]
            for point in samples[e.id][1:-1]:
                pts.append(occ.addPoint(*point, meshSize=p.mesh.size))
            pts.append(nodes[e.end])
            tags = [occ.addLine(u, v) for u, v in zip(pts, pts[1:])]
            sizes = [math.dist(u, v) for u, v in zip(samples[e.id], samples[e.id][1:])]
        curves[e.id] = tags
        lengths[e.id] = sizes
    surfaces = {}
    for face in p.material_regions:
        loops = []
        for loop in face.loops:
            tags = []
            for token in loop:
                chain = curves[token.lstrip("-")]
                tags.extend([-tag for tag in reversed(chain)] if token.startswith("-") else chain)
            loops.append(occ.addCurveLoop(tags))
        surfaces[face.id] = occ.addPlaneSurface(loops)
    occ.synchronize()
    gmsh.option.setNumber("Mesh.MeshSizeMax", p.mesh.size)
    gmsh.option.setNumber("Mesh.MeshSizeMin", min([p.mesh.size, *p.mesh.local.values()]) / 4)
    for edge_id, size in p.mesh.local.items():
        for tag, length in zip(curves[edge_id], lengths[edge_id]):
            gmsh.model.mesh.setTransfiniteCurve(
                tag, max(2, 1 + math.ceil(length / min(size, p.mesh.size)))
            )
    for face in p.material_regions:
        surface = surfaces[face.id]
        if p.mesh.recombine:
            gmsh.model.mesh.setRecombine(2, surface)
        if gmsh.model.getNormal(surface, [0, 0])[2] < 0:
            gmsh.model.mesh.setReverse(2, surface)
    gmsh.model.mesh.generate(2)
    node_ids, coords, _ = gmsh.model.mesh.getNodes()
    coords = {int(n): [float(x) for x in pt] for n, pt in zip(node_ids, coords.reshape(-1, 3))}
    elements, face_elements, edge_nodes = [], {}, {}
    face_nodes = defaultdict(set)
    for face in p.material_regions:
        face_elements[face.id] = []
        types, groups, connectivities = gmsh.model.mesh.getElements(2, surfaces[face.id])
        for kind, ids, connectivity in zip(types, groups, connectivities):
            if kind not in (2, 3):
                raise ValueError(f"Unsupported Gmsh surface element type {kind}.")
            width, label = (3, "CPS3") if kind == 2 else (4, "CPS4R")
            for element_id, row in zip(ids, connectivity.reshape(-1, width)):
                conn = [int(n) for n in row]
                _check_element(int(element_id), conn, coords)
                elements.append(
                    dict(
                        id=int(element_id),
                        type=label,
                        nodes=conn,
                        entity=face.id,
                        component=face.component,
                    )
                )
                face_nodes[face.id].update(conn)
                face_elements[face.id].append(int(element_id))
        if not face_elements[face.id]:
            raise ValueError(f"No mesh generated for {face.name}.")
    roles = {c.id: c.role for c in p.components}
    for edge in p.edges:
        if roles[edge.component] == "vehicle_body":
            continue  # reviewed but not part of the analysed model
        tags = curves[edge.id]
        collected = set()
        for tag in tags:
            node_ids, _, _ = gmsh.model.mesh.getNodes(1, tag, includeBoundary=True)
            collected.update(int(n) for n in node_ids)
        # Order against the stored analytic definition, independent of OCC wire orientation.
        ordered = _along(sorted(collected), coords, samples[edge.id])
        if len(ordered) < 2:
            raise ValueError(f"No boundary discretization for {edge.name}.")
        edge_nodes[edge.id] = ordered
        for face_id in faces_at_edge[edge.id]:
            missing = set(ordered) - face_nodes[face_id]
            if missing:
                raise ValueError(
                    f"Disconnected mesh interface at {edge.name}: {len(missing)} of "
                    f"{len(ordered)} boundary nodes are absent from {face_id}."
                )
        if roles[edge.component] == "moving_panel":
            line_ids, conns = [], []
            for tag in tags:
                types, groups, connectivity = gmsh.model.mesh.getElements(1, tag)
                if list(types) != [1]:
                    raise ValueError(f"Expected linear panel segments on {edge.name}.")
                line_ids.extend(int(eid) for eid in groups[0])
                conns.extend(connectivity[0].reshape(-1, 2))
            for eid, row in zip(line_ids, conns):
                pair = _along(sorted(map(int, row)), coords, samples[edge.id])
                elements.append(
                    dict(
                        id=eid,
                        type="R2D2",
                        nodes=pair,
                        entity=edge.id,
                        component=edge.component,
                    )
                )
    used = {n for elem in elements for n in elem["nodes"]}
    return dict(
        nodes=[dict(id=n, xyz=coords[n]) for n in sorted(used)],
        elements=elements,
        edge_nodes=edge_nodes,
        face_elements=face_elements,
        excluded=excluded,
        counts=dict(Counter(e["type"] for e in elements)),
    )


def _along(node_ids, coords, polyline):
    """Sort nodes by their arc-length position along the analytic curve.

    Distance from the start point is only monotonic for lines and arcs up to pi,
    so splines and re-entrant curves are ordered by projection on the samples.
    """
    steps = [0.0]
    for a, b in zip(polyline, polyline[1:]):
        steps.append(steps[-1] + math.dist(a, b))

    def position(node):
        px, py = coords[node][0], coords[node][1]
        best_distance, best_length = math.inf, 0.0
        for index, (a, b) in enumerate(zip(polyline, polyline[1:])):
            dx, dy = b[0] - a[0], b[1] - a[1]
            squared = dx * dx + dy * dy
            t = 0.0
            if squared > 1e-18:
                t = max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / squared))
            distance = math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy))
            if distance < best_distance:
                best_distance = distance
                best_length = steps[index] + t * math.sqrt(squared)
        return best_length

    return sorted(node_ids, key=position)


def _check_element(eid, conn, coords):
    if len(set(conn)) != len(conn) or any(n not in coords for n in conn):
        raise ValueError(f"Invalid connectivity in element {eid}.")
    pts = [coords[n] for n in conn]
    for i, p in enumerate(pts):
        a, b = pts[(i + 1) % len(pts)], pts[i - 1]
        jac = (a[0] - p[0]) * (b[1] - p[1]) - (a[1] - p[1]) * (b[0] - p[0])
        if jac <= 1e-12:
            raise ValueError(
                f"Degenerate or inverted element {eid}. Adjust element size or repair the boundary."
            )
