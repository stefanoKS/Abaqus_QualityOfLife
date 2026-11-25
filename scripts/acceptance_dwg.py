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


def rigid_spos_checks(parts, seal_segments, tolerance=1e-6):
    """Local first-contact SPOS orientation for every rigid part.

    The check is independent of the writer's decision: it walks the generated
    R2D2 connectivity, recomputes each normal and compares it with the
    direction to the nearest seal segment at the closest elements.
    """
    from math import hypot

    from shapely.geometry import Point
    from shapely.ops import nearest_points
    from shapely.geometry import MultiLineString

    seal = MultiLineString(
        [[(segment[0], segment[1]), (segment[2], segment[3])] for segment in seal_segments]
    )
    rows = []
    for name, part in parts.items():
        distances = []
        for element, first, second in part["elements"]:
            a, b = part["nodes"][first], part["nodes"][second]
            midpoint = Point((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            distance = midpoint.distance(seal)
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = hypot(dx, dy)
            normal = (-dy / length, dx / length)
            _, on_seal = nearest_points(midpoint, seal)
            vx, vy = on_seal.x - midpoint.x, on_seal.y - midpoint.y
            vlength = hypot(vx, vy)
            dot = 0.0 if vlength <= 0 else (normal[0] * vx + normal[1] * vy) / vlength
            distances.append((distance, dot, element, midpoint))
        if not distances:
            continue
        closest = min(item[0] for item in distances)
        near = [item for item in distances if item[0] <= closest + max(0.5, closest * 0.02)]
        rows.append(
            {
                "part": name,
                "elements": len(distances),
                "closest_mm": closest,
                "near": len(near),
                "min_dot": min(item[1] for item in near),
                "sum_dot": sum(item[1] for item in near),
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
        checks = rigid_spos_checks(parts, seal_boundary_segments(nodes, continuum))
        for row in checks:
            print(
                f"SPOS {row['part']:5} : closest {row['closest_mm']:.4f} mm, "
                f"{row['near']} first-contact elements, min dot {row['min_dot']:+.6f}"
            )
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
