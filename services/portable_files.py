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
from packages.engineering import fixture as fixture_rules
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


def _restore_source(members: dict[str, bytes], setup: dict) -> dict:
    """Restore the embedded original drawing, if any, under a new source id.

    The original bytes are copied unchanged; the source id is new so no existing
    model's drawing directory is shared or modified.
    """
    name = next((key for key in members if key.startswith("drawing/")), None)
    if name is None:
        return {"status": "absent", "source_id": None}
    payload = members[name]
    if not payload:
        return {"status": "invalid", "source_id": None}
    filename = Path(name).name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".dxf", ".dwg"} or not filename.startswith("drawing"):
        return {"status": "invalid", "source_id": None}
    source_id = store.new_id()
    directory = store.root() / "drawings" / source_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_bytes(payload)
    source = setup.get("source") or {}
    (directory / "source.json").write_text(
        store.encoded(
            {
                "filename": source.get("filename") or filename,
                "units": source.get("unit_basis") or "N-mm-s-tonne",
                "restored_from_file": True,
            }
        ),
        encoding="utf-8",
    )
    return {"status": "restored", "source_id": source_id}


def _restore_mesh(
    members: dict[str, bytes], compat: str
) -> tuple[dict, dict, list[dict]]:
    """Validate the embedded mesh and fixture without trusting either.

    Returns ``(mesh, fixture, items)``. A member that does not match its own
    recorded identity, the reopened setup's mesh inputs, or its digest is
    reported for regeneration instead of being adopted; a fixture is restored
    only against the exact mesh bytes it was reviewed on.
    """
    items: list[dict] = []
    raw = members.get("mesh.json")
    if raw is None:
        return (
            {"status": "absent", "digest": None, "artifact": None},
            {"status": "absent", "labels": None},
            items,
        )
    try:
        artifact = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        items.append(
            {
                "code": "portable.mesh_unreadable",
                "stage": "mesh",
                "detail": "The embedded mesh is not valid JSON. Generate the mesh again.",
            }
        )
        return (
            {"status": "invalid", "digest": None, "artifact": None},
            {"status": "invalid", "labels": None},
            items,
        )
    if (
        not isinstance(artifact, dict)
        or not artifact.get("nodes")
        or not artifact.get("elements")
    ):
        items.append(
            {
                "code": "portable.mesh_empty",
                "stage": "mesh",
                "detail": "The embedded mesh has no nodes or elements. Generate the mesh again.",
            }
        )
        return (
            {"status": "invalid", "digest": None, "artifact": None},
            {"status": "invalid", "labels": None},
            items,
        )
    digest = sha256(raw).hexdigest()
    identity_raw = members.get("mesh-identity.json")
    if identity_raw is None:
        items.append(
            {
                "code": "portable.mesh_identity_missing",
                "stage": "mesh",
                "detail": "The embedded mesh has no identity record, so it cannot be trusted. "
                "Generate the mesh again.",
            }
        )
        return (
            {"status": "invalid", "digest": digest, "artifact": None},
            {"status": "invalid", "labels": None},
            items,
        )
    try:
        identity = json.loads(identity_raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        identity = {}
    if not isinstance(identity, dict) or identity.get("digest") != digest:
        items.append(
            {
                "code": "portable.mesh_identity_mismatch",
                "stage": "mesh",
                "detail": "The embedded mesh does not match its own digest record. "
                "Generate the mesh again.",
            }
        )
        return (
            {"status": "invalid", "digest": digest, "artifact": None},
            {"status": "invalid", "labels": None},
            items,
        )
    if identity.get("compat") != compat:
        items.append(
            {
                "code": "portable.mesh_incompatible",
                "stage": "mesh",
                "detail": "The embedded mesh was generated for different mesh inputs than this "
                "model. Generate the mesh again.",
            }
        )
        return (
            {"status": "incompatible", "digest": digest, "artifact": None},
            {"status": "invalid", "labels": None},
            items,
        )
    mesh = {"status": "restored", "digest": digest, "artifact": artifact}
    raw_fixture = members.get("fixture.json")
    if raw_fixture is None:
        return mesh, {"status": "absent", "labels": None}, items
    try:
        packaged = json.loads(raw_fixture.decode("utf-8"))
        labels = packaged["labels"]
        recorded_hash = packaged.get("hash")
        recorded_mesh = packaged.get("mesh_digest")
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        labels = recorded_hash = recorded_mesh = None
    try:
        if recorded_mesh != digest:
            raise ValueError("The fixed nodes were reviewed on different mesh bytes.")
        normalized = fixture_rules.normalize(labels, artifact)
        if not normalized or fixture_rules.labels_hash(normalized) != recorded_hash:
            raise ValueError("The fixed-node list does not match its recorded hash.")
    except ValueError as exc:
        items.append(
            {
                "code": "portable.fixture_invalid",
                "stage": "mounting",
                "detail": f"{exc} Review the fixed nodes on the regenerated mesh.",
            }
        )
        return mesh, {"status": "invalid", "labels": None}, items
    return mesh, {"status": "restored", "labels": normalized}, items


def open_model(path: str) -> dict:
    container = portable.read_container(Path(path), portable.MODEL_KIND)
    members = container["members"]
    try:
        setup = json.loads(members["model.json"].decode("utf-8"))
    except ValueError as exc:
        raise portable.PortableError("model-json", "The model contents are not valid JSON.") from exc
    try:
        project = Project.model_validate(setup)
    except ValueError as exc:
        raise portable.PortableError("model-invalid", f"The model contents are invalid: {exc}") from exc
    canonical = project.model_dump(mode="json")
    compat = mesh_compat(project)
    source = _restore_source(members, canonical)
    mesh, fixture_restore, items = _restore_mesh(members, compat)
    saved = store.save(canonical, source_id=source["source_id"])
    if mesh["status"] == "restored":
        store.import_mesh_job(
            saved["id"],
            mesh["digest"],
            compat,
            members,
            fixture_restore["labels"]
            and {
                "labels": fixture_restore["labels"],
                "hash": fixture_rules.labels_hash(fixture_restore["labels"]),
            },
        )
    return {
        "revision": saved["id"],
        "project": saved["project"],
        "name": saved["setup"]["name"],
        "manifest": container["manifest"],
        "mesh": mesh["status"],
        "fixture": fixture_restore["status"],
        "source": source["status"],
        "items": items,
    }


def _export_name(revision: dict, job: dict, partial: bool = False) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    model = _safe_name(revision["setup"].get("name", "model"), "model")
    run = _safe_name(job.get("name", "run"), "run")
    suffix = "-partial" if partial else ""
    return f"{model}-{run}-{stamp}-{str(job['id'])[:8]}{suffix}{RESULT_SUFFIX}"


def package_job(job_id: str, folder: str | None = None, allow_running: bool = False) -> dict:
    job = store.job(job_id)
    # The worker calls this before it publishes the terminal row, so it asserts
    # the extraction outcome itself through ``allow_running``.
    if job["mode"] not in {"ABAQUS"}:
        raise portable.PortableError(
            "not-completed", "A result file is written only for an Abaqus analysis."
        )
    if not allow_running:
        # Availability is a validated generation fact, not a status guess: a
        # failed solver with a usable partial index may be exported.
        if job.get("extraction") != "Succeeded":
            raise portable.PortableError(
                "extraction",
                "The result extraction did not succeed; the result file is not published.",
            )
        if job.get("result_state") not in {"partial", "complete"}:
            raise portable.PortableError(
                "not-completed", "No validated result generation is available to export."
            )
    directory = store.job_dir(job_id)
    index_path = directory / "results.json"
    if not index_path.is_file():
        raise portable.PortableError("missing-index", "The result index is missing.")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    availability = index.get("availability") or "complete"
    target_folder = Path(folder or job.get("output_dir") or "")
    if not str(target_folder):
        raise portable.PortableError(
            "no-folder", "Choose an output folder before submitting, or pass one now."
        )
    if not target_folder.is_dir():
        raise portable.PortableError("folder", "The output folder is not available.")
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
        "result": {
            "availability": availability,
            "solver_outcome": index.get("solver_outcome") or job.get("solver"),
            "failure_reason": index.get("failure_reason") or job.get("diagnostic") or "",
            "last_step": index.get("last_step"),
            "last_step_id": index.get("last_step_id"),
            "last_local_s": index.get("last_local_s"),
            "last_total_s": index.get("last_total_s"),
            "frame_ordinal": index.get("last_frame_ordinal"),
            "frames": len(index.get("frames") or []),
            "history_only": bool(index.get("history_only")),
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
        target_folder / _export_name(revision, job, availability == "partial"),
        portable.RESULT_KIND,
        members,
        {
            "name": job["name"],
            "job": job["id"],
            "revision": revision["id"],
            "availability": availability,
        },
    )
    store.set_publication(job_id, result["path"], "Saved")
    result["availability"] = availability
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
    availability = index.get("availability") or provenance.get("result", {}).get(
        "availability"
    ) or "complete"
    if not index.get("frames") and not index.get("history_only"):
        raise portable.PortableError("result-empty", "The result file has no frames.")
    revision = store.save(Project.model_validate(setup).model_dump(mode="json"))
    job = store.import_result_job(
        revision["id"],
        provenance.get("job", {}).get("name") or revision["setup"].get("name", "Imported result"),
        members,
        provenance,
        availability="partial" if availability == "partial" else "complete",
    )
    return {
        "job": job,
        "path": str(Path(path)),
        "manifest": container["manifest"],
        "availability": availability,
    }
