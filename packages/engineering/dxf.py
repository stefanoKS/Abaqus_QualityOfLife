"""Read a deliberately bounded planar DXF subset into analytic CAD entities."""

from collections import Counter, defaultdict
from hashlib import sha256
import math
from pathlib import Path

import ezdxf
from shapely import polygonize_full
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient

from .geometry import Builder, example_materials, sample_edges
from .intersections import validate_intersections
from .model import Component, Face, Project, Selection, Source

PANEL_LAYERS = {"PANEL", "MOVING_PANEL"}
MAX_DRAWING = 8 * 1024 * 1024


def import_dxf(path: Path, name: str, units: str = "N-mm-s-tonne") -> Project:
    path = Path(path)
    if units != "N-mm-s-tonne":
        raise ValueError("Select N-mm-s-tonne and confirm drawing coordinates are in millimetres.")
    if path.stat().st_size > MAX_DRAWING:
        raise ValueError("DXF exceeds the 8 MiB limit.")
    digest = sha256(path.read_bytes()).hexdigest()
    try:
        doc = ezdxf.readfile(path)
    except (ezdxf.DXFError, OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"Could not read drawing as DXF: {exc}") from exc
    if doc.units not in (0, 4):
        raise ValueError(
            "DXF declares non-millimetre drawing units. Convert the drawing to mm before importing."
        )
    builder = Builder(prefix=digest[:10] + "_")
    seen_poly = set()
    unsupported = Counter()
    for ent in doc.modelspace():
        kind = ent.dxftype()
        handle = ent.dxf.handle
        layer = ent.dxf.layer
        if kind not in ("LINE", "ARC", "CIRCLE", "LWPOLYLINE"):
            unsupported[kind] += 1
            continue
        if abs(ent.dxf.get("thickness", 0)) > 1e-8 or any(
            abs(x - y) > 1e-8 for x, y in zip(ent.dxf.get("extrusion", (0, 0, 1)), (0, 0, 1))
        ):
            raise ValueError(
                f"{kind} {handle}: flatten thickness and orient the section in the XY plane."
            )
        component = "panel" if layer.upper() in PANEL_LAYERS else "section"

        def add(a, b, **kwargs):
            return builder.edge(a, b, component, handle=handle, layer=layer, **kwargs)

        def read_segment(segment):
            if segment.dxftype() == "LINE":
                return [add(tuple(segment.dxf.start), tuple(segment.dxf.end))]
            c = tuple(segment.dxf.center)
            radius = segment.dxf.radius
            if not math.isfinite(radius) or radius < 1e-7:
                raise ValueError(f"{handle}: invalid radius.")
            begin, span = 0.0, math.tau
            if segment.dxftype() == "ARC":
                begin = math.radians(segment.dxf.start_angle)
                span = math.radians((segment.dxf.end_angle - segment.dxf.start_angle) % 360)
                if span < 1e-8:
                    raise ValueError(f"ARC {handle}: zero sweep. Use CIRCLE for a full circle.")
            # Smaller analytic arcs share endpoints and are unambiguous in OCC.
            n = math.ceil(span / (math.pi / 2))
            pts = [
                (
                    c[0] + radius * math.cos(begin + span * i / n),
                    c[1] + radius * math.sin(begin + span * i / n),
                    c[2],
                )
                for i in range(n + 1)
            ]
            return [add(a, b, center=c, sweep=span / n) for a, b in zip(pts, pts[1:])]

        if kind == "LWPOLYLINE":
            if not ent.closed:
                raise ValueError(
                    f"LWPOLYLINE {handle} is open. Close the contour or explode panel profiles into LINE/ARC."
                )
            if ent.has_width:
                raise ValueError(
                    f"LWPOLYLINE {handle} has width. Export its section boundary as zero-width curves."
                )
            if abs(ent.dxf.elevation) > 1e-8:
                raise ValueError(f"LWPOLYLINE {handle} has elevation. Move it to Z = 0.")
            if len(ent) > 4096:
                raise ValueError("Polyline exceeds the 4096-edge limit.")
            tokens = [
                token.lstrip("-") for part in ent.virtual_entities() for token in read_segment(part)
            ]
            key = frozenset(tokens)
            if not tokens or key in seen_poly or len(key) != len(tokens):
                raise ValueError(f"LWPOLYLINE {handle}: remove duplicate or retraced contours.")
            seen_poly.add(key)
        else:
            before = len(builder.edges)
            tokens = read_segment(ent)
            if len(builder.edges) - before != len(tokens):
                raise ValueError(f"{kind} {handle}: remove duplicate standalone curves.")
    if unsupported:
        details = ", ".join(f"{n} {k}" for k, n in sorted(unsupported.items()))
        raise ValueError(
            f"Unsupported DXF entities ({details}). Explode INSERT blocks and export LINE, ARC, CIRCLE or closed LWPOLYLINE only."
        )
    if not builder.edges:
        raise ValueError("The DXF model space has no supported entities.")
    components = [Component(id="section", name="Imported section", role="unassigned")]
    if any(e.component == "panel" for e in builder.edges):
        components.append(Component(id="panel", name="Panel profile", role="unassigned"))
    project = Project(
        name=name,
        vertices=builder.vertices,
        edges=builder.edges,
        faces=[],
        components=components,
        materials=example_materials(),
        selections=[Selection(id="mount", name="Fixed mounting")],
        source=Source(
            kind="dxf",
            filename=path.name,
            digest=digest,
            drawing_units="millimetres" if doc.units == 4 else "unitless; confirmed as millimetres",
        ),
    )
    samples = sample_edges(project)
    lines = [LineString([p[:2] for p in samples[e.id]]) for e in project.edges]
    validate_intersections(project, samples)
    section = [
        (edge, line) for edge, line in zip(project.edges, lines) if edge.component == "section"
    ]
    if not section:
        raise ValueError("Include at least one closed section region outside the PANEL layer.")
    polygons, cuts, dangles, invalid = polygonize_full([line for _, line in section])
    if not all(g.is_empty for g in (cuts, dangles, invalid)) or polygons.is_empty:
        raise ValueError(
            "Open, dangling, or ambiguous section contours. Close gaps, split T-junctions, and put open rigid profiles on layer PANEL."
        )
    # Trace polygon rings back to complete analytic edges, keeping reversed uses.
    segment_map = {}
    for edge, line in section:
        coords = list(line.coords)
        for a, b in zip(coords, coords[1:]):
            segment_map[(a, b)] = edge.id
            segment_map[(b, a)] = "-" + edge.id

    def trace(ring):
        coords = list(ring.coords)
        tokens = []
        for a, b in zip(coords, coords[1:]):
            token = segment_map[(a, b)]
            if not tokens or token != tokens[-1]:
                tokens.append(token)
        if len(tokens) > 1 and tokens[0] == tokens[-1]:
            tokens.pop()
        return tokens

    cells = [orient(poly, sign=1) for poly in polygons.geoms]
    if len(cells) > 512:
        raise ValueError("Drawing exceeds the 512 region limit.")
    shells = [Polygon(poly.exterior) for poly in cells]
    faces = []
    cavity_count = 0
    for i, poly in enumerate(cells):
        inside = poly.representative_point()
        nesting = sum(other.contains(inside) for j, other in enumerate(shells) if i != j)
        cavity = bool(nesting % 2)
        cavity_count += int(cavity)
        region_name = (
            f"Cavity {cavity_count}" if cavity else f"Region {len(faces) + 1 - cavity_count}"
        )
        loops = [trace(r) for r in (poly.exterior, *poly.interiors)]
        faces.append(
            Face(
                id=f"f{builder.prefix}{len(faces) + 1}",
                name=region_name,
                cavity=cavity,
                component="section",
                loops=loops,
            )
        )
    # A section can contain disconnected components. Split ownership by CAD vertices.
    incident = defaultdict(set)
    for e in project.edges:
        if e.component == "section":
            incident[e.start].add(e.end)
            incident[e.end].add(e.start)
    # Holes belong to the component of their outer wire.
    edges = {e.id: e for e in project.edges}
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
        cid = "section" if count == 1 else f"section{count}"
        if count > 1:
            components.append(Component(id=cid, name=f"Section {count}", role="unassigned"))
        stack = [vertex]
        while stack:
            node = stack.pop()
            if node not in labels:
                labels[node] = cid
                stack.extend(incident[node] - labels.keys())
    for edge in project.edges:
        if edge.component == "section":
            edge.component = labels[edge.start]
    for face in faces:
        face.component = edges[face.loops[0][0].lstrip("-")].component
    return Project.model_validate(
        {**project.model_dump(), "faces": faces, "components": components}
    )
