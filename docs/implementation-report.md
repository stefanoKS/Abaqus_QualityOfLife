# Implementation report — 2D engineering milestone (entry point, grouping, door response)

Date: 2026-11-21
Baseline commit: `b250789` (branch `main`, clean working tree; only the supplied
`apps/web/assets/logo.png` was untracked)
Repository: `stefanoKS/Abaqus_QualityOfLife`
Environment: Windows, Python 3.11.9 (`.venv`), Node.js 24.16.0, npm 11.13.0, Edge with WebGL,
Abaqus/Standard 2024 installed at `C:\SIMULIA\Commands\abq2024.bat`.

## A0. Delivered increment — 2D mesh-first fixture (brief item 5)

Delivered after the milestone above. Scope was limited to the 2D fixture workflow; drawing partitions,
two-panel motion, friction overrides and 3D solving remain separate milestones.

### Workflow and API

- `BUILD` is replaced by two durable-worker operations:
  `POST /api/meshes` (mesh only; an empty fixture is valid) and `POST /api/decks`
  (requires a compatible reviewed mesh, a non-empty fixture and a valid motion).
- `PUT /api/meshes/{id}/fixture` stores a validated, deduplicated, deterministically ordered set of
  instance-qualified labels (`WS-1:15`). `POST /api/meshes/{id}/fixture/edges` resolves a legacy
  CAD-edge mounting selection to nodes of that known mesh for inspection before saving.
- `store.submit` validates server-side, so direct API calls cannot bypass the rules: the deck must
  belong to the same model as the mesh, the mesh compatibility digest must match the saved revision,
  the fixture must exist, be non-empty and be bound to that mesh digest; a run needs a completed deck
  for the **exact** saved revision and the fixture hash the deck was prepared with.
- Mesh identity: `packages/engineering/identity.py` digests only the mesh-determining inputs
  (dimension/formulation/plane, vertices, analytic edges, face topology with cavity-fill presence,
  component roles, global and local mesh controls). Material values, motion, contact, thickness and the
  fixture are excluded, so they reuse the mesh. The worker records the digest of `mesh.json` and the
  compatibility digest on the job and writes a reviewable `mesh-identity.json` artifact.
- The deck writer consumes the stored mesh (`deck.write_inp(project, mesh, fixture)`), verifies the
  mesh digest before writing, and writes `WSFIX` from exactly the saved labels. The run stage re-checks
  the deck hash and the mesh digest before launching a solver.

### Browser

- New **Mesh generation** section: **Generate mesh** (no fixture required) and a mesh-ready/stale
  status with the digest.
- New **Fixed nodes (WSFIX)** section on the mesh stage: a **Fixed-node box mode** toggle, rectangle
  operation **Replace / Add / Subtract**, **Clear selection**, a live node count and source,
  **Save fixed nodes**, and **Resolve N old mounting edges to nodes** for editable legacy models.
- The viewport gained rectangular node selection: left drag selects when armed, Shift+drag and the
  secondary buttons pan, the wheel zooms, and the rectangle is drawn as an overlay. Selection is
  computed from projected mesh nodes with the active camera, so pan/zoom and high-DPI coordinates map
  correctly; rigid-panel nodes and reference points can never be selected, and a rectangle never
  expands to a CAD edge. Saved nodes stay highlighted after save, reload and language switch.
- New **Input deck** section (**Prepare input deck**, deck status, inspect link) available on the mesh
  and review stages; submission is enabled only for the exact revision, mesh and fixture.
- Workflow indicators now distinguish *mesh required*, *mesh inputs changed*, *fixture required*,
  *fixture reviewed* and *input ready*, and each incomplete or blocked step explains itself through
  `title` and the status bar.
- Japanese and English dictionaries were extended (391 keys in both).

### Verification

| Gate | Command | Result |
|---|---|---|
| Python tests | `.\.venv\Scripts\python.exe -m pytest -q` | **54 passed**, 1 skipped (opt-in ODB fixture) |
| Translation completeness | `npm --prefix apps/web run test:i18n` | **391 keys** in ja and en |
| TypeScript | `npm --prefix apps/web run typecheck` | pass |
| Production build | `npm --prefix apps/web run build` | pass |
| Browser end to end | `npm --prefix apps/web run test:browser` | **19 passed** |
| API contract | `scripts/schema.py` | regenerated (`/api/meshes`, `/api/decks`, fixture, `deck` field) |

New automated coverage:

- `tests/test_fixture.py` (9): deck blocked until nodes are selected; unknown/rigid/foreign/malformed
  labels rejected; duplicate labels deduplicated and ordered; a partial mounting-edge patch written to
  `WSFIX` with neighbouring nodes absent; motion and friction edits reuse the mesh while a stale deck
  cannot submit; a remesh changes the digest and invalidates the fixture; cross-model mesh and fixture
  binding rejected; legacy edge resolution saved and reopened; historical runs and artifacts survive;
  the result header carries the reviewed fixture.
- `apps/web/tests/fixture.spec.ts` (4): box selection after pan and zoom with add/subtract/clear;
  whole-model selection excluding rigid nodes; exact `WSFIX` comparison against the saved labels from
  the generated INP; save/reload highlighting; motion reuse and remesh invalidation; high-DPI
  (`deviceScaleFactor: 2`) selection; Japanese/English switch with an in-progress selection.
- `tests/test_geometry.py` and `tests/test_abaqus.py` gained mesh-identity and corrected-CSV checks.

### Licensed evidence

One licensed Abaqus/Standard 2024 door-only case was run through this exact path (18-node box-selected
patch, 42.3 s, contact reached). `WSFIX` matched the saved selection set-for-set, all selected nodes
were held at floating-point zero across 26 frames, and the RP attained −6.0 mm. Full identifiers,
hashes and tolerances are in
[engineering-validation.md](engineering-validation.md#licensed-execution-record--mesh-first-fixture-2026-11-21).

### Follow-up defects fixed here

- `history.csv` put the projected total in `panel_total_RF2_N`. The signed global `RF2` meaning is
  restored there, and the projected value has its own `closing_total_force_N` column.
- History projection now requires only the components the closing direction uses, so an X-only
  direction does not depend on `U2`/`RF2`.
- An empty history no longer crashes the results view's sample matching.

## A. Scope actually completed

The milestone brief lists nine items. This increment deliberately completes and verifies
items **1, 2 and 8** end to end, and left items **3, 4, 5, 6 and 7** unstarted rather than
half-implemented. Item 5 was subsequently delivered in section A0. The blockers for the rest are listed
in section E. The [working-tree handoff](../agent.md) maps those items to code, acceptance checks and follow-up defects found during review.

### 1. Windows entry point and product logo — DONE

- `start-abaqus-qol.cmd` is now a bootstrap that locates Python 3.11+ and delegates to
  `scripts/serve.py`. It never requires an execution-policy change, quotes every path (spaces are
  supported), and inherits `SEAL_DATA`, `SEAL_ODA`, `SIMPLIFY_ABAQUS_LAUNCHER` and their
  `ABAQUS_QOL_*` aliases unchanged.
- If no Python 3.11+ is found the launcher prints the exact installation and manual-setup commands and
  pauses so a double-click user can read them.
- `scripts/serve.py` now:
  - prepares the repository `.venv` and the pinned dependencies when missing (import probe, then
    `pip install -r requirements.txt`), and builds the browser bundle when `node_modules` or `dist` is
    missing or older than the sources;
  - reports which interpreter it uses;
  - identifies a live instance through `GET /api/health`
    (`{"product": "Abaqus QOL", "status": "ready", "version", "pid", "started"}`), and a second launch
    opens that instance instead of starting a second worker;
  - refuses to start when the port belongs to another application, naming the port and suggesting
    `--port N+1` (it never kills the other process);
  - serialises simultaneous launches with `.local/serve.lock`, verifying the owner by health rather than
    trusting a stale file;
  - opens the browser only after readiness, and never with `--test-data`/`--no-browser`;
  - keeps the worker's shutdown behaviour: the stop file is created, then the worker is awaited so its
    current operation completes.
- `sys.prefix`, not `sys.executable`, decides whether the project environment is active. On this machine
  `.venv\Scripts\python.exe` is a shim that relaunches the base image, so an executable-path comparison
  would loop forever; the bootstrap marker `ABAQUS_QOL_BOOTSTRAP` turns any such loop into a clear
  message.
- The header uses the supplied `apps/web/assets/logo.png` (1019 × 331) through a Vite asset import, so
  production ships a content-hashed file (`dist/assets/logo-DG4MlTUg.png`). It is sized proportionally
  (129 × 42 CSS px, ratio preserved) on a light chip for contrast against the dark navigation bar, and
  there is exactly one accessible product name (decorative image plus one screen-reader label).
  Verified by DOM measurement in Japanese and English.

### 2. Project grouping with minimal migration — DONE

- New `groups(id, name, created)` table; `projects.group_id` links a model to a group. Models are still
  `projects` rows, so revision, run, artifact and drawing identities are untouched.
- `store.initialize()` performs the additive migration in one `BEGIN IMMEDIATE` transaction: add the
  column when absent, then assign every `NULL` model to a single `Imported projects` group created on
  demand. Repeated or interrupted starts converge; a second start creates nothing new.
- API: `GET /api/groups` (groups with their models), `POST /api/groups`,
  `POST /api/projects/{id}/duplicate` (a new model in the same group),
  `GET /api/projects/{id}/revisions`. Creating a model with an unknown group returns 404. Job
  duplication keeps the model's group.
- Dashboard: **New project** now creates a project group plus its first model in one action (the model
  name defaults to the project name), and each group header has **New model**. Each model offers
  **Revisions** (inline history) and **Duplicate model**. The hint text states the difference between a
  group and a model, and the workspace breadcrumb shows `Projects › group › model › revision`.
- `Revision` also carries `group`/`group_name` so the workspace can show it without another request.
- Contract regenerated (`scripts/schema.py`); `generated.ts` has no manual edits.

### 8. Door response as the default plot, with export of the displayed curve — DONE

- The deck now requests `U1, U2, RF1, RF2` at the panel reference point (previously `U2, RF2`).
- `result-metadata.json` gains a `closing` block (panel, instance, reference label, normalized direction,
  distance, "measure from step start", ordered step roles).
- `interchange.align_histories` aligns all four components on the common time domain per step and adds
  `step`, `u1`, `u2`, `rf1`, `rf2`, plus the projected `displacement` and `force`. Travel is measured
  from the first sample of the closing step so a later closing step reports closing displacement, not
  assembly travel.
- `results.json` keeps version 1 and every previous field; `history.csv` adds `step`, `panel_U1_mm`,
  `panel_RF1_N`, `closing_displacement_mm`, `closing_force_<unit>` and keeps the old columns.
- Results page: **Door response** is the default chart, opening on the closing step; sample-to-frame
  matching uses step identity as well as time; **Reverse X sign** and **Reverse Y sign** transform both
  the chart and the client-side **Export displayed curve** CSV; the unmodified artifact stays available
  through **Download history CSV**. The exported CSV carries panel, instance, closing step, direction,
  units, both signs, normalization and DEMO/ABAQUS provenance in `#` lines, then the displayed values and
  the raw signed components.
- Legacy artifacts (history rows without `u1/u2/rf1/rf2`) still open, keep their original U2/RF2 meaning,
  and the UI says the projected response is unavailable for them.
- The DEMO generator's sign convention was corrected after measuring the solver: Abaqus reports
  `RF2 < 0` while the seal resists, so the projected closing force is positive. A regression test and a
  browser test now lock that convention.

**Subsequent artifact review.** The single-step displayed curve has the recorded projection. In the
stored CSV, the column named `panel_total_RF2_N` also receives this projection; use
`panel_RF2_N` for the signed global reaction in this run. The [handoff](../agent.md) describes
the compatibility fix and remaining missing-history and multi-step checks.

## B. Verification

### Automated gates (all executed locally)

| Gate | Command | Result |
|---|---|---|
| Python tests | `.\.venv\Scripts\python.exe -m pytest -q` | **43 passed**, 1 skipped (installed-runtime ODB fixture, opt-in) |
| Translation completeness | `npm --prefix apps/web run test:i18n` | **349 keys** in ja and en |
| TypeScript | `npm --prefix apps/web run typecheck` | pass |
| Production build | `npm --prefix apps/web run build` | pass (chunk-size warning only) |
| API contract | `.\.venv\Scripts\python.exe scripts\schema.py` | regenerated, no manual diff |
| Browser end to end | `npm --prefix apps/web run test:browser` | **15 passed** |

New tests in this increment:

- `tests/test_grouping.py` (4): group with 2D+3D models and same-group duplicate; unknown group rejected;
  newest-first revision history; **populated legacy database** migrated twice without losing revision,
  run, artifact-list or original-drawing access, and without creating a second group; artifact directory
  path unchanged after renaming a group.
- `apps/web/tests/groups.spec.ts` (2): create a group with its first model, add a sibling model, browse
  revisions, duplicate inside the group; an in-progress region selection and edit survive a ja/en switch.
- `apps/web/tests/curve.spec.ts` (1): default door-response chart, projected travel/force signs, raw
  components retained, both sign toggles mirrored in the export, raw artifact untouched, and the
  historical run reopens after a later model edit.

### Manual entry-point checks

| Check | Result |
|---|---|
| `start-abaqus-qol.cmd --prepare` | “environment and browser bundle are ready”, exit 0 |
| `start-abaqus-qol.cmd --no-browser --port 8897` | ready; `/api/health` returns the product identity |
| Second launch on a live port | “already running … Opening it”, exit 0 |
| Port owned by an unrelated HTTP server | “port 8898 is used by another application … --port 8899”, exit 1, other process untouched |
| Header logo, ja and en | 129 × 42 px from the bundled hashed asset, one accessible name |

### Licensed execution

One small, isolated, authorized Abaqus/Standard 2024 door-only closing case was executed from the normal
workflow (API → worker → launcher → ODB extraction), on the synthetic hollow-bulb section. Full values,
hashes and tolerances are in `docs/engineering-validation.md`.

Summary: solver and extraction both `Succeeded`; 47 increments; `THE ANALYSIS HAS COMPLETED
SUCCESSFULLY`; 26 frames in one `Closing` step; `WSFIX` held 13 nodes at floating-point zero displacement
in every frame; panel RP `U2` went 0 → −6.0 mm monotonically; first contact at 1.92 mm travel against a
reported geometric clearance of 1.80 mm (within one 0.24 mm output interval); final `RF2` −0.3335 N and
projected closing force +0.3335 N; the exported CSV matched `closing_force = −RF2` and
`closing_displacement = −U2` exactly. The `analysis.inp` SHA-256 matched the recorded `input_hash`.

## C. Backward compatibility

- **Storage**: same directory, same file layout. `groups` and `projects.group_id` are additive.
- **Revisions and runs**: identities, URLs and artifact names unchanged. A legacy model opens, its runs
  list, its original drawing downloads, and a sibling model in the same group is unaffected.
- **Result artifacts**: `results.json`, `history.csv` and `frame-NNNNN.json` keep version 1 and all
  previous fields; new fields are additive. Old runs remain viewable and exportable with their original
  meaning.
- **Configuration**: alias precedence unchanged (`SEAL_DATA` > `ABAQUS_QOL_DATA`, etc.).
- **Worker**: durable queue, ownership/heartbeat, cancellation tree-kill and extraction-only retry are
  unchanged; only the startup path around them changed.
- **Rollback**: stop the services, restore the previous directory copy if desired, check out `b250789`.
  The previous build ignores the extra table and column, so it also runs against a migrated database.

## D. Files changed

Added: `tests/test_grouping.py`, `apps/web/tests/groups.spec.ts`, `apps/web/tests/curve.spec.ts`,
`apps/web/src/assets.d.ts`.

Modified: `start-abaqus-qol.cmd`, `scripts/serve.py`, `services/store.py`, `services/api/main.py`,
`services/api/contracts.py`, `integrations/abaqus/{interchange,results,extract_odb,deck}.py`,
`apps/web/src/{main,Dashboard,Workspace,RunView,api,style}.tsx/ts/css`, `apps/web/src/i18n/{ja,en}.ts`,
`apps/web/src/generated.ts` (regenerated), `apps/web/tests/curve.spec.ts`, `tests/test_abaqus.py`,
`docs/{architecture,engineering-validation,migration-and-recovery,release-checklist,user-guide-ja,
user-guide-en,implementation-report}.md`.

Removed: nothing.

## E. Remaining blockers, reported separately

### DWG conversion

- **Gap:** no ODA-compatible converter is installed on this machine, so no genuine DWG was converted and
  the converted geometry, units, layers, curves and profiles were not inspected. `GET /api/capabilities`
  reports `DWG converter not configured`, and the UI shows it.
- **Continues with:** DXF, which is exercised end to end (import → roles → material → mesh → deck).
- Nothing proprietary was fetched or redistributed.

### Licensed execution

- Executed: one door-only closing case that reaches contact (recorded above).
- **Not executed and not implementable yet:** body-then-door two-step closing, oblique motion, reversed
  profile and per-pair friction — items 6 and 7 are not implemented, so there is nothing to validate.
- No solver diagnostics anomaly was observed; `analysis.msg`/`analysis.dat` were inspected for errors.

### Physical correlation

- **BLOCKED.** No trusted reference curve and no agreed engineering tolerance are available. The
  clearance-versus-contact-onset agreement is a self-consistency check, not correlation. No claim of
  engineering accuracy is made.

### Not started from the brief

| Item | State |
|---|---|
| 3. Drawing-role review before region construction | Not started. Requires splitting `import_dxf` into a linework-review phase and a confirmed-region phase, plus profile role selection |
| 4. Validated material-region partition tool | Not started. Requires a new topology-edit operation with base-revision checking and a cut/commit UI |
| 5. Mesh independent of fixture selection | **Delivered in this increment** (see A0) |
| 6. Role-aware arbitrary in-plane panel motion | Not started. Requires a per-panel motion schema, a new mesher/deck path and a two-step analysis with orientation checks |
| 7. Friction on contact-surface pairs | Not started. Depends on 6 for multiple panels; also needs per-edge exterior surface construction and overlap conflict detection |

## F. Readiness decision

**Selected level: 2 — INTERNAL DEMO READY**, with two verified licensed door-only cases (edge-based
and mesh-node-selected fixtures).

- The internal path is fully exercised: create a project group, add 2D/3D models, import a DXF, assign
  roles/materials/motion, save revisions, generate a mesh, box-select the fixed WS nodes, prepare the
  deck, run DEMO or ABAQUS, inspect diagnostics, read the projected door response, export the displayed
  curve, reopen historical runs.
- Level 3 (controlled pilot) is still withheld: drawing-role review, partitioning, two-panel motion and
  per-pair friction are not implemented, no reference correlation exists, and no tolerance has been
  agreed.
- **3D is not ready.** The 3D extrusion remains a preview; grouping 3D models is supported, but 3D
  solving, meshing and deck generation remain deferred until the 2D workflow is complete and validated.
