"""Shared assembly of analytic curves into regions, components and a project.

Both the DXF reader and the native DWG reader feed their curves through here, so a
drawing has exactly one canonical result regardless of the reader that produced
it. Only entity decoding differs; the geometry model, cavity detection,
connectivity split and the import report do not.
"""

from collections import Counter, defaultdict

from shapely import polygonize_full
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient

from .geometry import example_materials, face_polygon, sample_edges
from .intersections import validate_intersections
from .model import Component, Face, Project, Selection

MAX_REGIONS = 512


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
    components = [Component(id="section", name="Imported section", role="unassigned")]
    if any(edge.component == "panel" for edge in builder.edges):
        components.append(Component(id="panel", name="Panel profile", role="unassigned"))
    project = Project(
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
    }
    section = [edge for edge in project.edges if edge.component != "panel"]
    if not section:
        raise ValueError("Include at least one closed section region outside the panel profile.")
    closed_ids, opened = chains(section)
    report["openChains"] = len(opened)
    if any(edge.id not in closed_ids for edge in section):
        if not allow_open_profiles:
            raise ValueError(
                "Open, dangling, or ambiguous section contours. Close gaps, split T-junctions, and put open rigid profiles on layer PANEL."
            )
        by_id = {edge.id: edge for edge in section}
        for group in opened:
            first = by_id[group[0]]
            report["excluded"].append(
                {
                    "handles": [by_id[edge_id].source_handle for edge_id in group],
                    "labels": [by_id[edge_id].name for edge_id in group],
                    "kind": first.kind,
                    "curves": len(group),
                    "reason": "open profile; usable as a rigid panel, not as a material region",
                }
            )
    if not closed_ids:
        raise ValueError(
            "The drawing has no closed region. Close the weatherstrip contour or review the excluded curves in the import report."
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
    # Every curve keeps an owner, so no imported entity silently disappears.
    incident = defaultdict(set)
    for edge in project.edges:
        incident[edge.start].add(edge.end)
        incident[edge.end].add(edge.start)
    edges = {edge.id: edge for edge in project.edges}
    for face in faces:
        roots = [edges[loop[0].lstrip("-")].start for loop in face.loops]
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
        if edge.component == "section":
            edge.component = labels[edge.start]
    for face in faces:
        face.component = edges[face.loops[0][0].lstrip("-")].component
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
