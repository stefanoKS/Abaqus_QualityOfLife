"""Measure the produced FE boundary against the analytic drawing curves.

A display tessellation is not evidence: it is produced by the same tolerance it
is supposed to prove. These helpers evaluate the source curve independently
(analytic line/arc, or the canonical spline) and measure the distance from those
samples to the mesh boundary polyline, between nodes as well as at nodes.
"""

import math

from .spline import curve as spline_curve

DEFAULT_SAMPLES = 400


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, 0.0)


def source_samples(project, edge, count=DEFAULT_SAMPLES):
    """Points on the exact curve of ``edge``; independent of the display sampling."""
    vertices = {vertex.id: vertex.xyz for vertex in project.vertices}
    a, b = vertices[edge.start], vertices[edge.end]
    if edge.kind == "line":
        return [_lerp(a, b, index / (count - 1)) for index in range(count)]
    if edge.kind == "arc":
        centre = edge.center
        radius = math.dist(a, centre)
        start = math.atan2(a[1] - centre[1], a[0] - centre[0])
        return [
            (
                centre[0] + radius * math.cos(start + edge.sweep * index / (count - 1)),
                centre[1] + radius * math.sin(start + edge.sweep * index / (count - 1)),
                0.0,
            )
            for index in range(count)
        ]
    spline = spline_curve(edge.spline)
    return [
        tuple(spline.point(spline.max_t * index / (count - 1))) for index in range(count)
    ]


def _segment_distance(point, a, b):
    ax, ay = a[0], a[1]
    bx, by = b[0], b[1]
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    if length <= 1e-18:
        return math.dist(point[:2], (ax, ay))
    t = ((point[0] - ax) * dx + (point[1] - ay) * dy) / length
    t = min(1.0, max(0.0, t))
    return math.dist(point[:2], (ax + t * dx, ay + t * dy))


def polyline_deviation(samples, polyline):
    """Worst distance from ``samples`` to the polyline, measured between nodes."""
    points = [tuple(point) for point in polyline]
    if len(points) < 2:
        return math.inf
    worst = 0.0
    for point in samples:
        best = min(
            _segment_distance(point, points[i], points[i + 1]) for i in range(len(points) - 1)
        )
        worst = max(worst, best)
    return worst


def edge_polyline(mesh, edge_id, closed=False):
    """Ordered boundary polyline of one edge, closed when the edge is a loop.

    A closed curve shares its start and end vertex, so the mesh stores the seam
    node once; the final segment that returns to it has to be restored before the
    boundary can be compared with the source curve.
    """
    coordinates = {node["id"]: node["xyz"] for node in mesh["nodes"]}
    labels = mesh["edge_nodes"].get(edge_id, [])
    points = [coordinates[label] for label in labels if label in coordinates]
    if closed and len(points) > 2:
        points.append(points[0])
    return points


def measure(project, mesh, samples=DEFAULT_SAMPLES):
    """Per-edge and per-group boundary error in millimetres.

    Groups: the outer weatherstrip boundary, the cavity, and the rigid door/body
    profiles. ``worst`` is the largest error over every measured boundary.
    """
    roles = {component.id: component.role for component in project.components}
    faces = {face.id: face for face in project.faces}
    outer, cavity, rigid = {}, {}, {}
    for face in project.material_regions:
        for position, loop in enumerate(face.loops):
            for token in loop:
                edge_id = token.lstrip("-")
                edge = next((item for item in project.edges if item.id == edge_id), None)
                if edge is None:
                    continue
                polyline = edge_polyline(mesh, edge_id, closed=edge.start == edge.end)
                if len(polyline) < 2:
                    continue
                error = polyline_deviation(source_samples(project, edge, samples), polyline)
                target = outer if position == 0 else cavity
                target[edge_id] = error
    for edge in project.edges:
        if roles.get(edge.component) != "moving_panel":
            continue
        polyline = edge_polyline(mesh, edge.id, closed=edge.start == edge.end)
        if len(polyline) < 2:
            continue
        rigid[edge.id] = polyline_deviation(
            source_samples(project, edge, samples), polyline
        )
    groups = {
        "outerWs": max(outer.values(), default=0.0),
        "cavity": max(cavity.values(), default=0.0),
        "door": max(rigid.values(), default=0.0),
    }
    return {
        "groups": groups,
        "worst": max(groups.values(), default=0.0),
        "edges": {"outerWs": outer, "cavity": cavity, "door": rigid},
        "faces": len(faces),
    }


def fit_point_errors(project, mesh, samples=DEFAULT_SAMPLES):
    """Distance from every stored fit point to the FE boundary of its own edge."""
    result = {}
    for edge in project.edges:
        if edge.kind != "spline" or not edge.spline.fit_points:
            continue
        polyline = edge_polyline(mesh, edge.id, closed=edge.start == edge.end)
        if len(polyline) < 2:
            continue
        result[edge.id] = [
            min(_segment_distance(point, polyline[i], polyline[i + 1]) for i in range(len(polyline) - 1))
            for point in edge.spline.fit_points
        ]
    return result
