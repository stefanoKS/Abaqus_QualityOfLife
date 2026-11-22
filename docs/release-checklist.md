# Release checklist

## Automated gates

Run from the repository root. Every command must exit non-zero on failure.

| Gate | Command |
|---|---|
| Python unit and integration tests | `.\.venv\Scripts\python -m pytest -q` |
| Translation completeness | `npm --prefix apps/web run test:i18n` |
| TypeScript contract check | `npm --prefix apps/web run typecheck` |
| Production build | `npm --prefix apps/web run build` |
| Browser end-to-end tests | `npm --prefix apps/web run test:browser` |

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
   custom port (`--port N`) starts its own instance and does not join the default instance.
5. Verify the default interface language is Japanese on a clean profile, and that English switching
   persists across a reload and preserves an in-progress selection. Check readable Japanese on Create
   model, Import, Mesh, Mounting, Review and Results, and on the language button.
6. Verify an existing installation's data directory still opens its projects and that legacy models
   appear under the `Imported projects` group (see `docs/migration-and-recovery.md`).
7. Verify a clean installation shows an empty dashboard, that creating a project and its first model
   opens Import with “No drawing imported”, and that the example is created only when its checkbox is
   ticked. Create two models, import two drawings with the same basename but different geometry, and
   confirm each model shows its own revision, digest and original download.
8. Confirm the Abaqus-only path: omitted mode resolves to ABAQUS, an explicit DEMO submission returns
   an actionable 422 and queues nothing, and a historical DEMO run still opens with its notice.
9. Confirm the mesh-first workflow: **Generate mesh** with no fixture, box-select nodes on the mesh,
   **Save fixed nodes**, **Prepare input deck**, then submit. Confirm Review performs no mesh
   submission. Change panel travel and confirm the mesh and nodes survive; change the mesh size and
   confirm regeneration asks for a deliberate Regenerate/Cancel and the fixture must be reviewed again.
10. Replay a completed run: delay a frame, scrub out of order, pan and zoom, switch component and
    deformed/undeformed. Confirm the previous complete frame stays visible while loading, the camera
    does not reset, and each quantity's legend range is stable.
11. Do **not** claim engineering production readiness unless the physical validation gate has passed
    with authorized licensed evidence.

## Optional licensed checks (never in public CI)

- `SIMPLIFY_ABAQUS_TEST_LAUNCHER` set, then `python -m pytest -q` executes the installed-runtime ODB
  round trip. This submits no solver job.
- Authorized closing analysis and reference comparison: see `docs/engineering-validation.md`, which
  records the executed door-only case (input/mesh hashes, WSFIX membership, RP trajectory, contact
  onset, projected force) and the remaining blockers.
