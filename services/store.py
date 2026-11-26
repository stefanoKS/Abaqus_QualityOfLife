"""Local, append-only project revisions and the durable single-host work queue."""

import ctypes
import hashlib
import json
import os
import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from services import activity, ownership

STALE_SECONDS = 30
TERMINAL = {"Completed", "Failed", "Cancelled"}
# Every durable job kind, for the startup activity view. Dashboard run lists keep
# their narrower DEMO/ABAQUS default.
ALL_MODES = ("DEMO", "ABAQUS", "MESH", "DECK", "IMPORT")

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
          id TEXT PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL,
          archived INTEGER NOT NULL DEFAULT 0, internal INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS deletions(
          token TEXT PRIMARY KEY, kind TEXT NOT NULL, target TEXT NOT NULL,
          payload TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL,
          updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS material_library(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
          created REAL NOT NULL, updated REAL NOT NULL, current_version INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS material_versions(
          library_id TEXT NOT NULL REFERENCES material_library(id),
          version INTEGER NOT NULL, model TEXT NOT NULL, color TEXT NOT NULL,
          density REAL, young REAL, poisson REAL, test_data TEXT NOT NULL,
          created REAL NOT NULL, note TEXT NOT NULL DEFAULT '',
          c10 REAL, d1 REAL, family TEXT NOT NULL DEFAULT 'polymer', source TEXT,
          properties TEXT,
          PRIMARY KEY(library_id, version));
        CREATE TABLE IF NOT EXISTS creations(
          token TEXT PRIMARY KEY, group_id TEXT NOT NULL, project_id TEXT NOT NULL,
          revision_id TEXT NOT NULL, created REAL NOT NULL);
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
        # Archive/tombstone lifecycle is additive; old installations open unchanged.
        if "archived" not in columns:
            db.execute("ALTER TABLE projects ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        group_columns = {row["name"] for row in db.execute("PRAGMA table_info(groups)")}
        if "archived" not in group_columns:
            db.execute("ALTER TABLE groups ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
        # An internal owner holds independently opened/created file documents. It
        # is selected by this flag, never by a display name, and it has no archive
        # or delete control. Exactly one such row may exist.
        if "internal" not in group_columns:
            db.execute("ALTER TABLE groups ADD COLUMN internal INTEGER NOT NULL DEFAULT 0")
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS groups_single_internal "
            "ON groups(internal) WHERE internal=1"
        )
        # Mesh-first workflow: a mesh job records its immutable artifact digest and
        # the digest of the inputs that decide reuse; a deck job records the mesh
        # it consumed and the fixture revision it was prepared against.
        jobs_columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
        for name in ("mesh", "mesh_digest", "mesh_compat", "fixture_hash", "fixture_labels"):
            if name not in jobs_columns:
                db.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT")
        # Captured output folder, published result file and its publication state
        # are additive; an older job simply has none.
        for name in ("output_dir", "result_file", "publication"):
            if name not in jobs_columns:
                db.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT")
        # Solver outcome, extraction outcome and result availability are three
        # independent facts. These columns are additive: an older database opens
        # unchanged, and the backfill below only marks positively completed
        # historical extractions as complete.
        if "result_state" not in jobs_columns:
            db.execute(
                "ALTER TABLE jobs ADD COLUMN result_state TEXT NOT NULL DEFAULT 'none'"
            )
        if "result_summary" not in jobs_columns:
            db.execute("ALTER TABLE jobs ADD COLUMN result_summary TEXT")
        if "extraction_error" not in jobs_columns:
            db.execute("ALTER TABLE jobs ADD COLUMN extraction_error TEXT")
        if "result_generation" not in jobs_columns:
            db.execute(
                "ALTER TABLE jobs ADD COLUMN result_generation INTEGER NOT NULL DEFAULT 0"
            )
        # Immutable generation directory (relative to the job directory). Null on
        # historical rows, which keep the legacy flat-file layout.
        if "result_dir" not in jobs_columns:
            db.execute("ALTER TABLE jobs ADD COLUMN result_dir TEXT")
        if "salvage" not in jobs_columns:
            db.execute("ALTER TABLE jobs ADD COLUMN salvage INTEGER NOT NULL DEFAULT 0")
        if "cancel_scope" not in jobs_columns:
            db.execute("ALTER TABLE jobs ADD COLUMN cancel_scope TEXT")
        # Historical rows that positively finished extraction already carry a
        # published index; treating them as complete keeps their established
        # opening behaviour. Partial rows are only ever written by the new path.
        db.execute(
            "UPDATE jobs SET result_state='complete' WHERE result_state='none' "
            "AND solver='Succeeded' AND extraction='Succeeded'"
        )
        # Compressible neo-Hookean library cards add two parameters; older
        # versions keep NULL and are read unchanged.
        material_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(material_versions)")
        }
        for name in ("c10", "d1"):
            if name not in material_columns:
                db.execute(f"ALTER TABLE material_versions ADD COLUMN {name} REAL")
        # The engineering family and the CAE import provenance are additive: an
        # older card reads as a polymer with no source and stays unchanged.
        if "family" not in material_columns:
            db.execute(
                "ALTER TABLE material_versions ADD COLUMN family TEXT NOT NULL DEFAULT 'polymer'"
            )
        if "source" not in material_columns:
            db.execute("ALTER TABLE material_versions ADD COLUMN source TEXT")
        # A registered CAE record may have no density, and its faithful law lives
        # in ``properties``. SQLite cannot relax NOT NULL in place, so the one
        # table is rebuilt in the same transaction. Every existing row is copied
        # unchanged; only the column constraint and the new column differ.
        columns = {
            row["name"]: row for row in db.execute("PRAGMA table_info(material_versions)")
        }
        if columns.get("density") and columns["density"]["notnull"]:
            db.execute("ALTER TABLE material_versions RENAME TO material_versions_legacy")
            db.execute(
                """CREATE TABLE material_versions(
                  library_id TEXT NOT NULL REFERENCES material_library(id),
                  version INTEGER NOT NULL, model TEXT NOT NULL, color TEXT NOT NULL,
                  density REAL, young REAL, poisson REAL, test_data TEXT NOT NULL,
                  created REAL NOT NULL, note TEXT NOT NULL DEFAULT '',
                  c10 REAL, d1 REAL, family TEXT NOT NULL DEFAULT 'polymer', source TEXT,
                  properties TEXT,
                  PRIMARY KEY(library_id, version))"""
            )
            db.execute(
                """INSERT INTO material_versions(library_id,version,model,color,density,
                   young,poisson,test_data,created,note,c10,d1,family,source)
                   SELECT library_id,version,model,color,density,young,poisson,test_data,
                   created,note,c10,d1,family,source FROM material_versions_legacy"""
            )
            db.execute("DROP TABLE material_versions_legacy")
            columns = {
                row["name"]: row for row in db.execute("PRAGMA table_info(material_versions)")
            }
        if "properties" not in columns:
            db.execute("ALTER TABLE material_versions ADD COLUMN properties TEXT")
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
    # Finish any permanent-deletion cleanup interrupted by a crash. If the
    # deleting transaction never committed, its rows still exist and the
    # journal is discarded without removing artifacts.
    recover_deletions()


LEGACY_GROUP_NAME = "Imported projects"
# Independently created or opened documents get a persistent owner that is
# distinct from the historical migration group. The name is display metadata
# only: selection always uses ``internal=1``.
FILE_GROUP_NAME = "File documents"


def legacy_group(db):
    """Find-or-create the group that holds legacy and ungrouped models."""
    row = db.execute("SELECT id FROM groups WHERE name=?", (LEGACY_GROUP_NAME,)).fetchone()
    if row:
        return row["id"]
    group_id = new_id()
    db.execute(
        "INSERT INTO groups(id,name,created) VALUES (?,?,?)", (group_id, LEGACY_GROUP_NAME, time.time())
    )
    return group_id


def file_group(db):
    """Find-or-create the internal owner of standalone file documents.

    Resolved inside the caller's write transaction, so a head and its owner are
    created atomically. The row is never archived and never appears as a user
    project; the partial unique index keeps it single even under a race.
    """
    row = db.execute("SELECT id FROM groups WHERE internal=1").fetchone()
    if row:
        return row["id"]
    group_id = new_id()
    db.execute(
        "INSERT INTO groups(id,name,created,archived,internal) VALUES (?,?,?,0,1)",
        (group_id, FILE_GROUP_NAME, time.time()),
    )
    return group_id


def internal_group(gid):
    """True when a group is the application-managed file-document owner."""
    with connection() as db:
        row = db.execute("SELECT internal FROM groups WHERE id=?", (str(gid),)).fetchone()
    return bool(row and row["internal"])


def encoded(data):
    return json.dumps(
        data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def new_id():
    return str(uuid4())


def job_dir(jid):
    return root() / "jobs" / str(UUID(str(jid)))


def mesh_artifact_state(jid, expected_digest=None):
    """Classify the active mesh artifact: ``ok``, ``missing`` or ``corrupt``.

    Read-only. A byte-level digest is compared with the digest recorded when the
    mesh completed; a mismatch is corruption even if the JSON still parses.
    Historical job directories are never modified.
    """
    path = job_dir(jid) / "mesh.json"
    if not path.is_file():
        return "missing"
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return "corrupt"
    if not isinstance(data, dict) or not data.get("nodes") or not data.get("elements"):
        return "corrupt"
    if expected_digest and hashlib.sha256(raw).hexdigest() != str(expected_digest):
        return "corrupt"
    return "ok"


def revision(rid):
    with connection() as db:
        row = db.execute(
            """SELECT r.*, p.group_id AS "group", g.name AS group_name,
               p.archived AS archived, g.archived AS group_archived
               FROM revisions r JOIN projects p ON p.id=r.project
               LEFT JOIN groups g ON g.id=p.group_id WHERE r.id=?""",
            (str(rid),),
        ).fetchone()
    if row is None:
        raise KeyError("Revision not found")
    result = {**dict(row), "setup": json.loads(row["setup"])}
    result["archived"] = bool(result.get("archived"))
    result["group_archived"] = bool(result.get("group_archived"))
    return result


def append_revision(db, setup, project=None, base=None, source_id=None, group=None):
    rid = new_id()
    if project is None:
        project = new_id()
        number = 1
        # A new head and its owner are resolved and validated in this same write
        # transaction. An omitted group means "this is a standalone file
        # document", never "whatever the migration group happens to be called",
        # so a historical group's display name and archive state cannot make a
        # fresh file read-only.
        if group:
            owner = db.execute(
                "SELECT archived FROM groups WHERE id=?", (str(group),)
            ).fetchone()
            if owner is None:
                raise KeyError("Project group not found")
            if owner["archived"]:
                raise Conflict("This project is archived. Restore it before adding a model.")
            group_id = str(group)
        else:
            group_id = file_group(db)
        db.execute(
            "INSERT INTO projects(id, head, group_id) VALUES (?,?,?)",
            (project, rid, group_id),
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


def groups(include_archived=False):
    with connection() as db:
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT id,name,created,archived,internal FROM groups"
                + ("" if include_archived else " WHERE archived=0")
                + " ORDER BY internal, created, name"
            )
        ]
    models = projects(include_archived=include_archived)
    for row in rows:
        row["archived"] = bool(row["archived"])
        row["internal"] = bool(row["internal"])
        row["models"] = [m for m in models if m["group"] == row["id"]]
    return rows


def create_group(name):
    group_id = new_id()
    with connection(True) as db:
        db.execute("INSERT INTO groups(id,name,created) VALUES (?,?,?)", (group_id, name, time.time()))
    return {"id": group_id, "name": name, "created": time.time(), "models": []}


def create_group_with_model(group_name, setup, token):
    """Create the group and its first model as one transaction.

    The user action carries one ``token``. A second request with the same token
    returns the first result even if the first response was lost, and a failure
    anywhere inside the transaction leaves neither a group nor a model behind.
    """
    with connection(True) as db:
        existing = db.execute(
            "SELECT revision_id FROM creations WHERE token=?", (str(token),)
        ).fetchone()
        if existing:
            return revision(existing["revision_id"])
        group_id = new_id()
        db.execute(
            "INSERT INTO groups(id,name,created) VALUES (?,?,?)", (group_id, group_name, time.time())
        )
        rid = append_revision(db, setup, group=group_id)
        project = db.execute("SELECT project FROM revisions WHERE id=?", (rid,)).fetchone()[0]
        db.execute(
            "INSERT INTO creations VALUES (?,?,?,?,?)",
            (str(token), group_id, project, rid, time.time()),
        )
    return revision(rid)


def copy_target_group(db, pid):
    """Owner for a copy of a model: its own group unless that group is archived.

    A copy of a model stranded in an archived group must be independently
    editable; keeping the archived owner would silently reproduce the defect this
    release fixes. The internal owner and an active project group are kept.
    """
    owner = db.execute(
        "SELECT p.group_id AS id, g.archived FROM projects p "
        "LEFT JOIN groups g ON g.id=p.group_id WHERE p.id=?",
        (str(pid),),
    ).fetchone()
    if owner is None:
        raise KeyError("Project not found")
    if not owner["id"] or owner["archived"]:
        return file_group(db)
    return owner["id"]


def recover_model(pid, name=None):
    """Create an independent, editable copy of a model's current head.

    The original revisions, submitted setups and result files stay untouched;
    the copy is a new project with a new identity and no group history.
    """
    with connection(True) as db:
        head = db.execute(
            "SELECT r.setup, r.source_id FROM projects p JOIN revisions r ON p.head=r.id "
            "WHERE p.id=?",
            (str(pid),),
        ).fetchone()
        if head is None:
            raise KeyError("Project not found")
        setup = json.loads(head["setup"])
        setup["name"] = (name or setup.get("name") or "Recovered model")[:150]
        group_id = copy_target_group(db, pid)
        rid = append_revision(db, setup, source_id=head["source_id"], group=group_id)
    return revision(rid)


def creation_of(token):
    """Return the recorded creation for a token, if one exists."""
    with connection() as db:
        row = db.execute(
            "SELECT * FROM creations WHERE token=?", (str(token),)
        ).fetchone()
    return dict(row) if row else None


def data_identity():
    """Stable identity of the resolved data directory, including its inode."""
    return ownership.canonical_identity(root())


INSTANCE_RECORD = ownership.INSTANCE_RECORD


def instance_path():
    return root() / INSTANCE_RECORD


def read_instance():
    return ownership.read_instance(root())


def pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True


def claim_data_root(pid, port, release_id=""):
    """Atomically claim the API/launcher role for this data directory.

    The claim is an OS lock, held until :func:`release_data_root` drops the last
    in-process reference (normally after the worker has finished). Two cold
    starts on different ports cannot both win, and a crash releases the lock
    through the kernel rather than through a PID record.
    """
    try:
        return ownership.acquire(root(), ownership.OWNER, pid, port, release_id)
    except ownership.OwnershipConflict as error:
        raise Conflict(str(error)) from error


def release_data_root(pid):
    ownership.release(root(), ownership.OWNER, pid)


def claim_worker_root(pid):
    """Claim the worker role, so an orphaned worker keeps the directory busy."""
    try:
        return ownership.acquire(root(), ownership.WORKER, pid)
    except ownership.OwnershipConflict as error:
        raise Conflict(str(error)) from error


def release_worker_root(pid):
    ownership.release(root(), ownership.WORKER, pid)


def group_exists(group):
    with connection() as db:
        return db.execute("SELECT 1 FROM groups WHERE id=?", (str(group),)).fetchone() is not None


def group_of(project):
    with connection() as db:
        row = db.execute(
            "SELECT p.group_id AS id, g.name, g.archived, g.internal FROM projects p "
            "LEFT JOIN groups g ON g.id=p.group_id WHERE p.id=?",
            (str(project),),
        ).fetchone()
    if row is None:
        raise KeyError("Project not found")
    return {
        **dict(row),
        "archived": bool(row["archived"]),
        "internal": bool(row["internal"]),
    }


def project_archived(pid):
    with connection() as db:
        row = db.execute(
            "SELECT archived FROM projects WHERE id=?", (str(pid),)
        ).fetchone()
    if row is None:
        raise KeyError("Project not found")
    return bool(row["archived"])


def group_archived(gid):
    with connection() as db:
        row = db.execute(
            "SELECT archived FROM groups WHERE id=?", (str(gid),)
        ).fetchone()
    if row is None:
        raise KeyError("Project group not found")
    return bool(row["archived"])


def project_locked(pid):
    """True when the model or its project group is archived (read-only)."""
    with connection() as db:
        row = db.execute(
            "SELECT p.archived, g.archived AS group_archived FROM projects p "
            "LEFT JOIN groups g ON g.id=p.group_id WHERE p.id=?",
            (str(pid),),
        ).fetchone()
    if row is None:
        raise KeyError("Project not found")
    return bool(row["archived"] or row["group_archived"])


def set_project_archived(pid, archived):
    with connection(True) as db:
        cursor = db.execute(
            "UPDATE projects SET archived=? WHERE id=?",
            (1 if archived else 0, str(pid)),
        )
        if not cursor.rowcount:
            raise KeyError("Project not found")
    return next(row for row in projects(include_archived=True) if row["id"] == str(pid))


def set_group_archived(gid, archived):
    with connection(True) as db:
        row = db.execute("SELECT internal FROM groups WHERE id=?", (str(gid),)).fetchone()
        if row is None:
            raise KeyError("Project group not found")
        # The file-document owner is application-managed. Archiving it would turn
        # every standalone document read-only at once, and no user control offers
        # that action, so the API refuses it rather than trusting the caller.
        if row["internal"]:
            raise Conflict(
                "This group holds standalone file documents and cannot be archived."
            )
        db.execute(
            "UPDATE groups SET archived=? WHERE id=?",
            (1 if archived else 0, str(gid)),
        )
    return next(row for row in groups(include_archived=True) if row["id"] == str(gid))


def _jobs_for(project_ids):
    placeholders = ",".join("?" * len(project_ids))
    with connection() as db:
        return [
            dict(row)
            for row in db.execute(
                JOB_SELECT + f" WHERE r.project IN ({placeholders})",
                tuple(project_ids),
            )
        ]


def _unsafe_jobs(project_ids):
    unsafe = []
    for row in _jobs_for(project_ids):
        public_row = public(row)
        if activity.classify(public_row) != activity.TERMINAL:
            unsafe.append(public_row)
    return unsafe


def project_deletion_info(pid):
    with connection() as db:
        row = db.execute(
            "SELECT p.id, p.group_id, p.archived, g.name AS group_name, g.archived AS group_archived, "
            "json_extract(r.setup,'$.name') AS name FROM projects p "
            "JOIN revisions r ON p.head=r.id LEFT JOIN groups g ON g.id=p.group_id WHERE p.id=?",
            (str(pid),),
        ).fetchone()
        if row is None:
            raise KeyError("Project not found")
        revisions = db.execute(
            "SELECT COUNT(*) FROM revisions WHERE project=?", (str(pid),)
        ).fetchone()[0]
        jobs = db.execute("SELECT COUNT(*) FROM jobs j JOIN revisions r ON r.id=j.revision WHERE r.project=?", (str(pid),)).fetchone()[0]
    unsafe = _unsafe_jobs([str(pid)])
    return {
        "kind": "model",
        "id": str(pid),
        "name": row["name"],
        "group": row["group_id"],
        "group_name": row["group_name"],
        "archived": bool(row["archived"]),
        "group_archived": bool(row["group_archived"]),
        "revisions": revisions,
        "jobs": jobs,
        "active_jobs": [job["name"] for job in unsafe],
        "deletable": not unsafe,
    }


def group_deletion_info(gid):
    with connection() as db:
        group = db.execute(
            "SELECT * FROM groups WHERE id=?", (str(gid),)
        ).fetchone()
        if group is None:
            raise KeyError("Project group not found")
        ids = [
            row["id"]
            for row in db.execute("SELECT id FROM projects WHERE group_id=?", (str(gid),))
        ]
        revisions = (
            db.execute(
                "SELECT COUNT(*) FROM revisions r JOIN projects p ON p.id=r.project "
                "WHERE p.group_id=?",
                (str(gid),),
            ).fetchone()[0]
            if ids
            else 0
        )
        placeholders = ",".join("?" * len(ids)) if ids else "''"
        jobs = (
            db.execute(
                f"SELECT COUNT(*) FROM jobs j JOIN revisions r ON r.id=j.revision WHERE r.project IN ({placeholders})", tuple(ids)
            ).fetchone()[0]
            if ids
            else 0
        )
        models = db.execute(
            "SELECT COUNT(*) FROM projects WHERE group_id=? AND archived=0", (str(gid),)
        ).fetchone()[0]
    unsafe = _unsafe_jobs(ids) if ids else []
    return {
        "kind": "group",
        "id": str(gid),
        "name": group["name"],
        "archived": bool(group["archived"]),
        "models": len(ids),
        "unarchived_models": models,
        "revisions": revisions,
        "jobs": jobs,
        "active_jobs": [job["name"] for job in unsafe],
        "deletable": not unsafe,
    }


def projects(include_archived=False):
    with connection() as db:
        rows = [
            dict(r)
            for r in db.execute("""
            SELECT project AS id, r.id AS revision, r.number AS number, r.created AS created,
                   json_extract(setup,'$.name') AS name,
                   json_extract(setup,'$.dimension') AS dimension,
                   p.group_id AS "group", g.name AS group_name,
                   p.archived AS archived, g.archived AS group_archived,
                   (SELECT COUNT(*) FROM revisions WHERE project=p.id) AS revisions
            FROM projects p JOIN revisions r ON p.head=r.id
            LEFT JOIN groups g ON g.id=p.group_id ORDER BY r.created DESC""")
        ]
    result = []
    for row in rows:
        row["archived"] = bool(row["archived"])
        row["group_archived"] = bool(row["group_archived"])
        if row["archived"] and not include_archived:
            continue
        if row["group_archived"] and not include_archived:
            continue
        result.append(row)
    return result


def head_revision(project):
    """The revision a model's head currently points at."""
    with connection() as db:
        row = db.execute("SELECT head FROM projects WHERE id=?", (str(project),)).fetchone()
    if row is None:
        raise KeyError("Project not found")
    return row["head"]


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


def result_summary(row):
    """Parsed persisted result summary, or ``None`` when no result was published."""
    raw = row.get("result_summary")
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def result_available(row):
    """True when a validated result generation exists for this job.

    Solver outcome, extraction outcome and result availability stay independent:
    a failed solver can carry a valid partial generation, and a successful solve
    can have none. The persisted state is authoritative; a legacy completed row
    is marked complete by :func:`initialize`.
    """
    state = row.get("result_state") or "none"
    if state in {"partial", "complete"}:
        return True
    # Compatibility for a row read before the additive migration ran.
    return row.get("solver") == "Succeeded" and row.get("extraction") == "Succeeded"


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
    summary = result_summary(result)
    generation = int(result.get("result_generation") or 0)
    result["result"] = {
        # Summary facts first; the durable pointer and availability are
        # authoritative and must not be shadowed by a stale summary member.
        **(summary or {}),
        "state": result.get("result_state") or "none",
        "available": result_available(result),
        "summary": summary,
        "generation": generation,
        # The immutable generation directory (relative) and the pinned read
        # base. Legacy flat rows expose generation 0 and no base.
        "dir": result.get("result_dir") or "",
        "base": f"/api/jobs/{result['id']}/results/{generation}" if generation else "",
        "extraction_error": result.get("extraction_error") or "",
    }
    result["result_state"] = result["result"]["state"]
    result["extraction_error"] = result.get("extraction_error") or ""
    result["salvage"] = int(result.get("salvage") or 0)
    result.pop("token", None)
    return result


JOB_SELECT = """SELECT j.*,r.project,r.number,
 json_extract(r.setup,'$.dimension') AS dimension,json_extract(r.setup,'$.name') AS project_name,
 p.group_id AS "group",g.name AS group_name,
 (SELECT labels FROM fixtures f WHERE f.job=j.id) AS review_labels,
 (SELECT labels_hash FROM fixtures f WHERE f.job=j.id) AS review_labels_hash
 FROM jobs j JOIN revisions r ON j.revision=r.id JOIN projects p ON p.id=r.project
 LEFT JOIN groups g ON g.id=p.group_id"""


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


def fixture(jid):
    """The reviewed fixed-node set for a mesh job, or ``None`` before review."""
    with connection() as db:
        row = db.execute("SELECT * FROM fixtures WHERE job=?", (str(jid),)).fetchone()
    if row is None:
        return None
    labels = json.loads(row["labels"])
    return {
        "labels": labels,
        "count": len(labels),
        "hash": row["labels_hash"],
        "mesh_digest": row["mesh_digest"],
        "updated": row["updated"],
    }


def set_fixture(jid, mesh_digest, labels_hash, labels):
    """Unconditional write, kept for internal migrations and tests."""
    with connection(True) as db:
        db.execute(
            "INSERT INTO fixtures VALUES (?,?,?,?,?) ON CONFLICT(job) DO UPDATE SET "
            "mesh_digest=excluded.mesh_digest, labels_hash=excluded.labels_hash, "
            "labels=excluded.labels, updated=excluded.updated",
            (str(jid), mesh_digest, labels_hash, encoded(labels), time.time()),
        )
    return job(jid)


def set_fixture_checked(jid, mesh_digest, labels_hash, labels, expected_hash=None):
    """Compare-and-set one reviewed fixture inside one serialized transaction.

    The expected hash, job eligibility, mesh identity and the update are checked
    with the write lock held (``BEGIN IMMEDIATE``), so two tabs that read the
    same reviewed hash cannot both win. ``expected_hash=None`` is the documented
    legacy unconditional write used by pre-concurrency clients.
    """
    with connection(True) as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (str(jid),)).fetchone()
        if (
            row is None
            or row["mode"] != "MESH"
            or status(row) != "Completed"
            or not row["mesh_digest"]
        ):
            raise Conflict("Generate the mesh before reviewing its fixed nodes.")
        if mesh_digest and row["mesh_digest"] != mesh_digest:
            raise Conflict(
                "The mesh identity changed while the fixed nodes were edited. "
                "Reopen Mounting and review the current mesh."
            )
        current = db.execute("SELECT * FROM fixtures WHERE job=?", (str(jid),)).fetchone()
        current_hash = current["labels_hash"] if current else ""
        if expected_hash is not None and expected_hash != current_hash:
            count = len(json.loads(current["labels"])) if current else 0
            raise Conflict(
                "The fixed nodes were changed by another tab or session. Reopen Mounting "
                f"to see the current selection ({count} nodes), then save again."
            )
        db.execute(
            "INSERT INTO fixtures VALUES (?,?,?,?,?) ON CONFLICT(job) DO UPDATE SET "
            "mesh_digest=excluded.mesh_digest, labels_hash=excluded.labels_hash, "
            "labels=excluded.labels, updated=excluded.updated",
            (str(jid), row["mesh_digest"], labels_hash, encoded(labels), time.time()),
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
    expected_fixture=None,
    output_dir=None,
):
    jid = token if mode == "IMPORT" else new_id()
    if mode == "DEMO":
        raise Conflict(
            "DEMO execution is no longer available for new submissions. "
            "Historical DEMO evidence remains readable."
        )
    with connection(True) as db:
        # The caller read the revision outside this transaction. A permanent
        # deletion may have won in between; fail with a clear 404 instead of a
        # foreign-key error, and never resurrect work for a deleted model.
        if not db.execute("SELECT 1 FROM revisions WHERE id=?", (str(rev),)).fetchone():
            raise KeyError("Revision not found")
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
                if mesh_artifact_state(record["id"], record["mesh_digest"]) != "ok":
                    raise Conflict(
                        "The active mesh file is missing or unreadable. Generate the mesh again "
                        "in Mesh, then review the fixed nodes. Review does not regenerate a mesh "
                        "automatically."
                    )
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
                # The engineer prepared this deck from a specific reviewed fixture.
                # If another tab changed it after that review, conflict instead of
                # silently snapshotting the newer selection.
                if expected_fixture is not None and fixture["labels_hash"] != expected_fixture:
                    raise Conflict(
                        "The fixed nodes changed after you reviewed them. Reopen Mounting, "
                        "confirm the current selection, then prepare the input deck again."
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
                       input_hash,mesh_digest,mesh_compat,fixture_hash,fixture_labels,output_dir)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                    output_dir,
                ),
            )
    return job(jid)


def set_publication(jid, result_file, publication):
    with connection(True) as db:
        db.execute(
            "UPDATE jobs SET result_file=?, publication=? WHERE id=?",
            (result_file, publication, str(jid)),
        )


def import_result_job(revision, name, members, provenance, availability="complete", package_path=None):
    """Materialize an opened portable result as a read-only historical job.

    The result is never resubmitted or re-extracted. The package becomes one
    immutable generation directory, and every terminal fact it carries is kept
    independently: solver outcome, extraction outcome, availability, last saved
    step/time, origin identity and diagnostics. A legacy package that simply did
    not record a fact is reported as ``Unknown`` rather than guessed as Failed.
    """
    jid = new_id()
    directory = job_dir(jid)
    directory.mkdir(parents=True, exist_ok=True)
    state = "partial" if availability == "partial" else "complete"
    try:
        index = json.loads(members.get("results.json", b"{}").decode("utf-8"))
    except (TypeError, ValueError):
        index = {}
    provenance = provenance if isinstance(provenance, dict) else {}
    origin = provenance.get("job") or {}
    facts = provenance.get("result") or {}
    solver_outcome = (
        index.get("solver_outcome")
        or facts.get("solver_outcome")
        or origin.get("solver")
        or "Unknown"
    )
    extraction_outcome = (
        facts.get("extraction_outcome")
        or facts.get("extraction")
        or origin.get("extraction")
        or "Unknown"
    )
    failure_reason = index.get("failure_reason") or facts.get("failure_reason") or ""
    # One immutable generation directory holds exactly the packaged members.
    generation_dir = directory / "results" / f"gen-1-{jid}"
    generation_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for member, payload in members.items():
        if member == "setup.json":
            continue
        if member.startswith("frames/"):
            target = generation_dir / Path(member).name
        elif member in {"results.json", "history.csv", "provenance.json"}:
            target = generation_dir / Path(member).name
        else:
            continue
        target.write_bytes(payload)
        manifest.append(target.name)
    from integrations.abaqus import interchange

    try:
        interchange.write_json(
            generation_dir / "manifest.json",
            interchange.generation_manifest(generation_dir, f"import-{jid}"),
        )
    except (OSError, ValueError):
        pass
    now = time.time()
    summary = {
        "availability": state,
        "solver_outcome": solver_outcome,
        "extraction_outcome": extraction_outcome,
        "failure_reason": failure_reason,
        "last_step": index.get("last_step"),
        "last_step_id": index.get("last_step_id"),
        "last_role": index.get("last_role"),
        "last_local_s": index.get("last_local_s"),
        "last_total_s": index.get("last_total_s"),
        "frames": len(index.get("frames") or []),
        "history_only": bool(index.get("history_only")),
        "initial_only": bool(index.get("initial_only")),
        "skipped": len(index.get("skipped_frames") or []),
        "frame_ordinal": index.get("last_frame_ordinal"),
        "native_frame_id": index.get("last_native_frame_id"),
        "increment": index.get("last_increment"),
        "imported": True,
        "origin_job": str(origin.get("id") or ""),
        "origin_name": str(origin.get("name") or ""),
        "generation": 1,
        "result_dir": f"results/gen-1-{jid}",
        "provenance_complete": solver_outcome != "Unknown" and extraction_outcome != "Unknown",
    }
    with connection(True) as db:
        db.execute(
            """INSERT INTO jobs(id,revision,name,mode,scenario,cpus,token,created,started,ended,
                   solver,extraction,phase,diagnostic,step,increment,step_time,manifest,
                   result_file,publication,result_state,result_summary,result_generation,result_dir)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                jid,
                str(revision),
                name[:200],
                "ABAQUS",
                "imported",
                1,
                new_id(),
                now,
                origin.get("created") or now,
                origin.get("ended") or now,
                solver_outcome,
                extraction_outcome,
                "Partial result imported from a portable file"
                if state == "partial"
                else "Results imported from a portable file",
                failure_reason,
                index.get("last_step"),
                index.get("last_increment"),
                index.get("last_local_s"),
                encoded(sorted(set(manifest))),
                str(package_path or origin.get("id") or ""),
                "Imported",
                state,
                encoded(summary),
                1,
                f"results/gen-1-{jid}",
            ),
        )
    return job(jid)


def import_mesh_job(revision, digest, compat, members, fixture=None):
    """Materialize a compatible mesh carried by a portable model file.

    The bytes are copied verbatim, so the recorded digest and the existing
    identity comparison keep working and nothing is regenerated. ``fixture`` is
    ``{"labels": [...], "hash": "..."}`` after it was validated against these
    exact bytes, or ``None`` when the file carries no reviewable fixture.
    """
    jid = new_id()
    directory = job_dir(jid)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "mesh.json").write_bytes(members["mesh.json"])
    names = ["mesh.json"]
    if members.get("mesh-identity.json"):
        (directory / "mesh-identity.json").write_bytes(members["mesh-identity.json"])
        names.append("mesh-identity.json")
    now = time.time()
    with connection(True) as db:
        db.execute(
            """INSERT INTO jobs(id,revision,name,mode,scenario,cpus,token,created,started,ended,
                   solver,extraction,phase,mesh_digest,mesh_compat,manifest)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                jid,
                str(revision),
                "Mesh from file",
                "MESH",
                "imported",
                1,
                new_id(),
                now,
                now,
                now,
                "Succeeded",
                "Succeeded",
                "Mesh imported from a portable file",
                digest,
                compat,
                encoded(names),
            ),
        )
        if fixture:
            db.execute(
                "INSERT INTO fixtures VALUES (?,?,?,?,?)",
                (jid, digest, fixture["hash"], encoded(fixture["labels"]), now),
            )
    return job(jid)


def claim(owner):
    with connection(True) as db:
        # Synthetic DEMO execution is withdrawn. A queued legacy DEMO row is never
        # converted into a licensed job, relocated or relaunched.
        row = db.execute("""SELECT id,solver FROM jobs WHERE owner IS NULL
          AND mode IN ('ABAQUS', 'MESH', 'DECK', 'IMPORT')
          AND (
            (solver='Queued' AND cancelled=0)
            OR (solver='Succeeded' AND extraction='Queued' AND cancelled=0)
            OR (solver IN ('Failed','Cancelled') AND extraction='Queued'
                AND salvage=1 AND cancelled=0)
          )
          ORDER BY created LIMIT 1""").fetchone()
        if not row:
            return None
        extracting = row["solver"] != "Queued"
        now = time.time()
        db.execute(
            """UPDATE jobs SET owner=?,heartbeat=?,started=coalesce(started,?),
          solver=?,extraction=?,phase=?,cancel_scope=NULL,cancelled=0 WHERE id=?""",
            (
                owner,
                now,
                now,
                row["solver"] if extracting else "Preparing",
                "Running" if extracting else "Pending",
                "Recovering saved results" if extracting else "Preparing input",
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
        "result_state",
        "result_summary",
        "extraction_error",
        "result_generation",
        "result_dir",
        "salvage",
        "cancel_scope",
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
        # Repeated cancel/duplicate requests are idempotent: the request is a
        # flag on the row, not a second action.
        if row["cancelled"]:
            return job(jid)
        # A finished solver may still have a queued or running extraction (a
        # salvage attempt, or the existing retry path). Cancelling then stops the
        # extraction only; it must never be read later as cancelling a solver that
        # had already stopped, and it must not block a deliberate new attempt.
        if row["solver"] in {"Succeeded", "Failed", "Cancelled"}:
            if row["extraction"] not in {"Queued", "Running"}:
                raise Conflict("Job has already finished.")
            scope = "extraction"
        elif status(row) in TERMINAL:
            raise Conflict("Job has already finished.")
        else:
            scope = "solver"
        db.execute(
            "UPDATE jobs SET cancelled=1,cancel_scope=? WHERE id=?", (scope, jid)
        )
        if not row["owner"]:
            column = "solver" if scope == "solver" else "extraction"
            db.execute(
                f"UPDATE jobs SET {column}='Cancelled',phase='Cancelled in queue',ended=? WHERE id=?",
                (time.time(), jid),
            )
    return job(jid)


def _candidate_evidence(directory):
    """Whether a terminal run left a possible native result to re-read.

    This is only a candidate test: nothing here claims the ODB is readable,
    complete or that the process stopped. The extractor validates the file
    itself; an unreadable or empty ODB produces a concrete diagnostic.
    """
    odb = directory / "analysis.odb"
    metadata = directory / "result-metadata.json"
    if not odb.is_file() or not metadata.is_file() or not odb.stat().st_size:
        return False, "No native ODB candidate and submitted metadata are available."
    return True, ""


def authorize_extraction(jid):
    """Queue one extraction-only attempt for a terminal run; never a solver.

    Used both by the automatic salvage path and by an explicit engineer action on
    an eligible historical job. A stale solver cancellation flag is cleared here
    so it cannot suppress reading an already stopped analysis. The previous
    usable result generation stays readable while the new attempt runs.
    """
    with connection(True) as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (str(jid),)).fetchone()
        if row is None:
            raise KeyError("Job not found")
        if row["mode"] != "ABAQUS":
            raise Conflict("Only an Abaqus analysis has native results to recover.")
        if row["owner"]:
            raise Conflict("This run is still owned by a worker; wait for reconciliation.")
        if row["solver"] not in {"Succeeded", "Failed", "Cancelled"}:
            raise Conflict("Wait for the solver to finish before extracting results.")
        if row["extraction"] in {"Queued", "Running"}:
            raise Conflict("An extraction is already queued for this run.")
        possible, reason = _candidate_evidence(job_dir(jid))
        if not possible:
            raise Conflict(reason)
        db.execute(
            """UPDATE jobs SET extraction='Queued',cancelled=0,cancel_scope=NULL,
               salvage=1,extraction_error='',phase='Awaiting result recovery',
               extraction_exit=NULL,ended=NULL WHERE id=?""",
            (str(jid),),
        )
    return job(jid)


def publish_result_generation(
    jid, owner, expected_generation, summary, generation, result_dir, availability, manifest
):
    """Atomically switch the durable result pointer and summary.

    The generation directory was already finalized on disk. This transaction is
    the only action that makes it authoritative. It is fenced on owner, expected
    generation and cancellation so a late, stale or cancelled attempt cannot
    replace a newer generation. Returns a reason string; ``ok`` means committed.
    """
    state = "partial" if availability == "partial" else "complete"
    if isinstance(manifest, str):
        try:
            manifest = json.loads(manifest)
        except (TypeError, ValueError):
            manifest = []
    with connection(True) as db:
        row = db.execute(
            "SELECT owner,cancelled,result_generation FROM jobs WHERE id=?", (str(jid),)
        ).fetchone()
        if row is None:
            return "missing"
        if row["owner"] != owner:
            return "lease"
        if int(row["result_generation"] or 0) != int(expected_generation):
            return "generation"
        if row["cancelled"]:
            return "cancelled"
        cursor = db.execute(
            """UPDATE jobs SET result_state=?,result_summary=?,result_generation=?,result_dir=?,
               extraction='Succeeded',extraction_error='',salvage=0,cancel_scope=NULL,
               owner=NULL,heartbeat=?,ended=?,manifest=?,phase=?
               WHERE id=? AND owner=? AND result_generation=? AND cancelled=0""",
            (
                state,
                encoded(summary),
                int(generation),
                str(result_dir),
                time.time(),
                time.time(),
                encoded(sorted(set(manifest))),
                "Partial results ready" if state == "partial" else "Results ready",
                str(jid),
                owner,
                int(expected_generation),
            ),
        )
        return "ok" if cursor.rowcount == 1 else "fenced"


def result_generation_dir(jid, generation=None):
    """Resolve the immutable directory for a pinned generation.

    Returns ``(base, generation)``; ``(None, 0)`` for a legacy flat-file row.
    Raises ``KeyError`` when the requested generation is not retained.
    """
    row = job(jid)
    current = int(row["result"]["generation"] or 0)
    if not current:
        return None, 0
    requested = current if generation is None else int(generation)
    if requested < 1 or requested > current:
        raise KeyError("Result generation unavailable")
    directory = job_dir(jid).resolve()
    if requested == current and row["result"].get("dir"):
        base = (directory / row["result"]["dir"]).resolve()
    elif requested == current:
        # A retained row written before generation directories (or an imported
        # result from an older build) keeps its flat files as the pinned store.
        base = directory
    else:
        candidates = sorted((directory / "results").glob(f"gen-{requested}-*"))
        if not candidates:
            raise KeyError("Result generation unavailable")
        base = candidates[0].resolve()
    try:
        base.relative_to(directory)
    except ValueError as exc:
        raise KeyError("Result generation unavailable") from exc
    if not (base / "results.json").is_file():
        raise KeyError("Result generation unavailable")
    return base, requested


def retry(jid):
    """Retry extraction after a failed attempt or a partial generation.

    A partial result can be re-read from the same ODB when the engineer believes
    more frames are available; this still never relaunches a solver.
    """
    row = job(jid)
    if row["solver"] not in {"Succeeded", "Failed", "Cancelled"}:
        raise Conflict("Only a finished solver can have its results retried.")
    recoverable = row["extraction"] in {"Failed", "Cancelled", "Pending"} or (
        row.get("result_state") == "partial"
    )
    if not recoverable:
        raise Conflict("Only an unsuccessful or partial extraction can be retried.")
    return authorize_extraction(jid)


def deletion_journal_dir():
    path = root() / "deletions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_journal(token, kind, target, payload, status):
    now = time.time()
    with connection(True) as db:
        db.execute(
            "INSERT INTO deletions VALUES (?,?,?,?,?,?,?) ON CONFLICT(token) DO UPDATE SET "
            "payload=excluded.payload,status=excluded.status,updated=excluded.updated",
            (token, kind, str(target), encoded(payload), status, now, now),
        )


def _safe_remove_job(job_id):
    try:
        path = job_dir(job_id)
    except ValueError:
        return
    shutil.rmtree(path, ignore_errors=False) if path.exists() else None


def _safe_remove_drawing(source_id):
    if not source_id:
        return
    try:
        path = root() / "drawings" / str(UUID(str(source_id)))
    except ValueError:
        return
    if path.parent != root() / "drawings":
        return
    if path.exists():
        shutil.rmtree(path)


def _cleanup_journal(token, payload):
    """Remove artifacts after the database rows are gone; idempotent.

    A drawing directory is shared by duplicated models, so it is removed only
    when no remaining revision references the source id.
    """
    for job_id in payload.get("jobs", []):
        try:
            with connection() as db:
                if db.execute("SELECT 1 FROM jobs WHERE id=?", (str(job_id),)).fetchone():
                    continue
            _safe_remove_job(job_id)
        except (OSError, ValueError):
            return False
    for source_id in payload.get("sources", []):
        try:
            with connection() as db:
                if db.execute(
                    "SELECT 1 FROM revisions WHERE source_id=? LIMIT 1", (str(source_id),)
                ).fetchone():
                    continue
            _safe_remove_drawing(source_id)
        except (OSError, ValueError):
            return False
    with connection(True) as db:
        db.execute("DELETE FROM deletions WHERE token=?", (token,))
    return True


def recover_deletions():
    """Finish (or safely abandon) an interrupted permanent-deletion cleanup.

    If the transaction never committed, the rows still exist and the journal is
    discarded without deleting anything. If it committed, orphan artifacts are
    removed. Filesystem errors leave the journal for the next startup.
    """
    with connection() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM deletions")]
    complete = True
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except ValueError:
            payload = {}
        with connection() as db:
            if row["kind"] == "group":
                exists = db.execute(
                    "SELECT 1 FROM groups WHERE id=?", (row["target"],)
                ).fetchone()
            else:
                exists = db.execute(
                    "SELECT 1 FROM projects WHERE id=?", (row["target"],)
                ).fetchone()
        if exists and row["status"] == "pending":
            # The database transaction did not commit; keep its rows and files.
            with connection(True) as db:
                db.execute("DELETE FROM deletions WHERE token=?", (row["token"],))
            continue
        if not _cleanup_journal(row["token"], payload):
            complete = False
    return complete


def _expected_mismatch(expected, actual):
    """True when the caller previewed a different deletion impact."""
    if not expected:
        return False
    for key, value in expected.items():
        if value is None or key not in actual:
            continue
        if int(value) != int(actual[key]):
            return True
    return False


def _unsafe_rows(db, project_ids):
    if not project_ids:
        return []
    placeholders = ",".join("?" * len(project_ids))
    rows = [
        dict(row)
        for row in db.execute(
            JOB_SELECT + f" WHERE r.project IN ({placeholders})", tuple(project_ids)
        )
    ]
    unsafe = []
    for row in rows:
        public_row = public(row)
        if activity.classify(public_row) != activity.TERMINAL:
            unsafe.append(public_row)
    return rows, unsafe


def purge_project(pid, confirm=None, expected=None):
    """Permanently delete one model and its owned rows, without archiving it.

    The activity decision, the affected-ID enumeration and the row deletes all
    happen under one ``BEGIN IMMEDIATE`` transaction. A job queued or claimed
    before this writer wins is therefore visible to the decision; a writer that
    arrives afterwards either sees the model gone or waits until it is gone.
    The journal row is committed in the same transaction as the deletes, so a
    crash before the commit leaves neither deleted rows nor a cleanup journal.
    """
    token = new_id()
    with connection(True) as db:
        row = db.execute(
            "SELECT p.id, json_extract(r.setup,'$.name') AS name FROM projects p "
            "JOIN revisions r ON p.head=r.id WHERE p.id=?",
            (str(pid),),
        ).fetchone()
        if row is None:
            raise KeyError("Project not found")
        name = row["name"]
        job_rows, unsafe = _unsafe_rows(db, [str(pid)])
        if unsafe:
            raise Conflict(
                "The model still has active or unresolved work: "
                + ", ".join(job["name"] for job in unsafe)
                + ". Wait for it to finish before deleting."
            )
        if confirm is not None and confirm.strip() != name:
            raise Conflict("Type the exact model name to confirm permanent deletion.")
        job_ids = [job["id"] for job in job_rows]
        sources = [
            source["source_id"]
            for source in db.execute(
                "SELECT DISTINCT source_id FROM revisions WHERE project=? AND source_id IS NOT NULL",
                (str(pid),),
            )
        ]
        revisions = db.execute(
            "SELECT COUNT(*) FROM revisions WHERE project=?", (str(pid),)
        ).fetchone()[0]
        if _expected_mismatch(expected, {"revisions": revisions, "jobs": len(job_ids)}):
            raise Conflict(
                "The deletion impact changed after it was previewed. "
                "Review the revised counts and confirm again."
            )
        payload = {"kind": "model", "id": str(pid), "jobs": job_ids, "sources": sources}
        now = time.time()
        db.execute(
            "INSERT INTO deletions VALUES (?,?,?,?,?,?,?)",
            (token, "model", str(pid), encoded(payload), "pending", now, now),
        )
        placeholders = ",".join("?" * len(job_ids)) if job_ids else "''"
        db.execute(f"DELETE FROM fixtures WHERE job IN ({placeholders})", tuple(job_ids))
        db.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", tuple(job_ids))
        db.execute("DELETE FROM revisions WHERE project=?", (str(pid),))
        db.execute("DELETE FROM projects WHERE id=?", (str(pid),))
    _write_journal(token, "model", pid, payload, "committed")
    cleaned = recover_deletions()
    return {
        "id": str(pid),
        "name": name,
        "removed_jobs": len(job_ids),
        "cleanup": "done" if cleaned else "pending",
    }


def purge_group(gid, confirm=None, expected=None):
    """Permanently delete a whole project group, archived or not.

    Group membership is captured under the same write transaction that deletes
    it, so a model added after the preview is either part of the decision or
    cannot be inserted at all.
    """
    token = new_id()
    with connection(True) as db:
        group = db.execute("SELECT * FROM groups WHERE id=?", (str(gid),)).fetchone()
        if group is None:
            raise KeyError("Project group not found")
        # The internal file-document owner is not a user project: it has no
        # archive or delete control, and deleting it would destroy every
        # standalone document at once. Refuse it in the API, not only the UI.
        if group["internal"]:
            raise Conflict(
                "This group holds standalone file documents and cannot be deleted. "
                "Delete the individual models instead."
            )
        name = group["name"]
        projects_ = [
            row["id"]
            for row in db.execute("SELECT id FROM projects WHERE group_id=?", (str(gid),))
        ]
        job_rows, unsafe = _unsafe_rows(db, projects_)
        if unsafe:
            raise Conflict(
                "The project still has active or unresolved work: "
                + ", ".join(job["name"] for job in unsafe)
                + ". Wait for it to finish before deleting."
            )
        if confirm is not None and confirm.strip() != name:
            raise Conflict("Type the exact project name to confirm permanent deletion.")
        job_ids = [job["id"] for job in job_rows]
        placeholders = ",".join("?" * len(projects_)) if projects_ else "''"
        sources = (
            [
                source["source_id"]
                for source in db.execute(
                    f"SELECT DISTINCT source_id FROM revisions WHERE project IN ({placeholders}) "
                    "AND source_id IS NOT NULL",
                    tuple(projects_),
                )
            ]
            if projects_
            else []
        )
        revisions = (
            db.execute(
                f"SELECT COUNT(*) FROM revisions WHERE project IN ({placeholders})",
                tuple(projects_),
            ).fetchone()[0]
            if projects_
            else 0
        )
        if _expected_mismatch(
            expected,
            {"models": len(projects_), "revisions": revisions, "jobs": len(job_ids)},
        ):
            raise Conflict(
                "The deletion impact changed after it was previewed. "
                "Review the revised counts and confirm again."
            )
        payload = {
            "kind": "group",
            "id": str(gid),
            "projects": projects_,
            "jobs": job_ids,
            "sources": sources,
        }
        now = time.time()
        db.execute(
            "INSERT INTO deletions VALUES (?,?,?,?,?,?,?)",
            (token, "group", str(gid), encoded(payload), "pending", now, now),
        )
        placeholders_jobs = ",".join("?" * len(job_ids)) if job_ids else "''"
        db.execute(
            f"DELETE FROM fixtures WHERE job IN ({placeholders_jobs})", tuple(job_ids)
        )
        db.execute(f"DELETE FROM jobs WHERE id IN ({placeholders_jobs})", tuple(job_ids))
        if projects_:
            placeholders_projects = ",".join("?" * len(projects_))
            db.execute(
                f"DELETE FROM revisions WHERE project IN ({placeholders_projects})",
                tuple(projects_),
            )
            db.execute(
                f"DELETE FROM projects WHERE id IN ({placeholders_projects})",
                tuple(projects_),
            )
        db.execute("DELETE FROM groups WHERE id=?", (str(gid),))
    _write_journal(token, "group", gid, payload, "committed")
    cleaned = recover_deletions()
    return {
        "id": str(gid),
        "name": name,
        "removed_models": len(projects_),
        "removed_jobs": len(job_ids),
        "cleanup": "done" if cleaned else "pending",
    }


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()
