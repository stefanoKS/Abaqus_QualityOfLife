"""Analytic section entities and their disposable display tessellation."""

import math
from collections import defaultdict

from shapely import constrained_delaunay_triangles
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from .model import Component, Edge, Face, Material, Project, Selection, Source, Vertex
from .spline import endpoint_points as spline_endpoints
from .spline import tessellate


class Builder:
    """Join coincident vertices and exact duplicate curves before building OCC wires."""

    def __init__(self, prefix=""):
        self.prefix = prefix
        self.vertices = []
        self.edges = []
        self.points = {}
        self.curves = {}
        self.splines = {}
        # Measured endpoint snaps, so an import report can state the gap that was
        # closed instead of silently hiding it.
        self.snaps = []

    def vertex(self, xyz, tolerance=0.0):
        x, y, z = xyz
        if not all(math.isfinite(n) for n in (x, y, z)) or abs(z) > 1e-8:
            raise ValueError("Move all section entities to the XY plane at Z = 0.")
        xyz = (x, y, 0)
        key = tuple(round(float(k), 8) for k in xyz)
        if key not in self.points and tolerance > 0:
            # Only splines snap: a converted B-spline endpoint can differ from the
            # adjoining line's endpoint by a sub-micron rounding amount.
            for existing, vertex_id in self.points.items():
                gap = math.dist(existing[:2], key[:2])
                if gap <= tolerance:
                    self.snaps.append(
                        {
                            "vertex": vertex_id,
                            "xyz": list(key),
                            "gap": gap,
                            "tolerance": tolerance,
                        }
                    )
                    return vertex_id
        if key not in self.points:
            vertex = Vertex(id=f"v{self.prefix}{len(self.vertices) + 1}", xyz=xyz)
            self.points[key] = vertex.id
            self.vertices.append(vertex)
        return self.points[key]

    def edge(self, a, b, component, *, center=None, sweep=None, name="", handle="", layer=""):
        start, end = self.vertex(a), self.vertex(b)
        key = (tuple(sorted([start, end])), tuple(round(c, 8) for c in center) if center else None)
        if center:
            mid = math.atan2(a[1] - center[1], a[0] - center[0]) + sweep / 2
            key += (round(math.cos(mid), 8), round(math.sin(mid), 8))
        if key in self.curves:
            edge = self.curves[key]
            if edge.component != component:
                raise ValueError("Rigid panel and section boundaries must not coincide.")
            return edge.id if start == edge.start else "-" + edge.id
        index = len(self.edges) + 1
        edge = Edge(
            id=f"e{self.prefix}{index}",
            name=name or f"Edge {index}",
            component=component,
            start=start,
            end=end,
            kind="arc" if center else "line",
            center=center,
            sweep=sweep,
            source_handle=handle,
            layer=layer,
        )
        self.edges.append(edge)
        self.curves[key] = edge
        if len(self.edges) > 4096:
            raise ValueError("Section exceeds the 4096 analytic edge limit. Simplify the drawing.")
        return edge.id

    def spline(self, data, component, *, name="", handle="", layer=""):
        """Add the canonical spline curve; vertices come from its true endpoints."""
        if handle and handle in self.splines:
            return self.splines[handle]
        start_xyz, end_xyz = spline_endpoints(data)
        start, end = self.vertex(start_xyz, 1e-6), self.vertex(end_xyz, 1e-6)
        index = len(self.edges) + 1
        edge = Edge(
            id=f"e{self.prefix}{index}",
            name=name or f"Spline {index}",
            component=component,
            start=start,
            end=end,
            kind="spline",
            spline=data,
            source_handle=handle,
            layer=layer,
        )
        self.edges.append(edge)
        if handle:
            self.splines[handle] = edge.id
        if len(self.edges) > 4096:
            raise ValueError("Section exceeds the 4096 analytic edge limit. Simplify the drawing.")
        return edge.id


def example_materials():
    # Fictional demonstration curves in N-mm-s-tonne. No supplier data.
    return [
        Material(
            id="bulb_foam",
            name="Cellular EPDM",
            color="#46ad94",
            model="hyperfoam_test",
            density=5.2e-10,
            test_data=[
                (0, 0, 0),
                (0.13, 0.1, -0.015),
                (0.31, 0.25, -0.035),
                (0.68, 0.5, -0.06),
                (1.15, 0.75, -0.08),
            ],
        ),
        Material(
            id="base_rubber",
            name="Dense EPDM",
            color="#dc9b50",
            model="linear_elastic",
            density=1.15e-9,
            young=6.2,
            poisson=0.44,
        ),
    ]


def synthetic(name="Hollow bulb section"):
    b = Builder()

    def edge(a, z, label):
        return b.edge((*a, 0), (*z, 0), "seal", name=label)

    mount = edge((-9, 0), (9, 0), "Mounting foot")
    right = edge((9, 0), (9, 3.2), "Foot · right")
    interface = edge((-9, 3.2), (9, 3.2), "Bonded interface")
    left = edge((-9, 3.2), (-9, 0), "Foot · left")

    def arch(radius, height, label):
        o = (0, height, 0)
        crown = (0, height + radius, 0)
        first = b.edge(
            (radius, height, 0), crown, "seal", center=o, sweep=math.pi / 2, name=label + " · right"
        )
        second = b.edge(
            crown, (-radius, height, 0), "seal", center=o, sweep=math.pi / 2, name=label + " · left"
        )
        return [first, second]

    outer = arch(9, 3.2, "Outer bulb")
    floor = edge((-6.8, 4.5), (6.8, 4.5), "Cavity floor")
    inner = arch(6.8, 4.5, "Cavity wall")
    b.edge((-12, 14, 0), (12, 14, 0), "panel", name="Panel contact profile")
    faces = [
        Face(
            id="foot",
            name="Mounting foot",
            component="seal",
            material="base_rubber",
            loops=[[mount, right, "-" + interface, left]],
        ),
        Face(
            id="bulb",
            name="Hollow bulb",
            component="seal",
            material="bulb_foam",
            loops=[[interface, *outer], ["-" + e for e in reversed([floor, *inner])]],
        ),
    ]
    return Project(
        schema_version=4,
        name=name,
        vertices=b.vertices,
        edges=b.edges,
        faces=faces,
        components=[
            Component(id="seal", name="Weatherstrip", role="seal"),
            Component(id="panel", name="Closing panel", role="moving_panel"),
        ],
        materials=example_materials(),
        selections=[Selection(id="mount", name="Fixed mounting", entities=[mount])],
        source=Source(kind="synthetic", filename="Hollow bulb section"),
    )


def two_panel_section(name="Two-panel seating section", body_y=-1.0, body_travel=5.0):
    """Door above the seal and a moving body below it.

    A named, intentionally specified example: the body sits 1 mm below the
    seal foot and the historical two-panel scenario's explicit 1.0 s body /
    1.3 s door durations are preserved. It is used by the API template, the
    acceptance harness and the two-step tests instead of a hand-built fixture.
    """
    project = synthetic(name)
    panel = next(edge for edge in project.edges if edge.component == "panel")
    start = next(vertex for vertex in project.vertices if vertex.id == panel.start)
    end = next(vertex for vertex in project.vertices if vertex.id == panel.end)
    project.components.append(
        Component(id="body", name="Body profile", role="vehicle_body")
    )
    project.vertices.append(Vertex(id="body-v1", xyz=(start.xyz[0], body_y, 0)))
    project.vertices.append(Vertex(id="body-v2", xyz=(end.xyz[0], body_y, 0)))
    project.edges.append(
        Edge(
            id="body-profile",
            name="Body contact profile",
            component="body",
            start="body-v1",
            end="body-v2",
        )
    )
    project.analysis.mode = "body_then_door"
    project.motion.body.stroke = abs(body_travel)
    project.motion.body.angle = -90 if body_travel < 0 else 90
    project.motion.body.duration = 1.0
    project.motion.duration = 1.3
    return Project.model_validate(project.model_dump(mode="json"))


def empty(name="Untitled model", dimension="2D"):
    """An explicit model with no drawing yet.

    No placeholder vertex, component, material region, filename or digest is
    invented: the absence of geometry is the state the engineer sees at Import.
    """
    return Project(
        schema_version=4,
        name=name,
        dimension=dimension,
        formulation="plane_stress" if dimension == "2D" else "extrusion_preview",
        source=Source(kind="empty", filename=""),
    )


def sample_edges(p):
    """Fixed engineering tessellation. Neither mesh nor screen zoom changes CAD.

    Arcs use a fixed angular step; splines adapt to their declared chord
    deviation, so refinement never changes the analytic curve it samples.
    """
    vertices = {v.id: v.xyz for v in p.vertices}
    result = {}
    for edge in p.edges:
        a, b = vertices[edge.start], vertices[edge.end]
        points = [a]
        if edge.kind == "arc":
            center = edge.center
            angle = math.atan2(a[1] - center[1], a[0] - center[0])
            radius = math.dist(a, center)
            count = max(2, math.ceil(edge.sweep / math.radians(4)))
            for i in range(1, count):
                t = angle + edge.sweep * i / count
                points.append(
                    (center[0] + radius * math.cos(t), center[1] + radius * math.sin(t), 0)
                )
        elif edge.kind == "spline":
            points.extend(tessellate(edge.spline)[1:-1])
        result[edge.id] = points + [b]
    return result


def face_polygon(face, curves):
    def ring(loop):
        points = []
        for token in loop:
            curve = curves[token.removeprefix("-")]
            points.extend((curve[::-1] if token.startswith("-") else curve)[:-1])
        return [v[:2] for v in points]

    rings = [ring(loop) for loop in face.loops]
    poly = Polygon(rings[0], rings[1:])
    if not poly.is_valid or poly.area < 1e-10:
        raise ValueError(
            f"{face.name}: invalid or intersecting region contours. Repair the drawing."
        )
    return orient(poly, sign=1)


def display(project):
    samples = sample_edges(project)
    faces_by_edge = defaultdict(list)
    primitives = []
    role = {c.id: c.role for c in project.components}
    length = project.extrusion.length if project.dimension == "3D" else 0

    def add(entity, component, kind, points, cells, *, source=None, material=None):
        offset = project.motion.offset if role[component] == "moving_panel" else 0
        primitives.append(
            dict(
                id=f"view-{kind}-{entity}",
                entity=entity,
                component=component,
                kind=kind,
                source=source or entity,
                material=material,
                points=[(p[0], p[1] + offset, p[2]) for p in points],
                cells=cells,
            )
        )

    for face in project.material_regions:
        poly = face_polygon(face, samples)
        points = {}
        triangles = []
        for triangle in constrained_delaunay_triangles(poly).geoms:
            ids = []
            for vertex in list(triangle.exterior.coords)[:3]:
                xy = vertex[:2]
                ids.append(points.setdefault(xy, len(points)))
            triangles.append(ids)
        if not triangles:
            raise ValueError(f"{face.name}: unable to triangulate region.")
        add(
            face.id,
            face.component,
            "face",
            [(x, y, 0) for x, y in points],
            triangles,
            material=face.material,
        )
        if length:
            add(
                "top-" + face.id,
                face.component,
                "face",
                [(x, y, length) for x, y in points],
                triangles,
                source=face.id,
                material=face.material,
            )
        for loop in face.loops:
            for token in loop:
                faces_by_edge[token.removeprefix("-")].append(face)
    for edge in project.edges:
        pts = samples[edge.id]
        add(edge.id, edge.component, "edge", pts, [list(range(len(pts)))])
        if length:
            face = next(iter(faces_by_edge[edge.id]), None)
            points = list(pts) + [(x, y, length) for x, y, _ in pts]
            n = len(pts)
            add(
                "side-" + edge.id,
                edge.component,
                "face",
                points,
                [[i, i + 1, n + i + 1, n + i] for i in range(n - 1)],
                source=face.id if face else edge.id,
                material=face.material if face else None,
            )
    points = [point for obj in primitives for point in obj["points"]]
    bounds = (
        [
            v
            for axis in range(3)
            for v in (min(p[axis] for p in points), max(p[axis] for p in points))
        ]
        if points
        else [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    )
    return dict(
        primitives=primitives, bounds=bounds, solids=[s.model_dump() for s in project.solids]
    )
