"""Gate E: reopen a worker-published `.aqresult` in a fresh data root.

Compares the reopened index and every frame with the submitted artifacts,
including the door profile axis, units, per-station pressure/force arrays and
frame order. The fresh root is disposable; the source artifacts are hashed
before and after and are never modified.
"""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def tree_digest(directory, names):
    return {name: digest(Path(directory) / name) for name in names if (Path(directory) / name).is_file()}


def compare(source, reopened, names):
    problems = []
    source_index = json.loads((source / "results.json").read_text(encoding="utf-8"))
    reopened_index = json.loads((reopened / "results.json").read_text(encoding="utf-8"))
    if source_index.get("frames") != reopened_index.get("frames"):
        problems.append("frame order or identity changed")
    for key in ("door_pressure", "steps", "closing", "body", "units", "force_unit", "thickness_mm"):
        if source_index.get(key) != reopened_index.get(key):
            problems.append(f"{key} changed on reopen")
    if (source / "history.csv").read_bytes() != (reopened / "history.csv").read_bytes():
        problems.append("history.csv bytes changed")
    for entry in source_index["frames"]:
        name = entry["file"]
        if (source / name).read_bytes() != (reopened / name).read_bytes():
            problems.append(f"frame bytes changed: {name}")
    return source_index, reopened_index, problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-data", type=Path, required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--aqresult", type=Path, required=True)
    parser.add_argument("--fresh-data", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source = args.source_data / "jobs" / args.job
    if not source.is_dir():
        raise SystemExit(f"source job directory is missing: {source}")
    source_index = json.loads((source / "results.json").read_text(encoding="utf-8"))
    names = [entry["file"] for entry in source_index["frames"]]
    before = tree_digest(source, ["results.json", "history.csv", *names])
    fresh = args.fresh_data or Path(tempfile.mkdtemp(prefix="reopen-", dir=str(ROOT / ".local" / "gate-c")))
    if fresh.exists():
        shutil.rmtree(fresh)
    fresh.mkdir(parents=True)
    os.environ["SEAL_DATA"] = str(fresh)
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient

    from services.api.main import app

    with TestClient(app, base_url="http://127.0.0.1") as api:
        response = api.post("/api/files/result/open", json={"path": str(args.aqresult)})
        assert response.is_success, response.text
        job = response.json()
        reopened = fresh / "jobs" / job["id"]
    _, reopened_index, problems = compare(source, reopened, names)
    after = tree_digest(source, ["results.json", "history.csv", *names])
    if before != after:
        problems.append("source artifacts changed")
    door = reopened_index.get("door_pressure") or {}
    profiles = [entry for entry in door.get("profiles") or [] if entry.get("supported")]
    report = {
        "source_job": args.job,
        "reopened_job": job["id"],
        "aqresult": str(args.aqresult),
        "aqresult_sha256": digest(args.aqresult),
        "fresh_data": str(fresh),
        "frames": len(reopened_index["frames"]),
        "profiles": [
            {
                "id": entry["id"],
                "alias": entry["alias"],
                "labels": len(entry["labels"]),
                "stations_mm": [entry["stations_mm"][0], entry["stations_mm"][-1]],
                "length_mm": entry["length_mm"],
                "maximum_pressure_kpa": entry.get("maximum_pressure_kpa"),
            }
            for entry in profiles
        ],
        "native_unit": door.get("native_unit"),
        "display_unit": door.get("display_unit"),
        "conversion": door.get("conversion"),
        "problems": problems,
        "source_artifacts_unchanged": before == after,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if problems:
        print("FAILED: " + "; ".join(problems))
        return 1
    print("result: reopened result matches the submitted artifacts exactly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
