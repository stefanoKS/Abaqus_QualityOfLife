"""Local, append-only project revisions and the durable single-host work queue."""

import ctypes
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

STALE_SECONDS = 30
TERMINAL = {"Completed", "Failed", "Cancelled"}

# The product is now "Abaqus QOL", but the on-disk directory keeps its previous
# name so every existing installation opens its projects without a migration
# step. Renaming the directory would silently create an empty database next to
# the real one. See docs/migration-and-recovery.md.
LEGACY_DIRECTORY = "SimplifyAbaqus"
ENV_DATA = "SEAL_DATA"
ENV_DATA_ALIAS = "ABAQUS_QOL_DATA"


class Conflict(ValueError):
    pass


def data_setting():
    """Return the configured data root name and value.

    Precedence is documented and deterministic: the established ``SEAL_DATA``
    wins over the new ``ABAQUS_QOL_DATA`` alias so existing startup scripts keep
    their exact behaviour.
    """
    for name in (ENV_DATA, ENV_DATA_ALIAS):
        value = os.environ.get(name)
        if value:
            return name, value
    return ENV_DATA, ""


def root():
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / LEGACY_DIRECTORY
    _, configured = data_setting()
    path = Path(configured).expanduser().resolve() if configured else base.resolve()
    if str(path).startswith(("//", "\\\\")) or (
        os.name == "nt" and ctypes.windll.kernel32.GetDriveTypeW(path.anchor) == 4
    ):
        raise ValueError("The Abaqus QOL data directory must be on a local disk for SQLite.")
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connection(write=False):
    db = sqlite3.connect(root() / "workbench.sqlite3", timeout=15, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        if write:
            db.execute("BEGIN IMMEDIATE")
        yield db
        if write:
            db.commit()
    finally:
        db.close()


def initialize():
    with connection() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, head TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS revisions(
          id TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(id),
          number INTEGER NOT NULL, created REAL NOT NULL, setup TEXT NOT NULL,
          source_id TEXT, UNIQUE(project, number));
        CREATE TABLE IF NOT EXISTS jobs(
          id TEXT PRIMARY KEY, revision TEXT NOT NULL REFERENCES revisions(id),
          name TEXT NOT NULL, mode TEXT NOT NULL, scenario TEXT NOT NULL,
          cpus INTEGER NOT NULL, token TEXT NOT NULL UNIQUE, build TEXT REFERENCES jobs(id),
          created REAL NOT NULL, started REAL, ended REAL, heartbeat REAL, owner TEXT,
          pid INTEGER, process_started REAL, solver TEXT NOT NULL DEFAULT 'Queued',
          extraction TEXT NOT NULL DEFAULT 'Pending', cancelled INTEGER DEFAULT 0,
          phase TEXT NOT NULL DEFAULT 'Awaiting worker', step TEXT, increment INTEGER, step_time REAL,
          exit_code INTEGER, extraction_exit INTEGER, diagnostic TEXT NOT NULL DEFAULT '',
          input_hash TEXT, manifest TEXT NOT NULL DEFAULT '[]');
        CREATE INDEX IF NOT EXISTS job_queue ON jobs(solver, extraction, created);
        """)


def encoded(data):
    return json.dumps(
        data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def new_id():
    return str(uuid4())


def job_dir(jid):
    return root() / "jobs" / str(UUID(str(jid)))


def revision(rid):
    with connection() as db:
        row = db.execute("SELECT * FROM revisions WHERE id=?", (str(rid),)).fetchone()
    if row is None:
        raise KeyError("Revision not found")
    return {**dict(row), "setup": json.loads(row["setup"])}


def append_revision(db, setup, project=None, base=None, source_id=None):
    rid = new_id()
    if project is None:
        project = new_id()
        number = 1
        db.execute("INSERT INTO projects VALUES (?,?)", (project, rid))
    else:
        head = db.execute("SELECT head FROM projects WHERE id=?", (project,)).fetchone()
        if not head:
            raise KeyError("Project not found")
        if head["head"] != base:
            raise Conflict("Another revision was saved. Reopen the project before saving.")
        number = db.execute("SELECT number FROM revisions WHERE id=?", (base,)).fetchone()[0] + 1
        db.execute("UPDATE projects SET head=? WHERE id=?", (rid, project))
    db.execute(
        "INSERT INTO revisions VALUES (?,?,?,?,?,?)",
        (rid, project, number, time.time(), encoded(setup), source_id),
    )
    return rid


def save(setup, project=None, base=None, source_id=None, seed=False):
    with connection(True) as db:
        if seed and db.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
            return
        rid = append_revision(db, setup, project, base, source_id)
    return revision(rid)


def projects():
    with connection() as db:
        return [
            dict(r)
            for r in db.execute("""
            SELECT project AS id, r.id AS revision, number, created,
                   json_extract(setup,'$.name') AS name, json_extract(setup,'$.dimension') AS dimension
            FROM projects p JOIN revisions r ON p.head=r.id ORDER BY created DESC""")
        ]


def status(r):
    solver, extraction = r["solver"], r["extraction"]
    if r["phase"] == "Process termination unconfirmed":
        return "Unknown / worker disconnected"
    if r["owner"] and time.time() - (r["heartbeat"] or 0) > STALE_SECONDS:
        return "Unknown / worker disconnected"
    if r["cancelled"] and r["owner"]:
        return "Cancel requested"
    if solver == "Succeeded":
        return {
            "Queued": "Processing results",
            "Running": "Processing results",
            "Succeeded": "Completed",
            "Failed": "Failed",
            "Cancelled": "Cancelled",
        }[extraction]
    return solver


def public(row):
    result = dict(row)
    result["status"] = status(result)
    result["manifest"] = json.loads(result["manifest"])
    result.pop("token", None)
    return result


JOB_SELECT = """SELECT j.*,r.project,r.number,
 json_extract(r.setup,'$.dimension') AS dimension,json_extract(r.setup,'$.name') AS project_name
 FROM jobs j JOIN revisions r ON j.revision=r.id"""


def job(jid):
    with connection() as db:
        row = db.execute(JOB_SELECT + " WHERE j.id=?", (str(jid),)).fetchone()
    if row is None:
        raise KeyError("Job not found")
    return public(row)


def jobs(builds=False):
    with connection() as db:
        return [
            public(r)
            for r in db.execute(
                JOB_SELECT
                + (" WHERE j.mode='BUILD'" if builds else " WHERE j.mode IN ('DEMO','ABAQUS')")
                + " ORDER BY j.created DESC"
            )
        ]


def submit(rev, name, mode, token, scenario="success", cpus=1, build=None):
    jid = token if mode == "IMPORT" else new_id()
    with connection(True) as db:
        existing = db.execute("SELECT * FROM jobs WHERE token=?", (token,)).fetchone()
        if existing:
            params = (rev, mode, name, scenario, cpus, build)
            if (
                tuple(
                    existing[k] for k in ("revision", "mode", "name", "scenario", "cpus", "build")
                )
                != params
            ):
                raise Conflict("Submission key was already used with different settings.")
            jid = existing["id"]
        else:
            input_hash = None
            if mode in {"DEMO", "ABAQUS"}:
                record = db.execute("SELECT * FROM jobs WHERE id=?", (build,)).fetchone()
                if (
                    not record
                    or record["revision"] != rev
                    or record["mode"] != "BUILD"
                    or status(record) != "Completed"
                ):
                    raise Conflict(
                        "Generate and review the input deck for this saved revision first."
                    )
                input_hash = record["input_hash"]
            db.execute(
                """INSERT INTO jobs(id,revision,name,mode,scenario,cpus,token,build,created,input_hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (jid, rev, name, mode, scenario, cpus, token, build, time.time(), input_hash),
            )
    return job(jid)


def claim(owner):
    with connection(True) as db:
        row = db.execute("""SELECT id,solver FROM jobs WHERE owner IS NULL AND cancelled=0
          AND (solver='Queued' OR (solver='Succeeded' AND extraction='Queued'))
          ORDER BY created LIMIT 1""").fetchone()
        if not row:
            return None
        extracting = row["solver"] == "Succeeded"
        now = time.time()
        db.execute(
            """UPDATE jobs SET owner=?,heartbeat=?,started=coalesce(started,?),
          solver=?,extraction=?,phase=? WHERE id=?""",
            (
                owner,
                now,
                now,
                "Succeeded" if extracting else "Preparing",
                "Running" if extracting else "Pending",
                "Extracting results" if extracting else "Preparing input",
                row["id"],
            ),
        )
    return job(row["id"])


def update(jid, owner, **values):
    columns = {
        "heartbeat",
        "pid",
        "process_started",
        "solver",
        "extraction",
        "phase",
        "owner",
        "ended",
        "exit_code",
        "extraction_exit",
        "diagnostic",
        "input_hash",
        "manifest",
        "step",
        "increment",
        "step_time",
    }
    if not values.keys() <= columns:
        raise ValueError("Unsupported worker update")
    with connection(True) as db:
        cursor = db.execute(
            "UPDATE jobs SET " + ",".join(k + "=?" for k in values) + " WHERE id=? AND owner=?",
            (*values.values(), jid, owner),
        )
        if not cursor.rowcount:
            raise Conflict("Worker no longer owns the job")


def cancel(jid):
    with connection(True) as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            raise KeyError("Job not found")
        if status(row) in TERMINAL:
            raise Conflict("Job has already finished.")
        db.execute("UPDATE jobs SET cancelled=1 WHERE id=?", (jid,))
        if not row["owner"]:
            column = "extraction" if row["solver"] == "Succeeded" else "solver"
            db.execute(
                f"UPDATE jobs SET {column}='Cancelled',phase='Cancelled in queue',ended=? WHERE id=?",
                (time.time(), jid),
            )
    return job(jid)


def retry(jid):
    with connection(True) as db:
        changed = db.execute(
            """UPDATE jobs SET extraction='Queued',cancelled=0,ended=NULL,
            diagnostic='',phase='Awaiting extraction',extraction_exit=NULL WHERE id=? AND mode!='BUILD'
            AND owner IS NULL AND solver='Succeeded' AND extraction IN ('Failed','Cancelled')""",
            (jid,),
        )
        if not changed.rowcount:
            raise Conflict("Only unsuccessful extraction after a successful solve can be retried.")
    return job(jid)


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
