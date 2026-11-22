# Release checklist

## Automated gates

Run from the repository root. Every command must exit non-zero on failure.

| Gate | Command |
|---|---|
| Contract regeneration (inspect the diff) | `.\.venv\Scripts\python scripts\schema.py` |
| Python unit and integration tests | `.\.venv\Scripts\python -m pytest -q` |
| Translation completeness | `npm --prefix apps/web run test:i18n` |
| Source encoding quality | `npm --prefix apps/web run test:encoding` |
| TypeScript contract check | `npm --prefix apps/web run typecheck` |
| Production build (verified, immutable release) | `npm --prefix apps/web run build` |
| Browser end-to-end tests | `npm --prefix apps/web run test:browser` |

The build stages the whole bundle, verifies every referenced file, hashes the complete file manifest
and only then writes `dist/release.json`. A failed build exits non-zero and leaves the previous
manifest untouched. `/api/health` reports `releaseValid`; the launcher refuses to serve an incomplete
release. Confirm `releaseValid: true` and that `releaseFiles` matches the published directory.

Run the build and browser gates from an isolated implementation root, not from a checkout whose
`dist/` or data directory belongs to a running instance. A build publishes
`apps/web/releases/<content-id>/`; the record is `apps/web/dist/release.json`, and `/api/health`
reports the pinned `release`, `frontend` and `api`.

GitHub Actions runs the same set in `.github/workflows/ci.yml` on Windows, because the worker uses
Windows-specific process handling. No paid Abaqus license is required or used in CI: the browser suite
starts its own API and worker with disposable data and a launcher double at the solver/extractor
boundary.

## Supported version matrix

| Component | Version |
|---|---|
| Windows application Python | 3.11 |
| Abaqus 2024 bundled Python | 3.10.5 (extractor only) |
| Node.js | 24.x |
| npm | 11.x |

Python dependencies are pinned in `requirements.txt` / `requirements.lock.txt`; npm dependencies are
locked by `apps/web/package-lock.json` and installed with `npm ci`.

## Manual release steps

1. Confirm `docs/implementation-report.md` reflects this build.
2. Confirm the gate matrix has an honest status for every gate, including BLOCKED entries.
3. Verify the product name: the header wordmark, browser title, API title and generated deck heading
   all read **Abaqus QOL**. The header logo must be the bundled production asset
   (`dist/assets/logo-*.png`) in both languages, with one accessible product name.
4. Verify double-clicking `start-abaqus-qol.cmd` prepares a missing environment/bundle, waits for
   `/api/health`, and opens the browser; verify a second double-click reuses the running instance and
   that an unrelated process on the port produces the "used by another application" message. Verify a
   custom port (`--port N`) starts its own instance with its own `SEAL_DATA` and does not join the
   default instance, and that a second port on the same data directory is refused with the owner's PID.
   Verify a second worker on the same directory exits non-zero. Verify `--takeover` refuses while any
   IMPORT/MESH/DECK/ABAQUS job is queued, preparing, waiting for a license, running, cancelling,
   extracting, disconnected or termination-unconfirmed, and when the job list cannot be read.
   Verify a reconciled idle instance can be taken over, and that killing the launcher leaves the
   worker lock held so a relaunch fails closed until the worker exits.
5. Verify release pinning: start instance A, rebuild from another root (or with a changed source) to
   publish release B, refresh A, and confirm A still serves its original entry asset and reports its
   original `release`/`frontend`. Start B with separate data and confirm it serves its own pair.
6. Verify the compatibility banner with a simulated stale tab and with a mismatched `api` value:
   project creation, import, deck preparation and submission are disabled, the message is actionable
   in the current language, and reload/restart clears it. Confirm the API refuses an identified write
   from the stale pair with HTTP 409.
7. Verify the dashboard's project and model filters are separate, and that two same-named runs are
   distinguished by a short run ID and a timestamp with seconds.
8. Verify the default interface language is Japanese on a clean profile, and that English switching
   persists across a reload and preserves an in-progress selection. Check readable Japanese on Create
   model, Import, Mesh, Mounting, Review and Results, and on the language button.
9. Verify an existing installation's data directory still opens its projects and that legacy models
   appear under the `Imported projects` group (see `docs/migration-and-recovery.md`).
10. Verify a clean installation shows an empty dashboard, that creating a project and its first model
   opens Import with “No drawing imported”, and that the example is created only when its checkbox is
   ticked. Import without any unit checkbox: a declared-mm drawing, a unitless drawing (summary shows
   “Unitless drawing interpreted as mm”), an inches drawing (rejected naming inches), a cancelled
   picker and a corrupt file. Create two models, import two drawings with the same basename but
   different geometry, and confirm each model shows its own revision, digest and original download.
11. Confirm the Abaqus-only path: omitted mode resolves to ABAQUS, an explicit DEMO submission returns
   an actionable 422 and queues nothing, and a historical DEMO run still opens with its notice.
12. Confirm the mesh-first workflow: **Generate mesh** with no fixture, box-select nodes on the mesh,
   **Save fixed nodes**, **Prepare input deck**, then submit. Confirm Review performs no mesh
   submission. Change panel travel and confirm the mesh and nodes survive; change the mesh size and
   confirm regeneration asks for a deliberate Regenerate/Cancel and the fixture must be reviewed again.
13. Verify viewport and component review: middle-button drag pans without page scroll while wheel
    still zooms; no mesh hash appears in ordinary Mounting/Mesh/Review text; component rows show
    name, role, inclusion, element type and count with an included total equal to the mesh total;
    renaming a component persists through Save/reload, does not force a remesh, and Escape cancels.
    Repeat in Japanese and English.
14. Verify numeric and paste integrity: leave an invalid travel or mesh size in the field and confirm
    it stays visible, Save/Generate/Prepare/Submit and step navigation are refused, and Escape
    restores. Paste a hyperfoam table with one malformed middle row and confirm Apply is blocked, the
    saved card is unchanged on Cancel, and a corrected paste reaches the saved revision and deck.
15. Replay a completed run: confirm Results opens on von Mises with element probing when stress is
    present (otherwise displacement magnitude with node probing), the canvas is solid white with no
    grid, the legend reads 0.00–0.50 MPa by default, and the probe reports the actual value when a
    manual maximum saturates the colours. Delay a frame, scrub out of order, pan and zoom, switch
    field and deformed/undeformed, toggle mesh edges and node markers, and edit the range. Confirm
    the previous complete frame stays visible while loading, the camera does not reset, and each
    quantity's legend range is stable. Toggle Reverse X/Y in full view and
    after a deliberate zoom; confirm the visible axis limits mirror the data and reversing twice
    restores the interval.
16. Verify archive/delete: archive a model and a project, confirm they disappear by default, appear
    with **Show archived**, open read-only, and restore. Confirm a duplicate stays independent.
    Queue work and confirm permanent deletion is refused with the active job named. Delete an archived
    model with the typed confirmation and confirm its artifact directory is gone, a shared drawing used
    by its duplicate remains, and library materials remain. Simulate an interrupted cleanup and
    confirm the next startup finishes it without removing a live record.
17. Verify the two-step template without a license: choose body-then-door in Motion, confirm the body
    fields and missing-body rejection, and that body/door travel 0 is accepted as a hold (0/−5.5,
    +5/0, 0/0) with explicit zero BCs in the INP and a positive step duration. Mesh a model with one
    body and one door, and inspect the INP:
    Body seating before Closing, body held in step 2, door held in step 1, both reference points with
    U/RF history, WSFIX, two rigid bodies, and no `op=NEW`. Confirm the results step selector appears
    only for a two-step result. **Do not mark this physically validated without a licensed run.**
18. Verify defaults and element policy: a fresh blank model reports 0.5 mm and 1.0 s; a version-1
    model keeps its earlier values. Mesh the rubber example, inspect the actual INP by region,
    reconcile CPS4R/CPS3/R2D2 counts with Mesh, and confirm the enforced reduced-integration setting
    is not editable. Create a **compressible neo-Hookean** library card (C10 in MPa, D1 in MPa⁻¹),
    edit it to a new version, and confirm the INP contains `*Hyperelastic, neo Hooke` and the exact
    values. In an isolated data copy, remove or corrupt the active `mesh.json` and confirm Review
    names the recovery, deck preparation refuses, and a completed deck/run remains readable.
19. Verify diagnostics: while a fake or real job runs, the top card shows solver and extraction
    separately, the current step/increment/simulated time, and a determinate bar only when a valid
    fraction exists. Confirm 99% with running extraction and 100% only after extraction succeeds;
    confirm license wait, stale heartbeat, unknown step and failure states, and that no ETA is shown.
    For a two-step job, confirm the active step is highlighted.
20. Verify the material library: create a card on the Materials page, edit it twice, confirm v1 is
    unchanged and v2/v3 are readable; archive/restore; import model-local cards from two revisions and
    confirm same-named cards are not merged; assign a library version in a model, adopt a newer
    version, and confirm the mesh is reused, a new deck is required and old revisions/runs are
    unchanged. Compare two hyperfoam versions and confirm only measured points are plotted with units
    and version labels. Repeat in Japanese.
21. Do **not** claim engineering production readiness unless the physical validation gate has passed
    with authorized licensed evidence.

## Optional licensed checks (never in public CI)

- `SIMPLIFY_ABAQUS_TEST_LAUNCHER` set, then `python -m pytest -q` executes the installed-runtime ODB
  round trip. This submits no solver job.
- Authorized closing analysis and reference comparison: see `docs/engineering-validation.md`, which
  records the executed door-only case (input/mesh hashes, WSFIX membership, RP trajectory, contact
  onset, projected force) and the remaining blockers.
