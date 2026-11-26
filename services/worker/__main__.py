"""Durable worker. Only a claimed job may start a process in its own directory."""

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import threading
import time
import traceback

import psutil

from integrations import drawings, dwg
from packages import engineering
from packages.engineering.model import Project
from integrations.abaqus import deck, interchange, launcher, results
from services import store

KNOWN_FILES = {
    "setup.json",
    "mesh.json",
    "mesh-identity.json",
    "analysis.inp",
    "analysis.odb",
    "analysis.dat",
    "analysis.msg",
    "analysis.sta",
    "analysis.log",
    "worker.log",
    "solver.log",
    "extract.log",
    "result-metadata.json",
    "history.csv",
    "results.json",
    "extraction-context.json",
}


def preparation_diagnostic(exc):
    """Worker diagnostic for a failed job.

    A typed preparation rejection keeps its stable code and owning stage, so the
    browser can point at the same condition the readiness view explains. Other
    failures keep their original message.
    """
    diagnostic = str(exc) or type(exc).__name__
    code = getattr(exc, "code", None)
    stage = getattr(exc, "stage", None)
    if code:
        diagnostic = f"{code}" + (f" [{stage}]" if stage else "") + f": {diagnostic}"
    return diagnostic


def manifest(directory):
    return json.dumps(
        sorted(
            p.name
            for p in directory.iterdir()
            if p.is_file() and (p.name in KNOWN_FILES or re.fullmatch(r"frame-\d+\.json", p.name))
        )
    )


class ProcessUncertain(Exception):
    """The worker could not verify that its child stopped."""


class Cancelled(Exception):
    pass


class SolverTerminal(Exception):
    """The solver ended unsuccessfully; the recorded fields already say why."""


def checkpoint(jid, scope="solver"):
    """Honour a cancellation aimed at this stage only.

    A stale solver cancellation must not abort a later, separately authorized
    extraction, and stopping an extraction must not be read as cancelling a
    solver that had already stopped.
    """
    row = store.job(jid)
    if row["cancelled"] and (row.get("cancel_scope") or "solver") == scope:
        raise Cancelled()


@contextmanager
def pulse(jid, owner):
    stop = threading.Event()

    def tick():
        while not stop.wait(2):
            try:
                store.update(jid, owner, heartbeat=time.time())
            except store.Conflict:
                return  # Completion and the last periodic heartbeat can coincide.

    thread = threading.Thread(target=tick, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()


def log(directory, message):
    with (directory / "worker.log").open("a", encoding="utf-8") as stream:
        stream.write(time.strftime("%Y-%m-%d %H:%M:%S %z ") + message + "\n")


def monitor(jid, owner, directory, start, filename, solving=False, scope="solver"):
    with (directory / filename).open("ab", buffering=0) as stream:
        process = start(stream)
        try:
            try:
                birth = psutil.Process(process.pid).create_time()
            except psutil.NoSuchProcess:
                birth = None
            store.update(jid, owner, pid=process.pid, process_started=birth)
            while process.poll() is None:
                checkpoint(jid, scope)
                if solving:
                    info = launcher.progress(directory)
                    waiting = "license" in str(info.get("phase", "")).lower()
                    store.update(
                        jid,
                        owner,
                        solver="Waiting for license" if waiting else "Running",
                        manifest=manifest(directory),
                        **{
                            k: v
                            for k, v in info.items()
                            if k in {"phase", "step", "step_time", "increment"}
                        },
                    )
                time.sleep(0.4)
            return process.returncode
        finally:
            if process.poll() is None:
                try:
                    launcher.stop_process(process)
                except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                    raise ProcessUncertain(str(exc)) from exc


def perform(row, owner):
    jid = row["id"]
    directory = store.job_dir(jid)
    directory.mkdir(parents=True, exist_ok=True)
    extracting = row["extraction"] == "Running"
    fields = {}
    imported = None
    attempt = None
    recovery_reason = ""
    try:
        checkpoint(jid)
        setup = Project.model_validate(store.revision(row["revision"])["setup"])
        if row["mode"] == "DEMO":
            raise ValueError(
                "This is a legacy DEMO job. Synthetic execution has been withdrawn; the "
                "recorded evidence stays readable. Submit an ABAQUS analysis instead."
            )
        if not extracting:
            (directory / "setup.json").write_text(setup.model_dump_json(indent=2), encoding="utf-8")
        log(directory, "Extracting results" if extracting else "Preparing " + row["mode"])
        store.update(jid, owner, manifest=manifest(directory))
        if row["mode"] == "IMPORT":
            upload = store.root() / "drawings" / jid
            metadata = json.loads((upload / "source.json").read_text(encoding="utf-8"))
            ext = Path(metadata["filename"]).suffix.lower()
            source = upload / ("drawing" + ext)
            if ext == ".dwg":
                # Native path: the DWG bytes go straight to the reader helper.
                # No ODA converter and no DXF intermediate take part.
                inventory = dwg.read(source)
                (directory / "dwg-inventory.json").write_text(
                    json.dumps(inventory, indent=2, sort_keys=True), encoding="utf-8"
                )
                imported, report = engineering.dwg.import_inventory(
                    inventory,
                    setup.name,
                    metadata["units"],
                    digest=store.digest(source),
                )
                (directory / "import-report.json").write_text(
                    json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
                )
            else:
                imported = engineering.import_dxf(source, setup.name, metadata["units"])
            imported.source.filename = metadata["filename"]
            # A 3D preview model stays a 3D preview model when it imports a
            # section. Model-level settings that do not depend on the drawing's
            # topology are carried over; mesh refinements that name old edges are not.
            imported.dimension = setup.dimension
            imported.formulation = setup.formulation
            imported.extrusion = setup.extrusion
            imported.analysis = setup.analysis
            imported.motion = setup.motion
            imported.contact = setup.contact
            imported.mesh.size = setup.mesh.size
            imported.mesh.recombine = setup.mesh.recombine
            fields.update(solver="Succeeded", extraction="Succeeded", phase="Drawing imported")
        elif row["mode"] == "MESH":
            mesh = engineering.generate_mesh(setup)
            (directory / "mesh.json").write_text(store.encoded(mesh), encoding="utf-8")
            mesh_digest = store.digest(directory / "mesh.json")
            compat = engineering.mesh_compat(setup)
            (directory / "mesh-identity.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "digest": mesh_digest,
                        "compat": compat,
                        "revision": row["revision"],
                        "inputs": engineering.mesh_inputs(setup),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            checkpoint(jid)
            fields.update(
                solver="Succeeded",
                extraction="Succeeded",
                phase="Mesh ready",
                mesh_digest=mesh_digest,
                mesh_compat=compat,
            )
        elif row["mode"] == "DECK":
            mesh_row = store.job(row["mesh"])
            shutil.copyfile(store.job_dir(row["mesh"]) / "mesh.json", directory / "mesh.json")
            mesh_digest = store.digest(directory / "mesh.json")
            if not mesh_row["mesh_digest"] or mesh_digest != mesh_row["mesh_digest"]:
                raise ValueError("The stored mesh does not match its recorded digest.")
            if mesh_row["mesh_compat"] != engineering.mesh_compat(setup):
                raise ValueError(
                    "The mesh was generated for different mesh inputs. Generate the mesh again."
                )
            # Use the selection captured when the deck was queued, never the live
            # fixture: a later edit to the nodes must not change this deck.
            review = row["fixture_labels"]
            if not review:
                raise ValueError(
                    "Select the fixed weatherstrip nodes before preparing the input deck."
                )
            if engineering.fixture.labels_hash(review) != row["fixture_hash"]:
                raise ValueError("The queued fixed-node snapshot no longer matches its hash.")
            mesh = json.loads((directory / "mesh.json").read_text(encoding="utf-8"))
            inp = deck.write_inp(setup, mesh, review)
            (directory / "analysis.inp").write_text(inp, encoding="utf-8")
            results.write_metadata(setup, mesh, directory, review)
            checkpoint(jid)
            fields.update(
                solver="Succeeded",
                extraction="Succeeded",
                phase="Input ready",
                input_hash=store.digest(directory / "analysis.inp"),
                mesh_digest=mesh_digest,
            )
        elif not extracting:
            prepared = store.job_dir(row["build"])
            for name in ("mesh.json", "analysis.inp", "result-metadata.json"):
                shutil.copyfile(prepared / name, directory / name)
            if store.digest(directory / "analysis.inp") != row["input_hash"]:
                raise ValueError("Input hash differs from the reviewed deck.")
            if row["mesh_digest"] and store.digest(directory / "mesh.json") != row["mesh_digest"]:
                raise ValueError("Mesh digest differs from the reviewed deck.")
            store.update(
                jid, owner, solver="Running", phase="Panel closing", manifest=manifest(directory)
            )
            if row["mode"] == "DEMO":
                log(directory, "DEMO — synthetic results, not an Abaqus analysis.")
                for i in range(10):
                    checkpoint(jid)
                    store.update(
                        jid,
                        owner,
                        step="Synthetic closing",
                        increment=i + 1,
                        step_time=setup.motion.duration * (i + 1) / 10,
                    )
                    time.sleep(2 if row["scenario"] == "slow" else 0.18)
                if row["scenario"] == "failure":
                    raise ValueError("Requested demonstration of solver failure.")
            else:
                executable = launcher.configured_launcher()
                code = monitor(
                    jid,
                    owner,
                    directory,
                    lambda stream: launcher.start_solver(
                        executable, directory, row["cpus"], stream
                    ),
                    "solver.log",
                    True,
                )
                store.update(jid, owner, exit_code=code)
                ok, reason = launcher.solver_evidence(directory, code)
                log(directory, reason)
                if not ok:
                    # A terminal solver failure is still an opportunity to read
                    # whatever the analysis saved. Queue exactly one automatic
                    # extraction-only attempt when a native candidate exists; the
                    # extractor validates readability rather than this check.
                    fields.update(
                        solver="Failed",
                        diagnostic=reason,
                        phase="Solver failed; checking saved results",
                    )
                    possible, why = store._candidate_evidence(directory)
                    if possible:
                        fields.update(
                            extraction="Queued",
                            phase="Awaiting result recovery",
                            salvage=1,
                        )
                    else:
                        log(directory, "No result recovery candidate: " + why)
                    raise SolverTerminal(reason)
            checkpoint(jid)
            fields.update(solver="Succeeded", extraction="Queued", phase="Awaiting extraction")
        else:
            mesh = json.loads((directory / "mesh.json").read_text(encoding="utf-8"))
            metadata_path = directory / "result-metadata.json"
            fixture_labels = row["fixture_labels"]
            if fixture_labels is None and metadata_path.is_file():
                fixture_labels = (
                    json.loads(metadata_path.read_text(encoding="utf-8")).get("fixture") or {}
                ).get("nodes")
            legacy = row["mode"] == "DEMO"
            candidate = None
            if legacy:
                if (
                    row["scenario"] == "extraction_failure"
                    and not (directory / "demo-retry").exists()
                ):
                    (directory / "demo-retry").touch()
                    raise ValueError(
                        "Requested one-time extraction failure. Retry extraction to recover."
                    )
                results.write_demo(setup, mesh, directory, fixture_labels)
                index_path = directory / "results.json"
            else:
                results.write_metadata(setup, mesh, directory, fixture_labels)
                # The submitted metadata stays immutable. The terminal solver
                # facts travel in a separate attempt-scoped context file.
                (directory / "extraction-context.json").write_text(
                    store.encoded(
                        {
                            "solver_outcome": row["solver"],
                            "failure_reason": row.get("diagnostic") or "",
                        }
                    ),
                    encoding="utf-8",
                )
                # The extractor publishes every member into one private attempt
                # directory; the live run directory is never modified.
                attempt = store.new_id()
                candidate = interchange.attempt_directory(directory, attempt)
                os.environ[interchange.ATTEMPT_ENV] = attempt
                try:
                    code = monitor(
                        jid,
                        owner,
                        directory,
                        lambda stream: launcher.start_extraction(
                            launcher.configured_launcher(), directory, stream
                        ),
                        "extract.log",
                        scope="extraction",
                    )
                finally:
                    os.environ.pop(interchange.ATTEMPT_ENV, None)
                store.update(jid, owner, extraction_exit=code)
                if code:
                    raise ValueError("ODB extraction failed. See extract.log.")
                if not candidate.is_dir():
                    raise ValueError("The extractor did not publish a result generation.")
                try:
                    index, _manifest = interchange.validate_published_generation(candidate)
                except Exception:
                    shutil.rmtree(candidate, ignore_errors=True)
                    raise
                index_path = candidate / "results.json"
            base = directory if legacy else candidate
            if legacy:
                index = json.loads(index_path.read_text(encoding="utf-8"))
            history_only = bool(index.get("history_only"))
            if index["mode"] != row["mode"]:
                raise ValueError("Extractor returned a result for another job mode.")
            if not index["frames"] and not history_only:
                raise ValueError(index.get("diagnostic") or "Extractor returned no frames.")
            if (base / "history.csv").is_file() is False:
                raise ValueError("Extractor returned no history file.")
            for frame in index["frames"]:
                name = frame["file"]
                if not re.fullmatch(r"frame-\d+\.json", name) or not (base / name).is_file():
                    raise ValueError("Extractor returned a missing or invalid frame.")
            checkpoint(jid, "extraction")
            availability = index.get("availability") or "complete"
            expected_generation = int(row.get("result_generation") or 0)
            generation = expected_generation if legacy else expected_generation + 1
            summary = {
                "availability": availability,
                "solver_outcome": index.get("solver_outcome") or row["solver"],
                "extraction_outcome": "Succeeded",
                "failure_reason": index.get("failure_reason") or row.get("diagnostic") or "",
                "last_step": index.get("last_step"),
                "last_step_id": index.get("last_step_id"),
                "last_role": next(
                    (
                        step.get("role")
                        for step in (index.get("steps") or [])
                        if (step.get("id") or step.get("name")) == index.get("last_step_id")
                    ),
                    None,
                ),
                "last_local_s": index.get("last_local_s"),
                "last_total_s": index.get("last_total_s"),
                "frames": len(index.get("frames") or []),
                "history_only": history_only,
                "initial_only": bool(index.get("initial_only")),
                "skipped": len(index.get("skipped_frames") or []),
                "frame_ordinal": index.get("last_frame_ordinal"),
                "native_frame_id": index.get("last_native_frame_id"),
                "increment": index.get("last_increment"),
                "generation": generation,
                "index_sha256": store.digest(index_path),
                "diagnostic": row.get("diagnostic") or "",
            }
            if legacy:
                # Historical DEMO / direct-extractor layout: flat files only.
                fields.update(
                    extraction="Succeeded",
                    phase="Partial results ready"
                    if availability == "partial"
                    else "Results ready",
                    result_state=availability,
                    result_summary=store.encoded(summary),
                    extraction_error="",
                    salvage=0,
                    cancel_scope=None,
                )
            else:
                summary.update(
                    {
                        "result_dir": f"results/gen-{generation}-{attempt}",
                        "manifest_sha256": store.digest(candidate / "manifest.json"),
                    }
                )
                fields.update(
                    phase="Partial results ready"
                    if availability == "partial"
                    else "Results ready",
                )
                log(directory, fields["phase"])
                final_rel = f"results/gen-{generation}-{attempt}"
                final_dir = directory / final_rel
                try:
                    interchange.finalize_generation(candidate, final_dir)
                    # The durable summary travels with the generation so the
                    # directory describes itself even before the DB commit.
                    interchange.write_json(
                        final_dir / "summary.json",
                        {**summary, "attempt": attempt, "generation": generation},
                    )
                except Exception:
                    shutil.rmtree(candidate, ignore_errors=True)
                    shutil.rmtree(final_dir, ignore_errors=True)
                    raise
                members = sorted(
                    set(json.loads(manifest(directory)))
                    | {"results.json", "history.csv"}
                    | {frame["file"] for frame in index["frames"]}
                )
                outcome = store.publish_result_generation(
                    jid,
                    owner,
                    expected_generation,
                    summary,
                    generation,
                    final_rel,
                    availability,
                    members,
                )
                if outcome == "cancelled":
                    shutil.rmtree(final_dir, ignore_errors=True)
                    raise Cancelled()
                if outcome in {"lease", "missing"}:
                    # Another worker owns (or the row vanished): never touch its
                    # pointer from this attempt.
                    shutil.rmtree(final_dir, ignore_errors=True)
                    log(directory, "Result generation fenced: " + outcome)
                    return
                if outcome != "ok":
                    # Generation fencing: keep the previous generation and settle
                    # this attempt as failed without claiming availability.
                    shutil.rmtree(final_dir, ignore_errors=True)
                    log(directory, "Result generation fenced: " + outcome)
                    fields.update(
                        extraction="Failed",
                        extraction_error="The result generation was superseded.",
                        phase="Extraction failed",
                    )
                else:
                    log(directory, "Published result generation %d" % generation)
                    # A historical row kept its old generation only in the flat
                    # files. Preserve that exact set before the mirror moves on.
                    if expected_generation > 0 and not row.get("result_dir"):
                        try:
                            interchange.snapshot_flat(
                                directory,
                                directory / "results" / f"gen-{expected_generation}-legacy",
                            )
                        except Exception as exc:  # noqa: BLE001 - best-effort retention
                            log(directory, "Previous flat generation not preserved: " + str(exc))
                    try:
                        interchange.mirror_flat(directory, final_dir)
                    except Exception as exc:  # noqa: BLE001 - mirror is compatibility only
                        log(directory, "Legacy flat mirror not refreshed: " + str(exc))
                    if row.get("output_dir"):
                        # Auto-package only after the terminal pointer/summary
                        # commit, so its provenance describes the committed
                        # generation.
                        try:
                            from services import portable_files

                            packaged = portable_files.package_job(jid)
                            store.set_publication(jid, packaged["path"], "Saved")
                        except Exception as exc:  # noqa: BLE001 - publication is reported
                            log(directory, "Result file not saved: " + str(exc))
                            store.set_publication(jid, None, "Failed")
                    return

    except ProcessUncertain as exc:
        log(directory, traceback.format_exc())
        store.update(
            jid,
            owner,
            phase="Process termination unconfirmed",
            diagnostic=str(exc),
            manifest=manifest(directory),
        )
        return  # Retain ownership. A replacement worker cannot claim this process.
    except SolverTerminal as exc:
        # The solver fields were recorded before raising; no additional state to
        # invent. A salvageable ODB already queued an extraction-only attempt.
        log(directory, "Terminal solver outcome: " + str(exc))
    except Cancelled:
        if extracting:
            # The attempt never became authoritative: discard its private
            # directory and leave the previous generation untouched.
            if attempt:
                shutil.rmtree(interchange.attempt_directory(directory, attempt), ignore_errors=True)
            shutil.rmtree(directory / interchange.STAGING, ignore_errors=True)
            fields.update(extraction="Cancelled", phase="Extraction cancelled")
        else:
            fields.update(solver="Cancelled", phase="Solver cancelled")
            possible, why = store._candidate_evidence(directory)
            if possible:
                # A verified stop plus a safe candidate: exactly one extraction-
                # only recovery. The final settlement below keeps this state and
                # clears the solver-scope cancellation flag.
                fields.update(
                    extraction="Queued", phase="Awaiting result recovery", salvage=1
                )
            else:
                fields.update(extraction="Pending", salvage=0, diagnostic=why)
                recovery_reason = why
                log(directory, "No result recovery candidate: " + why)
    except Exception as exc:
        log(directory, traceback.format_exc())
        if extracting:
            if attempt:
                shutil.rmtree(interchange.attempt_directory(directory, attempt), ignore_errors=True)
            shutil.rmtree(directory / interchange.STAGING, ignore_errors=True)
            fields.update(
                extraction="Failed",
                extraction_error=preparation_diagnostic(exc),
                phase="Extraction failed",
            )
        else:
            fields.update(
                solver="Failed",
                phase="Preparation or execution failed",
                diagnostic=preparation_diagnostic(exc),
            )
            # A failure after the solver wrote an ODB is still recoverable.
            possible, why = store._candidate_evidence(directory)
            if possible:
                fields.update(
                    extraction="Queued", phase="Awaiting result recovery", salvage=1
                )
            else:
                recovery_reason = why
                log(directory, "No result recovery candidate: " + why)
    log(directory, fields["phase"])
    # Serialize a last-moment cancellation against publishing the terminal state.
    with store.connection(True) as db:
        current = db.execute(
            "SELECT owner,cancelled,result_state FROM jobs WHERE id=?", (jid,)
        ).fetchone()
        if current["owner"] != owner:
            raise store.Conflict("Worker lease lost")
        if current["cancelled"]:
            if extracting and fields.get("extraction") == "Succeeded":
                # Legacy flat extraction only; generation attempts commit through
                # publish_result_generation and return before this block.
                fields.update(cancel_scope=None)
            elif not extracting and fields.get("extraction") == "Queued":
                # The cancel stopped a verified solver and a safe candidate is
                # queued: honour the request by clearing the solver-scope flag so
                # exactly one extraction-only recovery can be claimed.
                fields.update(
                    solver="Cancelled",
                    cancelled=0,
                    cancel_scope=None,
                    phase="Awaiting result recovery",
                )
            else:
                fields.update(
                    {("extraction" if extracting else "solver"): "Cancelled"},
                    phase="Cancelled",
                    cancelled=0,
                )
                if not extracting:
                    fields.update(extraction="Pending", salvage=0)
                    if not fields.get("diagnostic") and recovery_reason:
                        fields["diagnostic"] = recovery_reason
        elif imported is not None and fields.get("solver") == "Succeeded":
            try:
                store.append_revision(
                    db, imported.model_dump(mode="json"), row["project"], row["revision"], jid
                )
            except store.Conflict as exc:
                fields.update(
                    solver="Failed",
                    extraction="Pending",
                    diagnostic=str(exc),
                    phase="Import conflict",
                )
        fields.update(
            owner=None,
            heartbeat=time.time(),
            manifest=manifest(directory),
            ended=None if fields.get("extraction") == "Queued" else time.time(),
        )
        db.execute(
            "UPDATE jobs SET " + ",".join(key + "=?" for key in fields) + " WHERE id=?",
            (*fields.values(), jid),
        )


def once(owner):
    row = store.claim(owner)
    if row:
        with pulse(row["id"], owner):
            perform(row, owner)
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--stop-file", type=Path)
    args = parser.parse_args()
    store.initialize()
    # Hold the worker role for the whole process lifetime. If a supervisor crash
    # leaves this worker behind, the OS lock keeps a replacement pair out until
    # it exits, instead of letting two workers claim one queue.
    try:
        store.claim_worker_root(os.getpid())
    except store.Conflict as error:
        print(f"Abaqus QOL worker: {error}", flush=True)
        raise SystemExit(2) from None
    owner = f"{socket.gethostname()}:{os.getpid()}:{store.new_id()}"
    try:
        while not (args.stop_file and args.stop_file.exists()):
            claimed = once(owner)
            if args.once:
                return
            if not claimed:
                time.sleep(0.35)
    finally:
        store.release_worker_root(os.getpid())


if __name__ == "__main__":
    main()
