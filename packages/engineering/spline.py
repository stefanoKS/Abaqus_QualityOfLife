"""Spline evaluation that never depends on the mesher.

The canonical spline data in the project model is the source of truth. Display
tessellation, mesh approximation and geometry validation all evaluate the same
curve here, so a screen chord can never be mistaken for the boundary.
"""

import math

from ezdxf.math import BSpline, Vec3, fit_points_to_cad_cv

DEFAULT_TOLERANCE = 0.02  # mm; 2 % of the smallest 1 mm wall in the drawing set
MAX_POINTS = 4096


class SplineError(ValueError):
    pass


def _vec(point):
    return Vec3(float(point[0]), float(point[1]), float(point[2] if len(point) > 2 else 0))


def curve(data):
    """Build the ezdxf B-spline described by canonical ``SplineData``."""
    control = [_vec(p) for p in data.control_points]
    fits = [_vec(p) for p in data.fit_points]
    tangents = [_vec(t) for t in data.tangents]
    try:
        if control:
            spline = BSpline(
                control,
                order=data.degree + 1,
                knots=list(data.knots) or None,
                weights=list(data.weights) or None,
            )
        elif fits:
            # Documented AutoCAD-compatible reconstruction for fit points: a cubic
            # interpolation through the points honouring the supplied tangents.
            spline = fit_points_to_cad_cv(fits, tangents or None)
        else:
            raise SplineError("Spline has neither control points nor fit points.")
    except SplineError:
        raise
    except Exception as exc:  # ezdxf raises assorted ValueError/TypeError
        raise SplineError(f"Invalid spline data: {exc}") from exc
    if spline.count < 2 or not spline.degree:
        raise SplineError("Spline has too few control points.")
    return spline


def endpoint_points(data):
    spline = curve(data)
    return tuple(spline.point(0.0)), tuple(spline.point(spline.max_t))


def evaluate(data, fraction):
    spline = curve(data)
    return tuple(spline.point(spline.max_t * min(1.0, max(0.0, float(fraction)))))


def tessellate(data, tolerance=None):
    """Adaptive polyline whose chord deviation is within ``tolerance`` (mm).

    Independent of any mesh so display and meshing cannot share a coarse chord.
    """
    spline = curve(data)
    tol = float(tolerance if tolerance is not None else getattr(data, "tolerance", DEFAULT_TOLERANCE))
    if not math.isfinite(tol) or tol <= 0:
        raise SplineError("Spline tolerance must be a positive length in millimetres.")
    max_t = spline.max_t
    points = [spline.point(0.0)]

    def refine(t0, p0, t1, p1, depth):
        tm = (t0 + t1) / 2
        pm = spline.point(tm)
        chord = ((p0.x + p1.x) / 2, (p0.y + p1.y) / 2, (p0.z + p1.z) / 2)
        deviation = math.dist(tuple(pm), chord)
        if deviation <= tol or depth <= 0:
            points.append(tuple(p1))
            return
        refine(t0, p0, tm, pm, depth - 1)
        refine(tm, pm, t1, p1, depth - 1)

    refine(0.0, points[0], max_t, spline.point(max_t), int(12))
    if len(points) > MAX_POINTS:
        raise SplineError(
            f"Spline needs more than {MAX_POINTS} display points at {tol} mm. "
            "Check the curve for a fold or a degenerate knot span."
        )
    return points


def occ_descriptor(data):
    """Exact OpenCASCADE B-spline descriptor, or ``None`` to approximate.

    Exact construction needs a clamped, non-periodic B-spline with consistent
    knots, positive weights and distinct endpoints, which is what the drawing
    converter emits.
    """
    if getattr(data, "periodic", False) or getattr(data, "closed", False):
        return None
    spline = curve(data)
    poles = [tuple(p) for p in spline.control_points]
    degree = spline.degree
    knots = list(spline.knots())
    weights = list(spline.weights())
    if len(knots) != len(poles) + degree + 1 or len(poles) < degree + 1:
        return None
    if weights and (len(weights) != len(poles) or any(w <= 0 for w in weights)):
        return None
    distinct, multiplicities = [], []
    for value in knots:
        if distinct and abs(value - distinct[-1]) <= 1e-12:
            multiplicities[-1] += 1
        else:
            distinct.append(value)
            multiplicities.append(1)
    if len(distinct) < 2:
        return None
    if math.dist(poles[0], poles[-1]) <= 1e-9:
        return None
    return {
        "poles": poles,
        "degree": degree,
        "knots": distinct,
        "multiplicities": multiplicities,
        "weights": weights,
    }


def _segment_distance(point, a, b):
    ax, ay, az = a
    bx, by, bz = b
    px, py, pz = point
    dx, dy, dz = bx - ax, by - ay, bz - az
    length = dx * dx + dy * dy + dz * dz
    if length <= 1e-18:
        return math.dist(point, a)
    t = ((px - ax) * dx + (py - ay) * dy + (pz - az) * dz) / length
    t = min(1.0, max(0.0, t))
    return math.dist(point, (ax + t * dx, ay + t * dy, az + t * dz))


def deviation(data, polyline, samples=257):
    """Largest distance from the true curve to a candidate polyline (mm).

    Independent of the tessellation tolerance, so tests can prove the promise
    rather than restate it.
    """
    spline = curve(data)
    max_t = spline.max_t
    polyline = [tuple(p) for p in polyline]
    if len(polyline) < 2:
        return math.inf
    worst = 0.0
    for index in range(samples):
        point = tuple(spline.point(max_t * index / (samples - 1)))
        best = min(
            _segment_distance(point, polyline[i], polyline[i + 1])
            for i in range(len(polyline) - 1)
        )
        worst = max(worst, best)
    return worst
