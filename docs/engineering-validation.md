# Engineering validation

## Force-axis replay of retained licensed run 76b20d84 · 2026-11-24 (no solver launch)

The oblique two-panel run recorded below was replayed through the built UI from a **copy** of its
retained artifacts. No Abaqus license was checked out, no solver process was started and the original
artifacts were not modified. This check answers only whether the viewer plots and exports the stored
measured components on the selected step's own projection axis.

| Item | Closing | Body seating |
|---|---|---|
| Role / instance / RP label | door / `PANEL-1` / 275 | body / `BODY-1` / 322 |
| Direction d (global XY) | (0.6, −0.8), −53.1301° | (0, 1), 90° |
| Final signed raw RF (N) | (0.0130300671, −0.0774725974) | (−2.0×10⁻¹³, 1178.3289795) |
| Final dot product RF·d (N) | 0.0697961181 | 1178.3289795 |
| Reporting basis | total width, W = 100 mm, t = 1 mm | same |
| Final displayed force (N) | **6.979611814** | **117832.8979** |
| Plot samples checked | 31 | 21 |
| Max absolute plotted-vs-independent difference | 0 | 0 |
| Max absolute exported-row-vs-trace difference | 4.68×10⁻¹² | 2.19×10⁻⁷ |

The exported second row was read from the two-row CSV download after switching the **Curve step**
selector. The independent arithmetic used the stored `rf1`/`rf2` and the step direction, multiplied
once by W/t. Reverse Y was off for these readings.

**Limits.** This is agreement between the stored measured components, the plotted trace and the exported
row for one retained run. It is not a new solve, not a mesh/time sensitivity study and not physical
correlation. The very large body-seating value is the run's recorded reaction under the represented
100 mm width, not an independently validated contact force.

## Second UI and 2D engineering pass — licensed execution · 2026-11-24

Three small disposable synthetic cases were run through the normal API -> worker -> Abaqus 2024 solver ->
Abaqus-Python extractor path on this machine, under an isolated `SEAL_DATA`
(`.local/phase2-licensed/data`). License checkout succeeded (5 tokens from the local Flexnet server).
Artifacts were retained under `.local/phase2-licensed/`; they are not committed. No operator project,
retained licensed run or original drawing was modified.

**These are execution and extraction results, not physical validation.** All three runs completed with
repeated contact penetration-error and cut-back warnings. They do not establish mesh/time sensitivity,
contact onset accuracy or agreement with an independent reference.

### Case 1 — vertical door-only reference (t = 1 mm, W = 100 mm, stroke 2.5 mm at −90°, 0.5 s)

| Item | Value |
|---|---|
| Run | `b3859d0a-606f-4685-93bb-ba199e2d4d96` |
| Solver / extraction | Succeeded / Succeeded (Completed) |
| Mesh digest | `5a3bfaa14c54f97c3a9ffb3c345fcfda8e5ca8fe84b3cc9f8063151be0d68bad` |
| Input deck SHA-256 | `59a7bb66c7360de7a8e062baa0b0f4fed66a219a825701b91a123dab7c1ec768` |
| Frames / aligned samples | 26 / 26 |
| Final measured RP | U1 = 0.0, U2 = −2.5 mm; RF1 = 0.0001033 N, RF2 = −0.0122732 N |
| Projection | (RF·d) = +0.0122732 N at d = (0,−1) |
| Displayed total | 0.0122732 × 100 / 1 = **1.2273 N** (matches `history.csv` `force`) |
| Thickness / width / basis | 1.0 mm / 100.0 mm / `total_width` |
| Contact | named pairs, door 0.7 / body 0.7 / self 0.7 |

### Case 2 — oblique two-panel with distinct coefficients

Door stroke 5.0 mm at −53.130102° → Δ = (3,−4) mm over 0.6 s; body stroke 2.0 mm at +90° → Δ = (0,2) mm
over 0.4 s; μ door 0.17, body 0.43, self 0.81.

| Item | Value |
|---|---|
| Run | `76b20d84-dc96-4d24-8059-85ed8a3942ad` |
| Solver / extraction | Succeeded / Succeeded (Completed) |
| Mesh digest | `c3a80d49512a03bce4a43e6e1bf59bf78b34362502993849db11aeadb6910282` |
| Input deck SHA-256 | `83093f33d9b095665f41938b674242bc576c86217fb32e9c891c4d4ce75c32b4` |
| Frames / aligned samples | 52 / 52 |
| Body seating final | U = (0, 2.0) mm; RF2 = 1178.329 N; projected total 117832.9 N at W = 100 |
| Closing final | U = (3.0, −4.0) mm; RF = (0.013030, −0.077473) N |
| Closing projection | 0.6(0.013030) + (−0.8)(−0.077473) = 0.069796 N → **6.9796 N** total |
| Metadata | two steps, directions (0,1) and (0.6,−0.8), Δ (0,2)/(3,−4); μ 0.17/0.43/0.81; W = 100; t = 1 |
| Contact evidence | `.msg` reports contact points changing open→closed in both steps; the datacheck names the three surface interactions and property assignments |

The body-seating reaction is very large (1178 N raw at 2 mm into the seal) and is reported as a numerical
observation, not a validated physical magnitude.

### Case 3 — bonded partition, two child materials, then solve

Synthetic foot cut at x = 0 from (0,0) to (0,3.2); children assigned `base_rubber` and `bulb_foam`;
default door closing 10 mm.

| Item | Value |
|---|---|
| Run | `bbe7a44c-773d-4fe6-8973-6b8f90860caf` |
| Solver / extraction | Succeeded / Succeeded (Completed) |
| Input deck SHA-256 | `3ef78cf39268e83e4da348c7e0e2066eb12b91c41e6254c563386f409f6047b8` |
| Children / areas | `p09bfe93481f1`, `p09bfe93481f2`; 28.8 / 28.8 mm² |
| Sections in INP | 3 (`REGION_1`..`REGION_3`) with both child materials |
| Interface | 9 shared mesh nodes between the two children; no internal seam side in `SEAL_EXTERIOR` |
| Frames / samples | 51 / 51; final U2 = −10.0 mm, total force 1264.84 N at W = 100 |
| Contact | door ↔ seal and seal ↔ self (no body); 0.7 each |

### What these runs do not establish

- **Self-contact participation — BLOCKED.** No measured pressure/slip evidence shows the seal touching
  itself. The self pair is declared and accepted by the input processor, but no claim of occurrence is made.
- **Numerical sensitivity — BLOCKED.** No mesh or time/ramp refinement was run.
- **Physical correlation — BLOCKED.** No independent reference measurements or agreed tolerances exist.
- **Convergence quality.** The message files show recurring “penetration error too large compared with the
  displacement increment”, displacement-correction and cut-back warnings. A Completed status alone is not
  convergence-quality evidence.
- A first vertical attempt (`c7a7e2e9-…`) solved but failed extraction because the metadata version had been
  bumped; that defect was fixed (version restored to 1 for the installed extractor) and the case re-ran.
  The failed artifacts were kept under `.local/phase2-licensed/vertical-odb-failed-extraction/`.

## UI redesign, direct deletion and seal partitioning · 2026-11-23

This slice changed the browser/API workflow and added a CAD material partition. **No licensed solver
was launched, no license was consumed and no retained ODB/INP/history was modified.** The four
engineering outcomes stay separate:

| Outcome | State |
|---|---|
| Software behaviour | Exercised by pytest domain/API/mesh/deck tests and the isolated browser harness (`--test-data` launcher double). A partition of the synthetic foot at x = 0 produces two bonded children that share one conforming interface node set, one `*Solid Section` per region, and an internal seam absent from `SEAL_EXTERIOR`; both door-only and two-step deck writers were inspected. |
| Licensed execution of the partition | **Not performed.** The partition feature has no licensed ODB, reference run ID or extraction evidence. The manufactured launcher double is not solver evidence. |
| Extraction/ODB agreement | Not revalidated in this slice. The retained moving-body, held-body and neo-Hookean runs were not replayed read-only here. |
| Numerical sensitivity (mesh/time) | Not studied for the partition children. A topology change necessarily produces a new mesh; no convergence comparison was executed. |
| Physical correlation | **BLOCKED** — still no independent reference measurements and no agreed tolerance. A converged run or a shared-interface mesh cannot establish physical accuracy. |

Partition material cards are inherited from the parent. The deck records the same section thickness for
both children and the unit system N-mm-s-tonne; the internal cut is a bonded interface, not a contact
surface. Prior licensed runs predate the partition feature and remain comparisons only.

## New default under verification · 2026-11-23

New models prescribe door U2 = −10 mm (Y-positive upward); this is not a gap
measurement or a safe-compression limit. Earlier licensed cases and their
recorded commands remain unchanged. No licensed solve or independent physical
correlation of the new default was performed in this repair.

Read-only `Get-FileHash -Algorithm SHA256` checks of the retained moving-body
5 mm-gap, held-body and neo-Hookean input decks matched the three hashes in the
records below. This checks file integrity only; the ODBs, revision linkage,
extraction agreement and licensed viewer replay were not independently
revalidated in this repair.

This document states exactly what is supported, what has been executed, and what remains unverified.
It is deliberately conservative: a solver finishing is **not** evidence of engineering accuracy.
Three outcomes are kept separate everywhere: solver executed, extraction succeeded, engineering
comparison passed.

## Supported analysis scope

| Aspect | Supported |
|---|---|
| Solver | Abaqus/Standard 2024 |
| Formulation | 2D plane stress (`plane_stress`), nonlinear geometry, implicit dynamic ramp |
| Elements | CPS3 (triangle), CPS4R (reduced-integration quad) |
| Rigid body | One or two R2D2 rigid profiles (moving door, optional moving body), each with its own reference node, contact surface and assembled instance |
| Material | Linear elastic, or hyperfoam with uniaxial test data (`*Hyperfoam, N=1`) |
| Contact | Hard general contact (`pressure-overclosure=HARD`), all exterior, Coulomb friction |
| Motion | Door closing from above the seal; body seating from above or below with the sign checked against the measured contact side; one or two steps |
| Fixture | Reviewed mesh-node selection (`WSFIX`); legacy CAD-edge mounting resolved to nodes |
| Mesh reuse | A new mesh is required only when geometry, roles, region fill or mesh controls change |
| Drawing curves | Exact B-spline (`SPLINE`) with control points/knots/weights, or the AutoCAD-compatible cubic through fit points; chord tolerance 0.02 mm for display and approximation |
| History output | `U1, U2, RF1, RF2` at the reference point that owns each step |
| Field output | `U`, `RF` (nodal), `LE`, `S` (element), `CSTRESS` (contact) requests |
| Units | N, mm, s, tonne (density in tonne/mm³, stress in MPa) |

Not supported: 3D solving, more than two moving rigid profiles, simultaneous panel motion, a door
that closes from **below** the seal (the door travel is negative by schema; a bottom mount uses the
moving-body role, whose travel sign is open), oblique X/Y motion, a profile that straddles the seal
or has an ambiguous contact side, arbitrary STEP assemblies, curved sweeps, installation preload,
full-perimeter closing, additional constitutive models.

## Physical assumptions

- Plane stress with an explicit section thickness. Thickness is applied to the contact surface and the
  solid sections consistently.
- The panel is rigid. Deformation of the mating component is not modelled.
- Contact is hard in the normal direction with Coulomb friction; no cohesive or adhesive model.
- The prescribed travel starts from the assembled position. The reported initial vertical clearance is
  the minimum gap between the faceted seal boundary and the panel profile at that position, measured
  along Y over the shared X range. It is positive for a panel above **or** below the seal; the contact
  side is measured from the drawn profile, not assumed.
- Force reporting is either total reaction (N) or reaction per millimetre of thickness (N/mm), chosen
  explicitly and recorded in the run metadata.
- Signed global components are preserved end to end. The chart projects `U` and `RF` onto the
  configured closing direction; it never replaces the raw component history.

## Door response definition

For a closing direction `d` (unit vector, `[0, -1]` for the vertical template):

- closing travel `= (U - U_step_start) · d`, measured from the first sample of the closing step;
- closing force `= (RF · d) / normalization`.

Abaqus reports `RF2 < 0` while the seal resists the downward stroke, so a resisting seal produces a
**positive** closing force. This was measured, not assumed (see below). The raw `u1, u2, rf1, rf2`
values are stored in every history row and in `history.csv`; `results.json` is never rewritten to
reflect a display preference. The "Reverse X sign" and "Reverse Y sign" controls affect only the chart
and the client-side "Export displayed curve" CSV.

## What has actually been executed

| Check | Status | Evidence |
|---|---|---|
| Deterministic INP generation with required keywords | PASS | `tests/test_abaqus.py::test_deck_sections_history_mesh_and_motion` |
| History request covers all four signed components | PASS | same test (`U1, U2, RF1, RF2`) |
| Material card mapping and section assignment | PASS | `tests/test_abaqus.py`, `apps/web/tests/materials.spec.ts` |
| Element set / mounting / rigid reference point | PASS | `tests/test_abaqus.py`, `apps/web/tests/workflow.spec.ts` |
| Deck rejection of invalid material and mounting data | PASS | `tests/test_abaqus.py` |
| Gmsh meshing and inverted-element rejection | PASS | `tests/test_geometry.py`, `tests/test_workbench.py` |
| Abaqus launcher argument construction (batch fixture) | PASS | `tests/test_abaqus.py::test_windows_batch_launcher_spaces_and_fixed_arguments` |
| Completion-evidence detection, license diagnosis | PASS | `tests/test_abaqus.py` |
| History alignment, step identity and projection | PASS | `tests/test_abaqus.py::test_histories_align_in_time_and_normalize` |
| Role-aware clearance, contact normals, two-step deck and per-motion projection | PASS (license-free) | `tests/test_two_step.py` (24 tests, A–M and the user scenario) |
| Readiness exposes the assembly measurement and penetration blocker | PASS (license-free) | `tests/test_two_step.py::test_readiness_exposes_the_bottom_body_measurement` |
| Assembled viewport instances and Motion/Review diagnostics | PASS (browser) | `apps/web/tests/assembly.spec.ts` |
| Door response is projected, sign-reversible, exported | PASS | `apps/web/tests/curve.spec.ts` |
| ODB extraction round trip (`abaqus python`, manufactured ODB) | PASS (optional) | gated by `SIMPLIFY_ABAQUS_TEST_LAUNCHER` |
| **Real licensed Abaqus/Standard closing analysis** | **PASS** | below |
| Mesh-first fixture: exact `WSFIX` from a saved node selection | PASS | `tests/test_fixture.py`, `apps/web/tests/fixture.spec.ts` |
| Spline import, tessellation and meshing follow the drawn curve | PASS | `tests/test_spline.py` |
| Licensed closing case through the mesh → fixture → deck path | **PASS** | below |
| Contact onset compared with a reference curve | **BLOCKED** | No trusted reference supplied |
| Force–displacement compared with a reference curve | **BLOCKED** | No trusted reference supplied |
| Mesh convergence study | **BLOCKED** | One mesh size only |
| Time-step / ramp sensitivity | **BLOCKED** | One duration only |

### Licensed execution record — door-only closing, 2026-11-21

Environment: Windows, Abaqus/Standard 2024 (`C:\SIMULIA\Commands\abq2024.bat`), 1 CPU, synthetic
"Hollow bulb section" (no proprietary geometry), mesh size 1.5 mm, travel −6.0 mm, step duration 0.5 s,
thickness 1.0 mm, total reaction reporting.

| Item | Value |
|---|---|
| Run UUID | `39f696ee-c757-44ba-bb42-9e8f9671bfe6` |
| Retained local evidence | `.local/licensed-evidence/39f696ee-c757-44ba-bb42-9e8f9671bfe6/` on the reviewed machine; generated files are excluded from Git |
| Solver / extraction | `Succeeded` / `Succeeded`, launcher exit 0 at both stages |
| Wall time | 38.2 s (solve + extraction) |
| Analysis status | `THE ANALYSIS HAS COMPLETED SUCCESSFULLY`, 47 increments |
| `analysis.inp` SHA-256 | `4e3cf6fe1d1f564d2e969bb87bfe8335ecbafe62d645c2f171008eda4666fc35` (matches the recorded `input_hash`) |
| `mesh.json` SHA-256 | `59d98e164692a301ae112520b0ea23de6abdc2eecacfce56ada5a572adb95a2c` |
| Frames / steps | 26 frames, one step `Closing` |
| `WSFIX` membership | 13 node labels: 1, 2, 15–25 |
| Held-node displacement | max \|U\| over **all** frames = 8.25e-37 mm (floating-point zero) |
| Panel RP `U2` | 0.0 → −6.0 mm, monotonically non-increasing |
| Geometric initial clearance | 1.80 mm (reported in `result-metadata.json`) |
| First contact sample | t = 0.16 s, travel 1.92 mm, `RF2` = −1.38e-3 N |
| Final `RF2` / projected closing force | −0.3335 N / **+0.3335 N** |
| Final signed `RF1` | −2.45e-6 N (extracted final sample) |
| Exported CSV identity | `closing_force_N == -panel_RF2_N` and `closing_displacement_mm == -panel_U2_mm` for every row (exact) |
| Unavailable outputs | none |

Interpretation and tolerances actually used:

- **Contact onset vs geometry.** The reported clearance (1.80 mm) and the solver's first contact sample
  (1.92 mm) agree within one history output interval (0.24 mm). This checks that the geometric
  clearance quoted by the tool is a fair predictor of when contact starts; it is **not** a correlation
  with a reference curve.
- **Held nodes.** `WSFIX` was checked by exact set membership against the INP and by a
  floating-point-zero displacement tolerance (1e-12 mm) over every frame.
- **Projection.** Checked as an exact arithmetic identity against the raw history, in both the stored
  index and the CSV.
- **No engineering tolerance has been agreed** for force magnitude, contact pressure or onset, so no
  correlation claim is made.

### Licensed execution record — mesh-first fixture, 2026-11-21

Same machine, launcher and synthetic section as above, but driven through the mesh-first workflow:
generate the mesh, box-select an explicit node patch, save the fixture, prepare the deck, submit.

| Item | Value |
|---|---|
| Model revision | `35462af6-768b-4b8b-b176-d9450ebaf7b0` |
| Mesh job / digest | `cc3fcc81-2f7c-4ffa-9c57-dbe98df396f7` / `59d98e164692a301ae112520b0ea23de6abdc2eecacfce56ada5a572adb95a2c` |
| Mesh compatibility digest | `1b214a822a3eccce719af0f3682d48b37c825f6a0c9eaa5652ce73a48194aad1` |
| Fixture | 18 labels `WS-1:{1, 2, 15–26, 42, 100, 117, 121}`, hash `a83ea4905bcb1ac9c224ddf41103d723435ec8cf296db450ff00b137a9b2497f` |
| Selection rule | deformable WS nodes with `y ≤ 1.0 mm` (a rectangle, not a CAD edge) |
| Deck job / SHA-256 | `f53ed7d3-fca8-48ae-8c96-17f825a41536` / `b68b7d84c31cdf60d1276cccd86d21f1452c2fb6b0519dfd33bcd870e3457ed7` (file hash equal to the recorded `input_hash`) |
| Run | `54b7be8c-d260-4a65-adcf-0205263032f3`, solver and extraction `Succeeded`, 42.3 s |
| Analysis status | `THE ANALYSIS HAS COMPLETED SUCCESSFULLY`, 48 increments |
| `WSFIX` in the submitted deck | exactly the 18 selected labels (set equality; no extra node) |
| Selected-node displacement | max \|U\| over all 26 frames = 8.03e-37 mm |
| Panel RP `U1` / `U2` at the end | 2.0e-41 mm / −6.0 mm (prescribed travel attained) |
| Panel RP `RF1` / `RF2` at the end | −1.95e-5 N / −0.33797 N |
| Projected closing force | +0.33797 N |
| First contact sample | t = 0.16 s, travel 1.92 mm, `RF2` = −1.39e-3 N |
| Geometric clearance | 1.80 mm |
| Raw CSV | `panel_RF2_N` = `panel_total_RF2_N` = −0.33797; `closing_force_N` = `closing_total_force_N` = +0.33797 |

Checks and tolerances used:

- **Fixture exactness.** The `WSFIX` list parsed from `analysis.inp` equals the saved label set
  element-for-element; no neighbouring node and no rigid-panel node is present.
- **Held nodes.** Every selected label appears in the ODB and its displacement is below 1e-12 mm in
  every frame.
- **Attained travel.** The RP `U2` equals the prescribed −6.0 mm; the transverse `U1` is numerically
  zero, so no unintended in-plane motion was introduced.
- **Contact.** Onset at 1.92 mm travel versus a reported clearance of 1.80 mm, i.e. within one 0.24 mm
  history output interval. Self-consistency, not correlation.
- **Force.** A different fixture patch changes the force curve: this case gives −0.33797 N against
  −0.33351 N for the earlier 13-node edge fixture, a 1.3 % difference. Neither value is a pass
  threshold; there is still no trusted reference.
- **Provenance.** `result-metadata.json` records `fixture.source = mesh-node-selection`, the 18 labels
  and the count; `results.json` carries the same block.
- **Provenance re-extraction (2026-11-21, after this record was first written).** The originally
  retained `results.json` was produced by an extractor build that predated the `fixture` header block,
  so only `result-metadata.json` carried the labels. The same ODB was re-extracted with the current
  extractor into `.local/licensed-evidence/54b7be8c-reextract/` (launcher exit 0). In that output both
  `result-metadata.json` and `results.json` carry the same 18 labels, and both sets equal the deck's
  `WSFIX`. The original run directory was left untouched; the run ID, mesh digest, deck hash and
  solver results above are unchanged.

## Native DWG evidence on the original drawing

Executed on the reviewed machine with `SEAL_ODA` and `ABAQUS_QOL_ODA` unset and the ODA entry
points replaced by functions that raise if called. `tests/test_dwg.py::test_original_drawing_reaches_a_deck_without_any_converter`
asserts that the converter is never reached, and the acceptance harness below runs the whole path.

| Item | Value |
|---|---|
| Drawing | `examples/hollow-section_2.dwg`, 14 503 bytes, header `AC1032`, SHA-256 `8592c3c2aa59530e7b937d58f6354f6beeb24b6bc56cfcb6d37945e483aac771` (matches the expected value) |
| Units | header `$INSUNITS = 4` (millimetres), confirmed by the reader |
| Reader | ACadSharp 3.8.35 (MIT), `integrations/dwg/bin/dwg-inventory.exe` → `DwgReader.Read`; no DXF, ODA, AutoCAD automation or network |
| Model space | 5 entities on one layer (`0`): 1 `LINE` (handle CC), 1 `LWPOLYLINE` (D7, 8 vertices with 4 bulges), 3 `SPLINE` (CD 21 fit points, 11D 13 fit points closing on itself, 120 6 fit points) |
| Spline provenance | All three are **fit-point** splines (`controlPoints` empty, `knots` empty) and were reconstructed with the AutoCAD-compatible cubic; recorded in `import-report.json` as `{"fit_points": 3}` |
| Accounting | 0 unknown entities, 0 skipped entities; reader warnings: one unlisted `SUN` object, one unresolved `CellStyle` table reference, three `knot count does not match control points` notes that reflect the fit-point-only storage |
| Canonical model | 11 analytic edges, 13 vertices, 3 components: seal loop (LINE CC + SPLINE CD + cavity SPLINE 11D), body profile (D7), door profile (SPLINE 120) |
| Regions | 1 filled region with 2 loops (outer + cavity) and 1 cavity; filled area 98.29 mm²; 2 open chains excluded and offered as rigid profiles |
| Mesh | 83 CPS3 + 291 CPS4R (WS) + 38 R2D2 (door), 453 nodes; the 128.32 mm² cavity contains **0** material elements; the body component is reported as excluded, not silently dropped |
| Fixture | 15 nodes `WS-1:{1, 2, 98–110}` on the mounting foot; `WSFIX` parsed from the deck equals that set exactly |
| Deck | job `bd6ec609-01b5-4ea8-a422-ff9bb79592bb`, SHA-256 `ff0de2ec50b3c9a5ac3570f99c3bfcc5df9b7974d0c94d1510377945a9afb827`, one step `Closing`, one rigid body (`PANEL_RP`), travel −6.5 mm, duration 1.3 s, thickness 1.0 mm |
| Run | `8a0cefa3-6bef-4eaf-97d6-94d3712c33b1`, solver and extraction `Succeeded`, evidence under `.local/dwg-acceptance-contact/` (ignored) |
| Solver | `THE ANALYSIS HAS COMPLETED SUCCESSFULLY`, 84 increments, 66 ODB frames |
| Held nodes | all 15 labels present in every frame; worst \|U\| over all frames = 8.40e-39 mm |
| Panel RP | `U2` 0 → −6.5 mm (prescribed travel attained), `U1` 2.66e-40 mm, final `RF2` −0.018122 N |
| Contact | first non-zero `RF2` at travel 5.70 mm against a reported geometric clearance of 5.66153 mm, i.e. inside one 0.1 mm output interval |
| Projected closing force | +0.018122 N at 6.5 mm travel (resisting seal ⇒ positive) |
| CSV vs ODB | `history.csv` equals the extracted history exactly for `panel_U2_mm`, `panel_RF2_N` and `closing_force_N` at the final sample |

Interpretation:

- This is a **door-only** closing case on the real drawing. The body profile is imported, reviewed and
  reported as excluded; it is not meshed and it does not move. At the time of this session body
  seating followed by door closing (two panels, two steps) was not implemented; the milestone
  delivery below adds and exercises that template, so this bullet is the historical door-only record,
  not a current limitation.
- The material card is the illustrative hyperfoam card carried by the repository; it is not a measured
  compound. The force value is therefore an execution result, not a correlation result.
- No engineering tolerance has been agreed, so the closing force is recorded, not judged.

### Mesh-fidelity correction on the private drawing (release candidate)

The first private-drawing mesh did not satisfy the boundary tolerance. Measured against the analytic
curves rather than the display tessellation:

| Group | First mesh | Refined mesh | Limit |
|---|---|---|---|
| Outer WS (spline CD) | 0.30747 mm | 0.01549 mm | 0.02 mm |
| Cavity (spline 11D) | 0.11288 mm | 0.01974 mm | 0.02 mm |
| Door (spline 120) | 0.01423 mm | 0.01423 mm | 0.02 mm |
| Fit points beyond 0.02 mm | 10 of 21 (worst 0.29415 mm) | 0 of 21 (worst 0.01071 mm) | 0 |

Two causes were found and fixed: the boundary polyline of a closed spline was compared without its
closing segment, and the global `MeshSizeMin` floor blocked curvature refinement below 0.25 mm on a
sub-millimetre hook. Meshing now refines from curvature and re-measures until every boundary group is
inside 0.02 mm, or raises a diagnostic naming the measured deviation.

Refined licensed run (same drawing, same fixture, door travel ?6.5 mm, one CPU):

| Item | Value |
|---|---|
| Run | `d0d409c2-6fc9-4e69-95a1-c75069075d68` |
| Solver / extraction | `Succeeded` / `Succeeded`, `THE ANALYSIS HAS COMPLETED SUCCESSFULLY`, 90 increments |
| Frames | 66; worst fixed-node \|U\| 1.811e-38 mm; all 15 labels present in every frame |
| Travel | 6.5 mm of 6.5 mm prescribed; clearance 5.66497 mm; first contact at 5.70 mm |
| Final `RF2` / projected closing force | ?0.016966 N / +0.016966 N |
| Previous coarse-mesh value | ?0.018122 N (a 6.4 % difference from the mesh change; both are comparison values, not a target) |
| CSV vs ODB | last row equals the extracted sample for `panel_U2_mm` and `panel_RF2_N` |
| Solver warnings | 3 ? "THE SOLUTION APPEARS TO BE DIVERGING" and 3 ? negative-eigenvalue warnings ? **needing engineering review**, not an expected output limitation |
| Expected limitations | Body profile excluded; hyperfoam card is illustrative |

## Drawing-curve evidence (synthetic, no license needed)

`tests/test_spline.py` measures the imported curve rather than the control values:

| Check | Measurement |
|---|---|
| S-curve regression (brief-specified) | Clamped cubic Bézier `(0,0),(1,1),(2,−1),(3,0)`: the midpoint lies on the endpoint chord, `y(0.25) = 0.28125`, a single chord is 0.2887 away, and the adaptive tessellation reaches 0.0127 ≤ 0.02 mm |
| Display/approximation promise | Adaptive tessellation deviation from the true curve ≤ the declared `tolerance` (0.02 mm), measured by sampling the curve at 257 parameters and projecting onto the polyline |
| Exact meshing path | For an open, clamped B-spline boundary at 1.0 mm global size, every boundary mesh node is within **0.012 mm** of the true curve; a straight chord between its endpoints would be **0.577 mm** away |
| Approximation path | A closed spline region (descriptor unavailable to OCC) meshes through its sampled chain; every boundary mesh node stays within the declared tolerance |
| DXF round trip | Control points, degree, knots and the source handle survive import; the spline's ends snap onto the adjoining line's vertices so the contour closes |
| Fit-point splines | An entity that stores only fit points is rebuilt with the AutoCAD-compatible cubic and passes through every fit point (test tolerance 0.05 mm) |
| Mesh identity | Renaming the edge keeps the mesh compatibility digest; changing the spline (including its tolerance) changes it, so the mesh is re-reviewed |
| API → worker path | An uploaded spline DXF goes through `/api/projects/{id}/drawing` → role assignment → `/api/meshes` → `PUT /api/meshes/{id}/fixture` → `/api/decks`, and the produced `analysis.inp` contains `WSFIX` with the saved labels |

The DWG that this increment was asked to reproduce could not be converted (see Remaining blockers), so
no claim is made about how that specific drawing stores its curves.

## Benchmark procedure (to be executed by the responsible engineer)

1. Obtain written authorization and a configured launcher (`SIMPLIFY_ABAQUS_LAUNCHER` or
   `ABAQUS_QOL_LAUNCHER`).
2. Save a revision and record its ID, the INP SHA-256 shown in Run diagnostics, the material card
   versions and the mesh metrics from the review step.
3. Submit one `ABAQUS` run. Confirm Run diagnostics shows `Succeeded` for both solver and extraction.
4. Compare, against a trusted reference from the same geometry and material:
   - contact onset travel,
   - projected closing force at matching travel,
   - raw `RF1`/`RF2` where a directional check is needed,
   - contact pressure where available.
5. Repeat at two further element sizes and report the change in peak force and contact onset. Record
   the chosen mesh as converged only if the change is inside the approved tolerance.
6. Repeat with half and double the step duration to expose rate sensitivity.
7. Agree and record numerical tolerances **before** comparing. Tolerances must come from the responsible
   engineer, not from the tool.
8. Record the reviewer's approval in the release record.

The harness must not substitute synthetic DEMO output for any of these steps.

## Retained licensed replay — 2026-11-22 (no solver launch)

The retained licensed run `989fec4a-98fa-4a61-999a-e16ec886ac68` was copied to an isolated data
directory and replayed through the built application on a separate loopback port. No solver process
was started, no license was checked out, and the retained directory was not modified.

| Observation | Value |
|---|---|
| Frames | 66 (slider 0–65) |
| Camera | Panned and zoomed, then stepped through every frame; the grid size and position were identical at the end |
| Final frame | 1.300 s |
| Closing travel (displayed) | 6.5 mm |
| Signed `RF2` | −0.0169664863 N |
| Projected closing force | +0.0169664863 N |
| `history.csv` vs `results.json` | Last row agrees: time 1.2999999523 s, `panel_U2` −6.5 mm, `panel_RF2` −0.0169664863 N, closing travel 6.5 mm, projected force 0.0169664863 N |
| Display metadata | The older result had no recorded block; the first request derived bounds/ranges server-side and cached them. Magnitude 6.5 mm, `U1` 0.4226605 mm, `U2` 6.5 mm. Original artifacts unchanged. |
| Page errors | None |

This is replay of retained licensed evidence. It confirms that the displayed history matches the
recorded artifacts; it does not establish physical correlation, contact accuracy or mesh convergence.

## Remaining blockers

| Area | Blocker |
|---|---|
| DWG conversion | **Resolved for reading.** The original `examples/hollow-section_2.dwg` (AutoCAD 2018, `AC1032`, SHA-256 `8592c3c2…aac771`) is read natively by ACadSharp 3.8.35 (MIT); no ODA converter, DXF intermediate or CAD automation takes part. Reading is proven for this drawing and for the entity types it contains (`LINE`, `LWPOLYLINE` with bulges, `SPLINE` with fit points). Other DWG versions are accepted by the reader but were not exercised. |
| Licensed execution breadth | Door-only closing is executed, including on the original drawing. Two-step body-then-door deck preparation is implemented for both above and below body mounts, but **no licensed two-step ODB has been produced or extracted**, so no two-panel trajectory, contact or force result is evidenced. |
| Friction assignment | One global coefficient; per-pair overrides are not implemented. |
| Drawing role review | Roles are assigned per connected component after import; an in-viewport chain review with per-chain WS/Door/Body confirmation is not implemented. |
| Fixture history view | **Resolved 2026-11-22.** A submitted setup now resolves the mesh job recorded by its deck and verifies the digest chain before drawing archived labels. An unverifiable archive reports why; a newer mesh is never substituted. |
| Physical correlation | No trusted reference curve and no agreed engineering tolerance exist. |
| Mesh/time convergence | Not studied; two mesh sizes were exercised only as an invalidation test, not as a convergence study. |

## Limitations that remain after this phase

- No engineering benchmark comparison has been executed; no tolerance has been agreed.
- The historical DEMO curve is illustrative only and its coefficients are not measured material parameters. Its
  sign convention matches the measured solver convention (`RF2 < 0` while resisting), which is
  regression-tested. New submissions are Abaqus-only.
- Mesh metrics shown in the review step are measured from the produced mesh (node/element counts,
  shortest and longest element edge, max/min edge ratio per element, per-region counts). Inverted and
  degenerate elements are rejected during generation, so their count is always zero by construction.
- Contact onset is not predicted a priori; it must be read from a solved result.
- Legacy results produced before this phase have history rows without `u1/u2/rf1/rf2`. They remain
  viewable and exportable with their original U2/RF2 meaning; the chart states that the projected door
  response is unavailable for them.

## Release-safety pass — 2026-11-22

No solver process was launched in this pass or in Phases 0, 2 and 3, and no Abaqus license was
consumed. The retained licensed
runs (`989fec4a-98fa-4a61-999a-e16ec886ac68`, `54b7be8c-d260-4a65-adcf-0205263032f3`,
`39f696ee-c757-44ba-bb42-9e8f9671bfe6`) and their ODBs, decks, meshes and history files were not
modified or re-extracted. The pass changed browser release serving, HTTP request validation, readiness
reporting and UI state handling; it did not change the INP writer, solver invocation, extraction code
or any physical assumption.

Where this record cites the door-only result (contact at about 5.70 mm, projected +0.016966 N, signed
`RF2` −0.0169664863 N), that evidence comes from the earlier licensed run and remains a regression
replay anchor for that artifact, not an acceptance threshold for another model. A new licensed solve
would be required to claim contact or force accuracy on a different geometry, material or fixture.

Backup/restore drill for this pass: **executed on isolated data**. A retained revision with a completed
mesh (19 fixed nodes, fixture hash `97eab31a…`), a completed deck (input hash `a8e66b22…`) and its
`analysis.inp` were created in an isolated data root, the API was stopped, the whole directory was
copied, the original moved aside and the copy restored. After restart the project, revision, deck job,
fixture hash and downloaded INP were re-read: the INP SHA-256 matched exactly and the `WSFIX` block was
present. The `instance.json` left by the stopped process was recognised as stale and taken over by the
new PID. Low-disk and interrupted-write fault injection were **not** repeated in this pass.

### Phase 4 two-step template — 2026-11-22

Status by category, kept separate:

1. **Code implemented:** yes — model mode, body motion, body R2D2 meshing, two-step INP with
   propagated BCs, two-reference metadata, per-step history projection and a results step selector.
2. **Automated tests passed:** yes — 8 Python tests (INP structure, step order, BC values, rigid
   bodies, history requests, metadata, legacy regression, mesh-identity sensitivity, validation,
   projection) and 1 browser test (mode UI/missing-body rejection).
3. **Real solver executed:** **NO.**
4. **Result extraction succeeded:** **NO** for a two-step ODB (the extractor code path exists but has
   not been run against licensed output).
5. **Sensitivity/correlation qualified:** **NO.**

**Gate 4B is BLOCKED** pending an authorized Abaqus/Standard 2024 run of the two-step template on a
trusted geometry, with retained INP/ODB evidence, verification that step 1 moves only the body and
step 2 only the door, seal deformation/contact carry-over, correct force/displacement signs and units,
and no rigid-body or overconstraint artefacts. No synthetic playback is accepted for this gate.

### Phase 5 live diagnostics — 2026-11-22

Status by category:

1. **Code implemented:** yes — simulated-time progress card, per-step states, separate solver and
   extraction status, license-wait, stale-heartbeat, extraction-failure and unknown-step handling,
   with no ETA.
2. **Automated tests passed:** yes — 4 browser tests with mocked job/revision state covering both
   steps, 99 vs 100, queued 0%, license wait, unknown step, stale heartbeat and failed extraction.
3. **Real solver executed:** no new licensed solve; the existing retained runs were not modified.
4. **Result extraction succeeded:** unchanged; no extraction was run this phase.
5. **Sensitivity/correlation qualified:** no.

### Panel placement, contact orientation and motion projection - 2026-11-22

Status by category, kept separate:

1. **Code implemented:** yes - role-aware clearance for a profile above **or** below the seal,
   geometric contact-side detection, per-profile R2D2 orientation, per-motion projection direction,
   separate viewport instances and Motion/Review diagnostics.
2. **Automated tests passed:** yes - `tests/test_two_step.py` (24 tests: A-M scenarios, the reported
   user arrangement, readiness exposure and penetration blocker), `apps/web/tests/assembly.spec.ts`
   (scene instances/offsets and localized Motion/Review diagnostics), the existing renderer,
   playback, picking and review browser tests, and the full Python suite.
3. **Real solver executed:** **NO.** No licensed run was started, no license was consumed, and no
   retained ODB, INP, mesh or history file was modified.
4. **Result extraction succeeded:** **NO** for a two-step ODB. The extractor now selects the
   reference that owns each step and projects it along that step's own direction, but that path was
   not run against licensed output in this pass.
5. **Sensitivity/correlation qualified:** **NO.**

The reported arrangement - door above the seal at -5.5 mm over 1.3 s, body below the seal at
+5 mm over 1.0 s, both initial offsets 0 mm - now prepares a deck containing the `WS`, `PANEL` and
`BODY` parts, the `PANEL_RP` and `BODY_RP` references, `Body seating` then `Closing`, the declared
initial placements and displacement BCs, and one rigid contact surface per part whose SPOS side
faces the seal. That is deck-preparation evidence, not solver evidence.

What the geometric checks actually establish:

- **Clearance.** The minimum of the piecewise-linear difference between the FE seal boundary and the
  FE rigid profile over their shared X range, evaluated exactly at every breakpoint (including
  sloped, curved and vertical segments). The reported value is positive for both mounts; the
  separation convention is not an absolute value, because a profile on the wrong side of the seal
  keeps a negative separation and is rejected as initial penetration.
- **Normals.** Recomputed as `(-dy, dx)/|...|` from the connectivity written into each part, not from
  the presence of `SPOS`. Every door segment normal has a negative Y component and every
  below-mounted body segment normal a positive one, i.e. toward the seal under the Abaqus local-2
  (SPOS) convention. The above-seal orientation is the one used by the retained licensed door-only
  runs, which did reach contact (first contact at 5.70 mm travel, final `RF2` -0.016966 N); the body
  orientation mirrors that executed convention. Neither is a new contact-pressure result.
- **Projection.** `align_histories` is checked as an exact arithmetic identity: raw `u1/u2/rf1/rf2`
  stay signed, while `displacement` and `force` are projected onto the step's own direction
  (door `[0,-1]`, bottom body `[0,+1]`). No raw evidence is rewritten.

**Gate 7 remains BLOCKED.** A licensed Abaqus/Standard 2024 run of this exact arrangement is still
required to show that step 1 moves only the body, step 2 only the door, the seal contact carries
over, the attained positions match the deck, the reaction signs are physically consistent, and no
rigid-body or overconstraint artefact appears. Until then the deck preparation is supported and the
solver physics are not claimed.

Supported geometry limitations of this increment:

- The door closes from above; its travel is negative by schema. A bottom-mounted profile must use
  the moving-body role, whose travel sign is free.
- Motion is a single vertical translation along Y. Oblique X/Y motion, a profile that straddles the
  seal boundary at the assembled position, and an ambiguous contact side are rejected explicitly.
- Clearance is measured along Y over the shared X range, not as a minimum normal distance to an
  arbitrary surface.
- More than two moving rigid profiles and simultaneous motion are not supported.
- A moving-body component can be introduced from a native DWG (which allows open contours) or a
  model that already carries one. The DXF reader still rejects open non-PANEL contours and merges
  multiple open PANEL contours into one component, so a DXF-only two-panel drawing cannot yet
  declare a separate body profile.

## Milestone delivery — import units, defaults, zero travel, stress viewer and licensed two-panel runs

Date: 2026-11-23 (work started 2026-11-22). Baseline `5104b99`. Isolated data roots and ports were
used throughout; the engineer's live instance (8765) and its database, drawings and retained runs
were not restarted or modified.

### What was executed

| Area | Status | Evidence |
|---|---|---|
| Import unit policy: declared mm, unitless-as-mm, missing header, inches rejection | PASS | `tests/test_units.py`; browser `apps/web/tests/import-units.spec.ts` |
| Import without the mm checkbox, first click opens the picker, cancel/corrupt/two models | PASS | `import-units.spec.ts`, `isolation.spec.ts` |
| New-model defaults 0.5 mm / 1.0 s; version-1 payloads keep 1.0 mm / 1.3 s | PASS | `tests/test_defaults.py`, API creation/duplication |
| Rubber quadrilateral reduced-integration policy and CPS4 rejection | PASS | `tests/test_abaqus.py::test_rubber_quadrilateral_is_rejected_as_full_integration`; Mesh UI policy and element legend |
| Solid hyperelastic rubber (compressible neo-Hookean C10/D1) | PASS | `tests/test_abaqus.py`, `tests/test_material_library.py`, browser `materials.spec.ts`; licensed run `a8f47acc-dd15-42df-8f61-a0feed14adb9` |
| Zero travel as a true hold (four combinations + door-only) | PASS | `tests/test_two_step.py`; browser `apps/web/tests/zero-travel.spec.ts` (0/−5.5 and 0/0) |
| Draft validation never blanks the last geometry | PASS | `zero-travel.spec.ts`; display no longer clears on a draft 422 |
| Assembled-offset placement, intersection vs ambiguous side, no X overlap | PASS | `tests/test_two_step.py` geometric tests |
| Missing raw components preserved (null, empty CSV cell); measured zero numeric | PASS | `tests/test_results_fields.py` |
| Canonical step identity incl. Abaqus space-stripped names | PASS | re-extracted licensed ODBs; `test_results_fields.py` |
| Stress-default Results view, cell colouring and max-IP policy | PASS | browser `results-retained.spec.ts` on retained licensed `39f696ee…` |
| White Results canvas, fixed 0–0.5 MPa limits, saturation, range editing | PASS | `results-retained.spec.ts`, screenshots under `.local/milestone/` |
| Edges/node markers independent toggles, deformation scale | PASS | `results-retained.spec.ts` |
| Licensed two-panel body+door and held-body+door execution | PASS (execution) | runs below |
| Viewer/extractor Mises vs ODB | PASS (extraction agreement) | element 217 IP1 values below |
| Physical correlation | BLOCKED | no independent reference data or agreed tolerance |
| Mesh-artifact recovery for missing/corrupt active mesh | PASS | `test_release_and_compatibility.py::test_missing_or_corrupt_active_mesh_names_the_recovery`; readiness `mesh.artifact_missing/corrupt`, deck refusal, historical deck readable |
| Offset-profile picking in a real browser | PASS | browser `offset-picking.spec.ts`: door/body at +0.5/−1.0 mm, zoom and middle-button pan |
| Two-step result replay in the Results UI | PASS | browser `two-step-results.spec.ts` on a re-extracted licensed result: opens on Closing, switches to Body seating, canonical CSV step |

### Licensed execution record — two-panel synthetic, 2026-11-23

Environment: Abaqus/Standard 2024 (`C:\SIMULIA\Commands\abq2024.bat`), one CPU, isolated
`SEAL_DATA`, synthetic `Two-panel seating section` (coarse 1.5 mm acceptance mesh), `Body seating`
(1.0 s) then `Closing` (1.3 s). Run through the normal API → worker → solver → read-only extractor
path. ODBs were inspected read-only with `abaqus python`.

| Case | Run | Body step | Closing step | Fixed WS nodes | Final max CPRESS | Max Mises (ODB) |
|---|---|---|---|---|---|---|
| moving body 5 mm gap, door −5.5 | `eca0c88e-8196-48cc-964a-971f2f8c24e3` | BODY U2 0→5.0, RF2 0.0; PANEL 0→0 | BODY held 5.0→5.0, RF2 ≈0; PANEL 0→−5.5, RF2 −0.17537114024162292 | 13 labels, max \|U\| 9.15e-38 mm | 0.05185 MPa | 0.162458926 MPa (WS-1 el. 217 IP 1) |
| held body, door −5.5 | `89fab9df-23fd-481c-a8d5-bbcb934f0354` | BODY 0→0, RF2 0; PANEL 0→0 | BODY 0→0, RF2 0; PANEL 0→−5.5, RF2 −0.17537090182304382 | 13 labels, max \|U\| 9.15e-38 mm | 0.05185 MPa | 0.162471995 MPa (WS-1 el. 217 IP 1) |

| Case | Mesh digest | Deck SHA-256 | Solver / extraction | Frames |
|---|---|---|---|---|
| moving body 5 mm gap | `51ef1a65fa5b7701156f9ce6c93b4bd2411fd63b0c6b490f6e10b19d929b0c15` | `b5b0413517ac770645d88d68732428008595ccd495263bee93992489c9ff4bf1` | Succeeded / Succeeded | 117 |
| held body | `487df47458048a8b9ded0689a855b8c9c473b8c0a657406c9f9617cc32619104` | `c75f09b0735ac36b02570257cfde6a177f67500c9bc7d76cddf5f13595856dd5` | Succeeded / Succeeded | 117 |

Checks actually made:

- **Prescribed and attained motion.** Both reference points were read directly from the ODB in
  both steps. The commanded body/door travel is attained; the non-moving reference stays fixed.
- **Step-boundary continuity.** The body's Closing-step first U2 equals its Body-seating last U2;
  the door's Closing-step first U2 is 0.
- **Fixed nodes.** The 13 reviewed `WS-1` labels move by at most ~1e-37 mm over every frame.
- **Projection and CSV.** `history.csv` final door row equals the ODB RP: U2 −5.5,
  RF2 −0.17537114024162292 / −0.17537090182304382, projected force +0.17537…; body step rows carry
  U2 5.0 / 0.0 with `step_id` `bodyseating`.
- **Mises agreement.** The extractor's `Mises` field for WS-1 element 217 integration point 1
  equals the ODB invariant to the printed precision (0.162458926 vs 0.16245892643928528;
  0.162471995 vs 0.16247199475765228). The viewer colours an element by its maximum
  integration-point Mises and the Gate F browser test verifies the displayed probe value against
  the extracted frame.
- **Solver warnings.** Both analyses completed successfully but emitted divergence/cut-back
  warnings and "3 unconnected regions" (the two rigid instances and the seal are separate
  instances until contact). The 5 mm-gap body step also reports zero force before contact. These
  warnings require engineering review; a converged solve is not a physical validation.
- **Sensitivity, not a target.** An earlier moving-body run with the synthetic body drawn only
  1 mm below the seal and commanded +5 mm (`4279bf92-e9e6-4f4f-a011-a02fbfe60ef8`) over-compressed
  the foot: BODY RF2 1975.7 N and CPRESS 109.76 MPa. It is retained as a high-compression
  sensitivity case and is **not** presented as a representative seating result.

### Licensed neo-Hookean solid-rubber verification

The same API → worker → solver → extractor path was used for a door-only synthetic section whose
bulb is assigned a compressible neo-Hookean card (C10 = 0.5 MPa, D1 = 0.01 MPa⁻¹). The deck contains
`*Hyperelastic, neo Hooke` followed by `0.5, 0.01`; this is a deliberately named synthetic card, not
a material qualification.

| Run | Mesh digest | Deck SHA-256 | Solver / extraction | Result |
|---|---|---|---|---|
| `a8f47acc-dd15-42df-8f61-a0feed14adb9` | `3869f07dfd81e4ea8a26e37cb0c0a5737b6bb752f42914d1e849ea7a2aa5bfd3` | `cf4017b226c3523d17bf7920dca332256074fb9add9c2c4668aa6cd63437bf84` | Succeeded / Succeeded | Closing 51 frames; PANEL U2 0→−5.5, RF2 −0.3982129693031311; 13 fixed nodes max \|U\| 8.41e-37 mm; CPRESS 0.116296 MPa; max Mises 0.367282778 MPa (WS-1 el. 199 IP 1) |

The analysis ended with "THE ANALYSIS HAS BEEN COMPLETED" and **0 ERROR MESSAGES**. It emitted
divergence/cut-back warnings and "2 unconnected regions", which remain engineering-review items.
The material library keeps C10/D1 as versioned values (v1/v2 tested), and a linear-elastic card is
never relabelled.

### Two-step result replay

A re-extracted copy of the held-body licensed run (source `89fab9df-23fd-481c-a8d5-bbcb934f0354`)
was served on an isolated instance as completed run `62ce070f-5803-44ac-a14b-4488d574b09f`. The
browser spec opens it on the **Closing** frame (t = 1.0 s), shows both canonical step options, switches
the curve/CSV to **Body seating** (`step_id=bodyseating`) while retaining the displayed frame and
field/probe policy, then returns to **Closing** (`step_id=closing`) and reaches 5.5 mm. This is a
replay of extracted evidence, not a new solve.

### Final regression

pytest **230 passed, 1 opt-in skipped**; Playwright **71 passed, 1 opt-in skipped** (the retained
8891 replay was not running for the final suite, so it skipped by design; the two-step 8892 replay
ran and passed); `test:i18n` **700 keys**; encoding **41 files**; `typecheck`; production build
**`50f7b3465baf`**. No solver is used by the automated suites.

### Separate conclusions

These are intentionally separate; none implies the next one.

| Conclusion | Outcome | Basis |
|---|---|---|
| Workflow readiness | **PASS for the stated gates** | Import/units, defaults, zero holds, placement, mesh recovery, results controls and step identity are automated and pass; Gates A–F/H above. |
| Successful solver execution | **PASS for the three synthetic acceptance cases** | `eca0c88e…`, `89fab9df…` and `a8f47acc…` each completed solver and extraction; ODB read-only inspection. Not a statement about arbitrary geometry or production decks. |
| Viewer agreement with the ODB | **PASS for the extracted fields tested** | Extractor Mises equals the ODB invariant to ~1e-9 MPa; the browser probe equals the extracted max-IP value; RP histories/CSV equal the ODB; two-step replay preserves canonical step identity. |
| Physical correlation | **BLOCKED** | No independent reference measurement, boundary condition set or agreed tolerance. Convergence alone, and a completed solve, do not establish it. |

### Remaining blockers

| Area | Status |
|---|---|
| Physical correlation | No independent reference and no agreed tolerance. |
| Convergence/rate sensitivity | Not studied; the synthetic cases emit divergence cut-backs and zero-force warnings before contact. |
