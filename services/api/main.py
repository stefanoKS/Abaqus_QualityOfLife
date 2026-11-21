import json
import os
import re
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from integrations import dwg, drawings
from packages import engineering
from packages.engineering.model import Project
from services import store
from .contracts import (
    Build,
    Deck,
    DuplicateModel,
    Fixture,
    FixtureInfo,
    GroupSummary,
    Job,
    NewGroup,
    NewProject,
    Revision,
    RevisionSummary,
    Save,
    Submit,
    Summary,
)

MAX_DRAWING = 8 * 1024 * 1024
STARTED = time.time()


def revision_payload(row):
    """Attach the mesh-compatibility digest so the browser can decide mesh reuse."""
    return {**row, "mesh_compat": engineering.mesh_compat(Project.model_validate(row["setup"]))}


def mesh_artifact(jid):
    path = store.job_dir(jid) / "mesh.json"
    if not path.is_file():
        raise store.Conflict("This mesh job has no stored mesh artifact.")
    return json.loads(path.read_text(encoding="utf-8"))


@asynccontextmanager
async def lifespan(_):
    store.initialize()
    if not store.projects():
        store.save(engineering.synthetic().model_dump(mode="json"), seed=True)
    yield


app = FastAPI(title="Abaqus QOL", version="0.2.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]"])


@app.middleware("http")
async def local_writes(request: Request, call_next):
    if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).hostname not in {"localhost", "127.0.0.1", "::1"}:
            return JSONResponse(
                {"detail": "This workbench accepts local browser requests only."}, 403
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
    """Identifiable readiness probe used by the launcher and instance reuse."""
    return {
        "product": "Abaqus QOL",
        "status": "ready",
        "version": app.version,
        "pid": os.getpid(),
        "started": STARTED,
    }


@app.get("/api/capabilities")
def capabilities():
    from integrations import dwg
    from integrations.abaqus.launcher import configured_launcher

    result = {}
    for name, fn in [("abaqus", configured_launcher), ("dwg", dwg.helper)]:
        try:
            fn()
            result[name] = "Configured"
        except (ValueError, OSError) as exc:
            result[name] = str(exc)
    result["dwgReader"] = "ACadSharp 3.8.35 (native, MIT)"
    result["odaRequired"] = False
    return result


@app.get("/api/groups", response_model=list[GroupSummary])
def groups():
    return store.groups()


@app.post("/api/groups", response_model=GroupSummary, status_code=201)
def create_group(body: NewGroup):
    return store.create_group(body.name)


@app.get("/api/projects", response_model=list[Summary])
def projects():
    return store.projects()


@app.get("/api/projects/{pid}/revisions", response_model=list[RevisionSummary])
def revision_history(pid: UUID):
    return store.revision_history(pid)


@app.post("/api/projects/{pid}/duplicate", response_model=Revision)
def duplicate_model(pid: UUID, body: DuplicateModel = DuplicateModel()):
    """Copy the current model into a new, independent model in the same group."""
    group = store.group_of(str(pid))
    with store.connection() as db:
        head = db.execute(
            "SELECT r.setup, r.source_id FROM projects p JOIN revisions r ON p.head=r.id "
            "WHERE p.id=?",
            (str(pid),),
        ).fetchone()
    if head is None:
        raise KeyError("Project not found")
    setup = json.loads(head["setup"])
    setup["name"] = body.name or setup["name"][:150] + " · copy"
    return revision_payload(store.save(setup, source_id=head["source_id"], group=group["id"]))


@app.post("/api/projects", response_model=Revision)
def create(body: NewProject):
    if body.group and not store.group_exists(str(body.group)):
        raise KeyError("Project group not found")
    setup = engineering.synthetic(body.name)
    if body.dimension == "3D":
        setup.dimension, setup.formulation = "3D", "extrusion_preview"
    return revision_payload(
        store.save(setup.model_dump(mode="json"), group=str(body.group) if body.group else None)
    )


@app.get("/api/revisions/{rid}", response_model=Revision)
def revision(rid: UUID):
    return revision_payload(store.revision(rid))


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


@app.post("/api/projects/{pid}/drawing", response_model=Job, status_code=202)
def drawing(
    pid: UUID, base: UUID = Form(...), units: str = Form(...), file: UploadFile = File(...)
):
    previous = store.revision(base)
    if previous["project"] != str(pid):
        raise store.Conflict("Choose a revision from this project.")
    original = file.filename or ""
    if not original or len(original) > 200 or re.search(r'[\\/:*?"<>|\x00-\x1f]', original):
        raise ValueError("Choose a drawing with a simple filename.")
    ext = Path(original).suffix.lower()
    if ext not in {".dwg", ".dxf"} or units != "N-mm-s-tonne":
        raise ValueError("Select a DXF or DWG and confirm millimetre input units.")
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
    setup = Project.model_validate(store.revision(body.revision)["setup"])
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
    return store.set_fixture(
        jid, row["mesh_digest"], engineering.fixture.labels_hash(labels), labels
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
    setup = Project.model_validate(store.revision(body.revision)["setup"])
    if setup.dimension != "2D":
        raise ValueError(
            "Input generation is available for 2D sections. The extrusion is a geometry preview."
        )
    return store.submit(
        str(body.revision),
        "Prepare input deck",
        "DECK",
        str(body.token),
        mesh=str(body.mesh),
        compat=engineering.mesh_compat(setup),
    )


@app.get("/api/decks", response_model=list[Job])
def decks():
    return store.jobs(("DECK",))


@app.post("/api/runs", response_model=Job)
def submit(body: Submit):
    if body.mode == "ABAQUS":
        from integrations.abaqus.launcher import configured_launcher

        configured_launcher()
        if body.scenario != "success":
            raise ValueError("Synthetic scenarios apply to DEMO runs only.")
    store.revision(body.revision)
    return store.submit(
        str(body.revision),
        body.name,
        body.mode,
        str(body.token),
        body.scenario,
        body.cpus,
        deck=str(body.deck),
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


dist = Path(__file__).resolve().parents[2] / "apps/web/dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True))
