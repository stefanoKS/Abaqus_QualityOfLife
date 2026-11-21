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
directory.

## Backup

1. Stop the application as above.
2. Copy the entire data directory, keeping the directory structure.
3. Record the application version and the current git commit with the backup.

The database is append-only for revisions, so a backup taken after a clean shutdown is self-consistent
without further tooling.

## Restore

1. Stop the application.
2. Move the current directory aside (do not delete it).
3. Copy the backup into place and start the application.
4. Open a project and one historical run; verify the artifact downloads.

## Database schema

Schema version 1 is unchanged by this release; project grouping is additive.

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

## Artifacts and retention

Artifacts are restricted to a known filename allowlist inside each run directory. Nothing is deleted
automatically. Plan disk space for ODBs and frame files; purge old run directories manually only after
confirming the corresponding revision is no longer needed.
