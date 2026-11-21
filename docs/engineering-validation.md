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
| DWG conversion | No ODA-compatible converter is installed on this machine, so no genuine DWG was converted. DXF is exercised end to end. |
| Licensed execution breadth | Door-only closing is executed. Body-then-door, oblique motion and reversed profiles are not implemented yet, so they cannot be executed. |
| Friction assignment | One global coefficient; per-pair overrides are not implemented. |
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
