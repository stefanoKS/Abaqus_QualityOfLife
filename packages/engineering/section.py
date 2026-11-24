"""Shared assembly of analytic curves into regions, components and a project.

Both the DXF reader and the native DWG reader feed their curves through here, so a
drawing has exactly one canonical result regardless of the reader that produced
it. Only entity decoding differs; the geometry model, cavity detection,
connectivity split and the import report do not.
"""

from collections import Counter, defaultdict
import math

from shapely import polygonize_full
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient

from .geometry import example_materials, face_polygon, sample_edges
from .intersections import validate_intersections
from .model import Component, Face, Project, Selection

MAX_REGIONS = 512
# The existing spline join tolerance. Evaluated endpoints of a native spline and
# an adjoining line can differ by a sub-micron rounding amount; anything larger
# is a real gap and must be reported, never silently bridged.
JOIN_TOLERANCE = 1e-6


def merge_endpoints(builder, tolerance=JOIN_TOLERANCE):
    """Join evaluated endpoints within ``tolerance`` in model millimetres.

    The rule is order-independent: every vertex is compared with its spatial
    neighbourhood, and the surviving vertex is the earliest one in builder order,
    so the same drawing produces the same topology regardless of entity order or
    parameter direction. A joined pair reports the measured gap it closed.
    """
    vertices = builder.vertices
    snapped = list(getattr(builder, "snaps", []))
    if tolerance <= 0 or len(vertices) < 2:
        return {
            "merged": 0,
            "max_gap": max((item["gap"] for item in snapped), default=0.0),
            "collapsed": 0,
            "snapped": len(snapped),
            "gaps": snapped[:20],
            "nearest_gap": None,
            "nearest_pair": None,
        }
    parent = list(range(len(vertices)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first, second):
        left, right = find(first), find(second)
        if left != right:
            # The lower index is the deterministic survivor.
            parent[max(left, right)] = min(left, right)

    buckets = defaultdict(list)
    pair_gap = {}
    for index, vertex in enumerate(vertices):
        x, y = vertex.xyz[0], vertex.xyz[1]
        cell = (math.floor(x / tolerance), math.floor(y / tolerance))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in buckets.get((cell[0] + dx, cell[1] + dy), []):
                    ox, oy = vertices[other].xyz[0], vertices[other].xyz[1]
                    gap = math.dist((x, y), (ox, oy))
                    if gap <= tolerance:
                        union(index, other)
                        pair_gap[index] = min(pair_gap.get(index, gap), gap)
                        pair_gap[other] = min(pair_gap.get(other, gap), gap)
        buckets[cell].append(index)
    if all(find(index) == index for index in range(len(vertices))):
        nearest = _nearest_gap(vertices)
        return {
            "merged": 0,
            "max_gap": max((item["gap"] for item in snapped), default=0.0),
            "collapsed": 0,
            "snapped": len(snapped),
            "gaps": snapped[:20],
            "nearest_gap": nearest[0],
            "nearest_pair": nearest[1],
        }
    survivor = {}
    for index in range(len(vertices)):
        survivor[vertices[index].id] = vertices[find(index)].id
    kept = [vertex for index, vertex in enumerate(vertices) if find(index) == index]
    max_gap = max(
        max(pair_gap.values(), default=0.0),
        max((item["gap"] for item in snapped), default=0.0),
    )
    edges, collapsed = [], 0
    for edge in builder.edges:
        edge.start = survivor[edge.start]
        edge.end = survivor[edge.end]
        if edge.start == edge.end:
            collapsed += 1
            continue
        edges.append(edge)
    builder.vertices = kept
    builder.edges = edges
    builder.points = {
        (round(vertex.xyz[0], 8), round(vertex.xyz[1], 8), 0.0): vertex.id for vertex in kept
    }
    # Curve dedupe keys refer to removed ids; assembly no longer adds curves.
    builder.curves = {}
    nearest = _nearest_gap(kept)
    return {
        "merged": len(vertices) - len(kept),
        "max_gap": max_gap,
        "collapsed": collapsed,
        "snapped": len(snapped),
        "gaps": snapped[:20],
        "nearest_gap": nearest[0],
        "nearest_pair": nearest[1],
    }


def _nearest_gap(vertices):
    """Closest distinct surviving endpoints, so a real gap is reported, not bridged."""
    points = sorted((vertex.xyz[0], vertex.xyz[1], vertex.id) for vertex in vertices)
    best = None
    for index, (x, y, identifier) in enumerate(points):
        for other_x, other_y, other_id in points[index + 1 :]:
            if best is not None and other_x - x > best[0]:
                break
            gap = math.hypot(other_x - x, other_y - y)
            if gap > 0 and (best is None or gap < best[0]):
                best = (gap, [identifier, other_id])
    return (best[0], best[1]) if best else (None, None)


def _assign_components(project, components, faces):
    """Give every connected curve group one selectable component.

    Connectivity includes open chains and panel profiles, so a disconnected open
    curve keeps its own component instead of disappearing into the closed region
    it happens to share a layer with.
    """
    incident = defaultdict(set)
    by_id = {edge.id: edge for edge in project.edges}
    for edge in project.edges:
        if edge.component == "panel":
            continue
        incident[edge.start].add(edge.end)
        incident[edge.end].add(edge.start)
    for face in faces:
        roots = [by_id[loop[0].lstrip("-")].start for loop in face.loops]
        for other in roots[1:]:
            incident[roots[0]].add(other)
            incident[other].add(roots[0])
    labels = {}
    count = 0
    for vertex in incident:
        if vertex in labels:
            continue
        count += 1
        component_id = "section" if count == 1 else "section" + str(count)
        if count > 1:
            components.append(
                Component(id=component_id, name=f"Section {count}", role="unassigned")
            )
        stack = [vertex]
        while stack:
            node = stack.pop()
            if node not in labels:
                labels[node] = component_id
                stack.extend(incident[node] - labels.keys())
    for edge in project.edges:
        if edge.component != "panel":
            edge.component = labels.get(edge.start, edge.component)
    for face in faces:
        face.component = by_id[face.loops[0][0].lstrip("-")].component
    return components



def chains(edges):
    """Group edges by shared endpoints; return ``(closed_edge_ids, open_groups)``.

    A chain is closed when none of its vertices has a single incident edge, so a
    reversed or unordered set of LINE entities still closes its contour while an
    accidental near-touch does not join two separate profiles.
    """
    incident = defaultdict(set)
    degree = Counter()
    by_id = {}
    for edge in edges:
        incident[edge.start].add(edge.id)
        incident[edge.end].add(edge.id)
        degree[edge.start] += 1
        degree[edge.end] += 1
        by_id[edge.id] = edge
    if not incident:
        return set(), []
    adjacency = defaultdict(set)
    for vertex, edge_ids in incident.items():
        for edge_id in edge_ids:
            edge = by_id[edge_id]
            other = edge.end if edge.start == vertex else edge.start
            adjacency[edge_id].update(incident.get(other, set()) - {edge_id})
    seen = set()
    closed, opened = set(), []
    for edge in edges:
        if edge.id in seen:
            continue
        group, stack = [], [edge.id]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            group.append(current)
            stack.extend(adjacency[current] - seen)
        members = set(group)
        dangling = [
            vertex
            for vertex in incident
            if degree[vertex] == 1 and incident[vertex] & members
        ]
        if dangling:
            opened.append(group)
        else:
            closed.update(group)
    return closed, opened


def assemble(builder, name, source, *, allow_open_profiles=False):
    """Build the project from ``builder`` curves and return ``(project, report)``."""
    joins = merge_endpoints(builder)
    components = [Component(id="section", name="Imported section", role="unassigned")]
    if any(edge.component == "panel" for edge in builder.edges):
        components.append(Component(id="panel", name="Panel profile", role="unassigned"))
    project = Project(
        schema_version=4,
        name=name,
        vertices=builder.vertices,
        edges=builder.edges,
        faces=[],
        components=components,
        materials=example_materials(),
        selections=[Selection(id="mount", name="Fixed mounting")],
        source=source,
    )
    samples = sample_edges(project)
    validate_intersections(project, samples)
    report = {
        "curves": len(project.edges),
        "vertices": len(project.vertices),
        "splines": sum(1 for edge in project.edges if edge.kind == "spline"),
        "excluded": [],
        "regions": 0,
        "cavities": 0,
        "filledArea": 0.0,
        "unresolved": [],
        "openChains": 0,
        "closedRegions": 0,
        "openProfiles": [],
        "joins": {
            "tolerance": JOIN_TOLERANCE,
            "merged": joins["merged"],
            "snapped": joins.get("snapped", 0),
            "maxGap": joins["max_gap"],
            "collapsed": joins["collapsed"],
            "gaps": joins.get("gaps", []),
            "nearestGap": joins.get("nearest_gap"),
            "nearestPair": joins.get("nearest_pair"),
        },
    }
    section = [edge for edge in project.edges if edge.component != "panel"]
    if not section:
        raise ValueError(
            "Include at least one section curve outside the panel profile."
        )
    closed_ids, opened = chains(section)
    report["openChains"] = len(opened)
    open_ids = {edge_id for group in opened for edge_id in group}
    if open_ids and not allow_open_profiles:
        raise ValueError(
            "Open, dangling, or ambiguous section contours. Close gaps, split T-junctions, and put open rigid profiles on layer PANEL."
        )
    if opened:
        # Disconnected curves stay in the model as selectable open profiles. They
        # are usable as a rigid profile but never become a material region.
        by_id = {edge.id: edge for edge in section}
        for group in opened:
            first = by_id[group[0]]
            report["excluded"].append(
                {
                    "handles": [by_id[edge_id].source_handle for edge_id in group],
                    "labels": [by_id[edge_id].name for edge_id in group],
                    "kind": first.kind,
                    "curves": len(group),
                    "reason": "open profile; no closed material region",
                }
            )
    if not closed_ids:
        if not allow_open_profiles:
            raise ValueError(
                "The drawing has no closed region. Close the weatherstrip contour or review the excluded curves in the import report."
            )
        # An open-only drawing is a valid, inspectable model: zero material
        # faces, every source curve preserved, and simulation blocked until a
        # closed seal exists.
        _assign_components(project, components, [])
        report["closedRegions"] = 0
        report["openProfiles"] = [
            {
                "component": by_id[group[0]].component,
                "curves": len(group),
                "handles": [by_id[edge_id].source_handle for edge_id in group],
                "kinds": sorted({by_id[edge_id].kind for edge_id in group}),
            }
            for group in opened
        ]
        report["readiness"] = {
            "code": "drawing.no_closed_region",
            "openProfiles": len(opened),
            "message": "No closed structural seal. Save or inspect the curves, then close the contour in CAD to simulate.",
        }
        return (
            Project.model_validate(
                {**project.model_dump(), "faces": [], "components": components}
            ),
            report,
        )
    rings = {edge_id: LineString([point[:2] for point in samples[edge_id]]) for edge_id in closed_ids}
    polygons, cuts, dangles, invalid = polygonize_full(list(rings.values()))
    if not all(geometry.is_empty for geometry in (cuts, dangles, invalid)) or polygons.is_empty:
        details = [
            f"{geometry.geom_type} near ({round(geometry.bounds[0], 3)}, {round(geometry.bounds[1], 3)})"
            for geometry in list(cuts.geoms) + list(dangles.geoms) + list(invalid.geoms)
        ]
        raise ValueError(
            "Ambiguous section contours: "
            + "; ".join(details[:4])
            + ". Close gaps or split T-junctions before importing."
        )
    segment_map = {}
    for edge_id, line in rings.items():
        coordinates = list(line.coords)
        for a, b in zip(coordinates, coordinates[1:]):
            segment_map[(a, b)] = edge_id
            segment_map[(b, a)] = "-" + edge_id

    def trace(ring):
        coordinates = list(ring.coords)
        tokens = []
        for a, b in zip(coordinates, coordinates[1:]):
            token = segment_map[(a, b)]
            if not tokens or token != tokens[-1]:
                tokens.append(token)
        if len(tokens) > 1 and tokens[0] == tokens[-1]:
            tokens.pop()
        return tokens

    cells = [orient(poly, sign=1) for poly in polygons.geoms]
    if len(cells) > MAX_REGIONS:
        raise ValueError("Drawing exceeds the 512 region limit.")
    shells = [Polygon(poly.exterior) for poly in cells]
    faces = []
    cavity_count = 0
    for index, poly in enumerate(cells):
        inside = poly.representative_point()
        nesting = sum(
            other.contains(inside) for position, other in enumerate(shells) if position != index
        )
        cavity = bool(nesting % 2)
        cavity_count += int(cavity)
        region_name = (
            f"Cavity {cavity_count}" if cavity else f"Region {len(faces) + 1 - cavity_count}"
        )
        loops = [trace(ring) for ring in (poly.exterior, *poly.interiors)]
        faces.append(
            Face(
                id=f"f{builder.prefix}{len(faces) + 1}",
                name=region_name,
                cavity=cavity,
                component="section",
                loops=loops,
            )
        )
    # Every curve keeps an owner, so no imported entity silently disappears. The
    # connectivity split also gives a disconnected open curve its own component.
    _assign_components(project, components, faces)
    report["closedRegions"] = 1
    report["regions"] = len([face for face in faces if not face.cavity])
    report["cavities"] = cavity_count
    report["filledArea"] = sum(
        face_polygon(face, samples).area for face in faces if not face.cavity
    )
    report["unresolved"] = [
        {"handle": edge.source_handle, "label": edge.name, "component": edge.component}
        for edge in project.edges
        if edge.id not in closed_ids and edge.source_handle
    ]
    return (
        Project.model_validate(
            {**project.model_dump(), "faces": faces, "components": components}
        ),
        report,
    )
