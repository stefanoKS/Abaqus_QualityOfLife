"""Portable file workflow: model and result containers on disk.

The database remains the queue and artifact store; these functions only read a
revision/job snapshot and write, or validate and re-open, a portable file. They
never resubmit a solve, never overwrite a submitted artifact and never depend on
an absolute path recorded in another installation.
"""

from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import re

from packages.engineering import portable
from packages.engineering.identity import mesh_compat
from packages.engineering.model import Project
from services import store

MODEL_SUFFIX = ".aqmodel"
RESULT_SUFFIX = ".aqresult"


def _safe_name(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", (value or "").strip()).strip("-._")
    return cleaned[:60] or fallback


def _file_digest(path: Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def _source_payload(revision: dict) -> dict:
    setup = revision["setup"]
    source = dict(setup.get("source") or {})
    payload = {
        "source": source,
        "revision": {
            "id": revision["id"],
            "number": revision["number"],
            "created": revision["created"],
        },
    }
    source_id = revision.get("source_id")
    if source_id:
        drawing = store.root() / "drawings" / str(source_id)
        if drawing.is_dir():
            for path in sorted(drawing.iterdir()):
                if path.is_file() and path.name.startswith("drawing"):
                    payload["drawing"] = {
                        "name": path.name,
                        "sha256": _file_digest(path),
                        "data": path.read_bytes(),
                    }
    return payload


def model_members(revision_id: str) -> dict[str, bytes]:
    revision = store.revision(revision_id)
    setup = revision["setup"]
    source = _source_payload(revision)
    drawing = source.pop("drawing", None)
    members = portable.model_container(setup, source, None, None)
    if drawing:
        members["drawing/" + drawing["name"]] = drawing["data"]
    # The compatible completed mesh and its reviewed fixture travel with the model
    # only while they are still reusable for this exact setup.
    project = Project.model_validate(setup)
    compat = mesh_compat(project)
    meshes = [
        job
        for job in store.jobs(("MESH",))
        if job["revision"] == str(revision_id) and job.get("mesh_compat") == compat
    ]
    if meshes:
        mesh = meshes[0]
        directory = store.job_dir(mesh["id"])
        artifact = directory / "mesh.json"
        if mesh["status"] == "Completed" and artifact.is_file():
            members["mesh.json"] = artifact.read_bytes()
            identity = directory / "mesh-identity.json"
            if identity.is_file():
                members["mesh-identity.json"] = identity.read_bytes()
            fixture = store.fixture(mesh["id"])
            if fixture:
                members["fixture.json"] = json.dumps(
                    {
                        "labels": fixture["labels"],
                        "hash": fixture["hash"],
                        "mesh_digest": fixture["mesh_digest"],
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
    return members


def save_model(
    revision_id: str,
    path: str,
    base_sha: str | None = None,
    overwrite: bool = False,
) -> dict:
    target = Path(path)
    if target.suffix.lower() != MODEL_SUFFIX:
        raise portable.PortableError("suffix", f"Model files use the {MODEL_SUFFIX} extension.")
    current = _file_digest(target) if target.is_file() else None
    if current is not None:
        if not overwrite and (base_sha is None or base_sha != current):
            raise portable.PortableError(
                "changed-on-disk",
                "The file on disk differs from the version this session saved. "
                "Overwrite it explicitly or choose Save As.",
            )
    revision = store.revision(revision_id)
    members = model_members(revision_id)
    result = portable.write_container(
        target,
        portable.MODEL_KIND,
        members,
        {
            "name": revision["setup"].get("name", ""),
            "revision": revision["id"],
            "number": revision["number"],
            "api": 3,
        },
    )
    result["revision"] = revision_id
    return result


def open_model(path: str) -> dict:
    container = portable.read_container(Path(path), portable.MODEL_KIND)
    try:
        setup = json.loads(container["members"]["model.json"].decode("utf-8"))
    except ValueError as exc:
        raise portable.PortableError("model-json", "The model contents are not valid JSON.") from exc
    try:
        project = Project.model_validate(setup)
    except ValueError as exc:
        raise portable.PortableError("model-invalid", f"The model contents are invalid: {exc}") from exc
    saved = store.save(project.model_dump(mode="json"))
    return {
        "revision": saved["id"],
        "project": saved["project"],
        "name": saved["setup"]["name"],
        "manifest": container["manifest"],
        "mesh": "mesh.json" in container["members"],
        "fixture": "fixture.json" in container["members"],
        "source": "drawing" in "".join(container["members"]),
    }


def _export_name(revision: dict, job: dict) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    model = _safe_name(revision["setup"].get("name", "model"), "model")
    run = _safe_name(job.get("name", "run"), "run")
    return f"{model}-{run}-{stamp}-{str(job['id'])[:8]}{RESULT_SUFFIX}"


def package_job(job_id: str, folder: str | None = None, allow_running: bool = False) -> dict:
    job = store.job(job_id)
    # The worker calls this before it publishes the terminal row, so it asserts
    # the extraction outcome itself through ``allow_running``.
    if job["mode"] not in {"ABAQUS"} or (not allow_running and job["status"] != "Completed"):
        raise portable.PortableError(
            "not-completed", "A result file is written only after a completed extraction."
        )
    if not allow_running and job.get("extraction") != "Succeeded":
        raise portable.PortableError(
            "extraction", "The solver finished but extraction did not; the result file is not published."
        )
    target_folder = Path(folder or job.get("output_dir") or "")
    if not str(target_folder):
        raise portable.PortableError(
            "no-folder", "Choose an output folder before submitting, or pass one now."
        )
    if not target_folder.is_dir():
        raise portable.PortableError("folder", "The output folder is not available.")
    directory = store.job_dir(job_id)
    index_path = directory / "results.json"
    if not index_path.is_file():
        raise portable.PortableError("missing-index", "The result index is missing.")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    frames = {}
    for frame in index.get("frames", []):
        name = frame.get("file", "")
        path = directory / name
        if not re.fullmatch(r"frame-\d+\.json", name) or not path.is_file():
            raise portable.PortableError("frame", f"Result frame {name!r} is missing.")
        frames[name] = path.read_bytes()
    history = directory / "history.csv"
    revision = store.revision(job["revision"])
    provenance = {
        "job": {
            "id": job["id"],
            "name": job["name"],
            "mode": job["mode"],
            "created": job["created"],
            "ended": job.get("ended"),
            "solver": job.get("solver"),
            "extraction": job.get("extraction"),
            "input_hash": job.get("input_hash"),
        },
        "revision": {
            "id": revision["id"],
            "number": revision["number"],
            "source_id": revision.get("source_id"),
        },
        "artifacts": {
            "results": _file_digest(index_path),
            "history": _file_digest(history) if history.is_file() else None,
            "frames": {name: sha256(payload).hexdigest() for name, payload in frames.items()},
        },
    }
    members = portable.result_container(
        revision["setup"],
        index,
        history.read_bytes() if history.is_file() else b"",
        frames,
        provenance,
    )
    result = portable.write_container(
        target_folder / _export_name(revision, job),
        portable.RESULT_KIND,
        members,
        {"name": job["name"], "job": job["id"], "revision": revision["id"]},
    )
    store.set_publication(job_id, result["path"], "Saved")
    return result


def open_result(path: str) -> dict:
    container = portable.read_container(Path(path), portable.RESULT_KIND)
    members = container["members"]
    try:
        setup = json.loads(members["setup.json"].decode("utf-8"))
        index = json.loads(members["results.json"].decode("utf-8"))
        provenance = json.loads(members["provenance.json"].decode("utf-8"))
    except (KeyError, ValueError) as exc:
        raise portable.PortableError("result-json", "The result contents are not valid JSON.") from exc
    if not index.get("frames"):
        raise portable.PortableError("result-empty", "The result file has no frames.")
    revision = store.save(Project.model_validate(setup).model_dump(mode="json"))
    job = store.import_result_job(
        revision["id"],
        provenance.get("job", {}).get("name") or revision["setup"].get("name", "Imported result"),
        members,
        provenance,
    )
    return {
        "job": job,
        "path": str(Path(path)),
        "manifest": container["manifest"],
    }
