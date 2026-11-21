# Engineering validation

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
| Rigid body | One R2D2 rigid panel profile with a reference node |
| Material | Linear elastic, or hyperfoam with uniaxial test data (`*Hyperfoam, N=1`) |
| Contact | Hard general contact (`pressure-overclosure=HARD`), all exterior, Coulomb friction |
| Motion | Single moving panel, prescribed displacement along Y, one closing step |
| Fixture | Reviewed mesh-node selection (`WSFIX`); legacy CAD-edge mounting resolved to nodes |
| Mesh reuse | A new mesh is required only when geometry, roles, region fill or mesh controls change |
| Drawing curves | Exact B-spline (`SPLINE`) with control points/knots/weights, or the AutoCAD-compatible cubic through fit points; chord tolerance 0.02 mm for display and approximation |
| History output | `U1, U2, RF1, RF2` at the panel reference point |
| Field output | `U`, `RF` (nodal), `LE`, `S` (element), `CSTRESS` (contact) requests |
| Units | N, mm, s, tonne (density in tonne/mm³, stress in MPa) |

Not supported: 3D solving, multiple moving panels, body-then-door two-step closing, oblique or
reversed panel motion, arbitrary STEP assemblies, curved sweeps, installation preload,
full-perimeter closing, additional constitutive models.

## Physical assumptions

- Plane stress with an explicit section thickness. Thickness is applied to the contact surface and the
  solid sections consistently.
- The panel is rigid. Deformation of the mating component is not modelled.
- Contact is hard in the normal direction with Coulomb friction; no cohesive or adhesive model.
- The prescribed travel starts from the assembled position. The reported initial vertical clearance is
  the minimum gap between the faceted seal boundary and the panel profile at that position.
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
  reported as excluded; it is not meshed and it does not move. Body seating followed by door closing
  (two panels, two steps) is **not implemented**, so no two-panel table can be evidenced.
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

## Remaining blockers

| Area | Blocker |
|---|---|
| DWG conversion | **Resolved for reading.** The original `examples/hollow-section_2.dwg` (AutoCAD 2018, `AC1032`, SHA-256 `8592c3c2…aac771`) is read natively by ACadSharp 3.8.35 (MIT); no ODA converter, DXF intermediate or CAD automation takes part. Reading is proven for this drawing and for the entity types it contains (`LINE`, `LWPOLYLINE` with bulges, `SPLINE` with fit points). Other DWG versions are accepted by the reader but were not exercised. |
| Licensed execution breadth | Door-only closing is executed, including on the original drawing. Body-then-door two-step closing is still not implemented, so it cannot be executed. |
| Friction assignment | One global coefficient; per-pair overrides are not implemented. |
| Drawing role review | Roles are assigned per connected component after import; an in-viewport chain review with per-chain WS/Door/Body confirmation is not implemented. |
| Fixture history view | The archived labels of an old run can still be shown against the newest compatible mesh instead of that run's own mesh; duplication does not verify mesh identity. |
| Physical correlation | No trusted reference curve and no agreed engineering tolerance exist. |
| Mesh/time convergence | Not studied; two mesh sizes were exercised only as an invalidation test, not as a convergence study. |

## Limitations that remain after this phase

- No engineering benchmark comparison has been executed; no tolerance has been agreed.
- The DEMO curve is illustrative only and its coefficients are not measured material parameters. Its
  sign convention now matches the measured solver convention (`RF2 < 0` while resisting), which is
  regression-tested.
- Mesh metrics shown in the review step are measured from the produced mesh (node/element counts,
  shortest and longest element edge, max/min edge ratio per element, per-region counts). Inverted and
  degenerate elements are rejected during generation, so their count is always zero by construction.
- Contact onset is not predicted a priori; it must be read from a solved result.
- Legacy results produced before this phase have history rows without `u1/u2/rf1/rf2`. They remain
  viewable and exportable with their original U2/RF2 meaning; the chart states that the projected door
  response is unavailable for them.
