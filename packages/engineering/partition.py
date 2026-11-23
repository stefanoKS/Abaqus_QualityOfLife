"""Straight two-point material partition of one 2D seal face.

A cut is a display-independent CAD operation: it splits canonical vertices,
edges and face loops, never renderer triangles or FE labels. Both preview and
commit call the same :func:`plan` and :func:`apply`, and every rejection leaves
the input project untouched.

The resulting topology is the existing bonded-interface pattern: two faces
share one new edge with opposite loop signs, so the mesher sees two regions and
one conforming interface. All new IDs derive from the base revision and the cut
so a retried request is byte-identical.
"""

from __future__ import annotations

import hashlib
import math

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import split

from .geometry import face_polygon, sample_edges
from .model import Edge, Face, Project, SplineData, Vertex
from .spline import curve as spline_curve

# Documented snap tolerance in project length units (mm). An endpoint farther
# than this from the target face's exterior boundary is rejected.
CUT_SNAP = 0.05
# A cut that meets the boundary more shallowly than this is treated as tangent.
MIN_ANGLE = math.radians(5.0)
# Reject slivers smaller than this fraction of the parent area.
MIN_AREA_FRACTION = 1e-4
MIN_AREA = 1e-6


class PartitionError(ValueError):
    """A validated, non-destructive partition rejection.

    ``code`` is stable and localized by the browser; the message is diagnostic.
    """

    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _hash(seed, face, start, end):
    payload = "|".join(
        [
            str(seed),
            face,
            f"{start[0]:.9f}",
            f"{start[1]:.9f}",
            f"{end[0]:.9f}",
            f"{end[1]:.9f}",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]


class _Ids:
    def __init__(self, prefix, existing):
        self.prefix = prefix
        self.existing = set(existing)
        self.counters = {"v": 0, "e": 0, "f": 0}

    def next(self, kind):
        while True:
            self.counters[kind] += 1
            value = f"p{self.prefix}{kind}{self.counters[kind]}"
            if value not in self.existing:
                self.existing.add(value)
                return value


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, 0.0)


def _arc_point(edge, a, t):
    center = edge.center
    radius = math.dist(a, center)
    angle = math.atan2(a[1] - center[1], a[0] - center[0]) + edge.sweep * t
    return (center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle), 0.0)


def _curve_point(project, edge, t):
    if edge.kind == "line":
        a = next(v.xyz for v in project.vertices if v.id == edge.start)
        b = next(v.xyz for v in project.vertices if v.id == edge.end)
        return _lerp(a, b, t)
    if edge.kind == "arc":
        a = next(v.xyz for v in project.vertices if v.id == edge.start)
        return _arc_point(edge, a, t)
    return tuple(spline_curve(edge.spline).point(t * spline_curve(edge.spline).max_t))


def _nearest_on_edge(project, edge, point):
    """Return ``(t, xyz, distance)`` on the canonical curve."""
    if edge.kind == "line":
        a = next(v.xyz for v in project.vertices if v.id == edge.start)
        b = next(v.xyz for v in project.vertices if v.id == edge.end)
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = dx * dx + dy * dy
        t = 0.0 if length <= 1e-18 else ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length
        t = min(1.0, max(0.0, t))
        xyz = _lerp(a, b, t)
        return t, xyz, math.dist(point[:2], xyz[:2])
    if edge.kind == "arc":
        a = next(v.xyz for v in project.vertices if v.id == edge.start)
        center = edge.center
        start = math.atan2(a[1] - center[1], a[0] - center[0])
        angle = math.atan2(point[1] - center[1], point[0] - center[0])
        delta = (angle - start) % (2 * math.pi)
        t = delta / edge.sweep if edge.sweep > 0 else 0.0
        t = min(1.0, max(0.0, t))
        xyz = _arc_point(edge, a, t)
        return t, xyz, math.dist(point[:2], xyz[:2])
    bs = spline_curve(edge.spline)
    t = float(bs.point_inversion((point[0], point[1], 0.0))) / bs.max_t
    t = min(1.0, max(0.0, t))
    xyz = tuple(bs.point(t * bs.max_t))
    return t, xyz, math.dist(point[:2], tuple(xyz)[:2])


def _tangent(project, edge, t):
    eps = 1e-6
    a = _curve_point(project, edge, max(0.0, t - eps))
    b = _curve_point(project, edge, min(1.0, t + eps))
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length > 0 else (1.0, 0.0)


def _sub_spline(data, f0, f1):
    if data.fit_points or data.closed or data.periodic:
        raise PartitionError(
            "unsupported_curve",
            "Only a clamped control-point spline can be split exactly; use a line or arc cut.",
        )
    bs = spline_curve(data)
    max_t = bs.max_t
    t0, t1 = max_t * f0, max_t * f1
    if f0 <= 1e-12:
        part = bs.split(t1)[0]
    elif f1 >= 1.0 - 1e-12:
        part = bs.split(t0)[1]
    else:
        right = bs.split(t0)[1]
        local = (t1 - t0) / (max_t - t0)
        part = right.split(right.max_t * local)[0]
    poles = [tuple(p) for p in part.control_points]
    knots = list(part.knots())
    weights = [float(w) for w in part.weights()]
    if len(weights) != len(poles) or all(abs(w - 1.0) <= 1e-12 for w in weights):
        weights = []
    return SplineData(
        degree=part.degree,
        control_points=poles,
        knots=knots,
        weights=weights,
        tolerance=data.tolerance,
    )


def _sub_edge(project, edge, t0, t1, start_vertex, end_vertex, ids):
    if t1 - t0 <= 1e-9:
        raise PartitionError("degenerate_cut", "The cut creates a zero-length edge.")
    if edge.kind == "line":
        return Edge(
            id=ids.next("e"),
            name=f"{edge.name} (partition)",
            component=edge.component,
            start=start_vertex,
            end=end_vertex,
            kind="line",
            source_handle=edge.source_handle,
            layer=edge.layer,
        )
    if edge.kind == "arc":
        sweep = edge.sweep * (t1 - t0)
        if sweep <= 1e-9:
            raise PartitionError("degenerate_cut", "The cut leaves a zero-sweep arc.")
        return Edge(
            id=ids.next("e"),
            name=f"{edge.name} (partition)",
            component=edge.component,
            start=start_vertex,
            end=end_vertex,
            kind="arc",
            center=edge.center,
            sweep=sweep,
            source_handle=edge.source_handle,
            layer=edge.layer,
        )
    return Edge(
        id=ids.next("e"),
        name=f"{edge.name} (partition)",
        component=edge.component,
        start=start_vertex,
        end=end_vertex,
        kind="spline",
        spline=_sub_spline(edge.spline, t0, t1),
        source_handle=edge.source_handle,
        layer=edge.layer,
    )


def _expand_token(token, pieces):
    edge_id = token[1:] if token.startswith("-") else token
    if edge_id not in pieces:
        return [token]
    ordered = pieces[edge_id]
    if token.startswith("-"):
        return ["-" + piece for piece in reversed(ordered)]
    return list(ordered)


def _loop_items(loop, edges):
    items = []
    for token in loop:
        edge = edges[token.lstrip("-")]
        if token.startswith("-"):
            items.append((edge.end, edge.start, token))
        else:
            items.append((edge.start, edge.end, token))
    return items


def _signed_area(loop, edges, samples):
    points = []
    for token in loop:
        curve_points = samples[token.lstrip("-")]
        points.extend((curve_points[::-1] if token.startswith("-") else curve_points)[:-1])
    area = 0.0
    for (x1, y1, *_), (x2, y2, *_) in zip(points, points[1:] + points[:1]):
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _orient(loop, edges, samples):
    if _signed_area(loop, edges, samples) >= 0:
        return list(loop)
    return [
        (token[1:] if token.startswith("-") else "-" + token) for token in reversed(loop)
    ]


def _split_loop_at(loop, edge_map, vertex_a, vertex_b, cut_edge):
    """Return two closed child loops sharing ``cut_edge`` (A: a→b, B: b→a)."""
    items = _loop_items(loop, edge_map)
    starts_a = [i for i, item in enumerate(items) if item[0] == vertex_a]
    starts_b = [i for i, item in enumerate(items) if item[0] == vertex_b]
    if len(starts_a) != 1 or len(starts_b) != 1:
        raise PartitionError(
            "ambiguous_loop",
            "The cut boundary point is visited more than once; use a simpler cut.",
        )
    i1, i2 = starts_a[0], starts_b[0]
    if i1 == i2:
        raise PartitionError("degenerate_cut", "Both cut endpoints resolve to one boundary point.")
    if i1 < i2:
        arc_a = items[i1:i2]
        arc_b = items[i2:] + items[:i1]
    else:
        arc_a = items[i1:] + items[:i2]
        arc_b = items[i2:i1]
    if not arc_a or not arc_b:
        raise PartitionError("degenerate_cut", "The cut leaves an empty boundary run.")
    a_tokens = [item[2] for item in arc_a]
    b_tokens = [item[2] for item in arc_b]
    return a_tokens + ["-" + cut_edge], b_tokens + [cut_edge]


def _project_faces(project, faces):
    candidate = project.model_copy(deep=True)
    candidate.faces = faces
    return candidate


def _remap(values, pieces, face, children):
    result = []
    for value in values:
        if value in pieces:
            result.extend(pieces[value])
        elif value == face:
            result.extend(children)
        else:
            result.append(value)
    return result


def plan(project: Project, face_id, start, end, *, seed):
    """Validate a cut and describe its deterministic result without mutating."""
    face = next((item for item in project.faces if item.id == face_id), None)
    if face is None:
        raise PartitionError("face_missing", "The target face no longer exists.")
    if face.cavity:
        raise PartitionError("face_cavity", "A cavity is not a material region and cannot be cut.")
    role = next((c.role for c in project.components if c.id == face.component), None)
    if role != "seal":
        raise PartitionError(
            "face_not_seal",
            "Only a material-bearing seal face can be partitioned in this delivery.",
        )
    if len(start) != 2 or len(end) != 2:
        raise PartitionError("bad_request", "A cut needs two XY positions.")
    if math.dist(start, end) <= 1e-6:
        raise PartitionError("degenerate_cut", "The two cut points are the same position.")
    vertices = {v.id: v.xyz for v in project.vertices}
    edges = {e.id: e for e in project.edges}
    samples = sample_edges(project)
    parent = face_polygon(face, samples)

    # Locate both endpoints on the target face's exterior boundary. A point on
    # a cavity ring is rejected explicitly instead of being snapped outward.
    exterior_tokens = [token.lstrip("-") for token in face.loops[0]]
    hole_tokens = [token.lstrip("-") for loop in face.loops[1:] for token in loop]
    located = []
    for point in (start, end):
        best = None
        for edge_id in exterior_tokens:
            edge = edges[edge_id]
            t, xyz, distance = _nearest_on_edge(project, edge, (point[0], point[1], 0.0))
            if best is None or distance < best[3]:
                best = (edge_id, t, xyz, distance)
        for edge_id in hole_tokens:
            edge = edges[edge_id]
            _, _, distance = _nearest_on_edge(project, edge, (point[0], point[1], 0.0))
            if distance <= CUT_SNAP:
                raise PartitionError(
                    "endpoint_on_hole",
                    "An endpoint snapped to a cavity boundary. Cut the material region only.",
                )
        if best is None or best[3] > CUT_SNAP:
            raise PartitionError(
                "endpoint_off_boundary",
                f"An endpoint is {best[3] if best else float('inf'):.3f} mm from the face boundary "
                f"(limit {CUT_SNAP} mm).",
            )
        edge_id, t, xyz, _ = best
        edge = edges[edge_id]
        at_start = t <= 1e-9
        at_end = t >= 1.0 - 1e-9
        if at_start:
            located.append((edge_id, 0.0, edge.start, True))
        elif at_end:
            located.append((edge_id, 1.0, edge.end, True))
        else:
            located.append((edge_id, t, None, False))

    # A second endpoint that snaps to the very same boundary position is not a cut.
    p1 = vertices[located[0][2]] if located[0][2] else _curve_point(project, edges[located[0][0]], located[0][1])
    p2 = vertices[located[1][2]] if located[1][2] else _curve_point(project, edges[located[1][0]], located[1][1])
    if math.dist(p1[:2], p2[:2]) <= 1e-6:
        raise PartitionError("degenerate_cut", "The two cut points resolve to the same boundary point.")
    chord = LineString([p1[:2], p2[:2]])
    # A cavity is a void: crossing it is a different rejection from leaving the
    # exterior boundary, and the engineer needs the actionable message.
    for ring in parent.interiors:
        hole = Polygon(ring)
        # The tessellated cavity is inscribed inside the true void, so a small
        # buffer keeps a cut from grazing the real cavity wall.
        if chord.intersects(hole) or chord.distance(hole) <= CUT_SNAP:
            raise PartitionError(
                "cut_crosses_hole",
                "The cut crosses a cavity. Split the material into separate valid cuts instead.",
            )
    if not parent.buffer(CUT_SNAP).covers(chord):
        raise PartitionError("cut_outside_face", "The cut leaves the material region.")
    parts = [geometry for geometry in split(parent, chord).geoms]
    if len(parts) < 2:
        raise PartitionError("cut_outside_face", "The cut does not divide the region.")
    if len(parts) > 2:
        raise PartitionError(
            "cut_disjoint",
            "The cut crosses the region in more than one interval. Use separate valid cuts.",
        )
    if any(part.area < max(MIN_AREA, MIN_AREA_FRACTION * parent.area) for part in parts):
        raise PartitionError("sliver_cut", "The cut leaves a sliver region; move it away from an edge.")

    # Tangent/shallow cuts meet the boundary at a grazing angle.
    direction = (p2[0] - p1[0], p2[1] - p1[1])
    length = math.hypot(*direction)
    direction = (direction[0] / length, direction[1] / length)
    for (edge_id, t, _, _) in located:
        tangent = _tangent(project, edges[edge_id], t)
        cosine = abs(direction[0] * tangent[0] + direction[1] * tangent[1])
        angle = math.degrees(math.acos(min(1.0, max(-1.0, cosine))))
        if angle < math.degrees(MIN_ANGLE):
            raise PartitionError(
                "tangent_cut",
                "The cut meets the boundary almost tangentially; move an endpoint sideways.",
            )

    identifier = _hash(seed, face.id, p1[:2], p2[:2])
    ids = _Ids(identifier, [v.id for v in project.vertices] + list(edges) + [f.id for f in project.faces])
    new_vertices = list(project.vertices)
    new_edges = list(project.edges)

    def vertex_for(index):
        if located[index][2]:
            return located[index][2]
        value = ids.next("v")
        new_vertices.append(Vertex(id=value, xyz=(p1 if index == 0 else p2)))
        located[index] = (located[index][0], located[index][1], value, False)
        return value

    v1 = vertex_for(0)
    v2 = vertex_for(1)

    # Split every intersected edge once. Two hits on one edge are ordered along it.
    hits = {}
    for index, (edge_id, t, vertex_id, _) in enumerate(located):
        if located[index][2] and (t <= 1e-9 or t >= 1.0 - 1e-9):
            continue
        hits.setdefault(edge_id, []).append((t, vertex_id))
    pieces = {}
    for edge_id, entries in hits.items():
        edge = edges[edge_id]
        ordered = sorted(entries, key=lambda item: item[0])
        previous_vertex, previous_t = edge.start, 0.0
        piece_ids = []
        for t, vertex_id in ordered:
            piece = _sub_edge(project, edge, previous_t, t, previous_vertex, vertex_id, ids)
            new_edges.append(piece)
            piece_ids.append(piece.id)
            previous_vertex, previous_t = vertex_id, t
        piece = _sub_edge(project, edge, previous_t, 1.0, previous_vertex, edge.end, ids)
        new_edges.append(piece)
        piece_ids.append(piece.id)
        pieces[edge_id] = piece_ids
    new_edges = [edge for edge in new_edges if edge.id not in pieces]

    edge_map = {edge.id: edge for edge in new_edges}
    rewritten = {}
    for item in project.faces:
        loops = [[token for original in loop for token in _expand_token(original, pieces)] for loop in item.loops]
        rewritten[item.id] = loops

    cut_id = ids.next("e")
    cut_edge = Edge(
        id=cut_id,
        name=f"{face.name} partition",
        component=face.component,
        start=v1,
        end=v2,
        kind="line",
    )
    new_edges.append(cut_edge)
    edge_map = {edge.id: edge for edge in new_edges}
    samples2 = sample_edges(
        project_parts(project, new_vertices, new_edges)
    )

    child_a, child_b = _split_loop_at(rewritten[face.id][0], edge_map, v1, v2, cut_id)
    child_a = _orient(child_a, edge_map, samples2)
    child_b = _orient(child_b, edge_map, samples2)
    face_a = ids.next("f")
    face_b = ids.next("f")
    children = [face_a, face_b]
    a_face = Face(
        id=face_a,
        name=f"{face.name} A",
        component=face.component,
        material=face.material,
        loops=[child_a],
    )
    b_face = Face(
        id=face_b,
        name=f"{face.name} B",
        component=face.component,
        material=face.material,
        loops=[child_b],
    )

    # A hole belongs wholly to the side that contains its representative point.
    for hole in rewritten[face.id][1:]:
        ring = face_polygon(Face(id=face_a, name="hole probe", component=face.component, loops=[hole]), samples2)
        point = ring.representative_point()
        poly_a = face_polygon(a_face, samples2)
        poly_b = face_polygon(b_face, samples2)
        if poly_a.contains(point) and not poly_b.contains(point):
            a_face.loops.append(hole)
        elif poly_b.contains(point) and not poly_a.contains(point):
            b_face.loops.append(hole)
        else:
            raise PartitionError(
                "ambiguous_hole",
                "A cavity could not be assigned to exactly one side of the cut.",
            )

    poly_a = face_polygon(a_face, samples2)
    poly_b = face_polygon(b_face, samples2)
    if abs((poly_a.area + poly_b.area) - parent.area) > max(1e-6, 1e-6 * parent.area):
        raise PartitionError("area_mismatch", "The cut does not preserve the region area.")
    if poly_a.intersection(poly_b).area > max(1e-9, 1e-6 * parent.area):
        raise PartitionError("overlapping_children", "The two children overlap.")
    if not poly_a.is_valid or not poly_b.is_valid:
        raise PartitionError("invalid_result", "The cut produces an invalid region contour.")

    new_faces = []
    for item in project.faces:
        if item.id == face.id:
            new_faces.extend([a_face, b_face])
        elif item.id in rewritten:
            item = item.model_copy(deep=True)
            item.loops = rewritten[item.id]
            new_faces.append(item)
        else:
            new_faces.append(item)

    candidate = _project_faces(project, new_faces)
    candidate.vertices = new_vertices
    candidate.edges = new_edges
    for selection in candidate.selections:
        selection.entities = _remap(selection.entities, pieces, face.id, children)
    if candidate.mesh.local:
        remapped = {}
        for edge_id, value in candidate.mesh.local.items():
            for replacement in pieces.get(edge_id, [edge_id]):
                remapped[replacement] = value
        candidate.mesh.local = remapped
    # Re-validation is the contract gate; keep the error localized.
    try:
        candidate = Project.model_validate(candidate.model_dump(mode="json"))
    except ValueError as exc:
        raise PartitionError("invalid_result", str(exc)) from exc

    return {
        "face": face.id,
        "start": [round(p1[0], 9), round(p1[1], 9)],
        "end": [round(p2[0], 9), round(p2[1], 9)],
        "line": [p1[:2], p2[:2]],
        "hits": [
            {"edge": edge_id, "t": round(t, 9)} for edge_id, t, _, _ in located
        ],
        "child_a": face_a,
        "child_b": face_b,
        "cut_edge": cut_id,
        "created_vertices": [v.id for v in new_vertices if v.id.startswith(f"p{identifier}")],
        "created_edges": [e.id for e in new_edges if e.id.startswith(f"p{identifier}")],
        "split_edges": sorted(pieces),
        "area_a": poly_a.area,
        "area_b": poly_b.area,
        "project": candidate,
    }


def project_parts(project, vertices, edges):
    """A topology-only copy used to sample the split result before faces exist."""
    copy = project.model_copy(deep=True)
    copy.vertices = vertices
    copy.edges = edges
    return copy


def apply(project: Project, face_id, start, end, *, seed):
    """Return ``(candidate_project, plan)``; never saves or mutates the input."""
    result = plan(project, face_id, start, end, seed=seed)
    candidate = result.pop("project")
    return candidate, result
