# Hollow seal lip partition audit

Checked 2026-11-24 at `9dd1965`, matching remote main. The local application reported release `f17b356730d6`. The existing Gate D covers the synthetic hollow section. The native-DWG lip partition fails on that same release.

## Reproduced in the released UI

I read the saved setup for `test32` revision 4 and opened a copy in an isolated local service using the released frontend. In Edge, I selected **Components → Region 1 → Partition region** and clicked two viewport points across the right-hand lip. The actual browser request contained approximately (27.002, 5.995) and (26.992, 8.962) mm. The preview reached the correct face, returned HTTP 422 with `unsupported_curve`, and left Apply disabled. The visible message said “This boundary curve cannot be split safely. Use a line or arc boundary.” That advice gives the operator no way to cut this lip on the imported drawing.

The rubber face has an outer loop containing a line and an open fit-point spline. Its inner loop is a closed, non-periodic fit-point spline. The capability gap is in [subcurve construction](../packages/engineering/partition.py#L147). It rejects a boundary carrying fit points or a closed/periodic flag before the material cells are counted. A lip cut already fails on the **outer** spline, even when the guide stays clear of the cavity. Both other visible model heads inspected contained the same boundary types. The exact guide in the operator's original tab is unknown.

## Experiments on the copied CAD

Coordinates are model XY in mm. The comparison used three paths: the released preview endpoint, polygonization of the display contour as an independent connectivity check, and a diagnostic in-memory substitution for the spline split. The substitution evaluated the same curve used by import/display, obtained its B-spline poles and knots, and trimmed that representation using the existing clamped splitter. No application source or saved model was changed by the experiment.

| Guide | Released preview | Expected connectivity, reproduced by the prototype |
|---|---|---|
| Right lip, (27, 6) to (27, 9) | 422, unsupported curve | Two material regions. The small lip separates at a single interface. The larger region retains the cavity. |
| Left lip, (13.4, 6) to (13.4, 9) | 422, unsupported curve | Two material regions. The cavity stays with the larger region. |
| Across the base below the cavity, (10, 7.5) to (30, 7.5) | 422, unsupported curve | Two material regions, with the cavity above the cut. |
| Left wall only, (9, 12) to (18, 12) | 422, unsupported curve | One connected material region. Retain the guide and invite a second cut. |
| Through both walls, (9, 12) to (30, 12) | 422, unsupported curve | Two regions. The two seam segments end at the cavity boundary. |
| Left-wall guide above plus (22, 12) to (30, 12) | 422, unsupported curve | Same two regions as the through-guide. |
| Wholly inside the cavity, (18, 14) to (21, 14) | 422, no material hit | No material intersection. The existing response is appropriate. |

For the right lip, the projected seam ran from y = 6.654843 to 8.523978 mm. Integrating the canonical spline and line boundaries gave **2.432070 mm²** for the lip and **95.823642 mm²** for the remainder, summing to the original **98.255711 mm²**. The preview reports polygonal areas at its display tessellation tolerance. Use curve-based area or a common refined tessellation when comparing pre- and post-cut areas. In the lip probe, 101 parameter samples per trimmed spline gave a maximum deviation below 2 × 10⁻¹⁴ mm from its parent on the tested intervals.

The prototype lip mesh had 46 elements on the lip, 939 on the remaining rubber, and five common nodes exactly matching the seam node set. No seal element centroid fell in the cavity. The worst reported FE boundary deviation was 0.01974 mm at the existing 0.02 mm tolerance. After assigning the two existing material cards and selecting 20 fresh bottom-edge fixture nodes in the diagnostic mesh, the production deck writer emitted two region elsets with distinct material sections. This was a mesh and INP check. Solver execution was outside this audit.

## Two additional failures in the current partition engine

1. **A centered guide can lose a wall.** Use the existing 10 × 10 mm hollow box with a centered 4 × 4 mm hole. Replace its left outer line by the identical straight clamped degree-one spline. Draw from (−6, 0) to (6, 0). The [intersection loop](../packages/engineering/partition.py#L342) skips intervals when either sample is exactly zero, except at the beginning of the spline. The exact midpoint crossing disappears. The released engine reports only the right wall and one remaining region. Move the guide to y = 0.001 mm and it finds both walls and two regions. Fix crossings on sample/knot boundaries and deduplicate shared roots. Distinguish genuine crossings from tangencies and coincident spans.
2. **A successful guide can hide a dangling guide.** On the same ordinary line-bounded hollow box, combine a full cap cut at y = 3 with a left-wall-only guide at y = 0. The released engine reports `valid`. One new seam has two incident child faces. The other has **zero**. The same issue appeared with a lip cut plus a single-wall cut on the prototype DWG. Check each proposed seam segment against distinct incident material cells and report the affected guide. Retain the draft until the operator removes the unused segment or adds a guide that makes it a real interface.

## Execution command for the repair

Work from current main and reproduce these three failures before editing. Keep all writes in disposable local data. Use manufactured spline fixtures in CI and keep the original drawing and all derived geometry local. Implement the following gates.

1. **Preserve the imported CAD.** Reuse the canonical [spline evaluator](../packages/engineering/spline.py#L24), including its fit-point tangent handling. Trim the evaluated B-spline on its actual parameter domain. Preserve knot multiplicities, weights, source handles, loop orientation and existing cavity references. Distinguish the geometrically closed, non-periodic evaluated curve seen here from genuinely periodic splines. Exercise cuts on both sides of the closure and at an existing vertex, handle a full unsplit span safely and reject any genuinely unsupported representation with a specific reason. Keep parent revisions and source drawings immutable.
2. **Make the geometry decision observable.** Resolve intersections including exact sample/knot hits. Show all projected material intervals on the selected rubber face. Accept a single outer-to-outer lip cut that isolates positive-area material. Retain a one-wall draft if material is still connected. Permit one through-guide or two shorter guides that cross both walls. Validate every seam segment for two distinct incident child faces with opposing edge senses before Apply. Keep an unfilled void empty through save, reopen, material assignment and meshing. Localize each distinct outcome in Japanese and English.
3. **Prove the normal workflow.** In Edge, use two viewport clicks in Components to part the lip of a manufactured native-style fit-point seal with a closed cavity. Apply, reopen, select the lip, give it a second material, remesh, review fresh mounting nodes and prepare a deck. Assert matching preview/commit child IDs, material coverage, shared seam nodes, and representation of the two materials by separate sections. Check the seam is excluded from exterior contact and that the mesh leaves the cavity open. Repeat locally against the reviewed native DWG if available. Exercise the incomplete, centered-crossing, through-cavity, mixed-draft and void-only cases as separate tests.
4. **Correct the release evidence.** The [existing spline test](../tests/test_partition.py#L421) explicitly expects fit-point rejection. Replace that assertion for the newly supported case and retain explicit rejection coverage for unsupported inputs. The [native-DWG deck test](../tests/test_dwg.py#L289) exercises import and meshing without a partition. Extend coverage to this exact use case and narrow the previous Gate D claim until it passes. Record the command, release, actual result and any remaining curve restrictions.

Baseline rerun: all 31 partition tests and the two original native-DWG inventory/deck tests passed on the unmodified implementation. The six material-intersecting preview probes in the table still failed. Production implementation and end-to-end acceptance of the repair are pending.
