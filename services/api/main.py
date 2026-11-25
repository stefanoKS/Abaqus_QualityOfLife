import json
import os
import re
import subprocess
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from integrations import dwg, drawings
from packages import engineering
from packages.engineering.model import Project
from services import activity, material_library, portable_files, readiness, release, store
from .contracts import (
    Build,
    CaeExportRequest,
    Deck,
    DeleteConfirm,
    DeletionInfo,
    DeletionResult,
    DuplicateModel,
    Fixture,
    FixtureInfo,
    GroupCreated,
    GroupSummary,
    Job,
    LibraryCreate,
    LibraryDetail,
    LibraryDuplicate,
    LibrarySummary,
    LibraryUpdate,
    MaterialImportRequest,
    MaterialImportResult,
    ModelFileRequest,
    NewGroup,
    NewProject,
    NewProjectGroup,
    OpenFileRequest,
    PackageResultRequest,
    PartitionApply,
    PartitionPreview,
    Revision,
    RevisionSummary,
    ResultFileRetry,
    Save,
    Submit,
    Summary,
)

MAX_DRAWING = 8 * 1024 * 1024
STARTED = time.time()

API_VERSION = 3
CAPABILITIES_VERSION = 2
WRITE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "apps" / "web"
_DIST_OVERRIDE = os.environ.get("ABAQUS_QOL_WEB_DIST", "").strip()
RELEASE = release.resolve(WEB, Path(_DIST_OVERRIDE) if _DIST_OVERRIDE else None)
PORT = int(os.environ.get("ABAQUS_QOL_PORT", "0") or 0)


def _fingerprint():
    """Digest of the running Python sources and the exact release being served.

    The release directory is content-addressed and immutable, so a build that
    happens while this instance is running cannot change this digest or the
    files this instance serves.
    """
    from hashlib import sha256

    entries = []
    for folder in ("services", "packages", "integrations"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            stat = path.stat()
            entries.append(f"{path.relative_to(ROOT).as_posix()}:{stat.st_size}:{stat.st_mtime_ns}")
    if RELEASE.directory.is_dir():
        for path in sorted(RELEASE.directory.rglob("*")):
            if path.is_file():
                entries.append(
                    f"release/{path.relative_to(RELEASE.directory).as_posix()}:"
                    f"{path.stat().st_size}"
                )
    return sha256("\n".join(entries).encode("utf-8")).hexdigest()[:16], RELEASE.entry


def _git_head():
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


BUILD, FRONTEND = _fingerprint()
GIT = _git_head()




def revision_payload(row):
    """Attach the mesh-compatibility digest so the browser can decide mesh reuse.

    The validated setup is returned, not the raw stored dictionary, so additive
    defaults (including the door-pressure output plan) are visible to the
    editor on a revision saved before those fields existed.
    """
    project = Project.model_validate(row["setup"])
    return {
        **row,
        "setup": project.model_dump(mode="json"),
        "mesh_compat": engineering.mesh_compat(project),
    }


def assert_editable(pid):
    """Archived models/groups stay readable but cannot change or queue work."""
    if store.project_locked(str(pid)):
        raise store.Conflict(
            "This model is archived. Restore it before changing its setup or starting new work."
        )


def mesh_artifact(jid):
    path = store.job_dir(jid) / "mesh.json"
    if not path.is_file():
        raise store.Conflict("This mesh job has no stored mesh artifact.")
    return json.loads(path.read_text(encoding="utf-8"))


@asynccontextmanager
async def lifespan(_):
    store.initialize()
    # One API/worker pair owns a data directory. A second instance on another
    # port with the same SEAL_DATA would share a queue and an artifact tree, so
    # it is refused before any job can be claimed.
    store.claim_data_root(os.getpid(), PORT, RELEASE.id)
    # No synthetic model is seeded: a clean installation opens an empty dashboard
    # and every model starts at Import with no drawing.
    try:
        yield
    finally:
        store.release_data_root(os.getpid())


app = FastAPI(title="Abaqus QOL", version="0.2.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])


@app.middleware("http")
async def local_writes(request: Request, call_next):
    if request.method in WRITE_METHODS:
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).hostname not in {"localhost", "127.0.0.1", "::1"}:
            return JSONResponse(
                {"detail": "This workbench accepts local browser requests only."}, 403
            )
        # A tab that identifies itself is checked against this instance. An
        # unidentified client (scripts, tests, older releases) keeps the old
        # contract; our own browser always identifies itself.
        client_api = request.headers.get("x-abaqus-qol-api", "")
        client_entry = request.headers.get("x-abaqus-qol-client", "")
        if client_api.isdigit() and int(client_api) != API_VERSION:
            return JSONResponse(
                {
                    "detail": "This browser build does not match the running API. "
                    "Close Abaqus QOL and start it again from start-abaqus-qol.cmd.",
                    "code": "compatibility.api_mismatch",
                },
                409,
            )
        if client_entry and client_entry not in {RELEASE.entry, "dev"}:
            return JSONResponse(
                {
                    "detail": "This browser tab is from a different release than the "
                    "running API. Reload the page.",
                    "code": "compatibility.stale_tab",
                },
                409,
            )
        length = request.headers.get("content-length", "")
        if not length.isdigit() or int(length) > MAX_DRAWING + 1024 * 1024:
            return JSONResponse(
                {"detail": "Request exceeds the local upload limit or lacks a length."}, 413
            )
    return await call_next(request)


@app.exception_handler(KeyError)
async def missing(_, exc):
    return JSONResponse({"detail": str(exc.args[0])}, 404)


@app.exception_handler(ValueError)
async def invalid(_, exc):
    return JSONResponse({"detail": str(exc)}, 409 if isinstance(exc, store.Conflict) else 422)


@app.get("/api/health")
def health():
    """Identifiable readiness probe used by the launcher and instance reuse.

    ``build`` fingerprints the Python sources that are actually running and the
    built frontend asset, so an uncommitted build is distinguishable from a
    released one and a stale process can never be mistaken for the current code.
    """
    return {
        "product": "Abaqus QOL",
        "status": "ready",
        "version": app.version,
        "pid": os.getpid(),
        "started": STARTED,
        "api": API_VERSION,
        "capabilities": CAPABILITIES_VERSION,
        "build": BUILD,
        "git": GIT,
        # The exact browser release this instance pinned at startup. A later
        # build publishes a new release; it cannot change these values.
        **RELEASE.as_health(),
        "data": store.data_identity(),
    }


@app.get("/api/capabilities")
def capabilities():
    """What the running services can actually do, with the reason when they cannot."""
    from integrations import dwg
    from integrations.abaqus import launcher

    result = {}
    try:
        found = launcher.resolve_launcher()
        result["abaqus"] = "Configured"
        result["abaqusPath"] = found["path"]
        result["abaqusSource"] = found["source"]
        result["abaqusDetail"] = found["detail"]
    except (ValueError, OSError) as exc:
        result["abaqus"] = str(exc)
        result["abaqusPath"] = ""
        result["abaqusSource"] = "unavailable"
        result["abaqusDetail"] = str(exc)
    reader = dwg.status()
    result["dwg"] = "Configured" if reader["ready"] else reader["message"]
    result["dwgReader"] = reader["label"]
    result["dwgHelper"] = reader["helper"]
    result["dwgMissing"] = reader["missing"]
    result["odaRequired"] = False
    result["schemaVersion"] = CAPABILITIES_VERSION
    return result


@app.get("/api/materials", response_model=list[LibrarySummary])
def materials(query: str = "", include_archived: bool = False):
    """Global material library, with immutable version history per material."""
    return material_library.list_materials(query, include_archived)


@app.post("/api/materials", response_model=LibraryDetail, status_code=201)
def create_material(body: LibraryCreate):
    body.card.checked(body.name)
    return material_library.create(
        body.name, body.card.model_dump(mode="json"), body.note
    )


@app.post("/api/materials/import", response_model=list[MaterialImportResult])
def import_materials(body: MaterialImportRequest):
    """Explicitly import selected model-local cards; never merge by name."""
    return material_library.import_from_revision(body.revision, body.material_ids)


@app.get("/api/materials/{mid}", response_model=LibraryDetail)
def material(mid: str):
    return material_library.get(mid)


@app.put("/api/materials/{mid}", response_model=LibraryDetail)
def update_material(mid: str, body: LibraryUpdate):
    if body.card is not None:
        body.card.checked(body.name or "Library material")
    return material_library.update(
        mid,
        body.name,
        body.card.model_dump(mode="json") if body.card is not None else None,
        body.note,
    )


@app.post("/api/materials/{mid}/duplicate", response_model=LibraryDetail, status_code=201)
def duplicate_material(mid: str, body: LibraryDuplicate = LibraryDuplicate()):
    return material_library.duplicate(mid, body.name)


@app.post("/api/materials/{mid}/archive", response_model=LibraryDetail)
def archive_material(mid: str):
    return material_library.set_archived(mid, True)


@app.post("/api/materials/{mid}/restore", response_model=LibraryDetail)
def restore_material(mid: str):
    return material_library.set_archived(mid, False)


# ---------------------------------------------------- CAE material library I/O


def _cae_source_path(digest: str) -> Path:
    folder = store.root() / "material-library"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (digest + ".lib")


def _read_cae_upload(data: bytes):
    from packages.engineering import abaqus_lib

    try:
        library = abaqus_lib.parse(data)
    except abaqus_lib.LibraryError as exc:
        raise ValueError(str(exc)) from exc
    return library


@app.post("/api/material-library/cae/preview")
async def preview_cae_library(file: UploadFile = File(...)):
    """Decode an uploaded CAE library without executing or registering anything."""
    data = await file.read()
    library = _read_cae_upload(data)
    from packages.engineering import abaqus_lib

    cards = []
    for card in library.cards:
        entry = card.describe()
        entry["assessment"] = abaqus_lib.assessment(card)
        # The historical key name stays for older clients; it now describes the
        # run suitability of the record, not whether it may be registered.
        entry["eligibility"] = entry["assessment"]
        cards.append(entry)
    return {
        "file": file.filename or "library.lib",
        "sha256": library.fingerprint,
        "bytes": library.size,
        "containers": library.containers,
        "cards": cards,
        "registrable": sum(1 for entry in cards if entry["assessment"]["registrable"]),
        "available": sum(1 for entry in cards if entry["assessment"]["available"]),
        "eligible": sum(1 for entry in cards if entry["assessment"]["available"]),
    }


def _cae_card_payload(decision: dict, color: str, family: str) -> dict:
    """The stored card for one registered record, faithful to its source."""
    elastic = decision.get("elastic") or {}
    payload = {
        "model": decision["model"],
        "color": color,
        "density": decision["density"],
        "young": elastic.get("young"),
        "poisson": elastic.get("poisson"),
        "c10": None,
        "d1": None,
        "test_data": [],
        "family": family,
        "hyperfoam": None,
        "hyperelastic": None,
        "viscoelastic": None,
        "plastic": None,
        "mullins": None,
        "thermal": None,
    }
    for block in ("hyperfoam", "hyperelastic", "viscoelastic", "plastic", "mullins", "thermal"):
        payload[block] = (decision.get("blocks") or {}).get(block)
    return payload


@app.post("/api/material-library/cae/import")
async def import_cae_library(
    file: UploadFile = File(...),
    keys: str = Form("[]"),
    family: str = Form("polymer"),
    families: str = Form("{}"),
    units: str = Form("N-mm-s-tonne"),
):
    """Register every well-formed selected record with its full source data.

    Registering and running are separate: a record whose source omits a density,
    or whose law this phase cannot emit, is still registered and visible, and
    carries the precise missing input. ``families`` lets a mixed import declare
    the engineering family per card; the per-card hint is a default only.
    """
    data = await file.read()
    library = _read_cae_upload(data)
    from packages.engineering import abaqus_lib

    if units != "N-mm-s-tonne":
        raise ValueError(
            "This application stores N-mm-s-tonne data. Declare that basis for the library."
        )
    if family not in ("polymer", "metal"):
        raise ValueError("Declare the structural family (polymer or metal) for the imported cards.")
    try:
        wanted = [str(key) for key in json.loads(keys)]
    except ValueError as exc:
        raise ValueError("The selected card list is not valid JSON.") from exc
    try:
        declared = json.loads(families or "{}")
    except ValueError as exc:
        raise ValueError("The per-card family declaration is not valid JSON.") from exc
    if not isinstance(declared, dict) or any(
        value not in ("polymer", "metal") for value in declared.values()
    ):
        raise ValueError("Each declared family must be polymer or metal.")
    chosen = [card for card in library.cards if card.key in set(wanted)]
    if not chosen:
        raise ValueError("Select at least one card to import.")
    _cae_source_path(library.fingerprint).write_bytes(data)
    existing = material_library.list_materials(include_archived=True)
    by_record: dict[str, list[dict]] = {}
    for entry in existing:
        detail = material_library.get(entry["id"])
        for version in reversed(detail.get("versions", [])):
            source = version.get("source") or {}
            if source.get("sha256") == library.fingerprint and source.get("record"):
                by_record.setdefault(source["record"], []).append(detail)
    registered, skipped, conflicts = [], [], []
    palette = ["#46ad94", "#dc9b50", "#5b8def", "#b06ad4", "#d45b5b", "#7a8a99"]
    for card in chosen:
        decision = abaqus_lib.assessment(card)
        if not decision["registrable"]:
            skipped.append(
                {
                    "key": card.key,
                    "name": card.name,
                    "reasons": decision["reasons"],
                    "needs": decision["needs"],
                }
            )
            continue
        card_family = declared.get(card.key) or (
            family if len(chosen) == 1 else decision["family_hint"]
        )
        payload = _cae_card_payload(
            decision, palette[len(registered) % len(palette)], card_family
        )
        try:
            from services.api.contracts import MaterialCard

            MaterialCard.model_validate(payload).checked(card.name)
        except ValueError as exc:
            skipped.append(
                {
                    "key": card.key,
                    "name": card.name,
                    "reasons": [{"code": "cae.card_invalid", "detail": str(exc)}],
                    "needs": decision["needs"],
                }
            )
            continue
        canonical = material_library.canonical_card(payload)
        same = next(
            (
                detail
                for detail in by_record.get(card.key, [])
                if material_library.canonical_card(detail["card"]) == canonical
            ),
            None,
        )
        if same is not None:
            registered.append(
                {
                    "key": card.key,
                    "library_id": same["id"],
                    "version": same["current_version"],
                    "existing": True,
                    "available": decision["available"],
                    "needs": decision["needs"],
                }
            )
            continue
        same_name = [
            entry for entry in existing if entry["name"].casefold() == card.name.casefold()
        ]
        name = card.name
        if same_name:
            # Never merge divergent same-name cards; make the difference explicit.
            name = f"{card.name} · {card.fingerprint()[:8]}"
            conflicts.append(
                {
                    "key": card.key,
                    "name": card.name,
                    "existing": [entry["id"] for entry in same_name],
                    "registered_as": name,
                }
            )
        source = {
            "engine": "Abaqus/CAE",
            "file": file.filename or "library.lib",
            "sha256": library.fingerprint,
            "record": card.key,
            "fingerprint": card.fingerprint(),
            "category": card.category,
            "metadata": card.metadata_json(),
            "data": abaqus_lib._jsonable(card.data),
            "units": units,
            "family": card_family,
            "model": decision["model"],
            "available": decision["available"],
            "needs": decision["needs"],
            "reasons": decision["reasons"],
            "exportable": True,
        }
        created = material_library.create(
            name,
            payload,
            f"Imported from {source['file']} ({library.fingerprint[:8]} record {card.key})",
            source=source,
        )
        registered.append(
            {
                "key": card.key,
                "library_id": created["id"],
                "version": created["current_version"],
                "existing": False,
                "available": decision["available"],
                "needs": decision["needs"],
            }
        )
    return {
        "file": file.filename or "library.lib",
        "sha256": library.fingerprint,
        "registered": registered,
        "skipped": skipped,
        "conflicts": conflicts,
        "registrable": sum(
            1 for card in library.cards if abaqus_lib.assessment(card)["registrable"]
        ),
        "source": str(_cae_source_path(library.fingerprint)),
    }


@app.post("/api/material-library/cae/export")
def export_cae_library(body: CaeExportRequest):
    """Write CAE's own bytes to a chosen folder and verify the round-trip.

    The source stream interleaves global memo definitions between records, so a
    subset cannot be rebuilt byte-for-byte. This is therefore explicitly an
    original-file export, named as such, and never presented as the edited card.
    """
    from packages.engineering import abaqus_lib

    folder = body.folder.strip()
    if not folder:
        raise ValueError("Choose a folder for the exported CAE library.")
    target = Path(folder)
    if not target.is_dir():
        raise ValueError("The chosen output folder is not available.")
    wanted = {str(item) for item in body.material_ids}
    sources = material_library.cae_sources()
    if not sources:
        raise ValueError(
            "No CAE-imported material is registered yet. App-created cards have no "
            "CAE source record to export faithfully."
        )
    written, skipped = [], []
    for source in sources:
        selected = sorted(set(source["materials"]).intersection(wanted)) if wanted else []
        if wanted and not selected:
            continue
        path = _cae_source_path(source["sha256"])
        if not path.is_file():
            skipped.append({"sha256": source["sha256"], "reason": "source bytes missing"})
            continue
        library = _read_cae_upload(path.read_bytes())
        stem = Path(source.get("file") or "material-library").stem or "material-library"
        output = target / f"{stem}-original.lib"
        counter = 1
        while output.exists():
            counter += 1
            output = target / f"{stem}-original-{counter}.lib"
        result = abaqus_lib.write_export(library, output)
        result["mode"] = "original-file"
        result["covers"] = selected
        written.append(result)
    if not written and not skipped:
        raise ValueError("The selected materials have no CAE source library to export.")
    return {"files": written, "skipped": skipped, "mode": "original-file"}


@app.post("/api/material-library/cae/export")
def export_cae_library(body: CaeExportRequest):
    """Write the original CAE bytes to a chosen folder and verify the round-trip."""
    from packages.engineering import abaqus_lib

    folder = body.folder.strip()
    if not folder:
        raise ValueError("Choose a folder for the exported CAE library.")
    target = Path(folder)
    if not target.is_dir():
        raise ValueError("The chosen output folder is not available.")
    wanted = {str(item) for item in body.material_ids}
    sources = material_library.cae_sources()
    if not sources:
        raise ValueError(
            "No CAE-imported material is registered yet. App-created cards have no "
            "CAE source record to export faithfully."
        )
    written, skipped = [], []
    for source in sources:
        if wanted and not wanted.intersection(set(source["materials"])):
            continue
        path = _cae_source_path(source["sha256"])
        if not path.is_file():
            skipped.append({"sha256": source["sha256"], "reason": "source bytes missing"})
            continue
        library = _read_cae_upload(path.read_bytes())
        stem = Path(source.get("file") or "material-library").stem or "material-library"
        output = target / f"{stem}-export.lib"
        counter = 1
        while output.exists():
            counter += 1
            output = target / f"{stem}-export-{counter}.lib"
        written.append(abaqus_lib.write_export(library, output))
    if not written and not skipped:
        raise ValueError("The selected materials have no CAE source library to export.")
    return {"files": written, "skipped": skipped}


@app.get("/api/files/pick")
def pick_path(mode: str = "folder", title: str = "Choose a folder"):
    """Explorer-style picker through the local desktop session (loopback only)."""
    from services import picker

    return picker.choose(mode, title)


# ------------------------------------------------ portable model/result files


@app.post("/api/files/model/save")
def save_model_file(body: ModelFileRequest):
    """Write the current head as a portable model file, atomically."""
    from hashlib import sha256

    target = Path(body.path)
    if target.is_file() and not body.overwrite:
        current = sha256(target.read_bytes()).hexdigest()
        if body.base_sha != current:
            return JSONResponse(
                {
                    "detail": "The file on disk differs from the version this session saved. "
                    "Overwrite it explicitly or choose Save As.",
                    "currentSha": current,
                },
                status_code=409,
            )
    try:
        return portable_files.save_model(
            str(body.revision), body.path, body.base_sha, body.overwrite
        )
    except portable_files.portable.PortableError as exc:
        raise ValueError(str(exc)) from exc


@app.post("/api/files/model/open", response_model=Revision)
def open_model_file(body: OpenFileRequest):
    """Open a portable model as a new independent head in this installation."""
    try:
        opened = portable_files.open_model(body.path)
    except portable_files.portable.PortableError as exc:
        raise ValueError(str(exc)) from exc
    return revision_payload(store.revision(opened["revision"]))


@app.post("/api/files/model/open-info")
def open_model_file_with_identity(body: OpenFileRequest):
    """Open a model and return the file identity the browser must remember.

    The revision alone cannot tell the workspace which file is active, so the
    opener returns the pathname and the exact SHA-256 it read.
    """
    from hashlib import sha256

    data = Path(body.path).read_bytes()
    try:
        opened = portable_files.open_model(body.path)
    except portable_files.portable.PortableError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "revision": revision_payload(store.revision(opened["revision"])),
        "path": body.path,
        "sha256": sha256(data).hexdigest(),
        # Exactly which compatible members were restored, and which item must be
        # regenerated when the embedded artifact could not be trusted.
        "restore": {
            "mesh": opened["mesh"],
            "fixture": opened["fixture"],
            "source": opened["source"],
            "items": opened["items"],
        },
    }


@app.post("/api/files/result/package")
def package_result_file(body: PackageResultRequest):
    try:
        return portable_files.package_job(str(body.job), body.folder)
    except portable_files.portable.PortableError as exc:
        raise ValueError(str(exc)) from exc


@app.post("/api/files/result/open", response_model=Job)
def open_result_file(body: OpenFileRequest):
    """Open a packaged result read-only; no solver or extractor runs."""
    try:
        opened = portable_files.open_result(body.path)
    except portable_files.portable.PortableError as exc:
        raise ValueError(str(exc)) from exc
    return opened["job"]




@app.get("/api/groups", response_model=list[GroupSummary])
def groups(include_archived: bool = False):
    return store.groups(include_archived)


@app.post("/api/groups/{gid}/archive", response_model=GroupSummary)
def archive_group(gid: UUID):
    return store.set_group_archived(gid, True)


@app.post("/api/groups/{gid}/restore", response_model=GroupSummary)
def restore_group(gid: UUID):
    return store.set_group_archived(gid, False)


@app.get("/api/groups/{gid}/deletion-info", response_model=DeletionInfo)
def group_deletion_info(gid: UUID):
    return store.group_deletion_info(gid)


@app.post("/api/groups/{gid}/delete", response_model=DeletionResult)
def delete_group(gid: UUID, body: DeleteConfirm = DeleteConfirm()):
    return store.purge_group(
        gid,
        body.confirm,
        {
            "models": body.expected_models,
            "revisions": body.expected_revisions,
            "jobs": body.expected_jobs,
        },
    )


@app.post("/api/groups", response_model=GroupSummary, status_code=201)
def create_group(body: NewGroup):
    return store.create_group(body.name)


@app.get("/api/projects", response_model=list[Summary])
def projects(include_archived: bool = False):
    return store.projects(include_archived)


@app.post("/api/projects/{pid}/archive", response_model=Summary)
def archive_model(pid: UUID):
    return store.set_project_archived(pid, True)


@app.post("/api/projects/{pid}/restore", response_model=Summary)
def restore_model(pid: UUID):
    return store.set_project_archived(pid, False)


@app.get("/api/projects/{pid}/deletion-info", response_model=DeletionInfo)
def model_deletion_info(pid: UUID):
    return store.project_deletion_info(pid)


@app.post("/api/projects/{pid}/delete", response_model=DeletionResult)
def delete_model(pid: UUID, body: DeleteConfirm = DeleteConfirm()):
    return store.purge_project(
        pid,
        body.confirm,
        {"revisions": body.expected_revisions, "jobs": body.expected_jobs},
    )


@app.get("/api/projects/{pid}/revisions", response_model=list[RevisionSummary])
def revision_history(pid: UUID):
    return store.revision_history(pid)


@app.post("/api/projects/{pid}/duplicate", response_model=Revision)
def duplicate_model(pid: UUID, body: DuplicateModel = DuplicateModel()):
    """Copy the current model into a new, independent model.

    A copy of a model whose group is archived goes to the internal file-document
    owner, so the copy is editable; an active project group is kept.
    """
    with store.connection(True) as db:
        group_id = store.copy_target_group(db, str(pid))
        head = db.execute(
            "SELECT r.setup, r.source_id FROM projects p JOIN revisions r ON p.head=r.id "
            "WHERE p.id=?",
            (str(pid),),
        ).fetchone()
        if head is None:
            raise KeyError("Project not found")
        setup = json.loads(head["setup"])
        setup["name"] = body.name or setup["name"][:150] + " · copy"
        rid = store.append_revision(
            db, setup, source_id=head["source_id"], group=group_id
        )
    return revision_payload(store.revision(rid))


@app.post("/api/projects/{pid}/recover", response_model=Revision, status_code=201)
def recover_model(pid: UUID):
    """Recover a stranded model as a distinct, independently editable copy.

    The original keeps its archived history and every immutable revision; the
    returned model has its own identity under the file-document owner.
    """
    return revision_payload(store.recover_model(str(pid)))


@app.get("/api/jobs")
def job_list(response: Response):
    """Lightweight activity list for the launcher and polling.

    Deliberately omits manifests, fixture node lists and logs: the startup check
    only needs to know whether anything is still owned, and dashboard lists use
    the paginated detail endpoints on demand. The coverage header is explicit so
    an older API's empty list can never be mistaken for "nothing is running".
    """
    response.headers["X-Abaqus-QOL-Jobs"] = "all-modes-v1"
    keys = (
        "id",
        "project",
        "project_name",
        "name",
        "mode",
        "status",
        "phase",
        "solver",
        "extraction",
        "created",
        "started",
        "ended",
        "owner",
        "heartbeat",
        "pid",
        "process_started",
        "cancelled",
        "result_state",
        "extraction_error",
        "salvage",
        "cancel_scope",
        "result_file",
        "publication",
    )
    result = []
    for job in store.jobs(store.ALL_MODES):
        row = {key: job.get(key) for key in keys}
        row["activity"] = activity.classify(job)
        row["result"] = job.get("result")
        result.append(row)
    return result


@app.post("/api/project-groups", response_model=GroupCreated, status_code=201)
def create_project_group(body: NewProjectGroup):
    """Create a project group and its first model as one durable operation."""
    model_name = (body.model_name or body.name).strip()
    if not model_name:
        raise ValueError("Enter a name for the first model.")
    setup = engineering.synthetic(model_name) if body.example else engineering.empty(model_name)
    if body.dimension == "3D":
        setup.dimension, setup.formulation = "3D", "extrusion_preview"
    model = store.create_group_with_model(
        body.name, setup.model_dump(mode="json"), str(body.token)
    )
    created = store.group_of(model["project"])
    return {
        "group": {
            "id": created["id"],
            "name": created["name"],
            "created": model["created"],
        },
        "model": revision_payload(model),
    }


@app.post("/api/projects", response_model=Revision)
def create(body: NewProject):
    if body.group and not store.group_exists(str(body.group)):
        raise KeyError("Project group not found")
    if body.group and store.group_archived(str(body.group)):
        raise store.Conflict("This project is archived. Restore it before adding a model.")
    # Creating a model never invents geometry. ``example`` is the only path to the
    # public synthetic section, and it is an explicit user choice. ``template``
    # selects the named example without changing the default.
    if body.example and body.template == "two-panel":
        setup = engineering.two_panel_section(body.name)
    elif body.example:
        setup = engineering.synthetic(body.name)
    else:
        setup = engineering.empty(body.name)
    if body.dimension == "3D":
        setup.dimension, setup.formulation = "3D", "extrusion_preview"
    return revision_payload(
        store.save(setup.model_dump(mode="json"), group=str(body.group) if body.group else None)
    )


@app.get("/api/revisions/{rid}", response_model=Revision)
def revision(rid: UUID):
    return revision_payload(store.revision(rid))


@app.get("/api/revisions/{rid}/readiness")
def revision_readiness(rid: UUID):
    """The single readiness calculation shared by the sidebar, Review and API.

    Every finding carries a stable reason code, the stage that resolves it and
    the artifact it refers to; the browser translates the code in Japanese and
    English. Direct API acceptance uses the same blockers.
    """
    return readiness.evaluate(rid)


def topology(setup):
    return (
        setup["vertices"],
        setup["edges"],
        setup["source"],
        setup["plane"],
        [(f["id"], f["component"], f["loops"], f.get("cavity", False)) for f in setup["faces"]],
        [c["id"] for c in setup["components"]],
    )


@app.put("/api/projects/{pid}", response_model=Revision)
def save(pid: UUID, body: Save):
    assert_editable(pid)
    previous = store.revision(body.base)
    setup = body.setup.model_dump(mode="json")
    if topology(setup) != topology(previous["setup"]):
        raise ValueError(
            "Import a replacement drawing to change topology and reset geometry assignments."
        )
    previous_cards = {card["id"]: card for card in previous["setup"]["materials"]}
    for card in setup["materials"]:
        prior = previous_cards.get(card["id"])
        if prior:
            changed = any(
                value != prior.get(key) for key, value in card.items() if key != "version"
            )
            card["version"] = prior["version"] + int(changed)
    return revision_payload(store.save(setup, str(pid), str(body.base), previous["source_id"]))


@app.post("/api/partition/preview")
def partition_preview(body: PartitionPreview):
    """Validate projected guides against a saved base; nothing is persisted.

    Preview and commit call the same domain function and the same seed, so the
    child IDs the operator reviews are the IDs that are saved. A draft setup is
    not accepted as the preview authority: partition requires a saved revision.
    """
    face, strokes = _partition_request(body)
    result = engineering.partition.arrange(
        body.setup, face, strokes, seed=str(body.base) if body.base else "preview"
    )
    candidate = result.pop("project", body.setup)
    return {
        "plan": result,
        "setup": candidate.model_dump(mode="json"),
        "display": engineering.display(candidate),
    }


@app.post("/api/projects/{pid}/partition", response_model=Revision)
def partition_model(pid: UUID, body: PartitionApply):
    """Persist one projected material partition as a new revision.

    The generic ``PUT`` topology guard stays untouched; a partition is its own
    validated operation. The base revision is checked transactionally, and a
    retried request that already produced this exact geometry returns its own
    revision instead of failing or duplicating it.
    """
    assert_editable(pid)
    previous = store.revision(body.base)
    if previous["project"] != str(pid):
        raise store.Conflict("The base revision belongs to another model.")
    setup = Project.model_validate(previous["setup"])
    face, strokes = _partition_request(body)
    candidate, _plan = engineering.partition.commit(
        setup, face, strokes, seed=str(body.base)
    )
    payload = candidate.model_dump(mode="json")
    try:
        return revision_payload(
            store.save(payload, str(pid), str(body.base), previous["source_id"])
        )
    except store.Conflict:
        current = store.revision(store.head_revision(pid))
        if current["setup"] == payload:
            return revision_payload(current)
        raise


def _action_message(document, action):
    """Actionable server-side refusal carrying the stable readiness code."""
    issues = document.get("submit_issues" if action == "submit" else "setup_issues") or []
    if issues:
        issue = issues[0]
        return (
            f"{issue['code']}: {issue['stage']} blocks {action} for revision "
            f"{document.get('revision')}."
        )
    return f"Revision {document.get('revision')} is not ready to {action}."


def _partition_request(body):
    """One target face plus projected guides from the new or legacy request."""
    if body.cut is not None:
        return body.cut.face, [((body.cut.start[0], body.cut.start[1]), (body.cut.end[0], body.cut.end[1]))]
    if not body.face:
        raise ValueError("Choose the target material region before partitioning.")
    if not body.strokes:
        raise ValueError("Draw at least one straight guide in the viewport.")
    if len(body.strokes) > 32:
        raise ValueError("A partition accepts at most 32 guides.")
    return body.face, [
        ((float(stroke[0][0]), float(stroke[0][1])), (float(stroke[1][0]), float(stroke[1][1])))
        for stroke in body.strokes
    ]


@app.post("/api/projects/{pid}/drawing", response_model=Job, status_code=202)
def drawing(
    pid: UUID,
    base: UUID = Form(...),
    units: str = Form("N-mm-s-tonne"),
    file: UploadFile = File(...),
):
    assert_editable(pid)
    previous = store.revision(base)
    if previous["project"] != str(pid):
        raise store.Conflict("Choose a revision from this project.")
    original = file.filename or ""
    if not original or len(original) > 200 or re.search(r'[\\/:*?"<>|\x00-\x1f]', original):
        raise ValueError("Choose a drawing with a simple filename.")
    ext = Path(original).suffix.lower()
    if ext not in {".dwg", ".dxf"}:
        raise ValueError("Select a DXF or DWG drawing.")
    # The drawing's own unit header decides the import basis; the form field is
    # the project unit system and is optional for current clients. No checkbox
    # confirmation is required.
    if units not in ("", "N-mm-s-tonne"):
        raise ValueError("This application uses N-mm-s-tonne project units.")
    units = "N-mm-s-tonne"
    if ext == ".dwg":
        dwg.helper()
    sid = store.new_id()
    directory = store.root() / "drawings" / sid
    directory.mkdir(parents=True)
    try:
        source = directory / ("drawing" + ext)
        with source.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                if output.tell() + len(chunk) > MAX_DRAWING:
                    raise ValueError("Maximum drawing size is 8 MiB.")
                output.write(chunk)
        (directory / "source.json").write_text(
            store.encoded({"filename": original, "units": units}), encoding="utf-8"
        )
        return store.submit(str(base), "Import drawing", "IMPORT", sid)
    except Exception:
        shutil.rmtree(directory)
        raise


@app.get("/api/jobs/{jid}/imported", response_model=Revision)
def imported(jid: UUID):
    job = store.job(jid)
    if job["mode"] != "IMPORT" or job["status"] != "Completed":
        raise store.Conflict("Drawing import is incomplete.")
    with store.connection() as db:
        row = db.execute(
            "SELECT id FROM revisions WHERE project=? AND source_id=? ORDER BY number LIMIT 1",
            (job["project"], str(jid)),
        ).fetchone()
    return revision_payload(store.revision(row["id"]))


@app.get("/api/revisions/{rid}/drawing")
def original_drawing(rid: UUID):
    rev = store.revision(rid)
    if not rev["source_id"]:
        raise KeyError("This revision uses the built-in synthetic geometry.")
    original = rev["setup"]["source"]["filename"]
    ext = Path(original).suffix.lower()
    if ext not in {".dxf", ".dwg"}:
        raise KeyError("Drawing unavailable")
    directory = store.root() / "drawings" / str(UUID(rev["source_id"]))
    return FileResponse(
        directory / ("drawing" + ext), filename=original, media_type="application/octet-stream"
    )


@app.post("/api/display")
def display(body: Project):
    return engineering.display(body)


@app.post("/api/meshes", response_model=Job)
def create_mesh(body: Build):
    revision = store.revision(body.revision)
    assert_editable(revision["project"])
    setup = Project.model_validate(revision["setup"])
    if setup.is_empty:
        raise ValueError(
            "This model has no drawing yet. Import a DXF or DWG at Import, assign the "
            "component roles and materials, then generate the mesh."
        )
    if setup.dimension != "2D":
        raise ValueError(
            "Mesh generation is available for 2D sections. The extrusion is a geometry preview."
        )
    # An empty fixture is valid here: the mesh is generated first, nodes are
    # reviewed afterwards.
    return store.submit(
        str(body.revision),
        "Generate mesh",
        "MESH",
        str(body.token),
        compat=engineering.mesh_compat(setup),
    )


@app.get("/api/meshes", response_model=list[Job])
def meshes():
    return store.jobs(("MESH",))


@app.put("/api/meshes/{jid}/fixture", response_model=Job)
def save_fixture(jid: UUID, body: Fixture):
    row = store.job(jid)
    if row["mode"] != "MESH" or row["status"] != "Completed" or not row["mesh_digest"]:
        raise store.Conflict("Generate the mesh before reviewing its fixed nodes.")
    labels = engineering.fixture.normalize(body.labels, mesh_artifact(jid))
    # Compare and update under one SQLite write transaction. The pre-read above
    # is only a fast rejection; it is never the concurrency decision.
    return store.set_fixture_checked(
        jid,
        row["mesh_digest"],
        engineering.fixture.labels_hash(labels),
        labels,
        body.expected_hash,
    )


@app.post("/api/meshes/{jid}/fixture/edges", response_model=FixtureInfo)
def resolve_legacy_fixture(jid: UUID, revision: UUID | None = None):
    """Resolve the open revision's mounting selection to nodes of this known mesh.

    ``revision`` is the revision the user is editing; without it the mesh's
    creating revision is used. The revision must belong to the same model and its
    mesh inputs must match, so two compatible revisions can resolve their own,
    different mounting edges.
    """
    row = store.job(jid)
    if row["mode"] != "MESH" or row["status"] != "Completed":
        raise store.Conflict("Generate the mesh before resolving a mounting selection.")
    target = store.revision(revision or row["revision"])
    if target["project"] != row["project"]:
        raise store.Conflict("The mesh belongs to another model.")
    if engineering.mesh_compat(Project.model_validate(target["setup"])) != row["mesh_compat"]:
        raise store.Conflict(
            "The mesh was generated for different mesh inputs. Generate the mesh again."
        )
    setup = target["setup"]
    selection = next(
        (s for s in setup["selections"] if s["id"] == setup["mounting"]["selection"]), None
    )
    if not selection or not selection["entities"]:
        raise ValueError(
            "This revision has no stored mounting edges. Select fixed nodes on the mesh instead."
        )
    labels = engineering.fixture.from_edges(mesh_artifact(jid), selection["entities"])
    return {
        "labels": labels,
        "count": len(labels),
        "hash": engineering.fixture.labels_hash(labels),
    }


@app.post("/api/decks", response_model=Job)
def create_deck(body: Deck):
    revision = store.revision(body.revision)
    assert_editable(revision["project"])
    setup = Project.model_validate(revision["setup"])
    if setup.is_empty:
        raise ValueError(
            "This model has no drawing yet. Prepare the input deck only after importing a "
            "drawing, meshing it and reviewing the fixed nodes."
        )
    if setup.dimension != "2D":
        raise ValueError(
            "Input generation is available for 2D sections. The extrusion is a geometry preview."
        )
    # The same action-specific decision the browser renders. Mesh artifact and
    # fixture defects keep the store's specific 409 recovery messages; every
    # other engineering setup blocker is refused here, before a job is queued.
    document = readiness.evaluate(body.revision)
    if not document.get("can_prepare", False):
        delegated = {"mesh.missing", "mesh.artifact_missing", "mesh.artifact_corrupt", "mounting.missing"}
        issues = [issue for issue in document.get("setup_issues", []) if issue["code"] not in delegated]
        if issues:
            raise ValueError(_action_message({**document, "setup_issues": issues}, "prepare"))
    return store.submit(
        str(body.revision),
        "Prepare input deck",
        "DECK",
        str(body.token),
        mesh=str(body.mesh),
        compat=engineering.mesh_compat(setup),
        expected_fixture=body.fixture_hash,
    )


@app.get("/api/decks", response_model=list[Job])
def decks():
    return store.jobs(("DECK",))


@app.post("/api/runs", response_model=Job)
def submit(body: Submit):
    if body.mode == "DEMO":
        raise ValueError(
            "DEMO execution has been withdrawn for new submissions. Historical DEMO runs "
            "remain readable. Select ABAQUS to analyse the reviewed input deck."
        )
    revision = store.revision(body.revision)
    assert_editable(revision["project"])
    setup = Project.model_validate(revision["setup"])
    if setup.is_empty:
        raise ValueError(
            "This model has no drawing yet. Import a drawing and prepare an input deck "
            "before submitting an analysis."
        )
    from integrations.abaqus.launcher import configured_launcher

    configured_launcher()
    if body.scenario != "success":
        raise ValueError("Synthetic scenarios are no longer available for new submissions.")
    store.revision(body.revision)
    output_dir = (body.output_dir or "").strip() or None
    if output_dir:
        target = Path(output_dir)
        if not target.is_dir():
            raise ValueError("The captured output folder is not available. Choose another folder.")
    return store.submit(
        str(body.revision),
        body.name,
        body.mode,
        str(body.token),
        "success",
        body.cpus,
        deck=str(body.deck),
        output_dir=output_dir,
    )


@app.get("/api/runs", response_model=list[Job])
def runs():
    return store.jobs()


@app.get("/api/jobs/{jid}", response_model=Job)
def job(jid: UUID):
    return store.job(jid)


@app.post("/api/jobs/{jid}/duplicate", response_model=Revision)
def duplicate(jid: UUID):
    job = store.job(jid)
    snapshot = store.revision(job["revision"])
    # An independent project avoids overwriting someone else's current head.
    setup = snapshot["setup"]
    setup["name"] = setup["name"][:150] + " · copy"
    group = store.group_of(job["project"])
    return revision_payload(
        store.save(setup, source_id=snapshot["source_id"], group=group["id"])
    )


@app.post("/api/jobs/{jid}/cancel", response_model=Job)
def cancel(jid: UUID):
    return store.cancel(str(jid))


@app.post("/api/jobs/{jid}/retry", response_model=Job)
def retry(jid: UUID):
    return store.retry(str(jid))


@app.post("/api/jobs/{jid}/extract", response_model=Job)
def extract_available(jid: UUID):
    """Queue one extraction-only attempt for an eligible terminal run.

    This never relaunches a solver. It is the explicit path for a historical
    failed/cancelled run whose native ODB may still be readable, and for a
    recoverable extraction error.
    """
    return store.authorize_extraction(str(jid))


@app.post("/api/jobs/{jid}/result-file")
def retry_result_file(jid: UUID, body: ResultFileRetry | None = None):
    """Retry saving a completed result to a folder without resubmitting the solver."""
    job = store.job(jid)
    folder = body.folder if body is not None else None
    try:
        return portable_files.package_job(str(jid), folder or job.get("output_dir"))
    except portable_files.portable.PortableError as exc:
        raise ValueError(str(exc)) from exc


@app.get("/api/jobs/{jid}/display-metadata")
def display_metadata(jid: UUID):
    """Run-wide camera bounds and colour ranges for result playback.

    New extraction records this in ``results.json``. A retained result without it
    is read once, server-side, into a derived cache keyed by the run and the
    index digest. Original artifacts are never rewritten and no solver runs.
    """
    job = store.job(jid)
    if not job["result"]["available"]:
        raise store.Conflict("Results are available only after a validated extraction.")
    import json as _json

    directory = store.job_dir(jid)
    index_path = directory / "results.json"
    if not index_path.is_file():
        raise KeyError("Result index unavailable")
    index = _json.loads(index_path.read_text(encoding="utf-8"))
    recorded = index.get("display")
    if isinstance(recorded, dict) and recorded.get("bounds"):
        return {**recorded, "source": "recorded"}
    digest = store.digest(index_path)
    cache = store.root() / "cache" / "display" / f"{jid}-{digest[:16]}.json"
    if cache.is_file():
        return {**_json.loads(cache.read_text(encoding="utf-8")), "source": "cache"}
    from integrations.abaqus.interchange import display_metadata as derive

    try:
        derived = derive(directory, index)
    except (OSError, KeyError, ValueError) as exc:
        raise store.Conflict(
            "Display metadata is unavailable for this retained result: " + str(exc)
        ) from exc
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(store.encoded(derived), encoding="utf-8")
    return {**derived, "source": "derived"}


@app.get("/api/jobs/{jid}/artifacts/{name}")
def artifact(jid: UUID, name: str):
    job = store.job(jid)
    directory = store.job_dir(jid).resolve()
    path = (directory / name).resolve()
    if name not in job["manifest"] or path.parent != directory or not path.is_file():
        raise HTTPException(404, "Artifact unavailable")
    media = "text/plain" if path.suffix in {".inp", ".log", ".sta", ".msg", ".dat"} else None
    return FileResponse(
        path,
        filename=name,
        media_type=media,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/jobs/{jid}/tail/{name}")
def tail(jid: UUID, name: str):
    from integrations.abaqus.launcher import tail as read_tail

    if name not in {
        "worker.log",
        "analysis.log",
        "analysis.dat",
        "solver.log",
        "extract.log",
        "analysis.msg",
        "analysis.sta",
    }:
        raise KeyError("Log not found")
    job = store.job(jid)
    if name not in job["manifest"]:
        raise KeyError("Log unavailable")
    return {"text": read_tail(store.job_dir(jid) / name, 16384)}


# Serve only the immutable release resolved at startup. A build that happens
# later publishes a new directory and manifest; it cannot replace these files.
if RELEASE.directory.is_dir():
    app.mount("/", StaticFiles(directory=str(RELEASE.directory), html=True))
