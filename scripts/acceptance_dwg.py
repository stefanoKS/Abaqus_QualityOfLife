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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drawing", type=Path, default=DRAWING)
    parser.add_argument("--evidence", type=Path, default=ROOT / ".local" / "dwg-acceptance")
    parser.add_argument("--licensed", action="store_true", help="also submit a real Abaqus run")
    parser.add_argument("--travel", type=float, default=-5.5)
    parser.add_argument("--duration", type=float, default=1.3)
    options = parser.parse_args()

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
        setup["motion"]["travel"] = options.travel
        setup["motion"]["duration"] = options.duration
        saved = api.put(
            "/api/projects/" + revision["project"],
            json={"setup": setup, "base": revision["id"]},
        )
        assert saved.is_success, saved.text
        saved = saved.json()

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

        # Box selection: the mounting foot is the lowest weatherstrip boundary.
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
        lowest = min(coords[node][1] for node in candidates)
        labels = [f"WS-1:{node}" for node in candidates if coords[node][1] <= lowest + 1e-6]
        print(f"fixture      : {len(labels)} nodes {labels}")
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
            ok, travel = travel_attained(history, options.travel)
            required = abs(float(options.travel))
            print(f"travel       : {travel:.4f} mm of {required:.4f} mm prescribed")
            if not ok:
                fail("prescribed travel was not attained")
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
