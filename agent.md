# Abaqus QOL implementation handoff

## Gates A–C: file ownership, Dashboard/Close and faithful CAE materials · 2026-11-25

Executed the [File ownership, material import and navigation handoff](docs/file-open-materials-navigation-handoff.md).
During the session the previously uncommitted A–E delivery was committed by the operator session as
`2f569ed`; this delivery's changes sit uncommitted on top of it and no file from that work was
discarded. All writes used disposable `SEAL_DATA`
roots, the isolated `--test-data` browser server (ports 19871–19880) and temporary folders. The
operator instance on 8765, its database, drawings and retained licensed artifacts were not
contacted, stopped or modified. **No solver was launched.** One Abaqus/CAE 2024 noGUI session was
used for the material-reference check and consumed CAE license tokens (recorded in the validation
record). The full detail and measured tables are in
[implementation-report.md](docs/implementation-report.md#a14-file-ownership-navigation-close-and-faithful-cae-material-support--2026-11-25).

Built release **`055f04911427`** (entry `index-kfFfAlip.js`, API 3). Save, Ctrl+S, Save As and Save &
Close share one path that flushes the workspace autosave first — this closes the reported 100 → 111 mm
regression. The supplied library now registers **27/27** records (was 2); **19** are ready for a new
2D run, **7** name the missing density and **1** (thermal-only) names the missing structural law. All
**11 Hyperfoam** cards emit their source law, active columns and every row.

### Gate status

| Gate | Status | Measured outcome |
|---|---|---|
| A — archived owner | **PASS** | An internal, name-independent owner (`groups.internal=1`, partial unique index) is resolved and validated in the same write transaction as the head. With the historical `Imported projects` group archived: File → New and Open Model return `archived=false, group_archived=false`, no banner, enabled Save, persisted 100 → 111 mm and a queued drawing import. Explicit creation in the archived group still 409, historical replays stay read-only, `POST /api/projects/{pid}/recover` and duplicate-from-archived create distinct editable identities. Eight concurrent creates leave 1 internal row and 8 owned models; archive/delete of the internal owner is refused by the API. |
| B — Dashboard first and Close | **PASS** | Rendered and keyboard order Dashboard → Workspace → Materials in EN/JA at 1440 and 390 px; cold start opens Dashboard; Materials returns to the tab's document. Close ends only that tab's session (sessionStorage), names the document, keeps recents and the head, and Workspace/refresh do not reopen it. With the working-head PUT held, Ctrl+S and Save & Close both left the on-disk file at **111 mm** after reopening; Cancel and a failed write keep the document and its draft; a Japanese folder and file name save correctly. |
| B — portable-open restore | **PASS** | A 37-node fixture reopens in a fresh data root with `can_prepare=true`, `mounting.reviewed=37`, no reselection and `deck.missing` as the only submit issue. Mismatched identity, truncated mesh, missing identity and foreign fixture are each reported by code and never adopted; the original drawing returns byte-identical. |
| C — CAE registration/deck | **PASS (software)** | 27/27 registered, 19 available, 7 need density, 1 needs a structural law. All 11 Hyperfoam cards (6 test-data N=1, 1 direct N=1, 2 direct N=3 + Prony, 2 direct N=5 + Prony) emit faithfully; 6 test-data cards write 2 active columns with `lateralNominalStrain=OFF` and never the zero storage column. Per-card family declaration, idempotent repeat import, same-name divergence, per-record outcomes, rejected direct submissions, CPS4/CPS4R sections and an explicit original-file export are covered. |
| C — CAE 2024 reference | **PASS (5/5 combinations)** | A CAE 2024 noGUI session imported the app-emitted keywords and re-read every behaviour and value for E13, EPTO_E110, DKSPONGEHK, E18WW and SPCC. It found and fixed two real defects: direct `*Hyperfoam` must be packed ≤8 values per line (CAE rejected one 3N-value line), and CAE 2024 rejects a `DEFINITION` parameter on `*Mullins Effect` (bare keyword is correct). This is input-keyword evidence, **not** solver or physical evidence. |
| — Solver execution / physics | **BLOCKED** (unchanged) | No licensed solve; no convergence, sensitivity or physical-correlation claim. |

### Tests actually run (this machine, isolated data)

- `.\.venv\Scripts\python.exe -m pytest -q`: **364 passed, 1 skipped** (opt-in Abaqus-Python
  roundtrip), exit 0.
- New: `tests/test_archived_owner.py` (12), `tests/test_portable_restore.py` (6),
  `tests/test_cae_materials.py` (18); updated `tests/test_material_library_cae.py` (5).
- `test:i18n` 970 keys both languages; `test:encoding` 47 files; `typecheck` pass; release
  **`055f04911427`**.
- Browser feature specs on their own servers: `archived-owner.spec.ts` (2), `file-close.spec.ts` (9),
  `cae-materials.spec.ts` (1), `isolation.spec.ts` (5), `materials.spec.ts` (7),
  `offset-picking.spec.ts` (1), `partition.spec.ts` (5), `prepare-readiness.spec.ts` (5) — all passed.
- **Full browser suite, final build `055f04911427`, port 19890: 171 passed, 4 skipped, 4 failed**
  (179 tests, 18.9 min). The four failures are the known suite-load cases, not gate regressions:
  playback cadence (71.7 ms vs ≤50 ms; reproduces alone on this machine and is unrelated to this
  pass — no playback code changed), the two `materials.spec.ts` journeys (both passed in a 7-test
  isolated run) and `offset-picking` (passed in isolation). No failure touches Gates A–C.
- `scripts/schema.py` regenerated `generated.ts`; the diff was inspected (schemas split into
  `-Input`/`-Output` because nested engineering models mark defaults as required on serialization).

### Outstanding

1. **Licensed solver acceptance and physical correlation remain BLOCKED.** No Hyperfoam card was
   solved; the CAE check proves the keywords only.
2. **Registered-only enforcement is partial.** An unpinned model-local card still reports
   `material.unregistered` as a warning rather than a Prepare blocker, so existing synthetic models
   keep working. Enforcing the stricter rule needs those demo cards migrated to registered entries.
3. **CAE GUI Material Library Manager round-trip is not automated.** Kernel/reference read is
   verified; the GUI file-open path is not scriptable here.
4. **Direct hyperelastic N>1** (Ogden/Polynomial) is emitted as one row; the supplied library only
   has N=1 direct hyperelastics, so that specific path is untested against CAE.
5. Full-suite-only browser failures: playback cadence (71.7 ms; reproduces alone on this machine and
   predates this pass), both `materials.spec.ts` journeys and `offset-picking`. All three non-cadence
   cases pass in isolation; none is a Gate A–C test.

**Next executable slice.** Migrate the built-in demo materials to registered library entries and
make unregistered cards a Prepare blocker; then run a small licensed Hyperfoam uniaxial/tension
verification case (API → worker → solver → extractor) to establish input acceptance separately from
convergence and physical correlation.

## File → New/Open, CAE materials and top-level navigation · 2026-11-25

Use the [execution command and acceptance gates](docs/file-open-materials-navigation-handoff.md). The operator on port 8765 is running release `81fc7a73aa30`, API `f96456e1a763af94`. Its legacy “Imported projects” group is archived. Both File → New and Open Model reproduced the read-only banner and HTTP 409 in a disposable Edge session with that configuration. The same test with an active default group was editable. Repair standalone file ownership at creation and preserve all genuine archives. Then put Dashboard first, implement explicit Close, synchronize disk saves with pending edits and restore compatible embedded mesh/fixtures on Open.

The supplied library has 27 parsed cards. The registration API accepted two and skipped 25 when asked to register all. Eleven are Hyperfoam, including four coupled to Prony viscoelasticity. The handoff gives the source counts, regression cases and CAE reference-deck checks. A local per-card inventory stays under ignored `.local/evidence/2026-11-25-file-material-audit/`. The three actual spline snapshots passed through the import worker, including the previously unavailable open-only sample. No CAE license or solver was used for this audit.

Independent regression run on the unchanged application code: 328 Python tests passed, one skipped. The full browser suite had 161 passes, four skips and two failures (Fit/reset camera state and the material comparison). Both failing tests passed on a fresh service when rerun together. Typecheck, translations (946 keys per language), encoding (47 files), schema-byte comparison and the isolated production build passed. Gates 4 and 6 still require application work and interoperability checks as detailed in the brief.

## Six file-workbench gates · 2026-11-24

Baseline `84ab7a2` plus the uncommitted A–E delivery, which was preserved. All
tests used disposable `SEAL_DATA` roots, temporary folders and the isolated
browser service; the operator instance, its database and retained licensed
artifacts were not modified. **No licensed solver was launched.** One
Abaqus/CAE 2024 noGUI session was used for material-card verification (see
Gate 4), which consumed a CAE license token.

### Gate status

| Gate | Status | Measured outcome |
|---|---|---|
| 0. Two-tab Save Retry | **PASS** | Retry now rebases only the local delta. The reported 111 mm / 1.25 mm case keeps both values (`analysis.reporting_width=111`, `mesh.size=1.25`); a same-field edit is reported by path with Reload, never overwritten. |
| 1. Live progress | **PASS** | The card keeps its intrinsic height (`flex: 0 0 auto`, max `min(340px, 56dvh)`) and the named, focusable detail region scrolls. Card `scrollHeight <= clientHeight` at 1874×762, 1440×900, 1280×720 and 390×844 in JA/EN; the 1280×520 window scrolls the detail by keyboard with status, current step and warning visible. |
| 2. Completed result space | **PASS** | The large card is replaced by a completion line in the existing banner. At 1280×720 the result grid grew from 355 to **458 px** and the viewport from **302 to 324 px**; 46vh is the fixed shell's limit because playback must stay fully visible and the display controls remain reachable by scrolling the field card. Diagnostics still shows the full card. |
| 3. Spline import | **PASS (software)** | Open-only drawings import as inspectable models: two selectable spline edges, zero faces, `drawing.no_closed_region` blocker. Endpoints join at the existing 1e-6 mm tolerance (`snapped`/`maxGap` reported), real gaps are reported (`nearestGap`) and not bridged, and mixed fit/control loops keep cavities. The current DWG (`b874fa5168`) and the mixed backup (`5a4b114f42`) still import through upload → worker with two splines and one face. The earlier open-only drawing (`b7955ecd1a`) is absent; a manufactured equivalent covers it. |
| 4. Material library + element family | **PARTIAL (UI/enforcement) · CAE transfer verified** | A data-only protocol-0 reader decodes the supplied 79,592-byte library (27 cards, Japanese decoded, no execution). 2 of 27 cards map exactly (PA6, METAL); 25 are visible with precise ineligibility reasons. Import/export and provenance/fingerprints work; export is byte-identical CAE source. **Abaqus/CAE 2024 noGUI created all 27 cards from the parsed data and reproduced PA6 (2600 MPa, 0.39, 1.13e-9) and METAL (206000 MPa, 0.3, 7.65e-9).** Metal regions now mesh as CPS4 and polymer regions as CPS4R, with explicit per-region ELSETs and sections in the INP; a family change stales the mesh, a coefficient change does not. The model still accepts legacy unregistered demo cards as a warning rather than a hard blocker, and the CAE **GUI Material Library Manager file-open path** was not automated (kernel card creation was). |
| 5. One vertical workflow | **PASS** | Eight stable stage rows in DOM/visual/keyboard order. `AnalysisActions` moved from under the tree to the top of the Results properties exactly once; it is reachable before a mesh/deck/run exists. Short and zoomed layouts keep every row and action; Submit-only run parameters name CPU/name reasons. |
| 6. Portable model/result files | **PARTIAL (UI) · container and worker workflow verified** | `.aqmodel` New/Save/Save As with on-disk fingerprint conflict, atomic publish, mesh/fixture inclusion and reopening in a fresh data root. `.aqresult` is published by the worker after extraction with no browser, gives collision-safe distinct names, and opens read-only with frames/history in a fresh installation. Truncated, wrong-kind and unsupported-version files are refused before extraction; failed extraction refuses publication. The Dashboard still shows the project history; the File entry point is added rather than the project UI being fully retired. |

### Tests actually run (this machine, isolated data)

- `.\.venv\Scripts\python.exe -m pytest -q`: **328 passed, 1 skipped** (the opt-in Abaqus-Python roundtrip), exit 0.
- New Python suites: `test_dwg_open_only.py` (11), `test_material_library_cae.py` (5), `test_portable_files.py` (7).
- `test:i18n`: **946 keys** both languages. `test:encoding`: 47 files. `typecheck`: pass.
- Build: release **`81fc7a73aa30`**, entry `index-BdawGA5k.js`, API 3.
- Browser: full suite on the final release `81fc7a73aa30`: **160 passed, 4 skipped, 3 failed** (167 tests). The three failures are timing-sensitive and pass in isolation: `gate-f` playback cadence (71.7 ms > 50 ms under full-suite load; 2 passed alone), `materials` library validation (7 passed together with motion preview) and `motion-preview` body/door equality (same isolated run). A later 4-file run also saw the rapid-edit coalescing test once (3 revisions instead of ≤2; it then passed 3/3 repeated alone). None reproduces alone; they are suite-load flakiness, not gate evidence.
- Schema regenerated with `scripts/schema.py`; the generated diff was inspected.

### Blocked or outstanding

1. **Licensed solver evidence, numerical sensitivity, physical correlation and self-contact participation remain BLOCKED.** Nothing in these gates is solver evidence; the manufactured worker runs are software evidence only.
2. **CAE GUI round-trip remains open.** Card data is verified by the CAE kernel, but the GUI `Material Library Manager` file-open path is not scriptable here. Export is CAE's own bytes, so this is a verification gap, not a container change.
3. **Registered-only material enforcement is partial.** Legacy/demo model-local cards remain usable with a warning; the gate's stricter "only eligible registered pins" rule is not enforced as a Prepare blocker for those cards.
4. **Project UI retirement is partial.** File → New/Open/Save/Save As and result packaging exist, but the Dashboard project/history workflow is still present.
5. **3D solving remains deferred** and 2D plane stress is unchanged.

**Next executable slice.** Finish the registered-only material policy (migrate
demo defaults to registered entries), automate the CAE GUI library open, and
retire the project UI after migrating its models to files. Then run hosted
Windows CI on this tree.

## Independent delivery audit and next execution command · 2026-11-24

**Spline recheck.** The drawing changed since the first audit. The normal import worker accepted the current DWG (`b874fa5168`) and its mixed fit/control-point backup (`5a4b114f42`), persisting two splines and one face in each model. The earlier open-only drawing (`b7955ecd1a`) still failed the closed-region check on the same code. Gate 3 now records all three inputs and their expected outcomes.

Follow the [file-workbench execution handoff](docs/file-workbench-execution-handoff.md). Its six gates cover live progress, completed result space, both native spline representations, CAE material-library exchange and element formulations, vertical setup order, and portable model/result files. Implement the progress layout and protect unrelated edits on conflict before relying on the current save controller. The file extensions and storage workflow in the brief are proposals for implementation.

Verified on `84ab7a2` plus the existing application patch. Both operator health and isolated health reported API `be1bb24c071006c8` and release `4933ae101e08`. Fresh production output matched the published bytes. Reran pytest (305 passed, one skipped), full isolated Playwright (150 passed, four skipped, zero flaky), typecheck, translations (879 keys each), encoding (45 files) and schema generation to a temporary comparison file. An independent Edge test reproduced the 111 → 100 mm overwrite after Retry on an unrelated edit. Active progress at 1280 × 720 showed 124 px for 276 px of content. The retained material overlay matched eight interfaces and 239 perimeter segments in JA/EN. The supplied two-open-spline DWG was decoded then rejected by the import worker; mixed curves joined in the two closed positive controls. Static inspection of the CAE library identified 27 cards. No new licensed solver run. CAE exchange and the proposed file workflow await implementation and verification.

## Workbench edit, readiness, dashboard, force axis and material outlines — delivered · 2026-11-24

Baseline `84ab7a2` on `main`; only the [execution command](docs/model-edit-readiness-results-handoff.txt)
and the previous handoff entry were uncommitted. All work used the isolated `--test-data` browser
service (port 8876), disposable `SEAL_DATA` directories and temporary paths. The operator instance on
8765, its database, drawings and retained licensed artifacts were not modified. **No licensed solver
was launched.** The five gates are implemented and verified on API build `be1bb24c071006c8`, release
**`4933ae101e08`** (`index-BZ3wYYIK.js`, API 3): **A PASS, B PASS, C PASS, D PASS, E PASS on
manufactured evidence** (the operator's retained result was not re-read). Full detail, the 12-row
transition matrix and the measured clips are in
[implementation-report.md](docs/implementation-report.md#a13-workbench-model-edit-readiness-dashboard-force-axis-and-material-outlines--2026-11-24).

Delivered: (A) dashboard filters that shrink and wrap inside the run card, a focusable labelled table
scroller and a compact labelled row layout below 760 px — filter overhang 0 px at 1440/1280/720/390 in
both languages, down from 166/148 px, with no page overflow; (B) one automatic writer replaces the
working head for every valid committed edit, with coalescing, serialized writes, retained drafts,
idempotent lost-response recovery, a recoverable two-tab conflict and a Retry path; the Save revision
and Save contact actions are gone, **Duplicate setup** is the explicit branch, and every queued
operation flushes first; (C) role/mesh/mounting/motion/deck prerequisites read as incomplete with a
reason, the padlock is reserved for the deferred 3D extrusion, and Mounting stays usable across
unrelated edits; (D) the full force description is a wrapping caption beside the plot with a concise
unit-bearing axis (Y title 52.5 px for N, 80 px for N/mm, inside the 210 px plot at every width and
200% zoom, down from ~269 px); (E) optional material outlines from the pinned revision's face→material
assignment, with perimeters, one interface per distinct-material FE edge, a swatch legend, coverage
reporting and frame/deformation tracking.

Tests actually run: Python **305 passed, 1 skipped**; translations **879 keys**; encoding 45 files;
typecheck and build pass; browser suite **150 passed, 4 skipped, 0 failed** (154 tests; the skips are
the two opt-in retained replays, the gated screenshot capture and the retained native-lip check);
`scripts/schema.py` reproduced `generated.ts` byte-identically; `git diff --check` clean.

**Next executable slice.** Run hosted Windows CI on this tree; then re-read the operator's retained
two-material result from a read-only copy to confirm the 8-interface / 4-same-material-seam count with
the new overlay. Investigate the pre-existing intermittent materials-comparison full-suite failure
(passes in isolation) and the previously reproduced desktop camera Fit/reset comparison.

**Outstanding dependencies.** No licensed solve: physical correlation, numerical sensitivity and
self-contact participation remain **BLOCKED**. The operator's 8765 instance still runs release
`5be20b24e6d0` and was not upgraded. 3D solving remains deferred.

## Dashboard, model editing, readiness and Results handoff · 2026-11-24

The [execution command](docs/model-edit-readiness-results-handoff.txt) covers five requests and defines the setting order and lock transitions explicitly. The three measured failures were narrow dashboard filter overflow, the clipped force-axis title, and a corrected component role retaining a blocked badge until persistence. In an isolated 37-node fixture, a friction-only edit hid the mounting controls; persisting it preserved the fixture and enabled deck preparation. A fresh mesh correctly required a new review. The retained result mapped 783 seal elements to two materials. Three existing readiness tests passed. The delivery above supersedes this paragraph: implementation, Gate A–E verification and the isolated build are complete; the retained operator result recheck is outstanding.

## Assembly tree at short window heights · 2026-11-24

Desktop sidebar scrolling keeps the populated tree at least 11 rem tall. Roles appear below component names. The open narrow-screen drawer includes the tree. In Edge at 1280 × 720 with missing materials and an expanded seal, tree height increased from 18 to 176 CSS pixels, revealing four child rows. The new regression failed on the previous release and passed on build `5be20b24e6d0`. The build, all four layout tests, and the bilingual analysis-action reachability test passed. The existing intermittent desktop camera Fit/reset comparison failed once and passed on the layout rerun. The next operator session can use the new build.

## Hollow lip partition repair · 2026-11-24

The three audited defects were reproduced before production edits and retained as regressions. The
canonical fit-point spline is now trimmed analytically, including existing knot cuts; centered
spline-wall hits are retained and seam incidence is checked against distinct opposing child faces.
The Components editor identifies unfinished guides and permits removal or completion.

The reviewed native DWG was imported into a disposable isolated service. Real Edge clicks after
pan/zoom, Apply, reopen, individual face picking, two materials, remesh, fresh fixture and INP
preparation passed on API build `31b50f8034fdd144` / release `079e1658446f` at checkout `9dd1965`
plus uncommitted edits. The operator instance remained on its old release and was not restarted.
Exact spline areas, seven guide cases, pointer rounding, cavity, seam nodes, contact exclusion,
boundary tolerance and section evidence are in [the implementation report](docs/implementation-report.md#a12-hollow-lip-partition-repair--2026-11-24).
The local evidence screenshots are in the current session's `files` directory. No solver was run.

Tests: targeted Python 48 passed; full Python 304 passed, 1 skipped; translation 863 keys, encoding
44 files, typecheck and build passed; targeted browser including the native drawing journey passed
8 tests. The full-browser run before the tangent-only follow-up had 114 passes, 4 skips and 2 failures. Material comparison
passed in isolation; desktop Fit/reset failed again and reproduces the same camera scales against
the original `f17b356730d6` frontend with the current API. The full browser suite was not rerun
after the tangent follow-up.

**Next executable slice:** investigate the separately reproduced desktop camera-fit regression, then
rerun the full browser suite and hosted Windows CI on the resulting tree. Periodic and unclamped
spline splits are not supported. Solver execution, numerical sensitivity,
physical correlation and self-contact participation are separate, still-open validation work.

## Native-DWG hollow lip partition audit · 2026-11-24

The [execution-agent command](docs/fix-hollow-lip-partition.txt) is ready to copy into an implementation session. It includes reproducible failures, targeted and full regression commands, and the four release gates.

The [reproduction and repair brief](docs/hollow-seal-partition-audit.md) supersedes the previous Gate D conclusion for imported fit-point geometry. On main at `9dd1965`, real Edge clicks against an isolated copy of the operator's saved hollow section returned HTTP 422 for a valid lip cut. Six material-intersecting guides failed. A diagnostic canonical-spline trim produced two material regions, a conforming lip mesh and distinct INP material sections. A single radial wall guide retained one region as expected.

The next executable slice is to support shape-preserving trims on the open and closed fit-point boundaries seen in native imports, fix exact-sample misses, and reject dangling seams in mixed drafts. Gate the release on the native-style Components → cut → assign → remesh → deck workflow. The current 31 partition and two original-DWG inventory/deck tests passed during the audit. Production changes, repaired browser acceptance and broader periodic-curve coverage remain pending.

## Left-panel setup, deck readiness, force axis and projected seal cuts — delivered · 2026-11-24

Baseline local HEAD `b8252a4`, remote main `aa2964b`. The pre-existing Windows launcher, startup-test,
handoff and guide edits were preserved. All writes used disposable data roots and unused ports; the
operator instance, database, drawings and retained licensed artifacts were not modified. **No new
licensed solver was launched.**

The four gates in the [execution brief](docs/setup-readiness-partition-handoff.txt) are implemented and
verified: **A PASS, B PASS, C PASS, D PASS**. The gate table, blocker before/after table, test counts and
evidence are in
[implementation-report.md](docs/implementation-report.md#a11-left-panel-setup-deck-readiness-force-axis-and-projected-seal-cuts--2026-11-24).
The retained licensed replay is recorded in
[engineering-validation.md](docs/engineering-validation.md#force-axis-replay-of-retained-licensed-run-76b20d84--2026-11-24-no-solver-launch).

Both reported Prepare failures were reproduced before editing: the 100→101→100 reporting-width revert
left Prepare disabled as “Unsaved changes”, and a valid +Y motion from below the seal (door at y=−2 mm,
3 mm at +90°) was rejected by the legacy signed-travel predicate. Readiness is now action-specific on the
server (`can_prepare` / `can_submit`), a missing/stale deck blocks Submit only, and semantic equality
clears unsaved state on revert.

### Delivered in this pass

- Review/Run is gone: workflow is Import → Components → Materials → Mesh → Mounting → Contact → Motion →
  Results, with stable stage IDs (legacy 7 → Motion, 8 → Results). Prepare/Submit live in one compact
  left **Analysis actions** group with deck inspection/download, run name, CPUs, launcher state and the
  active-run link. Motion owns W, force normalization and read-only solver thickness.
- Components owns roles, region selection and projected partition. Arbitrary two-click viewport guides
  are projected onto analytic boundaries; the authoritative server arrangement supports one or more
  seams, two-or-more children, a one-region draft, no-hit/mixed diagnostics and preview/commit-identical
  child IDs. Models, meshes, decks and prior child regions remain readable.
- RunView reports the selected step's role, RP, direction/angle and force basis; legacy provenance stays
  unknown rather than borrowing the closing direction. Reverse Y is visibly display-only; missing force
  stays a gap.

### Tests actually run (this machine, isolated data)

- `pytest -q`: **296 passed, 1 skipped** (opt-in Abaqus-Python roundtrip), exit 0.
- `test:i18n`: **862 keys** both languages. `test:encoding`: 44 files. `typecheck`: pass.
- `build`: release **`f17b356730d6`**, entry `index-4Io9K-QL.js`, API 3.
- `test:browser`: **113 passed, 3 skipped** (two opt-in retained replays and the gated screenshot
  capture). Gate A full DXF journey; Gate B width/angled/warning/failure-retry; Gate C trace+CSV; Gate D
  DPR 1 and DPR 2 after pan+zoom plus the hollow single-wall→second-wall flow.
- `scripts/schema.py`: second generation byte-identical (`C317BA95…`). `git diff --check`: clean.
- Evidence: `.local/evidence/{action-group-left,hollow-cut-incomplete,hollow-cut-valid}.png`,
  `axis-replay.json` and `axis-replay-{closing,bodyseating}.png`.

**Next executable slice.** Run hosted Windows CI on the tested tree; demonstrate self-contact
participation or leave it BLOCKED; obtain independent reference measurements and agreed tolerances
before any physical claim. A future partition slice can add an explicit multi-face target scope.

**Outstanding dependencies.** No new licensed solve was run. Physical correlation, numerical sensitivity
and self-contact participation remain BLOCKED. The force-axis pass is retained replay, not new solver
evidence. Hosted Windows CI for this tree is outstanding.

## Windows startup and delivery audit · 2026-11-24

Checked local commit `b8252a4` against remote main `aa2964b`. Port 8765 initially served release `5cac5e2a1e92` from a second checkout. The launcher detected the conflict, but its batch wrapper expanded `%ERRORLEVEL%` before Python ran and returned success. A failed double-click now keeps the diagnostic visible and flag-based invocations return the child's exit code. The idle instance was switched with operator approval. Edge opened the Japanese Dashboard at the normal root URL on release `6a8527d475c5`. All 6 group, 15 model and 69 job IDs matched the pre-switch inventory.

Fresh verification: 59 Python tests passed across startup, units and phase-two domain tests. Fourteen browser tests passed across Gates A, D, E and motion preview on an isolated manufactured-worker service. Typecheck, translation parity (806 keys) and encoding (43 files) passed. The retained full Python report contains 279 passes and one skip. The prior full browser count is the delivering agent's report. The three retained solver status files record completion, the ODBs exist, and all three original INP hashes match the engineering record. No new licensed solve was run. The retained playback trace differs from the original report on the worst interval; the trace values are recorded below.

**Next executable slice.** Run hosted Windows CI once the changes reach a tested remote SHA, including the batch wrapper regression below. DPR-2 pan/zoom partition coverage, self-contact occurrence, sensitivity and independent physical correlation remain open.

## Second UI and 2D engineering pass — delivered · 2026-11-24

Baseline `aa2964b4e1ed4640f2a4e28c8a2a74e1e7a37393`, matching `origin/main`; only the execution brief,
visual reference and this handoff entry were uncommitted before work. All verification used isolated
`--test-data` data and disposable synthetic projects. The operator instance, database, drawings and
retained licensed runs were not modified.

**Requests 1–16 are implemented.** The 16-row PASS/FAIL table, gate results and file list are in
[implementation-report.md](docs/implementation-report.md#a10-second-ui-and-2d-engineering-pass--2026-11-24).
Licensed execution (three synthetic cases) is recorded separately in
[engineering-validation.md](docs/engineering-validation.md#second-ui-and-2d-engineering-pass--licensed-execution--2026-11-24).
**Physical correlation, numerical sensitivity and self-contact participation remain BLOCKED.**

### Delivered in this pass

- Shell uses the full parent width with 16–32 px gutters; local vector hollow-seal brand; tangerine active
  navigation; 16 px body type and role-specific labels.
- Both Dashboard create flows start empty; the public-example checkbox is gone; synthetic seeding stays in
  the test API.
- DXF/DWG units are converted once to mm with declaration/factor/provenance recorded; US survey units and
  aliases supported; range and contradictory metadata are reported, never guessed.
- Contact has independent door↔seal, body↔seal and seal↔self coefficients written as named assembly
  surface pairs in both decks; legacy scalar friction is preserved exactly.
- Steps are derived from participating roles; duplicate roles are reported, never silently dropped.
- Motion uses stroke + direction angle with a shared Δ convention; the deck writes both U1/U2 targets;
  per-panel preview animates and restores without writing.
- Reporting width W (default 100 mm) is separate from solver thickness t; displayed force is (RF·d)·W/t.
- “Export displayed curve” is a two-row spreadsheet CSV (magnitude, projected force) with holes for missing
  measurements and a stated basis.
- The section cut is acquired on the white viewport with canonical snapping and real click preview/apply.
- Review actions are the first Properties group; “Go to Mesh” shortcuts are removed; the pane scrolls to
  the top on stage change.
- Results defaults to mesh edges on; playback has a fixed status track, bounded read-ahead and monotonic
  deadlines.

### Tests actually run (this machine, isolated data)

- `pytest -q`: **279 passed, 1 skipped** (opt-in Abaqus-Python roundtrip), exit 0.
- `test:i18n`: **806 keys** both languages. `test:encoding`: 43 files. `typecheck`: pass.
- `build`: release **`6a8527d475c5`**, entry `index-CfGm1X5y.js`, API 3.
- `test:browser`: **103 passed, 3 skipped** (two opt-in replays, gated screenshot capture).
- Gate F's retained trace records median 243.1 ms, p95 error 30.1 ms, worst 266.6 ms over 62 transitions; host/slider/camera
  stable. See `.local/gate-f-measurements.json`.
- Before/after screenshots: `.local/screenshots/{before,after}` at 2560/1440/390 in both locales.
- Licensed runs: vertical `b3859d0a…`, oblique `76b20d84…`, partition `bbe7a44c…`; all solver and extraction
  succeeded. Details and hashes in the validation record.

### Next executable slice

1. Re-run the oblique and partition cases with mesh/time refinement and inspect contact pressure/slip
   history, then obtain independent reference measurements and agreed tolerances before any physical claim.
2. Demonstrate self-contact participation with an observable pressure/slip result, or leave it BLOCKED.
3. Run hosted Windows CI for this tree; reproduce the two previously hosted browser failures under comparable
   conditions.
4. Add pan/zoom DPR-2 cut acquisition coverage if the projection discrepancy is reproduced.

## Second UI and 2D engineering pass — execution brief · 2026-11-23

Start with [the 16-request execution brief](docs/workbench-phase-two-execution-brief.txt) and the [workbench visual reference](docs/workbench-visual-reference.png). Local and remote main matched `aa2964b4e1ed4640f2a4e28c8a2a74e1e7a37393` at inspection. [Hosted CI for that SHA](https://github.com/stefanoKS/Abaqus_QualityOfLife/actions/runs/45185600553/job/137730259257) passed Python and failed the material comparison and renderer browser checks.

One temporary instrumented Edge/Playwright test passed against release `07b80dd311ac` on isolated port 18963 using the manufactured worker. The Dashboard scroller measured 1950 px in a 2560 px window. In 1440×900 Results the slider lost about 47 px on pending frames. With 180 ms added to odd frame requests, adjacent display intervals included 243 ms and 445 ms while camera signature and host size stayed stable. No licensed run or retained replay was used for this investigation. The previous full-suite counts below belong to the preceding implementation.

**Next executable slice.** Capture these three baseline symptoms, repair the layout and playback regressions using Gates A/F, then carry the domain contracts for units, contact, motion and represented width through both deck paths, extraction and the two-row export. Gate E exercises the cut entirely by viewport clicks. Remaining engineering dependencies include a local licensed oblique/contact verification case, retained playback with proven provenance, and independent physical reference data.

## UI redesign, direct deletion and seal partitioning — delivered · 2026-11-23

Baseline `6ace5475ba9f76b21cd2cc915a4c195f6d87fa9b`, matching `origin/main`. The working tree held
only the execution brief (untracked) and this handoff entry before work began. All verification used
isolated `--test-data` browser data and disposable projects; the operator database, active jobs,
retained licensed runs and original drawings were not modified. **No licensed solver was launched and
no license was consumed.**

### Request status

| # | Request | Status | Evidence |
|---|---|---|---|
| 1 | Redesign shell / move workspace controls | PASS | Fixed workstation at 1440×900 and 1280×720, pane adjacency, fixed canvas during property scroll, Review dock top-right, narrow collapse, 200% width: `apps/web/tests/layout.spec.ts`. |
| 2 | Body panel / Door panel terminology | PASS | 757 keys both languages; role/alias audit; assembly tree shows translated role; identifiers unchanged; `i18n.spec.ts`, `phase1.spec.ts`, encoding gate. |
| 3 | Result geometry (rigid panel with U, no stress) | PASS | `tests/scene-model.spec.ts` asserts the y=4→y=2 edge and markers in Mises/U, scales 1/2, missing U, measured zero vs absent stress, instance-qualified picking. |
| 4 | Independent displacement/stress ranges | PASS | `apps/web/tests/ranges.spec.ts`: 0–5 mm / 0–0.5 MPa defaults, Auto, manual both-end clipping, invalid drafts, reset, unclipped signed probe. |
| 5 | Shared saturated palette | PASS | `viewportModel.ramp` exact stops; legend and actors use it; scene test. |
| 6 | Loop playback | PASS | `ranges.spec.ts`: default loop, repeated wraps, Loop off, hold-last, slow boundary, camera/scale stable; existing playback/curve tests. |
| 7 | Prepare/submit controls and state near Review | PASS | `review-actions` dock in the upper-right work area; run name, CPU, readiness reasons, deck state/link retained; `layout.spec.ts`, `review.spec.ts`, `workflow.spec.ts`. |
| 8 | White field, no centred import; Import owns picker | PASS | `viewport.css`/renderer white; overlay removed; `layout.spec.ts` empty-viewport and one-chooser/cancel tests. |
| 9 | Narrow/zoom reachability and scrolling regions | PASS | Collapsible workflow/properties, stacked flow, internal pane scrolling; `layout.spec.ts` 390×844 and 720×450. |
| 10 | Direct permanent deletion | PASS | `tests/test_archive_delete.py` (direct model/group, enqueue race, revised scope, membership change) and `apps/web/tests/archive.spec.ts` (accessible dialog, focus/Escape, wrong name, mixed group). |
| 11 | 2D seal material partition | PASS (software) · **licensed evidence BLOCKED** | `tests/test_partition.py` (18 tests: area/union, child-of-child, arc/hole, rejection, mesh conformity, both deck paths, API idempotency/staleness) and `apps/web/tests/partition.spec.ts` (browser+worker+INP+replay). No licensed partition run or ODB exists. |

### Delivered summary

- **Gate 0.** The clean checkout reproduced the CI failure (`/api/health` returned an empty frontend
  before the build). `tests/test_release_and_compatibility.py` now provisions an isolated release
  fixture and separately covers the supported missing-build state; both pass without a `dist/`.
- **Shell.** Workflow and properties are adjacent on the left; the white drawing field gets the
  remaining width. Desktop is a fixed shell with independently scrolling panes; narrow/zoomed layouts
  stack and can collapse the panes. Review's prepare/submit dock is anchored upper-right.
- **Results.** Displayed coordinates use base coordinates + measured nodal U + toggle/scale; scalar
  availability controls colour only. Displacement and stress ranges are independent; Loop wraps after
  holding the last displayed frame.
- **Deletion.** The archive prerequisite is gone. The final activity decision, ID enumeration and row
  deletes run in one `BEGIN IMMEDIATE` transaction, and the journal commits atomically with the
  deletes. A competing enqueue loses with a 404/conflict; a competing model creation cannot orphan a
  deleted group.
- **Partition.** New `packages/engineering/partition.py` performs a deterministic straight two-point
  cut (0.05 mm boundary snap), splits canonical line/arc/clamped-spline edges, rewrites every incident
  signed loop, preserves cavities, remaps selections and local sizing, validates area/union/disjoint
  interiors, and returns code-bearing rejections. Preview and commit share it; commit is transactional,
  base-checked and content-idempotent. Children inherit the parent material; the internal seam is a
  bonded interface excluded from `SEAL_EXTERIOR`.

### Tests actually run (this machine, isolated data)

- `.\.venv\Scripts\python.exe -m pytest -q --junitxml=pytest-results.xml`: **261 passed, 1 skipped**
  (opt-in Abaqus-Python extractor roundtrip), exit 0.
- `npm --prefix apps/web run test:i18n`: **757 keys** in both dictionaries.
- `npm --prefix apps/web run test:encoding`: 41 source files, no known mojibake.
- `npm --prefix apps/web run typecheck`: pass. `npm --prefix apps/web run build`: release
  **`07b80dd311ac`** (entry `index-NSGLmlbQ.js`, API 3, 4 files).
- `npm --prefix apps/web run test:browser`: **86 passed, 3 skipped**. The skips are the two opt-in retained-result replays (their isolated 8891/8892 instances were not running) and the gated screenshot capture; they are not acceptance evidence.
- `git diff --check`: clean. `scripts/schema.py` regenerated `generated.ts`; a second run produced no
  further diff.

### Screenshots and evidence

Before/after captures (fictional data, both locales) are under
`.local/screenshots/before/` and `.local/screenshots/after/`: dashboard, materials, empty import,
populated workspace, Review and Results. These are local and ignored by Git.

### Blocked and next executable slice

1. **Licensed partition evidence — BLOCKED.** Exact missing inputs: a small local licensed 2D case
   passed through API → worker → solver → extractor with the retained ODB/revision, plus direct ODB
   checks of both child regions (one element set/section per child, internal seam not in `SEAL_EXTERIOR`,
   shared interface nodes, field locations). Nothing was authorized or run in this pass.
2. **Retained replay — not repeated here.** The opt-in retained-result and two-step replay specs still
   need their local seeds/ports; they skipped in the final run. Replaying read-only copies with verified
   provenance remains outstanding.
3. **Physical correlation — BLOCKED.** Still needs independent reference measurements and agreed
   tolerances; a converged run or matching screenshot cannot establish it.
4. **Hosted Windows CI** has not run for the delivered SHA; run it after committing and diagnose any
   real failure rather than accepting an incomplete report.
5. Partition follow-ups: straight cuts only (other spline variants rejected by name); FE-node fixtures
   are not transferred across the topology change; 3D solving remains out of scope.

## Prior planning entry: UI redesign and seal partitioning brief · 2026-11-23

The [execution prompt](docs/ui-redesign-execution-brief.txt) covers the eleven requested changes, the affected code paths and gates 0–6. At inspection, the clean working tree, local main and remote main matched `6ace5475ba9f76b21cd2cc915a4c195f6d87fa9b`. The usability repair described below has been committed. [Hosted Windows CI](https://github.com/stefanoKS/Abaqus_QualityOfLife/actions/runs/45159365244/job/137640449024) reported 1 failed, 234 passed and 3 skipped. The pinned-release health test received an empty frontend identifier before the frontend build step.

One local, license-free Node scene check reproduced the rigid-panel Mises bug. With a PANEL-1 edge at y=4 mm and measured U2=−2 mm at both ends, displacement view drew the edge and markers at y=2 mm. In Mises view the edge stayed at y=4 mm and its markers moved to y=2 mm. The scene builder conditions edge deformation on contour availability. This planning pass inspected source and CI logs and exercised the scene builder. Browser regression, full pytest and solver execution belong to the implementation pass.

**Next executable slice.** Begin with Gate 0 in the execution prompt. Reproduce the CI failure in a clean checkout, capture the baseline layouts and turn the panel-coordinate example into a regression. Gate 3 verifies the viewer, Gate 5 verifies conforming material partitions and Gate 6 covers retained replay. Licensed replay needs local artifacts with verified provenance; physical correlation still needs independent reference measurements and agreed tolerances.

## Usability and CI repair · 2026-11-23 (hosted CI and physics outstanding)

Baseline and fetched `origin/main`: `0e0c227a0be681ec12326fad6c8f22a236ed0417`;
the repair is uncommitted. No live instance, production data or retained solver
artifacts were altered. Version 3 defaults new door travel to −10 mm; old
omitted travel remains −5.5 mm. Contact status compares its own draft to its
saved values. Review actions, bilingual friction guidance, venv CI setup,
startup cleanup and pytest re-exec test isolation were updated.
Motion-value edits reuse compatible meshes; changing analysis mode can change
which rigid body participates and therefore legitimately invalidates the mesh.

Verification on Windows in an isolated worktree and fresh locked Python 3.11
environment: `python -m pytest -q --junitxml=pytest-final.xml`: **235 passed,
3 skipped**, complete report and exit 0. The optional Abaqus Python roundtrip
and two original-DWG checks skipped; the latter drawing is absent from the clean
worktree. `npm run test:browser`: **72 passed, 2 skipped**; the two skips are
licensed retained-result replay, not acceptance. That full browser run preceded
the final saved-readiness banner and active-run status text changes; the final
build (`c4771994c59f`) passed the 11 selected contact, readiness, compatibility,
Review and workflow tests. `test:i18n`: 709 keys; `test:encoding`: 41 files;
typecheck and isolated build passed. Full-suite literal legacy-payload additions
were subsequently rechecked with `pytest -q tests/test_defaults.py` (6 passed).
The expanded friction boundary and contact-dirty browser test was then rerun
separately (1 passed).
Before/after screenshots use fictional examples and disposable data.

Prior-claim independent software audit:

| Area | Status and evidence |
|---|---|
| Drawing units | Implemented/tested: `test_units.py`, `import-units.spec.ts`; original-DWG-specific checks skipped. |
| New/legacy defaults | Implemented/tested: `test_defaults.py`; real installation upgrade not exercised. |
| CPS4R policy | Implemented/tested: `test_abaqus.py`, mesh browser tests. |
| Neo-Hookean deck | Implemented/tested license-free: `test_abaqus.py`, material tests; no new licensed solve. |
| Zero holds | Implemented/tested: `test_two_step.py`, `zero-travel.spec.ts`. |
| Position/clearance | Implemented/tested: `test_two_step.py`, `assembly.spec.ts`, `offset-picking.spec.ts`. |
| Mesh artifact recovery | Implemented/tested: `test_release_and_compatibility.py`; historical retained-run replay not repeated. |
| Mises and Results defaults | Implemented and synthetic field tests passed; licensed viewer replay skipped. |
| Canonical steps | Implemented/tested: `test_results_fields.py`, `test_two_step.py`. |
| Instance-qualified element labels | Implemented/tested: `result-fields.spec.ts`. |
| Two-step playback | Implemented; licensed replay skipped, so retained-run replay not independently verified. |
| Windows ownership/startup | Implemented/tested: `test_startup.py`, `test_restart.py`; hosted CI remains unverified. |

Retained input-deck SHA-256 values for the three reported licensed cases match
the validation record, but ODB/revision linkage, solver/extractor agreement
and licensed replay were not independently checked. No new solve was authorized.
Physical correlation remains **BLOCKED**; divergence/cut-back and disconnected
region warnings remain open. The 10 mm default is not physically validated.

**Next executable slice:** run hosted Windows CI on the eventual commit; if it
fails, diagnose the actual failure without accepting an incomplete pytest report.
Separately replay read-only licensed evidence in isolated copied data with
verified revision/deck/mesh/ODB provenance, then obtain independent engineering
reference data and tolerances. Verify a real installation upgrade and all
remaining requested UI edge cases before release sign-off.

## Baseline for requested usability and CI repair · 2026-11-23

The clean working tree and fetched `origin/main` both point to
`0e0c227a0be681ec12326fad6c8f22a236ed0417`. The preceding milestone's
uncommitted work was incorporated into this commit. Its removal of `.dwl` and
`.dwl2` files is consistent with transient AutoCAD drawing locks; intent is not
documented. No retained data or live service has been changed.

Prior claims A–L (units, defaults, elements, material law, holds, placement,
mesh recovery, results, steps, instance labels, playback and ownership) are
implemented in the baseline according to the handoff, but independent
verification remains outstanding here. CI run 45074445610 independently
confirms a missing `uvicorn` in Playwright's interpreter and a locked
temporary `owner.lock` during exception cleanup. The local project venv imports
uvicorn, FastAPI, Pydantic and Shapely successfully. Licensed-artifact
agreement and physical correlation are not independently verified.

## Milestone delivery · 2026-11-23 (Gates A–G PASS with neo-Hookean; physical correlation BLOCKED)

Baseline `5104b99`. All work was done in isolated data roots and on isolated ports; the live
instance (8765), its database, drawings and retained runs were not restarted or modified. The live
instance was reachable at the start of the session and was not reachable at the end; no session
action targeted it, and it was not started again.

| Area | State | Where |
|---|---|---|
| Import units | PASS: no checkbox, immediate picker, declared mm / unitless-as-mm / missing-header / named-unit rejection recorded in `Source.unit_basis`. Browser and API tested. | [units.py](packages/engineering/units.py), [Workspace.tsx](apps/web/src/Workspace.tsx), [test_units.py](tests/test_units.py) |
| Defaults | PASS: new models 0.5 mm / 1.0 s; `schema_version` 2 with version-1 legacy backfill (1.0 mm / 1.3 s) and explicit-value preservation. | [model.py](packages/engineering/model.py), [test_defaults.py](tests/test_defaults.py) |
| Rubber element policy + solid law | PASS: enforced reduced integration, CPS4/R2D2/CPS3 legend, per-region counts, deck rejects CPS4 rubber quads; compressible neo-Hookean C10/D1 with versioned library cards, bilingual editing and a licensed 2024 run (`a8f47acc…`). | [deck.py](integrations/abaqus/deck.py), [model.py](packages/engineering/model.py), [MaterialEditor.tsx](apps/web/src/features/materials/MaterialEditor.tsx), [engineering-validation.md](docs/engineering-validation.md) |
| Zero travel | PASS: true hold for body/door incl. door-only, explicit zero BCs, hold-only UI/diagnostics. | [deck.py](integrations/abaqus/deck.py), [zero-travel.spec.ts](apps/web/tests/zero-travel.spec.ts) |
| Placement | PASS: offset-first assembled side, intersection vs ambiguous, no-overlap; legacy 1.80 mm door gap preserved. | [deck.py](integrations/abaqus/deck.py), [test_two_step.py](tests/test_two_step.py) |
| Results | PASS: Mises default, element cell colouring (max IP), fixed 0–0.5 MPa scale, saturation, editable range, white canvas, edge/node toggles, 1× deformation, node/element probes, missing vs zero. | [RunView.tsx](apps/web/src/RunView.tsx), [viewportModel.ts](apps/web/src/viewportModel.ts), [results-retained.spec.ts](apps/web/tests/results-retained.spec.ts) |
| Step identity | PASS: canonical id ignores case and whitespace (`Bodyseating`), shared by frames/history/plot/CSV; configured name kept for display. | [interchange.py](integrations/abaqus/interchange.py), [extract_odb.py](integrations/abaqus/extract_odb.py) |
| Licensed two-panel | PASS (execution): moving-body 5 mm gap `eca0c88e-8196-48cc-964a-971f2f8c24e3`; held-body `89fab9df-23fd-481c-a8d5-bbcb934f0354`; neo-Hookean door seal `a8f47acc-dd15-42df-8f61-a0feed14adb9`. All solved and extracted; both RPs read directly from both ODB steps; fixed nodes ~1e-37 mm; Mises and CSV agree. | [engineering-validation.md](docs/engineering-validation.md) |
| Mesh recovery | PASS: missing/corrupt active mesh is `mesh.artifact_missing/corrupt` in readiness, deck preparation refuses with the recovery action, and historical decks stay readable. | [readiness.py](services/readiness.py), [store.py](services/store.py), [test_release_and_compatibility.py](tests/test_release_and_compatibility.py) |
| Offset picking | PASS: real Edge/WebGL clicks on `PANEL-1` and `BODY-1` at +0.5/−1.0 mm, surviving zoom and middle-button pan. | [offset-picking.spec.ts](apps/web/tests/offset-picking.spec.ts) |
| Two-step replay | PASS: a re-extracted licensed two-step result opens on Closing, switches the curve/CSV to Body seating and back with canonical ids. | [two-step-results.spec.ts](apps/web/tests/two-step-results.spec.ts) |
| Physical correlation | **BLOCKED**: no independent reference, no agreed tolerance. Solver warnings (divergence cut-backs, 3 unconnected regions, zero-force body step before contact) need engineering review. | validation record |

**Tests actually run:** pytest **230 passed, 1 opt-in skipped**; `test:i18n` **700 keys**;
`test:encoding` pass (41 files); `typecheck` pass; build release **`50f7b3465baf`**; Playwright
**71 passed, 1 opt-in skipped** (the retained-result replay spec is skipped when its isolated 8891
instance/`.local` seed is absent; the two-step replay spec skipped only if 8892 is absent).

**Next executable slice.** (1) Physical correlation against an independent reference with an agreed
tolerance, starting from the synthetic two-panel and neo-Hookean cases (do not claim it from
convergence alone). (2) Convergence and rate sensitivity; the licensed runs still emit divergence
cut-backs and pre-contact zero-force warnings. (3) Per-pair friction, oblique motion and partitions
remain outside this delivery. (4) Optionally broaden the solid-rubber law beyond neo-Hookean.

**Files changed (this milestone).** `packages/engineering/{model,geometry,units,dxf,dwg,__init__}.py`;
`integrations/abaqus/{deck,results,interchange,extract_odb}.py`; `services/api/{main,contracts}.py`,
`services/readiness.py`, `services/store.py`, `services/material_library.py`;
`apps/web/src/{Workspace,RunView,Viewport,viewportModel,viewportRenderer,style,viewport.css,MaterialsPage}.tsx`,
`features/mesh/{meshQuality,MeshReview}.tsx/ts`, `features/run/fields.ts`,
`features/materials/MaterialEditor.tsx`,
`features/workspace/{AssemblyDiagnostics,readiness,workflowStates}`,
`i18n/{en,ja}`, `generated.ts`; tests `test_defaults`, `test_units`, `test_results_fields`,
`test_two_step`, `test_abaqus`, `test_geometry`, `test_release_and_compatibility`,
`test_material_library`,
`apps/web/tests/{import-units,zero-travel,assembly,results-retained,offset-picking,two-step-results,result-fields,materials,playback,numeric-guard,isolation,workflow}`;
docs. `scripts/schema.py` was run and the generated diff inspected.

## Two-panel placement, contact orientation and motion projection · 2026-11-22 (Gates 1–6 PASS, Gate 7 BLOCKED)

Baseline `f1cb37b`, clean tree. The reported arrangement — door **above** the seal moving −5.5 mm
over 1.3 s, body **below** the seal moving +5 mm over 1.0 s, both initial offsets 0 mm — now
prepares a complete two-step deck. No licensed solver was launched, no license was consumed, no
retained ODB/INP/mesh/history was modified and the live instance was not restarted.

| Item | Repair | Evidence |
|---|---|---|
| F1 role-aware clearance | `clearance_report()`/`_separation()` in [deck.py](integrations/abaqus/deck.py) classify the contact side from the drawn profile and measure the minimum vertical separation of the real piecewise-linear FE surfaces over their shared X range (sloped, curved, vertical segments). Positive separation for above **and** below; no `abs()`. Distinct `ClearanceError` codes `initial_penetration`, `motion_away`, `no_x_overlap`, `side_ambiguous`, `unsupported_geometry`. `vertical_gap()` stays as a compatibility wrapper and the legacy 1.80 mm door gap is unchanged. | A–I in [test_two_step.py](tests/test_two_step.py) |
| F2 rigid normals | `orient_for_contact()` reverses a below-mounted profile's R2D2 connectivity so SPOS faces the seal; the door above keeps the legacy order. Each part keeps its own `PROFILE` elset, connectivity and RP; the writer still emits one `SPOS` surface per part. | J recomputes every normal from the INP connectivity |
| F3 per-motion direction | `motion_assessment()` + `results._metadata()` derive door `[0,−1]` and body `[0,+1]` independently; `placement` and `assembly` record side/direction/clearance/gap reach. `align_histories()` projects per step; `_history()` in [extract_odb.py](integrations/abaqus/extract_odb.py) matches step names case-insensitively and refuses to project an unknown step onto the door reference. Raw signed components are never rewritten. | L, per-motion metadata, `tests/test_abaqus.py` |
| F4 viewport | [viewportModel.ts](apps/web/src/viewportModel.ts) groups mesh elements by instance (`WS-1`, `PANEL-1`, `BODY-1`) and applies each profile's own offset; picking identity, actors, camera and mesh toggle are unchanged. [Viewport.tsx](apps/web/src/Viewport.tsx) adds `data-scene-instances` and an assembled-offset caption. | `apps/web/tests/assembly.spec.ts`, `renderer.spec.ts` |
| F5 diagnostics | Readiness returns a geometric `assembly` block before a deck exists; [AssemblyDiagnostics.tsx](apps/web/src/features/workspace/AssemblyDiagnostics.tsx) shows clearance, side, offset, travel/direction and gap reach in Motion and Review, with ja/en codes and the explicit caveat that travel past the gap does not guarantee contact. Penetration/away/overlap become readiness blockers. | `test_readiness_exposes_the_bottom_body_measurement`, `assembly.spec.ts` |
| F6 fixtures | The two-step test project now accepts a body Y, sign, offset and X range; meshes are shared per scenario. | 24 tests in `test_two_step.py` |

**Gate summary:** 1 clearance PASS · 2 normals PASS · 3 INP/step boundaries PASS · 4 projection PASS
· 5 viewport/Edge PASS · 6 all existing suites PASS · **7 licensed two-step validation BLOCKED** — no
authorized licensed run, so no solver physics, contact onset or force correlation is claimed.

**Files changed.** `integrations/abaqus/deck.py`, `results.py`, `interchange.py`, `extract_odb.py`;
`services/readiness.py`; `packages/engineering/model.py` (comments only); `apps/web/src/Viewport.tsx`,
`Workspace.tsx`, `viewportModel.ts`, `viewport.css`, `style.css`, `features/workspace/readiness.ts`,
new `features/workspace/AssemblyDiagnostics.tsx`, `i18n/ja.ts`, `i18n/en.ts`;
`tests/test_two_step.py`, new `apps/web/tests/assembly.spec.ts`, `apps/web/tests/renderer.spec.ts`;
docs updated. No schema/API contract field changed, so `generated.ts` was not regenerated.

**Tests run (this machine, isolated data):** pytest **200 passed, 1 opt-in skipped**; i18n **648
keys** in both dictionaries; encoding pass (40 files); typecheck pass; build release
**`3d43dd8a4e82`** (entry `index-B2yxHlH9.js`, 4 files); Playwright **61 passed** (58 prior + 3 new).

**Supported geometry limits.** The door closes from above (negative travel by schema); a bottom
mount uses the moving-body role. Motion is one vertical translation along Y; oblique X/Y motion, a
profile straddling the seal and an ambiguous contact side are rejected. Clearance is measured along
Y over the shared X range, not as a minimum normal distance. More than two moving rigid profiles and
simultaneous motion are unsupported. A moving body can come from a native DWG (open contours
allowed); the DXF reader still rejects open non-PANEL contours and merges open PANEL contours, so a
DXF-only drawing cannot yet declare a separate body profile.

**Next executable slice.** (1) Run an authorized licensed two-step case on a trusted two-panel
drawing with retained INP/ODB and verify step-1-only body motion, step-2-only door motion, held-DOF
zero displacement, carried-over seal contact and reaction signs; record it under
[engineering-validation.md](docs/engineering-validation.md). (2) Then continue the outstanding
follow-ups below — RunView per-step filtering, missing-history representation and per-pair friction.
(3) If two-panel DXF workflow is required, add a declarable body layer/role to the DXF import.

## Independent release review · 2026-11-22

**Hold software RC sign-off.** The automated regression passed, but fresh checks on disposable data reopened Gates 1 and 4 and identified a silent input error in Gate 3. This review supersedes the RC verdict in implementation report A5.

1. Fix data-root ownership and takeover first. With the two reads synchronized, both callers of `claim_data_root` accepted ownership of one empty directory on different ports. Use an atomic cross-process claim held through worker shutdown, and test two simultaneous launcher processes. A queued mesh also returned an empty `GET /api/jobs` list. Include all job kinds and refuse takeover when activity or process termination is unresolved, including on older APIs.
2. Compare and update the fixture hash in one SQLite write transaction. Two synchronized HTTP PUTs carrying the same reviewed hash and different valid node sets both returned 200. Require one success and one 409, and verify the deck contains the winning selection.
3. Fix blank numeric drafts. In Edge a committed travel of −6.1 mm was cleared, the field stayed blank, and Save revision returned 200 with −6.1 mm. Check the header and stage-specific save buttons, navigation, and Escape.
4. Make release publication recover from an interrupted copy. With only the release index present, retrying the publisher exited 0 and published a manifest pointing to a missing entry script. Stage and verify the complete release before publishing the manifest, and exercise retry on an incomplete directory.

Fresh verification on the current tree yielded 122 Python tests passed and one opt-in skip, 500 translation keys per language, and a passing TypeScript check. The four targeted checks above used temporary data or release trees. The final isolated browser log (`.local/final2/browser3.log` in the implementation checkout) records 41 passes. An earlier attempt recorded a high-DPI selection failure. The checkout and isolated release directories match byte-for-byte for all four files. A read-only health check found port 8765 serving release `ec2cedaa9dfe`, API 3. No live restart or licensed solve was performed during review.

After these fixes, rerun the affected gates in isolation. Supervised operator acceptance, numerical sensitivity and physical correlation remain outstanding under the engineering validation record.

## Phase 0 — release safety repairs · 2026-11-22 (PASS)

All five review findings are repaired on top of `e9ca2c45`. No live instance, live database, artifact
or solver process was touched; the live 8765 instance remained up throughout.

| Item | Repair | Evidence |
|---|---|---|
| P0-1 data-root ownership | New [ownership.py](services/ownership.py): two lifetime OS locks (`owner.lock`, `worker.lock`) via `msvcrt.locking` / `fcntl.flock`, canonical `st_dev:st_ino` identity, re-entrant per-process refcount. `instance.json` is diagnostic only. The launcher holds the owner lock until `worker.wait()`; the worker holds its own lock. An orphaned worker blocks a new launcher; an API may attach to a live worker (the independent workflow). | Two spawned processes synchronized on a barrier: exactly one wins. Crash releases the lock in the kernel. Stale metadata, independent dirs, re-entry, orphan-worker refusal tested. Live smoke: second launcher on 8899 refused with owner PID; second worker exited 2; second API on 8900 refused; killing the owner left the worker lock, relaunch refused, then started after the orphan exited. |
| P0-2 takeover safety | [activity.py](services/activity.py) classifies every durable mode as `active`/`uncertain`/`terminal`; `/api/jobs` returns all five modes plus the classification and an `X-Abaqus-QOL-Jobs: all-modes-v1` coverage header. The launcher refuses when the header is absent (an older empty list is not inactivity), rechecks immediately before stopping, and stops only processes positively identified by module + data directory + start time. | Classifier matrix (queued/preparing/license/running/extraction/cancel/unknown/termination-unconfirmed/terminal), `/api/jobs` mode coverage, empty-without-header refusal, recheck-before-stop, idle takeover. Live: queued MESH showed `active`, then `terminal`; `--status`/reuse unaffected. |
| P0-3 atomic fixture | `store.set_fixture_checked` performs job eligibility, mesh digest, expected-hash comparison and the upsert inside one `BEGIN IMMEDIATE` transaction. | Two synchronized HTTP PUTs with one reviewed hash: one 200 and one 409; stored labels equal the winner; prepared INP `WSFIX` equals the winning nodes; stale hash cannot prepare a deck. |
| P0-4 blank numeric | Blank is invalid; registration is synchronous in the change handler, with a synchronous action guard in `Workspace` for Save/Generate/Prepare/Submit/Fixture/navigation. Escape restores; localized `validation.required`. | Real Edge test: clear committed −6.1 mm, Save disabled and forced click sends no PUT; Escape restores; new −4.2 saves. Also duration, offset, mesh size and section thickness. |
| P0-5 release publication | [publish-release.mjs](apps/web/scripts/publish-release.mjs) stages the whole tree, verifies every referenced file, hashes the complete file manifest, publishes by rename, re-verifies, and writes `dist/release.json` last. An incomplete prior release is quarantined and repaired. [release.py](services/release.py) verifies the schema-2 file list and tree digest. | Interrupted publication (only `index.html`) is repaired on retry; a missing source asset fails non-zero without rewriting the manifest; publishing B leaves A byte-identical; the resolver rejects a release with a missing file; the launcher refuses to serve an invalid release. |

**Phase 0 regression (current tree):** `pytest -q` → **158 passed, 1 skipped**; `test:i18n` → **501
keys**; `typecheck` → pass; isolated build → release `679da84a7cc6` (4 files); isolated Playwright →
**43 passed** (41 prior + 2 blank-numeric). The POSIX `flock` branch is implemented but was not
exercised on this Windows host. Phase 1–5 remain.

## Phase 1 — UI and data-presentation repairs · 2026-11-22 (PASS)

| Item | Repair | Evidence |
|---|---|---|
| 1.1 corrupted characters | Replaced real mojibake (`Â·`, `â€”`) in Dashboard/main; removed literal `?` separators from MeshReview and the `0 ? 5` range hint; added `scripts/check-encoding.mjs` (`npm run test:encoding`, also in CI). | Encoding check passes 35 source files; Edge test asserts rendered dashboard has no `Â·`/`â€”` and keeps a real `·`. |
| 1.2 middle-button pan | `pointerdown` cancels middle-button default, `auxclick` is suppressed, viewport uses `overscroll-behavior: contain`; wheel zoom unchanged. The renderer exposes a camera fingerprint for the test. | Edge test: middle drag changes the camera, `window.scrollY` stays 0, wheel still zooms without scrolling. |
| 1.3 mesh identity hidden | Removed the mesh digest/“mesh identity” rows from Mounting, Mesh, Review and archived-setup UI; contracts, digests, compatibility checks and stale-deck logic unchanged. | Edge test builds a mesh and asserts its digest prefix never appears in the page text. |
| 1.4 components in mesh | Structured rows with display name, role, Included/Excluded/Not-meshed badge, element type(s), count and an explanation; included totals must equal the mesh total; body profiles read as intentionally excluded, not as a failed 0-element mesh. | Edge test checks seal (CPS) and door (R2D2) rows plus included total; Python test asserts a `vehicle_body` is reported in `excluded`, contributes no elements and does not fail the mesh. |
| 1.5 editable names | `Component.alias` (optional display name) added; tree inline rename with Enter/Escape/Save/Cancel, validation, persisted through revisions. The authoritative `name` and CAD/FE IDs are untouched; alias is excluded from mesh identity and panel metadata records `panel_name`. | Python: alias persists, `mesh_compat` unchanged, revision history keeps its own alias, result metadata uses the alias while the panel ID is stable. Edge: rename, cancel, save, reload and selection label. |

**Phase 1 regression:** pytest **161 passed, 1 skipped**; i18n **519 keys**; encoding check pass; typecheck
pass; isolated build release **`91b90ed6d34c`** (entry `index-B8OCW0V9.js`, 4 files); isolated Playwright
**47 passed** (43 prior + 4 Phase 1). No solver executed; live 8765 untouched.

## Phase 2 — global material library · 2026-11-22 (PASS)

| Area | Delivered |
|---|---|
| Data model | Additive SQLite tables `material_library` / `material_versions`; versions are insert-only. A model material snapshot may carry `library_id` + `library_version`; values remain the immutable revision snapshot. No existing revision is rewritten. |
| API | `GET/POST /api/materials`, `GET/PUT /api/materials/{id}`, `duplicate`, `archive`, `restore`, and `POST /api/materials/import`. Import always creates explicit entries and never merges by name; existing pins are returned unchanged. |
| Library UI | New top-level **Materials** page: search, type/version/usage display, add, duplicate, rename, edit, version history, load version, archive/restore, model-usage list, and legacy-card import by model. |
| Comparison | Multi-series measured-only charts for stress vs axial strain and lateral vs axial strain; units, legend, per-version labels, source note and “no fit/extrapolation” limitation. |
| Workspace | Materials stage is assignment-only: assigned-material summary, library picker, newer-version notice and **Adopt vN**; test-data editing, card creation and graph editing moved to the library page. |
| Versioning | Library edits append a version; name-only edits do not. Material-only adoption reuses geometry/mesh (`mesh_compat` unchanged), creates a new model revision and requires a new deck; historical revisions and completed runs are byte-unchanged. |

Tests: `tests/test_material_library.py` (7) covers immutable versions, validation, pins/usage, two models sharing,
adoption + deck value, archive/restore, no name merging, import idempotency, and a completed run remaining unchanged
after library edit/archive. `apps/web/tests/materials.spec.ts` (5) covers the library UI, comparison, paste, workspace
assignment/adoption/mesh reuse/deck and Japanese localization.

**Phase 2 regression:** pytest **168 passed, 1 skipped**; i18n **567 keys**; encoding check pass; typecheck pass;
isolated build release **`7ff922276866`** (entry `index-DWdA_DXy.js`, 4 files); isolated Playwright **49 passed**.
No solver executed; live 8765 untouched.

## Phase 3 — project/model archive and safe deletion · 2026-11-22 (PASS)

| Area | Delivered |
|---|---|
| Lifecycle | Additive `projects.archived` / `groups.archived` tombstones. Default lists hide archived items; `?include_archived=true` shows them. Revision/run/artifact reads still work. |
| Read-only guard | Archived model or group refuses setup saves, imports, meshing, deck preparation, submission and new models in the group (HTTP 409), while historical evidence stays downloadable. The workspace shows a read-only banner. |
| API | `archive`/`restore` for models and groups, `deletion-info` (dependent revisions/jobs/active work/deletable) and explicit `delete` with exact-name confirmation. |
| Permanent deletion | Only for archived targets with no active/uncertain work. One transaction removes fixtures/jobs/revisions/(projects)/group; a journal then removes job directories and drawings that are no longer referenced. Shared drawings (duplicated models) and library materials are preserved. |
| Recovery | `deletions` journal is replayed at startup: a pending journal whose transaction never committed is discarded without deleting artifacts; a committed journal finishes idempotent file cleanup. Filesystem failures leave `cleanup: pending` and retry next start. |
| UI | Dashboard “Show archived”, archive/restore actions, permanent-delete actions only on archived items, descriptive confirm with revision/job counts and a typed-name prompt. |

Tests: `tests/test_archive_delete.py` (8) covers model/group archive+restore, read-only guards, duplicate independence,
active-work refusal, typed confirmation, artifact removal, shared drawing + library survival, interrupted cleanup and
uncommitted-journal recovery. `apps/web/tests/archive.spec.ts` (4) covers dashboard archive/restore, group lifecycle,
typed permanent deletion and the archived read-only workspace.

**Phase 3 regression:** pytest **176 passed, 1 skipped**; i18n **585 keys**; encoding check pass; typecheck pass;
isolated build release **`0f28d5648c35`** (entry `index-CdCPwQht.js`, 4 files); isolated Playwright **53 passed**.
No solver executed; 8765 was not running at this checkpoint and was not touched.

## Phase 4 — two-step body seating / door closing · 2026-11-22

**Gate 4A (license-free deck and integration): PASS. Gate 4B (licensed evidence): BLOCKED — no licensed
solve was run or authorized in this pass.**

| Area | Delivered |
|---|---|
| Model | `analysis.mode` (`door_only` default, `body_then_door`) and `motion.body` (`offset`, signed `travel`, `duration`). Two-step requires exactly one door, exactly one body, a non-zero body travel and a seal region. Legacy revisions default to `door_only` and keep their exact deck behaviour. |
| Mesh | In two-step mode the moving body edges are meshed as R2D2 and included; door-only keeps the body reviewed-but-excluded. Mesh identity adds the mode only for two-step, so every historical door-only digest stays valid. |
| Deck | New `write_two_step_inp`: separate WS/PANEL/BODY parts and instances, two reference points, two rigid-body constraints, two contact-participating rigid surfaces, explicit `Body seating` then `Closing` steps, body held during step 2, door held during step 1, WSFIX throughout, propagated BCs (no `op=NEW`), and U/RF history for both RPs in both steps. |
| Results | Metadata records ordered steps, both references, body placement/clearance and a body motion block. Extraction picks the reference that owns each step and projects along its direction; two-step history CSV gains a `role` column; the results page has a curve-step selector and body-specific axis labels. Legacy single-step results are unchanged. |
| UI | Motion stage mode selector and body offset/travel/duration; Review shows the step sequence and body motion; Mesh review includes the body in two-step mode. Manufactured playback refuses two-step rather than fabricating body contact evidence. |

Tests: `tests/test_two_step.py` (8) covers body R2D2 inclusion, exact two-step INP order/BCs/parts/rigid bodies/history,
metadata references, legacy deck regression, mode-sensitive mesh identity, validation, per-motion projection and the
manufactured-playback refusal. `apps/web/tests/two-step.spec.ts` covers the mode UI and the missing-body rejection.
The result step selector is implemented but its two-step browser path needs a licensed result; it is not claimed as
replay-verified.

**Phase 4 regression:** pytest **184 passed, 1 skipped**; i18n **605 keys**; encoding check pass; typecheck pass;
isolated build release **`ce9798f0a74f`** (entry `index-m-wVVrsa.js`, 4 files); isolated Playwright **54 passed**.
No solver executed; no ODB/INP/history evidence modified.

## Phase 5 — real-time run diagnostics · 2026-11-22 (PASS)

| Area | Delivered |
|---|---|
| Progress source | `features/run/progress.ts` derives progress from solver-reported `step_time` and the configured step durations of the job's **own revision**. Simulated-time fraction only; no wall-clock percentage and no ETA. |
| Determinate states | Queued → 0%; active step → fraction of current/total configured time (capped at 99%); solver succeeded + extraction succeeded → 100%. Solver succeeded with extraction queued/running/failed → 99%, explicitly “not 100%”. Unknown step, license wait, missing step time or unknown state → indeterminate. |
| Multi-step | The panel lists Body seating and Closing with pending/active/complete states; the active step follows the solver-reported step name (case-insensitive). Legacy runs show a single Closing step. |
| Status surface | Top-of-page card shows phase, status badge, progress bar (`role=progressbar` with `aria-valuenow` only when valid), solver and extraction separately, current increment, simulated step time and last update. |
| Warnings | License wait, stale heartbeat (30 s threshold, re-evaluated every 5 s), awaiting extraction and extraction failure have distinct notices; the diagnostic offers a link to its source log. Logs and downloads remain below. |
| Lifecycle | Polling keeps the existing active/idle cadence; the progress clock and revision fetch abort/clean up on navigation. |

Test: `apps/web/tests/progress.spec.ts` (4) uses mocked job/revision responses (clearly not solver evidence) to assert step 1 and step 2 percentages, 99 vs 100, license wait, unknown step, 0% queued, stale heartbeat, failed extraction and the absence of an ETA.

**Phase 5 regression:** pytest **184 passed, 1 skipped** (backend unchanged this phase); i18n **619 keys**; encoding check pass; typecheck pass; isolated build release **`5cac5e2a1e92`** (entry `index-BcID6OYd.js`, 4 files); isolated Playwright **58 passed**.
No solver executed; diagnostics tests use mocked state, not a live solve.

**Snapshot - 2026-11-22 (release-safety pass).** The local branch is `main`; the checkout was clean at
`9df297f` (one commit after `d7b6728`), which already contains the repairs the previous audit saw as
uncommitted. Those commits are preserved. This pass added the release/compatibility, atomic-creation,
data-root ownership, readiness and numeric/paste repairs described below. No new solver process was
launched and no license was consumed; the retained licensed run was not modified.

**Delivered in the release-safety pass (2026-11-22, on top of `9df297f`):**

- **Matched releases.** `npm run build` publishes `apps/web/releases/<content-id>/` plus
  `apps/web/dist/release.json`; the API resolves the manifest once and mounts only that directory.
  `/api/health` reports `release`, `frontend`, `api` (3) and `data`. A rebuild publishes a new
  directory and cannot change the files a running instance serves (verified: A stayed on
  `ba3873ae2788` / `index-Nu0v-nbm.js`, served it 200 and the new asset 404; B served
  `3f88561050cf` / `index-CAOdvt4j.js`).
- **Compatibility gate.** A tab compares its loaded entry and API generation with `/api/health`;
  a mismatch shows one localized recovery message and disables creation, import, deck preparation
  and submission. Identified writes from a stale tab/release/API are refused with 409; unidentified
  scripts keep the old contract. `apps/web/src/Compatibility.tsx`, `compatibility.ts`.
- **Atomic project creation.** `POST /api/project-groups` creates the group, project and first model
  in one SQLite transaction keyed by a client token; a repeat after a lost response returns the
  original pair and a failure leaves no group. The dashboard retries with the same token. Legacy
  `/api/groups` and `/api/projects` remain.
- **Startup ownership.** One `instance.json` owner per data directory; a second API/worker on the same
  `SEAL_DATA` is refused with PID/port before claiming work. `--takeover` refuses when the running
  job list cannot be read; a booting launcher's lock is joined rather than stolen; the startup job view
  uses the lightweight `/api/jobs` with a `/api/runs` fallback.
- **Readiness contract.** `GET /api/revisions/{rid}/readiness` returns stable reason codes with stage,
  action, severity and artifact; the workspace header shows the first blocker with a link to its stage.
  Rows cover drawing, roles, materials, mesh attempts, mounting, motion, deck staleness, running/failed
  run and historical revisions. Keys are localized in both dictionaries.
- **Fixture/deck concurrency.** `PUT /api/meshes/{id}/fixture` accepts `expected_hash`; a stale tab is
  rejected (409) without mutation. `POST /api/decks` accepts the reviewed `fixture_hash`; a changed
  fixture is rejected before enqueueing. Both are backward compatible when the fields are omitted.
- **Numeric and paste integrity.** Invalid numeric drafts stay visible, block Save/Generate/Prepare/
  Submit and block step navigation; Escape restores the saved value. Laboratory paste is parsed into a
  preview with header/blank-line support, source row numbers, rejected-row reasons, blocked Apply and
  an unchanged card on cancel/invalid paste.
- **Playback axes.** A sign mirror now refits an automatic axis and mirrors a deliberately zoomed
  interval; reversing twice restores the range. Verified in a real WebGL browser against actual Plotly
  axis limits.
- **Dashboard identity.** Separate project and model filters; run rows carry group, model, dimension,
  revision, short run ID and a seconds-precision timestamp.

**Earlier delivered in this branch** (details and gate table in the
[implementation report](docs/implementation-report.md#a4-repair-delivery--drawing-ownership-review-authority-playback-abaqus-only-execution)):

- New models are explicitly empty (`source.kind = "empty"`), open at Import, and never seed geometry.
  The public example is opt-in. Empty models save, rename, duplicate and reopen; mesh/deck/run reject
  them with a specific message.
- Navigation no longer substitutes `projects[0]` or `ps[0]`. The Workspace button restores the last
  explicitly opened model; invalid links name the revision and offer Back to Projects. Save/import
  update the history entry and the router, and the remembered stage survives the remount.
- Imports are bound to the model, base revision, job and source digest; a same-named drawing in
  another model is independent. Dimension (including a 3D preview) and model-level settings survive an
  import. A failed import leaves the last good drawing and head untouched.
- Review cannot generate or regenerate a mesh. Mesh owns regeneration, with an explicit
  Regenerate/Cancel choice and an affected-node count. A just-queued deck becomes authoritative before
  submission. Historical replay resolves the deck's own mesh and verifies the digest chain.
- Renderer actors are keyed by instance/entity/component/kind and reused only when cell topology and
  rendering class match. Run-wide camera bounds and per-quantity colour ranges are recorded by
  extraction or derived into a cache for retained results.
- Playback keeps requested and displayed frames separate, waits for the displayed frame before
  advancing, survives out-of-order responses, and updates the Plotly cursor without purging or
  resetting the reader's zoom.
- New execution is Abaqus-only. Explicit DEMO returns 422 and queues nothing; queued legacy DEMO jobs
  are retired with a diagnostic; historical DEMO evidence stays readable.
- The launcher lock is per port, so a custom-port launch no longer joins the default instance.

**Workflow order is** `Import -> Components -> Materials -> Mesh -> Mounting -> Contact -> Motion ->
Review / Run -> Results`, with ids in [stages.ts](apps/web/src/features/workspace/stages.ts). Mesh,
Mounting and Contact are independent stages; the language control is one button.

**Mesh fidelity on the private drawing is fixed and measured**: outer WS 0.30747 -> 0.01549 mm,
cavity 0.11288 -> 0.01974 mm, door 0.01423 mm, fit points beyond 0.02 mm 10/21 -> 0/21. The refined
mesh ran licensed as `d0d409c2-6fc9-4e69-95a1-c75069075d68` (door-only, completed, contact at 5.70 mm,
+0.016966 N projected).

**Open:** in-viewport drawing-role review, **licensed** body-first/door-second two-panel validation,
per-pair friction, and 3D solving. Human uncoached usability acceptance (Gate 7) was **not run**; the
task sheet is in the implementation report. Physical qualification remains **blocked** on a trusted
reference curve and an agreed tolerance. The release-safety gate table is in
[docs/implementation-report.md](docs/implementation-report.md) (section A5).

**Two acceptance commands.**

```powershell
.\.venv\Scripts\python.exe scripts\acceptance_dwg.py
```
Native read -> import -> roles -> mesh -> fixture -> deck on `examples/hollow-section_2.dwg`; zero
solver tokens; evidence in `.local/dwg-acceptance/`; exits non-zero on any failed check.

```powershell
$env:SIMPLIFY_ABAQUS_LAUNCHER = "C:\SIMULIA\Commands\abq2024.bat"; .\.venv\Scripts\python.exe scripts\acceptance_dwg.py --licensed --travel -6.5 --evidence .local\dwg-acceptance-contact2
```
Licensed door-only acceptance run; ODB, extraction and history land in `.local/dwg-acceptance-contact2/`.

## Baseline to preserve

| Brief item | Current state |
|---|---|
| 1 · Startup and logo | The existing CMD bootstraps local dependencies, starts the worker and API, checks application health and opens the browser. The header imports the supplied PNG. The report records repeat-launch and occupied-port checks. Cold concurrent startup still has a race described below. |
| 2 · Project grouping | `groups` owns model histories through `projects.group_id`. Creation, sibling duplication, revision browsing, additive migration and legacy links exist. The existing [group migration tests](tests/test_grouping.py) and [browser tests](apps/web/tests/groups.spec.ts) are regression assets. |
| 8 · Door curve | The shipped negative-Y, single-step door template requests U1/U2/RF1/RF2. A displayed-curve transform supports reversing either sign, with a separate raw artifact download. Keep the existing displacement contours, signed probes and legacy U2/RF2 interpretation. Multi-panel, missing-history and CSV caveats are below. |
| 5 · Mesh-first fixture | `POST /api/meshes` and `POST /api/decks` are separate durable operations. The worker records `mesh.json`'s digest and the mesh-compatibility digest; `PUT /api/meshes/{id}/fixture` stores validated `WS-1:n` labels bound to that digest. The viewport has a rectangular node-selection mode, and the deck writer writes `WSFIX` from exactly the saved set. Tests: [fixture API tests](tests/test_fixture.py), [fixture browser tests](apps/web/tests/fixture.spec.ts). |
| 9 · Verification | The [delivery report](docs/implementation-report.md) records historical counts from earlier passes. Current totals after the 2026-11-22 repair: 105 Python tests passed, one opt-in test skipped, 33 browser tests passed, 463 translation keys checked, typecheck and build passed. |
| · Native DWG import | [dwg.py](packages/engineering/dwg.py) maps an ACadSharp inventory onto the canonical model; [section.py](packages/engineering/section.py) is the assembler both readers share; [integrations/dwg](integrations/dwg) holds the prebuilt helper and its runner. `POST /api/projects/{id}/drawing` accepts `.dwg` with no converter configured. Tests: [tests/test_dwg.py](tests/test_dwg.py). |
| · Fixture correctness and splines | `store.active_mesh` makes the newest compatible mesh authoritative for both deck preparation and submission; `jobs.fixture_labels` snapshots the label set at queue time; a run requires the deck's mesh to be active and the deck to be the newest for that revision; a locked setup replays `locked.fixture_labels`. `SPLINE` is imported as canonical NURBS ([spline.py](packages/engineering/spline.py)), tessellated within a declared chord tolerance, meshed exactly with `occ.addBSpline` where OCC accepts it, and included in the mesh-compatibility digest. Tests: [spline tests](tests/test_spline.py), [fixture API tests](tests/test_fixture.py), [fixture browser tests](apps/web/tests/fixture.spec.ts). |

**Licensed regression anchors.** Synthetic runs `39f696ee-c757-44ba-bb42-9e8f9671bfe6` (13-node edge
fixture, `RF2` −0.33351448 N) and `54b7be8c-d260-4a65-adcf-0205263032f3` (18-node box-selected patch,
`RF2` −0.33796954 N, mesh digest `59d98e16…`, deck SHA-256 `b68b7d84…`). On the reviewed machine their
retained artifacts are under `.local/licensed-evidence/<run-id>/`, which is ignored and may be absent
on another machine. The fixture patch changes the force curve, so neither value is a pass threshold.

## Remaining implementation and acceptance

1. ~~**Mesh and fixture identity (brief 5).**~~ **Delivered.** Independent `MESH` and `DECK` worker
   operations, an immutable mesh digest plus a mesh-compatibility digest, rectangular
   replace/add/subtract/clear selection on visible eligible WS nodes with count and highlighting,
   instance-qualified labels stored against the exact mesh, and server-side rejection of stale decks,
   forged or cross-mesh labels, and direct API bypass. Historical runs and old `BUILD` artifacts still
   open; a mesh change forces fixture review even when labels recur. The legacy edge fixture can be
   resolved, inspected and saved.
2. **Confirm drawing roles before building regions (brief 3).** [DXF import](packages/engineering/dxf.py) currently buckets layers `PANEL` and `MOVING_PANEL` into one panel and polygonizes the rest. Ordinary-layer open profiles can fail before the user can assign roles. Introduce staged analytic linework review and explicit connected-profile selection for door/INR, optional body and WS. Reuse existing hole detection, cavity fill, intersections and source metadata. **Accept when** two open panel profiles and a nested WS share a generic layer and the user can identify both panels, confirm material/void loops and generate the section. Cover open polyline handling and ambiguous inputs. The [ODA adapter](integrations/drawings.py) exists; genuine DWG conversion needs an installed converter and suitable nonconfidential DWG. DXF implementation can proceed now. The requested public ESI workflow comparison still needs a source-backed note.
3. **Partition a WS face (brief 4).** The material-card editor and assignment to existing faces already work. Add a validated preview/commit line cut on authoritative CAD with a base-revision check; preserve the [generic topology guard](services/api/main.py). Preserve holes and unaffected assignments, return child faces sharing a single interface, and review affected edge assignments. **Accept when** a browser-drawn partition receives sponge and solid materials, a Gmsh mesh has shared interface nodes and the cavity stays empty. Test missed, tangent, cavity-crossing and sliver cuts, including non-destructive rejection.
4. **Role-aware motion and two steps (brief 6).** **Implementation delivered 2026-11-22** (see the
   top section): independent direction, distance, initial placement, RP identity and contact
   orientation for the door and the body, including a body mounted below the seal. Still open: the
   **licensed** acceptance — a two-panel case that reaches contact and an ODB trajectory that
   independently demonstrates all moved and held DOFs at both step boundaries. Oblique X/Y motion
   remains unsupported.
5. **Friction on contact pairs (brief 7).** The model and writer currently use one global coefficient. Map selected exterior WS CAD edges to actual element sides and their opposing panel surface. Support a default plus explicit overrides, retain eligible self-contact, and diagnose conflicting overlaps or internal bonded edges. **Accept when** two patches at 0.3 and 0.7 survive a compatible edit, the deck names the expected sides/opponents, and a licensed case with tangential travel exercises the assignments. A normal-only closing curve cannot establish friction sensitivity.
6. **Validation completion (brief 9).** Exercise the full workflow through the browser, worker and licensed extractor. Retain run IDs, exact mesh/deck hashes, step-local and cumulative times, projected and signed global data, and measured checks. Perform mesh and time/ramp sensitivity runs. Physical correlation additionally needs a trusted reference with matched geometry, material, loading and agreed tolerances. 3D grouping and extrusion preview remain available; 3D solving follows validated 2D.

## Follow-ups in delivered paths

| Priority and location | Evidence, impact and regression check |
|---|---|
| ~~High · [raw history writer](integrations/abaqus/interchange.py)~~ | **Fixed.** `panel_RF2_N` and `panel_total_RF2_N` now carry the signed global `RF2`; the projected total has its own `closing_total_force_N` column. Covered by `tests/test_abaqus.py::test_demo_csv_keeps_signed_rf2_and_separates_the_projected_total`. Original historical files are untouched. |
| High · [history alignment](integrations/abaqus/interchange.py) and [results view](apps/web/src/RunView.tsx) | **Partly fixed.** The projection now requires only the components the direction uses (an X-only direction no longer needs U2/RF2), and an empty history no longer crashes sample matching. Still to do: represent genuinely missing raw components as unavailable rather than `0.0`, require a common step-start sample for the origin, and add cases for partial components and mismatched time domains. |
| Before two-step delivery · [RunView](apps/web/src/RunView.tsx) | The default step comes from `steps[0]` and plot/export iterate the entire history. Select the door step by role and filter by panel and step before plotting, exporting and frame matching. Avoid crossing steps on identical cumulative timestamps. The existing [curve test](apps/web/tests/curve.spec.ts) checks plain and both-flipped output. Add X-only, Y-only, equal-time boundary and legacy cases; compare CSV columns according to their header names. |
| Startup reliability · [Python launcher](scripts/serve.py) and [CMD wrapper](start-abaqus-qol.cmd) | **Lock fixed 2026-11-22:** one lock per port (`<repo>/.local/serve-<port>.lock`) records the requested port, so a custom-port launch starts its own instance. A healthy same-port instance is still reused; a stale lock is taken over. Verified with `start-abaqus-qol.cmd --port 8897 --no-browser` on isolated data (health ready, build/frontend matched `dist`, empty project list). Remaining: simultaneous cold-launch stress and the CMD wrapper's `%ERRORLEVEL%` propagation inside parenthesized blocks. |
| Group creation recovery · [dashboard](apps/web/src/Dashboard.tsx) | Group and first model are created by two HTTP requests. A failed second request leaves a group and a retry can create another. Test a mid-operation failure and offer atomic creation or an idempotent resume path using the original group. |

## Handover verification

Use the [repository instructions](AGENTS.md) for normal commands and the [recovery guide](docs/migration-and-recovery.md) before investigating an unknown worker. Preserve the current licensed door-only runs as regression comparisons. Use an isolated data directory for new cases. For each completed slice, record the new API/schema behavior, historical compatibility, browser action exercised, test results, and any licensed run ID in the [implementation report](docs/implementation-report.md) and [validation record](docs/engineering-validation.md).

Last verified on this machine (2026-11-22, current checkout, isolated test data):
`python -m pytest -q` → **200 passed, 1 skipped**; `test:i18n` → **648 keys** in both dictionaries;
`test:encoding` → pass (40 source files); `typecheck` → pass; `build` → release
**`3d43dd8a4e82`**, entry `index-B2yxHlH9.js`, API 3, 4 files; `playwright test` → **61 passed**
(isolated `--test-data` server on 8876, live 8765 untouched). No new solver process was launched and
no license was consumed.
Generated contract hash matches the checkout (`4D376FBB…`). Earlier isolated instances on 8898/8899
exercised release pinning and data-root refusal, and a second API on one data directory was refused
with the owner's PID. No new solver process was launched and no license was consumed. The retained licensed run
`989fec4a-98fa-4a61-999a-e16ec886ac68` was not modified in this pass; its earlier replay (66 frames,
final 1.300 s, travel 6.5 mm, signed `RF2` −0.0169664863 N) remains the record. The earlier licensed
runs `54b7be8c-d260-4a65-adcf-0205263032f3` and `39f696ee-c757-44ba-bb42-9e8f9671bfe6` remain the
fixture regression anchors.
