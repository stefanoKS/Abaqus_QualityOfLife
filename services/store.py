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
        CREATE TABLE IF NOT EXISTS groups(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS fixtures(
          job TEXT PRIMARY KEY REFERENCES jobs(id), mesh_digest TEXT NOT NULL,
          labels_hash TEXT NOT NULL, labels TEXT NOT NULL, updated REAL NOT NULL);
        """)
    # Grouping is a logical layer above the model histories: revision rows, run
    # rows and artifact directories keep their identities and locations. The
    # column addition and backfill run in one transaction and are idempotent, so
    # a populated database survives an interrupted upgrade without data loss.
    with connection(True) as db:
        columns = {row["name"] for row in db.execute("PRAGMA table_info(projects)")}
        if "group_id" not in columns:
            db.execute("ALTER TABLE projects ADD COLUMN group_id TEXT")
        orphan = db.execute("SELECT 1 FROM projects WHERE group_id IS NULL LIMIT 1").fetchone()
        if orphan:
            group_id = legacy_group(db)
            db.execute("UPDATE projects SET group_id=? WHERE group_id IS NULL", (group_id,))
        # Mesh-first workflow: a mesh job records its immutable artifact digest and
        # the digest of the inputs that decide reuse; a deck job records the mesh
        # it consumed and the fixture revision it was prepared against.
        jobs_columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
        for name in ("mesh", "mesh_digest", "mesh_compat", "fixture_hash", "fixture_labels"):
            if name not in jobs_columns:
                db.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT")
        # A DEMO job that never started cannot be executed any more. Retire it with
        # an explicit record instead of relabelling it or launching it as Abaqus.
        db.execute(
            "UPDATE jobs SET solver='Failed', extraction='Cancelled', phase='Withdrawn', "
            "ended=coalesce(ended,?), diagnostic=? "
            "WHERE mode='DEMO' AND owner IS NULL AND solver='Queued' AND cancelled=0",
            (
                time.time(),
                "Legacy DEMO job retired: synthetic execution is no longer available. "
                "Submit an ABAQUS analysis for new evidence.",
            ),
        )


LEGACY_GROUP_NAME = "Imported projects"


def legacy_group(db):
    """Find-or-create the group that holds legacy and ungrouped models."""
    row = db.execute("SELECT id FROM groups WHERE name=?", (LEGACY_GROUP_NAME,)).fetchone()
    if row:
        return row["id"]
    group_id = new_id()
    db.execute(
        "INSERT INTO groups VALUES (?,?,?)", (group_id, LEGACY_GROUP_NAME, time.time())
    )
    return group_id


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
        row = db.execute(
            """SELECT r.*, p.group_id AS "group", g.name AS group_name
               FROM revisions r JOIN projects p ON p.id=r.project
               LEFT JOIN groups g ON g.id=p.group_id WHERE r.id=?""",
            (str(rid),),
        ).fetchone()
    if row is None:
        raise KeyError("Revision not found")
    return {**dict(row), "setup": json.loads(row["setup"])}


def append_revision(db, setup, project=None, base=None, source_id=None, group=None):
    rid = new_id()
    if project is None:
        project = new_id()
        number = 1
        db.execute(
            "INSERT INTO projects(id, head, group_id) VALUES (?,?,?)",
            (project, rid, group or legacy_group(db)),
        )
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


def save(setup, project=None, base=None, source_id=None, seed=False, group=None):
    with connection(True) as db:
        if seed and db.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
            return
        rid = append_revision(db, setup, project, base, source_id, group)
    return revision(rid)


def groups():
    with connection() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM groups ORDER BY created, name")]
    models = projects()
    for row in rows:
        row["models"] = [m for m in models if m["group"] == row["id"]]
    return rows


def create_group(name):
    group_id = new_id()
    with connection(True) as db:
        db.execute("INSERT INTO groups VALUES (?,?,?)", (group_id, name, time.time()))
    return {"id": group_id, "name": name, "created": time.time(), "models": []}


def group_exists(group):
    with connection() as db:
        return db.execute("SELECT 1 FROM groups WHERE id=?", (str(group),)).fetchone() is not None


def group_of(project):
    with connection() as db:
        row = db.execute(
            "SELECT p.group_id AS id, g.name FROM projects p "
            "LEFT JOIN groups g ON g.id=p.group_id WHERE p.id=?",
            (str(project),),
        ).fetchone()
    if row is None:
        raise KeyError("Project not found")
    return dict(row)


def projects():
    with connection() as db:
        return [
            dict(r)
            for r in db.execute("""
            SELECT project AS id, r.id AS revision, r.number AS number, r.created AS created,
                   json_extract(setup,'$.name') AS name,
                   json_extract(setup,'$.dimension') AS dimension,
                   p.group_id AS "group", g.name AS group_name,
                   (SELECT COUNT(*) FROM revisions WHERE project=p.id) AS revisions
            FROM projects p JOIN revisions r ON p.head=r.id
            LEFT JOIN groups g ON g.id=p.group_id ORDER BY r.created DESC""")
        ]


def revision_history(project):
    with connection() as db:
        return [
            dict(r)
            for r in db.execute(
                """SELECT id, project, number, created, source_id,
                   json_extract(setup,'$.name') AS name,
                   json_extract(setup,'$.dimension') AS dimension
                   FROM revisions WHERE project=? ORDER BY number DESC""",
                (str(project),),
            )
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
    # ``review_labels`` is the live fixture on a mesh job; ``fixture_labels`` is the
    # immutable snapshot a deck job was prepared from.
    labels = result.pop("review_labels", None)
    labels_hash = result.pop("review_labels_hash", None)
    result["fixture"] = (
        None
        if labels is None
        else {"labels": json.loads(labels), "count": len(json.loads(labels)), "hash": labels_hash}
    )
    snapshot = result.pop("fixture_labels", None)
    result["fixture_labels"] = None if snapshot is None else json.loads(snapshot)
    result.pop("token", None)
    return result


JOB_SELECT = """SELECT j.*,r.project,r.number,
 json_extract(r.setup,'$.dimension') AS dimension,json_extract(r.setup,'$.name') AS project_name,
 (SELECT labels FROM fixtures f WHERE f.job=j.id) AS review_labels,
 (SELECT labels_hash FROM fixtures f WHERE f.job=j.id) AS review_labels_hash
 FROM jobs j JOIN revisions r ON j.revision=r.id"""


def job(jid):
    with connection() as db:
        row = db.execute(JOB_SELECT + " WHERE j.id=?", (str(jid),)).fetchone()
    if row is None:
        raise KeyError("Job not found")
    return public(row)


def jobs(modes=("DEMO", "ABAQUS")):
    placeholders = ",".join("?" * len(modes))
    with connection() as db:
        return [
            public(r)
            for r in db.execute(
                JOB_SELECT + f" WHERE j.mode IN ({placeholders}) ORDER BY j.created DESC",
                tuple(modes),
            )
        ]


def set_fixture(jid, mesh_digest, labels_hash, labels):
    with connection(True) as db:
        db.execute(
            "INSERT INTO fixtures VALUES (?,?,?,?,?) ON CONFLICT(job) DO UPDATE SET "
            "mesh_digest=excluded.mesh_digest, labels_hash=excluded.labels_hash, "
            "labels=excluded.labels, updated=excluded.updated",
            (str(jid), mesh_digest, labels_hash, encoded(labels), time.time()),
        )
    return job(jid)


def project_of(db, rev):
    row = db.execute("SELECT project FROM revisions WHERE id=?", (str(rev),)).fetchone()
    if row is None:
        raise KeyError("Revision not found")
    return row["project"]


def active_mesh(db, project, compat):
    """Newest completed mesh for these mesh inputs.

    An explicit remesh therefore supersedes an older mesh with the same bytes:
    new deck preparation and submission must use this one, which starts without a
    reviewed fixture.
    """
    rows = db.execute(
        """SELECT j.* FROM jobs j JOIN revisions r ON j.revision=r.id
           WHERE r.project=? AND j.mode='MESH' AND j.mesh_compat=?
           ORDER BY j.created DESC""",
        (project, compat),
    ).fetchall()
    return next((row for row in rows if status(row) == "Completed"), None)


def newest_deck(db, rev):
    rows = db.execute(
        "SELECT * FROM jobs WHERE revision=? AND mode='DECK' ORDER BY created DESC", (str(rev),)
    ).fetchall()
    return next((row for row in rows if status(row) == "Completed"), None)


def submit(
    rev,
    name,
    mode,
    token,
    scenario="success",
    cpus=1,
    deck=None,
    mesh=None,
    compat=None,
):
    jid = token if mode == "IMPORT" else new_id()
    if mode == "DEMO":
        raise Conflict(
            "DEMO execution is no longer available for new submissions. "
            "Historical DEMO evidence remains readable."
        )
    with connection(True) as db:
        existing = db.execute("SELECT * FROM jobs WHERE token=?", (token,)).fetchone()
        if existing:
            params = (rev, mode, name, scenario, cpus, deck, mesh, compat)
            if (
                tuple(
                    existing[k]
                    for k in ("revision", "mode", "name", "scenario", "cpus", "build", "mesh",
                              "mesh_compat")
                )
                != params
            ):
                raise Conflict("Submission key was already used with different settings.")
            jid = existing["id"]
        else:
            input_hash = None
            mesh_digest = None
            fixture_hash = None
            fixture_labels = None
            if mode == "MESH":
                if not compat:
                    raise Conflict("Generate the mesh from a saved 2D revision.")
            elif mode == "DECK":
                record = db.execute("SELECT * FROM jobs WHERE id=?", (mesh,)).fetchone()
                if not record or record["mode"] != "MESH" or status(record) != "Completed":
                    raise Conflict("Generate the mesh for this model before preparing the input.")
                project = project_of(db, rev)
                same_model = project_of(db, record["revision"]) == project
                if not same_model:
                    raise Conflict("The mesh belongs to another model. Generate the mesh again.")
                if record["mesh_compat"] != compat:
                    raise Conflict(
                        "The mesh was generated for different mesh inputs. Generate the mesh again."
                    )
                current = active_mesh(db, project, compat)
                if current is None or current["id"] != record["id"]:
                    raise Conflict(
                        "A newer mesh supersedes this one. Review the fixed nodes on the "
                        "current mesh before preparing the input."
                    )
                fixture = db.execute("SELECT * FROM fixtures WHERE job=?", (mesh,)).fetchone()
                if not fixture or not json.loads(fixture["labels"]):
                    raise Conflict(
                        "Select the fixed weatherstrip nodes before preparing the input deck."
                    )
                if fixture["mesh_digest"] != record["mesh_digest"]:
                    raise Conflict(
                        "The fixed-node selection belongs to another mesh. Review the fixture."
                    )
                # Capture the reviewed selection atomically with the queue entry: a
                # later fixture edit must not change this deck.
                mesh_digest = record["mesh_digest"]
                fixture_hash = fixture["labels_hash"]
                fixture_labels = fixture["labels"]
            elif mode in {"DEMO", "ABAQUS"}:
                record = db.execute("SELECT * FROM jobs WHERE id=?", (deck,)).fetchone()
                if (
                    not record
                    or record["revision"] != rev
                    or record["mode"] != "DECK"
                    or status(record) != "Completed"
                ):
                    raise Conflict(
                        "Prepare and review the input deck for this saved revision first."
                    )
                if record["mesh"]:
                    mesh_row = db.execute(
                        "SELECT * FROM jobs WHERE id=?", (record["mesh"],)
                    ).fetchone()
                    current = (
                        active_mesh(db, project_of(db, rev), mesh_row["mesh_compat"])
                        if mesh_row
                        else None
                    )
                    if current is None or current["id"] != record["mesh"]:
                        raise Conflict(
                            "This input deck uses a superseded mesh. Review the fixed nodes on "
                            "the current mesh and prepare the input deck again."
                        )
                    fixture = db.execute(
                        "SELECT * FROM fixtures WHERE job=?", (record["mesh"],)
                    ).fetchone()
                    if not fixture or fixture["labels_hash"] != record["fixture_hash"]:
                        raise Conflict(
                            "The fixed-node fixture changed after the deck was prepared. "
                            "Prepare the input deck again."
                        )
                latest = newest_deck(db, rev)
                if latest is None or latest["id"] != record["id"]:
                    raise Conflict(
                        "A newer input deck exists for this revision. Prepare and review the "
                        "current deck before submitting."
                    )
                input_hash = record["input_hash"]
                mesh_digest = record["mesh_digest"]
                fixture_hash = record["fixture_hash"]
                fixture_labels = record["fixture_labels"]
            db.execute(
                """INSERT INTO jobs(id,revision,name,mode,scenario,cpus,token,build,mesh,created,
                       input_hash,mesh_digest,mesh_compat,fixture_hash,fixture_labels)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    jid,
                    rev,
                    name,
                    mode,
                    scenario,
                    cpus,
                    token,
                    deck,
                    mesh,
                    time.time(),
                    input_hash,
                    mesh_digest,
                    compat,
                    fixture_hash,
                    fixture_labels,
                ),
            )
    return job(jid)


def claim(owner):
    with connection(True) as db:
        # Synthetic DEMO execution is withdrawn. A queued legacy DEMO row is never
        # converted into a licensed job, relocated or relaunched.
        row = db.execute("""SELECT id,solver FROM jobs WHERE owner IS NULL AND cancelled=0
          AND mode IN ('ABAQUS', 'MESH', 'DECK', 'IMPORT')
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
        "mesh_digest",
        "mesh_compat",
        "fixture_hash",
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
            diagnostic='',phase='Awaiting extraction',extraction_exit=NULL WHERE id=?
            AND mode IN ('DEMO','ABAQUS')
            AND owner IS NULL AND solver='Succeeded' AND extraction IN ('Failed','Cancelled')""",
            (jid,),
        )
        if not changed.rowcount:
            raise Conflict("Only unsuccessful extraction after a successful solve can be retried.")
    return job(jid)


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
