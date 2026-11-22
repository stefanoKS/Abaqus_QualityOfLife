"""Read a deliberately bounded planar DXF subset into analytic CAD entities."""

from collections import Counter
from hashlib import sha256
import math
from pathlib import Path

import ezdxf

from .geometry import Builder
from .model import Project, Source, SplineData
from .section import assemble
from . import units as units_policy

PANEL_LAYERS = {"PANEL", "MOVING_PANEL"}
MAX_DRAWING = 8 * 1024 * 1024


def _attribute(ent, name, default):
    """Read an optional DXF attribute; SPLINE and others do not define every header."""
    return ent.dxf.get(name, default) if ent.dxf.is_supported(name) else default


def _off_plane(ent):
    if abs(_attribute(ent, "thickness", 0)) > 1e-8:
        return True
    return any(
        abs(x - y) > 1e-8 for x, y in zip(_attribute(ent, "extrusion", (0, 0, 1)), (0, 0, 1))
    )


def import_dxf(path: Path, name: str, units: str = "N-mm-s-tonne") -> Project:
    path = Path(path)
    if units != "N-mm-s-tonne":
        raise ValueError("This application uses N-mm-s-tonne project units.")
    if path.stat().st_size > MAX_DRAWING:
        raise ValueError("DXF exceeds the 8 MiB limit.")
    digest = sha256(path.read_bytes()).hexdigest()
    try:
        doc = ezdxf.readfile(path)
    except (ezdxf.DXFError, OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"Could not read drawing as DXF: {exc}") from exc
    # The raw header distinguishes an explicit unitless drawing (0) from a
    # missing header; decode_units rejects any other declared unit by name.
    basis, unit_note = units_policy.interpret(doc.header.get("$INSUNITS", None), "DXF")
    builder = Builder(prefix=digest[:10] + "_")
    seen_poly = set()
    unsupported = Counter()
    for ent in doc.modelspace():
        kind = ent.dxftype()
        handle = ent.dxf.handle
        layer = ent.dxf.layer
        if kind not in ("LINE", "ARC", "CIRCLE", "LWPOLYLINE", "SPLINE"):
            unsupported[kind] += 1
            continue
        if _off_plane(ent):
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

        def read_spline(segment):
            control = [tuple(p) for p in segment.control_points]
            fits = [tuple(p) for p in segment.fit_points]
            if control:
                fits = []  # the control polygon is authoritative when both are stored
            elif not fits:
                raise ValueError(f"SPLINE {handle}: no control points or fit points.")
            if len(control) > 4096 or len(fits) > 4096:
                raise ValueError(f"SPLINE {handle}: exceeds the 4096 point limit.")
            degree = int(segment.dxf.degree)
            data = SplineData(
                degree=degree,
                control_points=control,
                fit_points=fits,
                knots=[float(k) for k in (segment.knots or ())],
                weights=[float(w) for w in (segment.weights or ())],
                closed=bool(segment.closed),
                periodic=bool(segment.get_flag_state(segment.PERIODIC)),
            )
            return builder.spline(
                data,
                component,
                name=f"Spline {handle}",
                handle=handle,
                layer=layer,
            )

        if kind == "SPLINE":
            tokens = [read_spline(ent)]
        elif kind == "LWPOLYLINE":
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
            f"Unsupported DXF entities ({details}). Explode INSERT blocks and export LINE, ARC, CIRCLE, SPLINE or closed LWPOLYLINE only."
        )
    if not builder.edges:
        raise ValueError("The DXF model space has no supported entities.")
    project, _report = assemble(
        builder,
        name,
        Source(
            kind="dxf",
            filename=path.name,
            digest=digest,
            drawing_units=unit_note,
            unit_basis=basis,
        ),
    )
    return project
