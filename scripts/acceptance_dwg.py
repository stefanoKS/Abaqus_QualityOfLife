"""Private acceptance harness for the native DWG path.

Two modes, both through the normal services (API contract -> durable worker):

    python scripts/acceptance_dwg.py
        Native read, import, mesh, fixture and deck. Consumes zero solver tokens.

    python scripts/acceptance_dwg.py --licensed
        Additionally submits the ABAQUS run and the ODB extraction.

The drawing and every generated artifact stay in a local evidence directory; the
drawing itself is never copied into the repository.
"""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fastapi.testclient import TestClient  # noqa: E402

from services import store  # noqa: E402
from services.api.main import app  # noqa: E402
from services.worker.__main__ import once  # noqa: E402

DRAWING = ROOT / "examples" / "hollow-section_2.dwg"
EXPECTED_SHA256 = "8592c3c2aa59530e7b937d58f6354f6beeb24b6bc56cfcb6d37945e483aac771"


PROBLEMS = []


def fail(message):
    """Record a release-blocking discrepancy; the harness exits non-zero."""
    PROBLEMS.append(message)
    print("CHECK FAILED : " + message)



def wsfix_matches(written, expected):
    """Exact set equality between the deck's WSFIX and the saved selection."""
    return sorted(int(value) for value in written) == sorted(int(value) for value in expected)


def travel_attained(history, prescribed, relative=0.01, absolute=0.01):
    if not history:
        return False, 0.0
    travel = abs(float(history[-1]["u2"]))
    required = abs(float(prescribed))
    return abs(travel - required) <= max(absolute, required * relative), travel


def first_contact(history):
    """Signed RF2 magnitude above numerical noise, or None."""
    for row in history:
        if abs(float(row["rf2"])) > 1e-9:
            return row
    return None


def csv_agrees(rows, history, tolerance=1e-9):
    """Last CSV row must equal the last extracted sample for the shared columns."""
    if not rows or not history:
        return False
    final, sample = rows[-1], history[-1]
    pairs = [
        (float(final["panel_U2_mm"]), float(sample["u2"])),
        (float(final["panel_RF2_N"]), float(sample["rf2"])),
    ]
    return all(abs(a - b) <= tolerance for a, b in pairs)


def frame_fixed_error(frames, labels, instance="WS-1", tolerance=1e-9):
    """Worst |U| of the fixed nodes across frames, or None if a label is absent."""
    worst = 0.0
    for payload in frames:
        rows = payload.get("displacements", {}).get(instance, [])
        mapping = {int(row[0]): row[1:] for row in rows}
        if labels - set(mapping):
            return None
        for label in labels:
            worst = max(worst, max(abs(float(value)) for value in mapping[label]))
    return worst


def run_worker(owner):
    processed = 0
    while once(owner):
        processed += 1
        if processed > 12:
            raise SystemExit("worker kept claiming jobs; inspect the queue")
    return processed


def parse_rigid_parts(text):
    """Part name -> node coordinates, R2D2 connectivity and SPOS surface names."""
    parts, part, mode = {}, None, None
    for line in text.splitlines():
        if line.startswith("*Part, name="):
            part = line.split("name=", 1)[1].strip()
            parts[part] = {"nodes": {}, "elements": [], "surfaces": []}
        elif line.startswith("*End Part"):
            part, mode = None, None
        elif line.startswith("*Surface, type=ELEMENT"):
            if part:
                parts[part]["surfaces"].append(line.split("name=", 1)[1].strip())
        elif line.startswith("*Node"):
            mode = "nodes"
        elif line.startswith("*Element, type=R2D2"):
            mode = "elements"
        elif line.startswith("*"):
            mode = None
        elif part and mode == "nodes":
            label, x, y = line.split(",")[:3]
            parts[part]["nodes"][int(label)] = (float(x), float(y))
        elif part and mode == "elements":
            label, first, second = (int(value) for value in line.split(",")[:3])
            parts[part]["elements"].append((label, first, second))
    return parts


def parse_nset(text, name):
    import re

    block = re.search(r"\*Nset, nset=" + re.escape(name) + r"[^\n]*\n(.*?)(?=\n\*|\Z)", text, re.S | re.I)
    if not block:
        return None
    return sorted(int(value) for value in re.findall(r"\d+", block.group(1)))


def _cross(ax, ay, bx, by):
    return ax * by - ay * bx


def _unit(dx, dy):
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 1e-12:
        return None
    return [dx / length, dy / length]


def _closest_on_segment(px, py, first, second):
    ex, ey = second[0] - first[0], second[1] - first[1]
    scale = ex * ex + ey * ey
    if scale <= 1e-24:
        return first[0], first[1]
    t = max(0.0, min(1.0, ((px - first[0]) * ex + (py - first[1]) * ey) / scale))
    return first[0] + t * ex, first[1] + t * ey


def _closest_between(a, b, c, d):
    best = None
    for px, py, other in ((a[0], a[1], (c, d)), (b[0], b[1], (c, d)), (c[0], c[1], (a, b)), (d[0], d[1], (a, b))):
        qx, qy = _closest_on_segment(px, py, other[0], other[1])
        distance = ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5
        if best is None or distance < best[0]:
            best = (distance, [px, py], [qx, qy])
    return best


def _segment_toi(a, b, delta, c, d):
    """Earliest t in [0, 1] where (a,b)+t*delta meets (c,d). Independent math."""
    e1x, e1y = b[0] - a[0], b[1] - a[1]
    e2x, e2y = d[0] - c[0], d[1] - c[1]
    len1, len2 = (e1x * e1x + e1y * e1y) ** 0.5, (e2x * e2x + e2y * e2y) ** 0.5
    if len1 <= 1e-12 or len2 <= 1e-12:
        return None
    wx, wy = c[0] - a[0], c[1] - a[1]
    den = _cross(e1x, e1y, e2x, e2y)
    if abs(den) > 1e-12 * max(1.0, len1 * len2):
        s0 = _cross(wx, wy, e2x, e2y)
        s1 = -_cross(delta[0], delta[1], e2x, e2y)
        u0 = _cross(wx, wy, e1x, e1y)
        u1 = -_cross(delta[0], delta[1], e1x, e1y)
        low, high = 0.0, 1.0
        low_value, high_value = (0.0, den) if den > 0 else (den, 0.0)
        for c0, c1 in ((s0, s1), (u0, u1)):
            if abs(c1) <= 1e-12 * max(1.0, abs(c0), abs(low_value), abs(high_value)):
                if not (low_value - 1e-9 <= c0 <= high_value + 1e-9):
                    return None
                continue
            first_t = (low_value - c0) / c1
            last_t = (high_value - c0) / c1
            if c1 < 0:
                first_t, last_t = last_t, first_t
            low = max(low, min(first_t, last_t))
            high = min(high, max(first_t, last_t))
        if high < low - 1e-9:
            return None
        t = max(0.0, low)
        if t > 1.0 + 1e-9:
            return None
        t = min(1.0, t)
        scale = e2x * e2x + e2y * e2y
        mx, my = a[0] + t * delta[0], a[1] + t * delta[1]
        u = max(0.0, min(1.0, ((mx - c[0]) * e2x + (my - c[1]) * e2y) / scale))
        return t, (mx, my), (c[0] + u * e2x, c[1] + u * e2y)
    de = _cross(delta[0], delta[1], e2x, e2y)
    if abs(de) <= 1e-12 * max(1.0, (delta[0] ** 2 + delta[1] ** 2) ** 0.5 * len2):
        if abs(_cross(wx, wy, e2x, e2y)) > 1e-7 * len2:
            return None
        t = 0.0
    else:
        t = _cross(wx, wy, e2x, e2y) / de
        if t < -1e-9 or t > 1.0 + 1e-9:
            return None
        t = max(0.0, min(1.0, t))
    ax_t = a[0] + t * delta[0] - c[0]
    ay_t = a[1] + t * delta[1] - c[1]
    bx_t = b[0] + t * delta[0] - c[0]
    by_t = b[1] + t * delta[1] - c[1]
    scale = e2x * e2x + e2y * e2y
    ua = (ax_t * e2x + ay_t * e2y) / scale
    ub = (bx_t * e2x + by_t * e2y) / scale
    low, high = min(ua, ub), max(ua, ub)
    if high < -1e-9 or low > 1.0 + 1e-9:
        return None
    u = max(0.0, min(1.0, low))
    span = ub - ua
    s = 0.0 if abs(span) <= 1e-15 else max(0.0, min(1.0, (u - ua) / span))
    mx = a[0] + s * e1x + t * delta[0]
    my = a[1] + s * e1y + t * delta[1]
    return t, (mx, my), (c[0] + u * e2x, c[1] + u * e2y)


def _instance_translation(text, name):
    """Read the PANEL-1/BODY-1 instance translation emitted in the INP."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(f"*Instance, name={name},"):
            for candidate in lines[index + 1 : index + 4]:
                values = candidate.split(",")
                if len(values) >= 3:
                    try:
                        return [float(values[0]), float(values[1]), float(values[2])]
                    except ValueError:
                        continue
            return [0.0, 0.0, 0.0]
    return [0.0, 0.0, 0.0]


def _motion_delta(motion, schema_version):
    """Prescribed translation for the acceptance sweep (same convention as the deck)."""
    import math

    if schema_version >= 4:
        stroke = float(motion.get("stroke", 0.0))
        angle = float(motion.get("angle", -90.0))
        dx = stroke * math.cos(math.radians(angle))
        dy = stroke * math.sin(math.radians(angle))
        if abs(dx) < 1e-12:
            dx = 0.0
        if abs(dy) < 1e-12:
            dy = 0.0
        return [dx, dy]
    return [0.0, float(motion.get("travel", 0.0))]


def _segment_normal(c, d):
    return _unit(-(d[1] - c[1]), d[0] - c[0])


def _point_on_boundary(x, y, seal_pairs):
    for first, second in seal_pairs:
        qx, qy = _closest_on_segment(x, y, first, second)
        if ((x - qx) ** 2 + (y - qy) ** 2) ** 0.5 <= 1e-7:
            return True
    return False


def _inside_material(points, seal_pairs):
    for x, y in points:
        if _point_on_boundary(x, y, seal_pairs):
            continue
        inside = False
        for first, second in seal_pairs:
            if (first[1] > y) != (second[1] > y):
                crossing = first[0] + (y - first[1]) * (second[0] - first[0]) / (second[1] - first[1])
                if crossing > x:
                    inside = not inside
        if inside:
            return True
    return False


def _surface_approach(a, b, delta, c, d, seal_pairs, hit_point=None):
    """Direction from the element to the hit seal segment, using its tangent normal.

    A material probe on either side of the hit point selects the outward side.
    This stays stable for a corner or endpoint-only hit where the nearest-point
    vector is tangential.
    """
    normal = _segment_normal(c, d)
    if normal is None:
        return None
    mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    if hit_point is None:
        hit_point = _closest_on_segment(mid[0], mid[1], c, d)
    hx, hy = hit_point
    ex, ey = d[0] - c[0], d[1] - c[1]
    seal_length = (ex * ex + ey * ey) ** 0.5
    step = min(1e-3, max(1e-7, 1e-4 * max(seal_length, 1.0)))
    if seal_length > 1e-12:
        parameter = ((hx - c[0]) * ex + (hy - c[1]) * ey) / (seal_length * seal_length)
        margin = min(0.49, step / seal_length)
        parameter = min(1.0 - margin, max(margin, parameter))
        hx, hy = c[0] + parameter * ex, c[1] + parameter * ey
    inside_plus = _inside_material([(hx + normal[0] * step, hy + normal[1] * step)], seal_pairs)
    inside_minus = _inside_material([(hx - normal[0] * step, hy - normal[1] * step)], seal_pairs)
    if inside_plus and not inside_minus:
        return normal
    if inside_minus and not inside_plus:
        return [-normal[0], -normal[1]]
    direction = _unit(hx - mid[0], hy - mid[1])
    if direction is not None:
        return direction
    along = delta[0] * normal[0] + delta[1] * normal[1]
    if abs(along) <= 1e-12:
        return None
    return normal if along > 0 else [-normal[0], -normal[1]]


def _initial_approach(a, b, delta, c, d, seal_pairs):
    """Approach from an element already touching the hit seal segment at t = 0."""
    mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
    qx, qy = _closest_on_segment(mid[0], mid[1], c, d)
    return _surface_approach(a, b, delta, c, d, seal_pairs, (qx, qy))


def _select_dominant_hits(pairs, delta):
    """Keep the tied hits on the contact face most aligned with the motion.

    ``pairs`` is ``[(seal_index, direction), ...]``. At a flat-face tie the
    end/corner segments are also touched at the same instant; their tangent
    normals are nearly perpendicular and must not average into the face normal.
    """
    length = (delta[0] * delta[0] + delta[1] * delta[1]) ** 0.5
    if length <= 1e-12:
        return []
    ux, uy = delta[0] / length, delta[1] / length
    scored = []
    for seal_index, direction in pairs:
        if direction is None:
            continue
        alignment = abs(direction[0] * ux + direction[1] * uy)
        scored.append((alignment, seal_index, direction))
    if not scored:
        return []
    best = max(item[0] for item in scored)
    if best <= 1e-9:
        selected = [(seal_index, direction) for _alignment, seal_index, direction in scored]
    else:
        selected = [
            (seal_index, direction)
            for alignment, seal_index, direction in scored
            if alignment >= best - 1e-3
        ]
    for index, (_seal_index, first) in enumerate(selected):
        for _other_index, second in selected[index + 1 :]:
            if first[0] * second[0] + first[1] * second[1] < -1e-6:
                return []
    return selected


def _first_contact_hits(profile, delta, seal_pairs):
    """Earliest exact hit set, with initial-into preferred over a later surface."""
    hits = []
    for index, (a, b) in enumerate(profile):
        for seal_index, (c, d) in enumerate(seal_pairs):
            contact = _segment_toi(a, b, delta, c, d)
            if contact is not None:
                hits.append((index, seal_index, contact[0], contact[2]))
    if not hits:
        return None, []
    initial = [hit for hit in hits if hit[2] <= 1e-9]
    later = [hit for hit in hits if hit[2] > 1e-9]
    initial_into = []
    for index, seal_index, fraction, _hit_point in initial:
        c, d = seal_pairs[seal_index]
        approach = _initial_approach(*profile[index], delta, c, d, seal_pairs)
        if approach is not None and (
            delta[0] * approach[0] + delta[1] * approach[1] > 1e-12
        ):
            initial_into.append((index, seal_index, fraction, _hit_point))
    candidates = initial_into or later
    if not candidates:
        return None, []
    fraction = min(hit[2] for hit in candidates)
    return fraction, [
        hit for hit in candidates if hit[2] <= fraction + 1e-6
    ]


def rigid_spos_checks(parts, seal_segments, tolerance=1e-6, instance_translations=None, deltas=None):
    """Local first-contact SPOS orientation for every rigid part.

    The check is independent of the writer's decision: it applies the emitted
    PANEL-1/BODY-1 instance translation, solves the earliest translating-segment
    intersection with the seal (parallel, non-parallel and endpoint hits), and
    compares each emitted normal with the direction to the hit witness at contact
    time. It does not reuse the writer's nearest-point scoring.
    """
    from math import hypot

    instance_translations = instance_translations or {}
    deltas = deltas or {}
    seal_pairs = [((s[0], s[1]), (s[2], s[3])) for s in seal_segments]
    rows = []
    for name, part in parts.items():
        translation = instance_translations.get(name, [0.0, 0.0, 0.0])
        delta = deltas.get(name)
        profile = []
        normals = []
        midpoints = []
        for element, first, second in part["elements"]:
            a = part["nodes"][first]
            b = part["nodes"][second]
            a = (a[0] + translation[0], a[1] + translation[1])
            b = (b[0] + translation[0], b[1] + translation[1])
            profile.append((a, b))
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = hypot(dx, dy)
            normals.append((-dy / length, dx / length))
            midpoints.append(((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0))
        if not profile:
            continue

        def distance_to_seal(mid):
            best = None
            for pair in seal_pairs:
                qx, qy = _closest_on_segment(mid[0], mid[1], pair[0], pair[1])
                distance = hypot(mid[0] - qx, mid[1] - qy)
                if best is None or distance < best:
                    best = distance
            return best if best is not None else float("inf")

        distances = [distance_to_seal(mid) for mid in midpoints]
        closest = min(distances)
        if delta is None or hypot(delta[0], delta[1]) <= 1e-12:
            # Historical nearest-surface diagnostic for a static call.
            near = [index for index, distance in enumerate(distances) if distance <= closest + max(0.5, closest * 0.02)]
            dots = []
            for index in near:
                mid = midpoints[index]
                on_seal = min(
                    (
                        _closest_on_segment(mid[0], mid[1], pair[0], pair[1])
                        for pair in seal_pairs
                    ),
                    key=lambda point: (point[0] - mid[0]) ** 2 + (point[1] - mid[1]) ** 2,
                )
                direction = _unit(on_seal[0] - mid[0], on_seal[1] - mid[1])
                dots.append(0.0 if direction is None else normals[index][0] * direction[0] + normals[index][1] * direction[1])
            rows.append(
                {
                    "part": name,
                    "elements": len(profile),
                    "closest_mm": closest,
                    "near": len(near),
                    "min_dot": min(dots) if dots else 0.0,
                    "sum_dot": sum(dots),
                    "first_contact_fraction": None,
                    "target_segments": [],
                }
            )
            continue
        fraction, first = _first_contact_hits(profile, delta, seal_pairs)
        if fraction is None:
            rows.append(
                {
                    "part": name,
                    "elements": len(profile),
                    "closest_mm": closest,
                    "near": 0,
                    "min_dot": 0.0,
                    "sum_dot": 0.0,
                    "first_contact_fraction": None,
                    "target_segments": [],
                }
            )
            continue
        first_elements = []
        for index, _seal_index, _fraction, _hit_point in first:
            if index not in first_elements:
                first_elements.append(index)
        dots = []
        target_segments = []
        for index in first_elements:
            a, b = profile[index]
            candidates = [hit for hit in first if hit[0] == index]
            candidate_directions = []
            for _index, seal_index, hit_fraction, hit_point in candidates:
                c, d = seal_pairs[seal_index]
                if hit_fraction > 1e-9:
                    backoff = min(1e-6, hit_fraction / 2.0)
                    t_before = hit_fraction - backoff
                    moved = (
                        (a[0] + delta[0] * t_before, a[1] + delta[1] * t_before),
                        (b[0] + delta[0] * t_before, b[1] + delta[1] * t_before),
                    )
                    direction = _surface_approach(
                        moved[0], moved[1], delta, c, d, seal_pairs, hit_point
                    )
                else:
                    direction = _initial_approach(a, b, delta, c, d, seal_pairs)
                if direction is not None:
                    candidate_directions.append((seal_index, direction))
            selected = _select_dominant_hits(candidate_directions, delta)
            directions = [direction for _seal_index, direction in selected]
            for seal_index, _direction in selected:
                if tuple(seal_segments[seal_index]) not in target_segments:
                    target_segments.append(tuple(seal_segments[seal_index]))
            combined = (
                _unit(
                    sum(direction[0] for direction in directions),
                    sum(direction[1] for direction in directions),
                )
                if directions
                else None
            )
            if combined is not None:
                dots.append(normals[index][0] * combined[0] + normals[index][1] * combined[1])
        rows.append(
            {
                "part": name,
                "elements": len(profile),
                "closest_mm": closest,
                "near": len(first_elements),
                "min_dot": min(dots) if dots else 0.0,
                "sum_dot": sum(dots),
                "first_contact_fraction": fraction,
                "target_segments": target_segments,
            }
        )
    return rows



def seal_boundary_segments(nodes, continuum):
    """Exterior seal sides in the assembled mesh coordinate system."""
    from collections import defaultdict

    sides = defaultdict(list)
    for element in continuum:
        connectivity = element["nodes"]
        for index, node in enumerate(connectivity):
            side = tuple(sorted((node, connectivity[(index + 1) % len(connectivity)])))
            sides[side].append((element["id"], index + 1))
    segments = []
    for side, entries in sides.items():
        if len(entries) != 1:
            continue
        a, b = nodes[side[0]], nodes[side[1]]
        x0, y0, x1, y1 = float(a[0]), float(a[1]), float(b[0]), float(b[1])
        if x0 > x1:
            x0, y0, x1, y1 = x1, y1, x0, y0
        segments.append((x0, y0, x1, y1))
    return segments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drawing", type=Path, default=DRAWING)
    parser.add_argument("--evidence", type=Path, default=ROOT / ".local" / "dwg-acceptance")
    parser.add_argument("--licensed", action="store_true", help="also submit a real Abaqus run")
    # A signed Y travel keeps the historical door-only invocation working; the
    # two-panel case uses explicit stroke/angle so the body seats upward and the
    # door closes downward (the operator's 10 mm settings).
    parser.add_argument("--travel", type=float, default=None)
    parser.add_argument("--door-stroke", type=float, default=10.0)
    parser.add_argument("--door-angle", type=float, default=-90.0)
    parser.add_argument("--body-stroke", type=float, default=10.0)
    parser.add_argument("--body-angle", type=float, default=90.0)
    parser.add_argument("--door-duration", type=float, default=1.0)
    parser.add_argument("--body-duration", type=float, default=1.0)
    parser.add_argument(
        "--fixture-tolerance",
        type=float,
        default=0.5,
        help="mm band above the lowest seal boundary selected as the mounting foot",
    )
    options = parser.parse_args()
    if options.travel is not None:
        options.door_stroke = abs(options.travel)
        options.door_angle = -90.0 if options.travel <= 0 else 90.0

    if not options.drawing.is_file():
        raise SystemExit(f"Drawing not found: {options.drawing}")
    from hashlib import sha256

    digest = sha256(options.drawing.read_bytes()).hexdigest()
    print(f"drawing      : {options.drawing}")
    print(f"sha256       : {digest}")
    if digest != EXPECTED_SHA256:
        print("note         : this is a different drawing revision than the reviewed one")
    data = options.evidence / "data"
    data.mkdir(parents=True, exist_ok=True)
    import os

    os.environ["SEAL_DATA"] = str(data)
    if options.licensed:
        # One resolver shared with the API and worker: explicit override first,
        # then the supported launcher discovered on Path or in SIMULIA/Commands.
        from integrations.abaqus import launcher as abaqus_launcher

        try:
            found = abaqus_launcher.resolve_launcher()
        except ValueError as error:
            raise SystemExit(str(error))
        print(f"launcher     : {found['path']} ({found['source']})")

    with TestClient(app, base_url="http://127.0.0.1") as api:
        project = api.post("/api/projects", json={"name": "DWG acceptance"}).raise_for_status().json()
        upload = api.post(
            "/api/projects/" + project["project"] + "/drawing",
            data={"base": project["id"], "units": "N-mm-s-tonne"},
            files={"file": (options.drawing.name, options.drawing.read_bytes())},
        )
        assert upload.is_success, upload.text
        run_worker("acceptance")
        imported = api.get("/api/jobs/" + upload.json()["id"] + "/imported")
        assert imported.is_success, imported.text
        revision = imported.json()
        setup = revision["setup"]
        print(f"revision     : {revision['id']}")
        print(f"components   : {[(c['id'], c['role']) for c in setup['components']]}")
        print(f"faces        : {[(f['name'], f['cavity']) for f in setup['faces']]}")

        seal = [f["component"] for f in setup["faces"] if not f["cavity"]]
        if len(seal) != 1:
            raise SystemExit("expected exactly one filled weatherstrip region")
        panels = sorted({e["component"] for e in setup["edges"]} - set(seal))
        if len(panels) != 2:
            raise SystemExit("expected a door and a body open profile")
        # The door is the open profile above the bulb: it closes onto the seal.
        # The body profile sits behind and below it and is reviewed but excluded.
        heights = {
            component: sum(point[1] for edge in setup["edges"] if edge["component"] == component
                           for point in ()) for component in panels
        }
        del heights
        centroid = {}
        for component in panels:
            points = [
                edge for edge in setup["edges"] if edge["component"] == component
            ]
            vertices = {v["id"]: v["xyz"] for v in setup["vertices"]}
            ys = [vertices[edge["start"]][1] for edge in points] + [
                vertices[edge["end"]][1] for edge in points
            ]
            centroid[component] = sum(ys) / len(ys)
        door = max(panels, key=lambda component: centroid[component])
        body = [component for component in panels if component != door][0]
        print(f"door profile : {door} (mean y {centroid[door]:.3f})")
        print(f"body profile : {body} (mean y {centroid[body]:.3f})")
        for component in setup["components"]:
            if component["id"] == seal[0]:
                component["role"] = "seal"
            elif component["id"] == door:
                component["role"] = "moving_panel"
            elif component["id"] == body:
                component["role"] = "vehicle_body"
        for face in setup["faces"]:
            face["material"] = "bulb_foam" if not face["cavity"] else None
        # Version-4 motion: nonnegative stroke and an in-plane angle. The body
        # seats upward (+90 deg) and the door closes downward (-90 deg).
        setup["motion"]["stroke"] = options.door_stroke
        setup["motion"]["angle"] = options.door_angle
        setup["motion"]["duration"] = options.door_duration
        setup["motion"]["body"]["stroke"] = options.body_stroke
        setup["motion"]["body"]["angle"] = options.body_angle
        setup["motion"]["body"]["duration"] = options.body_duration
        saved = api.put(
            "/api/projects/" + revision["project"],
            json={"setup": setup, "base": revision["id"]},
        )
        assert saved.is_success, saved.text
        saved = saved.json()
        print(f"mode         : {saved['setup']['analysis']['mode']}")
        print(
            "door motion  : "
            f"{saved['setup']['motion']['stroke']} mm at "
            f"{saved['setup']['motion']['angle']} deg"
        )
        print(
            "body motion  : "
            f"{saved['setup']['motion']['body']['stroke']} mm at "
            f"{saved['setup']['motion']['body']['angle']} deg"
        )

        mesh_job = api.post("/api/meshes", json={"revision": saved["id"], "token": store.new_id()})
        assert mesh_job.is_success, mesh_job.text
        run_worker("acceptance")
        mesh = store.job(mesh_job.json()["id"])
        assert mesh["status"] == "Completed", mesh["diagnostic"]
        print(f"mesh job     : {mesh['id']}")
        print(f"mesh digest  : {mesh['mesh_digest']}")
        print(f"mesh compat  : {mesh['mesh_compat']}")
        mesh_json = json.loads((store.job_dir(mesh["id"]) / "mesh.json").read_text(encoding="utf-8"))
        print(f"elements     : {mesh_json['counts']}")
        print(f"excluded     : {mesh_json.get('excluded')}")

        # The mounting foot is a band of the lowest weatherstrip boundary, not a
        # single node: one free node leaves the seal free to translate.
        coords = {node["id"]: node["xyz"] for node in mesh_json["nodes"]}
        seal_edges = {
            edge["id"] for edge in saved["setup"]["edges"] if edge["component"] == seal[0]
        }
        candidates = sorted(
            {
                node
                for edge_id, nodes in mesh_json["edge_nodes"].items()
                if edge_id in seal_edges
                for node in nodes
            }
        )
        if not candidates:
            raise SystemExit("the seal has no meshed mounting boundary")
        lowest = min(coords[node][1] for node in candidates)
        labels = [
            f"WS-1:{node}"
            for node in candidates
            if coords[node][1] <= lowest + options.fixture_tolerance
        ]
        print(f"fixture      : {len(labels)} nodes {labels}")
        if len(labels) < 2:
            fail("the reviewed fixture needs at least two nodes to constrain the seal")
        fixture = api.put("/api/meshes/" + mesh["id"] + "/fixture", json={"labels": labels})
        assert fixture.is_success, fixture.text

        deck_job = api.post(
            "/api/decks",
            json={"revision": saved["id"], "token": store.new_id(), "mesh": mesh["id"]},
        )
        assert deck_job.is_success, deck_job.text
        run_worker("acceptance")
        deck = store.job(deck_job.json()["id"])
        assert deck["status"] == "Completed", deck["diagnostic"]
        deck_dir = store.job_dir(deck["id"])
        text = (deck_dir / "analysis.inp").read_text(encoding="utf-8")
        print(f"deck job     : {deck['id']}")
        print(f"deck sha256  : {store.digest(deck_dir / 'analysis.inp')}")
        import re

        block = re.search(r"\*Nset, nset=WSFIX.*?\n(.*?)(?=\n\*|\Z)", text, re.S | re.I)
        written = sorted(int(value) for value in re.findall(r"\d+", block.group(1)))
        expected = sorted(int(label.split(":")[1]) for label in labels)
        print(f"WSFIX equal  : {written == expected} ({len(written)} labels)")
        if not wsfix_matches(written, expected):
            fail("WSFIX does not match the saved selection")
        if not labels:
            fail("the reviewed fixture is empty")

        # Parse the actual generated deck: original rigid identities, SPOS sides,
        # both steps, contact pairs and the requested pressure output.
        parts = parse_rigid_parts(text)
        rigid = [e for e in mesh_json["elements"] if e["type"] == "R2D2"]
        role_of_component = {c["id"]: c["role"] for c in saved["setup"]["components"]}
        expected_rigid = {}
        for element in rigid:
            part = {
                "moving_panel": "PANEL",
                "vehicle_body": "BODY",
            }.get(role_of_component.get(element["component"]))
            if part:
                expected_rigid.setdefault(part, {})[element["id"]] = list(element["nodes"])
        for part in ("PANEL", "BODY"):
            if part not in expected_rigid:
                if part == "BODY" and saved["setup"]["analysis"]["mode"] == "door_only":
                    continue
                fail(f"the deck is missing the {part} rigid profile")
                continue
            if part not in parts:
                fail(f"the deck has no *Part, name={part}")
                continue
            generated = {
                label: (first, second) for label, first, second in parts[part]["elements"]
            }
            if set(generated) != set(expected_rigid[part]):
                fail(f"{part} R2D2 element identities differ from the mesh")
            changed = [
                label
                for label in set(generated) & set(expected_rigid[part])
                if generated[label] != tuple(expected_rigid[part][label])
            ]
            # A reversal of each pair is the allowed contact-side orientation; the
            # node set and element identity must be preserved exactly.
            bad = [
                label
                for label in changed
                if sorted(generated[label]) != sorted(expected_rigid[part][label])
            ]
            if bad:
                fail(f"{part} R2D2 connectivity changed for elements {bad[:4]}")
            print(
                f"{part:5} rigid  : {len(generated)} elements, "
                f"{len(changed)} pairs reversed for SPOS, identities preserved"
            )
            if parts[part]["surfaces"] != [f"{part}_FACE"]:
                fail(f"{part} has the wrong surface definitions {parts[part]['surfaces']}")
            block = re.search(
                r"\*Surface, type=ELEMENT, name=" + part + r"_FACE\n(.*?)(?=\n\*|\Z)",
                text,
                re.S,
            )
            if not block or "PROFILE, SPOS" not in block.group(1):
                fail(f"{part}_FACE does not use PROFILE, SPOS")

        continuum = [e for e in mesh_json["elements"] if e["type"] != "R2D2"]
        nodes = {n["id"]: n["xyz"] for n in mesh_json["nodes"]}
        setup = saved["setup"]
        schema_version = int(setup.get("schema_version", 1))
        deltas = {"PANEL": _motion_delta(setup.get("motion", {}), schema_version)}
        if "BODY" in parts:
            deltas["BODY"] = _motion_delta(
                setup.get("motion", {}).get("body", {}), schema_version
            )
        instance_translations = {
            part: _instance_translation(text, f"{part}-1") for part in parts
        }
        checks = rigid_spos_checks(
            parts,
            seal_boundary_segments(nodes, continuum),
            instance_translations=instance_translations,
            deltas=deltas,
        )
        for row in checks:
            print(
                f"SPOS {row['part']:5} : closest {row['closest_mm']:.4f} mm, "
                f"first contact {row['first_contact_fraction']}, "
                f"{row['near']} elements, min dot {row['min_dot']:+.6f}"
            )
            if row["first_contact_fraction"] is None:
                print(f"SPOS {row['part']:5} : no first contact; orientation not asserted")
                continue
            if row["min_dot"] <= 0:
                fail(f"{row['part']} SPOS faces away from the seal at first contact")

        door_nodes = sorted(
            {node for _, first, second in parts["PANEL"]["elements"] for node in (first, second)}
        )
        if parse_nset(text, "DOOR_PROFILE_NODES") != door_nodes:
            fail("DOOR_PROFILE_NODES does not equal the generated door R2D2 node set")
        if "*Contact Output, nset=DOOR_PROFILE_NODES" not in text:
            fail("the deck does not request door-profile contact output")
        door_output = re.search(
            r"\*Contact Output, nset=DOOR_PROFILE_NODES\n(.*?)(?=\n\*|\Z)", text, re.S
        )
        door_tokens = (
            {token.strip() for token in door_output.group(1).split(",") if token.strip()}
            if door_output
            else set()
        )
        global_stress = re.search(r"\*Contact Output\n([^\n]*)", text)
        global_tokens = (
            {token.strip() for token in global_stress.group(1).split(",") if token.strip()}
            if global_stress
            else set()
        )
        # The licensed pilot pattern: global CSTRESS plus door CFORCE, or the
        # scoped pair CFORCE, CSTRESS when global stress is off. Either way the
        # deck must request both the door force and the pressure field.
        if "CFORCE" not in door_tokens:
            fail("door-profile contact output must request CFORCE")
        if "CPRESS" not in door_tokens and "CSTRESS" not in global_tokens:
            fail("door-profile pressure output must request CPRESS or global CSTRESS")
        if "*Contact Inclusions" not in text:
            fail("the deck has no general-contact inclusions")
        if "ASSEMBLY_WS-1_SEAL_EXTERIOR, ASSEMBLY_PANEL-1_PANEL_FACE" not in text:
            fail("the door/seal contact pair is missing")
        if saved["setup"]["analysis"]["mode"] == "body_then_door":
            if "ASSEMBLY_WS-1_SEAL_EXTERIOR, ASSEMBLY_BODY-1_BODY_FACE" not in text:
                fail("the body/seal contact pair is missing")
            if "ASSEMBLY_WS-1_SEAL_EXTERIOR, ASSEMBLY_WS-1_SEAL_EXTERIOR" not in text:
                fail("the seal self-contact pair is missing")
        no_cavity = [face for face in saved["setup"]["faces"] if not face["cavity"]]
        sections = re.findall(r"\*Solid Section, elset=REGION_\d+, material=MAT_\d+", text)
        print(f"sections     : {len(sections)} for {len(no_cavity)} filled region(s), cavities excluded")
        if len(sections) != len(no_cavity):
            fail("the deck must write one solid section per filled region and none for cavities")
        steps = re.findall(r"\*Step, name=([^,\n]+)", text)
        print(f"steps        : {steps}")
        if saved["setup"]["analysis"]["mode"] == "body_then_door":
            if steps[:2] != ["Body seating", "Closing"]:
                fail("the two-step deck must contain Body seating then Closing")
            body_step = text.split("*Step, name=Body seating", 1)[1].split("*End Step", 1)[0]
            door_step = text.split("*Step, name=Closing", 1)[1].split("*End Step", 1)[0]
            body_delta = [
                float(value)
                for value in re.findall(r"BODY_RP, 2, 2, (-?[0-9.eE+]+)", body_step)[:1]
            ]
            door_delta = [
                float(value)
                for value in re.findall(r"PANEL_RP, 2, 2, (-?[0-9.eE+]+)", door_step)[:1]
            ]
            expected_body = options.body_stroke * (1 if options.body_angle == 90 else -1)
            expected_door = options.door_stroke * (1 if options.door_angle == 90 else -1)
            print(f"body delta   : {body_delta} (expected {expected_body})")
            print(f"door delta   : {door_delta} (expected {expected_door})")
            if not body_delta or abs(body_delta[0] - expected_body) > 1e-6:
                fail("the body seating step does not prescribe the configured upward travel")
            if not door_delta or abs(door_delta[0] - expected_door) > 1e-6:
                fail("the closing step does not prescribe the configured downward travel")
        elif steps != ["Closing"]:
            fail("the door-only deck must contain one Closing step")
        print(f"WSFIX labels : {written}")

        if not options.licensed:
            print("result       : native path complete, no solver tokens consumed")
            if PROBLEMS:
                raise SystemExit("FAILED: " + "; ".join(PROBLEMS))
            return

        submitted = api.post(
            "/api/runs",
            json={
                "revision": saved["id"],
                "deck": deck["id"],
                "mode": "ABAQUS",
                "token": store.new_id(),
                "name": "DWG acceptance",
            },
        )
        assert submitted.is_success, submitted.text
        run_worker("acceptance")
        job = store.job(submitted.json()["id"])
        print(f"run          : {job['id']}")
        print(f"solver       : {job['solver']} / extraction {job['extraction']}")
        print(f"phase        : {job['phase']}")
        print(f"diagnostic   : {job['diagnostic']}")
        directory = store.job_dir(job["id"])
        if job["solver"] != "Succeeded":
            fail("solver status is " + str(job["solver"]))
        if job["extraction"] != "Succeeded":
            fail("extraction status is " + str(job["extraction"]))
        for name in ("results.json", "result-metadata.json", "history.csv", "analysis.odb"):
            path = directory / name
            print(f"{name:20} : {'present' if path.is_file() else 'missing'}")
            if not path.is_file():
                fail("missing output " + name)
        warnings = []
        message_file = directory / "analysis.msg"
        if message_file.is_file():
            for line in message_file.read_text(errors="replace").splitlines():
                stripped = line.strip()
                if stripped.startswith("***WARNING") or stripped.startswith("***NOTE"):
                    warnings.append(stripped[:160])
        sta = directory / "analysis.sta"
        print(f"analysis.msg : {len(warnings)} warning/note lines")
        for line in warnings[:10]:
            print("  " + line)
        if sta.is_file():
            lines = [line for line in sta.read_text(errors="replace").splitlines() if line.strip()]
            completed = [line for line in lines if "COMPLETED SUCCESSFULLY" in line]
            print(f"analysis.sta : {'completed' if completed else 'no completion line'}")
            if not completed:
                fail("the solver did not report THE ANALYSIS HAS COMPLETED SUCCESSFULLY")
        results = json.loads((directory / "results.json").read_text(encoding="utf-8"))
        history = results.get("history", [])
        if not history:
            fail("the extracted history is empty")
        else:
            last = history[-1]
            import math as math_module

            prescribed_dy = options.door_stroke * math_module.sin(
                math_module.radians(options.door_angle)
            )
            ok, travel = travel_attained(history, prescribed_dy)
            required = abs(float(prescribed_dy))
            print(f"travel       : {travel:.4f} mm of {required:.4f} mm prescribed")
            if not ok:
                fail("prescribed door travel was not attained")
            contact = first_contact(history)
            if contact is None:
                print("contact      : no contact found")
                fail("no contact was detected during closing")
            else:
                print(f"contact      : first non-zero RF2 at travel {abs(float(contact['u2'])):.4f} mm")
            # Fixed nodes must be absent from every frame's displacement noise.
            labels_int = {int(label.split(":")[1]) for label in labels}
            worst = 0.0
            frames = 0
            for frame in sorted(directory.glob("frame-*.json")):
                payload = json.loads(frame.read_text(encoding="utf-8"))
                rows = payload.get("displacements", {}).get("WS-1", [])
                mapping = {int(row[0]): row[1:] for row in rows}
                missing = labels_int - set(mapping)
                if missing:
                    fail("frame " + frame.name + " is missing fixed nodes " + str(sorted(missing)))
                    break
                for label in labels_int:
                    worst = max(worst, max(abs(float(value)) for value in mapping[label]))
                frames += 1
            print(f"frames       : {frames}; worst fixed-node |U| {worst:.3e} mm")
            if worst > 1e-9:
                fail("a fixed node moved " + format(worst, ".3e") + " mm")
            csv_path = directory / "history.csv"
            if csv_path.is_file() and history:
                import csv as csv_module
                rows = list(csv_module.DictReader(csv_path.open(encoding="utf-8-sig")))
                if rows:
                    final = rows[-1]
                    if abs(float(final["panel_U2_mm"]) - float(history[-1]["u2"])) > 1e-9:
                        fail("history.csv and the extracted ODB disagree on panel U2")
                    if abs(float(final["panel_RF2_N"]) - float(history[-1]["rf2"])) > 1e-9:
                        fail("history.csv and the extracted ODB disagree on panel RF2")
        print(f"evidence     : {options.evidence}")
    if PROBLEMS:
        raise SystemExit("FAILED: " + "; ".join(PROBLEMS))
    print("result       : all acceptance checks passed")


if __name__ == "__main__":
    main()
