"""Gate 2: a bounded native failed solver case with a usable ODB.

The deck is the application-generated deck with only its maximum increment count
bounded, so Abaqus/Standard accepts a few increments and then terminates with
"TOO MANY INCREMENTS". That is a native solver failure, not a fabricated status.
The production extractor then recovers the saved frames, and the generation is
published as a partial result and portable package.

Usage:
  .venv\\Scripts\\python.exe scripts\\gate2_native_failed.py --case one|two \
      --evidence .local/evidence/gate2-native-failed-<case>
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


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bounded(deck: str, bound_step: int, increments: int = 100):
    """Bound one step definition and keep enough output points for it.

    Abaqus requires at least as many allowed increments as requested output
    points, so the output interval of the bounded step is refined together with
    the increment cap. The solver then reaches the cap before the step
    converges, terminates with "TOO MANY INCREMENTS", and leaves the frames it
    accepted on disk. Earlier steps keep their original output plan.
    """
    lines = deck.splitlines()
    current = 0
    for index, line in enumerate(lines):
        if line.startswith("*Step") and "inc=" in line.lower():
            current += 1
            if current == bound_step:
                lines[index] = line.replace("inc=100000", f"inc={increments}")
        if (
            current == bound_step
            and line.startswith("*Output")
            and "time interval=0.02" in line
        ):
            lines[index] = line.replace("time interval=0.02", "time interval=0.01")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("one", "two"), required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    evidence = Path(args.evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    os.environ["SEAL_DATA"] = str(evidence / "data")
    os.environ.pop("ABAQUS_QOL_DATA", None)
    from services import store

    store.initialize()
    from packages.engineering import generate_mesh, synthetic, two_panel_section
    from integrations.abaqus import deck as deck_module
    from integrations.abaqus import launcher, results

    project = synthetic() if args.case == "one" else two_panel_section()
    if args.case == "two":
        project.motion.body.stroke = 1.0
    mesh = generate_mesh(project)
    bound_step = 1 if args.case == "one" else 2
    increments = 100 if args.case == "one" else 150
    inp = bounded(deck_module.write_inp(project, mesh), bound_step, increments)
    revision = store.save(project.model_dump(mode="json"))
    jid = store.new_id()
    directory = store.job_dir(jid)
    directory.mkdir(parents=True)
    (directory / "analysis.inp").write_text(inp, encoding="ascii")
    (directory / "mesh.json").write_text(store.encoded(mesh), encoding="utf-8")
    (directory / "setup.json").write_text(
        project.model_dump_json(indent=2), encoding="utf-8"
    )
    results.write_metadata(project, mesh, directory)
    report = {
        "kind": "bounded native failed solver case",
        "case": args.case,
        "template": "one-panel Closing"
        if args.case == "one"
        else "two-panel Closing after Body seating",
        "max_increments": 100 if args.case == "one" else 150,
        "output_interval_s": 0.01,
        "inp_sha256": sha(directory / "analysis.inp"),
        "job": jid,
    }
    # A fresh run directory: the launcher refuses pre-existing solver artifacts.
    if any((directory / name).exists() for name in ("analysis.odb", "analysis.sta")):
        raise SystemExit("Run directory is not fresh")

    started = time.time()
    with (directory / "solver.log").open("ab", buffering=0) as log:
        process = launcher.start_solver(
            launcher.configured_launcher(), directory, 1, log
        )
        exit_code = process.wait(timeout=3600)
    report["solver_exit"] = exit_code
    report["solver_seconds"] = round(time.time() - started, 1)
    report["sta_tail"] = launcher.tail(directory / "analysis.sta", 2000)
    (evidence / "solver-msg-tail.txt").write_text(
        launcher.tail(directory / "analysis.msg", 4000), encoding="utf-8", errors="replace"
    )
    evidence_ok, evidence_reason = launcher.solver_evidence(directory, exit_code)
    report["solver_evidence_ok"] = evidence_ok
    report["solver_evidence_reason"] = evidence_reason
    if evidence_ok:
        raise SystemExit("The bounded case unexpectedly completed; it is not a failure")
    if not (directory / "analysis.odb").is_file():
        raise SystemExit("The failed run produced no ODB")
    report["odb_sha256"] = sha(directory / "analysis.odb")
    report["odb_bytes"] = (directory / "analysis.odb").stat().st_size
    report["failure_reason"] = (
        (directory / "analysis.msg").read_text(encoding="utf-8", errors="replace")[-1200:]
        if (directory / "analysis.msg").is_file()
        else "Abaqus/Standard terminated after the bounded increment count"
    )
    (directory / "extraction-context.json").write_text(
        store.encoded(
            {
                "solver_outcome": "Failed",
                "failure_reason": "Abaqus/Standard terminated after the bounded increment count; saved frames retained",
            }
        ),
        encoding="utf-8",
    )
    started = time.time()
    with (directory / "extract.log").open("ab", buffering=0) as log:
        process = launcher.start_extraction(
            launcher.configured_launcher(), directory, log
        )
        extraction_exit = process.wait(timeout=3600)
    report["extraction_exit"] = extraction_exit
    report["extraction_seconds"] = round(time.time() - started, 1)
    if extraction_exit != 0:
        report["extract_log_tail"] = (directory / "extract.log").read_text(
            encoding="utf-8", errors="replace"
        )[-4000:]
        (evidence / "gate2-native-failed.json").write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        raise SystemExit(f"Extraction failed with exit {extraction_exit}")

    index = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    report["availability"] = index.get("availability")
    report["frames"] = len(index["frames"])
    report["last_step"] = index.get("last_step")
    report["last_step_id"] = index.get("last_step_id")
    report["last_frame_ordinal"] = index.get("last_frame_ordinal")
    report["last_native_frame_id"] = index.get("last_native_frame_id")
    report["last_increment"] = index.get("last_increment")
    report["last_local_s"] = index.get("last_local_s")
    report["last_total_s"] = index.get("last_total_s")
    report["skipped_frames"] = index.get("skipped_frames")
    report["index_sha256"] = sha(directory / "results.json")
    last = json.loads(
        (directory / index["frames"][-1]["file"]).read_text(encoding="utf-8")
    )
    report["last_frame_fields"] = sorted((last.get("fields") or {}).keys())
    report["last_step_recorded"] = last.get("step")
    # A readable saved frame must exist, and the last frame must be the latest
    # by step/frame order rather than the status file's time.
    if not index["frames"]:
        raise SystemExit("Extraction published no frames")
    summary = {
        "availability": "partial",
        "solver_outcome": "Failed",
        "failure_reason": "Bounded native solver failure; saved frames retained",
        "last_step": index.get("last_step"),
        "last_step_id": index.get("last_step_id"),
        "last_role": "body" if index.get("last_step_id") == "bodyseating" else "door",
        "last_local_s": index.get("last_local_s"),
        "last_total_s": index.get("last_total_s"),
        "frames": len(index["frames"]),
        "history_only": False,
        "initial_only": bool(index.get("initial_only")),
        "skipped": len(index.get("skipped_frames") or []),
        "frame_ordinal": index.get("last_frame_ordinal"),
        "native_frame_id": index.get("last_native_frame_id"),
        "increment": index.get("last_increment"),
        "generation": 1,
        "index_sha256": report["index_sha256"],
        "diagnostic": "Bounded native solver failure after accepted increments",
    }
    with store.connection(True) as db:
        db.execute(
            """INSERT INTO jobs(id,revision,name,mode,scenario,cpus,token,created,started,
               ended,solver,extraction,phase,diagnostic,step,increment,step_time,exit_code,
               extraction_exit,input_hash,manifest,mesh_digest,result_state,result_summary,
               result_generation)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                jid,
                revision["id"],
                "Bounded native failed case (" + args.case + ")",
                "ABAQUS",
                "native-failure",
                1,
                store.new_id(),
                time.time(),
                time.time(),
                time.time(),
                "Failed",
                "Succeeded",
                "Partial results ready",
                "Bounded native solver failure after accepted increments",
                index.get("last_step"),
                index.get("last_increment"),
                index.get("last_local_s"),
                exit_code,
                extraction_exit,
                report["inp_sha256"],
                store.encoded(
                    sorted(
                        p.name
                        for p in directory.iterdir()
                        if p.is_file() and not p.name.startswith(".")
                    )
                ),
                sha(directory / "mesh.json"),
                "partial",
                store.encoded(summary),
                1,
            ),
        )
    from services import portable_files

    packaged = portable_files.package_job(jid, str(evidence))
    report["aqresult"] = packaged["path"]
    report["aqresult_sha256"] = packaged["sha256"]
    report["job"] = jid
    report["data_root"] = str(evidence / "data")
    (evidence / "job-id.txt").write_text(jid, encoding="utf-8")
    (evidence / "gate2-native-failed.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
