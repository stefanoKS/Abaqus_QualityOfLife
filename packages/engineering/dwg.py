"""Native DWG import: the drawing bytes go straight to the canonical model.

The decoding boundary is ``integrations/dwg`` (a small application-owned helper
linked to ACadSharp, MIT). This module only maps the decoded inventory onto the
same ``Builder``/``Project`` types the DXF reader uses, so both readers produce
one geometry model, one spline representation and one import report.
"""

from collections import Counter
from hashlib import sha256
import math
from pathlib import Path

from .geometry import Builder
from .model import Source, SplineData
from .section import assemble
from . import units as units_policy

SUPPORTED = {"LINE", "LWPOLYLINE", "POLYLINE", "SPLINE", "ARC", "CIRCLE", "POINT", "INSERT"}
MAX_DRAWING = 8 * 1024 * 1024
ARC_SEGMENTS = 4  # 90-degree analytic arcs share endpoints unambiguously in OCC


def _drawing_units(source):
    """Interpret the DWG unit header under the shared project unit policy."""
    declared = source.get("insUnits")
    if declared is None and source.get("insUnitsName"):
        declared = source.get("insUnitsName")
    return units_policy.interpret(declared, "DWG")


def _arc_parts(center, radius, start, sweep):
    """Split an arc into analytic CCW sub-arcs of at most a quarter turn.

    ``sweep`` may be negative (clockwise traversal); the returned points are then
    reversed so every consecutive pair is a counter-clockwise arc, which is what
    the canonical edge definition stores.
    """
    count = max(1, math.ceil(abs(sweep) / (math.pi / 2)))
    step = abs(sweep) / count
    direction = 1.0 if sweep >= 0 else -1.0
    points = [
        (
            center[0] + radius * math.cos(start + direction * step * index),
            center[1] + radius * math.sin(start + direction * step * index),
            0.0,
        )
        for index in range(count + 1)
    ]
    if direction < 0:
        points.reverse()
    return points, step


def _bulge_arc(first, second, bulge):
    """Return ``(centre, radius, start_angle, sweep)`` for a bulged segment, else ``None``."""
    if abs(bulge) < 1e-12:
        return None
    chord = math.dist(first[:2], second[:2])
    if chord < 1e-9:
        return None
    sweep = 4.0 * math.atan(bulge)  # signed included angle, positive is CCW
    radius = (chord / 2) / math.sin(abs(sweep) / 2)
    midpoint = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
    apothem = radius * math.cos(abs(sweep) / 2)
    unit = ((second[0] - first[0]) / chord, (second[1] - first[1]) / chord)
    normal = (-unit[1], unit[0]) if bulge > 0 else (unit[1], -unit[0])
    center = (midpoint[0] + normal[0] * apothem, midpoint[1] + normal[1] * apothem)
    start = math.atan2(first[1] - center[1], first[0] - center[0])
    return center, radius, start, sweep


def import_inventory(inventory, name, units="N-mm-s-tonne", digest=""):
    """Map a DWG inventory (see ``integrations/dwg``) onto a project and a report."""
    if units != "N-mm-s-tonne":
        raise ValueError("This application uses N-mm-s-tonne project units.")
    source = inventory.get("source", {})
    unit = _drawing_units(source)
    builder = Builder(prefix=(digest or source.get("sha256") or "")[:10] + "_")
    counts = Counter()
    skipped = []
    warnings = list(inventory.get("warnings", []))
    spline_provenance = Counter()

    def point(value, label):
        return unit.point(tuple(value), label)

    def length(value, label):
        return unit.apply(value, label)

    for entity in inventory.get("entities", []):
        kind = entity.get("type", "")
        handle = entity.get("handle", "")
        layer = entity.get("layer", "") or "0"
        if kind == "LINE":
            builder.edge(
                point(entity["start"], f"Line {handle}"),
                point(entity["end"], f"Line {handle}"),
                "section",
                name=f"Line {handle}",
                handle=handle,
                layer=layer,
            )
        elif kind == "ARC":
            sweep = (entity["endAngle"] - entity["startAngle"]) % math.tau
            if sweep <= 1e-9:
                skipped.append({"handle": handle, "reason": "zero-sweep arc"})
                continue
            center = point(entity["center"], f"Arc {handle} center")
            parts, step = _arc_parts(
                center, length(entity["radius"], f"Arc {handle} radius"), entity["startAngle"], sweep
            )
            for a, b in zip(parts, parts[1:]):
                builder.edge(
                    a,
                    b,
                    "section",
                    center=center,
                    sweep=step,
                    name=f"Arc {handle}",
                    handle=handle,
                    layer=layer,
                )
        elif kind == "CIRCLE":
            center = point(entity["center"], f"Circle {handle} center")
            parts, step = _arc_parts(
                center, length(entity["radius"], f"Circle {handle} radius"), 0.0, math.tau
            )
            for a, b in zip(parts, parts[1:]):
                builder.edge(
                    a,
                    b,
                    "section",
                    center=center,
                    sweep=step,
                    name=f"Circle {handle}",
                    handle=handle,
                    layer=layer,
                )
        elif kind == "LWPOLYLINE":
            vertices = entity.get("vertices", [])
            if not entity.get("closed") and vertices:
                pass  # an open polyline is a legitimate rigid profile candidate
            ordered = [
                point((v["x"], v["y"], 0.0), f"Polyline {handle} vertex")
                for v in vertices
            ]
            pairs = list(zip(ordered, ordered[1:]))
            if entity.get("closed") and ordered:
                pairs.append((ordered[-1], ordered[0]))
            for index, (first, second) in enumerate(pairs):
                bulge = vertices[index].get("bulge", 0.0)
                arc = _bulge_arc(first, second, bulge)
                if arc is None:
                    builder.edge(
                        first,
                        second,
                        "section",
                        name=f"Polyline {handle} segment {index + 1}",
                        handle=handle,
                        layer=layer,
                    )
                    continue
                center, radius, start, sweep = arc
                parts, step = _arc_parts(center, radius, start, sweep)
                origin = (center[0], center[1], 0.0)
                for a, b in zip(parts, parts[1:]):
                    builder.edge(
                        a,
                        b,
                        "section",
                        center=origin,
                        sweep=step,
                        name=f"Polyline {handle} arc {index + 1}",
                        handle=handle,
                        layer=layer,
                    )
        elif kind == "SPLINE":
            control = [
                point(value, f"Spline {handle} control point")
                for value in entity.get("controlPoints", [])
            ]
            fits = [
                point(value, f"Spline {handle} fit point")
                for value in entity.get("fitPoints", [])
            ]
            degree = int(entity.get("degree") or 3)
            if control:
                fits = []
                provenance = "control_points"
            elif fits:
                provenance = "fit_points"
            else:
                skipped.append({"handle": handle, "reason": "spline has no points"})
                continue
            if len(set(tuple(round(value, 9) for value in point) for point in (control or fits))) < 2:
                skipped.append({"handle": handle, "reason": "degenerate spline"})
                continue
            closed = bool(entity.get("closed")) or (
                len(fits) > 2 and math.dist(fits[0], fits[-1]) <= 1e-6
            )
            knots = [float(value) for value in entity.get("knots", [])]
            poles = control or fits
            if not knots and provenance == "control_points":
                if len(poles) < degree + 1:
                    degree = max(1, len(poles) - 1)
                counts_needed = len(poles) + degree + 1
                inner = counts_needed - 2 * (degree + 1)
                if inner < 0:
                    skipped.append(
                        {"handle": handle, "reason": "too few control points for its degree"}
                    )
                    continue
                knots = [0.0] * (degree + 1) + [
                    (index + 1) / (inner + 1) for index in range(inner)
                ] + [1.0] * (degree + 1)
            data = SplineData(
                degree=degree,
                control_points=control,
                fit_points=fits,
                knots=knots if provenance == "control_points" else [],
                weights=[float(value) for value in entity.get("weights", [])],
                tangents=[
                    point(entity[key], f"Spline {handle} tangent")
                    for key in ("startTangent", "endTangent")
                    if entity.get(key)
                ],
                closed=closed,
                periodic=bool(entity.get("periodic")),
            )
            builder.spline(
                data,
                "section",
                name=f"Spline {handle}",
                handle=handle,
                layer=layer,
            )
            spline_provenance[provenance] += 1
        elif kind == "POINT":
            skipped.append({"handle": handle, "reason": "reference point, not section geometry"})
        elif kind == "INSERT":
            if any(
                other.get("instance", "").startswith(handle + "/")
                for other in inventory.get("entities", [])
            ):
                continue  # block geometry is already expanded by the reader
            skipped.append({"handle": handle, "reason": "block instance with no expanded geometry"})
        else:
            skipped.append({"handle": handle, "reason": f"unsupported entity {kind}"})
        counts[kind] += 1

    if not builder.edges:
        raise ValueError(
            "The drawing contains no supported planar curve. Entity counts: "
            + (", ".join(f"{key} {value}" for key, value in sorted(counts.items())) or "none")
        )
    source_model = units_policy.record(
        unit,
        Source(
            kind="dwg",
            filename=source.get("path") or Path(name).name,
            digest=digest or source.get("sha256", ""),
        ),
    )
    project, report = assemble(builder, name, source_model, allow_open_profiles=True)
    report.update(
        {
            "reader": inventory.get("reader", {}),
            "sourceSha256": source.get("sha256", digest),
            "sourceVersion": source.get("version", ""),
            "units": unit.note,
            "unitBasis": unit.basis,
            "unitDeclaration": unit.declaration,
            "unitFactor": unit.factor,
            "unitProvenance": unit.provenance,
            "entityCounts": dict(sorted(counts.items())),
            "skipped": skipped,
            "unknownEntities": inventory.get("unknown", {}),
            "splineProvenance": dict(sorted(spline_provenance.items())),
            "warnings": warnings,
        }
    )
    return project, report
