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

from integrations import drawings
from packages import engineering
from packages.engineering.model import Project
from integrations.abaqus import deck, launcher, results
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
}


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


def checkpoint(jid):
    if store.job(jid)["cancelled"]:
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


def monitor(jid, owner, directory, start, filename, solving=False):
    with (directory / filename).open("ab", buffering=0) as stream:
        process = start(stream)
        try:
            try:
                birth = psutil.Process(process.pid).create_time()
            except psutil.NoSuchProcess:
                birth = None
            store.update(jid, owner, pid=process.pid, process_started=birth)
            while process.poll() is None:
                checkpoint(jid)
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
    try:
        checkpoint(jid)
        setup = Project.model_validate(store.revision(row["revision"])["setup"])
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
                source = drawings.convert(source)
            imported = engineering.import_dxf(source, setup.name, metadata["units"])
            imported.source.filename = metadata["filename"]
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
                    raise ValueError(reason)
            checkpoint(jid)
            fields.update(solver="Succeeded", extraction="Queued", phase="Awaiting extraction")
        else:
            previous_index = directory / "results.json"
            if previous_index.exists():
                previous_index.rename(directory / ("prior-index-" + store.new_id() + ".json"))
            mesh = json.loads((directory / "mesh.json").read_text(encoding="utf-8"))
            metadata_path = directory / "result-metadata.json"
            fixture_labels = row["fixture_labels"]
            if fixture_labels is None and metadata_path.is_file():
                fixture_labels = (
                    json.loads(metadata_path.read_text(encoding="utf-8")).get("fixture") or {}
                ).get("nodes")
            if row["mode"] == "DEMO":
                if (
                    row["scenario"] == "extraction_failure"
                    and not (directory / "demo-retry").exists()
                ):
                    (directory / "demo-retry").touch()
                    raise ValueError(
                        "Requested one-time extraction failure. Retry extraction to recover."
                    )
                results.write_demo(setup, mesh, directory, fixture_labels)
            else:
                results.write_metadata(setup, mesh, directory, fixture_labels)
                code = monitor(
                    jid,
                    owner,
                    directory,
                    lambda stream: launcher.start_extraction(
                        launcher.configured_launcher(), directory, stream
                    ),
                    "extract.log",
                )
                store.update(jid, owner, extraction_exit=code)
                if code:
                    raise ValueError("ODB extraction failed. See extract.log.")
            index = json.loads((directory / "results.json").read_text(encoding="utf-8"))
            if (
                index["mode"] != row["mode"]
                or not index["frames"]
                or not (directory / "history.csv").is_file()
            ):
                raise ValueError("Extractor returned an invalid result manifest.")
            for frame in index["frames"]:
                name = frame["file"]
                if not re.fullmatch(r"frame-\d+\.json", name) or not (directory / name).is_file():
                    raise ValueError("Extractor returned a missing or invalid frame.")
            checkpoint(jid)
            fields.update(extraction="Succeeded", phase="Results ready")
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
    except Cancelled:
        fields.update({("extraction" if extracting else "solver"): "Cancelled"}, phase="Cancelled")
    except Exception as exc:
        log(directory, traceback.format_exc())
        fields.update(
            {("extraction" if extracting else "solver"): "Failed"},
            phase="Extraction failed" if extracting else "Preparation or execution failed",
            diagnostic=str(exc) or type(exc).__name__,
        )
    log(directory, fields["phase"])
    # Serialize a last-moment cancellation against publishing the terminal state.
    with store.connection(True) as db:
        current = db.execute("SELECT owner,cancelled FROM jobs WHERE id=?", (jid,)).fetchone()
        if current["owner"] != owner:
            raise store.Conflict("Worker lease lost")
        if current["cancelled"]:
            fields.update(
                {("extraction" if extracting else "solver"): "Cancelled"}, phase="Cancelled"
            )
            if not extracting:
                fields["extraction"] = "Pending"
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
    owner = f"{socket.gethostname()}:{os.getpid()}:{store.new_id()}"
    while not (args.stop_file and args.stop_file.exists()):
        claimed = once(owner)
        if args.once:
            return
        if not claimed:
            time.sleep(0.35)


if __name__ == "__main__":
    main()
