# Implement door-panel contact pressure in Results

## Command for the execution agent

From `I:\GithubProjects\Abaqus_QualityOfLife`, read `AGENTS.md`, the current `agent.md`, and this brief. Implement **CNORMF as an additional result of new simulations in the current Abaqus QoL app**, alongside von Mises stress, displacement and the other configured outputs. An engineer must be able to start with **New Model → Import DXF/DWG**, assign the door and seal, complete normal setup, then **Prepare input deck → Submit Abaqus analysis → Results**. The app must generate the output requests, run the solver and extract the fields automatically. The engineer can select the measured door contact force in Results and inspect the pressure arrows and kPa graph for the displayed frame. Reopening the worker-produced `.aqresult` must offer the same data.

**Delivery proof comes from the newly imported drawing's own run.** Through the ordinary UI, demonstrate a new licensed submission with the default output settings, read its untouched ODB, and match a door node from that ODB to Results and the reopened file. The supplied INPs and ODBs are comparison fixtures for Gate B. The engineering workflow must work with those fixtures and the reference reader absent. Run gates A–F, record build IDs and artifact hashes, and update both user guides and engineering validation. The investigation used checkout `001d2db`. Recheck the working tree before editing.

### 1. Quantities and presentation

| Quantity | Implementation contract |
|---|---|
| Graph X | Cumulative distance **along the selected door profile**, in mm. Reconstruct the connected R2D2 chain from element connectivity in assembled, undeformed XY. For an open chain use the endpoint with lexicographically smallest `(x, y, nodeLabel)` as station zero. Sum each segment's Euclidean length. Persist orientation and stations once per profile so translating or rotating the door, reversing the declared edge connectivity, changing frames or zooming preserves the axis. |
| Graph Y | The ODB's **door-side nodal `CPRESS`**, in kPa. In the app's N–mm system, `p_kPa = 1000 × CPRESS_MPa`. Convert at one documented boundary. The 100 mm reporting width, solver section thickness, RF normalization and Reverse Y setting have no factor in this conversion. Keep the native scalar and its unit recoverable. For an external ODB require its unit convention in the mapping. |
| Arrow direction | The measured **`CNORMF` vector acting on the selected door node**, in the assembly frame. The plotted unit direction is `F / ‖F‖`. Preserve its signed components in N for inspection. Use its actual direction on angled or curved panels; the actuator's closing vector is a different quantity. Verify vector coordinates if an input uses a local coordinate system. |
| Arrow length | In the **CNORMF force field**, encode the magnitude of the raw nodal force and label the legend in N. In the **pressure view**, encode the same pressure shown by the graph, with `length = glyph_scale × p_kPa` for compression and a legend in kPa. Use one scale per quantity across the run or profile, and anchor arrows at the rendered deformed node. If deformation exaggeration exists, follow the displayed position and keep the measured values unchanged. Pressure remains signed as stored. If a supported result convention contains tensile values, label the sign, size by absolute magnitude and keep the actual force direction. |
| Identity | Join by result, step, frame, full contact domain, instance, surface/profile and node label. The same node label in the seal, body, another door segment or rigid reference point is a different identity. Preserve the original field keys and output position. |

Use the relationship deliberately: `CFORCE` requests the normal and tangential force vectors, while `CSTRESS` provides the scalar pressure. `CNORMF` alone has units of force. A raw force magnitude, force divided by reporting width, force divided by a guessed nodal area, or the door reference-point RF cannot supply this graph. If measured pressure is missing, expose that state. Never silently estimate kPa. The real reference ODBs already contain direct pressure and force. Contact data consolidated across interactions also need careful attribution. [Abaqus/Standard surface output](https://docs.software.vt.edu/abaqusv2026/English/SIMACAEOUTRefMap/simaout-c-std-surfacevariables.htm) · [Abaqus contact field naming and consolidation](https://docs.software.vt.edu/abaqusv2026/English/SIMACAECAERefMap/simacae-c-resvisvariablecontact.htm)

### 2. Read the supplied models before implementing

Use the three matching `20231129_*.inp` and `.odb` files under `I:\GithubProjects\abaqussurfacePressure` locally. All three original ODBs identify Abaqus/Standard 2023 and opened read-only in Abaqus Python 2024. Each model has two implicit-dynamic steps, General Contact, a lower rigid panel, deformable seal and **six separate upper R2D2 panel instances**. In Step-2 the prescribed upper assembly moves −20 mm in Y. For these reference cases, select the six upper profiles through an explicit mapping. In app-generated results, use the saved `moving_panel` role and its emitted ODB instance.

The reference decks request `*Contact Output, nset=<upper instance>.Set-1` followed by `CFORCE` in both steps, plus preselected field output. In the sampled frames the actual keys are `CNORMF   General_Contact_Faces/General_Contact_Faces` and `CPRESS   General_Contact_Faces/General_Contact_Faces`. The six upper profiles have 96, 96, 91, 94, 107 and 124 geometric nodes respectively, 608 total. Isolated rigid reference points do not count. At the last frame of Step-1 all 608 have measured zero pressure in each ODB. At the last frame of Step-2, local time 2.00 s, the following values were read independently. There are 51 frames in Step-1 and 101 in Step-2. Array index 100 names the last frame of Step-2 in all three files; native frame IDs differ.

| Reference | Native frame ID | Positive nodes across six profiles | Profile with highest pressure | Node | Station mm | Peak kPa | CNORMF at peak (Fx, Fy) N |
|---|---:|---:|---|---:|---:|---:|---|
| GENKOU | 205 | 30 | UPPER_ROOFBARA-1 | 17 | 56.405592 | 45.509089 | (+0.02160380, +0.01406746) |
| HK01 | 251 | 35 | UPPER_ROOF-1 | 44 | 28.074212 | 47.434494 | (+0.00727567, +0.02780876) |
| HK02 | 233 | 39 | UPPER_LOWER_HINGEBARA-1 | 39 | 29.612239 | 30.820487 | (−0.00152360, +0.01852310) |

The GENKOU peak profile has 124 stations, six positive readings, two separated contact patches and a full length of 73.588087 mm. The peak's displayed assembly XY at true scale is (232.088745, 194.081253) mm. The same reference data generated the [local visual example](../.local/evidence/door-panel-pressure/GENKOU-door-pressure.png). The local assets are ignored by Git. The [independent ODB reader](../scripts/reference_door_pressure.py) works directly from the original ODBs and prints per-station samples with `--samples`.

~~~powershell
Set-Location 'I:\GithubProjects\Abaqus_QualityOfLife'
$solver = 'C:\SIMULIA\Commands\abq2024.bat'
$reference = 'I:\GithubProjects\abaqussurfacePressure'
$profiles = 'UPPER_LOWER_BPLR-1','UPPER_LOWER_BPLRBARA-1','UPPER_LOWER_HINGE-1','UPPER_LOWER_HINGEBARA-1','UPPER_ROOF-1','UPPER_ROOFBARA-1'
$profileArgs = foreach ($profile in $profiles) { '--instance'; $profile }
foreach ($case in 'GENKOU','HK01','HK02') {
    $odb = Join-Path $reference ('20231129_' + $case + '.odb')
    foreach ($step in 'Step-1','Step-2') {
        $raw = & $solver python scripts/reference_door_pressure.py $odb --step $step --frame -1 @profileArgs
        $report = ($raw -join [Environment]::NewLine) | ConvertFrom-Json -ErrorAction Stop
        if ($LASTEXITCODE -ne 0 -or $report.step -ne $step -or @($report.profiles.psobject.Properties).Count -ne 6) {
            throw "Reference read failed for $case $step"
        }
        $report.profiles.psobject.Properties | ForEach-Object {
            [pscustomobject]@{ Case=$case; Step=$step; Profile=$_.Name; Nodes=$_.Value.node_count; Peak_kPa=$_.Value.peak.pressure_kPa }
        }
    }
}
~~~

### 3. Add the output to new analyses

1. Implement a default-on **Door-panel contact pressure** output for new 2D deck preparations. Record the effective setting in the submitted setup and result metadata. Keep explicit opt-outs meaningful. Define how opening an older editable setup and preparing a new deck gets the feature; historical submitted decks and extracted results keep their original output inventory. Ensure Prepare's deck fingerprint accounts for a changed output plan and preserves mesh/fixture compatibility. Surface the setting with the existing results/output controls and translate JA and EN. Keep the user's vertical workflow and existing Results actions.
2. In `packages/engineering/model.py` and `integrations/abaqus/deck.py` trace `write_inp`, `write_two_step_inp` and `output_cards`. The current output list allows five tokens and the writer only emits `CSTRESS` for contact. If adding a public token, update its validation, defaults and generated types together. Reuse the actual emitted `PANEL-1.PROFILE` connectivity for an assembly NSET named `DOOR_PROFILE_NODES`, containing every geometric door node once, excluding `PANEL_RP`. Reuse `set_lines`. In a two-step analysis include door output in **both** steps even when the body is the active actuator. Keep body and seal contact settings and R2D2 orientation intact.
3. With global stress output selected, this combination worked on the app's generated one-step deck using Abaqus/Standard 2024:

~~~text
*Nset, nset=DOOR_PROFILE_NODES, instance=PANEL-1
<geometric door labels>
** Inside the step's existing field-output block at its existing interval
*Contact Output
CSTRESS
*Contact Output, nset=DOOR_PROFILE_NODES
CFORCE
~~~

   If global `CSTRESS` is deselected and door pressure enabled, request `CFORCE, CSTRESS` together **only on the door NSET**. This combination also ran successfully in a two-step licensed pilot. The 17 door nodes reported zero pressure at the end of body seating and six positive pressures at the end of closing. The ODB recorded the first step as `Bodyseating` although the INP said `Body seating`. Use the existing step canonicalization and preserve the native key. Verify both output combinations through the integrated worker. Preserve the existing U output required for deformed anchors, or request the necessary door U once if the wider U field is disabled. Keep existing stress, RF, history and timing requests functional. Do not add `CNAREA` as a dependency of measured pressure.
4. A second licensed deck variant deliberately requested `CSTRESS` globally **and again** on the same door NSET. Abaqus completed but produced **98 CPRESS rows for 49 door nodes**, two identical samples per key. The single-request variant gave 49 pressure rows and 49 vectors. Prevent overlapping pressure requests in new decks. For an existing ODB coalesce only provably identical observations under the same complete identity; emit an ambiguity reason for conflicting observations. Never sum duplicate normal forces or take a maximum across unrelated domains. Read both named-pair and general-contact field keys. A general-contact aggregate may be presented as the total on the mapped door. Label it “door–seal” only if the submitted contact domain proves that sole counterpart.

### 4. Extract a portable, frame-aligned result

- Extend `integrations/abaqus/results.py`, `extract_odb.py` and `interchange.py`. Today `CSTRESS` expands to `CPRESS/CSHEAR1`; raw fields are keyed by their full ODB names. Capture `CNORMF` from `CFORCE`, the measured `CPRESS` and their provenance. Keep the extractor deployable under Abaqus Python with its bundled libraries. The reference reader is an independent comparison tool; the production extractor must supply the UI data.
- In the index store an additive schema/version for the profile feature, units, contact attribution, component/instance IDs and aliases, topology, ordered labels, station distances, reference geometry and validated scale range. In each existing `frame-*.json` store aligned raw pressure and force components or null per profile node, plus any field/placement availability reason. Reuse existing displacements and correct assembly placement. Keep source and display conversion identifiable. Index only the metadata and extents needed up front. Use the current frame cache and portable result members so a fresh computer can inspect an `.aqresult` without Abaqus or its source ODB. If adding sidecar members, version and validate packaging, hashes, reopen and older readers explicitly.
- A line chain may reverse in X or Y. Walk connected R2D2 edges. For disconnected chains keep separate profile IDs, origins and chart series/selections. For a closed ring define and test a deterministic seam and traversal, or report unsupported topology. For a branch, degenerate edge or multiple candidate sides require a justified mapping or an explicit unavailable reason. Preserve gaps and measured zeros. Gaps must break chart lines. Body seating, self-contact, cavity edges, material seams, inactive contact sides and the RP must never leak into a single door profile.
- Preserve existing results if new fields are missing. An old result with attributable CPRESS can show the graph even if CNORMF was never requested. CNORMF alone can report measured force in N and an unavailable pressure plot. With missing or zero-length direction suppress the arrow; if pressure was measured it still belongs on the chart. When deformed placement cannot be established, keep valid station data and explain arrow availability. Opening DEMO without measurements must report unavailable. A measured Step-1 zero profile should show a zero line and no arrows.
- For local reference acceptance, pass explicit external instance/step and N–mm unit mappings into the shared extraction path or a thin test adapter, produce a disposable result, and open it in the normal Results UI. Keep external component names and native frame IDs. Reuse `.aqresult`; a general-purpose native ODB file browser is outside this slice. Preserve raw reference files, previously submitted setups and ODBs.

### 5. Build the engineer-facing view

Add **CNORMF · Door normal contact force (N)** as a selectable result in the existing **Field** selector alongside **von Mises** and **displacement**. The current field IDs and options are in `apps/web/src/features/run/fields.ts` and `apps/web/src/RunView.tsx`. Use a nodal vector view for CNORMF. On the selected door station, show signed Fx, Fy and magnitude in N, identified by instance, node and frame. Make it available whenever the force field exists, including measured all-zero frames and frames without CPRESS. The selector must let the engineer switch back to von Mises or displacement at the same frame. Compute each result's availability independently and preserve the current default stress view when stress is available.

In `apps/web/src/RunView.tsx` add a **Door contact pressure** view next to the existing force–displacement response. Use `Plot.tsx` or its established plotting conventions for the spatial graph. Keep the existing force graph, its CSV semantics, field contours, mesh edges, material outlines and probes available. In the pressure view enable **Pressure arrows** by default with a visible toggle. If multiple profiles qualify, offer a profile selector using actual aliases. The axes must say **Distance along door panel (mm)** and **Contact pressure (kPa)**. Suggested Japanese labels are **ドアパネル接触圧**, **ドアパネルに沿った距離 (mm)**, **接触圧 (kPa)** and **接触圧の矢印**.

Use the committed, displayed frame shared by the contour, slider and step label. Update arrows and curve together on scrub, playback, step changes and delayed reads. Maintain camera and glyph scale across frames. In `viewportModel.ts`, `Viewport.tsx` and `viewportRenderer.ts` reuse the rendered geometry's world-to-screen transform. Make the overlay non-pickable, preserve CAD and element probes, and keep the white viewport. Mark the station origin or give the engineer a direction cue. A curve hover/focus or selection should identify the same station on the door and show profile name, station, pressure, native force components and units. Plotting nonuniform nodal stations with straight segments is sufficient; do not smooth through contact edges. Dense glyphs can be thinned for display if peaks/selected nodes remain findable and all measured points remain in the graph. Keep legends and both axis titles readable at 1280×720 and in Japanese.

### 6. Acceptance gates and release evidence

| Gate | Required test and evidence |
|---|---|
| A · Deck and contact identity | Compare generated one-step and body-then-door INPs. Assert the NSET equals unique geometric door nodes, excludes RPs/body/seal, and every relevant step requests the correct fields once. Cover global stress on/off and pressure on/off. Show unchanged mesh identity on output-only edits, a newly prepared matching deck, and unchanged historical INP hashes. |
| B · Numerical reference | Compare the **production** extractor against the independent reader for every station on all six profiles in all three source ODBs. At minimum include Step-1 final, Step-2 middle and final, and an initial frame with its actual availability. Compare labels, station, signed vector components, zero/null masks and pressure. For reads of the same ODB use absolute tolerances of 0.0001 mm, 0.001 kPa, and 0.0000001 N per component. Report maximum errors and their nodes; the table above is a quick cross-check. Include manufactured cases for missing fields, repeated labels across instances, duplicate/ambiguous contact domains and a bent panel with nonuniform spacing. Show that changing reporting width, RF units or Reverse Y leaves pressure and station unchanged. |
| C · Licensed current workflow | Use disposable `SEAL_DATA` and the normal API → worker → Abaqus/Standard → extractor path for one door-only run and one body-plus-door run. At least one run must have positive door pressure; include a nonvertical/curved contact normal and a frame with measured zero or verified no-contact. Show separate solver and extraction states, deck/ODB hashes, output keys, counts and a nonzero numeric comparison against the ODB reader. For the two-step case verify the door identity during body seating and closing. If invoking the panel force balance as a check, account separately for shear, inertia, sign, solver thickness and solver tolerance. An RF history alone cannot establish the local pressure field. |
| D · Arrow and graph behavior | In a real browser open the measured external reference and an app-generated run. On GENKOU select UPPER_ROOFBARA-1, find the two separated contact patches, select node 17 and recover the tabulated peak. Verify arrow direction (dot product >0.999 with normalized CNORMF in world coordinates), anchor within 2 CSS px of the rendered deformed node after pan/zoom, and scale proportional to p across two nonzero samples. Step back to a zero frame, change profiles, delay a frame fetch and play through the step transition. No stale arrows, stale curves or camera jumps. Exercise missing-only-one-field cases, mesh edges, outlines and picking. Capture JA/EN screenshots and browser assertions for numeric values. |
| E · Portability and history | Package through the worker, open the `.aqresult` in a fresh isolated data root and compare all pressure values, units, station IDs and frame order for the selected cases. Open an existing result without dedicated pressure metadata and DEMO. Check that the normal force–displacement curve, units, export and original artifacts retain their behavior. |
| F · Regression and reporting | Run the commands below. Report full-suite and targeted results separately, with names and measurements for any failures. The previous independent audit saw intermittent centered-cut/picking/material test failures and a repeatable playback cadence miss. Record any existing failures and compare frame timing with arrows off/on on the same build and data. A newly introduced failure blocks this feature's gate. Mark software rendering, actual extraction, licensed solver execution, mesh sensitivity and physical correlation separately. Archive artifact IDs and figures locally and update `agent.md`, `docs/engineering-validation.md`, the implementation report and both user guides. |

**Required end-to-end journey for gates C, D and E.** Use the same newly imported run across the following checks.

1. Launch the built QoL app on an isolated port and disposable `SEAL_DATA` with the real Abaqus launcher. `scripts/serve.py --test-data` installs a solver double for browser regression tests. For the licensed journey use normal service startup. From Dashboard click **New Model** and upload a supported CAD drawing using Import. A contact-capable DXF or DWG is sufficient for this journey. The existing `apps/web/tests/gate-a-workflow.spec.ts` and `scripts/acceptance_dwg.py` show the repo's import and worker paths. Decide the door from its assigned component role so a user-defined component name also works.
2. Assign roles and materials, generate the mesh, review mounting, and set contact and closing motion to produce contact. Leave the new output at its default. In Results properties click **Prepare input deck** and **Submit Abaqus analysis**. Use the INP actually prepared by QoL and the ODB produced by that submission. Capture drawing hash, run ID, submitted INP hash, ODB hash and result-file hash. This journey must succeed through ordinary app controls without hand-editing a deck or running a postprocessing script.
3. Independently open that new ODB read-only. On a closing frame with contact, record native field keys for S, U, door CNORMF and CPRESS. At the same door node record signed force components, magnitude, pressure and station. Confirm the configured RF/LE outputs are still present. In QoL Results, switch **von Mises → displacement → CNORMF** at that frame and inspect the node. Match its force to the ODB in N; switch to the pressure view and match its graph point in mm and kPa. Check each arrow's units and direction in its own view. Include the zero-contact frame and explicitly verify the existing force–displacement response.
4. Open the worker-produced `.aqresult` in a fresh QoL data root with only the result file available. Repeat the same field selections and node comparison. Report the ODB, live UI and reopened UI readings side by side under the same run, frame, instance and node IDs. Gates C–E require this evidence in addition to the external reference checks.

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\schema.py
npm --prefix apps/web run test:i18n
npm --prefix apps/web run test:encoding
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
npm --prefix apps/web run test:browser
git diff --check
~~~

Set a free `SEAL_TEST_PORT` for the isolated browser suite. Record the candidate build and frontend release used by the browser, not just the Git SHA. Use the supplied ODBs as external reference observations, the scratch pilot as keyword evidence, and the new API-to-UI runs for delivery acceptance. Put proprietary fixtures, generated decks/ODBs and logs only in local ignored storage.
