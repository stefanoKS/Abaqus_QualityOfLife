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
        launcher = os.environ.get("SIMPLIFY_ABAQUS_LAUNCHER", "")
        if not launcher:
            raise SystemExit("Set SIMPLIFY_ABAQUS_LAUNCHER to run the licensed case.")
        print(f"launcher     : {launcher}")

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
        if written != expected:
            raise SystemExit("WSFIX does not match the saved selection")

        if not options.licensed:
            print("result       : native path complete, no solver tokens consumed")
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
        for name in ("results.json", "result-metadata.json", "history.csv"):
            path = directory / name
            print(f"{name:20} : {'present' if path.is_file() else 'missing'}")
        print(f"evidence     : {options.evidence}")


if __name__ == "__main__":
    main()
