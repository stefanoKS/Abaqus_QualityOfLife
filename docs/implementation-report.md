# Implementation report — Abaqus QOL hardening phase

Date: 2026-11-21
Baseline commit: `160f52f` (branch `main`, clean working tree)
Repository: `stefanoKS/Abaqus_QualityOfLife`

## A. Implementation summary

### Product identity (G1)

- Displayed product name is exactly **Abaqus QOL**: header brand, browser title, page metadata,
  FastAPI title, `scripts/serve.py` startup line, generated INP `*Heading`, README and user guides.
- `apps/web/package.json` and `package-lock.json` renamed to `abaqus-qol` (version `0.2.0`).
- The legacy data directory `%LOCALAPPDATA%\SimplifyAbaqus` is **kept**. Renaming it would create an
  empty database next to the user's real one and hide existing projects.
- New configuration aliases with documented, tested precedence: `SEAL_DATA` > `ABAQUS_QOL_DATA`,
  `SIMPLIFY_ABAQUS_LAUNCHER` > `ABAQUS_QOL_LAUNCHER`, `SEAL_ODA` > `ABAQUS_QOL_ODA`. The legacy
  names win, so existing startup scripts behave identically.
- A CMD starter (`start-abaqus-qol.cmd`) was added for machines with a restrictive PowerShell
  execution policy. The existing Python entry point is unchanged.
- No vendor-affiliation claim is made; the README states the tool is independent of Dassault Systèmes.

### Localization (G2)

- Typed dictionary architecture in `apps/web/src/i18n/` (`ja.ts` source of truth, `en.ts` typed as
  `Record<TranslationKey, string>`, provider in `index.tsx`).
- Japanese is the default regardless of `navigator.language`; the choice persists in
  `localStorage['abaqus-qol.language']`; `document.documentElement.lang` follows it.
- 330 keys, translated for the application shell, dashboard, all eight workflow stages, material
  editor, viewport, run diagnostics, results and error/state vocabulary. Locale formatting uses
  `ja-JP` / `en-US`.
- Backend vocabulary (job status, worker phase, run mode) is translated for display while the raw
  value remains in `data-state` and in API payloads. Engineering identifiers, units, element types,
  file extensions and SHA digests are never translated. Raw solver logs stay in their original form.
- Language switching re-renders without remounting the workspace, so drafts, selections, the active
  step and the viewport camera all survive.
- Two independent completeness gates: `tsc` (type-level) and `npm run test:i18n`.

### UI system (G3)

- `apps/web/src/theme/tokens.css` centralizes the palette, type scale, radii, spacing, focus ring and
  Japanese-capable font stack. Contrast ratios are computed and documented in the file header.
- 28+ duplicated literals in `style.css` migrated to tokens. Fifteen near-duplicate muted greys were
  consolidated onto `--color-text-muted`; one of them (`#667c84`, 4.39:1) failed WCAG AA.
- Base line height raised to 1.55 for Japanese; wide letter-spacing is now restricted to Latin text via
  `:lang(ja)`; the smallest labels were raised (12.2 px → 12.6 px, labels 13.1 px → 13.4 px).
- Non-colour status cues: workflow steps carry a check/lock/circle icon plus a screen-reader suffix;
  job badges keep the machine status in `data-status` and `title`.
- `NumberInput` was rewritten as draft-then-commit. The previous `key={value}` + `defaultValue`
  implementation remounted on every committed value, silently discarding in-progress typing and focus.
  The new field commits on Enter or blur, restores on Escape, and reports `aria-invalid` with a linked
  message and range hint.
- Primary/secondary/danger hierarchy preserved; blocked actions expose the reason through `title`.

### Frontend architecture (G4)

- `Workspace.tsx` responsibilities were separated into cohesive modules instead of a bulk file move:
  `features/workspace/WorkflowNavigation.tsx`, `features/workspace/AssemblyTree.tsx`,
  `features/workspace/workflowStates.ts`, `features/materials/MaterialEditor.tsx`,
  `features/mesh/meshQuality.ts`, `features/mesh/MeshReview.tsx`,
  `shared/components/{NumberInput,Facts}.tsx`.
- Workflow completion is derived from the saved engineering configuration (roles assigned, every region
  has a material, a mounting edge exists, motion is valid, a build completed, runs exist, results
  exist) instead of "the step was visited". Missing prerequisites mark dependent steps as blocked.
- Polling is now adaptive: 1400 ms while any job is non-terminal, 10 s when everything is finished.
- The VTK renderer is not recreated when the language changes (translation is read through a ref), so
  camera state is preserved.

### Materials (G5)

- Full card workflow: list, select, create, duplicate, rename, colour, model switch, edit, delete with
  a reference guard (blocked while any region uses the card, with the reason in the tooltip).
- Linear elastic: density, Young's modulus, Poisson's ratio, colour, name.
- Hyperfoam: editable uniaxial test-data table with add/remove row, three-column paste, and a chart.
- Validation: finite values, density > 0, E > 0, −1 < ν < 0.5, at least three samples. Errors block
  saving; engineering advice (non-monotonic axial strain, |lateral| > |axial|) is a separate warning.
- Versioning is unchanged and verified: the server increments `version` only on a real data
  difference; historical revisions keep their values; an unassigned card is not written to the deck.

### Geometry and mesh (G6)

- Mesh review now reports measured values only: node/element counts, counts by element type,
  per-region element counts, boundary edge divisions, shortest/longest element edge and the worst
  longest/shortest edge ratio within one element. Inverted/degenerate elements cannot appear because
  the mesher rejects them, and the UI says so rather than showing a score. No synthetic quality metric
  was introduced.
- The review step states explicitly that a successful mesh is not proof of analysis readiness.

### Results (G9)

- Added a variable selector (U, with unavailable outputs listed separately) and a component selector
  (magnitude, |U1|, |U2|, |U3|). Components are contoured by absolute value while the probe reports the
  signed value, so a ramp is never mistaken for a signed field.
- Missing variables display as unavailable, never as zero. Instance-qualified probe identity is
  unchanged. Provenance (DEMO vs solver) is shown in the results panel.
- The force–displacement plot keeps signed RF2, units and the active frame marker.

### Reliability (G10)

- Unknown-worker state remains non-resubmissible by design; recovery and safe-shutdown procedures are
  documented in `docs/migration-and-recovery.md`.
- The data-root resolution was refactored into an explicit, tested precedence function. No schema change
  and no destructive migration was introduced.

### Release engineering (G11)

- `.github/workflows/ci.yml` runs Python tests, the translation gate, typecheck, production build and
  the Playwright suite on `windows-latest` with `npm ci` and no Abaqus license.
- `docs/release-checklist.md` records the gates, the supported version matrix and the optional licensed
  checks.

### Documentation (G12)

- New: `docs/user-guide-ja.md`, `docs/user-guide-en.md`, `docs/architecture.md`,
  `docs/engineering-validation.md`, `docs/migration-and-recovery.md`, `docs/release-checklist.md`,
  `docs/implementation-report.md`.
- Rewritten: `README.md` (concise, bilingual pointers, DEMO-vs-Abaqus table, configuration precedence).
- Updated: `docs/engineering.md` (storage/config precedence, material card rules, mesh metrics,
  verification record).
- No screenshots are referenced, because none are checked in; the guides describe the actual labels.

### Bugs fixed

1. `NumberInput` remounted on every committed value, discarding in-progress typing and focus.
2. Fifteen muted text colours, one of which (4.39:1) failed WCAG AA, were replaced by a verified token.
3. The active workflow step rendered an "unconfigured" icon even when it was configured.
4. Negative lookups: the language selector's accessible name changed with the language, so a
   name-based locator became stale mid-test (fixed in tests; the UI itself was correct).
5. The dashboard, workspace and run view polled finished jobs every 1.2–1.4 s indefinitely.

## B. File change summary

### Added

| File | Reason |
|---|---|
| `apps/web/src/i18n/{ja.ts,en.ts,index.tsx}` | Typed localization with compile-time completeness |
| `apps/web/src/theme/tokens.css` | Central design tokens with computed contrast |
| `apps/web/src/shared/components/NumberInput.tsx` | Correct draft/commit numeric editing |
| `apps/web/src/shared/components/Facts.tsx` | Extracted presentational list |
| `apps/web/src/shared/hooks/polling.ts` | Adaptive polling cadence |
| `apps/web/src/features/workspace/{WorkflowNavigation.tsx,AssemblyTree.tsx,workflowStates.ts}` | Workspace responsibility split |
| `apps/web/src/features/materials/MaterialEditor.tsx` | Material card editor + validation |
| `apps/web/src/features/mesh/{meshQuality.ts,MeshReview.tsx}` | Measured mesh metrics and review UI |
| `apps/web/scripts/check-translations.mjs` | Independent translation-completeness gate |
| `apps/web/tests/{fixtures.ts,i18n.spec.ts,materials.spec.ts}` | English-selecting fixture, localization and material tests |
| `tests/test_configuration.py` | Product identity and configuration precedence |
| `.github/workflows/ci.yml` | Automated quality gates |
| `start-abaqus-qol.cmd` | Startup without PowerShell execution-policy changes |
| `docs/user-guide-ja.md`, `docs/user-guide-en.md`, `docs/architecture.md`, `docs/engineering-validation.md`, `docs/migration-and-recovery.md`, `docs/release-checklist.md`, `docs/implementation-report.md` | Documentation set |

### Modified

| File | Reason |
|---|---|
| `apps/web/src/main.tsx` | Product name, `<I18nProvider>`, language selector, translated labels |
| `apps/web/src/Dashboard.tsx` | Localized, translated status badges, adaptive polling |
| `apps/web/src/Workspace.tsx` | Localized, extracted components, material editor, mesh review, guarded save |
| `apps/web/src/RunView.tsx` | Localized, variable/component selector, provenance, adaptive polling |
| `apps/web/src/Viewport.tsx` | Localized, component contouring, camera preserved across language change |
| `apps/web/src/viewportModel.ts` | `resultComponent`/`resultLabel` support |
| `apps/web/src/api.ts` | Removed English-only `date`/`demoNotice` (now locale-aware in i18n) |
| `apps/web/src/style.css` | Token migration, Japanese typography, new component styles |
| `apps/web/index.html` | `lang="ja"`, title `Abaqus QOL`, description |
| `apps/web/package.json`, `package-lock.json` | Package renamed to `abaqus-qol`, `test:i18n` script |
| `apps/web/tests/{jobs,picking,workflow}.spec.ts` | Use the English-selecting fixture |
| `services/store.py` | Explicit data-root precedence, legacy directory name, clearer error |
| `services/api/main.py` | FastAPI title/version |
| `integrations/abaqus/launcher.py` | Launcher alias with legacy precedence |
| `integrations/abaqus/deck.py` | Generated heading now reads "Abaqus QOL" |
| `integrations/drawings.py` | ODA alias |
| `scripts/serve.py` | Startup identity, alias cleanup in test mode |
| `README.md`, `docs/engineering.md` | Naming, configuration, verification record |

### Removed

None. No source file, project record, artifact or test was deleted.

## C. Test results

Environment: Windows, Python 3.11.4 in `.venv`, Node.js 24.16.0, npm 11.13.0, Edge with WebGL.

| Suite | Command | Passed | Failed | Skipped | Result |
|---|---|---|---|---|---|
| Python (baseline, before changes) | `.\.venv\Scripts\python -m pytest -q` | 32 | 0 | 1 | PASS |
| Python (final) | `.\.venv\Scripts\python -m pytest -q` | 39 | 0 | 1 | PASS |
| Translation completeness | `npm --prefix apps/web run test:i18n` | 330 keys | 0 | 0 | PASS |
| TypeScript | `npm --prefix apps/web run typecheck` | — | 0 | — | PASS |
| Production build | `npm --prefix apps/web run build` | — | 0 | — | PASS (chunk-size warning only) |
| API contract | `.\.venv\Scripts\python scripts\schema.py` | — | 0 | — | PASS (no diff in `generated.ts`) |
| Browser (baseline, before changes) | `npm --prefix apps/web run test:browser` | 5 | 0 | 0 | PASS |
| Browser (final) | `npm --prefix apps/web run test:browser` | 12 | 0 | 0 | PASS |

The single skipped Python test is `tests/test_abaqus.py::test_installed_odb_round_trip`, gated on
`SIMPLIFY_ABAQUS_TEST_LAUNCHER`. It requires an installed Abaqus runtime and was not available here.

New Python tests: `tests/test_configuration.py` (7 tests: default legacy directory, alias used when
legacy absent, legacy wins when both set, seed idempotency, launcher alias precedence and diagnostic,
ODA alias, API title).

New browser tests: `tests/i18n.spec.ts` (6) and `tests/materials.spec.ts` (1).

## D. Check-gate matrix

| Gate | Status | Evidence | Outstanding | Next action |
|---|---|---|---|---|
| **G0** Baseline | **PASS** | Clean tree at `160f52f`; 32 Python passed / 1 skipped; typecheck, build and 5/5 browser tests passed before any edit | Baseline recorded as the regression reference | — |
| **G1** Product identity | **PASS** | Brand, title, API title, startup line, deck heading, package name, docs updated. Legacy directory retained; aliases tested by `tests/test_configuration.py`. No vendor affiliation implied. Remaining `SimplifyAbaqus`/`SIMPLIFY_ABAQUS` matches are intentional legacy compatibility (directory name, env variable names, legacy fixtures in tests) and are documented | None | — |
| **G2** Localization | **PASS** | 330 keys, ja default, en switch, persistence, form/selection/camera preservation, localized statuses and accessibility labels; two independent completeness gates; Japanese and English browser tests pass; visual check at 1280/1440/1920 showed no clipping | Automated pixel-diff regression is not configured | Optional: add screenshot baselines |
| **G3** UI/UX | **PASS** (partial automation) | Tokens with computed contrast; AA failure fixed; Japanese typography and line height; non-colour status cues; keyboard focus ring; `NumberInput` validation and disabled reasons. No automated axe-core run | No axe-core run; no automated visual regression | Add `@axe-core/playwright` and screenshot baselines |
| **G4** Frontend architecture | **PASS** | Responsibilities split into cohesive modules; single source of truth for draft vs saved state; picking tests pass; no new framework; adaptive polling; camera preserved on language change. No profiling capture was taken | Performance was not profiled with a profiler; conclusions are from behaviour, not measurement | Profile large-geometry and frame-playback paths before further renderer changes |
| **G5** Materials | **PASS** | Create/duplicate/edit/delete-guard, linear elastic and hyperfoam editors, hard vs warning validation, versions verified against the API, unassigned card excluded from the deck, `8.5, 0.44` and new test rows found in `analysis.inp` | — | — |
| **G6** Geometry/mesh | **PASS** (scoped) | Existing DXF/Gmsh tests pass unchanged; mesh metrics measured from the produced mesh; review panel displays them; invalid models are still rejected before build | No new synthetic fixtures for nested cavities/self-intersection were added in this phase | Add the fixture matrix listed in the brief |
| **G7** Abaqus execution | **PASS** (non-licensed) | Deck contract, material/set/mounting/output assertions, launcher argument fixture, completion-evidence and license-diagnosis tests all pass. Input hash and revision provenance unchanged | No licensed execution was performed | Run one authorized closing case |
| **G8** Physical validation | **BLOCKED** | No licensed runtime and no reference curves/tolerances are available | Reference cases, curves and agreed tolerances are missing | Authorized engineer must supply references and approve tolerances |
| **G9** Results | **PASS** (scoped) | Displacement magnitude and components render; unavailable outputs listed, never zeroed; signed probe values; units and signs preserved; DEMO/solver provenance shown; CSV unchanged; frame playback test passes | Stress/strain/CPRESS are only listed as unavailable because the extractor publishes no such nodal field | Wire `fields` from the extractor when a validated averaging method exists |
| **G10** Reliability | **PASS** (no schema change) | API restart, browser closure, worker-disconnect, cancellation, extraction retry and artifact immutability tests pass; schema is still version 1 with idempotent initialization; recovery and shutdown documented | No automated unknown-process-state recovery drill beyond the existing disconnect test | Optionally add a "reconcile unknown job" guided command |
| **G11** Release automation | **PASS** (workflow authored, not yet executed on GitHub) | `ci.yml` runs all gates on Windows without a license; clean `npm ci` and `pip install -r requirements.lock.txt` used; version matrix documented | The workflow has not run on GitHub Actions from this environment | Push and observe the first CI run |
| **G12** Documentation | **PASS** | Japanese and English user guides, architecture, validation, migration/recovery, release checklist, report; naming consistent; DEMO separated; limitations accurate | No checked-in screenshots | Add screenshots from the real UI if desired |

## E. Backward compatibility

- **Storage**: unchanged directory (`%LOCALAPPDATA%\SimplifyAbaqus`) and unchanged file layout. A new
  alias (`ABAQUS_QOL_DATA`) is additive; the legacy variable keeps precedence.
- **Database**: schema version 1, unchanged. `initialize()` remains idempotent with
  `CREATE TABLE IF NOT EXISTS`; no migration or destructive step was introduced, so rollback is simply
  restoring the previous directory copy.
- **Launcher**: `SIMPLIFY_ABAQUS_LAUNCHER` still works and wins over the alias.
- **Projects and revisions**: the setup schema is untouched. Material versions are still recomputed
  server-side from the previous revision; historical revisions are immutable.
- **Artifacts**: manifest allowlist and download behaviour unchanged. `results.json`,
  `history.csv` and `frame-NNNNN.json` formats are unchanged, so existing runs remain readable.
- **API contract**: `generated.ts` regenerated with no diff; no endpoint or payload changed.
- **Rollback**: stop the services, restore the previous directory copy, check out the previous commit.
  No data conversion has to be undone.

## F. Engineering limitations

- 2D plane stress only. 3D remains a preview and cannot be submitted.
- Elements are CPS3 / CPS4R with one R2D2 rigid panel; contact is hard with Coulomb friction along Y.
- **No real licensed Abaqus solve was executed in this phase.** No reference force curve, contact-onset
  comparison, mesh-convergence study or time-step sensitivity result exists.
- Stress, strain and contact-pressure fields are not visualised: the extractor publishes no validated
  nodal averaging for them, and the UI lists them as unavailable rather than inventing values.
- Mesh metrics are geometric measurements of the produced mesh, not a solver-verified quality score.
- DEMO output is synthetic and is labelled as such in the dashboard, run banner, result page, legend,
  CSV and metadata.
- Backend error strings remain in English (diagnostic detail); only their surrounding labels and
  vocabulary are localized.

## G. Production readiness

**Selected level: 2 — INTERNAL DEMO READY.**

Justification:

- The internal demo path is fully exercised: project creation, DXF import, role/material/mounting
  entry, revision immutability, build, DEMO run, diagnostics, results, CSV download, restart and reopen.
  All automated gates pass (39 Python + 12 browser + translation + typecheck + build).
- Localization, branding, material editing, mesh review and result inspection are complete and tested.
- Level 3 (controlled internal pilot) is withheld because no licensed Abaqus solve has been executed
  from this environment and no engineering comparison exists; a pilot would expose users to unvalidated
  physical results.
- Level 4 (engineering production) must not be selected: gate G8 is BLOCKED and the brief forbids it
  without authorized validation evidence.
