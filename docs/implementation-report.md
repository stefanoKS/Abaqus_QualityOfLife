# Implementation report — 2D engineering milestone (entry point, grouping, door response)

The [independent A–E audit and next execution brief](file-workbench-execution-handoff.md) records the full test rerun, a reproducible two-tab Retry overwrite, the active progress-card clip, and the retained material-outline replay. Its measurements distinguish ordinary same-face mesh edges from same-material seams across different CAD faces.

## A16. OTR deck preparation, typed diagnosis and resampled result exports · 2026-11-26

Execution handoff: [otr-deck-and-resampled-exports-handoff.md](otr-deck-and-resampled-exports-handoff.md).
Implemented on the working tree after `001d2db` plus the uncommitted door-pressure delivery. All
verification used disposable `SEAL_DATA` roots, the isolated browser server and ignored local
evidence. **No new licensed solver run was launched.** The two retained licensed result packages were
re-opened read-only to verify the numerical exports. The operator instance on 8765 was not contacted.

Verified build: API 3, frontend release **`c4081e11df79`** (entry `index-BPS29o-Z.js`).

| Gate | Result | Principal evidence |
|---|---|---|
| A — OTR workflow | **PASS** | Both `scripts/acceptance_dwg.py --drawing examples/OTR*.dwg` invocations exit 0 with two-step decks. Browser import → roles → material → mesh → fixture → 10 mm upward body / 10 mm downward door → Prepare passes for both drawings. INP SHA-256 `1521a89c…` (OTR) / `b57c0c0b…` (OTR_single); WSFIX equals the 10 reviewed labels; PANEL/BODY keep 95/71 original R2D2 element IDs and node sets; both SPOS surfaces face the seal. One filled region and no cavity section; Body seating then Closing; door and body contact pairs; `DOOR_PROFILE_NODES` requests CFORCE with global CSTRESS. |
| B — Geometry and diagnosis | **PASS** | `tests/test_profile_topology.py` (8 tests) covers shuffled/reversed input, the curved return, vertical and equal-X endpoints, straight/sloped legacy order, typed branch/disconnected/closed/repeated/degenerate/self-intersecting rejections, and preservation of the typed code in the worker diagnostic. Readiness reports the same `panel.branched_profile` code/stage as the writer. Browser `deck-status.spec.ts` (3 tests) proves failed → actual diagnostic + failed stage + recovery, and “fixed nodes changed” only for a real hash mismatch; EN/JA both checked. The 19 affected existing fixture/readiness/review/layout tests pass. |
| C — Load CSV | **PASS (numerical)** | Real browser bytes at 1 mm: `stroke(mm),0,1,2,2.5` / `F (N/100mm),0,0,8.26096907258,51.3679385185` on `9efc065a`. At 0.65 mm, **5.61357017395 N/100mm at 1.95 mm** (reference 5.6135701740). Manufactured tests cover invalid/zero/negative/tiny intervals, multivalued → original ordered samples, repeated identical strokes, `F (N/80mm)`, `F (N/mm)` and legacy `F (N)` with no second scaling, Reverse Y once and Reverse X not negating stroke. |
| D — Pressure CSV | **PASS (numerical)** | `9efc065a` final frame, 1.3 mm: **67.179839313 kPa at 11.7 mm, 125.8664876223 at 13.0, 52.4925112724 at 14.3 and 0 at 24.0**; endpoint once. A second 2.0 mm interval hits the measured 12.0 mm value (57.2002381086) and still ends once at 24.0. GENKOU Step-2 final `UPPER_ROOFBARA-1`: **17.0842183789 at 35.1, 0 at 45.5, 14.0379243522 at 55.9**; last station 73.5880868374 once; original nodes retain the 45.5090888 kPa peak at 56.405592 mm. All-zero, null/missing, ambiguous, mismatched-array, profile switching and in-flight-frame tests pass; chart, bytes and filename identify the same frame. |
| E — Portability and delivery | **PASS** | The accepted live run and the same `.aqresult` reopened in a fresh root produce **byte-identical** load and pressure CSVs for matching settings; the package digest, live `results.json` and `history.csv` are unchanged after both reads. A legacy load-only result exports `F (N)` and shows pressure unavailable. Python **391 passed, 1 skipped**; translations **1045 keys**; encoding 48 files; typecheck and build pass. Full isolated browser suite recorded below. |

### What was implemented

- **Topology versus orientation.** `panel_order` now walks a degree-two open R2D2 chain from its
  deterministic endpoint and accepts local X returns, vertical portions and equal-X endpoints. It
  preserves every original element ID and node identity and rejects real defects with typed
  `PreparationError` codes and stages: malformed, zero length, repeated element, closed ring,
  disconnected islands, branches and self-intersection. Contact-side orientation is a separate
  decision. `orient_toward` measures each element's SPOS normal against the local nearest seal
  surface at the predicted first-contact neighborhood, flips the chain only as a unit and re-checks
  the oriented normals. Station order in Results remains derived independently from the assembled
  ODB connectivity.
- **Readiness agrees with the writer.** `services/readiness.py` catches `PreparationError` (including
  `ClearanceError`) and emits the same code/stage/role as a blocker; an unexplained assembly failure
  also blocks instead of silently returning “ready”. The browser deck card is status-driven (missing,
  preparing, failed, cancelled, newer deck, superseded mesh, proven stale fixture), keeps the worker
  diagnostic and failed stage, and offers diagnostics/recovery. “The fixed nodes changed” is reserved
  for a real `fixture_hash` mismatch.
- **Two-row exports.** `apps/web/src/features/run/export.ts` builds uniform grids from integer
  indices, appends the exact measured endpoint once, interpolates against stroke or arc-length
  station, keeps nulls as empty cells and refuses unbounded allocations. Results adds independent
  editable intervals (1.0 mm load, 1.3 mm pressure), original-sample modes, contextual basis labels
  and filesystem-safe filenames. Both exports read the immutable result data already used by the
  displayed chart and its portable `.aqresult`; no solver artifact is rewritten.
- **Curved OTR evidence.** With the original DWGs, the geometry-only assessment predicts first
  contact at **4.8487 mm** of the 10 mm downward door stroke and **8.1912 mm** of the 10 mm upward
  body stroke, matching the handoff's independent geometric check. The local first-contact SPOS dot
  is **+0.923** (door, 10 elements) and **+0.860** (body, 8 elements); every local normal is positive.
  This is undeformed geometry, not solver contact or convergence evidence.

### Full isolated browser suite

Build `c4081e11df79`, port 19964: **186 passed, 4 failed, 10 skipped** (200 tests, 22.8 min). The
four failures are the known suite-load/timing cases and are not gate regressions: `gate-f` playback
cadence, `motion-preview` body/door equality, `offset-picking`, and the centred `partition` mixed-draft
guide. A rerun of those four files together produced 8 passed, 1 skipped and `offset-picking`;
`offset-picking` then passed alone in 16.1 s. The new `otr-workflow` (2), `deck-status` (3),
`resampled-exports` (7 with the retained packages), `resampled-exports-manufactured` (3) and the
updated `curve`/`gate-d`/`force-axis` tests all passed in the suite.

### Evidence

Local (ignored): [acceptance log](../.local/evidence/otr-deck-exports/acceptance.log),
[Gate A OTR proof](../.local/evidence/otr-deck-exports/gate-a-otr.json),
[deck summary](../.local/evidence/otr-deck-exports/deck-summary.json),
[OTR INP](../.local/evidence/otr-deck-exports/OTR-analysis.inp),
[OTR_single INP](../.local/evidence/otr-deck-exports/OTR_single-analysis.inp),
representative CSVs under `.local/evidence/otr-deck-exports/`, and the full browser log
`browser-full.log`.

### Limits

**Solver convergence, numerical sensitivity and physical correlation remain unestablished.** The OTR
decks were not submitted to Abaqus. The export numbers are read from two retained licensed packages,
not from a new solve. `3D` solving remains deferred.


## A15. Door-panel contact pressure through Prepare, Submit, ODB extraction, Results and `.aqresult` · 2026-11-25

Execution handoff: [door-panel-pressure-handoff.md](door-panel-pressure-handoff.md). Implemented on
the working tree after `001d2db`. All development verification used disposable `SEAL_DATA` roots,
the isolated browser server and local ignored evidence. Two small licensed runs were executed; one
6.5 mm trial was cancelled after it stopped progressing and is not evidence. The operator instance
on 8765 was not contacted or modified.

Verified build: API 3, frontend release **`24102ca8108b`** (entry `index-Duef0qdY.js`). Accepted
licensed run **`9efc065a-805c-4215-b651-3349f6ebba24`** (solver and extraction succeeded, exit
0/0), produced through the browser from Dashboard → New project → DXF import → roles → materials →
mesh → fixture → motion → Prepare → Submit.

| Gate | Result | Principal evidence |
|---|---|---|
| A — Deck and identity | **PASS** | A 49-node open profile gets one `DOOR_PROFILE_NODES` NSET equal to the unique geometric R2D2 nodes, excluding `PANEL_RP`, seal and body. Global stress on → one global `CSTRESS` plus door-set `CFORCE`; global stress off → door-set `CFORCE, CSTRESS`. `U` is present. Both two-step steps request door output; `mesh_compat` is unchanged by the output-only edit; opt-out/re-opt-in decks changed then returned to the exact original INP hash; historical INP bytes stayed immutable. |
| B — Numerical reference | **PASS (exact)** | Production `extract_odb` + `door_pressure` vs the independent reader on all three supplied ODBs at four frames: 608 stations × 12 frames = **7,296 samples**, maximum error **0 mm / 0 kPa / 0 N**, null masks and native frame IDs identical. Positive counts 30/35/39. |
| C — Licensed workflow | **PASS** | The door-only run above produced 26 frames; one door profile of 49 nodes, 11 positive, node 230 at station 13.5 mm with **165.369302 kPa** (native 0.165369302 MPa) and CNORMF **(2.56e-05, 0.0826014) N**. ODB, live Results and reopened `.aqresult` agree exactly. A second **body-plus-door** run `25fa7055-…` (4.0 mm seating / 2.5 mm closing, 42 frames) had **zero** door pressure throughout Body seating and 9 positive stations in Closing; final peak node 250 at 11.5 mm with 5.145417 kPa. Deck/ODB/index/`.aqresult` hashes are in the validation record. |
| D — Arrow and graph | **PASS (browser)** | GENKOU `UPPER_ROOFBARA-1` final frame: 124 stations, 6 positive in **two patches**, node 17 at 56.405592 mm / 45.509089 kPa / (0.021603798, 0.014067459) N; direction dot > 0.999; anchor within 2 CSS px of the re-projected deformed node; zero frame draws no arrows; delayed fetch and step transition keep graph, glyphs and camera together; both axis titles readable at 1280 × 720 in EN and JA. |
| E — Portability and history | **PASS** | The worker-published `.aqresult` reopened in an empty data root: 26 frames byte-identical, frame order, 49-label/24 mm profile axis, units and history identical; source artifacts unchanged. A retained pre-pressure result also reopened with identical frames/history and no pressure metadata. |
| F — Regression and reporting | **PASS** | Python **383 passed, 1 skipped**; translations **990 keys**; encoding 47 files; typecheck pass; release `24102ca8108b`; schema diff additive only. Full isolated browser suite **171 passed, 4 failed, 8 skipped**; the four failures are the known suite-load cases (camera Fit/reset, materials validation, offset-picking, centered partition) and all four passed together in an isolated 17.1 s rerun. Targeted door-pressure specs (external reference, existing licensed run, full licensed workflow, arrows on/off) all passed. |

### What was implemented

- **Deck**: `Analysis.door_pressure` (default true) is the output plan. `write_inp` and
  `write_two_step_inp` add `DOOR_PROFILE_NODES` from the actual emitted PANEL connectivity and never
  include the rigid RP. `output_cards` requests the fields exactly once per step and adds `U` when
  needed for deformed anchors. Global `CSTRESS` and the door-set request are mutually exclusive in
  the way the licensed pilots proved safe.
- **Extraction**: `integrations/abaqus/door_pressure.py` (stdlib only) walks connected R2D2 chains in
  assembled undeformed XY, starts at the lexicographically smallest endpoint, sums Euclidean stations,
  and reports closed/branched/missing topology instead of guessing. It performs the single
  1000 × MPa→kPa conversion and coalesces duplicate observations only when exactly identical.
  `extract_odb.py` samples both `CPRESS` and `CNORMF`, preserves native and display values, the
  contact domain, instance-qualified node identity, ambiguity reasons and per-profile maxima; the
  launcher copies the new module beside the extractor.
- **Portable result**: `results.json` carries the profile axis, units, contact attribution, field
  keys and scale maxima; each `frame-*.json` carries aligned pressure/force arrays or explicit
  nulls. No new sidecar member was needed, so existing `.aqresult` readers remain compatible.
- **Results UI**: `RunView` adds a Door contact pressure view with profile selector, pressure-arrow
  toggle, spatial graph (station mm vs kPa), reference-arrow scale and a station readout that names
  the same node's native MPa and signed CNORMF. `CNORMF` is a selectable nodal-magnitude field with
  a signed probe. `ViewportRenderer` draws non-pickable glyphs on the shared affine projection, so
  pan/zoom/deformation follow the rendered node; `Plot` gained hover selection. Both dictionaries
  were extended and the previously missing output control is in Motion → Analysis settings.

### Evidence

Local (ignored) evidence: [Gate A deck](../.local/evidence/door-panel-pressure/gate-a-deck.json),
[Gate B comparison](../.local/evidence/door-panel-pressure/gate-b-comparison.json),
[GENKOU EN](../.local/evidence/door-panel-pressure/gate-d-genkou-en.png),
[GENKOU JA](../.local/evidence/door-panel-pressure/gate-d-genkou-ja.png),
[licensed triple-source match](../.local/gate-c/evidence/gate-c-evidence.json),
[reopen comparison](../.local/gate-c/evidence/gate-e-reopen.json),
[licensed EN](../.local/gate-c/evidence/gate-c-app-en.png),
[licensed JA](../.local/gate-c/evidence/gate-c-app-ja.png) and
[arrows on/off timing](../.local/gate-c/evidence/gate-f-timing.json).

### Limits

No mesh refinement, independent physical measurement or agreed tolerance was produced, so
**numerical sensitivity and physical correlation remain unestablished**. The tensile-pressure sign
path is unit-tested but no solver result contains a negative pressure. A reference ODB with several
door profiles is supported by the explicit instance mapping; a general-purpose native ODB browser is
still outside this slice.

## A14. File ownership, navigation, Close and faithful CAE material support · 2026-11-25

Execution handoff: [file-open-materials-navigation-handoff.md](file-open-materials-navigation-handoff.md).
The previously uncommitted A–E delivery was committed by the operator session as `2f569ed` while
this pass ran; the changes here are uncommitted on top of it and no preserved file was discarded.
All writes used disposable `SEAL_DATA` roots, the isolated `--test-data` browser server and
temporary folders. The operator instance on 8765, its database, drawings and retained licensed
artifacts were not contacted, stopped or modified. **No solver was launched.** One Abaqus/CAE 2024
noGUI session was used for the material-reference check and consumed CAE license tokens (see the
validation record).

Verified build: API 3, frontend release **`055f04911427`** (entry `index-kfFfAlip.js`), from this
checkout plus the uncommitted changes. The release was rebuilt after the final source edits; the
manifest records the exact files.

| Gate | Result | Principal evidence |
|---|---|---|
| A — Standalone file ownership | **PASS** | An internal, name-independent owner (`groups.internal=1`, unique partial index) is resolved and validated in the same write transaction as the new head. With the historical `Imported projects` group archived, File → New and Open Model return `archived=false, group_archived=false`, no banner, enabled Save, a persisted edit (100 → 111 mm) and a queued drawing import. Explicit creation in the archived group still returns 409, historical replays stay read-only, recovery copies create a distinct editable identity, and eight concurrent creates leave exactly one internal owner row and eight owned models. |
| B — Dashboard entry point and Close | **PASS** | Nav renders and tabs Dashboard → Workspace → Materials in JA/EN at 1440 and 390 px. Cold start opens Dashboard. Materials is a detour that returns to the tab's own document. Close ends only that tab's document session (sessionStorage), keeps recents and the working head, and Workspace/refresh do not silently reopen it. Save, Ctrl+S, Save As and Save & Close share one path that flushes the workspace autosave and packages the revision the flush returned: with the working-head PUT deliberately held, both Save and Save & Close left the on-disk file at **111 mm**, reopened from a fresh model. Cancel and a failed disk write keep the document and its draft. |
| B — Portable-open restore | **PASS** | A compatible 37-node fixture travels with the model and reopens in a fresh data root with `can_prepare=true`, `mounting.reviewed` count 37 and no new node selection. An incompatible identity, a truncated mesh, a mesh without identity and a fixture from other bytes are each reported by stable code and never adopted; a restored drawing is byte-identical to the original. |
| C — Faithful CAE library support | **PASS (software)** | All **27** source records register (was 2); **19** are ready for a new 2D run, 7 name the missing density, 1 (thermal-only) names the missing structural law. All **11 Hyperfoam** records — 6 test-data N=1, 1 direct N=1, and 4 Prony-coupled N=3/N=5 — emit their law, options, active columns and every numerical row; a CAE 2024 reference import re-read **5 representative combinations** value-for-value (Hyperfoam test data, direct N=1, direct N=5 + Prony, Yeoh + Mullins, elastic + plastic). The reference check found and fixed two real writer defects (see below). |
| — Solver execution / physical correlation | **BLOCKED** (unchanged) | No licensed solve was run; nothing here is solver or physical evidence. |

### Gate A — the archived owner

`services/store.py` now carries `groups.internal` (default 0) with a partial unique index on
`internal=1`. `file_group(db)` finds or creates that one row **inside the caller's
`BEGIN IMMEDIATE` transaction**, so a head and its owner are created atomically. `append_revision`
defaults an omitted group to the file owner instead of the historical migration group and validates
an explicit group's archive state in the same transaction. The migration backfill for pre-grouping
databases still uses `legacy_group` deliberately, so existing history is untouched. Archive and
delete of the internal owner are refused by the API, not only hidden in the browser; its model list
is visible with an `internal` flag and no group-level archive/delete controls.

`POST /api/projects/{pid}/recover` copies a stranded head into the file owner; duplication of a
model in an archived group also lands in the file owner so the copy is editable. Originals, their
revisions, submitted replays and result files are untouched.

Measured: `tests/test_archived_owner.py` (11 tests) and `apps/web/tests/archived-owner.spec.ts`
(2 Edge journeys). Eight concurrent creates: 1 internal row, 8 owned models.

### Gate B — Dashboard first and Close

`main.tsx` initialises an empty route to `dashboard` and renders Dashboard → Workspace → Materials.
`api.ts` adds a tab-scoped document session (`abaqus-qol.activeDocument`, `…closedDocument`) next to
the global recent-file list. Close records the project as closed **for that tab only**, removes the
recently closed tab's `lastModel` entry and returns to Dashboard; Workspace, refresh and another tab
are unaffected. `Save & Close` settles the working head (polling until two identical heads), packages
the flushed revision, and re-packages if the head moved while writing.

Measured: `apps/web/tests/file-close.spec.ts` (9 tests, including the held-PUT cases and a Japanese
folder/file name), `tests/test_portable_restore.py` (6 tests), `tests/test_archived_owner.py`.

### Gate C — faithful registration and deck support

* `abaqus_lib.assessment()` replaces the old "eligible/ineligible" gate. Every well-formed record is
  registrable with its source hierarchy, units, Japanese text and fingerprint; run suitability is a
  separate answer with named needs (`density`, `structural_law`) and precise unsupported-option codes.
* `Material` gained typed `hyperfoam`, `hyperelastic`, `viscoelastic`, `plastic`, `mullins` and
  `thermal` blocks plus `model="cae_law"`, and `density` is nullable. A metal cae_law card needs a
  structural law; a thermal-only record is registered but not runnable.
* `material_versions` was rebuilt once to allow a null density and gained a `properties` column that
  stores the canonical card; legacy rows read unchanged.
* `deck.material_cards` emits the registered law: `*Hyperfoam` test data (2 active columns when the
  source lateral flag is OFF — its zero third column is storage, not data), direct coefficients
  packed 8 values per line in keyword order, `moduli=INSTANTANEOUS` when the source says so,
  `*Hyperelastic` with `*Uniaxial Test Data`, `*Viscoelastic, time=PRONY`, `*Mullins Effect`,
  `*Plastic`, `*Conductivity`/`*Specific Heat`. Missing density or structural law refuses by name.
* The import endpoint returns per-record outcomes, accepts a per-card `families` map (defaulting from
  a modulus-based hint, never one bulk family for a mixed import), stays idempotent for an identical
  record and keeps a divergent same-name record separately named.
* The Materials page selects all registrable records, shows "ready / needs density / no structural
  law", offers a per-card family selector and a read-only law/table view; the density may be supplied
  in a new version without rewriting the law. Export is explicitly `mode: original-file`.

**CAE reference check.** An Abaqus/CAE 2024 noGUI session imported the app-emitted material
keywords for E13, EPTO_E110, DKSPONGEHK, E18WW and SPCC and re-read every behaviour and value. The
first run failed and produced two defects that reading the keyword reference alone had not caught:

1. A direct `*Hyperfoam` row must be packed **at most eight values per data line**; the app emitted
   one 3N-value line, which CAE 2024 rejects with `IndexError … *HYPERFOAM`.
2. CAE 2024 rejects a `DEFINITION` parameter on the Mullins constants form; the accepted keyword is
   the bare `*Mullins Effect`.

After the fixes all five combinations re-read value-for-value
(`.local/evidence/cae-reference/cae-reference-verdict.json`, 5/5 PASS). This is reference-input
evidence only, not solver acceptance.

### Tests actually run (this machine, isolated data)

* `.\.venv\Scripts\python.exe -m pytest -q`: **364 passed, 1 skipped** (the opt-in Abaqus-Python
  roundtrip), exit 0.
* New suites: `test_archived_owner.py` (12), `test_portable_restore.py` (6), `test_cae_materials.py`
  (18).
* `test:i18n`: **970 keys** both languages. `test:encoding`: 47 files. `typecheck`: pass.
* Build: release **`055f04911427`**, entry `index-kfFfAlip.js`, API 3.
* Browser: feature specs `archived-owner.spec.ts` (2), `file-close.spec.ts` (9),
  `cae-materials.spec.ts` (1), `isolation.spec.ts` (5), `materials.spec.ts` (7),
  `offset-picking.spec.ts` (1), `partition.spec.ts` (5), `prepare-readiness.spec.ts` (5) — all passed
  on isolated servers. **Full suite on the final build: 171 passed, 4 skipped, 4 failed** (179 tests).
  The failures are suite-load cases: playback cadence (71.7 ms > 50 ms; no playback code changed and
  it reproduces alone on this machine), both `materials.spec.ts` journeys (passed in the isolated
  7-test run) and `offset-picking` (passed in isolation). None of the four is a Gate A–C test.
* `scripts/schema.py` was regenerated and inspected.

### Blocked and outstanding

1. **Licensed solver acceptance and physical correlation remain BLOCKED.** No Hyperfoam card was
   solved; the reference check proves the input keywords, not convergence or material behaviour.
2. **Registered-only material policy is partial.** A model-local (unpinned) card is still usable with
   a `material.unregistered` warning, as before; it is not a Prepare blocker yet, so
   `tests/support`-style synthetic models keep working. Completing that migration is the next slice.
3. **CAE GUI library round-trip is not automated.** The kernel/reference read is verified; the
   Material Library Manager file-open path is not scriptable here.
4. **Hyperelastic direct coefficients** for N>1 Ogden/Polynomial are emitted as one row; the supplied
   library only contains N=1 direct hyperelastics, so that path is untested against CAE.
5. The full browser suite is not green under load: playback cadence (71.7 ms vs ≤50 ms, no playback
   code changed and it reproduces alone on this machine), both `materials.spec.ts` journeys and
   `offset-picking` failed in the 179-test run but pass on isolated servers. They are recorded as
   environment/timing failures, not gate evidence.

## A13. Workbench model edit, readiness, dashboard, force axis and material outlines · 2026-11-24

Baseline `84ab7a2fdeaaa5068cddb8ea6ad9164ebe3159ff` on `main`, matching the audited baseline in the
[execution brief](model-edit-readiness-results-handoff.txt); the only prior working-tree change was the
brief and the existing handoff entry. All writes used the isolated `--test-data` browser service on
port 8876, a disposable `SEAL_DATA` directory for Python, and temporary paths for the evidence scripts.
The operator instance on port 8765, its database, drawings and retained licensed artifacts were not
stopped, restarted or modified. **No licensed solver was launched and no license was consumed.** The
manufactured launcher double supplied every completed run used here; retained operator results were not
re-read and their 8-interface/4-same-material-seam observation remains the operator's own measurement.

Verified build: API build `be1bb24c071006c8`, frontend release **`4933ae101e08`**
(entry `index-BZ3wYYIK.js`, CSS `index-B5CPZgAZ.css`, API 3) from checkout `84ab7a2` plus these
uncommitted changes.

| Gate | Result | Principal evidence |
|---|---|---|
| A — Dashboard runs | **PASS** | Long-name filters and every run state at 1440×900, 1280×720, 720×450 and 390×844 in both languages: filter overhang **0 px** (was 166/148 px), page horizontal overflow **0 px**, table scroller `scrollWidth == clientWidth`, last row and its last action reachable. |
| B — Replace the current model | **PASS** | Automatic head replacement with coalescing, serialized writes, retained drafts, idempotent recovery and a recoverable two-tab conflict; no Save revision or Save contact control; submitted setup/mesh/deck/result hashes unchanged by later edits. |
| C — Order, readiness and locks | **PASS** | All 12 transition rows exercised through the UI and direct API; the visible Prepare/Submit state matched `/readiness` in every row; the padlock is now reserved for the deferred 3D extrusion. |
| D — Readable force axis | **PASS** | Full description in a wrapping caption beside the plot; rotated Y title **52.5 px** (`N`) and **80.0 px** (`N/mm`) inside a **210 px** plot at every width and 200% zoom (was ~269 px, 45 px above and 14 px below). |
| E — Material outlines | **PASS on manufactured evidence; operator retained-run recheck not repeated in A13** | Renderer-free invariants plus a real API→worker→manufactured-result run: **36** internal FE material interfaces, **184** perimeter segments, **1006** same-material interior edges excluded, **567/567** deformable elements mapped, rigid `PANEL-1` excluded. |
| — Physical correlation / solver physics | **BLOCKED** (unchanged) | No licensed solve was run; nothing here is physical validation. |

### A. Dashboard runs

The dashboard filter header is now a shrinking flex row inside the run card; native selects are
clamped (`min-width: 0; max-width: 100%`) so a long project/model option can no longer set the card's
intrinsic width. Below 760 px the table becomes one labelled compact row per run (identity, state,
submitted, elapsed, actions) instead of a horizontally scrolling table, and the run list still scrolls
with the page. Run names wrap with their full value in `title`, and the table scroller is a focusable,
labelled region.

Rendered measurements (`dashboard-measurements.json`, fictional long Japanese names, 12 rows in four
states in both locales):

| Window | Card width | Filters width | Filter overhang past card | Page horizontal overflow | Table scroller (scroll/client) |
|---|---|---|---|---|---|
| 1440×900 en/ja | 1393.9 | 1199.6 / 1223.2 | **0** | 0 | 1392/1392 |
| 1280×720 en/ja | 1239.1 | 1044.7 / 1068.3 | **0** | 0 | 1237/1237 |
| 720×450 en/ja | 688.0 | 656.0 | **0** | 0 | 686/686 |
| 390×844 en/ja | 358.0 | 326.0 | **0** | 0 | 356/356 (compact layout) |

Before, from the audited brief and reproduced by the same measurement: at 390 px the table needed
133 px of horizontal scrolling, and with long names two filter controls protruded **166 px** and
**148 px** past the card's clipping edge. The table's own scroller could reveal its last action but did
not contain the filter header. Filtering to an active run and reaching Diagnostics and Cancel by
keyboard caused **zero** cancel requests; an intentional activation caused exactly one. A real
manufactured Running/Queued pair rendered as active and was not cancelled by inspection.

### B. Replacing the current model during normal editing

[autosave.ts](../apps/web/src/features/workspace/autosave.ts) is the single writer. A valid committed
edit is coalesced (350 ms) and replaces the working head; the store still appends an immutable revision
per committed write, so a run, mesh, deck, fixture or historical link keeps referring to exactly what it
used. The URL follows the new head with `history.replaceState` only — no router event, no remount — so
focus, the focused field, the active stage, the selection, the camera and any in-progress draft survive.
`main.tsx` keeps mounting the workspace on the stable model identity for the same reason. Writes are
serialized per model, edits that arrive while a request is in flight are retained and written next, and
a response for a different model/generation is discarded. A 409 from another tab keeps the unsent draft,
says “Another revision was saved…”, and an explicit **Retry** adopts the newer head. A lost response is
recovered idempotently: Retry reads the head first and adopts it when it already contains the draft, so
the navigation adds exactly one revision instead of two.

Removed: the header **Save revision** button and the Contact **Save contact** action (the latter could
discard unrelated pending setup edits). Added: a compact localized `Saved automatically /
Saving changes… / Save failed` state with a Retry button and its cause, and **Duplicate setup** as the
explicit branch action. Prepare is disabled with the temporary “Saving changes…” reason only while the
write is genuinely in flight; a failed write blocks Prepare with “The current edits are not saved.” Mesh,
partition preview/Apply, Prepare, Submit, Duplicate and navigating away all flush and await the latest
valid edit, using the newest rendered draft synchronously so work is never queued from the previous
settings. An invalid numeric draft is never committed and keeps its field feedback and the existing
Escape restore.

Verified behaviours (real Edge, manufactured worker): immediate Generate-mesh after typing used the new
size; three rapid edits produced at most two revisions and the final value; a background save preserved
focus, stage and camera; navigating away committed the edit; an aborted PUT kept the value, showed the
cause and retried; a delivered-but-lost response retried without a duplicate revision; two tabs
surfaced a conflict and converged after Retry; editing a submitted model left the revision setup JSON
and the INP, mesh and `results.json` SHA-256 values byte-identical and its `/setup/<run>` link
read-only; switching models during a pending write kept both models independent.

### C. Setting order, readiness and locks

`services/readiness.py` now renders a role, mesh, mounting, motion or deck prerequisite as
**incomplete** with the owning stage and reason; the padlock is reserved for the deferred 3D extrusion
(the only read-only restriction in this phase). A local draft overlays the stale server snapshot, so
correcting a role can never leave a padlock beside an editable selector. Mounting reports
`mounting.awaiting_mesh` before a mesh exists, and the mesh stage names the missing drawing or roles.
Prepare/Submit remain one action-specific decision shared by the controls, the click handlers and the
API. The table below is the requested matrix; “UI” means the real browser, “API” the direct readiness
document.

| State or edit | Observed behaviour | Artifact identity used |
|---|---|---|
| Empty editable 2D model | Import actionable; every stage opens; **no padlock** anywhere; Mesh and Prepare name `drawing.missing`; `can_prepare=false`. | — |
| Drawing imported, roles missing | Components opens editable immediately, badge **incomplete** (`components.no_*`); the last role correction clears it without visiting Mesh or a manual save; one/two-step mode derived from participating roles. | head revision only |
| Roles correct, materials missing | Components complete; Materials incomplete with `material.unassigned` naming regions `foot`/`bulb`; partition remains available on valid geometry before a mesh. | head revision |
| Valid mesh inputs, no FE mesh | Generate mesh actionable; Contact and Motion open and accept edits before a mesh; Mounting explains `mounting.awaiting_mesh`; Prepare names `mesh.missing`. | mesh inputs digest |
| Role-dependent settings | Door↔seal and seal↔self always; body↔seal only while a body participates; 0.7 defaults for new models and stored values preserved; step plan changes with roles without a Contact visit. | head revision |
| New mesh, no reviewed fixed nodes | Mounting actionable when the mesh completes; Prepare names `mounting.missing`; one **Save fixed nodes** gesture associates the selection with this mesh; a discarded/pending rectangle never overwrites the saved set. | mesh job + fixture hash |
| Mesh and fixture ready, no deck | Prepare enabled, Submit blocked on `deck.missing`; one Prepare click queued exactly **one** DECK with that mesh and fixture hash; Submit then enabled. | mesh id + fixture hash |
| Friction 0.70 → 0.63 | Committed automatically; same mesh and same fixture hash; Mounting stayed visible and usable; the old deck became stale and Submit blocked; Prepare rebuilt one deck for the new head with the same mesh/fixture. | mesh id, fixture hash |
| Mesh-affecting change | A material-card value change reused the compatible mesh; changing global size made the mesh incompatible, said the mesh inputs changed, named `mesh.missing` and left the old mesh artifact readable. | mesh compatibility digest |
| Fixed nodes on the same mesh | Expected-hash write: a stale tab receives a recoverable conflict, the identical set is idempotent, the old deck is invalidated and Prepare can rebuild. | fixture hash |
| Deck ready | Submit enabled only for the current prepared deck and valid Submit-only settings; CPU 0 and a blank run name each disabled Submit with their own reason while Prepare stayed usable; the contract rejects the same values directly. | deck id + revision |
| Run / historical replay | `/setup/<run>` shows “Submitted setup · read-only”, no automatic writer, disabled actions; later head edits left the run's revision, mesh, deck and results byte-identical; Results open independently; 3D remains preview-only. | run revision + deck snapshot |

### D. Readable force axis

The long rotated title is gone from the axis. The full phrase is a wrapping semantic caption next to
the plot (`aria-describedby` on the plot, and the plot's accessible name carries both directions), while
the Y axis keeps a concise unit-bearing title. Measured against the real clipping container:

| Case | Plot height | Y title height | Y within plot | X title width / plot width |
|---|---|---|---|---|
| 1440/1280/720/390, English, `N` | 210 | **52.5** | top ≥ plot top, bottom ≤ plot bottom | 111.6 / 332–424 |
| 1440/1280/720/390, Japanese, `N` | 210 | **34.2** | inside | 59.9 / 332–424 |
| `N/mm` | 210 | **80.0** | inside | 111.6 / 424 |
| Body seating step | 210 | **80.0** | inside | 111.6 / 424 |
| Reverse Y | 210 | **80.0** | inside | 111.6 / 424 |

Before: the English title measured about **269 px** vertically in the **210 px** host and extended
**45 px above** and **14 px below** the SVG at every width. The plotted trace, zoom, picking and the
two-row exported CSV were re-checked unchanged (the existing signed-projection, step-switch and export
test still passes, including `4,-3` and Reverse-Y `-4,3`).

### E. Material outlines

The overlay is built from each deformable instance's **original element connectivity and local node
labels**, not from renderer vertices, so an element-based stress display with duplicated corner vertices
cannot change its topology. Face→material identity comes from the job's immutable submitted revision
with the pinned library version in the key. A shared FE edge with two distinct materials becomes one
interface associated with both; an edge shared by two CAD faces that carry the same material is not an
interface; edges with one incident element are perimeters (outer and cavity); rigid `R2D2` instances are
excluded; a result without regional mapping draws nothing and disables the toggle with the reason.

Renderer-free synthetic invariants (CI, no solver): a two-material bonded patch gives **2** interfaces
and **8** perimeters with the rigid panel excluded; the same patch with one material gives **0**
interfaces (four same-material seams skipped); a pinned version change splits the identity; a hollow
triangle ring gives **0** interfaces and **8** perimeter edges including the **4** inner cavity edges;
a legacy result with no regions maps **0** elements and draws nothing; the overlay follows the frame's
displacements, Deformed toggle and scale and is never a probe/pick target.

Manufactured API→worker→result run (default synthetic section, two materials, `PANEL-1` rigid):

| Quantity | Count |
|---|---|
| Mesh nodes / elements | 708 / 615 |
| Deformable seal elements / mapped | 567 / **567** |
| Effective materials | `card:base_rubber`, `card:bulb_foam` |
| Internal material interfaces | **36** |
| Perimeter segments | **184** |
| Same-material interior edges excluded | **1006**, all within a single CAD face per edge |

The browser test recomputes the interface count independently from `results.json` and the pinned
revision and compares it with the rendered overlay dataset and the legend; toggling mesh edges, node
markers, Deformed and frames changes neither the count nor the legend. A single-material run keeps a
readable perimeter, reports **0** interfaces and says so.

### Tests actually run (this machine, isolated data)

- `.\.venv\Scripts\python.exe -m pytest -q`: **305 passed, 1 skipped** (opt-in Abaqus-Python roundtrip).
- `npm --prefix apps/web run test:i18n`: **879 keys** in both dictionaries. `test:encoding`: 45 files.
- `npm --prefix apps/web run typecheck`: pass.
- `npm --prefix apps/web run build`: release **`4933ae101e08`**, entry `index-BZ3wYYIK.js`, API 3.
- `npm --prefix apps/web run test:browser`: **150 passed, 4 skipped, 0 failed** (154 tests). The four
  skips are the two opt-in retained-result replays (no local seed on this run), the gated screenshot
  capture and the retained native-lip drawing check.
- `.\.venv\Scripts\python.exe scripts\schema.py`: regenerated `generated.ts` byte-identically (no diff).
- `git diff --check`: clean (line-ending notices only).

Manufactured evidence: every run in these suites used the license-free launcher double. No retained
operator row, drawing, deck or ODB was read or changed by this pass.

### Evidence files (local, not committed)

`.local/evidence/dashboard-{1440,1280,720,390}-{en,ja}.png`,
`dashboard-measurements.json`, `force-axis-measurements.json`,
`material-outlines-{undeformed,deformed}.png`, and `.local/gate-e-counts.py` (isolated independent
count). The existing `.local/evidence` axis replay files are from the earlier retained-run pass.

### Outstanding

- Operator's running instance (port 8765, release `5be20b24e6d0` at the brief's audit) was **not**
  restarted or upgraded; this report describes the verified isolated build separately.
- The operator's retained two-material result was not re-read: its 8-interface / 4-same-material-seam
  count remains an operator observation. The synthetic CI equivalent and a fresh manufactured run are
  the evidence here.
- No licensed solve, numerical sensitivity study or physical correlation was performed; physical
  correlation, self-contact participation and 3D solving remain **BLOCKED**.
- Materials comparison and one renderer run failed once in full-suite runs under shared data and passed
  after the concrete fixes (the renderer case waited for the now-persisted 2D/3D display to settle;
  materials passes in isolation, the same pre-existing intermittency noted in A12). The definitive full
  run on the final build and test tree is **150 passed, 4 skipped, 0 failed**.

## A12. Hollow lip partition repair · 2026-11-24


Starting checkout `9dd196504864c7fdb310f09eb97c4ed0a902a917`; the handoff was modified and the
two partition briefs were untracked. The operator's existing port 8765 served API build
`226c0897c1c8a25b`, release `f17b356730d6`. It was not stopped or modified. The final isolated
browser run used API build `31b50f8034fdd144`, frontend release `079e1658446f`
(`index-DOyChL5d.js`) from the uncommitted repaired checkout, on port 18890 and test data.
The source drawing was read through the normal native importer into a disposable model.
No solver was launched.

| Acceptance gate | Evidence |
|---|---|
| Spline lip geometry | PASS for the reviewed drawing and manufactured imported fit-point fixture. Exact `(27,6) → (27,9)` gives curve-sampled areas **2.432069824 + 95.823644768 mm²**; original **98.255707937 mm²**. Each spline interval was sampled at 101 points after serialize/reload; worst deviation **1.52e-14 mm**. The seven audited guides produce valid, valid, valid, one-region, valid, valid, no-hit respectively. |
| Centered and mixed topology | PASS in domain/API regressions: centered straight degree-one spline wall gives **42 + 42 mm²**, offset gives **41.994 + 42.006 mm²**. A cap plus a one-wall guide is `mixed`, flags guide 2, and preview and rejected commit create no revision. Viewport recovery removes the flagged guide or adds the opposite wall. |
| Viewport Apply/reopen | PASS on the reviewed native drawing: actual Edge clicks after pan/zoom `(26.98332,5.98200) → (26.99572,8.99644)` produced HTTP 200 `valid`, one projected seam `(26.98609,6.65484) → (26.99378,8.52396)` and display areas **95.883727 + 2.434599 mm²**. Apply saved the previewed child IDs; both faces were subsequently clicked independently after reopen. |
| Two-material mesh/deck | PASS: pointer-cut mesh **1319 nodes**, **1179 elements** including rigid panel elements, with **974 + 55** seal elements and **7** common interface nodes. Twelve interface element sides are absent from `SEAL_EXTERIOR`. Sections were `REGION_1/MAT_1` and `REGION_2/MAT_2`. With a 0.02 mm inset of the sampled cavity, seal-element intersection area was below 1e-8 mm² per element; maximum FE boundary deviation was **0.0197401 mm**. Fresh mounting nodes were resolved and saved before deck preparation. |

Baseline reproduction on the unedited checkout: the native imported outer open fit-point spline
and closed non-periodic fit-point cavity were retained; native and manufactured lip previews raised
`unsupported_curve`. The exact centered box returned `one_region` and only its right interval,
whereas y=0.001 returned `valid`. Cap plus one wall returned `valid` with one seam used by zero
children. Three retained regressions failed before the production edits. The earlier real browser
HTTP 422 is documented in [the audit](hollow-seal-partition-audit.md).

Area comparisons above use 10,000 straight segments per canonical spline interval; the exact-coordinate
comparison tolerance is 0.0001 mm². For the actual rounded-pointer cut, the same method gives
**2.450884458 + 95.804830129 mm²**, within 0.03 mm² per region of the exact-coordinate reference.
Preview uses coarser display tessellation and is not the curve-area measurement. Exact-coordinate mesh:
1274 nodes, 985 seal elements, five shared seam nodes, maximum boundary deviation 0.0197401 mm.
Both exact and pointer meshes were checked against the inset cavity.

Splitting reuses the canonical evaluated spline, preserving poles, weights and knots in the children.
Interior knot multiplicities are completed before splitting; periodic and unclamped splines remain
unsupported. Spline/line intersections use the polynomial for each homogeneous Bézier span, including
knot and sample-boundary crossings. A guide tangent to the cavity is rejected as `tangent_cut`
rather than reported as an invalid child contour. Every seam must appear with opposing senses on two distinct
children; otherwise its guide remains editable and Apply is disabled.

Verification: targeted Python **48 passed**; full Python **304 passed, 1 skipped** (opt-in Abaqus
Python). Translation **863 keys**, encoding **44 files**, typecheck and frontend build passed.
Targeted viewport suites with the opt-in native drawing **8 passed**, including a manufactured DXF
lip, a spline-wall through-guide and mixed-draft recovery in both languages. The final full-browser
run before the final tangent-only geometry follow-up had **114 passed, 4 skipped, 2 failed**: the material-comparison case failed while looking for
the renamed duplicate, and passed in isolation; desktop Fit/reset expected camera scale `8.56747`
but received `8.67968`, and failed again in isolation. That same layout failure and values were
reproduced with the original `f17b356730d6` frontend and the current API. The full browser suite was
not rerun after the tangent follow-up and is not green; investigate the separate camera-fit failure
before broad release. No new solver, sensitivity study or
physical correlation was performed.

## A11. Left-panel setup, deck readiness, force axis and projected seal cuts · 2026-11-24

Baseline local HEAD `b8252a472a8722808e8b69f37c8adf3ae030ad4e`; remote main
`aa2964b4e1ed4640f2a4e28c8a2a74e1e7a37393`. The checkout already carried uncommitted launcher,
startup-test, handoff and guide edits; those were preserved. All writes used disposable data roots
and unused ports. The operator instance, database, drawings and retained licensed artifacts were not
modified. No new licensed solve was launched; the retained oblique run was replayed read-only from a
copy of its artifacts.

### Gate results

| Gate | Result | Evidence |
|---|---|---|
| A — remove Review/Run, left setup and action group | **PASS** | `gate-a-workflow.spec.ts`: empty model → real DXF import → roles → projected cut → two materials → mesh → fixed nodes → contact → motion → Prepare → INP inspection → Submit → Results. Both actions are owned once by the left **Analysis actions** group; no Review stage, row or header shortcut exists. `layout.spec.ts` and the Gate A layout test cover 1440×900, 1280×720, 720×450 (200%), 390×844 narrow drawer and both locales; numeric stage 7 opens Motion and 8 opens Results. |
| B — Prepare and check marks agree | **PASS** | Reproduced both reported failures before editing (below). `prepare-readiness.spec.ts` covers 100→101→100 with no durable write, a genuinely unsaved change, semantic recovery, deck.missing Prepare-enabled/Submit-disabled, +90° from below writing `PANEL_RP, 2, 2, 3`, warning-only missed path, failed readiness + Retry, and one action owner. `tests/test_readiness_actions.py` asserts the server decision. Existing fixture-concurrency, archive and compatibility tests still pass. |
| C — response axis in the actual plot | **PASS** | `force-axis.spec.ts` reads the Plotly trace and the downloaded second CSV row after switching door/body steps, including direction readout, RP, W/t basis, Reverse Y and a `(0,1)` body axis distinct from `(0,-1)`. Retained licensed replay below reproduces the brief's numeric example exactly. |
| D — projected cuts in Components | **PASS** | `tests/test_partition.py` covers solid 50+50, hollow two-wall 42+42, one-wall draft, second-stroke 42+42, y=3 20+64, concave U 9+9+58, crossing 4×25, duplicates, no-hit/mixed, stale base, shared interface and deck/mesh conformity. `partition.spec.ts` and `gate-e.spec.ts` drive the real Edge viewport at DPR 1 and DPR 2 after pan **and** zoom, assign two materials, regenerate the mesh and inspect child elsets and `*Solid Section`. `hollow-cut-incomplete.png` and `hollow-cut-valid.png` show the one-region draft and the two-region commit. |

### Reproduced before editing

| Reported failure | Reproduction | After |
|---|---|---|
| Reporting width 100→101→100 left Prepare disabled as “Unsaved changes” | Real Edge session on an isolated prepared model: after returning to 100 mm the button stayed disabled and the browser issued no durable write | Prepare is enabled again from semantic persisted-value equality; no Save and no write. `prepare-readiness.spec.ts` asserts the same values and zero non-display writes |
| A valid +Y motion from below the seal was rejected by a signed-travel predicate | Synthetic door at y = −2 mm, stroke 3 mm, θ = +90°; readiness said `ready` but the UI disabled Prepare with “Set a negative prescribed Y travel…” | The v4 rule validates stroke/angle/duration on both sides; the deck writes `PANEL_RP, 2, 2, 3` and the rerun prepare action succeeds |

### Delivered behaviour

- The workflow is Import → Components → Materials → Mesh → Mounting → Contact → Motion → Results.
  Stages are stored by stable ID; legacy numeric 7 decodes to Motion and 8 to Results. The old Review
  stage body and duplicate summaries are gone; thickness is a read-only solver fact in Motion.
- Prepare and Submit are one compact group beneath the two-column left workflow. The group carries the
  prepared/stale state, deck inspection/download, run name, CPUs, launcher state and active run. Save
  revision remains in the header. The viewport stays white and stationary while panes scroll.
- Readiness is action-specific on the server (`can_prepare`, `can_submit`, `setup_issues`,
  `submit_issues`, per-action findings and `stage_states`) and is reused by the sidebar, the action
  group and the API. A missing/stale deck blocks Submit only. Root causes are reported with owning
  stage, artifact, revision/mesh identity, a localized reason and a target.
- Components owns region selection, roles and projected partitions. Selecting a region highlights it
  and does not route away. The partition tool draws arbitrary two-click guides in the viewport,
  supports multiple pending guides, undo/cancel/precision entry, a one-region draft, a visible no-hit,
  and an accessible two-click alternative. Preview and commit share the saved base and seed, so the
  previewed child IDs are the persisted child IDs.
- The partition engine projects each guide's supporting line onto canonical analytic boundaries,
  selects only the material intervals the finite stroke touches, nodes seam-seam crossings, builds the
  planar arrangement, and maps cells back to analytic line/arc/spline edges. It preserves neighbouring
  bonded loops, assigns cavities to the correct child, excludes the internal seam from exterior
  contact, and validates area, closure and disjointness.
- RunView's direction readout follows the selected step instead of always reading the closing block,
  shows role/RP/direction/angle/force basis, labels legacy provenance as unknown, marks Reverse Y as a
  display-only inversion and preserves missing force as a gap rather than JavaScript `-null → -0`.

### Verification actually run

- `.\.venv\Scripts\python.exe -m pytest -q --junitxml=pytest-results.xml`: **296 passed, 1 skipped**
  (the opt-in Abaqus-Python extractor roundtrip), exit 0.
- `npm --prefix apps/web run test:i18n`: **862 keys** in both dictionaries.
- `npm --prefix apps/web run test:encoding`: **44** source files, no known mojibake.
- `npm --prefix apps/web run typecheck`: pass.
- `npm --prefix apps/web run build`: release **`f17b356730d6`**, entry `index-4Io9K-QL.js`, API 3.
- `npm --prefix apps/web run test:browser`: **113 passed, 3 skipped** (two opt-in retained replays and
  the gated screenshot capture) on the final release.
- `scripts/schema.py`: regenerated once; a second run was byte-identical
  (`C317BA95362BCACFA32BD4EDE1C4F64041DF67977E7A39EC788B1E7CBD845721`).
- `git diff --check`: clean.

### Evidence

- `.local/evidence/action-group-left.png`: left workflow plus the full Prepare/Input-ready/Submit group.
- `.local/evidence/hollow-cut-incomplete.png`: one radial cut, **One material region remains**, Apply
  disabled, 54.558 mm².
- `.local/evidence/hollow-cut-valid.png`: second cut, **Cut preview ready**, 1.849 + 52.711 mm², Apply
  enabled.
- `.local/evidence/axis-replay.json` and `axis-replay-{closing,bodyseating}.png`: retained licensed run
  `76b20d84-dc96-4d24-8059-85ed8a3942ad` replayed through the built UI. Closing used d = (0.6, −0.8),
  final RF = (0.0130300671, −0.0774725974) N, dot = 0.0697961181 N, displayed total force
  **6.979611814 N** at W/t = 100; Body seating used d = (0,1) and 21 samples. All 31 + 21 Plotly Y
  values matched independent arithmetic (max absolute difference 0); the exported force row matched
  the trace to 4.7×10⁻¹² (closing) and 2.2×10⁻⁷ (body). This is retained replay, not a new solve.
- Deck and mesh inspection is asserted in `partition.spec.ts` (three `*Solid Section`, child REGION
  elsets, shared interface nodes, internal seam absent from `SEAL_EXTERIOR`) and in the Gate A journey
  (4-region exported INP with `PANEL_RP, 2, 2, -6.5`).

### Known gaps after this delivery

1. No new licensed solve was run. The force-axis evidence is a replay of retained licensed artifacts; it
   establishes the viewer relationship for that run, not physical correlation.
2. Physical correlation, numerical sensitivity and self-contact participation remain **BLOCKED**.
3. Partition targeting is one material region per operation (the API rejects multi-face scope). Multiple
   guides and two-or-more children on that region are supported.
4. Hosted Windows CI was not run for this working tree.

## A10. Second UI and 2D engineering pass · 2026-11-24

Baseline `aa2964b4e1ed4640f2a4e28c8a2a74e1e7a37393`, equal to `origin/main`; the working tree held only
the execution brief, the visual reference and the handoff entry before work. All tests used isolated
`--test-data` data and disposable synthetic projects. The operator instance, database, drawings and
retained licensed artifacts were not modified. Licensed verification used three disposable synthetic
cases and the installed Abaqus 2024 launcher; it is recorded separately in
[engineering-validation.md](engineering-validation.md).

### Request status (16 rows)

| # | Request | Change | Test / evidence | Outcome |
|---|---|---|---|---|
| 1 | Usable app width | Removed the 1950 px page cap and left alignment; full-width scrollers with 16–32 px symmetric gutters | `apps/web/tests/gate-a.spec.ts` at 2560/2547/1920/1440/1280/390 px; keyboard inline model flow | **PASS** |
| 2 | Remove public-example checkbox | Both Dashboard create flows start empty; synthetic seeds only through the test API | `gate-a.spec.ts` create-flow test; `workflow.spec.ts`; `i18n.spec.ts` | **PASS** |
| 3 | Normalize world geometry to mm | Full DXF/DWG unit enumeration (incl. US survey), one recorded conversion, range/metadata checks, no repeat scaling | `tests/test_units.py` (14), paired mm/inch/cm/m/survey fixtures; `import-units.spec.ts` | **PASS** (software) |
| 4 | Remove overlapping viewport caption; three glyphs only | Caption deleted, retained offsets read-only in Motion, 44×44 icon buttons, focus ring | `gate-a.spec.ts` tools test; `renderer.spec.ts`; screenshots | **PASS** |
| 5 | Independent contact coefficients | Door/body/self μ fields (default 0.7), named assembly surface pairs and three property assignments in both decks; legacy scalar preserved exactly | `tests/test_phase_two_domain.py`; `tests/test_two_step.py`; licensed oblique run with 0.17/0.43/0.81 | **PASS** (software + deck); self-contact participation **BLOCKED** |
| 6 | Derive steps from roles | Server and browser derive one/two steps from participating roles; duplicate roles reported, never silently dropped; legacy modes retained | `tests/test_phase_two_domain.py`; `two-step.spec.ts`; `readiness` tests | **PASS** (software) |
| 7 | Brand and visual identity | Local vector hollow-seal mark + text wordmark, ink/cobalt/jade/tangerine tokens, tangerine active nav | before/after screenshots; `gate-a.spec.ts`; contrast table in `tokens.css` | **PASS** |
| 8 | Oblique in-plane motion | Nonnegative stroke + angle; Δ=(L cosθ, L sinθ) used by deck, assessment, metadata, extraction; both U1/U2 written and held | `test_phase_two_domain.py`; licensed oblique case measured U=(3,−4); `two-step.spec.ts` | **PASS** (software + licensed); numerical warnings recorded |
| 9 | Prepare/submit inside Properties | Actions are the first group of the Review properties pane; grid dock removed; pane scrolls to top on stage change | `layout.spec.ts`, `contact-motion-actions.spec.ts`, screenshots | **PASS** |
| 10 | Reporting width W | W=100 mm default separate from t=1 mm; (RF·d)·W/t and per-mm bases; W never enters the deck; legacy basis recorded | `test_phase_two_domain.py` golden identities; licensed 0.012273→1.2273 N; `curve.spec.ts` basis label | **PASS** |
| 11 | Interactive section cut | Face boundary click acquisition, canonical snap, rubber band, back/Esc, one Apply, second cut, curved arc | `gate-e.spec.ts` (DPR 2, Escape, invalid, curved), `partition.spec.ts` (DPR 1 + pan/zoom); licensed bonded partition | **PASS** |
| 12 | Remove Review “Go to Mesh” | All three shortcuts removed; explanations and the Mesh stage remain | `layout.spec.ts`, `contact-motion-actions.spec.ts` assert zero buttons | **PASS** |
| 13 | Motion preview | Per-panel preview along the vector and back, stop/reduced-motion, no writes/camera change, hold disabled | `motion-preview.spec.ts` | **PASS** |
| 14 | Larger readable type | 16 px body, ≥15 px workspace labels, larger metadata/controls/plots; 100% and 200% zoom | `gate-a.spec.ts`; screenshots at 1440 and 390 | **PASS** |
| 15 | Two-row spreadsheet CSV | Exactly two numeric rows (magnitude, projected force), no header/time/index, holes vs measured zero | `curve.spec.ts` download bytes; `gate-d.spec.ts` missing/zero cells; `test_phase_two_domain.py` identities | **PASS** |
| 16 | Stable playback and default edges | Fixed status track, bounded read-ahead, monotonic deadlines; mesh edges on by default | `gate-f.spec.ts` measured 62 transitions; `playback.spec.ts`; `ranges.spec.ts` | **PASS** |

### Gates

| Gate | Result | Evidence |
|---|---|---|
| A Layout / brand / actions | **PASS** | 10 Gate A assertions incl. 2560 px, 200% zoom, three 44 px tools, empty create flows, keyboard inline flow and focus checks |
| B Units / role-derived steps | **PASS** (software) | Paired mm–inch–cm–m–survey fixtures, bulged arc, spline, missing/unitless/unknown/overflow; role one→two→one tests |
| C Contact / oblique / preview | **PASS** software + licensed oblique; self-contact participation **BLOCKED** | Distinct μ in INP and metadata; U=(3,−4); preview endpoint/restore |
| D Width / force / two-row curve | **PASS** | Browser download bytes incl. missing component/force and measured zero; (−3,4)→−500 N, per-mm 5 N/mm, legacy t=2→500 N |
| E Interactive cut | **PASS** | Real WebGL clicks, DPR 1/2, panic/cancel with zero writes, curved arc; licensed bonded partition |
| F Playback | **PASS** | Retained `.local/gate-f-measurements.json`: median 243.1 ms, p95 absolute error 30.1 ms, worst 266.6 ms, 31 frames/62 transitions; host 917.95×378 and slider 833.95 px stable; camera constant |
| G Release / engineering | **PASS locally; hosted CI and physical correlation not run** | Full suites, schema regeneration stable, build `6a8527d475c5`; licensed runs recorded separately |

### Verification actually run

- `.\.venv\Scripts\python.exe -m pytest -q --junitxml=.local/phase2-final-pytest.xml`: **279 passed, 1 skipped** (the opt-in Abaqus-Python extractor roundtrip), exit 0.
- `npm --prefix apps/web run test:i18n`: **806 keys** in both dictionaries.
- `npm --prefix apps/web run test:encoding`: 43 source files, no known mojibake.
- `npm --prefix apps/web run typecheck`: pass.
- `npm --prefix apps/web run build`: release **`6a8527d475c5`**, entry `index-CfGm1X5y.js`, API 3, 3 files.
- `npm --prefix apps/web run test:browser`: **103 passed, 3 skipped** (the 3 skips are the two opt-in retained-result replays and the gated screenshot capture).
- `git diff --check`: clean. `scripts/schema.py` regenerated `generated.ts`; a second run was byte-identical (`0FF8684B…`).

### Evidence

- Before/after captures at 2560×1440, 1440×900 and 390×844 in both locales, plus Review and Results at 1440, are under `.local/screenshots/before/` and `.local/screenshots/after/` (local, ignored). "Before" was captured from an isolated worktree of `aa2964b` serving release `07b80dd311ac`; "after" from the final release `6a8527d475c5`.
- Playback measurements: `.local/gate-f-measurements.json`.
- Two-row sample export: `.local/evidence/sample-two-row-curve.csv` (2 rows × 31 samples, magnitude 0→10 mm,
  projected total force 0→4001.6 N at W = 100). It is **manufactured test evidence** from the isolated
  launcher double, not a licensed solve, and is labelled as such here.
- Section-cut interaction: `.local/screenshots/after/partition-cut-hover-1440-en.png` (rubber band and A/B
  handles) and `partition-cut-preview-1440-en.png` (children and shared edge; areas 28.803/28.797 mm²).
- Licensed records and artifact paths: [engineering-validation.md](engineering-validation.md). The licensed files are under `.local/phase2-licensed/` and are not committed.

### Known gaps after this delivery

1. Licensed self-contact participation was not demonstrated; no pressure/slip evidence exists for the seal↔seal pair.
2. All three licensed runs completed but emitted repeated contact penetration/cut-back warnings; numerical sensitivity and physical correlation remain **BLOCKED**.
3. Pan/zoom acquisition at DPR 2 was not reproduced in the automated Gate E test (DPR 2 default camera and DPR 1 pan/zoom are covered separately); one development run showed a projection mismatch after pan+zoom at DPR 2 that was not reproduced after simplifying the test.
4. The Gate D hole/zero test modifies only the results-index transport for the browser test; it is UI evidence, not a solver artifact.
5. Hosted Windows CI was not run for this working tree.

## A8. UI redesign, direct deletion and seal partitioning · 2026-11-23

Baseline `6ace5475ba9f76b21cd2cc915a4c195f6d87fa9b`, matching `origin/main`. Work continued in the
normal checkout with isolated browser data directories and ports; no operator database, active job or
retained solver artifact was modified, and no licensed solver was launched.

### Delivered behaviour

| Area | Change |
|---|---|
| Shell | Fixed engineering workstation: dark navigation, model/revision header, workflow plus properties side by side on the left, white drawing field on the right. Desktop fits the client area at 1440×900 and 1280×720 (no document scroll); panes scroll independently. Review's prepare-then-submit dock is anchored to the upper-right of the work area. Narrow and 200%-zoom layouts stack in the page flow and can collapse the workflow/properties panes. |
| Empty viewport | The centred DXF/DWG call to action was removed. Import owns the file picker and its guidance; the drawing field stays white, with WebGL and import errors still visible. |
| Results geometry | Displayed point coordinates now depend only on instance-qualified base coordinates, that frame's measured nodal U, the deformation toggle and scale. Scalar availability controls colour alone. The y = 4 → y = 2 rigid-panel reproducer moves in Mises and U views; missing U stays at the base position; true zero stress and absent stress are distinguished. |
| Ranges | Displacement (0–5 mm) and stress (0–0.5 MPa) keep independent Fixed/Auto/Manual state with editable minimum/maximum and units. Invalid, blank, non-finite or inverted drafts are rejected locally while the last valid render stays; clipping cues cover both ends; probes and CSV stay unclipped. |
| Palette | One saturated blue–cyan–green–yellow–red ramp (#1745E6, #00B9F2, #08B84F, #FFD400, #E32621) is shared by VTK scalar colours, actor updates and the legend. Material colours and chart axes remain independent. |
| Playback | Loop defaults on; playback holds the final displayed frame for one cadence and wraps to the first frame. Loop off stops on the final frame. Pause, scrub, camera and run-wide scale are preserved; slow and failed frames keep the last valid scene. |
| Terminology | Japanese uses ボデーパネル / ドアパネル and English Body panel / Door panel for the engineering roles, including readiness, motion, mesh, assembly diagnostics, results, curve steps and both guides. Engineering identifiers, CAD/FE IDs, step names and historical metadata are unchanged. The assembly tree shows the translated role beside the alias-first label. |
| Deletion | Permanent deletion is available directly from ordinary model and group listings. One accessible dialog shows the target, type, child-model/revision/job counts, removed artifact scope and blockers; exact-name typing enables the destructive action, and Cancel/Escape restores focus. A changed impact is re-presented for confirmation. The archive prerequisite was removed from preflight and execution. |
| Deletion safety | The final activity decision, affected-ID enumeration and row deletes now run inside one `BEGIN IMMEDIATE` transaction, with the journal committed atomically with the deletes. A competing enqueue either joins before the decision (and blocks deletion) or loses and receives a not-found/conflict; a competing model creation cannot orphan a deleted group. |
| Partition | New `packages/engineering/partition.py` implements a deterministic straight two-point cut on one material-bearing seal face. It snaps to the canonical boundary within 0.05 mm, splits canonical edges exactly (line, arc, clamped control-point spline), rewrites every incident signed loop including reverse use, preserves cavities, rewrites selections/local sizing, validates area/union/disjointness, and returns localized reason codes. Preview and commit share the same operation; the commit is its own transactional endpoint with base-revision checking and content-idempotent retry. Children keep stable CAD IDs and inherit the parent material. |

### Gate status

| Gate | Result | Evidence |
|---|---|---|
| 0 · Trustworthy CI baseline | PASS | Clean worktree reproduced the empty-frontend health failure; the test now provisions an isolated release fixture and separately covers the supported missing-build state. |
| 1 · Desktop/narrow/zoom shell | PASS | `apps/web/tests/layout.spec.ts`: document/client size, pane adjacency, fixed canvas through property scrolling, Review dock bounds, resize, narrow collapse, 200% width, white canvas, empty-viewport picker count and import isolation. |
| 2 · Terminology | PASS | Both dictionaries audited; role labels changed without touching identifiers. Browser locale, alias and asset tests plus translation/encoding gates. |
| 3a · Result geometry | PASS | `apps/web/tests/scene-model.spec.ts`: y=4→y=2 edge and markers in Mises/U, deformation off and scales 1/2, missing U, measured zero vs absent stress, instance-qualified picking, palette values. |
| 3b · Ranges and playback | PASS | `apps/web/tests/ranges.spec.ts` plus existing playback/curve/result-field coverage: independent defaults, Auto, manual clamping both ends, invalid drafts, unclipped signed probe, reset, loop wraps, Loop off, slow frame across the boundary, camera/scale stability. |
| 4 · Direct deletion | PASS | `tests/test_archive_delete.py` (direct model/group, revised scope, enqueue race, membership change, recovery) and `apps/web/tests/archive.spec.ts` (dialog focus/cancel/Escape/wrong name, direct model and mixed group). |
| 5a · Partition domain/API | PASS | `tests/test_partition.py`: area/union/disjointness, child-of-child, deterministic IDs, reverse shared interface, hole-preserving arc cut, invalid/tangent/sliver/hole-crossing rejection with no mutation, selection remap, mesh conformity, door-only and two-step deck sections/seam, preview/apply/retry/stale base/generic PUT guard. |
| 5b · Partition browser/worker/deck | PASS | `apps/web/tests/partition.spec.ts`: pan/zoom, preview, cancel, apply two cuts, two material cards, save/reload, worker mesh, re-reviewed fixture, prepared INP, shared interface nodes, pre-cut revision digest/deck replay, sibling untouched. |
| 6 · Regression/evidence | PASS (software) · physical correlation BLOCKED | Full suite counts below. No licensed partition run; no retained ODB replay or independent reference. |

### Verification runs and known gaps

Recorded in [agent.md](../agent.md). The partition has **no licensed execution, extraction or ODB
agreement**; the launcher double is manufactured evidence. Physical correlation remains blocked on an
independent reference and agreed tolerance. Straight cuts are the supported delivery; other curve
variants are rejected rather than approximated, and FE-node fixtures are not transferred across the
topology change.

## Usability and CI repair · 2026-11-23

New schema-v3 projects use −10 mm prescribed door travel; older omitted
travel retains −5.5 mm. Contact completion compares saved and draft contact
rather than unrelated edits. Review actions are separated and friction guidance
is localized. CI uses its repository venv, requires a complete pytest report,
and startup releases its owner after failed initialization. Independent solver
and physical validation of the new default has not been performed. Isolated
tests and remaining limitations are recorded in [agent.md](../agent.md).
Hosted CI has not yet run for these uncommitted changes.

Date: 2026-11-21
Baseline commit: `b250789` (branch `main`, clean working tree; only the supplied
`apps/web/assets/logo.png` was untracked)
Repository: `stefanoKS/Abaqus_QualityOfLife`
Environment: Windows, Python 3.11.9 (`.venv`), Node.js 24.16.0, npm 11.13.0, Edge with WebGL,
Abaqus/Standard 2024 installed at `C:\SIMULIA\Commands\abq2024.bat`.

## A7. Milestone delivery — import units, defaults, zero-travel holds, stress viewer, licensed two-panel runs

Date: 2026-11-23. Baseline: `5104b99`, clean tree. Isolated data roots and ports; the live instance
(8765) and its data/artifacts were not restarted or modified. Two authorized small synthetic
Abaqus/Standard 2024 two-panel cases were executed (one CPU); their ODBs were inspected read-only.

### Delivered behaviour

| Area | Change |
|---|---|
| Import | Removed the "Drawing coordinates are in mm" checkbox in both languages. Import enables immediately and the first click opens the picker. A drawing's own header decides: declared mm imports directly; unitless is interpreted as project mm and recorded as `unitless drawing interpreted as mm`; a missing header is recorded separately; another declared unit is rejected by name. `Source.unit_basis` persists the decision. |
| Defaults | New models use a 0.5 mm global mesh and a 1.0 s new step. `schema_version` 2 marks the new defaults; version-1 payloads with omitted defaulted fields still read as 1.0 mm / 1.3 s, and explicit values are never rewritten. |
| Zero travel | `travel = 0` is a valid hold for the door and body, including door-only. Two-step decks write explicit zero BCs (never an epsilon), keep both steps, references and contact continuity. The UI explains the hold; readiness no longer rejects it. |
| Placement | The initial Y offset is applied before the assembled side and clearance are decided. Above/below/actual intersection/ambiguous side/no X overlap are distinct. The legacy door-only 1.80 mm gap is unchanged. |
| Results | Stress opens by default with von Mises, element probing, cell colouring by maximum integration-point Mises, a fixed 0.00–0.50 MPa blue→red scale, saturation marking, run-wide/editable ranges with inline validation, independent mesh-edge and node-marker toggles, a 1× deformation scale, and a solid white canvas with no grid. Displacement opens on node probing and also supports element inspection. |
| Element policy | Mesh shows an enforced, non-editable "Reduced integration for rubber quadrilaterals" setting, plain-language CPS4R/CPS3/R2D2 explanations and real per-region/component counts. The deck writer rejects a rubber quadrilateral written as CPS4. |
| Integrity | Canonical step identity ignores case and whitespace (Abaqus stores `Body seating` as `Bodyseating`), shared by frames, histories, plot selection and CSV. Missing raw components stay null/empty rather than zero. |
| Licensed evidence | Two-panel moving-body and held-body cases completed with extraction success; both RPs were read directly from both ODB steps; Mises and CSV values agree with the ODB. |

### Gate status

| Gate | Status | Evidence |
|---|---|---|
| A. Import and model isolation | PASS | `tests/test_units.py`, browser `import-units.spec.ts`, `isolation.spec.ts`; native DWG reader path covered by `tests/test_dwg.py` on this machine |
| B. Defaults and element policy | PASS | defaults, CPS4R policy, compressible neo-Hookean C10/D1 (schema, library versions, bilingual editor, deck, licensed run) |
| C. Zero travel and validation recovery | PASS | Python four-combination deck tests; browser `zero-travel.spec.ts` |
| D. Placement and artifact integrity | PASS | offset/intersection/ambiguous/no-overlap; missing/corrupt active mesh is a named readiness blocker, deck preparation agrees, historical decks stay readable |
| E. Numerical field correctness | PASS | Mises zero/uniaxial/shear, missing vs measured zero, canonical steps, and duplicate element labels across instances (`result-fields.spec.ts`) |
| F. Actual Results browser behaviour | PASS | `results-retained.spec.ts` on retained licensed `39f696ee…` (white canvas, Mises, limits, saturation, probe value vs frame, toggles, deformation, step selection) |
| G. Licensed two-panel acceptance | PASS (execution, extraction and viewer agreement) | runs `eca0c88e…`, `89fab9df…` and neo-Hookean `a8f47acc…`; direct ODB RP inspection; extractor Mises equals the ODB; two-step replay `62ce070f…`; see the validation record |
| H. Regression and handoff | PASS | full suite counts and build identity recorded in [agent.md](../agent.md) |

### Files changed

`packages/engineering/model.py`, `geometry.py`, `units.py` (new), `dxf.py`, `dwg.py`,
`__init__.py`; `integrations/abaqus/deck.py`, `results.py`, `interchange.py`, `extract_odb.py`;
`services/api/main.py`, `contracts.py`, `readiness.py`, `store.py`, `material_library.py`;
`apps/web/src/Workspace.tsx`, `MaterialsPage.tsx`,
`RunView.tsx`, `Viewport.tsx`, `viewportModel.ts`, `viewportRenderer.ts`, `style.css`,
`viewport.css`, `features/mesh/meshQuality.ts`, `features/mesh/MeshReview.tsx`,
`features/run/fields.ts` (new), `features/materials/MaterialEditor.tsx`,
`features/workspace/AssemblyDiagnostics.tsx`, `features/workspace/readiness.ts`,
`features/workspace/workflowStates.ts`, `i18n/en.ts`, `i18n/ja.ts`, `generated.ts`;
`tests/test_defaults.py` (new), `test_units.py` (new), `test_results_fields.py` (new),
`test_two_step.py`, `test_abaqus.py`, `test_geometry.py`, `test_release_and_compatibility.py`,
`test_material_library.py`;
`apps/web/tests/import-units.spec.ts` (new), `zero-travel.spec.ts` (new),
`offset-picking.spec.ts` (new), `two-step-results.spec.ts` (opt-in, new),
`result-fields.spec.ts` (new), `assembly.spec.ts`, `materials.spec.ts`,
`results-retained.spec.ts` (opt-in, new), `playback.spec.ts`,
`numeric-guard.spec.ts`, `isolation.spec.ts`, `workflow.spec.ts`; docs.

### Known gaps carried forward

- Solver divergence/zero-force warnings on the licensed cases need engineering review; physical
  correlation remains blocked (no independent reference or agreed tolerance).
- Convergence and rate sensitivity are not studied.
- Per-pair friction, oblique motion and partitions remain outside this delivery.

Added after the first pass: the compressible neo-Hookean solid-rubber card (C10/D1) with versioned
library persistence, bilingual editing and a licensed 2024 run (`a8f47acc…`); named readiness
recovery for a missing/corrupt active mesh with deck refusal and readable history; a real Edge/WebGL
offset-picking test through zoom and pan; a two-step licensed-result replay; and instance-qualified
duplicate-label result tests. See the validation record.

## A6. Repair delivery — bottom-mounted body placement, contact orientation, motion projection

Date: 2026-11-22. Baseline: `f1cb37b`, clean working tree. No licensed solver was launched, no
license was consumed, no retained ODB/INP/mesh/history was modified, and the live instance was not
restarted.

### Reported defect

A legitimate two-panel assembly with the door above the seal and the body **below** it was rejected
at deck preparation with "The panel starts below the seal exterior". `vertical_gap()` assumed every
rigid profile lies above the seal; `write_two_step_inp()` reused that assumption for the body; the
result metadata hard-coded `direction = [0, -1]` for both motions; and the viewport grouped every
R2D2 element into `PANEL-1` with the door offset.

### Delivered repair

| Area | Change |
|---|---|
| Clearance | `deck.clearance_report()` classifies the contact side from the drawn profile and measures the minimum vertical separation of the actual piecewise-linear FE surfaces over their shared X range (sloped, curved and vertical segments included). The separation is positive for both mounts. Distinct `ClearanceError` codes: `initial_penetration`, `motion_away`, `no_x_overlap`, `side_ambiguous`, `unsupported_geometry`. |
| Contact normals | `deck.orient_for_contact()` reverses a below-mounted profile's R2D2 connectivity so its SPOS side faces the seal; the door above keeps the legacy right-to-left order. Each part keeps its own `PROFILE` elset, connectivity and reference node. |
| Motion metadata | `deck.motion_assessment()` records each profile's side, direction, offset, clearance and gap reach. `results._metadata()` derives the door (`[0,-1]` above) and body (`[0,+1]` below) directions separately. `interchange.align_histories()` projects onto the step's own direction; raw `U1/U2/RF1/RF2` are untouched. `extract_odb._history()` matches step names case-insensitively and refuses to project an unknown step onto the door reference. |
| Viewport | `makeScene()` groups mesh elements by assembled instance (`WS-1`, `PANEL-1`, `BODY-1`), applies each profile's own offset, and keeps instance-qualified picking identity. A DOM caption previews the assembled offsets. |
| Diagnostics | Readiness returns a geometric `assembly` block before a deck exists. Motion and Review show door/body clearance, side, offset, travel, direction and gap reach, with an explicit "travel past the gap does not guarantee contact" caveat. Penetration, wrong-sign travel and missing X overlap become localized readiness blockers (ja/en). |

### Gate status

| Gate | Result | Evidence |
|---|---|---|
| 1 · Geometric clearance | PASS | `tests/test_two_step.py` scenarios A–I |
| 2 · Rigid contact normals | PASS | scenario J, normals recomputed from written connectivity |
| 3 · INP and step boundaries | PASS | user-scenario test: parts, instances, RPs, both steps, BCs, initial placements |
| 4 · Result projection | PASS | scenario L and per-motion metadata assertions |
| 5 · Viewport and Edge regression | PASS | `apps/web/tests/assembly.spec.ts`, `renderer.spec.ts`, full Playwright suite |
| 6 · Existing suites | PASS | 200 Python passed + 1 opt-in skip; 61 Playwright passed; i18n 648 keys; encoding, typecheck, build pass |
| 7 · Licensed two-step validation | **BLOCKED** | no authorized licensed run; no solver physics claimed |

### Supported geometry limitations

- The door closes from above the seal (negative travel by schema); a bottom-mounted profile uses the
  moving-body role, whose travel sign is free.
- Motion is a single vertical translation along Y. Oblique X/Y motion, a profile that straddles the
  seal at the assembled position, and an ambiguous contact side are rejected explicitly.
- Clearance is measured along Y over the shared X range, not as a minimum normal distance to an
  arbitrary surface.
- More than two moving rigid profiles and simultaneous motion are not supported.

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

## A14. Six file-workbench gates — 2026-11-24

Baseline `84ab7a2` plus the uncommitted A–E delivery, preserved. Isolated
`SEAL_DATA`, temporary folders and the isolated browser service only; the
operator instance and retained artifacts were untouched. **No licensed solver
was launched.** Abaqus/CAE 2024 noGUI was used once for material-card
verification (a CAE license token was consumed).

### Gate results

| Gate | Result | Evidence |
|---|---|---|
| 0. Two-tab Save Retry | **PASS** | `apps/web/src/features/workspace/merge.ts` reconciles `base → head` with the local delta. Two-tab browser test: A saves width 111 mm, B changes only mesh size, Retry commits `reporting_width=111` **and** `mesh.size=1.25`. Same-field edits report `analysis.reporting_width` and offer Reload; nothing is overwritten. |
| 1. Live progress | **PASS** | `ProgressSummary` gained a visible current-step line and a named, focusable `progress-detail` scroll region; `.run-view .run-progress` is `flex: 0 0 auto` with a bounded height. Tests assert `scrollHeight <= clientHeight` and child bounds at 1874×762, 1440×900, 1280×720 and 390×844 in JA/EN, plus keyboard scrolling at 1280×520. |
| 2. Completed result space | **PASS** | The large card is replaced by a completion line in the existing banner. At 1280×720 the result grid is **458 px** (was 355) and the viewport **324 px** (was 302); playback is fully visible and the display controls are reachable by scrolling the field card. 46vh is the fixed shell's maximum because playback must remain inside the grid. Diagnostics keeps the full card. |
| 3. Spline import | **PASS (software)** | Open-only drawings become inspectable models with zero faces and `drawing.no_closed_region`. The 1e-6 mm endpoint join reports `snapped`, `maxGap`, `nearestGap`; gaps outside tolerance are never bridged. The two documented passing drawings still contain two splines and one face through upload → worker. |
| 4. Material library | **PARTIAL** | Data-only `.lib` reader (no pickle execution), 27 cards, Japanese decoded; 2 exact mappings (PA6, METAL), 25 explicit ineligibility reasons. Import/export with fingerprints and provenance. **CAE 2024 created all 27 cards from the parsed data and reproduced PA6/METAL numbers.** Metal regions emit CPS4, polymer regions CPS4R, with per-region ELSETs/sections in the INP. Legacy unregistered demo cards are still accepted with a warning; the CAE GUI Manager file-open was not automated. |
| 5. One vertical workflow | **PASS** | `AnalysisActions` moved from the left tree to the top of the Results properties once. Eight stages keep DOM/visual/keyboard order in JA/EN and at short/zoomed sizes; Results opens before any artifact; Submit-only CPU/name reasons are local; no duplicate run controls. |
| 6. Portable files | **PARTIAL** | `.aqmodel` New/Save/Save As with fingerprint conflict, atomic publish and fresh-install reopen. `.aqresult` published by the worker with no browser, collision-safe distinct names, read-only reopen. Truncated/wrong-kind/unsupported-version refused; failed extraction refuses publication. The Dashboard still shows project history. |

### Measured layout

| Measurement | Before | After |
|---|---|---|
| Progress card, 1280×720 | 124 px visible for 276 px content (audit) | card fits its content; detail scrolls only when the window is shorter |
| Result grid, 1280×720 | 355 px | **458.2 px** |
| Result viewport, 1280×720 | 302 px | **324 px** |

### Material coverage ledger (supplied library, SHA-256 `7ab001b6…`)

| Stage | Count |
|---|---|
| Records in file | 28 (27 materials, 1 container) |
| Parsed and shown in preview | 27 |
| Eligible for exact registration | 2 (PA6, METAL) |
| Ineligible — hyperfoam | 11 |
| Ineligible — hyperelastic | 9 |
| Ineligible — plastic | 2 |
| Ineligible — viscoelastic | 4 |
| Ineligible — Mullins | 2 |
| Ineligible — no structural law | 1 |
| CAE kernel created from parsed data | **27 of 27** |

CAE reproduction: PA6 density `1.13e-9`, elastic `[[2600, 0.39]]`,
`ISOTROPIC`; METAL density `7.65e-9`, elastic `[[206000, 0.3]]`, `ISOTROPIC`.
Export is byte-identical to the CAE-authored source (SHA-256 matches).

### Tests actually run

| Command | Result |
|---|---|
| `pytest -q` | **328 passed, 1 skipped** |
| `test:i18n` | **946 keys** both dictionaries |
| `test:encoding` | 47 files |
| `typecheck` | pass |
| `build` | release `81fc7a73aa30`, entry `index-BdawGA5k.js`, API 3 |
| `test:browser` | **160 passed, 4 skipped, 3 failed** on release `81fc7a73aa30`; the three failing tests pass in isolation (`gate-f` 2 passed alone; `materials` + `motion-preview` 7 passed together). A later 4-file run also flaked the rapid-edit coalescing test once; it passed 3/3 when repeated alone. These are suite-load timing flakes, not gate failures. |

New Python suites: `test_dwg_open_only.py` (11), `test_material_library_cae.py`
(5), `test_portable_files.py` (7). New browser suites: `run-layout.spec.ts` (5),
`auto-save.spec.ts` additions (2), `setup-workflow.spec.ts`, `file-workflow.spec.ts`.

### Honest limits

Physical correlation, numerical sensitivity, self-contact participation and any
licensed solver execution remain **BLOCKED**. The CAE GUI Material Library
Manager file-open path is not automated; card data and the exported container
are verified, not that GUI action. Registered-only material enforcement and the
full retirement of the project UI are partial.
