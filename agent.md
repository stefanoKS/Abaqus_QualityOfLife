# Abaqus QOL implementation handoff

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

**Open:** in-viewport drawing-role review, body-first/door-second two-panel analysis, per-pair
friction, and 3D solving. Human uncoached usability acceptance (Gate 7) was **not run**; the task
sheet is in the implementation report. Physical qualification remains **blocked** on a trusted
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
4. **Role-aware motion and two steps (brief 6).** The [schema](packages/engineering/model.py) contains a vehicle-body role, but the [mesher](packages/engineering/mesh.py), [viewport](apps/web/src/viewportModel.ts), [writer](integrations/abaqus/deck.py), [metadata/DEMO adapter](integrations/abaqus/results.py) and [extractor](integrations/abaqus/extract_odb.py) assume one rigid panel/reference. Implement independent direction, distance, initial placement and RP identity. Door alone closes in one step. With two panels, move the body first with the door held; hold the attained body position while the door moves in step two. Hold the same selected WS nodes throughout, retaining installed stresses/deformation/contact. Generalize direction-dependent clearance and rigid-side orientation. **Accept when** licensed oblique and two-panel cases reach contact and ODB trajectories independently demonstrate all moved and held DOFs at both step boundaries.
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

Last verified on this machine (2026-11-22, isolated root `I:\GithubProjects\Abaqus_QOL_impl`):
`python -m pytest -q` → **184 passed, 1 skipped**; `test:i18n` → **619 keys** in both dictionaries;
`test:encoding` → pass (39 source files); `typecheck` → pass; `build` → release
**`5cac5e2a1e92`**, entry `index-BcID6OYd.js`, API 3, 4 files; `playwright test` → **58 passed**.
Generated contract hash matches the checkout (`4D376FBB…`). Earlier isolated instances on 8898/8899
exercised release pinning and data-root refusal, and a second API on one data directory was refused
with the owner's PID. No new solver process was launched and no license was consumed. The retained licensed run
`989fec4a-98fa-4a61-999a-e16ec886ac68` was not modified in this pass; its earlier replay (66 frames,
final 1.300 s, travel 6.5 mm, signed `RF2` −0.0169664863 N) remains the record. The earlier licensed
runs `54b7be8c-d260-4a65-adcf-0205263032f3` and `39f696ee-c757-44ba-bb42-9e8f9671bfe6` remain the
fixture regression anchors.
