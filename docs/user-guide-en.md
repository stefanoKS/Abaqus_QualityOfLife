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

The 2D workflow is **Import -> Components -> Materials -> Mesh -> Mounting -> Contact -> Motion -> Review / Run -> Results**. Mesh produces elements only; **Mounting** owns the fixed-node selection and **Contact** owns the contact law and friction, and neither blocks the other.

The header shows one language button labelled with the destination language (`English` while the interface is Japanese, `日本語` while it is English). One click switches; the current model, step, camera, selection and unsaved values are kept.


1. **Dashboard → Create project**. This creates a *project group* and its first model in one step. A
   group is a container ("5q45"); a model is one analysed configuration inside it. Leave *Model name*
   blank to reuse the project name. **A new model starts empty**: it opens at Import with “No drawing
   imported”. Tick *Start from the public example section* only if you want the fictional demonstration
   geometry. A clean installation therefore shows an empty dashboard, not a seeded model.
2. **Add more models** with **New model** inside the group header. Each model keeps its own revision
   history and runs; **Revisions** lists them and **Duplicate model** creates an independent copy in the
   same group.
3. **Import** a DXF/DWG after confirming the drawing coordinates are in millimetres. DWG files are read
   **natively** — no CAD converter, no ODA configuration, no upload to a third party. The import runs in
   the background and creates a new revision when it finishes. `LINE`, `ARC`, `CIRCLE`, closed
   `LWPOLYLINE` and `SPLINE` entities are supported. A spline is kept as an exact B-spline
   (control polygon, knots and weights) or, for fit-point splines, as the AutoCAD-compatible cubic
   through its fit points, so display and meshing follow the drawn curve rather than a chord.
   A failed import leaves the last good drawing usable; a first failed import leaves the model empty
   with an error you can act on.
4. **Components** — assign each component a role: weatherstrip seal, moving panel, and so on.
5. **Materials** — assign a material card to each region and edit card properties as needed.
6. **Motion** — set the initial Y offset, the prescribed Y travel (negative) and the step duration.
   **Contact** sets the contact law and friction. Press **Save revision**; unsaved changes are flagged
   in the footer.
7. **Mesh → Generate mesh** meshes the section. Mesh owns sizing, generation and regeneration only.
8. **Mounting** — tick **Fixed-node box mode**, then drag a rectangle over the weatherstrip mesh nodes
   you want to hold. Left drag selects, **Shift + drag** pans and the wheel zooms. Choose
   **Replace / Add / Subtract** for the rectangle, use **Clear selection** to start over, and check
   the node count. Press **Save fixed nodes**. Only the nodes you selected are fixed; a rectangle never
   expands to a whole CAD edge. Editable legacy models can use **Resolve N old mounting edges to
   nodes**, inspect the highlighted result, and save it as the reviewed fixture.
9. **Review / Run → Prepare input deck** writes an `.inp` from the reviewed mesh, fixed nodes,
   materials, contact and motion. It never enqueues a mesh job.
10. **Review / Run** — check the summary, then submit an **Abaqus** analysis. A missing prerequisite
    names the stage that owns it instead of leaving a disabled button unexplained.
11. **Results** — play frames, probe nodes and elements, read the door-response curve, export the
    displayed curve, and download the raw history CSV.

### Operator workflows

**Create an empty model and import its drawing.** Dashboard → New project → name the project and its
first model (leave the example checkbox clear) → Create project. The model opens at Import with no
drawing. Confirm millimetres, choose the DXF or DWG, and wait for the new revision. The viewport shows
the returned geometry, and that revision's original drawing stays downloadable.

**Archive or delete a model/project.** The dashboard has **Show archived** and an Archive/Restore
action on every model and project. Archived models are hidden by default and open read-only; their
revisions, runs and downloads remain available. Permanent deletion is offered only for an archived
item: it shows the dependent revision and job counts, asks for confirmation, and then requires typing
the exact name. Deletion is refused while work is queued, running or unresolved. Shared drawings used
by a duplicate and the material library are not removed.

**Reopen another model or an earlier revision.** Dashboard → open the model card for its saved head, or
**Revisions** → choose an earlier revision. Reload, Back/Forward, the logo and the Workspace button
resolve the same way. An invalid link names the missing revision and offers **Back to Projects** rather
than opening a different model. The Workspace button restores the last model you explicitly opened.

**Read live run progress.** Diagnostics starts with a status card: phase, solver and extraction
states, the current step and increment, simulated step time, last update and a progress bar. Progress
is the fraction of the configured simulated time reported by the solver — not wall-clock time, and no
completion time is estimated. For two-step runs, Body seating and Closing are listed with the active
step highlighted. 100% appears only after both the solver and result extraction succeed; while
extraction is running or failed the bar stays below 100% and says why. A stale worker heartbeat and a
license wait are shown explicitly.

**Run a two-step body-seating analysis.** In Motion, choose **Body seating, then door closing** and
assign exactly one moving body and one moving door in Components. Set the body offset, signed travel
and seating duration, then the door travel and duration. Step 1 moves the body and holds the door;
step 2 holds the body at its seated position and closes the door, carrying the seal and contact state
forward. The mesh includes both rigid profiles as R2D2 elements. Results offer a curve-step selector
so the body and door travel/force curves are read separately. This template is generated and
integration-tested but has **not** been validated with a licensed solve yet; treat it as unqualified
until that evidence exists.

**Change travel and rerun with the same mounting.** Open the model → Motion → change the signed travel
→ Save revision. The mesh stays compatible; Review / Run prepares a new deck with the same reviewed
fixed nodes and submits Abaqus. The earlier revision, deck, fixture and result stay readable.

**Intentionally regenerate the mesh and review the fixed nodes again.** Open Mesh and choose Generate
mesh. When a reviewed fixture exists, the app states how many fixed nodes are affected and requires
**Regenerate** or **Cancel**. Cancel changes nothing. A successful regeneration starts with zero
reviewed nodes, so Mounting must be reviewed before a deck can be prepared. Even identical node
labels or mesh bytes require that fresh review.

**Correct an invalid number.** A number you type stays visible even when it is invalid. A **cleared
required field is invalid**, never “unchanged”: it cannot save the previous value. The field explains
the problem, and **Save revision**, **Generate mesh**, **Prepare input deck** and submit stay
disabled; leaving the step is refused with the same explanation. Correct the value, or press
**Escape** to restore the saved value deliberately. Nothing is saved behind your back.

**Pan, zoom and rename components.** Drag with the middle mouse button (or Shift + left) to pan the
viewport; the page does not scroll while you pan, and the wheel still zooms. In the assembly tree,
choose the pencil next to a component to give it a display name: Enter saves, Escape cancels, and the
name persists when you save the revision. The original drawing name and all geometry/FE identities
stay unchanged, so a rename does not force a remesh. Component rows in the mesh review show the
display name, role, inclusion, element type and count; an intentionally excluded rigid body is marked
“Excluded from analysis”, not “no elements”.

**Paste laboratory data.** In a hyperfoam card, **Paste table data** parses the clipboard into a review.
Three columns are expected (stress, axial nominal strain, lateral nominal strain), values are kept in
source order without rounding or sorting, blank lines are ignored, and one documented header line is
accepted. Any other malformed non-blank row is listed with its line number and blocks **Apply**; the
saved card is untouched by Cancel or by an invalid paste. The preview curve shows the accepted rows
before you commit them.

**When the browser and API do not match.** The header strip appears if this tab loaded a different
browser release than the running API, or if the API generation changed. It gives one action: reload for
a stale tab, or close Abaqus QOL and start it again for an API mismatch. Project creation, import, deck
preparation and submission are disabled until the pair matches. This is intentional: it prevents a
half-matched pair from changing a project or queueing a solver.

**Two tabs and the saved fixture.** Saving fixed nodes records the fixture version the tab loaded. If
another tab saved a newer selection first, your save is rejected with the current node count instead of
overwriting it; reopen Mounting and review the current selection. Preparing a deck also sends the exact
fixture you reviewed, so a deck cannot silently capture somebody else's newer nodes.

### Mesh reuse and invalidation

The mesh is identified by its geometry, component roles, region fill and mesh controls — not by the
analysis setup. Editing panel travel, step duration, friction or material values keeps the mesh and the
fixed nodes; you only need a new input deck. Changing the geometry, a role, whether a cavity is filled,
or a mesh size/control makes the old mesh incompatible: the mesh stage says so, the fixed nodes need
review on the new mesh, and any previously prepared deck can no longer be submitted. Refreshing or
reopening a model never remeshes; it restores the reviewed mesh and highlighted nodes. A submitted setup
replays the mesh and fixed nodes archived by its own deck, and the app explains when that archived mesh
cannot be verified instead of drawing labels on a newer mesh.

## 3. Materials

Open the top-level **Materials** tab to manage the shared, versioned library. The workspace
**Materials** stage only assigns a material to a region and shows the assigned version.

On the **Materials** page you can search, create, duplicate, rename, edit, archive and restore
materials. Every card edit appends a version; the previous versions stay readable and can be loaded
or selected for comparison. **Version history** shows when each version was created and which saved
model revisions pin it. Experimental stress–strain and lateral–axial charts plot the measured points
of selected versions only (no fit or extrapolation).

**Import model-local cards** creates new library entries from a model revision. Cards are never
merged by name, so two distinct cards with the same name remain separate.

In the workspace, choose a region and either pick an existing model-local card or **Assign from the
material library**. The summary shows the pinned library version. If the library has a newer version,
**Adopt vN** copies the new values into the model; geometry and mesh are reused, and a new revision
and deck are required.

**Material cards** lists the existing cards.

- **New card** creates an empty linear elastic card.
- **Duplicate** copies the selected card.
- **Delete** is unavailable while any region references the card. Clear the assignments first.
- **Material name** and **display colour** are free text/colour.
- **Material model** selects linear elastic or hyperfoam test data.

Linear elastic asks for density, Young's modulus and Poisson's ratio. Hyperfoam shows an editable
uniaxial test-data table (nominal stress, axial nominal strain, lateral nominal strain). You can paste
three columns from a spreadsheet; the paste is reviewed with source row numbers and rejected-row
reasons before it replaces the card.

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
- The camera, zoom, pan and colour scale stay fixed for the whole run. Playback never refits
  automatically; use **Fit and reset view** (F) to return explicitly. Stepping, scrubbing, playback,
  component changes and the deformed/undeformed toggle keep the camera. Each quantity's colour scale
  and legend come from measured run-wide values and do not change between frames.
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

## 5. Abaqus only, with identifiable history

New submissions run Abaqus/Standard and require a configured launcher and a solver entitlement. The
execution-mode and synthetic-scenario selectors have been removed. An explicit `DEMO` submission is
rejected with an actionable message and queues nothing, and a queued legacy DEMO job is retired with a
written diagnostic instead of being converted or relaunched.

Historical DEMO rows, result views, exports and their
`DEMO — synthetic results, not an Abaqus analysis.` label remain readable. Never use historical DEMO
output for design decisions or material-model validation.

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
- A DWG is read by the packaged native reader. If the helper is incomplete the import names the missing
  packaged component and asks you to restore `integrations/dwg/bin`; no ODA installation is required.
- Physical validity (contact onset, reaction magnitude, mesh convergence) is **not validated** against a
  trusted reference. One licensed door-only closing case has been executed and is recorded in
  [engineering-validation.md](engineering-validation.md).

## 8. Where data lives

Data is stored in `%LOCALAPPDATA%\SimplifyAbaqus`. The directory keeps its original name on purpose so
existing projects stay visible. See [migration-and-recovery.md](migration-and-recovery.md) for backup
and restore.
