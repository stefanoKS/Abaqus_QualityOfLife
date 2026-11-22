# Migration, backup, recovery and rollback

## Data location

| Setting | Value |
|---|---|
| Default | `%LOCALAPPDATA%\SimplifyAbaqus` |
| Override (legacy, highest precedence) | `SEAL_DATA` |
| Override (alias) | `ABAQUS_QOL_DATA` |

`SEAL_DATA` wins when both are set. The new alias is only consulted when the legacy variable is empty.
This precedence is covered by `tests/test_configuration.py`.

### Why the directory is still called `SimplifyAbaqus`

The displayed product is **Abaqus QOL**, but the on-disk directory keeps its former name. Renaming it
would make a new installation create a fresh, empty database next to the user's real one, so existing
projects, revisions, run artifacts and ODBs would appear to have vanished. Continued use of the
existing directory is the safe default and requires no migration.

Moving to a differently named directory is therefore **explicit and optional**:

1. Stop the application completely (close the browser, press Ctrl+C in the serving terminal and wait
   for the worker to exit).
2. Copy the whole directory, including `workbench.sqlite3`, `workbench.sqlite3-wal`,
   `workbench.sqlite3-shm`, `jobs/` and `drawings/`, to the new location.
3. Set `SEAL_DATA` (or `ABAQUS_QOL_DATA`) to the new path and start the application.
4. Confirm the project list and one historical run still open before deleting the old copy.

Never copy a database while the API or worker is running. Never point two installations at the same
directory: the launcher and the API now enforce this with `<data>/instance.json`, which records the
owning PID, port, release and data digest. A second launch on another port with the same data
directory is refused before it starts a worker, naming the owning process; a separate `SEAL_DATA` is
required for an independent test instance. The record is removed on clean shutdown and is taken over
only when the recorded process no longer exists, so a crashed launch does not block the next one.

## Backup

1. Stop the application as above.
2. Copy the entire data directory, keeping the directory structure.
3. Record the application version, the current git commit and the `/api/health` fingerprint — `build`,
   `release`, `api`, `frontend` — with the backup.

The database is append-only for revisions, so a backup taken after a clean shutdown is self-consistent
without further tooling. A retainable run needs the SQLite file together with its referenced drawing,
mesh, deck, result and ODB directories under `<data>/drawings/` and `<data>/jobs/`; the two must be
restored as one unit or the revision/run links will point at missing artifacts. `cache/` may be
omitted (it is derived) but keeping it makes the restore faster.

Browser release directories (`apps/web/releases/<id>/`) live with the code, not with the data. They are
content-addressed and can be rebuilt from source; a restore does not need to copy them. A running
instance never depends on a newer build replacing them.

## Restore

1. Stop the application.
2. Move the current directory aside (do not delete it).
3. Copy the backup into place and start the application.
4. Open a project and one historical run; verify the artifact downloads.

## Database schema

Schema version 1 is unchanged by this release. Empty models are represented in the existing revision
JSON: `source.kind` gained the value `empty`, and a drawing-backed model is validated exactly as
before. Every previously saved revision still loads. No dummy vertex, component, material region,
filename or digest is written for an empty model.

Two additional startup behaviours are idempotent:

- A queued, never-started `DEMO` job is retired with `solver = Failed`, `phase = Withdrawn` and a
  diagnostic explaining that synthetic execution is no longer available. It is never converted into a
  licensed job or relaunched. Completed, failed and already-running historical DEMO rows are untouched.
- Result display metadata is derived into `<data>/cache/display/<job-id>-<digest>.json` for results
  that predate the recorded block. This cache is read-only with respect to the run directory; deleting
  it only makes the next request derive it again. It never triggers a solver run.

Schema version 1 is unchanged by this release; project grouping is additive. The release-safety pass
adds one table, `creations(token, group_id, project_id, revision_id, created)`, which records an
idempotent project-group-plus-first-model action. It is created with `CREATE TABLE IF NOT EXISTS`; no
existing row is rewritten, and a previous build ignores it. If the table is present but a retry row is
missing, the retry behaves like a first request and the transaction still creates both rows or
neither.

`services/store.py::initialize()` uses `CREATE TABLE IF NOT EXISTS`, so a fresh installation and an
existing database take the same path and repeated initialization is a no-op.

### Project-grouping migration (additive, idempotent)

1. `groups(id, name, created)` is created if missing.
2. `projects.group_id` is added with `ALTER TABLE` when the column is absent.
3. Every project whose `group_id` is `NULL` is assigned to a single `Imported projects` group created
   on demand.

The mesh-first workflow adds more additive schema in the same transaction style:

4. `jobs.mesh`, `jobs.mesh_digest`, `jobs.mesh_compat` and `jobs.fixture_hash` are added when absent.
5. `fixtures(job, mesh_digest, labels_hash, labels, updated)` is created if missing.

No existing row is rewritten. Legacy `BUILD` jobs remain readable through `GET /api/jobs/{id}` and their
artifacts stay downloadable; only new work uses `MESH` and `DECK`. Runs created before this change keep
pointing at their old build job in `jobs.build` and reopen normally, without remeshing.

Steps 2 and 3 run inside one `BEGIN IMMEDIATE` transaction, so an interrupted upgrade leaves the
database exactly as it was. Running the application again completes the migration. No revision row, run
row, artifact directory, drawing directory or file name changes, so:

- existing revision URLs keep working;
- existing run URLs, result links and artifact downloads keep working;
- the original drawing of an imported revision still resolves;
- editing one model in a group cannot touch a sibling model or its history.

Rollback: the column and table are additive. Restoring the previous directory copy, or simply running
the previous build against the same database (it ignores the extra table and column), both work. That
is covered by `tests/test_grouping.py::test_populated_legacy_database_migrates_once_without_moving_identities`.

## Unknown worker state

A job shows **Unknown / worker disconnected** when its owning worker has not sent a heartbeat for 30
seconds, or when the worker could not confirm that a child process stopped
(`phase = Process termination unconfirmed`).

The application deliberately does **not** resubmit such a job automatically. A second licensed solve
would consume additional license tokens and could corrupt or duplicate results.

Reconciliation procedure:

1. Open **Run diagnostics** and note the process ID, owner, last heartbeat, build hash and the run
   directory (`<data>/jobs/<job-id>`).
2. Inspect `worker.log`, `solver.log`, `analysis.sta`, `analysis.msg` and `analysis.dat`.
3. Check whether an Abaqus process for this run is still alive on the machine.
4. If the solver is still running, let it finish. Do not cancel it unless the run is genuinely
   unneeded.
5. If nothing is running and no ODB exists, the run did not produce results. Record the finding, then
   submit a **new** run from the saved revision. Reference the abandoned job ID in your notes.
6. If an ODB exists and the solver succeeded, extraction can be retried safely: **Retry extraction**
   requeues only the extraction stage and never re-runs the solver.

## Safe shutdown

| Action | Effect on a running solve |
|---|---|
| Close the browser | None. The worker keeps solving. |
| Stop the API (Ctrl+C in the serving terminal) | None. The worker keeps solving and writes to the database. |
| Stop the worker | The current child process is terminated; the job becomes `Unknown / worker disconnected`. |
| Cancel in the UI | Only the tracked child process tree of that job is terminated. |

The API and worker are separate processes by design so that an accidental page reload, browser crash
or API restart cannot destroy an expensive authorized analysis.

## Launcher instances

Each port has its own lock file under the repository, `<repo>/.local/serve-<port>.lock`. A healthy
instance already listening on the requested port is reused; a custom `--port` therefore starts a
separate instance instead of silently joining the default one. A stale lock is taken over when no
healthy instance answers on its recorded port. Closing the serving terminal stops that API and lets its
worker finish the current operation; other ports are unaffected.

## Artifacts and retention

Artifacts are restricted to a known filename allowlist inside each run directory. Nothing is deleted
automatically. Plan disk space for ODBs and frame files; purge old run directories manually only after
confirming the corresponding revision is no longer needed.
