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
3. Verify the product name: the header, browser title, API title and generated deck heading all read
   **Abaqus QOL**.
4. Verify the default interface language is Japanese on a clean profile, and that English switching
   persists across a reload.
5. Verify an existing installation's data directory still opens its projects (see
   `docs/migration-and-recovery.md`).
6. Run one DEMO closing case end to end and confirm the synthetic-result labelling is visible on the
   dashboard, run banner, result page and CSV.
7. Do **not** claim engineering production readiness unless the physical validation gate has passed
   with authorized licensed evidence.

## Optional licensed checks (never in public CI)

- `SIMPLIFY_ABAQUS_TEST_LAUNCHER` set, then `python -m pytest -q` executes the installed-runtime ODB
  round trip. This submits no solver job.
- Authorized closing analysis and reference comparison: see `docs/engineering-validation.md`.
