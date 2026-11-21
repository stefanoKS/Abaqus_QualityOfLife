"""Reject crossings and tangencies away from common CAD vertices.

Use analytic lines and circles so a chord between display samples cannot hide
a sliver intersection. An STRtree limits the candidate pairs.
"""

import math

from shapely import STRtree
from shapely.geometry import LineString, box

TOL = 1e-7


def invalid_pair(a, b, coordinates, samples=None):
    if samples is not None and (a.kind == "spline" or b.kind == "spline"):
        return _sampled_invalid(a, b, coordinates, samples)
    a0, a1 = coordinates[a.start][:2], coordinates[a.end][:2]
    b0, b1 = coordinates[b.start][:2], coordinates[b.end][:2]
    common = [coordinates[v][:2] for v in {a.start, a.end} & {b.start, b.end}]

    def allowed(p):
        return any(math.dist(p, q) <= TOL for q in common)

    if a.kind == b.kind == "line":
        inter = LineString([a0, a1]).intersection(LineString([b0, b1]))
        return not inter.is_empty and (inter.geom_type != "Point" or not allowed(inter.coords[0]))
    if a.kind == "line":
        return invalid_pair(b, a, coordinates)

    center, radius = a.center[:2], math.dist(a0, a.center[:2])

    def on_arc(p, arc, start):
        if math.dist(p, start) <= TOL or math.dist(p, coordinates[arc.end][:2]) <= TOL:
            return True
        u = math.atan2(start[1] - arc.center[1], start[0] - arc.center[0])
        v = math.atan2(p[1] - arc.center[1], p[0] - arc.center[0])
        return (v - u) % math.tau <= arc.sweep

    candidates = []
    if b.kind == "line":
        length = math.dist(b0, b1)
        unit = ((b1[0] - b0[0]) / length, (b1[1] - b0[1]) / length)
        rel = (center[0] - b0[0], center[1] - b0[1])
        along = rel[0] * unit[0] + rel[1] * unit[1]
        perpendicular = abs(rel[0] * unit[1] - rel[1] * unit[0])
        if perpendicular <= radius + TOL:
            delta = math.sqrt(max(0, (radius - perpendicular) * (radius + perpendicular)))
            for t in (along - delta, along + delta):
                if -TOL <= t <= length + TOL:
                    candidates.append((b0[0] + t * unit[0], b0[1] + t * unit[1]))
    else:
        other = b.center[:2]
        other_radius = math.dist(b0, other)
        distance = math.dist(center, other)
        if distance <= TOL:
            if abs(other_radius - radius) > TOL:
                return False
            # On a common circle, overlapping arc interiors are invalid.
            for arc, start, end, other_arc, other_start in ((a, a0, a1, b, b0), (b, b0, b1, a, a0)):
                mid = math.atan2(start[1] - arc.center[1], start[0] - arc.center[0]) + arc.sweep / 2
                midpoint = (
                    arc.center[0] + radius * math.cos(mid),
                    arc.center[1] + radius * math.sin(mid),
                )
                if any(
                    on_arc(p, other_arc, other_start) and not allowed(p)
                    for p in (start, midpoint, end)
                ):
                    return True
            return False
        if distance > radius + other_radius + TOL or distance < abs(radius - other_radius) - TOL:
            return False
        unit = ((other[0] - center[0]) / distance, (other[1] - center[1]) / distance)
        along = (distance**2 + (radius - other_radius) * (radius + other_radius)) / (2 * distance)
        half = math.sqrt(max(0, (radius - along) * (radius + along)))
        middle = (center[0] + along * unit[0], center[1] + along * unit[1])
        for h in (half, -half):
            point = (middle[0] - h * unit[1], middle[1] + h * unit[0])
            if on_arc(point, b, b0):
                candidates.append(point)
    return any(on_arc(pt, a, a0) and not allowed(pt) for pt in candidates)


def _sampled_invalid(a, b, coordinates, samples):
    """Spline proximity check on the canonical tessellation.

    A spline has no closed-form intersection here, so the check runs on samples
    within the curve's own chord tolerance and reports only intersections that
    are not shared CAD vertices. Treat a hit as a warning to split the curve.
    """
    common = [coordinates[v][:2] for v in {a.start, a.end} & {b.start, b.end}]
    pad = max(TOL, *[e.spline.tolerance for e in (a, b) if e.kind == "spline"])

    def allowed(point):
        return any(math.dist(point, q) <= pad for q in common)

    first = LineString([p[:2] for p in samples[a.id]])
    second = LineString([p[:2] for p in samples[b.id]])
    crossing = first.intersection(second)
    if crossing.is_empty:
        return False
    pieces = (
        list(crossing.geoms) if crossing.geom_type.startswith("Multi") else [crossing]
    )
    return any(
        not (piece.geom_type == "Point" and allowed(piece.coords[0])) for piece in pieces
    )


def validate_intersections(project, samples):
    coordinates = {v.id: v.xyz for v in project.vertices}
    boxes = []
    for edge in project.edges:
        pts = samples[edge.id]
        # Exact upper bound on the circular chord's departure from its segment.
        pad = TOL
        if edge.kind == "arc":
            radius = math.dist(pts[0], edge.center)
            pad += radius * (1 - math.cos(edge.sweep / (2 * (len(pts) - 1))))
        x, y = zip(*(p[:2] for p in pts))
        boxes.append(box(min(x) - pad, min(y) - pad, max(x) + pad, max(y) + pad))
    tree = STRtree(boxes)
    for i, boundary in enumerate(boxes):
        a = project.edges[i]
        for j in tree.query(boundary):
            if j <= i:
                continue
            b = project.edges[j]
            if invalid_pair(a, b, coordinates, samples):
                raise ValueError(
                    f"Edges from handles {a.source_handle} and {b.source_handle} cross or overlap. Split curves at shared endpoints."
                )
            if a.component != b.component and {a.start, a.end} & {b.start, b.end}:
                raise ValueError(
                    "Separate the rigid panel profile from the undeformed section before import."
                )
