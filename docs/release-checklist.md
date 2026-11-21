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
Windows-specific process handling. No paid Abaqus license is required or used in CI.

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
   that an unrelated process on the port produces the "used by another application" message.
5. Verify the default interface language is Japanese on a clean profile, and that English switching
   persists across a reload and preserves an in-progress selection.
6. Verify an existing installation's data directory still opens its projects and that legacy models
   appear under the `Imported projects` group (see `docs/migration-and-recovery.md`).
7. Run one DEMO closing case end to end and confirm the synthetic-result labelling is visible on the
   dashboard, run banner, result page and CSV; confirm the door-response plot and the exported
   displayed-curve CSV agree under both sign toggles.
8. Confirm the mesh-first workflow: **Generate mesh** with no fixture, box-select nodes on the mesh,
   **Save fixed nodes**, **Prepare input deck**, then submit. Change panel travel and confirm the mesh
   and nodes survive; change the mesh size and confirm the fixture must be reviewed again.
9. Do **not** claim engineering production readiness unless the physical validation gate has passed
   with authorized licensed evidence.

## Optional licensed checks (never in public CI)

- `SIMPLIFY_ABAQUS_TEST_LAUNCHER` set, then `python -m pytest -q` executes the installed-runtime ODB
  round trip. This submits no solver job.
- Authorized closing analysis and reference comparison: see `docs/engineering-validation.md`, which
  records the executed door-only case (input/mesh hashes, WSFIX membership, RP trajectory, contact
  onset, projected force) and the remaining blockers.
