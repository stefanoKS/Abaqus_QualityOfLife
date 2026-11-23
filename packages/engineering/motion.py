"""Prescribed rigid-panel motion: one direction convention for every consumer.

The convention is global model XY: +X is 0 deg, +Y is 90 deg and positive angles
are counterclockwise. A setup stores a nonnegative stroke in mm and an angle in
degrees; the delta is ``(L cos t, L sin t)``. Numerical residues on axis-aligned
directions are canonicalized to exact zero so a 90-degree move writes ``0.`` in
the deck rather than ``6.12e-16``.

Version-3 revisions keep their signed Y travel: down is -90 deg, up is +90 deg
and the magnitude is the absolute travel. Nothing here rewrites a stored
revision; callers use :func:`resolve` to obtain the effective prescribed motion.
"""

import math

AXIS_TOLERANCE = 1e-12


def canonical_angle(angle):
    """Validate a finite angle and return it with axis residues canonicalized."""
    value = float(angle)
    if not math.isfinite(value):
        raise ValueError("The motion angle must be a finite number of degrees.")
    if abs(value) > 360:
        raise ValueError("The motion angle must be between -360 and 360 degrees.")
    residue = value % 90.0
    if min(residue, 90.0 - residue) < 1e-9:
        return round(value / 90.0) * 90.0
    return value


def unit_vector(angle):
    """The validated in-plane direction ``(cos t, sin t)`` with exact axes."""
    theta = canonical_angle(angle)
    x = round(math.cos(math.radians(theta)), 15)
    y = round(math.sin(math.radians(theta)), 15)
    if abs(x) < AXIS_TOLERANCE:
        x = 0.0
    if abs(y) < AXIS_TOLERANCE:
        y = 0.0
    return [x, y]


def delta(stroke, angle):
    """Translation vector in mm for a nonnegative stroke and direction angle."""
    length = float(stroke)
    if not math.isfinite(length) or length < 0:
        raise ValueError("The motion stroke must be a nonnegative finite distance in mm.")
    ux, uy = unit_vector(angle)
    dx, dy = ux * length, uy * length
    if abs(dx) < AXIS_TOLERANCE:
        dx = 0.0
    if abs(dy) < AXIS_TOLERANCE:
        dy = 0.0
    return [dx, dy]


def angle_of(direction):
    """The canonical angle in degrees for a nonzero direction vector."""
    dx, dy = float(direction[0]), float(direction[1])
    magnitude = math.hypot(dx, dy)
    if not math.isfinite(magnitude) or magnitude <= 1e-12:
        raise ValueError("A motion direction must be a nonzero finite vector.")
    return canonical_angle(math.degrees(math.atan2(dy, dx)))


def legacy_angle(travel):
    """Lossless angle for a legacy signed Y travel (down -90, up +90, zero -90)."""
    value = float(travel)
    if value < 0:
        return -90.0
    if value > 0:
        return 90.0
    return -90.0


def resolve(motion, schema_version, body=False):
    """Effective prescribed motion for one role.

    Returns ``angle``, ``stroke``, ``delta``, ``duration``, ``offset`` and
    ``legacy``. Version-3 revisions derive these from their signed Y travel; the
    stored revision is never modified.
    """
    duration = float(motion.duration)
    offset = float(motion.offset)
    if schema_version >= 4:
        angle = canonical_angle(motion.angle)
        stroke = float(motion.stroke)
        return {
            "angle": angle,
            "stroke": stroke,
            "delta": delta(stroke, angle),
            "duration": duration,
            "offset": offset,
            "legacy": False,
            "body": body,
        }
    travel = float(motion.travel)
    return {
        "angle": legacy_angle(travel),
        "stroke": abs(travel),
        "delta": [0.0, travel],
        "duration": duration,
        "offset": offset,
        "legacy": True,
        "body": body,
    }


def project_motion(project):
    """Both roles' effective motion for a project-like object."""
    return {
        "door": resolve(project.motion, project.schema_version, body=False),
        "body": resolve(project.motion.body, project.schema_version, body=True),
    }


def project_vector(direction, values):
    """Dot product of a direction with the four signed history components."""
    ux, uy = float(direction[0]), float(direction[1])
    return (
        float(values.get("U1", 0.0)) * ux
        + float(values.get("U2", 0.0)) * uy,
        float(values.get("RF1", 0.0)) * ux
        + float(values.get("RF2", 0.0)) * uy,
    )
