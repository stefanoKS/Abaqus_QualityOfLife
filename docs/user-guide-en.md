# Abaqus QOL user guide

Audience: design and analysis engineers working on weatherstrip sections.

Abaqus QOL is a single-user workbench that runs entirely on the local PC. No project data leaves the
machine. The interface is Japanese by default; use the language selector in the header to switch to
English. The choice is remembered across reloads. Engineering values — numbers, units, material IDs,
node and element numbers — never change with the interface language.

Start it by double-clicking `start-abaqus-qol.cmd`. The first launch prepares the repository-local
Python environment and browser bundle when Python 3.11+ and Node.js are installed, starts the workbench
and its worker, waits until the application reports ready, and opens the default browser. Starting it
again reuses the running instance. If a prerequisite is missing, or the port belongs to another
application, a message says exactly what to do. No login is required.

## 1. Layout

| Area | Contents |
|---|---|
| Header | Product logo and name, Workspace / Dashboard switch, session indicator, language selector |
| Left panel | Workflow (with per-step configuration state) and the assembly tree |
| Centre | Geometry, mesh and result viewport |
| Right panel | Property editor for the current selection |
| Footer | Save state, validation message, worker phase |

Each workflow step shows its configuration state:

- **check** — the required configuration is complete.
- **circle** — not configured yet.
- **lock** — blocked because a prerequisite step is incomplete.

Completion is derived from the saved setup, not from whether you opened the step.

## 2. Basic workflow

1. **Dashboard → New project**. This creates a *project group* and its first model in one step. A group
   is a container ("5q45"); a model is one analysed configuration inside it. Leave *Model name* blank to
   reuse the project name. The starting geometry is a 2D hollow bulb section or a 3D extruded segment.
2. **Add more models** with **New model** inside the group header. Each model keeps its own revision
   history and runs; **Revisions** lists them and **Duplicate model** creates an independent copy in the
   same group.
3. **Import** a DXF/DWG after confirming the drawing coordinates are in millimetres. DWG files are read
   **natively** — no CAD converter, no ODA configuration, no upload to a third party. The import runs in
   the background and creates a new revision when it finishes. `LINE`, `ARC`, `CIRCLE`, closed
   `LWPOLYLINE` and `SPLINE` entities are supported. A spline is kept as an exact B-spline
   (control polygon, knots and weights) or, for fit-point splines, as the AutoCAD-compatible cubic
   through its fit points, so display and meshing follow the drawn curve rather than a chord.
   After the import, open the **Import** step's report to see every entity accounted for, and assign
   roles to the components it found (weatherstrip, one moving panel, optional body profile).
4. **Components** — assign each component a role: weatherstrip seal, moving panel, and so on.
5. **Materials** — assign a material card to each region and edit card properties as needed.
6. **Mounting / Contact** — select the edges to fix and set the friction coefficient.
7. **Motion** — set the initial Y offset, the prescribed Y travel (negative) and the step duration.
8. Press **Save revision**. Unsaved changes are flagged in the footer.
9. **Mesh → Generate mesh** meshes the section. No fixed-node selection is needed yet.
10. **Fixed nodes (WSFIX)** — tick **Fixed-node box mode**, then drag a rectangle over the
    weatherstrip mesh nodes you want to hold. Left drag selects, **Shift + drag** pans and the wheel
    zooms. Choose **Replace / Add / Subtract** for the rectangle, use **Clear selection** to start
    over, and check the node count. Press **Save fixed nodes**. Only the nodes you selected are fixed;
    a rectangle never expands to a whole CAD edge. Editable legacy models can use **Resolve N old
    mounting edges to nodes**, inspect the highlighted result, and save it as the reviewed fixture.
11. **Input deck → Prepare input deck** builds the deck from the stored mesh and the saved nodes.
12. **Review / Run** — check the summary, then submit as DEMO or ABAQUS.
13. **Results** — play frames, probe nodes and elements, read the door-response curve, export the
    displayed curve, and download the raw history CSV.

### Mesh reuse and invalidation

The mesh is identified by its geometry, component roles, region fill and mesh controls — not by the
analysis setup. Editing panel travel, step duration, friction or material values keeps the mesh and the
fixed nodes; you only need a new input deck. Changing the geometry, a role, whether a cavity is filled,
or a mesh size/control makes the old mesh incompatible: the mesh stage says so, the fixed nodes need
review on the new mesh, and any previously prepared deck can no longer be submitted. Refreshing or
reopening a model never remeshes; it restores the reviewed mesh and highlighted nodes.

## 3. Editing materials

**Materials → Material cards** lists the existing cards.

- **New card** creates an empty linear elastic card.
- **Duplicate** copies the selected card.
- **Delete** is unavailable while any region references the card. Clear the assignments first.
- **Material name** and **display colour** are free text/colour.
- **Material model** selects linear elastic or hyperfoam test data.

Linear elastic asks for density, Young's modulus and Poisson's ratio. Hyperfoam shows an editable
uniaxial test-data table (nominal stress, axial nominal strain, lateral nominal strain). You can paste
three columns from a spreadsheet.

Hard validation errors block saving and disable **Save revision**. Engineering warnings (for example
non-monotonic axial strain) are shown but do not block saving.

The card version increments only when the data actually changes. Historical revisions keep the
material values they were saved with. A card that no region uses is not written to the input deck.

## 4. Reading results

- **Variable** is U (displacement). **Component** selects the magnitude or |U1| / |U2| / |U3|. Component
  contours use the absolute value; the probe field reports the signed value.
- Probes are labelled `instance · kind number`. Labels are never mixed across instances.
- **Unavailable outputs** lists variables that were not requested or could not be extracted. A missing
  value is never shown as zero.
- **Door response** plots the panel reaction projected onto the closing direction against the closing
  travel, measured from the start of the closing step. A resisting seal gives a rising positive curve.
  The effective direction is shown under the chart.
- **Displayed signs** reverses the X and/or Y sign for reading. It changes the chart and the exported
  displayed curve only; the stored results are never rewritten.
- **Export displayed curve** downloads a CSV of exactly what is plotted, with panel, step, direction,
  units, signs, normalization and DEMO/ABAQUS provenance in `#` header lines plus the raw signed
  components. **Download history CSV** gives the unmodified artifact.
- Results produced before the projected door response existed still open: the chart shows their
  original signed U2/RF2 and says so.

## 5. DEMO versus Abaqus

**DEMO** exercises the workbench and the queue. Field values and the force curve are synthetic and are
not Abaqus results. The dashboard, run banner, result page, legend, CSV and metadata all carry
`DEMO — synthetic results, not an Abaqus analysis.`

**ABAQUS** runs Abaqus/Standard with a real license. It requires a configured launcher and a solver
entitlement. Never use DEMO output for design decisions or material-model validation.

## 6. Error messages

| Message | Action |
|---|---|
| Abaqus launcher not configured | Set the launcher environment variable and restart the application. |
| DWG reader unavailable | Restore `integrations/dwg/bin` from the repository. No CAD converter is required. |
| This DWG version is not supported by the installed reader | Export the drawing as DXF, or open and re-save it in a supported AutoCAD version. |
| The drawing declares … instead of millimetres | Set `$INSUNITS` to millimetres in the CAD file, or scale the drawing to mm before importing. |
| Unsupported DXF entities | Explode blocks and export `LINE`, `ARC`, `CIRCLE`, `SPLINE` or closed `LWPOLYLINE`. |
| Spline knot vector length must equal control points + degree + 1 | Re-export the curve; the file stores an inconsistent B-spline definition. |
| Spline endpoints disagree with its vertices | Re-export the drawing so the spline ends meet the adjoining curves exactly. |
| Every seal edge must belong to a material region | Fix the drawing so every edge belongs to a region. |
| Assign the seal role and a material to every section region | Resolve unassigned regions in Materials. |
| Requested mesh exceeds the pilot mesh budget | Increase the global element size. |
| Degenerate or inverted element | Change the element size or repair the boundary. |
| Unknown / worker disconnected | Inspect the run directory logs and processes; see the recovery document. |

## 7. Known limitations

- Analysis is 2D plane stress only. 3D is preview only.
- Supported elements are CPS3 / CPS4R with a single R2D2 rigid panel.
- Contact is hard, one moving panel, closing along Y only. Body-then-door two-step closing, oblique
  travel and per-pair friction overrides are not available yet.
- The fixed nodes are a mesh-node selection; a mesh-changing edit still requires a new mesh and a
  reviewed fixture, because coincident node numbers are not proof that an old selection is right.
- Splines are imported exactly, but a spline is meshed through its declared chord tolerance when OCC
  cannot take the exact B-spline (closed or periodic curves). The default tolerance is 0.02 mm.
- A DWG needs an installed ODA File Converter. Without it the import reports *DWG converter not
  configured* and asks for a DXF export.
- Physical validity (contact onset, reaction magnitude, mesh convergence) is **not validated** against a
  trusted reference. One licensed door-only closing case has been executed and is recorded in
  [engineering-validation.md](engineering-validation.md).

## 8. Where data lives

Data is stored in `%LOCALAPPDATA%\SimplifyAbaqus`. The directory keeps its original name on purpose so
existing projects stay visible. See [migration-and-recovery.md](migration-and-recovery.md) for backup
and restore.
