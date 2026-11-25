"""Gate 2: recover a retained native cancellation through the real extractor.

Reads a verified, inactive copy of the retained job's ODB with the installed
Abaqus 2024 Python. The source directory, its ODB and its lock are never opened
for writing. The produced generation is published as a partial result and a
`.aqresult` package, then served by the normal API for Results/File Open.

Usage:
  .venv\\Scripts\\python.exe scripts\\gate2_native_partial.py \
      --source .local/gate-c/data/jobs/313893f2-... \
      --evidence .local/evidence/gate2-native-partial
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED_ODB = "5faf3255638e3cb033f1bd45b2b0ee6c9fa3bf38b3f0f94e430b036c45f528ea"
EXPECTED_FRAMES = 43
EXPECTED_LAST_ORDINAL = 42
EXPECTED_NATIVE_FRAME = 162
EXPECTED_TIME = 0.8399999737739563
EXPECTED_NODE = 238
EXPECTED_STATION_MM = 17.5
EXPECTED_PRESSURE_KPA = 2830.7080269
EXPECTED_CNORMF = (0.00834000576, 1.41455960274)


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    source = Path(args.source).resolve()
    evidence = Path(args.evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    report = {"kind": "retained cancelled native ODB", "source": str(source)}

    odb = source / "analysis.odb"
    source_hash = sha(odb)
    if source_hash != EXPECTED_ODB:
        raise SystemExit(f"Unexpected source ODB digest {source_hash}")
    report["source_odb_sha256"] = source_hash
    report["source_odb_bytes"] = odb.stat().st_size
    report["source_lock_retained"] = (source / "analysis.lck").exists()
    lock_before = (source / "analysis.lck").stat().st_mtime_ns

    data = evidence / "data"
    if data.exists():
        shutil.rmtree(data)
    data.mkdir(parents=True)
    os.environ["SEAL_DATA"] = str(data)
    os.environ.pop("ABAQUS_QOL_DATA", None)
    from services import store

    store.initialize()
    revision = store.save(
        json.loads((source / "setup.json").read_text(encoding="utf-8"))
    )
    jid = store.new_id()
    directory = store.job_dir(jid)
    directory.mkdir(parents=True)
    # Copy only immutable inputs; never the source's lock or scratch files.
    for name in (
        "analysis.odb",
        "analysis.inp",
        "analysis.sta",
        "analysis.msg",
        "analysis.dat",
        "analysis.log",
        "solver.log",
        "mesh.json",
        "result-metadata.json",
        "setup.json",
        "worker.log",
    ):
        if (source / name).is_file():
            shutil.copyfile(source / name, directory / name)
    (directory / "extraction-context.json").write_text(
        store.encoded(
            {
                "solver_outcome": "Cancelled",
                "failure_reason": "Retained cancellation at step time 0.855 s",
            }
        ),
        encoding="utf-8",
    )
    if sha(directory / "analysis.odb") != source_hash:
        raise SystemExit("The copied ODB does not match the source digest")

    metadata = json.loads((directory / "result-metadata.json").read_text(encoding="utf-8"))
    fixture = (metadata.get("fixture") or {}).get("nodes") or []
    manifest = sorted(
        p.name
        for p in directory.iterdir()
        if p.is_file() and not p.name.startswith(".")
    )
    now = time.time()
    with store.connection(True) as db:
        db.execute(
            """INSERT INTO jobs(id,revision,name,mode,scenario,cpus,token,created,started,
               ended,solver,extraction,phase,diagnostic,step,increment,step_time,exit_code,
               input_hash,manifest,mesh_digest,fixture_hash,fixture_labels,result_state,
               result_generation,salvage)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                jid,
                revision["id"],
                "Retained cancelled 6.5 mm trial",
                "ABAQUS",
                "retained",
                1,
                store.new_id(),
                now,
                now,
                now,
                "Cancelled",
                "Queued",
                "Awaiting result recovery",
                "",
                "1",
                1484,
                0.855,
                None,
                sha(directory / "analysis.inp"),
                store.encoded(manifest),
                sha(directory / "mesh.json"),
                None,
                store.encoded(fixture),
                "none",
                0,
                1,
            ),
        )

    from integrations.abaqus import launcher

    started = time.time()
    with (directory / "extract.log").open("ab", buffering=0) as log:
        process = launcher.start_extraction(
            launcher.configured_launcher(), directory, log
        )
        exit_code = process.wait(timeout=3600)
    report["extraction_exit"] = exit_code
    report["extraction_seconds"] = round(time.time() - started, 1)
    if exit_code != 0:
        report["extract_log_tail"] = (directory / "extract.log").read_text(
            encoding="utf-8", errors="replace"
        )[-4000:]
        (evidence / "gate2-native-partial.json").write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        raise SystemExit(f"Extraction failed with exit {exit_code}")

    index = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    report["index_sha256"] = sha(directory / "results.json")
    report["frames"] = len(index["frames"])
    report["availability"] = index.get("availability")
    report["last_frame_ordinal"] = index.get("last_frame_ordinal")
    report["last_native_frame_id"] = index.get("last_native_frame_id")
    report["last_increment"] = index.get("last_increment")
    report["last_local_s"] = index.get("last_local_s")
    report["last_total_s"] = index.get("last_total_s")
    last = json.loads(
        (directory / index["frames"][-1]["file"]).read_text(encoding="utf-8")
    )
    profile_id, profile = next(
        (key, value)
        for key, value in last["door_pressure"]["profiles"].items()
        if value.get("supported")
    )
    definition = next(
        entry
        for entry in index["door_pressure"]["profiles"]
        if entry["id"] == profile_id
    )
    position = profile["labels"].index(EXPECTED_NODE)
    measured = {
        "profile": profile_id,
        "node": EXPECTED_NODE,
        "station_mm": definition["stations_mm"][position],
        "pressure_kpa": profile["pressure_kpa"][position],
        "cnormf_n": profile["cnormf_n"][position],
    }
    report["reference"] = measured
    failures = []
    if report["frames"] != EXPECTED_FRAMES:
        failures.append(f"frames {report['frames']} != {EXPECTED_FRAMES}")
    if report["last_frame_ordinal"] != EXPECTED_LAST_ORDINAL:
        failures.append(f"last ordinal {report['last_frame_ordinal']}")
    if report["last_native_frame_id"] != EXPECTED_NATIVE_FRAME:
        failures.append(f"native frame {report['last_native_frame_id']}")
    if abs(float(report["last_total_s"]) - EXPECTED_TIME) > 1e-9:
        failures.append(f"time {report['last_total_s']}")
    if abs(measured["pressure_kpa"] - EXPECTED_PRESSURE_KPA) > 1e-6:
        failures.append(f"pressure {measured['pressure_kpa']}")
    if max(
        abs(measured["cnormf_n"][axis] - EXPECTED_CNORMF[axis]) for axis in (0, 1)
    ) > 1e-9:
        failures.append(f"cnormf {measured['cnormf_n']}")
    report["failures"] = failures

    from integrations.abaqus.interchange import display_metadata

    summary = {
        "availability": "partial",
        "solver_outcome": "Cancelled",
        "failure_reason": "Retained cancellation at step time 0.855 s",
        "last_step": index.get("last_step"),
        "last_step_id": index.get("last_step_id"),
        "last_role": "door",
        "last_local_s": index.get("last_local_s"),
        "last_total_s": index.get("last_total_s"),
        "frames": len(index["frames"]),
        "history_only": False,
        "initial_only": False,
        "skipped": len(index.get("skipped_frames") or []),
        "frame_ordinal": index.get("last_frame_ordinal"),
        "native_frame_id": index.get("last_native_frame_id"),
        "increment": index.get("last_increment"),
        "generation": 1,
        "index_sha256": report["index_sha256"],
        "diagnostic": "Retained cancellation; last saved frame recovered",
    }
    with store.connection(True) as db:
        db.execute(
            """UPDATE jobs SET extraction='Succeeded',extraction_exit=0,
               phase='Partial results ready',result_state='partial',result_summary=?,
               result_generation=1,salvage=0,ended=?,manifest=? WHERE id=?""",
            (
                store.encoded(summary),
                time.time(),
                store.encoded(
                    sorted(
                        p.name
                        for p in directory.iterdir()
                        if p.is_file() and not p.name.startswith(".")
                    )
                ),
                jid,
            ),
        )
    report["job"] = jid
    report["data_root"] = str(data)
    report["lock_mtime_unchanged"] = (
        (source / "analysis.lck").stat().st_mtime_ns == lock_before
    )

    from services import portable_files

    packaged = portable_files.package_job(jid, str(evidence))
    report["aqresult"] = packaged["path"]
    report["aqresult_sha256"] = packaged["sha256"]
    report["aqresult_availability"] = packaged.get("availability")
    (evidence / "job-id.txt").write_text(jid, encoding="utf-8")
    (evidence / "gate2-native-partial.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    if failures or report["extraction_exit"] != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
