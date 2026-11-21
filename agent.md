# Abaqus QOL implementation handoff

**Snapshot - 2026-11-21 (fifth pass, release candidate).** The local branch reference was `main` at
`b250789`. Commits `dabffe3` (fixture correctness + splines), `b1c3db6` (native DWG) and the current
release candidate carry the work. Preserve them when resuming.

**Workflow order is now** `Import -> Components -> Materials -> Mesh -> Mounting -> Contact -> Motion ->
Review / Run -> Results`, with ids in [stages.ts](apps/web/src/features/workspace/stages.ts). Mesh,
Mounting and Contact are independent stages; the language control is one button.

**Mesh fidelity on the private drawing is fixed and measured**: outer WS 0.30747 -> 0.01549 mm,
cavity 0.11288 -> 0.01974 mm, door 0.01423 mm, fit points beyond 0.02 mm 10/21 -> 0/21. The refined
mesh ran licensed as `d0d409c2-6fc9-4e69-95a1-c75069075d68` (door-only, completed, contact at 5.70 mm,
+0.016966 N projected).

**Open:** in-viewport drawing-role review, body-first/door-second two-panel analysis, the historical
view pairing a run's own mesh with its labels, duplication mesh verification, and the API-restart and
double-click-startup gates. See the gate table in the implementation report (section A3).

**Two acceptance commands.**

```powershell
.\venv\Scripts\python.exe scripts\acceptance_dwg.py
```
Native read -> import -> roles -> mesh -> fixture -> deck on `examples/hollow-section_2.dwg`; zero
solver tokens; evidence in `.local/dwg-acceptance/`; exits non-zero on any failed check.

```powershell
$env:SIMPLIFY_ABAQUS_LAUNCHER = "C:\SIMULIA\Commands\abq2024.bat"; .\venv\Scripts\python.exe scripts\acceptance_dwg.py --licensed --travel -6.5 --evidence .local\dwg-acceptance-contact2
```
Licensed door-only acceptance run; ODB, extraction and history land in `.local/dwg-acceptance-contact2/`.

## Baseline to preserve

| Brief item | Current state |
|---|---|
| 1 · Startup and logo | The existing CMD bootstraps local dependencies, starts the worker and API, checks application health and opens the browser. The header imports the supplied PNG. The report records repeat-launch and occupied-port checks. Cold concurrent startup still has a race described below. |
| 2 · Project grouping | `groups` owns model histories through `projects.group_id`. Creation, sibling duplication, revision browsing, additive migration and legacy links exist. The existing [group migration tests](tests/test_grouping.py) and [browser tests](apps/web/tests/groups.spec.ts) are regression assets. |
| 8 · Door curve | The shipped negative-Y, single-step door template requests U1/U2/RF1/RF2. A displayed-curve transform supports reversing either sign, with a separate raw artifact download. Keep the existing displacement contours, signed probes and legacy U2/RF2 interpretation. Multi-panel, missing-history and CSV caveats are below. |
| 5 · Mesh-first fixture | `POST /api/meshes` and `POST /api/decks` are separate durable operations. The worker records `mesh.json`'s digest and the mesh-compatibility digest; `PUT /api/meshes/{id}/fixture` stores validated `WS-1:n` labels bound to that digest. The viewport has a rectangular node-selection mode, and the deck writer writes `WSFIX` from exactly the saved set. Tests: [fixture API tests](tests/test_fixture.py), [fixture browser tests](apps/web/tests/fixture.spec.ts). |
| 9 · Verification | The [delivery report](docs/implementation-report.md) records 54 Python tests passed, one opt-in test skipped, 19 browser tests passed, 391 translation keys checked, typecheck and build passed. These are historical counts; the current totals are 81 Python tests, 22 browser tests and 422 keys (sections A1 and A2). |
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
| Startup reliability · [Python launcher](scripts/serve.py) and [CMD wrapper](start-abaqus-qol.cmd) | The lock records the default port even for a custom launch and removes an existing lock when health is still unavailable. A second process can claim it during a healthy first startup. Dependency preparation also precedes lock acquisition. Exercise simultaneous cold launches and owner-specific cleanup on default/custom ports. The CMD wrapper uses `%ERRORLEVEL%` inside parenthesized blocks; check that a failing child status propagates and its message remains visible after double-click. |
| Group creation recovery · [dashboard](apps/web/src/Dashboard.tsx) | Group and first model are created by two HTTP requests. A failed second request leaves a group and a retry can create another. Test a mid-operation failure and offer atomic creation or an idempotent resume path using the original group. |

## Handover verification

Use the [repository instructions](AGENTS.md) for normal commands and the [recovery guide](docs/migration-and-recovery.md) before investigating an unknown worker. Preserve the current licensed door-only runs as regression comparisons. Use an isolated data directory for new cases. For each completed slice, record the new API/schema behavior, historical compatibility, browser action exercised, test results, and any licensed run ID in the [implementation report](docs/implementation-report.md) and [validation record](docs/engineering-validation.md).

Last verified on this machine: `python -m pytest tests -q` → 75 passed, 1 skipped; `node scripts/check-translations.mjs` → 422 keys; `typecheck` and `build` → pass; `playwright test` → 22 passed; one licensed Abaqus/Standard 2024 case through the mesh → fixture → deck path → solver and extraction succeeded (run `54b7be8c-d260-4a65-adcf-0205263032f3`), and its ODB was re-extracted with the current extractor into `.local/licensed-evidence/54b7be8c-reextract/` so both result files carry the 18 fixture labels.
