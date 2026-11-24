"""Projected straight material partitions of one 2D seal face.

The operator draws arbitrary two-click strokes on the *face*, not on its border.
Each stroke's supporting line is intersected with the face's canonical analytic
boundary; every material interval the drawn segment actually touches is
selected and extended to its true boundary hits. The selected intervals become
candidate seams, which are welded into a planar arrangement with the existing
face boundary. Only the cells that lie in the original material become children.

The preview and the commit call the same :func:`arrange`, so the geometry the
operator reviews is the geometry that is saved. Analytic edges and source
provenance are preserved: seam fragments are lines, boundary splits keep their
line/arc/spline definitions, and preview triangles are never persisted.

The historical two-boundary-point request is still accepted through
:func:`plan` / :func:`apply` and the ``cut`` HTTP field. It is projected by the
same policy, so an endpoint need not sit on the border any more.
"""

from __future__ import annotations

import hashlib
import math

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

from .geometry import face_polygon, sample_edges
from .model import Edge, Face, Project, SplineData, Vertex
from .spline import curve as spline_curve

# Pointer/projection proximity tolerance in model millimetres. Kept for the
# historical boundary-snapping contract; the projected workflow does not need
# the operator to touch the border.
CUT_SNAP = 0.05
# Numerical weld of coincident intersection points, in mm.
WELD = 1e-6
# A drawn segment must overlap a material interval by at least this much to
# select it. A single touching point is not a cut.
TOUCH = 1e-6
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


def _hash(seed, face, strokes):
    payload = "|".join(
        [str(seed), face]
        + [
            "{:.9f},{:.9f},{:.9f},{:.9f}".format(*stroke[0], *stroke[1])
            for stroke in sorted(
                tuple(sorted((tuple(stroke[0]), tuple(stroke[1])))) for stroke in strokes
            )
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


def _signed_area(loop, samples):
    points = []
    for token in loop:
        curve_points = samples[token.lstrip("-")]
        points.extend((curve_points[::-1] if token.startswith("-") else curve_points)[:-1])
    area = 0.0
    for (x1, y1, *_), (x2, y2, *_) in zip(points, points[1:] + points[:1]):
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _orient(loop, samples, sign=1):
    area = _signed_area(loop, samples)
    if (area >= 0) == (sign >= 0):
        return list(loop)
    return [
        (token[1:] if token.startswith("-") else "-" + token) for token in reversed(loop)
    ]


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


def project_parts(project, vertices, edges):
    """A topology-only copy used to sample the split result before faces exist."""
    copy = project.model_copy(deep=True)
    copy.vertices = vertices
    copy.edges = edges
    return copy


# --------------------------------------------------------------------------- #
# Analytic line/curve intersections
# --------------------------------------------------------------------------- #


def _cross(ax, ay, bx, by):
    return ax * by - ay * bx


def _line_edge_hits(project, edge, origin, direction):
    """Infinite-line crossings with one canonical edge as ``[(t, xy)]``.

    ``direction`` is a unit vector. ``t`` is the edge parameter, not the line
    parameter; a spline crossing is refined to its own parameter domain so the
    sub-curve split stays on the same analytic curve.
    """
    vertices = {v.id: v.xyz for v in project.vertices}
    a = vertices[edge.start]
    b = vertices[edge.end]
    ox, oy = origin
    dx, dy = direction
    if edge.kind == "line":
        ex, ey = b[0] - a[0], b[1] - a[1]
        den = _cross(dx, dy, ex, ey)
        if abs(den) <= 1e-14:
            return []
        t = _cross(a[0] - ox, a[1] - oy, ex, ey) / den
        s = _cross(a[0] - ox, a[1] - oy, dx, dy) / den
        if s < -1e-9 or s > 1 + 1e-9:
            return []
        s = min(1.0, max(0.0, s))
        return [(s, (a[0] + ex * s, a[1] + ey * s))]
    if edge.kind == "arc":
        cx, cy = edge.center[0], edge.center[1]
        radius = math.dist((a[0], a[1]), (cx, cy))
        wx, wy = ox - cx, oy - cy
        half = wx * dx + wy * dy
        disc = half * half - (wx * wx + wy * wy - radius * radius)
        if disc < -1e-9 * max(1.0, radius * radius):
            return []
        root = math.sqrt(max(0.0, disc))
        hits = []
        for offset in (-root, root):
            t_line = -half + offset
            px, py = ox + dx * t_line, oy + dy * t_line
            start = math.atan2(a[1] - cy, a[0] - cx)
            angle = math.atan2(py - cy, px - cx)
            delta = (angle - start) % (2 * math.pi)
            t = delta / edge.sweep if edge.sweep > 0 else 0.0
            if -1e-9 <= t <= 1 + 1e-9:
                hits.append((min(1.0, max(0.0, t)), (px, py)))
        return hits
    bs = spline_curve(edge.spline)
    max_t = bs.max_t
    steps = 512
    values = []
    for index in range(steps + 1):
        u = max_t * index / steps
        px, py, *_ = bs.point(u)
        values.append((u, px, py, _cross(dx, dy, px - ox, py - oy)))
    hits = []
    for (u0, x0, y0, f0), (u1, x1, y1, f1) in zip(values, values[1:]):
        if f0 == 0.0 and u0 == 0.0:
            hits.append((0.0, (x0, y0)))
            continue
        if f0 == 0.0 or f1 == 0.0 or f0 * f1 > 0:
            continue
        lo, hi = u0, u1
        flo, fhi = f0, f1
        for _ in range(80):
            mid = (lo + hi) / 2
            mx, my, *_ = bs.point(mid)
            fm = _cross(dx, dy, mx - ox, my - oy)
            if flo * fm <= 0:
                hi, fhi = mid, fm
            else:
                lo, flo = mid, fm
        u = (lo + hi) / 2
        px, py, *_ = bs.point(u)
        hits.append((u / max_t, (px, py)))
    # A crossing exactly at the final endpoint is not reported twice.
    return hits


def _unit(a, b):
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    if not math.isfinite(length) or length <= 1e-9:
        raise PartitionError("degenerate_cut", "A guide needs two distinct points.")
    return ((b[0] - a[0]) / length, (b[1] - a[1]) / length), length


def _material_intervals(project, face, start, end, parent):
    """Material intervals on the supporting line touched by the drawn segment.

    Returns ``(origin, direction, intervals)`` where each interval is a dict
    with the two analytic boundary hits. The drawn segment only decides which
    intervals are selected; selected intervals are extended to the true
    material boundary.
    """
    direction, length = _unit(start, end)
    origin = (float(start[0]), float(start[1]))
    boundary = [token.lstrip("-") for loop in face.loops for token in loop]
    edges = {edge.id: edge for edge in project.edges}
    hits = []
    for edge_id in boundary:
        edge = edges[edge_id]
        for t, (px, py) in _line_edge_hits(project, edge, origin, direction):
            hits.append(
                {
                    "s": (px - origin[0]) * direction[0] + (py - origin[1]) * direction[1],
                    "t": t,
                    "edge": edge_id,
                    "point": (px, py),
                }
            )
    hits.sort(key=lambda hit: hit["s"])
    unique = []
    for hit in hits:
        if unique and abs(hit["s"] - unique[-1]["s"]) <= WELD:
            # A shared vertex or a tangency is one geometric crossing.
            continue
        unique.append(hit)
    touched = []
    for first, second in zip(unique, unique[1:]):
        if second["s"] - first["s"] <= TOUCH:
            continue
        mid = (
            origin[0] + direction[0] * (first["s"] + second["s"]) / 2,
            origin[1] + direction[1] * (first["s"] + second["s"]) / 2,
        )
        probe = Point(mid)
        if not parent.contains(probe) or parent.boundary.distance(probe) <= WELD:
            continue
        # The drawn segment must overlap this material interval by a positive
        # length. A stroke wholly inside the void, or beyond the wall, is a hit.
        lo, hi = sorted((0.0, length))
        overlap = min(hi, second["s"]) - max(lo, first["s"])
        if overlap <= TOUCH:
            continue
        touched.append(
            {
                "low": first,
                "high": second,
                "low_s": first["s"],
                "high_s": second["s"],
                "start": first["point"],
                "end": second["point"],
                "direction": direction,
                "origin": origin,
                "length": second["s"] - first["s"],
            }
        )
    return direction, length, touched


def _line_key(origin, direction):
    """Canonical line equation key so opposite/repeated strokes share a seam."""
    dx, dy = _canonical_direction(direction)
    normal = (-dy, dx)
    offset = normal[0] * origin[0] + normal[1] * origin[1]
    # Quantize only for grouping; the authoritative coordinates stay exact.
    return (round(normal[0], 9), round(normal[1], 9), round(offset, 7))


def _canonical_direction(direction):
    dx, dy = float(direction[0]), float(direction[1])
    if dx < -1e-12 or (abs(dx) <= 1e-12 and dy < 0):
        return (-dx, -dy)
    return (dx, dy)


def _merge_seams(selected):
    """Union collinear overlapping/adjacent intervals into seam segments."""
    groups = {}
    for interval in selected:
        key = _line_key(interval["origin"], interval["direction"])
        groups.setdefault(key, []).append(interval)
    seams = []
    for key in sorted(groups, key=lambda item: (item[0], item[1], item[2])):
        intervals = groups[key]
        direction = _canonical_direction(intervals[0]["direction"])
        origin = intervals[0]["origin"]
        # Re-express every interval on one common origin and canonical
        # direction; each stroke carries its own origin otherwise.
        prepared = []
        for interval in intervals:
            start = interval["start"]
            end = interval["end"]
            sa = (start[0] - origin[0]) * direction[0] + (start[1] - origin[1]) * direction[1]
            sb = (end[0] - origin[0]) * direction[0] + (end[1] - origin[1]) * direction[1]
            if sa <= sb:
                low_hit, high_hit = interval["low"], interval["high"]
            else:
                low_hit, high_hit = interval["high"], interval["low"]
            prepared.append((min(sa, sb), max(sa, sb), low_hit, high_hit, interval))
        prepared.sort(key=lambda item: (item[0], item[1]))
        current = None
        for low, high, low_hit, high_hit, interval in prepared:
            if current is None:
                current = {
                    "low": low,
                    "high": high,
                    "low_hit": low_hit,
                    "high_hit": high_hit,
                    "origin": origin,
                    "direction": direction,
                    "key": key,
                    "guides": [interval.get("guide", 0)],
                }
                continue
            if low <= current["high"] + WELD:
                if high > current["high"]:
                    current["high"] = high
                    current["high_hit"] = high_hit
                current["guides"].append(interval.get("guide", 0))
                continue
            seams.append(current)
            current = {
                "low": low,
                "high": high,
                "low_hit": low_hit,
                "high_hit": high_hit,
                "origin": origin,
                "direction": direction,
                "key": key,
                "guides": [interval.get("guide", 0)],
            }
        if current is not None:
            seams.append(current)
    for seam in seams:
        seam["start"] = seam["low_hit"]["point"]
        seam["end"] = seam["high_hit"]["point"]
        seam["length"] = seam["high"] - seam["low"]
    seams.sort(key=lambda item: (item["start"][0], item["start"][1], item["end"][0], item["end"][1]))
    return seams


def _segment_intersection(a, b, c, d):
    """Proper or endpoint intersection of two finite segments, or ``None``."""
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    den = _cross(rx, ry, sx, sy)
    if abs(den) <= 1e-14:
        return None
    qx, qy = c[0] - a[0], c[1] - a[1]
    t = _cross(qx, qy, sx, sy) / den
    u = _cross(qx, qy, rx, ry) / den
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return (a[0] + rx * t, a[1] + ry * t)
    return None


def _split_seams(seams):
    """Split seams at interior crossings so the arrangement is properly noded."""
    points = [[seam["start"], seam["end"]] for seam in seams]
    for i in range(len(seams)):
        for j in range(i + 1, len(seams)):
            hit = _segment_intersection(seams[i]["start"], seams[i]["end"], seams[j]["start"], seams[j]["end"])
            if hit is None:
                continue
            for index in (i, j):
                a, b = points[index]
                if math.dist(hit, a) > WELD and math.dist(hit, b) > WELD:
                    points[index].append(hit)
    split = []
    for seam, nodes in zip(seams, points):
        a = seam["start"]
        b = seam["end"]
        ordered = sorted(nodes, key=lambda p: math.dist(a, p))
        ordered = [p for p in ordered if math.dist(a, p) <= seam["length"] + WELD]
        pieces = []
        for first, second in zip(ordered, ordered[1:]):
            if math.dist(first, second) <= WELD:
                continue
            pieces.append((first, second))
        split.append({**seam, "pieces": pieces})
    return split


def _dedupe_strokes(strokes):
    seen = set()
    unique = []
    for start, end in strokes:
        key = tuple(sorted((tuple(round(v, 9) for v in start), tuple(round(v, 9) for v in end))))
        if key in seen:
            continue
        seen.add(key)
        unique.append((start, end, key))
    return unique


def arrange(project, face_id, strokes, *, seed):
    """Plan a projected multi-stroke partition.

    Returns the candidate project (``project`` key) plus the public plan. The
    status is ``valid`` when the arrangement has at least two material
    children; ``one_region`` keeps the draft; ``no_hit``/``mixed`` identify
    strokes that do not contribute; ``redundant`` detects an already-applied
    internal seam.
    """
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
    normalised = []
    for stroke in strokes or []:
        if len(stroke) != 2 or len(stroke[0]) != 2 or len(stroke[1]) != 2:
            raise PartitionError("bad_request", "A guide needs two XY positions.")
        normalised.append(
            ((float(stroke[0][0]), float(stroke[0][1])), (float(stroke[1][0]), float(stroke[1][1])))
        )
    if not normalised:
        raise PartitionError("bad_request", "Draw at least one straight guide.")
    unique = _dedupe_strokes(normalised)

    samples0 = sample_edges(project)
    parent = face_polygon(face, samples0)
    selected = []
    guide_reports = []
    for index, (start, end, _key) in enumerate(unique):
        direction, length, intervals = _material_intervals(project, face, start, end, parent)
        if not intervals:
            guide_reports.append(
                {
                    "index": index,
                    "status": "no_hit",
                    "start": list(start),
                    "end": list(end),
                    "intervals": [],
                    "length_mm": 0.0,
                }
            )
            continue
        for interval in intervals:
            interval["guide"] = index
        selected.extend(intervals)
        guide_reports.append(
            {
                "index": index,
                "status": "selected",
                "start": list(start),
                "end": list(end),
                "intervals": [
                    [list(interval["start"]), list(interval["end"])] for interval in intervals
                ],
                "length_mm": round(sum(interval["length"] for interval in intervals), 9),
            }
        )
    hit_guides = [report for report in guide_reports if report["status"] == "selected"]
    if not selected:
        raise PartitionError(
            "cut_no_hit",
            "The guide does not cross the target material. Draw across a wall of the selected face.",
        )
    if len(hit_guides) != len(guide_reports):
        return _plan_payload(
            face,
            parent,
            guide_reports,
            status="mixed",
            unused=[report["index"] for report in guide_reports if report["status"] == "no_hit"],
        )

    seams = _split_seams(_merge_seams(selected))
    if not seams:
        raise PartitionError("cut_no_hit", "The guide does not divide the target material.")

    # Deterministic identifier for every derived CAD entity.
    identifier = _hash(seed, face.id, [item[:2] for item in unique])
    existing = (
        [v.id for v in project.vertices]
        + [e.id for e in project.edges]
        + [f.id for f in project.faces]
    )
    ids = _Ids(identifier, existing)
    vertices = {v.id: (v.xyz[0], v.xyz[1]) for v in project.vertices}
    new_vertices = list(project.vertices)
    by_point = {}

    def vertex_at(point):
        key = (round(point[0], 6), round(point[1], 6))
        if key in by_point:
            return by_point[key]
        for vertex in new_vertices:
            if math.hypot(vertex.xyz[0] - point[0], vertex.xyz[1] - point[1]) <= WELD:
                by_point[key] = vertex.id
                return vertex.id
        value = ids.next("v")
        new_vertices.append(Vertex(id=value, xyz=(point[0], point[1], 0.0)))
        by_point[key] = value
        return value

    # Boundary split points: every seam endpoint lies on a canonical edge and
    # carries its own edge parameter from the analytic intersection.
    boundary_cuts = {}
    seam_pieces = []
    for seam in seams:
        low_hit = seam["low_hit"]
        high_hit = seam["high_hit"]
        seam_pieces.append(
            {
                "start": low_hit["point"],
                "end": high_hit["point"],
                "low_hit": low_hit,
                "high_hit": high_hit,
                "pieces": seam["pieces"],
            }
        )
        for hit in (low_hit, high_hit):
            boundary_cuts.setdefault(hit["edge"], []).append(hit)
    # Junction points are shared by crossing seams.
    for seam in seam_pieces:
        for a, b in seam["pieces"]:
            for point in (a, b):
                vertex_at(point)

    edge_map = {edge.id: edge for edge in project.edges}
    pieces = {}
    new_edges = []
    for edge in project.edges:
        hits = boundary_cuts.get(edge.id)
        if not hits:
            new_edges.append(edge)
            continue
        ordered = sorted(hits, key=lambda hit: hit["t"])
        cuts = []
        for hit in ordered:
            if hit["t"] <= 1e-9 or hit["t"] >= 1 - 1e-9:
                continue
            cuts.append((hit["t"], vertex_at(hit["point"])))
        deduped = []
        for t, vertex in cuts:
            if deduped and abs(t - deduped[-1][0]) <= WELD:
                continue
            deduped.append((t, vertex))
        piece_ids = []
        previous_vertex, previous_t = edge.start, 0.0
        for t, vertex in deduped:
            piece = _sub_edge(project, edge, previous_t, t, previous_vertex, vertex, ids)
            new_edges.append(piece)
            piece_ids.append(piece.id)
            previous_vertex, previous_t = vertex, t
        piece = _sub_edge(project, edge, previous_t, 1.0, previous_vertex, edge.end, ids)
        new_edges.append(piece)
        piece_ids.append(piece.id)
        pieces[edge.id] = piece_ids

    seam_edges = []
    for seam in seam_pieces:
        for a, b in seam["pieces"]:
            va = vertex_at(a)
            vb = vertex_at(b)
            if va == vb:
                continue
            edge = Edge(
                id=ids.next("e"),
                name=f"{face.name} partition",
                component=face.component,
                start=va,
                end=vb,
                kind="line",
            )
            new_edges.append(edge)
            seam_edges.append(edge.id)

    # Rewrite every face loop so bonded interfaces stay conforming even when a
    # cut ends on a boundary shared with a neighbouring region.
    edge_map = {edge.id: edge for edge in new_edges}
    rewritten = {}
    for item in project.faces:
        loops = [
            [token for original in loop for token in _expand_token(original, pieces)]
            for loop in item.loops
        ]
        rewritten[item.id] = loops

    topology = project_parts(project, new_vertices, new_edges)
    samples = sample_edges(topology)
    # The rewritten boundary is re-tessellated from the split analytic edges, so
    # compare the cells with that discretisation rather than the parent's
    # different chord phase. The analytic geometry is unchanged.
    try:
        parent_exact = face_polygon(
            Face(
                id=face.id,
                name=face.name,
                component=face.component,
                material=face.material,
                loops=rewritten[face.id],
            ),
            samples,
        )
    except ValueError as exc:
        raise PartitionError("invalid_result", str(exc)) from exc

    # Planar arrangement: the noded linework's bounded material cells are the
    # authoritative child count and area. polygonize is the decision oracle.
    lines = []
    for loop in rewritten[face.id]:
        points = []
        for token in loop:
            curve_points = samples[token.lstrip("-")]
            points.extend(curve_points if not token.startswith("-") else curve_points[::-1])
        if len(points) > 1:
            lines.append(LineString([(p[0], p[1]) for p in points]))
    for edge_id in seam_edges:
        lines.append(LineString([(p[0], p[1]) for p in samples[edge_id]]))
    merged = unary_union(lines)
    all_cells = list(polygonize(merged))
    material_cells = [
        polygon
        for polygon in all_cells
        if parent.buffer(WELD).contains(polygon.representative_point())
    ]
    if any(
        polygon.area < max(MIN_AREA, MIN_AREA_FRACTION * parent.area)
        for polygon in material_cells
    ):
        raise PartitionError(
            "sliver_cut", "The cut leaves a sliver region; move it away from an edge."
        )
    cells = [polygon for polygon in material_cells if polygon.area >= MIN_AREA]
    cells.sort(
        key=lambda polygon: (
            round(polygon.representative_point().x, 6),
            round(polygon.representative_point().y, 6),
        )
    )
    if not cells:
        raise PartitionError("invalid_result", "The guide does not divide the region.")
    if len(cells) == 1:
        return _plan_payload(
            face,
            parent,
            guide_reports,
            status="one_region",
            cells=cells,
            seams=seam_edges,
            split_edges=sorted(pieces),
        )
    total = sum(polygon.area for polygon in cells)
    if abs(total - parent_exact.area) > max(1e-6, 1e-6 * parent_exact.area):
        raise PartitionError("area_mismatch", "The partition does not preserve the region area.")
    for index, first in enumerate(cells):
        for second in cells[index + 1 :]:
            if first.intersection(second).area > max(1e-9, 1e-6 * parent.area):
                raise PartitionError("overlapping_children", "Two child regions overlap.")
    if not all(polygon.is_valid for polygon in cells):
        raise PartitionError("invalid_result", "The partition produces an invalid region contour.")

    # Map each ring back to analytic edge tokens. The ring is sampled linework,
    # so consecutive coordinate pairs name exactly one sub-edge occurrence.
    pair_edges = {}
    for edge_id, points in samples.items():
        for first, second in zip(points, points[1:]):
            a = (round(first[0], 9), round(first[1], 9))
            b = (round(second[0], 9), round(second[1], 9))
            if a == b:
                continue
            pair_edges.setdefault((a, b), (edge_id, 1))
            pair_edges.setdefault((b, a), (edge_id, -1))

    def tokens_for_ring(coords):
        keys = [(round(p[0], 9), round(p[1], 9)) for p in coords]
        if len(keys) > 1 and keys[0] == keys[-1]:
            keys = keys[:-1]
        tokens = []
        for first, second in zip(keys, keys[1:] + keys[:1]):
            found = pair_edges.get((first, second))
            if found is None:
                raise PartitionError(
                    "invalid_result",
                    "A child boundary could not be mapped back to its analytic edge.",
                )
            edge_id, direction = found
            tokens.append(edge_id if direction > 0 else "-" + edge_id)
        merged_tokens = []
        for token in tokens:
            if merged_tokens and merged_tokens[-1] == token:
                continue
            merged_tokens.append(token)
        return merged_tokens

    child_ids = [ids.next("f") for _ in cells]
    children = []
    for index, (cell, child_id) in enumerate(zip(cells, child_ids)):
        exterior = tokens_for_ring(list(cell.exterior.coords))
        exterior = _orient(exterior, samples, sign=1)
        loops = [exterior]
        for ring in cell.interiors:
            hole = tokens_for_ring(list(ring.coords))
            hole = _orient(hole, samples, sign=-1)
            loops.append(hole)
        suffix = chr(ord("A") + index) if index < 26 else f"Part {index + 1}"
        children.append(
            Face(
                id=child_id,
                name=f"{face.name} {suffix}",
                component=face.component,
                material=face.material,
                loops=loops,
            )
        )

    new_faces = []
    for item in project.faces:
        if item.id == face.id:
            new_faces.extend(children)
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
        selection.entities = _remap(selection.entities, pieces, face.id, child_ids)
    if candidate.mesh.local:
        remapped = {}
        for edge_id, value in candidate.mesh.local.items():
            for replacement in pieces.get(edge_id, [edge_id]):
                remapped[replacement] = value
        candidate.mesh.local = remapped
    try:
        candidate = Project.model_validate(candidate.model_dump(mode="json"))
    except ValueError as exc:
        raise PartitionError("invalid_result", str(exc)) from exc

    plan = _plan_payload(
        face,
        parent,
        guide_reports,
        status="valid",
        cells=cells,
        seams=seam_edges,
        split_edges=sorted(pieces),
        children=children,
    )
    plan["project"] = candidate
    plan["created_vertices"] = [v.id for v in new_vertices if v.id.startswith(f"p{identifier}")]
    plan["created_edges"] = [e.id for e in new_edges if e.id.startswith(f"p{identifier}")]
    return plan


def _plan_payload(
    face,
    parent,
    guides,
    *,
    status,
    cells=None,
    seams=None,
    split_edges=None,
    children=None,
    unused=None,
):
    cells = cells or []
    children = children or []
    seams = seams or []
    payload = {
        "face": face.id,
        "status": status,
        "guides": guides,
        "unused_guides": unused or [],
        "seams": seams,
        "split_edges": split_edges or [],
        "children": [
            {
                "id": child.id,
                "name": child.name,
                "area": area,
                "material": child.material,
            }
            for child, area in zip(children, [cell.area for cell in cells])
        ]
        if children
        else [
            {"id": None, "name": None, "area": polygon.area, "material": face.material}
            for polygon in cells
        ],
        "areas": [polygon.area for polygon in cells],
        "area_parent": parent.area,
        "area_children": sum(polygon.area for polygon in cells),
        "child_count": len(cells),
    }
    # The historical single-cut response fields remain for older readers.
    first = guides[0] if guides else None
    if first and first.get("intervals"):
        start, end = first["intervals"][0]
        payload["line"] = [start, end]
        payload["start"] = start
        payload["end"] = end
    if len(cells) == 2:
        payload["area_a"] = cells[0].area
        payload["area_b"] = cells[1].area
        payload["child_a"] = children[0].id if children else None
        payload["child_b"] = children[1].id if children else None
        payload["cut_edge"] = seams[0] if seams else None
    return payload


def preview(project: Project, face_id, strokes, *, seed="preview"):
    """Public plan without the candidate CAD project (JSON-safe)."""
    result = arrange(project, face_id, strokes, seed=seed)
    result.pop("project", None)
    return result


def commit(project: Project, face_id, strokes, *, seed):
    """Return ``(candidate_project, plan)``; never saves or mutates the input."""
    result = arrange(project, face_id, strokes, seed=seed)
    if result["status"] != "valid":
        raise PartitionError(result["status"], _status_message(result))
    candidate = result.pop("project")
    return candidate, result


def _status_message(result):
    status = result["status"]
    if status == "one_region":
        return "This guide opens the region but leaves one connected material region. Add another cut."
    if status == "mixed":
        return "Some guides miss the target material. Remove or reposition them before applying."
    if status == "redundant":
        return "This seam is already an internal boundary between two regions."
    return "The guide does not produce two or more material regions."


def plan(project: Project, face_id, start, end, *, seed):
    """Historical two-point entry point, projected by the same policy."""
    candidate, info = commit(project, face_id, [(start, end)], seed=seed)
    return {**info, "project": candidate}


def apply(project: Project, face_id, start, end, *, seed):
    """Historical ``(candidate, plan)`` wrapper; no directory mutation."""
    candidate, info = commit(project, face_id, [(start, end)], seed=seed)
    return candidate, info
