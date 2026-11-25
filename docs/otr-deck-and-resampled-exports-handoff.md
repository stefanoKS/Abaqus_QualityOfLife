# OTR deck preparation and resampled result exports

## Command for the execution agent

In `I:\GithubProjects\Abaqus_QualityOfLife`, read `AGENTS.md`, `agent.md` and this brief. Start from the current working tree, including the existing door-pressure implementation. Deliver both OTR drawings through **Import → Components → Materials → Mesh → Mounting → Contact/Motion → Results → Prepare input deck**, correct the misleading failed-deck message, and add two CSV downloads in Results. Load uses a user-editable **1.0 mm** stroke interval by default. Door surface pressure uses a separate user-editable **1.3 mm** station interval. Use the measured results of the selected run. Complete gates A–E and record the evidence. This investigation used `001d2db` plus the uncommitted pressure delivery.

## 1. Reproduced failure

The retained worker logs for OTR job `4027e862-afe2-4e52-8814-7216baf1c101` and OTR_single job `1a3fee80-8f00-414f-ae71-fdec24497cd3` show `write_two_step_inp → _mesh_parts → panel_order(body, nodes)`, followed by **“The vertical closing template requires a panel without a folded-back profile.”** The retained single-cavity attempts used earlier saves of the drawing. Both files currently in `examples` reproduced the same error independently through native import, mesh, reviewed fixture and the DECK worker.

| Current drawing | SHA-256 | Filled seal / cavities | Door / body IDs observed in the audit | Prepare |
|---|---|---|---|---|
| `OTR.dwg` | `aacc24c7ae1a8cf886b376f6049a467ee59025de17adddd5fde0822d43aa11f6` | 1 / 2 | upper `section2` / lower `section3` | Failed in body profile ordering |
| `OTR_single.dwg` | `52c9e554a722a137bfcde999e608a2e6a2535bd70e78072cfa48d43ca9a88a35` | 1 / 1 | upper `section3` / lower `section2` | Same failure |

Both imports identified mm units. On each file the upper and lower rigid CAD components each contained three lines and three arcs. The meshed door was an open, simple 95-element R2D2 chain. The body was an open, simple 71-element chain with two endpoints, maximum vertex degree two and length **27.388 mm**. Following the body from its right-hand endpoint, five elements turned toward increasing X, by **0.2311 mm in total**. That trips the legacy global-X rule. Select the parts by drawing geometry and assigned role; ordinal `section2` changes meaning between files.

In the independent runs, readiness reported `can_prepare=true` and `mounting.reviewed`. The saved 11-node fixture's hash equalled the hash captured by the failed deck for each file. The shipped acceptance harness also reproduced this with its single lowest-node fixture. Abaqus was never started. In a geometry-only check using the correctly connected panels, the current directional assessor predicted an intersection with the initial seal at about 4.85 mm of downward door travel and 8.19 mm of upward body travel on separate 10 mm sweeps. These are geometric checks on the undeformed seal; the submitted two-step analysis is what determines actual pressure and force.

Reproduce the two failures from the repo root. Each invocation uses a fresh local data directory. Run these commands before and after repair.

~~~powershell
$evidence = Join-Path $env:TEMP ('aqol-otr-' + [guid]::NewGuid().ToString('N'))
foreach ($case in 'OTR','OTR_single') {
    & .\.venv\Scripts\python.exe scripts\acceptance_dwg.py --drawing "examples/$case.dwg" --evidence (Join-Path $evidence $case)
    Write-Output "$case exit code $LASTEXITCODE"
}
~~~

### Geometry and status repair

1. In `integrations/abaqus/deck.py` separate **topological ordering** from **contact-side orientation**. `panel_order` currently rejects equal-X endpoints and each increase in X during traversal. `_mesh_parts` applies it to both rigid parts before the v4 directional assembly assessment runs. For supported 2D directional motion, walk the adjacency of each open connected R2D2 profile and visit every original element exactly once. Support a local return in X, vertical portions, and vertical endpoints. Preserve element identities, node labels, curved shape, mesh, CAD role and fixture. Align the deterministic endpoint convention with `integrations/abaqus/door_pressure.py` where appropriate. Keep station order independent of the connectivity reversal that selects the physical SPOS face.
2. Reject actual topology errors with the role and actionable reason: branches, disconnected islands within a required single profile, repeated/degenerate elements and unsupported self-intersections. Keep checks for penetration, ambiguous contact side and invalid motion. Audit `orient_toward`, `surface_normal` and the directional clearance/sweep helpers. Independently check local SPOS normals at the predicted first-contact neighborhoods of the door and body against the seal-facing side. A single global average is insufficient evidence on a curved return. Preserve legacy deck behavior for supported historical inputs, including existing flat, sloped, top/bottom and angled cases; keep submitted decks and results immutable. Increasing the X tolerance, sorting elements by X, flattening the CAD or exploding polylines would conceal the observed defect.
3. In `services/readiness.py`, `_assembly` catches ordinary `ValueError` and returns an error payload without a blocking finding, so the app can say “Ready to prepare” while the writer deterministically rejects the same geometry. Use shared, typed preparation errors with a stable reason, role and owning stage. Make readiness and deck execution agree. If the asynchronous worker fails for another reason, preserve the job diagnostic and point the engineer to the failed stage or log. Keep retry available when appropriate.
4. In `apps/web/src/features/workspace/AnalysisActions.tsx` the current `deckReady ? inputReady : deckStale` branch calls every nonready deck “The fixed nodes changed.” Bind the message to actual status and readiness codes. Distinguish missing, queued/running, completed/current, failed, superseded mesh, and verified `deck.stale_fixture`. For a failure with an unchanged fixture show the actual failure and recovery. Keep Submit disabled until the matching deck is current. Verify English and Japanese.

## 2. CSV contract

Provide two discoverable actions next to their respective Results graphs. Each takes an independent positive, finite spacing in **mm**. Show the selected panel/step for load and the selected door profile/step/displayed frame for pressure. A user can change the spacing before downloading. Export from the immutable data already available to Results and to a reopened `.aqresult`. The existing raw `history.csv` remains the original time-history download.

| Export | Exactly two rows, labels in column A | Source of numeric columns |
|---|---|---|
| Load | A1 `stroke(mm)`. A2 `F (N/100mm)` for the default 100 mm represented width. | Selected step's panel, paired step-relative U magnitude in mm and signed reaction projected along that panel's prescribed motion. Reuse the result's recorded force basis and the current export's Reverse Y convention. |
| Door surface pressure | A1 `door station(mm)`. A2 `CPRESS (kPa)`. | Cumulative station on the selected door profile versus its door-side nodal pressure at the **displayed** frame. Export the scalar in kPa and retain measured zeros. |

Use two equally long comma-delimited rows, decimal points, UTF-8, CRLF, and no extra title, time column or metadata rows. Numeric samples start in column B. Preserve enough significant digits for engineering comparisons; avoid negative zero and floating-point artifacts in station labels. Keep unit labels stable in both locales. Put contextual metadata in the UI and a filesystem-safe filename, including run, step/panel or profile/frame, interval and applicable force basis/sign.

**Load basis.** Follow `twoRowExport` in `apps/web/src/RunView.tsx` for the meaning of U: `hypot(U1−U1_start, U2−U2_start)` for the selected step, using a valid common reference sample. Force is the corresponding instance's step-direction projection already normalized by `align_histories` in `integrations/abaqus/interchange.py`. A body seating step uses the body's own history and vector. Preserve the present positive stroke axis on Reverse X; apply the displayed Reverse Y exactly once to force. When the result represents 80 mm, write `F (N/80mm)` with its actual force values; for per-mm use `F (N/mm)`. A legacy result with known force in N but unknown represented width uses `F (N)`. Do not silently relabel all runs “100 mm” or rescale an already width-adjusted force a second time. Display the actual selected basis before export.

**Pressure source.** Reuse the station axis under `index.door_pressure.profiles` and the matching `frame.door_pressure.profiles[profileId].pressure_kpa` array. Match by profile ID, ordered node identity and displayed frame. `fields.CNORMF` contains forces in N; it cannot supply a pressure sample. The reporting width, force sign toggle and current glyph scale do not change pressure. For pending frame loads, export the frame that is still visibly displayed, with that frame in the filename, or keep the action disabled during the transition. Missing profile, missing/ambiguous pressure, mismatched arrays or unavailable legacy/DEMO data need an explanatory state. A measured all-zero profile is a valid export.

### Resampling rule

1. Use evenly spaced positions `q = k × Δ` from zero. Include positions within the measured domain and append the exact last measured stroke/station once if it falls between grid points. For 2.5 mm stroke and 1 mm spacing return `0,1,2,2.5`. For 3 mm length and 1.3 mm spacing return `0,1.3,2.6,3`. When the end falls on the grid within a small, documented floating-point tolerance, snap it and write it once. Construct grid points from integer indices. Show the endpoint rule next to the interval controls or in the guides.
2. At a measured coordinate use its measured value. Between two adjacent valid samples at `x0 < q < x1` use `y(q) = y0 + (y1−y0) × (q−x0)/(x1−x0)`. Interpolate against **stroke** for load and **arc-length station** for pressure. Abaqus frames are irregular in time and FE nodes are irregular in space. Averages by row number, nearest-frame selection and interpolation in global X give different answers.
3. Keep zero distinct from missing. A zero pressure on each side of a physical gap in contact remains zero. With null samples or known gaps, leave affected output cells empty; never remove the nulls and interpolate across them. Keep separate steps, profiles and mesh chains separate. Do not extrapolate outside measured support or invent a zero load at the origin. A coarser pressure grid can miss a real narrow peak; offer original nodal/sample positions as an alternative, and preserve their measured peak there. Never insert an off-grid peak into the uniform interior grid without identifying it.
4. Keep load samples in acquisition order. Identical repeated strokes carrying the same value can coalesce. A dwell with materially different loads at the same stroke or an unload/reload creates a multivalued curve. For this slice, explain why uniform export is ambiguous and offer the original ordered samples, or provide explicit monotonic branch selection. Never sort by stroke and silently average distinct physical states. Validate both controls for blank, zero, negative and nonfinite spacing and avoid unbounded allocation on impractically small values.

### Measured download checks

These values were computed independently from existing result packages. Use them to catch incorrect units, double force scaling and nearest-node substitutions.

- At the accepted licensed run `9efc065a-805c-4215-b651-3349f6ebba24` (under `.local/gate-c/results`), the 1 mm Closing load export in default sign and W=100 mm should be numerically equivalent to:

~~~csv
stroke(mm),0,1,2,2.5
F (N/100mm),0,0,8.26096907258,51.3679385185
~~~

- With a custom **0.65 mm** stroke interval, the same run must produce **5.6135701740 N/100mm at 1.95 mm**. The adjacent measured strokes are 1.8999999762 and 2.0 mm; their forces are 2.9661700130 and 8.2609690726 N/100mm. This case exercises load interpolation between solver frames.
- The same run's last door frame has a 24 mm profile. At 1.3 mm spacing, interpolating between measured stations 11.5 and 12 gives **67.1798393130 kPa at 11.7 mm**. At 13.0 mm an exact sample is **125.8664876223 kPa**. At 14.3 mm the answer is **52.4925112724 kPa**; at the appended endpoint 24.0 mm it is **0 kPa**.
- From `.local/evidence/door-panel-pressure/GENKOU-reference.aqresult`, Step-2 final, `UPPER_ROOFBARA-1`, the 1.3 mm grid gives **17.0842183789 kPa at 35.1 mm**, **0 at 45.5 mm**, and **14.0379243522 kPa at 55.9 mm**. Last station **73.5880868374 mm** appears exactly once; pressure there is zero. Original-nodes export retains the measured 45.509089 kPa peak near 56.405592 mm. Keep the proprietary packages local; use manufactured fixtures with the same edge cases in CI.

## 3. Acceptance gates

| Gate | How to prove it |
|---|---|
| A · OTR workflow | Run the two commands above and repeat both drawing imports in the built browser app on a disposable data root. Set the actual upper door, lower body and seal roles; assign a material to the filled seal, keep cavities empty, generate mesh, save reviewed WS fixture nodes, configure two-step motion and click Prepare. Cover the operator's upward-body/downward-door 10 mm settings. Require a completed DECK, Inspect/Download working, and Submit enabled with valid run name/CPU and the configured solver. Parse the actual INP: correct WSFIX labels, all original door/body R2D2 IDs/connectivity up to orientation, correct SPOS sides, sections and cavities, both steps, contact pairs and requested pressure output. Confirm the user can leave the original DWGs untouched. A completed input deck and solver convergence are separate results. |
| B · Geometry and diagnosis regressions | Test shuffled/reversed element input, the curved return and vertical cases, straight and angled legacy cases, plus genuinely invalid branch, disconnected and intersecting profiles. Test identical fixture, genuinely changed fixture, worker failure and superseded mesh. Take JA/EN screenshots or browser assertions that show the specific reason; “fixed nodes changed” must occur only on a proven mismatch. Check Prepare's readiness against the worker result for the same inputs. |
| C · Load CSV | Download real browser bytes at 1 mm and a custom spacing. Assert exact first-column labels, row/column counts, correct width and signed projected load for angled and body steps, Reverse Y once, exact and off-grid endpoints, null gaps, repeated stroke and reversal. Compare the accepted licensed package against the values above. Replace the obsolete numeric-only row assertions in `apps/web/tests/curve.spec.ts`; keep the missing-versus-zero and per-step tests in `gate-d.spec.ts` and `force-axis.spec.ts` meaningful. |
| D · Pressure CSV | Download for the selected profile and displayed frame at 1.3 mm, another spacing and original nodes. Compare the values above within 0.001 kPa and stations within 0.0001 mm. Include non-axis-aligned profiles, a nonuniform mesh, separated pressure patches, all-zero, missing/ambiguous samples, switching profile, and scrubbing with an in-flight frame fetch. Assert the chart, download values and filename identify the same frame. |
| E · Portability and delivery | Repeat both downloads after opening the same `.aqresult` in a fresh data root; for matching selections and settings require numerically identical CSVs. Verify a legacy result with load only, and confirm the original result frames, `history.csv` and result package hashes remain unchanged. Run Python, translation/encoding checks, typecheck, build, targeted browser cases and the full isolated browser suite. Record build ID, drawing hashes, mesh/fixture/deck IDs, representative CSVs and pass/fail by gate. Update `agent.md`, implementation report and both user guides. Record any newly executed licensed case separately. |

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix apps/web run test:i18n
npm --prefix apps/web run test:encoding
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
npm --prefix apps/web run test:browser
git diff --check
~~~

Use a free `SEAL_TEST_PORT` for browser tests. Regenerate the frontend schema if an API contract changes. The isolated diagnostic baseline for this brief was **55 passing** existing tests across `test_readiness_actions.py`, `test_two_step.py` and `test_door_pressure.py`. Both native OTR preparations failed reproducibly before solver submission.
