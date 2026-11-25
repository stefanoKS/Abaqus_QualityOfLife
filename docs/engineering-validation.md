## Native failure and partial-result recovery · 2026-11-26

This section supports the [partial-results execution handoff](partial-results-arrows-multiplier-handoff.txt).
It records three **native** Abaqus/Standard 2024 cases and distinguishes them from manufactured test
evidence. No operator run on port 8765 was contacted. Source ODBs, locks, decks and retained packages
were copied into ignored `.local` evidence roots; every source artifact was read-only.

### A. Retained cancelled ODB re-read through the production extractor — native, cancelled

| Item | Measured value |
|---|---|
| Source job | `313893f2-7a6a-46ab-acb6-a1878922150f` (recorded solver Cancelled, extraction Pending) |
| Source ODB SHA-256 / bytes | `5faf3255638e3cb033f1bd45b2b0ee6c9fa3bf38b3f0f94e430b036c45f528ea` / 40,894,464 |
| Source lock | retained, mtime unchanged after the read |
| Extractor | installed Abaqus 2024 Python, read-only copy, exit **0** in 12.9 s |
| Frames / last ordinal | **43** / **42** (native frame ID and increment **162**) |
| Last saved time | **0.8399999737739563 s** (total), local 0.8399999737739563 s |
| Availability | **partial** (solver outcome Cancelled) |
| Node / station | PANEL-1 node **238**, station **17.5 mm** |
| CPRESS | **2.8307080268859863 MPa = 2830.7080268859863 kPa** |
| CNORMF | **(0.00834000576287508, 1.4145596027374268) N** |
| Index SHA-256 | `4d782a4c1ec0e29c79f4e0c3982a4c0f8d754511881d7b772ddb13609384089d` |
| Partial package | `…-partial.aqresult`, SHA-256 `7fa5545cdf3361e34330f8e4f76e76021f57ee7e729afc71729e2fd81268229e` |
| UI (Results) | `43 / 43`, frame time **0.840 s**, node 238 / 17.5 mm / 2830.7080268859863 kPa / native 2.8307080268859863 MPa / Fx 0.00834000576287508 / Fy 1.4145596027374268 |
| Reopened package | `43 / 43` and the same reference measurement in a fresh data root |

This proves recovery of a native cancellation; it is **not** a failed-solver case.

### B. Bounded native failed one-panel Closing case — genuine solver failure, usable ODB

Deck: the application-generated `synthetic()` one-panel deck, unchanged except `inc=100` and
`time interval=0.01` (the output/increment contract Abaqus requires). Abaqus accepted **100**
increments (11 cutbacks, 288 iterations) and terminated with `**ERROR`/`THE ANALYSIS HAS NOT BEEN
COMPLETED`; `analysis.sta` never reports completion. The batch wrapper returned process exit **0**
even though `launcher.solver_evidence` returned **False** (“Abaqus reported an analysis error”), so
the solver outcome is taken from the evidence, not the wrapper exit code.

| Item | Measured value |
|---|---|
| INP SHA-256 | `04a7950d2aac1c26197fac9ae0841d08dbd3d75713cae7e87fa4caff6c2ac66d` |
| ODB SHA-256 / bytes | `184ef76d9f33563f61e058b011de4dd305dcdf1bf118d09f8881d05633a72c42` / 5,334,008 |
| Solver exit / evidence | **0** / **failure** (2 error messages; last status line `THE ANALYSIS HAS NOT BEEN COMPLETED`) |
| Extraction exit | **0** in 16.2 s |
| Frames / last ordinal | **65** / **64** (native frame ID 100, increment 100) |
| Last saved time | local **0.6324414014816284 s**; total **0.6324414014816284 s** |
| Availability | **partial** |
| Reference node / station | node **264**, station **19.5 mm** |
| CPRESS | **0.17752908170223236 MPa = 177.52908170223236 kPa** |
| CNORMF | **(−0.0006900692242197692, 0.08880005031824112) N** |
| Package SHA-256 | `338f47000e5e99eda1d32fbbcdc3d8513ebeb624dca050083f983693de3137ea` |
| UI / reopened | `65 / 65`, **0.632 s**, same node/station/pressure/force |

### C. Bounded native failed two-panel Closing case — genuine solver failure after Body seating

The `two_panel_section()` deck was bounded only in its **Closing** step (`inc=150`, output interval
0.01 s); Body seating kept its original output plan. Abaqus completed Body seating, accepted 150
Closing increments (22 cutbacks) and then failed. The last saved step is Closing, not Body seating.

| Item | Measured value |
|---|---|
| INP SHA-256 | `0a1c9db1ea737d4434e672dc8b0a7c6c84efacf59455b4816f9a243cb9e8012c` |
| ODB SHA-256 / bytes | `93b266d49ed8ed1906a6701427f054caf6c3e6277bf1ec42e4d4fe2b46869c5a` / 10,896,548 |
| Solver exit / evidence | **0** / **failure** (`THE ANALYSIS HAS NOT BEEN COMPLETED`) |
| Extraction exit | **0** in 35.7 s |
| Frames / last ordinal | **136** / **135** (native frame ID 150, increment 150) |
| Last closing time | local **0.8334758877754211 s**; total **1.8334758877754211 s** |
| Availability | **partial** |
| Reference node / station | node **266**, station **19.5 mm** |
| CPRESS | **0.17229050397872925 MPa = 172.29050397872925 kPa** |
| CNORMF | **(−0.0005710562109015882, 0.08619822561740875) N** |
| Package SHA-256 | `dfa2b4aa48344d610e72e6ec3731aaa33da4511c33c092c01fb6a56e5f81266f` |
| UI / reopened | `136 / 136`, **1.833 s**, same reference |

### D. Manufactured evidence (separate)

Gate 1 lifecycle cases use `tests/fake_abaqus.py` and `tests/manufactured_results.py`; every artifact
is labelled `MANUFACTURED TEST EVIDENCE - not an Abaqus analysis.` They exercise partial publication,
history-only, initial-only, unreadable tail, retry/cancel and portable reopen. They are **not** solver
evidence and are not mixed with A–C.

### Commands actually run

~~~powershell
.\venv\Scripts\python.exe scripts\gate2_native_partial.py --source .local\gate-c\data\jobs\313893f2-7a6a-46ab-acb6-a1878922150f --evidence .local\evidence\gate2-native-partial
.\venv\Scripts\python.exe scripts\gate2_native_failed.py --case one --evidence .local\evidence\gate2-native-failed-one
.\venv\Scripts\python.exe scripts\gate2_native_failed.py --case two --evidence .local\evidence\gate2-native-failed-two
~~~

Each script writes its full report, ODB hash, frame identity, reference measurement, exit statuses,
log tails and a `-partial.aqresult`. The browser evidence (`apps/web/tests/native-partial.spec.ts`)
then opens Results and the packaged file and writes the measured UI coordinates to `ui.json`.

# Engineering validation

## Readable field output from a cancelled Closing run · 2026-11-26

This reference supports the [partial-results execution handoff](partial-results-arrows-multiplier-handoff.txt). The isolated job database records `313893f2-7a6a-46ab-acb6-a1878922150f` as solver Cancelled and extraction Pending. Its last retained status line reports step time 0.855 s. The cancelled-run ODB has SHA-256 `5faf3255638e3cb033f1bd45b2b0ee6c9fa3bf38b3f0f94e430b036c45f528ea` and size 40,894,464 bytes. The inspection used a copy of the ODB and opened it with `readOnly=True` under the installed Abaqus 2024 Python. The original directory contains a retained lock file.

| Native Closing output | Read from the copy |
|---|---|
| Last saved field frame | 43 frames, final ordinal 42, native frame ID 162, increment 162 |
| Local and cumulative time | 0.8399999737739563 s, step start 0 s |
| Selected door profile | PANEL-1, 49 nodes over 24 mm, 26 nodes with positive pressure |
| Peak node | 238 at station 17.5 mm, deformed XY (5.5, 8.53999996185) mm at true scale |
| Nodal CPRESS | 2.83070802689 MPa, equivalent to 2830.70802689 kPa |
| Signed nodal CNORMF | (0.00834000576, 1.41455960274) N |

A direct `odbAccess` read enumerated steps, frames, increments and field values. A second check used `abq2024 python scripts/read_app_odb_node.py <copied-analysis.odb> --step Closing`. These measurements establish native output available for recovery from this retained cancellation. Verification of the proposed app workflow and separate failed-solver cases remains pending. This inspection launched no solve.

## OTR curved-profile decks and resampled exports · 2026-11-26

The [execution brief](otr-deck-and-resampled-exports-handoff.md) defines the slice. **No solver was
launched for this delivery.** The deck path is input-generation evidence; the numerical export checks
re-read two already accepted licensed result packages. Solver convergence, mesh/stroke sensitivity
and physical correlation remain separate, unestablished work.

### OTR geometry and generated decks — PASS

The original `examples/OTR.dwg` (`aacc24c7…`) and `examples/OTR_single.dwg` (`52c9e554…`) imported
through the normal API → worker → DXF/DWG path and produced completed two-step decks. The upper
profile is the door and the lower profile is the body; the CAD component IDs swap between files
(`section2`/`section3`), so the roles were selected by measured mean Y, never by ordinal.

| Case | Door/body components | Door / body R2D2 elements | Deck SHA-256 | WSFIX labels |
|---|---|---|---:|---|
| OTR | `section2` / `section3` | 95 / 71 | `1521a89c0278…` | 26, 27, 248–254, 258 (10) |
| OTR_single | `section3` / `section2` | 95 / 71 | `b57c0c0be182…` | 52, 53, 414–420, 424 (10) |

The body chain is an open, simple 71-element R2D2 profile of length 27.388 mm and includes a local
return in X. The generated deck keeps every original R2D2 element ID and node identity; only the
per-element node order may reverse to select SPOS. Both decks contain one `*Solid Section` for the one
filled region and none for the cavities, `Body seating` then `Closing`, door–seal and body–seal pairs
plus seal self-contact, and `*Contact Output, nset=DOOR_PROFILE_NODES` with CFORCE alongside global
CSTRESS.

The independent local SPOS check recomputed each normal from the generated connectivity and compared
it with the direction to the nearest seal segment in the predicted first-contact neighborhood:

| Part | Closest separation | First-contact elements | Minimum local dot |
|---|---:|---:|---:|
| PANEL (door) | 4.6816 mm | 10 | **+0.922995** |
| BODY (body) | 2.3023 mm | 8 | **+0.859663** |

The geometry-only sweep predicts first contact at **4.8487 mm** of the 10 mm downward door stroke and
**8.1912 mm** of the 10 mm upward body stroke. These are undeformed-seal geometric checks, not solver
contact or convergence.

### Load CSV — numerical reference — PASS

Real browser downloads from the accepted licensed run `9efc065a-805c-4215-b651-3349f6ebba24`
(Closing, default sign, represented width 100 mm):

| Stroke (mm) | 0 | 1 | 2 | 2.5 |
|---|---:|---:|---:|---:|
| Reference F (N/100mm) | 0 | 0 | 8.26096907258 | 51.3679385185 |
| Downloaded F (N/100mm) | 0 | 0 | 8.26096907258 | 51.3679385185 |

At the custom 0.65 mm interval the grid is `0, 0.65, 1.3, 1.95, 2.5`; the downloaded value at
**1.95 mm** is **5.61357017395 N/100mm** (reference 5.6135701740), interpolated between the measured
strokes 1.8999999762 (2.9661700130) and 2.0 (8.2609690726). The exact end 2.5 mm is appended once.

### Door pressure CSV — numerical reference — PASS

`9efc065a` final Closing frame, 24 mm profile, 1.3 mm interval:

| Station (mm) | 11.7 | 13.0 | 14.3 | 24.0 |
|---|---:|---:|---:|---:|
| Reference CPRESS (kPa) | 67.1798393130 | 125.8664876223 | 52.4925112724 | 0 |
| Downloaded CPRESS (kPa) | 67.179839313 | 125.866487622 | 52.4925112724 | 0 |

The 24.0 mm measured endpoint appears exactly once. Original profile nodes retain the measured peak
**165.369302 kPa at 13.5 mm**.

`GENKOU-reference.aqresult`, Step-2 final, selected `UPPER_ROOFBARA-1` (non-axis-aligned,
nonuniform 73.5880868374 mm profile):

| Station (mm) | 35.1 | 45.5 | 55.9 | 73.5880868374 |
|---|---:|---:|---:|---:|
| Reference CPRESS (kPa) | 17.0842183789 | 0 | 14.0379243522 | 0 |
| Downloaded CPRESS (kPa) | 17.0842183789 | 0 | 14.0379243522 | 0 |

The last station appears once. Original profile nodes retain the measured **45.5090888 kPa peak at
56.405592 mm** and show nonuniform station spacing.

### Portability and immutability — PASS

The retained live job `9efc065a` in a copied data root and the same `.aqresult` reopened in a fresh
disposable root produced **byte-identical** load (0.65 mm) and pressure (1.3 mm, final frame) CSVs.
The `.aqresult` SHA-256, the live `results.json` and the live `history.csv` were unchanged after both
reads and downloads. A manufactured legacy load-only result exported `F (N)` correctly and showed
pressure unavailable.

### Regression suite — PASS with known suite-load cases

Final build `c4081e11df79`: Python **391 passed, 1 skipped**; translations 1045 keys; encoding 48
files; typecheck/build pass. The full isolated browser suite was **186 passed, 4 failed, 10 skipped**
(200 tests, 22.8 min). The four failures are the previously recorded suite-load cases (`gate-f`
playback cadence, `motion-preview` body/door, `offset-picking`, centred `partition` mixed draft); a
combined isolation rerun gave 8 passed, 1 skipped and `offset-picking`, and `offset-picking` passed
alone in 16.1 s. None is an OTR-deck or export regression.

Local detail: [deck summary](../.local/evidence/otr-deck-exports/deck-summary.json),
[Gate A OTR proof](../.local/evidence/otr-deck-exports/gate-a-otr.json),
[acceptance log](../.local/evidence/otr-deck-exports/acceptance.log), representative downloaded CSVs
under `.local/evidence/otr-deck-exports/`, and `browser-full.log`.


## Door-panel contact pressure implementation · Gates A–F · 2026-11-25

The [execution brief](door-panel-pressure-handoff.md) defines the feature. This delivery was
implemented on the working tree after `001d2db` and exercised against the three supplied
Abaqus/Standard 2023 ODBs and new licensed Abaqus/Standard 2024 runs. **Solver execution, extraction
and the local numerical/UI acceptance are separate evidence from mesh sensitivity and physical
correlation, which remain unestablished.**

### Gate A · Deck and contact identity — PASS

The generated one-step deck for the 49-node panel profile contains exactly one
`*Nset, nset=DOOR_PROFILE_NODES, instance=PANEL-1`; the set equals the unique geometric R2D2 nodes,
excludes `PANEL_RP`, seal and body nodes. With global stress on it requests `*Contact Output \n
CSTRESS` once and `*Contact Output, nset=DOOR_PROFILE_NODES \n CFORCE` once; with global stress off
the door set requests `CFORCE, CSTRESS` together. `U` is present in `*Node Output`. The two-step deck
has the same request in both `Body seating` and `Closing`, and the body profile never appears in the
door set. An output-only opt-out and re-opt-in left `mesh_compat` unchanged; the opt-out deck hash
differed, the original INP bytes stayed identical, and the re-opted deck returned to the exact
original SHA-256.

| Case | Door nodes | Steps | Original INP SHA-256 | Door output off | Re-opt-in |
|---|---:|---:|---|---|---|
| one-step hollow | 49 | 1 | `c2c54ab272f5…` | `66796f0b7034…`, no door set | byte-identical to original |
| body-then-door | 49 | 2 | `d9842ffd2cae…` | `bbbb65d2757f…`, no door set | byte-identical to original |

Local detail: [gate-a-deck.json](../.local/evidence/door-panel-pressure/gate-a-deck.json).

### Gate B · Numerical reference — PASS (exact)

The production extractor (`scripts/reference_extract.py`, shared `extract_odb`/`door_pressure`
modules) was run under Abaqus Python 2024 against all three supplied ODBs. The independent reader
(`scripts/reference_door_pressure.py`) was run separately at Step-1 final, Step-2 initial, Step-2
middle (array index 50) and Step-2 final. All **608 stations × 12 frames = 7,296 station samples**
matched on labels, station, pressure, both signed `CNORMF` components and null masks. Maximum
absolute differences were **0 mm station, 0 kPa pressure and 0 N force component**; the required
tolerances were 0.0001 mm, 0.001 kPa and 0.0000001 N. Positive-node counts were 30 / 35 / 39 at the
three final frames, matching the handoff. Native frame IDs (205, 251, 233 at the final Step-2 frame)
and times were retained.

| Case | Step-1 final (native) | Step-2 initial | Step-2 middle (native) | Step-2 final (native) | Positive nodes (final) |
|---|---:|---:|---|---:|---:|
| GENKOU | 0 kPa (117) | 0 kPa (0) | 608 stations (77) | 30 positive (205) | 30 |
| HK01 | 0 kPa (116) | 0 kPa (0) | 608 stations (110) | 35 positive (251) | 35 |
| HK02 | 0 kPa (120) | 0 kPa (0) | 608 stations (100) | 39 positive (233) | 39 |

The production frame `door_pressure` arrays retain the native `pressure_mpa` and the display
`pressure_kpa`, `CNORMF` components, per-node ambiguity entries, per-profile orientation/stations and
the two MPa→kPa units. Local detail:
[gate-b-comparison.json](../.local/evidence/door-panel-pressure/gate-b-comparison.json).

### Gate C · Licensed current workflow — PASS (small synthetic case)

Two isolated licensed runs were completed through the normal browser workflow
(Dashboard → New project → Import DXF → roles → materials → mesh → fixture → motion → Prepare →
Submit) on disposable `SEAL_DATA`. The accepted run
`9efc065a-805c-4215-b651-3349f6ebba24` used the 24 mm imported door profile, a 2.5 mm closing stroke
over 0.5 s, default reporting width 100 mm and solver thickness 1 mm. Solver and extraction both
succeeded; exit codes 0/0. It produced 26 frames. The deck requested `CFORCE` once on the door set
and global `CSTRESS`, with `U`; no duplicate pressure request was present. The ODB contains one
`CPRESS` and one `CNORMF` field key (`General_Contact_Faces/General_Contact_Faces`) and the
pointed-at node 230, station **13.5 mm**, measured **165.36930203437805 kPa** native
**0.16536930203437805 MPa** with `CNORMF` **(2.5648099835962057e-05, 0.08260141313076019) N**.
Eleven door nodes were positive and the UI drew 11 arrows. The first attempt with a 6.5 mm stroke
(`313893f2-…`) was cancelled at step time 0.855 after 1461 increments without a completed result and
is not acceptance evidence.

| Artifact | Value |
|---|---|
| Run | `9efc065a-805c-4215-b651-3349f6ebba24` |
| Submitted INP SHA-256 | `58b467ad206c1378df164ac11ad72a103e56a6a2bca460a5f4cfe35c8e3f0ba0` |
| ODB SHA-256 | `b0eddc73e5f4108d88ce8a0b4c618ef894b3b539c0c1d2a8d57e7242d9f01645` |
| Results index SHA-256 | `bf69102fb3b2ee010f8adcdbf5a6c262aac30f569896f1ada8b6b2fc4ecd729b` |
| `.aqresult` SHA-256 | `7b6e159754b54dbbfeed3b3877a621ec974db7fbddd96d931a44c0ab95d22073` |

The same nonzero node was read directly from the ODB (`scripts/read_app_odb_node.py`, Abaqus Python
2024), from the live Results artifacts and from the reopened `.aqresult`: pressure, native MPa and
both force components were bit-identical (differences 0.0). Local detail:
[gate-c-evidence.json](../.local/gate-c/evidence/gate-c-evidence.json) and
[gate-c-odb-node.json](../.local/gate-c/evidence/gate-c-odb-node.json).

The required **body-plus-door** case was also executed through the same API → worker →
Abaqus/Standard → extractor path in a second isolated root: run
**`25fa7055-7cbe-4b20-9257-f1f5841525b6`**, 4.0 mm body seating / 2.5 mm door closing at 0.4 s each,
42 frames (21 per step), solver and extraction exit 0/0. The deck requested door output in both
steps. The door profile has 49 stations; Body seating had **zero** positive door pressure and
Closing had 9 positive stations. The final closing peak was node 250 at station **11.5 mm**, native
**0.005145416595041752 MPa** = **5.145416595041752 kPa** with CNORMF
**(−3.088685787133727e-07, 0.002571261487901211) N**. INP SHA-256
`24f990cdf3698f28342c64d6c1686d98ad2d8173dc5d1aabd89b573619c35acc`; ODB
`9194b691d804bb1da315828dec5ab0364b5b930a123739bd6bbcc49162eea33b`; index
`46467c0f23fbc566d4ceeefd2dfdc8bb58d30febfffe2b9ff756fa3bf4720859`. Local detail:
[gate-c-twostep.json](../.local/gate-c/gate-c-twostep.json).

### Gate D · Arrow and graph behavior — PASS (browser)

A disposable result packaged from the supplied GENKOU ODB (`scripts/reference_extract.py` plus the
portable container) was opened in the normal Results UI. The profile selector exposed all six upper
profiles. On `UPPER_ROOFBARA-1` the final Step-2 frame had 124 stations, **6 positive stations in two
separated patches**, no null gaps and a run-wide maximum of 46.5045 kPa. Selecting the graph point at
node 17 recovered station **56.405592 mm**, **45.509089 kPa**, native **0.045509089 MPa** and
`CNORMF` **(0.021603798, 0.014067459) N**; the plotted arrow direction dotted with the normalized
world force above 0.999. The glyph anchor matched the independently re-projected deformed node
within the 2 CSS px requirement. A measured-zero frame (array index 50) showed a zero line and zero
arrows; step transition, a delayed frame fetch, profile changes and playback kept the arrows, graph,
frame label and camera together. At 1280 × 720 both axis titles remained inside the viewport. Local
screenshots: [EN](../.local/evidence/door-panel-pressure/gate-d-genkou-en.png) and
[JA](../.local/evidence/door-panel-pressure/gate-d-genkou-ja.png).

Playback timing on the licensed run, same build and data, measured through the frame-count mutation
stream: arrows on median **280.8 ms**, p95 296.3 ms, one camera signature; arrows off median
**266.3 ms**, p95 280.8 ms, one camera signature. The difference is 14.5 ms in the median; no camera
jump or stale frame was observed. Local detail:
[gate-f-timing.json](../.local/gate-c/evidence/gate-f-timing.json).

### Gate E · Portability and history — PASS

The worker published the licensed run as a `.aqresult`; opening it in an empty fresh data root
preserved all 26 frames byte-for-byte, the index, frame order, the 49-label/24 mm profile axis,
native MPa / display kPa / conversion and the history CSV. The source artifacts were hashed before
and after and were unchanged. A retained pre-pressure vertical result was also packaged and reopened:
it has no `door_pressure` metadata, but all 26 frames and history stayed identical, so older results
remain readable. A DEMO result opened with **Door-panel contact pressure is unavailable for this
result**, while its force–displacement plot, export, history CSV, units and `Synthetic data (DEMO)`
provenance stayed available. Local detail: [gate-e-reopen.json](../.local/gate-c/evidence/gate-e-reopen.json),
[gate-e-legacy.json](../.local/gate-e/gate-e-legacy.json) and
[Gate E DEMO](../.local/evidence/door-panel-pressure/gate-e-demo.png).

### Gate F · Regression and reporting — PASS (with known suite-load exceptions)

- Python: **383 passed, 1 skipped** (the opt-in Abaqus-Python roundtrip), exit 0. New
  `tests/test_door_pressure.py` covers profiles, orientation, units, duplicate/ambiguity, identity,
  deck output combinations, the two-step deck and display metadata.
- Translations **990 keys** both languages; encoding 47 files; typecheck pass; release
  **`24102ca8108b`** (`index-Duef0qdY.js`, API 3); `scripts/schema.py` regenerated `generated.ts`
  with only the additive `door_pressure` field.
- Browser acceptance specs: `door-pressure.spec.ts` (external GENKOU, pass), `door-pressure-app.spec.ts`
  (existing licensed run, pass), `door-pressure-run.spec.ts` (full Dashboard → import → Prepare →
  licensed submit → Results, pass, 53.1 s), `door-pressure-timing.spec.ts` (arrows on/off, pass).
- Full isolated browser suite on build `24102ca8108b`, port 19930: **171 passed, 4 failed,
  8 skipped** (183 tests, 12.5 min). The four failures — `gate-a` camera Fit/reset comparison,
  `materials` library validation, `offset-picking` and the centered `partition` guide — all passed
  together in a 17.1 s isolated rerun on port 19931, so they are suite-load behaviour, not this
  feature. The in-suite `gate-f` playback cadence passed. The door-pressure on/off measurement above
  used the same licensed data and build.
- DEMO browser check: pressure unavailable, one force chart, export and history CSV available,
  provenance still `Synthetic data (DEMO)`. [Screenshot](../.local/evidence/door-panel-pressure/gate-e-demo.png).

### Separate status

- **Solver execution:** yes, two accepted small licensed runs (`9efc065a…` door-only and
  `25fa7055…` body-then-door) plus the supplied reference ODB reads and one cancelled trial.
- **Actual extraction:** yes, production extractor output, not a manufactured result.
- **Mesh sensitivity / physical correlation:** **not established.** One mesh and one stroke were
  solved; no refinement study, independent physical measurement or agreed tolerance exists.
- **Software rendering:** the browser arrow/graph evidence used SwiftShader in Edge.
- **Pressure sign:** the accepted frame contains compressive (positive) values only. Tensile sign
  handling is implemented and unit-tested but not exercised by a solver result.

## Door-panel contact pressure reference and keyword pilots · 2026-11-25

The [execution brief](door-panel-pressure-handoff.md) defines the feature and release gates. On checkout `001d2db` the [independent reader](../scripts/reference_door_pressure.py) opened all three supplied Abaqus/Standard 2023 ODBs read-only under Abaqus Python 2024. The final-step door nodal CPRESS and CNORMF, station and deformed position matched a separate native ODB traversal at all **1,824 stations** across the three closing frames. The three final seating frames contained **1,824 measured zero pressure/force samples** on those same profiles. The original INP and ODB SHA-256 hashes were unchanged after the inspection. The measured units use the N–mm convention.

| Reference ODB (SHA-256 prefix) | Final native frame | Upper profile, node | Station (mm) | CPRESS (kPa) |
|---|---:|---|---:|---:|
| GENKOU `41abb0adaca4` | 205 | UPPER_ROOFBARA-1, 17 | 56.405592 | 45.509089 |
| HK01 `1eec6dc2a047` | 251 | UPPER_ROOF-1, 44 | 28.074212 | 47.434494 |
| HK02 `e8a678a2a7ca` | 233 | UPPER_LOWER_HINGEBARA-1, 39 | 29.612239 | 30.820487 |

Three new, sequential, synthetic Abaqus/Standard 2024 jobs completed, each on one CPU with five Standard tokens checked out. The normal mesh and INP writers produced their base decks. The test harness edited the contact output blocks and door NSET **in scratch copies** and submitted those copies directly. The one-step cases used solver thickness 1 mm, reporting width 100 mm and a 5.5 mm closing stroke. The two-step case used a 1.5 mm mesh and a moving body below the seal. The native reader tested field extraction; product pressure extraction and UI remain implementation gates.

| Pilot | Submitted INP / ODB SHA-256 prefixes | Measured result |
|---|---|---|
| `pressureunique` | `5ca4c67ecc33` / `97a7d404583d` | Global CSTRESS plus door NSET CFORCE. All 49 door stations had one CPRESS and one CNORMF. All zero initially, 14 positive in the last frame. Closing node 262 at 18.5 mm had **102.009602 kPa**, CNORMF (−0.0001272505, +0.05108861) N. |
| `pressureproof` | `3806c4d89ea3` / `62d48e204712` | Global CSTRESS plus door NSET CFORCE **and** CSTRESS. At the final frame the same ODB field had **98 CPRESS records for 49 nodes**, with two identical scalars per node, alongside 49 CNORMF records. |
| `pressuretwostep` | `622afb3699a6` / `d15bf36971cc` | Door NSET CFORCE and CSTRESS only in both steps. 17 pressure/force samples on each final door frame. `Bodyseating` had zero positive samples. Closing had six; node 103 at 6.0 mm had **70.216551 kPa**, CNORMF (−0.0003574215, +0.10495484) N. |

The 2024 solver reported DAT/MSG warnings in all three runs, including negative-eigenvalue warnings. These jobs establish output availability, units and duplicate behavior. They do not establish numerical sensitivity, production seal performance or physical correlation. The existing `test_abaqus.py`, `test_two_step.py` and `test_results_fields.py` modules returned **51 passed, 1 skipped**. The operator service was outside the test path. [Local source hashes and profile measurements](../.local/evidence/door-panel-pressure/reference-summary.json) · [Local reference plot](../.local/evidence/door-panel-pressure/GENKOU-door-pressure.png)

## CAE 2024 material-reference check · 2026-11-25 (CAE license used, no solver)

One Abaqus/CAE 2024 noGUI session (`abaqus cae noGUI=…`) imported the app-emitted material keyword
blocks for five representative source combinations and re-read every behaviour, option and numerical
row from the resulting CAE material objects. This checks the **input keywords and values**, not
solver acceptance, convergence or physical behaviour. No analysis was submitted and no ODB exists.

| Case | Source definition | CAE 2024 re-read | Verdict |
|---|---|---|---|
| `E13` | Density + Hyperfoam test data, N=1, `moduli=LONG_TERM`, lateral flag OFF, 130 rows | `n=1`, `testData=ON`, `moduli=LONG_TERM`, 130 rows with the lateral column omitted (CAE pads its storage with 0) | PASS |
| `EPTO_E110` | Density + direct Hyperfoam, N=1, `moduli=INSTANTANEOUS`, 3 coefficients | `n=1`, `testData=OFF`, `moduli=INSTANTANEOUS`, table equals source | PASS |
| `DKSPONGEHK` | Density + direct Hyperfoam, N=5, `moduli=INSTANTANEOUS`, 15 coefficients + Prony 3×3 | `n=5`, `moduli=INSTANTANEOUS`, 15-value table equals source; `*Viscoelastic, time=PRONY` 3 rows equal source | PASS |
| `E18WW` | Density + Yeoh N=3 (6 coefficients) + Mullins constants (3 values) | `type=YEOH`, `n=3`, table equals source; `mullinsEffect` table equals source | PASS |
| `SPCC` | Density + isotropic elastic + 8-row isotropic plastic table | `*Elastic` and all 8 plastic rows equal source (including the source's non-monotonic row) | PASS |

Two real writer defects were found and fixed by this check; neither had been caught by reading the
keyword reference:

1. A direct `*Hyperfoam` row must be packed at most **eight values per data line**. The app emitted
   one 3N-value line, which CAE 2024 rejected (`IndexError: tuple index out of range … *HYPERFOAM`).
2. CAE 2024 rejects a `DEFINITION` parameter on the Mullins constants form; the accepted keyword is
   the bare `*Mullins Effect`.

Artifacts (local, ignored by Git): `.local/evidence/cae-reference/` contains the app INPs, the CAE
re-read JSON (`cae-reference-final.json`), the verdict (`cae-reference-verdict.json`, **5/5 PASS**)
and the keyword-form matrix that established the two fixes. Library SHA-256
`7ab001b64d3a35fe6d40bdc9c3feb253b74b4e2480e8615e34be635084dbbca6`, 79,592 bytes, 27 records.

**Not verified.** A licensed solve of any Hyperfoam card, hyperelastic/plastic convergence, the CAE
GUI Material Library Manager file-open path, and direct N>1 Ogden/Polynomial hyperelastic tables.

## Independent file and CAE material software checks · 2026-11-25

Release `81fc7a73aa30` previewed all 27 supplied CAE cards. The ordinary import endpoint registered two and skipped 25 when every source record was requested. Exporting the selected PA6 card returned the entire original 27-record library. A synthetic model with unregistered cards could prepare without a registry-related readiness finding. The [audit and execution handoff](file-open-materials-navigation-handoff.md) records the Hyperfoam source options, open-file and fixture reproduction, and full-suite outcomes. This audit used read-only access to operator metadata and disposable application runs. It adds no licensed solver, CAE GUI or physical-correlation evidence.

## Independent retained material-overlay replay · 2026-11-24

An independent read-only check used completed run `632ad17b-fae7-4774-a9e9-ee1e550523c7`, its submitted setup, converted index and frames. All **783** deformable elements mapped to material assignments. Counting instance-qualified corner edges gave **8** shared by different materials, **4** across different CAD faces with the same material, **1,370** internal to a single face and **239** perimeter edges. A fresh Edge session on isolated frontend `4933ae101e08` displayed **8 interfaces and 239 perimeters** in both languages. Original results were only read. This is a viewer check with previously generated data.

Recounting manufactured run `9b713f7e-9f87-4c96-9be2-cb9e86485fb4` gave the reported 36 interfaces, 184 perimeter edges and 567 mapped deformable elements. All 1,006 other interior edges were within **one CAD face per edge**. This sample has zero same-material edges between distinct faces. The earlier counter checked the material identity only. Operator health during this later audit reported API `be1bb24c071006c8`, release `4933ae101e08`. No additional licensed solve or CAE library round-trip was performed.

## Workbench edit/readiness/dashboard/axis/outlines pass · 2026-11-24 (no solver launch)

No Abaqus license was checked out, no solver process was started and no retained operator artifact
was read or modified. Every "completed" run in this pass came from the license-free launcher double
(`tests/fake_abaqus.py`) through the real API → SQLite queue → worker → artifact path. Results are
therefore **manufactured test evidence**, not solver physics.

| Item | Value |
|---|---|
| Verified build | API `be1bb24c071006c8`, release `4933ae101e08`, entry `index-BZ3wYYIK.js`, API 3 |
| Checkout | `84ab7a2` plus the uncommitted changes in this pass |
| Isolated data | `--test-data` temp root on port 8876; disposable `SEAL_DATA` for Python |
| Operator instance | port 8765 release `5be20b24e6d0`; not contacted, stopped or modified |
| Manufactured Gate E run | mesh 708 nodes / 615 elements; 567 deformable seal elements, all mapped; 36 internal material interfaces; 184 perimeter segments; 1006 same-material interior edges excluded; rigid `PANEL-1` excluded |
| Solver physics | **not exercised** |
| Numerical sensitivity | **not exercised** |
| Physical correlation | **BLOCKED** |
| Self-contact participation | **BLOCKED** |
| Retained operator result | not re-read; the brief's 8-interface / 4-same-material-seam observation is the operator's measurement |

The material-interface counts were computed independently of the renderer from `results.json`
connectivity and the job's immutable revision using `.local/gate-e-counts.py` (isolated, license-free).
A separate browser test recomputes the same count from the artifact and asserts it against the drawn
overlay, legend and interface count.

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

## Abaqus/CAE material-library card verification — 2026-11-24 (no solver launch)

**Scope.** One Abaqus/CAE 2024 noGUI session (`C:\SIMULIA\Commands\abq2024.bat`,
license token consumed) was used to read the supplied library's material data
through CAE's own kernel. No analysis was submitted and no ODB or deck was
created.

**Input.** `I:\GithubProjects\AbaqusLibrary\HK_matlib.lib`, 79,592 bytes, SHA-256
`7ab001b64d3a35fe6d40bdc9c3feb253b74b4e2480e8615e34be635084dbbca6`. It is a
legacy protocol-0 pickle: 28 records (27 materials, 1 container). The
application reader never executes it; it interprets data opcodes only and
rejects `GLOBAL`/`REDUCE`/`OBJ`/`BUILD`/`INST`.

**Method.** The application parser extracted each card's `Data` string (Japanese
values decoded to UTF-8). A CAE noGUI script called
`matG_MatLibKernel.createMaterialFromDataString(model, name, '6-12', data)` for
all 27 cards, then read back density, elastic table and type from
`mdb.models['Model-1']`.

**Result.** 27 of 27 cards were created without error. Reproduced values:

| Card | Density | Elastic table | Type |
|---|---|---|---|
| PA6 | `1.13e-09` | `[[2600.0, 0.39]]` | `ISOTROPIC` |
| METAL | `7.65e-09` | `[[206000.0, 0.3]]` | `ISOTROPIC` |

Application eligibility was 2 of 27: only a pure isotropic linear-elastic card
with constant density maps exactly. Hyperfoam (11), hyperelastic (9), plastic
(2), viscoelastic (4), Mullins (2) and thermal-only (1) cards are shown with
precise reasons and are not registered. The exported `.lib` is byte-identical to
the CAE-authored source (same SHA-256), and the export is re-parsed and verified
before the file is published.

**Gap.** The CAE GUI `Material Library Manager` file-open path is not scriptable
in this environment, so the GUI action itself is **not verified**. Card data,
the exported container bytes and the application's decoded metadata are verified.
This is a verification gap, not a claim of physical material validation.

**Separate conclusions.**

| Conclusion | Outcome |
|---|---|
| CAE card-data interoperability | **PASS for the supplied library** (27/27 created, numbers reproduced) |
| CAE GUI library manager round-trip | **NOT VERIFIED** (GUI-only path) |
| Material behaviour validation | **BLOCKED** — no physical test data or agreed tolerance for these cards |
| Licensed solver execution | **NOT RUN** in this pass |

## Portable model/result containers — 2026-11-24 (software evidence)

`.aqmodel` and `.aqresult` are versioned ZIP containers with per-member sizes and
SHA-256. Opening validates kind, version, required members, member hashes,
expansion bound (4 GiB) and safe relative paths before extracting anything.
Writes stage to a temporary sibling, re-read the staged container, then replace
atomically.

Verified in disposable data roots and temporary folders:

| Check | Result |
|---|---|
| Model round-trip after moving the file and using a fresh data root | PASS — setup edges/faces/source preserved; new independent head |
| Save As preserves the original bytes; Save replaces the same pathname | PASS (SHA-256 compared) |
| External edit + Save without overwrite | 409 with `currentSha`; explicit overwrite succeeds |
| Renamed JSON as `.aqmodel` | refused as "not a readable portable container" |
| Worker publishes `.aqresult` after extraction with no browser | PASS — two runs, two distinct collision-safe files |
| Result opened in a fresh installation | PASS — frames, history and index readable; read-only import |
| Truncated / unsupported-version file | refused; the open document is untouched |
| Failed extraction | result file not published |

No solver was launched; these runs used the manufactured test launcher.
