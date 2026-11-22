# Implementation report — 2D engineering milestone (entry point, grouping, door response)

Date: 2026-11-21
Baseline commit: `b250789` (branch `main`, clean working tree; only the supplied
`apps/web/assets/logo.png` was untracked)
Repository: `stefanoKS/Abaqus_QualityOfLife`
Environment: Windows, Python 3.11.9 (`.venv`), Node.js 24.16.0, npm 11.13.0, Edge with WebGL,
Abaqus/Standard 2024 installed at `C:\SIMULIA\Commands\abq2024.bat`.

## A4. Repair delivery — drawing ownership, Review authority, playback, Abaqus-only execution

Date: 2026-11-22. Baseline: `d7b6728` (parent `240460c`), clean tree. No new solver process was
launched for this repair. The retained licensed run was replayed read-only from an isolated copy.

### Delivered behaviour

- **Empty models are explicit.** `Source.kind` now includes `empty`; a new model carries no vertices,
  components, regions, selections, material cards, filename or digest. `POST /api/projects` creates an
  empty model unless `example: true` is supplied. Startup no longer seeds geometry. Save, rename,
  close, reopen and duplicate all work before an import. Mesh, deck and run endpoints reject an empty
  model with a specific message.
- **Drawing identity is model-bound.** Two uploads named `section.dxf` coexist as separate source
  digests and revision identities. The original bytes download from the owning revision. Import
  preserves the model's dimension (including a 3D preview), motion, contact and analysis settings, and
  a failed import leaves the last good revision and head untouched.
- **Navigation is deterministic.** `main.tsx` no longer falls back to `projects[0]` or `ps[0]`. The
  Workspace button restores the last explicitly opened model or opens the dashboard. An invalid link
  names the missing revision and offers **Back to Projects**. Save and import completion replace the
  history entry and notify the router; the remembered step survives the resulting remount.
- **Review cannot remesh.** Generate mesh is rendered only in Mesh. A reviewed fixture turns
  regeneration into an explicit Regenerate/Cancel choice that names the affected node count. Review
  shows mesh identity, node/element counts, quality and a Go to Mesh link, plus copy stating that deck
  preparation writes an `.inp` and never enqueues a mesh job. A just-queued deck becomes the visible
  deck before submission, so an older deck can no longer be submitted by accident.
- **Historical replay uses its own mesh.** A submitted setup resolves the mesh job recorded by its
  deck and verifies the digest chain before drawing archived labels. An unverifiable archive reports
  why the overlay is unavailable; a newer compatible mesh is never substituted.
- **Renderer reuse is topology-safe.** Every actor has a stable key derived from instance, entity,
  component, primitive kind and rendering class. Reuse also requires equal cells, point count,
  contour and edge-visibility flags; otherwise the old actor is disposed exactly once and replaced.
  CAD, mesh, 2D and 3D displays no longer collide on an empty key.
- **Camera and colour scale are run-wide.** Extraction records `display.bounds` and `display.ranges`
  for each supported nodal quantity. Retained results without it get a derived cache keyed by run and
  index digest; original artifacts are not rewritten and no solver runs. The renderer consumes the
  six-value array bounds, fits once, and keeps camera/zoom/pan through frames. A missing quantity is
  reported unavailable instead of being painted with a fabricated zero.
- **Frames are atomic.** Requested and displayed frame identities are separate; the previous complete
  frame stays visible while a slower frame loads. Playback waits for the displayed frame before
  advancing, so slow responses are not abandoned. Out-of-order scrub responses cannot repaint, a
  failed frame is identified, the frame cache is bounded to eight, and the Plotly cursor is restyled
  without purging the plot or resetting the reader's axis zoom.
- **Execution is Abaqus-only.** The execution-mode and scenario selectors are removed. Omitted mode
  resolves to `ABAQUS`; an explicit `DEMO` returns 422 and queues nothing. `store.claim` never claims a
  DEMO row, and startup retires a queued, never-started DEMO job with a written diagnostic rather than
  converting or relaunching it. Historical DEMO rows, result views, exports and notices remain.
- **Launcher lock is per port.** A custom-port launch no longer joins the default instance. Each port
  has its own lock file; the same-port healthy instance is still reused.

### Gate table

| Gate | Result | Evidence | Remaining |
|---|---|---|---|
| Clean installation and empty models | PASS | Python: `test_clean_installation_has_no_seeded_model`, `test_new_model_is_explicitly_empty_and_round_trips` (2D/3D), `test_empty_model_rejects_mesh_deck_and_run_clearly`. Browser: `isolation.spec.ts` creates three empty models. Launcher health with isolated data returned `projects: []`. | — |
| Two-model, same-filename drawing evidence | PASS | Python `test_same_filename_drawings_bind_to_their_own_models`; browser `two models keep same-named drawings apart…` uploads `with-cavity/section.dxf` and `without-cavity/section.dxf`, asserts equal basename, different digests and download hashes, and a cavity-centre pick that selects nothing in A but a face in B. | — |
| Navigation, reload, Back/Forward, brand, fresh session | PASS | Same browser test: A→B→dashboard→A, B reload, Back/Forward, brand restore, new browser context, invalid link alert + Back to Projects, cancelled chooser, failed import. | — |
| Import completes in A while B is open | PASS | Browser `an import that finishes in A stays in A while B is open`: A's revision count reaches 2 while B stays unchanged and keeps its own digest. | — |
| 3D preview keeps its dimension | PASS | Python `test_import_preserves_the_3d_preview_dimension`; browser `a 3D preview keeps its dimension…`. | — |
| Zero mesh submissions from Review | PASS | Browser `review.spec.ts` monitors POST `/api/meshes` from entering Review through deck preparation and submission; asserted 0. Second test asserts the mesh-job count is unchanged. | — |
| Historical mesh/WSFIX equality | PASS | Python `test_submitted_run_replays_its_archived_fixture`, `test_result_header_carries_the_reviewed_fixture`; browser review test parses WSFIX before and after a travel change and compares it with the saved instance-qualified labels; archived replay count equals the archived labels. | — |
| Renderer actor reuse and picking | PASS | Browser `renderer.spec.ts`: repeated hide/show, mesh toggle and 2D/3D switch return to the exact actor count; the crown still picks `Hollow bulb` and `bulb_foam`. | — |
| Delayed frame, out-of-order scrub, failure, camera/scale | PASS | Browser `playback.spec.ts`: 1.5 s delayed frame keeps the frame time and actor count unchanged, playback pauses and then displays it; pan+zoom persists through frame steps; Fit restores the fitted grid; the U2 legend is identical at frames 0 and 65; an out-of-order frame 20 cannot overwrite frame 5; an aborted frame 8 reports itself and keeps frame 5. | Colour equality is asserted through the fixed run-wide legend range and deterministic ramp; direct per-pixel colour comparison was not automated. |
| Retained licensed replay | PASS (replay only) | Isolated copy of run `989fec4a-98fa-4a61-999a-e16ec886ac68`: 66 frames, slider 0–65, camera grid unchanged after pan+zoom through all frames, final frame 1.300 s, closing travel 6.5 mm, signed `RF2` −0.0169664863 N, projected 0.0169664863 N. `history.csv` and `results.json` agree. Display metadata came from the derived cache (`source: cache`). No page errors. | Physical correlation remains separate and unvalidated. |
| Abaqus-only API and legacy DEMO | PASS | Python `test_demo_submission_is_rejected_without_queueing_and_history_stays_readable`, `test_queued_legacy_demo_is_retired_and_completed_demo_stays_readable`; `store.claim` excludes DEMO. Browser jobs test submits ABAQUS and completes through the launcher double. | A queued legacy DEMO is retired; an already-running legacy DEMO remains under its owning worker's reconciliation. |
| Display metadata for retained results | PASS | Python `test_display_metadata_is_recorded_and_derived_without_rewriting_artifacts`: recorded source, derived source, cache source, and the index bytes are unchanged. | — |
| Python suite | PASS | `.\.venv\Scripts\python.exe -m pytest -q`: 105 passed, 1 skipped (the opt-in installed-runtime ODB test). | — |
| Frontend typecheck and build | PASS | `npm --prefix apps/web run typecheck`, `npm --prefix apps/web run build`. | — |
| Translation parity | PASS | `npm --prefix apps/web run test:i18n`: 463 keys in both dictionaries; the corrupted Japanese Mounting/Contact/Review block and the `???` language-switch template were restored; the duplicated/corrupted tail of the Japanese guide was removed. Browser test `Japanese Create, Import, Mesh, Mounting, Review and Results labels are readable` renders the Japanese UI and asserts representative labels on every named screen plus the language button. | Japanese wording outside those screens still merits a native-speaker read. |
| Browser suite | PASS | `npm --prefix apps/web run test:browser`: 33 tests. | — |
| Windows startup, isolated port | PASS | `cmd /c start-abaqus-qol.cmd --port 8897 --no-browser` with isolated `SEAL_DATA`: health ready, `frontend` matched `dist/assets`, empty project list; stopped afterwards without touching the default instance. | Double-click itself is not automatable; the CMD wrapper path was used. |
| Two-step body/door, oblique motion, per-pair friction, partition, drawing-role review | BLOCKED | Not implemented in this repair. Listed separately as outstanding. | Requires solver-method work and a trusted reference. |


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

Totals moved on with the next increment: see the A1 table for the current 66 Python / 22 browser tests
and 395 translation keys.

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

## A2. Delivered increment — native DWG import (this brief, seven gates)

The original drawing is now read **natively**: `examples/hollow-section_2.dwg` → `integrations/dwg/bin/dwg-inventory.exe`
(ACadSharp 3.8.35, MIT) → `packages/engineering/dwg.py` → the same canonical model, mesh, fixture and
deck the DXF path uses. No converter, no DXF intermediate, no network.

### Gate status

| Gate | Status | Evidence | Remaining issue |
|---|---|---|---|
| 1 · Native reader on the original file | **PASS** | `tests/test_dwg.py::test_original_drawing_inventory_accounts_for_every_entity`; hash/header match; 5 model-space entities, all on layer `0`, 0 unknown, 0 skipped; warnings captured in `dwg-inventory.json` | The reader emits three `knot count does not match control points` notes because the file stores fit points only; they are reported, not hidden |
| 2 · Spline shape and hollow section | **PASS** | S-curve regression (0.28125 / 0.2887 / 0.0127 mm), quarter-point flatness test, refusal to exceed the subdivision limit; real drawing keeps 1 filled region + 1 cavity through save, reopen, mesh and hashing | Closed/periodic splines are meshed through their sampled chain at the declared 0.02 mm tolerance, not as exact OCC curves |
| 3 · Drawing-role review before regions | **BLOCKED** | Import reports the chain inventory (3 components: seal loop, body D7, door 120), excludes open profiles with handles, keeps fill/void review data and shows per-component roles in the existing Components panel | There is **no** in-viewport chain picking with add/remove and a WS/Door/Body confirmation step; roles are still assigned per connected component after import |
| 4 · Fixture traceability | **PARTIAL** | Queue-time snapshot, stale-deck rejection and archived-label replay from `dabffe3` stay in force; the new acceptance harness saves a fixture and proves `WSFIX` equality; corrupt DWG imports fail as jobs without touching existing revisions | The historical-view defect called out in the brief (archived labels combined with the *latest* compatible mesh) is **not** fixed yet, and duplication does not verify mesh identity |
| 5 · Two-panel analysis | **BLOCKED** | Roles allow a reviewed `vehicle_body` profile that is excluded and reported; the deck still writes one rigid body and one step | No per-panel instance/reference point/step, no body-then-door sequence, no two-panel plot |
| 6 · Licensed acceptance on the drawing | **PASS (door-only)** | Run `8a0cefa3-6bef-4eaf-97d6-94d3712c33b1`: completed, 84 increments, 15/15 fixture nodes held at ≤ 8.4e-39 mm, RP `U2` 0 → −6.5 mm, contact at 5.70 mm vs 5.66 mm clearance, projected force +0.018122 N, CSV = ODB | The brief's two-panel table (body seating then door closing) cannot be evidenced; the body does not move |
| 7 · Regression, packaging, handover | **PARTIAL** | 75 Python tests, 22 browser tests, 395 translation keys, typecheck and build pass; helper ships prebuilt in `integrations/dwg/bin` so no SDK or converter is needed; two copy-paste commands below | No independently authored binary DWG fixture is committed (the mapping is tested against a synthetic inventory; the original file is read only when it is present locally) |

### What changed in the code

- `integrations/dwg/src/DwgInventory.cs` + `bin/` — the helper. Reads DWG bytes, expands `INSERT`
  instances with their transform and instance identity, emits deterministic JSON (entities, layers,
  blocks, counts, unknown handles, warnings). Built with the .NET Framework 4.8 compiler, so it needs
  no SDK, no runtime install and no converter on any Windows machine.
- `integrations/dwg/__init__.py` — runs the helper with `SEAL_ODA`/`ABAQUS_QOL_ODA` removed from its
  environment and maps failures to actionable messages (missing helper, corrupt file, unsupported
  version, timeout, oversized drawing).
- `packages/engineering/section.py` — one assembler shared by both readers: connectivity chains,
  closed-versus-open classification (degree-1 test, so reversed/reordered body lines still join), region
  polygonization, cavity detection, component labelling and the import report.
- `packages/engineering/dwg.py` — entity mapping (LINE, ARC, CIRCLE, LWPOLYLINE with bulges, SPLINE
  with control or fit points, POINT/INSERT diagnostics), millimetre-only unit gate, spline provenance.
- `packages/engineering/spline.py` — quarter/mid/three-quarter flatness test and a diagnostic when the
  subdivision limit is reached.
- `packages/engineering/mesh.py`, `integrations/abaqus/deck.py` — a `vehicle_body` profile is accepted,
  excluded from the analysis and recorded in `mesh.json.excluded`; its edges contribute no fixtures.
- `services/worker/__main__.py`, `services/api/main.py` — the IMPORT stage uses the native reader for
  `.dwg` and writes `dwg-inventory.json` + `import-report.json` artifacts; capabilities report the
  native reader and `odaRequired: false`.
- `scripts/acceptance_dwg.py` — the reproducible acceptance harness (zero-token and licensed modes).

### Commands

```powershell
.\.venv\Scripts\python.exe scripts\acceptance_dwg.py
```
Native read, import, roles, mesh, fixture and deck on `examples/hollow-section_2.dwg`. Evidence in
`.local/dwg-acceptance/`. Consumes **zero solver tokens**.

```powershell
$env:SIMPLIFY_ABAQUS_LAUNCHER = "C:\SIMULIA\Commands\abq2024.bat"; .\.venv\Scripts\python.exe scripts\acceptance_dwg.py --licensed --travel -6.5 --evidence .local\dwg-acceptance-contact
```
The licensed door-only acceptance run; needs one CPU token, writes the ODB, extraction and history into
`.local/dwg-acceptance-contact/`.

## A1. Delivered increment — fixture correctness, provenance and spline import

Delivered after A0, before A2. Two of the four engineering items in that brief were completed and
verified: the fixture-correctness repairs with a provenance re-extraction, and spline import that
preserves the drawn geometry. Drawing-role review and body-then-door two-panel loading were reported as
open rather than half-built; A2 records their current state.

### Fixture correctness (five defects found by adversarial review of A0)

| Defect | Repair |
|---|---|
| A deck could be prepared from an older mesh of the same revision | `store.active_mesh` must be the newest completed mesh whose compatibility digest matches the saved revision, both for `POST /api/decks` and for run submission. An explicit remesh supersedes the previous mesh even when its bytes are identical |
| The worker read the *live* fixture row, so a fixture edited after queueing changed the deck | `jobs.fixture_labels` snapshots the label set at queue time; the worker consumes the snapshot, re-verifies its hash and never reads the live row |
| A fixture edited between deck preparation and submission could ride along | Run submission requires the fixture hash recorded on the deck, the deck's mesh to be the active mesh, and the deck to be the newest completed deck for that revision |
| Reopening an old setup lost its archived labels | The deck copies its labels to the run (`locked.fixture_labels`); the workspace and the result header replay them, and the interactive selection is hidden for a locked setup |
| Legacy edge resolution could cross models | `POST /api/meshes/{id}/fixture/edges?revision=` validates project ownership and mesh compatibility before resolving CAD edges to nodes |

Browser behaviour added: a pending (unsaved) rectangle selection disables **Prepare input deck** and
**Run**, survives polling, pan, zoom and language switches, and has an explicit **Discard** button.

### Provenance re-extraction

The retained licensed run's `results.json` was written by an extractor build that predated the
`fixture` header block, so only `result-metadata.json` carried the selected labels. The same ODB was
re-extracted with the current extractor into `.local/licensed-evidence/54b7be8c-reextract/`; both files
now carry the 18 labels and both sets equal the deck's `WSFIX`. The original evidence directory was not
modified and the run/metrics in A0 stand.

### Spline import

- `packages/engineering/spline.py` is the only place a spline is evaluated. It builds the exact
  B-spline from control points/knots/weights, reconstructs fit-point splines with ezdxf's
  AutoCAD-compatible cubic, and tessellates adaptively so the chord deviation never exceeds the
  declared tolerance (default 0.02 mm).
- `model.py` gained `SplineData` (degree, control points, fit points, knots, weights, tangents,
  closed/periodic, tolerance) with validation: exactly one point set, knot count
  `n + degree + 1`, positive weights, planar, and evaluated endpoints that agree with the edge's
  vertices. A closed spline may be a zero-length edge, which is the one permitted exception.
- `dxf.py` now imports `SPLINE` (no longer reports it as unsupported), keeps the source handle, layer
  and exact definition, and snaps the curve's endpoints onto an adjoining vertex within 1 µm so the
  contour closes.
- `geometry.py` samples splines from the canonical curve, `mesh.py` meshes the exact B-spline with
  `occ.addBSpline` when OCC can take it and otherwise meshes the sampled chain within tolerance, and
  orders boundary nodes by arc-length projection (distance from the start point is only monotonic for
  lines and arcs ≤ π).
- `identity.py` includes the spline definition in the mesh compatibility digest, so a curve edit
  invalidates the mesh while renaming the edge does not.

Two mesher defects were introduced and caught while wiring splines in, both now covered by the spline
tests: the B-spline's end control points must be the shared CAD vertices (otherwise OCC silently
re-stitches the wire with duplicate points and the surface no longer shares nodes with the boundary),
and the loop-token handling had to strip a leading `-` with `lstrip("-")` rather than a fixed slice so
that reversed chains work.

### Verification

| Gate | Command | Result |
|---|---|---|
| Python tests | `.\.venv\Scripts\python.exe -m pytest tests -q` | **66 passed**, 1 skipped (opt-in ODB fixture) |
| Translation completeness | `node scripts/check-translations.mjs` | **395 keys** in ja and en |
| TypeScript | `npm run typecheck` (inside `apps/web`) | pass |
| Production build | `npm run build` | pass |
| Browser end to end | `npm run test:browser` | **22 passed** |
| API contract | `scripts/schema.py` | regenerated (spline payload in the project schema) |

Test counts for this increment: `tests/test_spline.py` (8) is new; `tests/test_fixture.py` grew from 9
to 13; `apps/web/tests/fixture.spec.ts` grew from 4 to 7.

## A3. Release candidate ? stage split, language button, mesh fidelity

### 1. Mesh, Mounting and Contact are separate stages

The 2D workflow is now `Import -> Components -> Materials -> Mesh -> Mounting -> Contact ->
Motion -> Review / Run -> Results`, driven by one table in
[stages.ts](apps/web/src/features/workspace/stages.ts). Navigation, picking modes, mesh visibility and
panel rendering all read `STAGE.<id>` instead of literal indexes, so a stage insert cannot route a user
to the wrong tool. `workflowStates` returns one entry per id with prerequisites: Mesh needs materials,
Mounting needs a compatible mesh (and an empty fixture is valid at Mesh), Contact needs materials only,
and Review needs mesh + mounting + motion.

| Step | Owns | Completion |
|---|---|---|
| Mesh | global/local sizing, generate, counts and quality | a compatible mesh exists |
| Mounting | box selection, replace/add/subtract, clear, save, discard, legacy edge resolution | a non-empty reviewed fixture is saved against the active mesh |
| Contact | hard normal law, general-contact domain, analysed/excluded components, global friction, save | a persisted contact definition is valid, independent of the fixture |

The Contact screen has no action that fixes an edge or writes `WSFIX`; the deck writer still reads the
fixture from the queue-time snapshot, unchanged.

### 2. One language button

The header now has a single button whose visible label names the destination language (`English` in
Japanese, `???` in English), with an accessible name `Switch interface to ?`, keyboard operation and a
visible focus ring. It keeps the Japanese first-launch default and the stored preference, and switching
only re-renders: no save, no job restart, no remesh. Both dictionaries are at 422 keys.

### 3. Mesh fidelity on the private drawing

Reproduced on the retained mesh before changing anything: on outer WS spline `CD`, **10 of 21 fit
points were farther than 0.02 mm** from the FE boundary and the worst was **0.29415 mm**, exactly as
reported. Measuring independently (source curve evaluated at 400 parameters per edge, distance to the
mesh boundary polyline) found two real defects:

| Defect | Effect | Fix |
|---|---|---|
| A closed spline's boundary polyline was treated as open, so the closing segment was missing | cavity error reported as 0.11288 mm | [fidelity.py](packages/engineering/fidelity.py) restores the seam segment for a loop edge |
| `Mesh.MeshSizeMin` clamped the size to a quarter of the global size, so curvature refinement could not go below 0.25 mm on a ~0.3 mm hook | refinement plateaued at 0.02877 mm | the floor is now 1/100 of the size, and [mesh.py](packages/engineering/mesh.py) drives `Mesh.MeshSizeFromCurvature` and re-measures, doubling the curvature spacing until the boundary tolerance is met or a diagnostic is raised |

Result on `examples/hollow-section_2.dwg`:

| Group | Before | After | Limit |
|---|---|---|---|
| Outer WS | 0.30747 mm | **0.01549 mm** | 0.02 mm |
| Cavity | 0.11288 mm | **0.01974 mm** | 0.02 mm |
| Door | 0.01423 mm | **0.01423 mm** | 0.02 mm |
| Fit points over 0.02 mm (outer WS) | 10 of 21 (worst 0.29415) | **0 of 21 (worst 0.01071)** | 0 |

Elements changed from 83 CPS3 + 291 CPS4R + 38 R2D2 (453 nodes) to **765 CPS4R + 38 R2D2 (928 nodes)**;
the cavity stays empty and the body profile stays excluded.

### 4. Acceptance exit status

[acceptance_dwg.py](scripts/acceptance_dwg.py) now exits non-zero when the fixture is empty or does not
match `WSFIX`, the solver or extraction did not succeed, an output file is missing, the prescribed
travel is not attained, no contact is detected, a fixed node is missing from a frame or moved, or
`history.csv` disagrees with the extracted history. The checks are pure functions covered by
[tests/test_acceptance.py](tests/test_acceptance.py) (5 cases), and the harness prints every
`***WARNING`/`***NOTE` line from `analysis.msg`.

### 5. Gate results

| Gate | Status | Command / evidence | Remaining issue |
|---|---|---|---|
| A ? Startup and compatibility | PARTIAL | `serve.py --test-data` + API/browser suites; capabilities report the native reader with ODA unset; legacy edge models still resolve | The double-click `start-abaqus-qol.cmd` path was not re-exercised this turn |
| B ? Independent configuration | PASS | `tests/test_fixture.py` (13): mesh identity constant across fixture/friction edits, friction preserved when the fixture changes, superseded deck rejected by direct API, invalid edits leave the saved state usable | ? |
| C ? Real browser and language | **FAIL** | Language: `i18n.spec.ts` (7/7) passes, including the new one-activation button test with Enter and Space. Stage split: the Playwright suite is **14 passed / 9 failed** after the cascade to Mounting/Contact; the failures are un-migrated test expectations (fixture controls expected on Mesh, `.property-body` selectors, step count), not observed application defects | The Playwright suite must be green before any pilot; the nine failing specs are listed in the release section |
| D ? History and job integrity | **BLOCKED** | Queue-time snapshot and stale-deck rejection tests pass; the run's archived labels and mesh hash are recorded in `result-metadata.json` | The API-restart-during-job case was not re-run this turn |
| E ? Private drawing geometry | PASS | `scripts/acceptance_dwg.py`: hash `8592c3c2?`, one filled region, one cavity, spline door, bulged body polyline, 0 unknown entities, boundary errors above | ? |
| F ? Licensed solve and results | PASS (door-only) | Run `d0d409c2-6fc9-4e69-95a1-c75069075d68`: completed, 90 increments, 66 frames, travel 6.5/6.5 mm, contact at 5.70 mm, worst fixed-node |U| 1.8e-38 mm, CSV = ODB | 3 "solution appears to be diverging" notes and 3 negative-eigenvalue warnings need engineering review; body-first/door-second was not exercised |

### Release decision for this candidate

| Question | Answer |
|---|---|
| Ready for an internal engineering pilot? | **No.** The stage split and mesh-fidelity work are implemented and the native path is verified end to end, but the Playwright suite is 14/22 after the cascade (9 un-migrated specs), so the browser gate that protects an engineer from submitting a *different* fixture, contact definition or geometry than the one reviewed is not proven. Fixing those nine specs is the blocker; there is no known application defect behind them. |
| Was body-first / door-second exercised? | **No.** The template still writes one rigid body and one step. A `vehicle_body` component is accepted, excluded and labelled `Body imported - excluded from this analysis` in Contact and Review. |
| Is physical force correlation established? | **No.** The +0.016966 N result is a comparison value from an illustrative hyperfoam card with no agreed tolerance, and the solver emitted three divergence notes that need engineering review. |

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

- **Resolved for reading (2026-11-22).** The native ACadSharp reader imports DWG without ODA or a DXF
  intermediate; the capabilities payload reports `odaRequired: false`. This older paragraph recorded a
  machine that had no converter. Other DWG versions are accepted by the reader but not all were
  exercised.
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

Delivered from the *later* brief (fixture correctness and splines): the five fixture-correctness
repairs, the provenance re-extraction and `SPLINE` import, all described in A1. Still open from that
brief: drawing-role review, body-then-door two-panel loading, per-panel travel/duration, the two-step
deck and the two-panel result plot. The supplied `examples/hollow-section_2.dwg` could not be converted
(no converter installed), so the acceptance case for that drawing has not been run.

## F. Readiness decision

**Selected level: 2 — INTERNAL DEMO READY**, with two verified licensed door-only cases (edge-based
and mesh-node-selected fixtures).

- The internal path is fully exercised: create a project group, add 2D/3D models, import a DXF
  (including spline boundaries), assign roles/materials/motion, save revisions, generate a mesh,
  box-select the fixed WS nodes, prepare the deck, run DEMO or ABAQUS, inspect diagnostics, read the
  projected door response, export the displayed curve, reopen historical runs.
- Level 3 (controlled pilot) is still withheld: drawing-role review, partitioning, two-panel motion and
  per-pair friction are not implemented, no reference correlation exists, and no tolerance has been
  agreed.
- **3D is not ready.** The 3D extrusion remains a preview; grouping 3D models is supported, but 3D
  solving, meshing and deck generation remain deferred until the 2D workflow is complete and validated.

## A5. Release-safety repair pass — 2026-11-22

Scope: matched browser/API releases, an explicit compatibility gate, atomic project creation, one
owner per data directory, a single readiness contract, fixture/deck concurrency, numeric and
laboratory-paste integrity, dashboard project/model identity, and the Reverse-X/Y axis defect.

**Baseline at start of pass.** `main` was clean at `9df297f` (one commit after `d7b6728`); the repairs
the previous audit saw as uncommitted were already committed and are preserved. The live instance on
port 8765 reported `build 4d7e4ff5f2f003f9`, `git d7b6728`, `api 2`, `frontend index-BGFyxNwQ.js`,
while the homepage served `/assets/index-D8N6_7rq.js` from a later build — the old-API/new-frontend
mismatch was reproduced. The dashboard creation path issued two requests and could leave a group
without its first model. `/api/jobs` did not exist, so the launcher's activity probe always reported
"could not be read". `Plot` preserved positive axis limits when the series was mirrored.

**Isolation.** All builds and browser acceptance ran in `I:\GithubProjects\Abaqus_QOL_impl`, populated
from the current working tree (excluding `.venv`, `node_modules`, `dist`, `releases`, `.local`), with
a repository-local `.venv` junction and an independent copy of the frontend dependencies. Browser tests
used their own temporary SQLite root and the launcher double on port 8876. No solver process was
started and no license was consumed. The publisher's data directory
(`%LOCALAPPDATA%\SimplifyAbaqus`) was inspected read-only; it was not modified (its newest write
predates this pass and no `instance.json` was created there).

**Incident and remediation.** During the pass one build was accidentally run from the publisher's
checkout instead of the isolated root. The checkout's `apps/web/dist` was replaced by the new build
(the old assets were not recoverable). The running instance on 8765 was already gone by the next
check and its data directory was intact; the checkout is now self-consistent because `dist/` and
`apps/web/releases/` contain the same published release (`ec2cedaa9dfe`). This is recorded so it is
not mistaken for a clean separation: future builds must run from the isolated root.

### Repairs and evidence

| Repair | Evidence |
|---|---|
| Immutable release directories; startup pins one release | `services/release.py`, `apps/web/scripts/publish-release.mjs`, `tests/test_release_and_compatibility.py`. Isolated A (`8898`) stayed on `ba3873ae2788` / `index-Nu0v-nbm.js` after a rebuild published `3f88561050cf`: A served its entry 200 and B's entry 404. B (`8899`, separate data) served `3f88561050cf` / `index-CAOdvt4j.js`. |
| Compatibility gate and stale tab | `apps/web/src/compatibility.ts`, `Compat.tsx`; API middleware rejects identified writes (409). Browser tests `compatibility.spec.ts` (3) cover stale tab, API-generation mismatch and bypass refusal. |
| Atomic project + first model | `POST /api/project-groups` + `creations` table; dashboard retries with the same token. Python tests cover repeat/lost response, a different token, and rollback with no orphan group; browser test loses the first response and retries. |
| One owner per data directory | `store.claim_data_root`, `instance.json`; launcher `--takeover` refuses when jobs are unreadable or active. Live check: a second launch on 8900 against the same data directory was refused with `PID 34072 on port 8898`. Unit tests cover live owner, re-entry, stale-record takeover, unreadable job list and a booting lock. |
| One readiness calculation | `services/readiness.py`, `GET /api/revisions/{id}/readiness`, workspace header blocker link. Tests cover empty, missing mesh, ready after deck, and a mesh-control change that invalidates a previous mesh. |
| Fixture/deck concurrency | `expected_hash` on fixture save, `fixture_hash` on deck preparation; stale saves/decks return 409 without mutation (`tests/test_release_and_compatibility.py`). |
| Numeric drafts | Invalid text stays visible; Save/Generate/Prepare/Submit and step navigation blocked; Escape restores. Browser test with `Prescribed Y travel` = 5 mm. |
| Laboratory paste | Draft preview, documented header, blank lines, source row numbers, rejected-row reasons, blocked Apply, Cancel preserves data. Browser test with one invalid middle row; corrected values reach the saved card. |
| Reverse axes | `plotAxis.ts` refits an auto axis and mirrors a zoomed interval; real Plotly axis limits asserted before/after in `curve.spec.ts`, including double reversal. |
| Dashboard identity | Separate project/model filters, group/model/revision/run-ID/seconds timestamp; `jobs.spec.ts` updated and passing. |

### Gate status (this pass)

| Gate | Status | Procedure and result | Remaining impact |
|---|---|---|---|
| 1 — startup, release, compatibility, atomic creation | **PASS** (automated) | Isolated A/B release pinning; stale tab and API mismatch browser tests; duplicate/lost project creation; data-root refusal; unreadable-job and active-job refusal; two-launch lock; browser-open unit path. | A real double-click with a visible browser window was not observed; browser opening is proven by intercepting `webbrowser.open`, not by an operator watching a window. |
| 2 — drawing/model/revision/draft ownership | **PASS** (existing + automated) | Existing `isolation.spec.ts` (5), `groups.spec.ts` (2), `workflow.spec.ts` (2) pass; new project/model filters and run identity. | In-viewport drawing-role review and the material partition tool remain unimplemented (separate engineering work). |
| 3 — inputs readable and hard to change silently | **PARTIAL** | Readiness API/header tests, numeric draft test, paste rejection/correction test and the material/deck test pass. | The combined cases (single material on a hollow seal, unassigned component, excluded body, zero friction, short-travel warning with JA/EN draft preservation) were not all re-run as one fresh acceptance case. Per-pair friction and body-first loading are unsupported and refused. |
| 4 — mesh, fixture, deck identity | **PASS** (automated, API-level concurrency) | Existing fixture/review browser tests (8) pass; stale fixture save and stale deck preparation rejected without mutation; Review enqueues no `POST /api/meshes` (`review.spec.ts`). | The stale-save conflict was exercised through the API from two request contexts, not two visible browser tabs. |
| 5 — playback, mirroring, provenance | **PARTIAL** | Reverse X/Y full-view and zoomed intervals asserted against real Plotly layout; delayed-frame, camera and actor-count browser tests pass; retained licensed replay from the earlier pass remains the record. | The specific WebGL case with a seal node moving beyond its panel RP, a measured zero, missing U3/RF, out-of-order scrub responses, a failed frame request and two-window uncached open was not re-run in this pass. |
| 6 — job control, performance, recovery | **PARTIAL (restore PASS, fault injection NOT RUN)** | Existing worker, cancel, retry, restart and extraction-failure tests pass (121 Python, 1 skipped). Backup/restore drill executed on isolated data: revision, deck job, fixture hash, `WSFIX` and INP SHA-256 (`a8e66b22…`) survived a stop-copy-move-restore-restart cycle; the stale `instance.json` was taken over. | Low-disk, interrupted-artifact-write and worker-disconnect fault injection were not repeated. Performance payload/time on a realistic historical dataset was not measured. |
| 7 — operator usability and engineering scope | **AUTOMATED PASS / HUMAN NOT RUN** | Both languages load and switch; 500 keys; accessibility labels and Japanese workflow labels pass. Viewport/scaling was exercised only at the default 1440×960 in the browser suite. | No representative engineer performed the six uncoached tasks; 125%/150% Windows scaling was not captured. Human usability acceptance is **NOT RUN**. |
| Final regression | **PASS** | See counts below; all six commands exit 0. | — |

### Final regression (isolated root)

| Check | Result |
|---|---|
| `python scripts/schema.py` | regenerated `apps/web/src/generated.ts`; diff contains the new readiness/project-group/Job fields only |
| `python -m pytest -q` | **122 passed, 1 skipped** (opt-in installed-runtime test skipped) |
| `npm run test:i18n` | **500 keys** in both dictionaries |
| `npm run typecheck` | pass |
| `npm run build` | release `ec2cedaa9dfe`, entry `index-CwQ1OlF7.js`, API 3 |
| `npm run test:browser` | **39 passed** |

### Release decisions (separate)

| Decision | Verdict | Dependency |
|---|---|---|
| Software release candidate for the stated local workflow | **PASS** | None for the automated scope; double-click browser opening was verified as a unit path, not observed. |
| Supervised internal engineering pilot | **BLOCKED** | Needs a supervised run by a representative engineer on the target Windows host, including 125%/150% scaling and the six-task sheet; current solver evidence is door-only. |
| Production use for engineering decisions | **BLOCKED** | Needs a trusted reference or measured curve with matching geometry, material, fixture, contact, thickness and motion, plus tolerances agreed before comparison, contact onset/force comparisons, mesh and duration sensitivity, and disposition of divergence/negative-eigenvalue warnings. No such reference exists here. |

## A6. Phase 0 — release safety repairs, 2026-11-22

Baseline `e9ca2c45`. The independent review had reopened Gates 1 and 4 and found a silent Gate 3
input error. All five findings are repaired; the live 8765 instance, its data directory and all
artifacts were untouched, and no solver was started.

1. **Atomic data-root ownership** (`services/ownership.py`). Ownership is two OS locks held for a
   process lifetime (`owner.lock` by the launcher/API, `worker.lock` by the worker), so two cold
   starts cannot both win and a crash releases the lock in the kernel. `instance.json` is diagnostic
   metadata only. A supervisor crash that leaves a worker behind keeps `worker.lock`; a new launcher
   refuses to start beside it, while an API-only start may attach to the live worker (the supported
   independent workflow). A canonical `st_dev:st_ino` identity distinguishes directories.
   Tests: barrier-synchronized two-process race (exactly one owner), crash release, stale record,
   re-entry, independent directories, orphan-worker refusal. Live smoke reproduced the refusal for a
   second launcher, a second worker and a second API on one data directory.
2. **Takeover safety** (`services/activity.py`, `GET /api/jobs`). All five durable modes are listed
   with `active` / `uncertain` / `terminal`; the endpoint sets `X-Abaqus-QOL-Jobs: all-modes-v1`.
   The launcher fails closed when that header is absent, rechecks activity immediately before
   stopping, and terminates only processes matched by module, data directory and start time. Every
   solver/extraction phase, cancellation, stale heartbeat, unknown worker and unconfirmed
   termination classifies as unsafe. A reconciled idle instance can be taken over.
3. **Atomic fixture update** (`store.set_fixture_checked`). Job eligibility, mesh digest, expected
   hash and the upsert run in one `BEGIN IMMEDIATE` transaction. A synchronized two-writer HTTP test
   yields exactly one 200 and one 409; the stored set and the generated `WSFIX` equal the winner, and
   the losing hash cannot prepare a deck.
4. **Blank numeric fields** (`NumberInput`, `draftGuard`, `Workspace`). Blank is now invalid and is
   registered synchronously, with an action-level guard for Save, mesh, deck, submission, fixture
   save and stage navigation. Escape restores the committed value. Real Edge tests cover travel,
   duration, offset, mesh size and section thickness, including a forced click on a disabled Save.
5. **Verified release publication** (`publish-release.mjs`, `services/release.py`). The publisher
   stages the whole tree, verifies referenced files, hashes the complete file manifest, publishes by
   rename, re-verifies and writes the pointer last. Interrupted publications are quarantined and
   repaired; missing inputs fail non-zero without changing the manifest; release A is byte-identical
   after publishing B. The resolver verifies every listed file and the tree digest.

**Phase 0 verification.** `pytest -q` → 158 passed, 1 skipped; `test:i18n` → 501 keys;
`typecheck` → pass; isolated build → release `679da84a7cc6` (4 files); isolated Playwright → 43
passed. The POSIX lock branch is implemented but was not exercised on this Windows host. Phases 1–5
remain; this is not a release sign-off.

## A7. Phase 1 — UI and data-presentation repairs, 2026-11-22

1. **Encoding.** Real mojibake (`Â·`, `â€”`) was removed from Dashboard and main; MeshReview’s literal
   `?` separators and the `0 ? 5` range hint were replaced by structured text/`·`/`–`. A source check
   (`apps/web/scripts/check-encoding.mjs`) rejects known mojibake sequences and runs in CI.
2. **Middle-button panning.** The viewport cancels the middle-button pointer default and `auxclick`,
   uses `overscroll-behavior: contain`, and leaves wheel zoom intact. The renderer exposes a camera
   fingerprint; the Edge test proves the camera moves while `window.scrollY` stays 0.
3. **Mesh identity.** Digest and “mesh identity” rows were removed from ordinary Mounting, Mesh,
   Review and archived-setup panels. Digests, compatibility checks, stale-deck rejection and fixture
   identity remain in the contracts and diagnostics.
4. **Components in mesh.** The review now renders structured rows (name, role, Included/Excluded/
   Not-meshed, element type(s), count, explanation) and an included-element total that must equal the
   mesh total. A reviewed rigid body is shown as intentionally excluded, not as a failed 0-element
   mesh. Mixed CPS3/CPS4R and R2D2 are shown from the measured mesh.
5. **Editable names.** `Component.alias` is an optional display name; the authoritative drawing name
   and all CAD/FE IDs stay unchanged. The assembly tree supports inline rename (Enter/Escape/Save/
   Cancel), the alias persists through revisions, is excluded from mesh identity (no remesh), and new
   result metadata records `closing.panel_name` while keeping `closing.panel` stable.

Verification: pytest 161 passed / 1 skipped, i18n 519 keys, encoding check pass, typecheck pass,
isolated release `91b90ed6d34c`, Playwright 47 passed. No solver executed; live 8765 untouched.

## A8. Phase 2 — global material library, 2026-11-22

The material definitions moved out of the per-model editor into a shared, versioned library while
each model revision keeps an immutable snapshot.

- **Schema:** additive `material_library` and `material_versions` tables; versions are insert-only.
  `Material` gained optional `library_id`/`library_version`; cards without them stay valid
  model-local cards.
- **API:** list/search/create/get/update/duplicate/archive/restore plus explicit
  `POST /api/materials/import` (never merges by name, idempotent for already-pinned cards).
- **Library page:** search, add, duplicate, rename, card editing, version history with load/compare,
  archive/restore, usage by saved revisions, model-local import, and measured-only comparison charts
  (stress–axial strain; lateral–axial) with units, legend, source note and no fabricated fit.
- **Workspace:** assignment-only Materials stage with the assigned snapshot, library pin, newer-version
  notice and explicit adoption. Test-data editing and graphs moved to the library page.
- **Versioning:** name-only edits do not create a version; card edits do. Adoption creates a new model
  revision, pins the exact version, keeps `mesh_compat` unchanged, requires a new deck, and leaves
  historical revisions and completed runs byte-unchanged (verified by artifact hashes).

Verification: pytest 168 passed / 1 skipped; i18n 567 keys; encoding check pass; typecheck pass;
isolated release `7ff922276866`; Playwright 49 passed. No solver executed; live 8765 untouched.

## A9. Phase 3 — archive and safe permanent deletion, 2026-11-22

Models and project groups gained reversible archive tombstones (`archived` columns). Default lists
hide archived rows; `include_archived=true` shows them. Archived targets are read-only at the API
(setup, import, mesh, deck, submit and new models are rejected with 409) while revisions, runs and
artifacts stay readable and downloadable. The workspace shows an archived read-only banner.

Permanent deletion is offered only for archived targets, shows dependent revision/job counts, requires
an exact-name confirmation, and is refused while any job is active or unresolved. A `deletions`
journal records the artifact set; database rows are removed in one transaction, then job directories
and unreferenced drawings are deleted. Shared drawings (duplicated models) and material library rows
are never removed. `recover_deletions()` runs at startup: an uncommitted journal is discarded without
deleting files; a committed journal finishes idempotent cleanup, and filesystem failures leave
`cleanup: pending` for the next start.

Verification: pytest 176 passed / 1 skipped; i18n 585 keys; encoding check pass; typecheck pass;
isolated release `0f28d5648c35`; Playwright 53 passed. No solver executed; 8765 was not running and
was not touched.

## A10. Phase 4 — two-step body seating / door closing, 2026-11-22

**Gate 4A PASS (license-free). Gate 4B BLOCKED (no licensed solve).**

- **Model:** `analysis.mode` defaults to `door_only`; `body_then_door` adds `motion.body`
  (offset, signed travel, duration). Two-step validation requires exactly one moving door, exactly one
  moving body, non-zero body travel and a seal region. Legacy revisions keep door-only behaviour.
- **Mesh:** body profile edges become R2D2 elements in two-step mode; door-only keeps the body
  excluded. The mesh-compatibility digest adds the mode only for two-step, so historical door-only
  digests remain valid.
- **Deck:** `write_two_step_inp` creates WS/PANEL/BODY parts and instances, both reference points and
  rigid bodies, two contact-participating rigid surfaces, an explicit `Body seating` step followed by
  `Closing`, the door held during step 1 and the body held during step 2, WSFIX throughout, propagated
  boundary conditions (no `op=NEW`), and U/RF history for both RPs in both steps.
- **Results:** metadata records ordered steps, both references, body placement/clearance/travel;
  extraction selects the reference that owns each step and projects along its direction; two-step
  history CSV has a `role` column; the results page has a curve-step selector and body axis labels.
  Manufactured playback refuses two-step rather than inventing body contact evidence.

Verification: `tests/test_two_step.py` 8 passed; `apps/web/tests/two-step.spec.ts` 1 passed; full
pytest 184 passed / 1 skipped; i18n 605 keys; isolated release `ce9798f0a74f`; Playwright 54 passed.
No solver was executed and no licensed artifact was modified.

**Gate 4B remains blocked** on an authorized two-step licensed run verifying: body moves while the door
is held, door moves while the body is held, seal deformation/contact carry over, forces/displacements
have correct units/signs, and no unexpected rigid-body motion or overconstraint. Syntax-level INP tests
are not physical validation.

## A11. Phase 5 — real-time run diagnostics, 2026-11-22

Diagnostics now leads with a status card: phase and status badge, solver and extraction separately,
current step/increment, simulated step time, last update, and a progress bar. Progress is computed
from solver-reported simulated time and the configured durations of the job's own revision — a
simulated-time fraction, never a wall-clock estimate, with no completion time.

- Queued → 0%; a known active step → fraction capped below 100%; unknown step, license wait or
  missing step time → indeterminate.
- Solver succeeded but extraction queued/running/failed → 99% with an explicit “not 100%” notice;
  100% only when solver and extraction both succeeded.
- Two-step jobs list Body seating and Closing with pending/active/complete states; legacy runs show
  Closing only.
- License wait, stale heartbeat (30 s, re-evaluated every 5 s), awaiting extraction, extraction
  failure and the diagnostic source log are distinct, labelled states. Logs stay below the summary.

Verification: `apps/web/tests/progress.spec.ts` 4 passed using mocked job/revision responses (not
solver evidence); full pytest 184 passed / 1 skipped (backend unchanged); i18n 619 keys; typecheck
pass; isolated release `5cac5e2a1e92`; Playwright 58 passed. No solver was executed.

## A12. Final regression and release decision — Phases 0–5, 2026-11-22

Final isolated matrix after the last edits (isolated root, release `5cac5e2a1e92`):

| Check | Result |
|---|---|
| `python scripts/schema.py` | exit 0; generated contract identical to checkout (`4D376FBB…`) |
| `python -m pytest -q` | **184 passed, 1 skipped** |
| `npm run test:i18n` | **619 keys** in both dictionaries |
| `npm run test:encoding` | pass, 39 source files |
| `npm run typecheck` | pass |
| `npm run build` | release `5cac5e2a1e92`, entry `index-BcID6OYd.js`, API 3, 4 files |
| `npm run test:browser` | **58 passed** |

Phase status: 0 PASS, 1 PASS, 2 PASS, 3 PASS, 4A PASS, 4B BLOCKED, 5 PASS. Gate 6
(worker/backup) is partially covered by the earlier restore drill and existing worker tests; no new
fault-injection run was made. Gate 7 remains automated-pass / human NOT RUN at 125–150% scaling.

Release decisions:

- **Software release candidate for the stated local single-host workflow: PASS** on the automated
  scope.
- **Supervised internal engineering pilot: BLOCKED** — needs supervised operator tasks and a licensed
  two-step run.
- **Production engineering decisions: BLOCKED** — no trusted reference curve, agreed tolerance or
  reviewer; no physical correlation exists.

No solver was executed in Phases 0–5 and no licensed artifact was modified. The live 8765 instance was
not running at the final checkpoints and was never touched.
