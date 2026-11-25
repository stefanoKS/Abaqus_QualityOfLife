"""Gate C second case: licensed body-then-door run with door pressure output.

Runs the normal API -> durable worker -> Abaqus/Standard -> extractor path in an
isolated data root. No browser and no manufactured result.
"""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / ".local" / "gate-c"
DATA = EVIDENCE / "twostep-data"
os.environ["SEAL_DATA"] = str(DATA)
os.environ.setdefault("SIMPLIFY_ABAQUS_LAUNCHER", r"C:\SIMULIA\Commands\abq2024.bat")
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from services import store  # noqa: E402
from services.api.main import app  # noqa: E402
from services.worker.__main__ import once  # noqa: E402


def worker(owner="gate-c-twostep"):
    for _ in range(40):
        if not once(owner):
            return
    raise SystemExit("worker kept claiming jobs")


def post(api, path, data):
    response = api.post(path, json=data)
    assert response.is_success, response.text
    return response.json()


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with TestClient(app, base_url="http://127.0.0.1") as api:
        project = post(
            api,
            "/api/projects",
            {"name": "Door pressure two-step", "example": True, "template": "two-panel"},
        )
        setup = project["setup"]
        setup["motion"]["body"]["stroke"] = 4.0
        setup["motion"]["body"]["angle"] = 90
        setup["motion"]["body"]["duration"] = 0.4
        setup["motion"]["stroke"] = 2.5
        setup["motion"]["angle"] = -90
        setup["motion"]["duration"] = 0.4
        response = api.put(
            "/api/projects/" + project["project"],
            json={"base": project["id"], "setup": setup},
        )
        assert response.is_success, response.text
        project = response.json()

        mesh = post(api, "/api/meshes", {"revision": project["id"], "token": store.new_id()})
        worker()
        mesh_job = store.job(mesh["id"])
        assert mesh_job["status"] == "Completed", mesh_job["diagnostic"]
        resolved = post(api, "/api/meshes/" + mesh["id"] + "/fixture/edges", {})
        saved = api.put(
            "/api/meshes/" + mesh["id"] + "/fixture", json={"labels": resolved["labels"]}
        )
        assert saved.is_success, saved.text
        deck = post(
            api,
            "/api/decks",
            {
                "revision": project["id"],
                "token": store.new_id(),
                "mesh": mesh["id"],
                "fixture_hash": resolved["hash"],
            },
        )
        worker()
        deck_job = store.job(deck["id"])
        assert deck_job["status"] == "Completed", deck_job["diagnostic"]
        text = (store.job_dir(deck["id"]) / "analysis.inp").read_text(encoding="utf-8")
        assert text.count("*Contact Output, nset=DOOR_PROFILE_NODES") == 2
        assert text.count("*Nset, nset=DOOR_PROFILE_NODES, instance=PANEL-1") == 1

        run = post(
            api,
            "/api/runs",
            {
                "revision": project["id"],
                "deck": deck["id"],
                "token": store.new_id(),
                "name": "Door pressure two-step",
                "mode": "ABAQUS",
                "cpus": 1,
            },
        )
        worker()
        job = store.job(run["id"])
        directory = store.job_dir(job["id"])
        index = json.loads((directory / "results.json").read_text(encoding="utf-8"))
        report = {
            "job": job["id"],
            "solver": job["solver"],
            "extraction": job["extraction"],
            "exit_code": job["exit_code"],
            "extraction_exit": job["extraction_exit"],
            "diagnostic": job["diagnostic"],
            "input_sha256": job["input_hash"],
            "frames": len(index["frames"]),
            "steps": [step["name"] for step in index.get("steps") or []],
            "door_profiles": [
                {
                    "id": entry["id"],
                    "alias": entry["alias"],
                    "labels": len(entry["labels"]),
                    "maximum_pressure_kpa": entry.get("maximum_pressure_kpa"),
                }
                for entry in index.get("door_pressure", {}).get("profiles") or []
            ],
            "step_frames": {},
        }
        if job["solver"] != "Succeeded" or job["extraction"] != "Succeeded":
            raise SystemExit(json.dumps(report, indent=2))
        for entry in index["frames"]:
            frame = json.loads((directory / entry["file"]).read_text(encoding="utf-8"))
            door = frame.get("door_pressure") or {}
            positive = 0
            samples = 0
            for profile in (door.get("profiles") or {}).values():
                for value in profile.get("pressure_kpa") or []:
                    if value is None:
                        continue
                    samples += 1
                    if value > 0:
                        positive += 1
            bucket = report["step_frames"].setdefault(
                entry.get("step") or entry.get("step_id"),
                {"frames": 0, "positive_max": 0, "samples": 0},
            )
            bucket["frames"] += 1
            bucket["positive_max"] = max(bucket["positive_max"], positive)
            bucket["samples"] = max(bucket["samples"], samples)
        (EVIDENCE / "gate-c-twostep.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, indent=2))
        if not report["door_profiles"]:
            raise SystemExit("no door profile in the two-step result")
        if report["step_frames"].get("Body seating", {}).get("positive_max", 1) != 0:
            raise SystemExit("door pressure appeared during body seating")
        if report["step_frames"].get("Closing", {}).get("positive_max", 0) <= 0:
            raise SystemExit("no positive door pressure during closing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
