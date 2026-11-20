# Engineering validation

This document states exactly what is supported, what has been executed, and what remains unverified.
It is deliberately conservative: a solver finishing is **not** evidence of engineering accuracy.

## Supported analysis scope

| Aspect | Supported |
|---|---|
| Solver | Abaqus/Standard 2024 |
| Formulation | 2D plane stress (`plane_stress`), nonlinear geometry, implicit dynamic ramp |
| Elements | CPS3 (triangle), CPS4R (reduced-integration quad) |
| Rigid body | One R2D2 rigid panel profile with a reference node |
| Material | Linear elastic, or hyperfoam with uniaxial test data (`*Hyperfoam, N=1`) |
| Contact | Hard general contact (`pressure-overclosure=HARD`), all exterior, Coulomb friction |
| Motion | Single moving panel, prescribed displacement along Y, one step |
| Output | `U`, `RF` (nodal), `LE`, `S` (element), `CSTRESS` (contact) requests |
| Units | N, mm, s, tonne (density in tonne/mm³, stress in MPa) |

Not supported: 3D solving, multiple moving panels, arbitrary STEP assemblies, curved sweeps,
installation preload, full-perimeter closing, additional constitutive models.

## Physical assumptions

- Plane stress with an explicit section thickness. Thickness is applied to the contact surface and the
  solid sections consistently.
- The panel is rigid. Deformation of the mating component is not modelled.
- Contact is frictionless-to-Coulomb with hard normal behaviour; no cohesive or adhesive model.
- The prescribed travel starts from the assembled position. The reported initial vertical clearance is
  the minimum gap between the faceted seal boundary and the panel profile at that position.
- Force reporting is either total reaction (N) or reaction per millimetre of thickness (N/mm), chosen
  explicitly and recorded in the run metadata.
- Signed panel U2 and RF2 are preserved end to end. Signs are never normalized for display.

## What has actually been executed

| Check | Status | Evidence |
|---|---|---|
| Deterministic INP generation with required keywords | PASS | `tests/test_abaqus.py::test_deck_contract` |
| Material card mapping and section assignment | PASS | `tests/test_abaqus.py`, `apps/web/tests/materials.spec.ts` |
| Element set / mounting / rigid reference point | PASS | `tests/test_abaqus.py`, `apps/web/tests/workflow.spec.ts` |
| Deck rejection of invalid material and mounting data | PASS | `tests/test_abaqus.py` |
| Gmsh meshing and inverted-element rejection | PASS | `tests/test_geometry.py`, `tests/test_workbench.py` |
| Abaqus launcher argument construction (batch fixture) | PASS | `tests/test_abaqus.py::test_launcher_fixture` |
| Completion-evidence detection, license diagnosis | PASS | `tests/test_abaqus.py` |
| ODB extraction round trip (`abaqus python`, manufactured ODB) | PASS (optional, installed runtime) | gated by `SIMPLIFY_ABAQUS_TEST_LAUNCHER` |
| Real licensed Abaqus/Standard closing analysis | **NOT RUN** | No authorization/license in the development environment |
| Contact onset compared with a reference | **BLOCKED** | No reference data supplied |
| Force–displacement compared with a reference curve | **BLOCKED** | No reference data supplied |
| Mesh convergence study | **BLOCKED** | Requires the licensed analysis above |
| Time-step / ramp sensitivity | **BLOCKED** | Requires the licensed analysis above |

## Benchmark procedure (to be executed by the responsible engineer)

1. Obtain written authorization and a configured launcher (`SIMPLIFY_ABAQUS_LAUNCHER` or
   `ABAQUS_QOL_LAUNCHER`).
2. Save a revision and record its ID, the INP SHA-256 shown in Run diagnostics, the material card
   versions and the mesh metrics from the review step.
3. Submit one `ABAQUS` run. Confirm Run diagnostics shows `Succeeded` for both solver and extraction.
4. Compare, against a trusted reference from the same geometry and material:
   - contact onset displacement,
   - signed reaction-force magnitude at matching displacements,
   - maximum displacement,
   - contact pressure where available.
5. Repeat at two further element sizes and report the change in peak force and contact onset. Record
   the chosen mesh as converged only if the change is inside the approved tolerance.
6. Repeat with half and double the step duration to expose rate sensitivity.
7. Agree and record numerical tolerances **before** comparing. Tolerances must come from the responsible
   engineer, not from the tool.
8. Record the reviewer's approval in the release record.

The harness must not substitute synthetic DEMO output for any of these steps. Separate the three
outcomes explicitly: solver executed, extraction succeeded, engineering comparison passed.

## Limitations that remain after this phase

- No engineering benchmark has been executed; no tolerance has been agreed.
- The DEMO curve is illustrative only and its coefficients are not measured material parameters.
- Mesh metrics shown in the review step are measured from the produced mesh (node/element counts,
  shortest and longest element edge, max/min edge ratio per element, per-region counts). Inverted and
  degenerate elements are rejected during generation, so their count is always zero by construction.
- Contact onset is not predicted a priori; it must be read from a solved result.
