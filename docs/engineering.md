# Engineering and operations

## Model and identity

Pydantic defines the saved setup and API contract. OpenAPI generates TypeScript types for the browser. SQLite stores a project head and append-only revision records. Saves carry a base-revision ID so two editors cannot silently overwrite one another. Run preparation references one specific revision. Submissions reference its successful build, copy its input artifacts, and verify the SHA-256 digest of the deck.

Section coordinates are XYZ in an explicit XY coordinate system. The geometry dimension and formulation have separate fields. Components have engineering roles independent of geometric entity type. A face owns a region's material-card assignment. The canonical setup stores topology, analytic edges, material versions, mounting selection, contact, offsets, travel, extrusion, mesh sizes and output requests. A drawing replacement rebuilds selections. Normal edits can change assignments and settings while preserving the original CAD topology.

The viewport consumes disposable primitives with a display ID, CAD entity ID, component ID and source region. Picking resolves these identities using the active camera and CSS-pixel edge tolerance. Faces and extruded walls retain section membership. Mesh artifacts contain global generation labels, CAD-to-element and CAD-edge-to-ordered-node maps. The input writer maps those to part/instance-qualified sets. Result nodes and elements carry their original instance-qualified labels. Triangulated quad picking resolves to its parent element.

## Import, mesh and analysis scope

- **DXF.** Modelspace LINE, ARC, CIRCLE and closed, zero-width LWPOLYLINE with bulges. Use the XY plane at Z = 0 and positive Z extrusion. Millimetre headers import directly; unitless drawings are interpreted as project millimetres and recorded as such; a drawing declaring another unit is rejected by name. Put the open moving profile on layer `PANEL` or `MOVING_PANEL`. Split section boundaries at every intended junction. The importer checks unsupported entities, intersections, unresolved blocks, nonplanarity, gaps and ambiguous contours. It retains source handles, layers and an input digest. The original upload is stored separately.
- **Regions.** Analytic circular arcs survive import and supply the Gmsh OpenCASCADE model. Fixed angular chord sampling assists planar region construction and display. Nested cells default to unfilled cavities. Explicit assignment can fill one. Shared CAD edges represent bonded interfaces. Complex drawings may require CAD cleanup outside the workbench.
- **Limits.** Each drawing is limited to 8 MiB, 4,096 analytic edges and 512 regions. A conservative estimate limits the requested mesh. Local sizes refine selected edges. Quad recombination permits triangular fallback. Checks cover edge sharing, complete connected material regions, valid connectivity, positive orientation and quad corner Jacobians.
- **Analysis.** The runnable template accepts a single deformable seal network, a fixed mounting selection and one open panel closing along negative Y. It supports plane-stress triangles and quads, R2D2 rigid elements, elastic, uniaxial-test hyperfoam or compressible neo-Hookean material cards, hard general contact with friction, nonlinear geometry and an implicit dynamic ramp. Section thickness and total or thickness-normalized force are explicit. Geometry-specific contact corrections and explicit vehicle-body attachment require new engineering validation.
- **Placement.** The initial Y offset moves the panel before analysis. The reviewed deck reports minimum vertical clearance over the overlapping faceted profiles. Prescribed travel starts at that assembled position. The synthetic history uses the gap to construct its illustrative post-contact response. Actual contact and force require a solve.
- **3D.** Straight extrusions share the existing workflow and role/material selections. The model records length and longitudinal subdivision count. Only length affects the current geometric preview. Volume meshes, 3D solution, arbitrary STEP assemblies, curved sweeps, installation preload and full-perimeter closing are future work. The STEP adapter boundary is in `integrations/drawings.py`.

## Processes and state transitions

React, VTK.js and Plotly run in the browser. FastAPI validates requests and stores revisions. A separate Python worker imports drawings, generates meshes/decks, supervises solver processes and extracts results. The browser polls persisted job state. Reloading a tab or restarting the API leaves the worker and database independent.

The SQLite queue uses WAL, foreign keys and `BEGIN IMMEDIATE` for claims. Submission tokens make retries idempotent. A worker claims solve and extraction stages separately. Each run records its owner, heartbeat, child process identity when available, status, observed increments/time, exits, diagnostics and file manifest. The active worker uses fixed filenames in a UUID directory. Missing input, unrecognized completion evidence and unavailable capabilities surface as failures. [SQLite transactions](https://www.sqlite.org/lang_transaction.html) · [WAL deployment constraints](https://www.sqlite.org/wal.html)

Queued cancellation is transactional. Running cancellation goes to the owning worker, which stops only its tracked child tree. Import and native meshing can finish their current library operation before cancellation takes effect. A worker without a heartbeat for 30 seconds appears as **Unknown / worker disconnected**. A replacement worker claims queued work only. For an unknown job, inspect its logged process identity, directory, Abaqus status and Windows process tree before deciding whether a new submission is appropriate. The original record remains available for diagnosis.

Solver success requires acceptable exit and diagnostic evidence, a Standard completion record, and a nonempty ODB. Extraction publishes a result index after frame files and CSV and validates their presence. A failed extraction retains successful solver state. Retry requeues extraction only.

## Result interchange v1

Each run has a submitted setup, input deck, mesh, mapping/placement metadata and logs. A real solve also owns its ODB. The manifest restricts downloads to known artifacts inside the run directory.

`results.json` stores mode, units, thickness, normalization, instance topology, region IDs, time-indexed frame filenames, variable availability and a panel history. `frame-NNNNN.json` contains instance-qualified nodal U and supported raw field records with position and integration/section-point identity. History interpolation is restricted to the shared sampled time interval of each step. Every history row keeps the raw signed `u1/u2/rf1/rf2` and adds the closing-direction projection (`displacement`, `force`) plus the step name; `closing` records the direction and whether travel is measured from the step start. `history.csv` includes the step, all four raw components, total `RF2` in N and the projected closing values. Missing values remain unavailable. The UI fetches topology once and frame payloads on demand, scales actual displacement by one, and contours the selected nodal U component. A component is coloured by its absolute value while the probe field reports the signed value, so the ramp is never mistaken for a signed field. Variables listed in `unavailable` are shown as unavailable rather than as zero. Display-only sign reversal affects the chart and the exported displayed curve, never the stored artifacts. The 3D roadmap retains the volume mesh for eventual interior cuts and a separate exterior display map.

## Material cards

The browser edits material cards directly. Density, Young's modulus and Poisson's ratio are editable for linear elastic cards; hyperfoam cards expose an editable uniaxial test-data table with row paste and a chart; compressible neo-Hookean cards expose C10 (MPa) and D1 (MPa⁻¹). Card validation runs in the browser before saving and blocks saving on non-finite, non-positive or out-of-range values; engineering advice such as non-monotonic axial strain is reported as a warning only. The server recomputes `version` on save from the actual data difference, so an unchanged card never bumps and historical revisions keep their values. `integrations/abaqus/deck.py` writes material cards only for materials assigned to meshed regions, as `*Elastic`, `*Hyperfoam, N=1, test data input` or `*Hyperelastic, neo Hooke` respectively.

## Mesh review metrics

The review step reports values measured from the produced mesh: node and element counts, counts by element type, per-region element counts, boundary edge segment counts, the shortest and longest element edge, and the worst longest/shortest edge ratio within a single element. Inverted and degenerate elements never appear because the mesher rejects them during generation. No synthetic quality score is displayed.

## Local storage and distribution

The product is displayed as **Abaqus QOL**. The on-disk directory intentionally keeps its previous
name, `%LOCALAPPDATA%\SimplifyAbaqus`, so an upgrade opens existing projects instead of creating an
empty database beside them. `SEAL_DATA` (legacy) takes precedence over the `ABAQUS_QOL_DATA` alias;
`SIMPLIFY_ABAQUS_LAUNCHER` takes precedence over `ABAQUS_QOL_LAUNCHER`; `SEAL_ODA` takes precedence
over `ABAQUS_QOL_ODA`. The rules are pinned by `tests/test_configuration.py`.

Store confidential fixtures under the ignored `fixtures/private/` or outside the checkout. Local
drawings, database and jobs live under the data directory. Back up the entire data directory with
services stopped. Large ODBs and job artifacts require disk-space planning.

The pilot trusts the Windows user and binds to loopback. Shared deployment requires authenticated project/artifact access, transport security, service-account isolation, resource/disk quotas, retention/backups, managed job supervision and license-aware scheduling. Keep SQLite on one host's local storage.

The Gmsh distribution is GPL-licensed and the authors offer commercial licensing. Review the chosen distribution and linking model before shipping the application. Native DWG reading uses the packaged ACadSharp helper and does **not** require ODA File Converter; ODA is only an optional vendor tool for other conversion workflows, so verify installation, unattended-use and redistribution rights if you choose to use it. Abaqus requires a separately licensed installation and solver entitlements. This repository includes synthetic public engineering data. [Gmsh licensing](https://gmsh.info/#Licensing) · [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)

## Verification record

The first milestone check passed 39 Python tests (1 skipped: the optional installed-Abaqus ODB round trip) and twelve Playwright tests in real Edge with WebGL. TypeScript checking, the translation-completeness gate (330 keys in both languages), the regenerated OpenAPI contract and the Vite production build passed after a clean npm installation.

This milestone passes 43 Python tests (same skip) and fifteen Playwright tests, with 349 translation keys in both languages, plus a regenerated contract and production build. It adds: the Windows bootstrap launcher (prepare, readiness, instance reuse, foreign-port refusal, simultaneous-launch lock), project grouping with an idempotent migration of a populated legacy database, an in-progress selection surviving a language switch, the projected door response with display-only sign reversal and an exported displayed curve, and a historical run reopening after a later model edit.

The mesh-first fixture increment passed 54 Python tests (same skip) and nineteen Playwright tests, with 391 translation keys. It adds: separate `MESH` and `DECK` worker operations, mesh identity and compatibility digests, validated instance-qualified fixture labels bound to the mesh, rectangular node selection with replace/add/subtract/clear, high-DPI selection, mesh reuse after a motion edit, remesh invalidation with fixture re-review, rejection of stale decks and forged or cross-model labels, and legacy edge-fixture resolution.

The 2026-11-22 repair pass passes 105 Python tests (same skip) and 33 Playwright tests, with 463 translation keys, typecheck and production build. It adds explicit empty models, model-bound drawing identity, deterministic navigation, Review without remeshing, archived-mesh replay, topology-safe renderer reuse, run-wide camera/colour metadata, atomic frame playback, Abaqus-only submission and per-port launcher locks. Details and the gate table are in [implementation-report.md](implementation-report.md#a4-repair-delivery--drawing-ownership-review-authority-playback-abaqus-only-execution).

One authorized Abaqus/Standard 2024 door-only closing case was executed through the normal workflow and reached contact, then a second case through the mesh → fixture → deck path. Measured values, hashes and tolerances are recorded in [engineering-validation.md](engineering-validation.md).

Visual inspection was performed on captured Japanese and English renders at 1280, 1440 and 1920 px widths, and on the bundled header wordmark in both languages. Automated pixel-diff visual regression is **not** configured.

## Tested environment

| Component | Version |
|---|---|
| Windows application Python | 3.11.9 |
| Abaqus 2024 bundled Python | 3.10.5 |
| Node.js / npm | 24.16.0 / 11.13.0 |
| FastAPI / Pydantic / Uvicorn | 0.116.1 / 2.11.7 / 0.35.0 |
| Gmsh / ezdxf / Shapely / NumPy | 4.14.1 / 1.4.2 / 2.1.2 / 2.2.6 |
| React / TypeScript / Vite | 19.1.1 / 5.8.3 / 6.4.1 |
| VTK.js / Plotly.js basic | 34.15.4 / 3.1.0 |
| Playwright / Edge | 1.55.0 / 157.0.4341.60 |

At the default 1 mm size, the built-in example produced 165 CPS4R elements and 24 R2D2 segments in the tested environment. The separate DXF fixture includes a circular cavity and multiple material regions. No confidential decks were present in the checkout or accessible at their supplied network paths on this PC. An ODB created for testing verified extraction, including overlapping labels across two instances, mismatched history sampling, raw integration-point stress and unchanged ODB checksum. That early environment check used no reference force curve or licensed solve; the later authorized synthetic Abaqus 2024 acceptance runs are recorded separately in the [engineering validation record](engineering-validation.md).

The underlying geometry APIs and the checked input/output procedure are documented by their maintainers. [Gmsh manual](https://gmsh.info/doc/texinfo/gmsh.html) · [ezdxf lightweight polylines](https://ezdxf.readthedocs.io/en/stable/dxfentities/lwpolyline.html) · [Abaqus 2024 analysis execution](https://docs.software.vt.edu/abaqusv2024/English/SIMACAEEXCRefMap/simaexc-c-analysisproc.htm)
