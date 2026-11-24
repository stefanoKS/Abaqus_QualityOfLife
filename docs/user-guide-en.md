# Abaqus QOL user guide

Audience: design and analysis engineers working on weatherstrip sections.

Abaqus QOL is a single-user workbench that runs entirely on the local PC. No project data leaves the
machine. The interface is Japanese by default; use the language selector in the header to switch to
English. The choice is remembered across reloads. Engineering values — numbers, units, material IDs,
node and element numbers — never change with the interface language.

Start it by double-clicking `start-abaqus-qol.cmd`. The first launch prepares the repository-local
Python environment and browser bundle when Python 3.11+ and Node.js are installed, starts the workbench
and its worker, waits until the application reports ready, and opens the default browser. Starting it
again reuses a matching instance. If startup fails, the double-click window keeps the reason visible
until you press a key. If it identifies another checkout on the same port, check its jobs, close the
idle workbench from its own launcher window, then double-click the launcher in the intended checkout.
No login is required.

## 1. Layout

The workspace is a fixed engineering shell: the navigation, model header and work area stay on one
screen, and only the named panes scroll. Long forms never push the drawing field or the primary
actions out of view.

| Area | Contents |
|---|---|
| Header | Product logo and name, Workspace / Dashboard switch, session indicator, language selector |
| Model header | Model name, revision, dimension, unit system, readiness notice; **Save revision** |
| Left work area | Two-column workflow (with per-step configuration state) and the assembly tree |
| Property editor | Editor for the selected workflow stage or CAD entity; scrolls on its own |
| Drawing field | White geometry, mesh and result viewport with zoom / fit tools on the right |
| Analysis actions | Always-visible group under the left workflow: **Prepare input deck** then **Submit Abaqus analysis**, prepared/stale state, deck inspection and download, run name, CPU count, licensed-launcher state and the active-run link |
| Footer | Save state, validation message, worker phase |

On a narrow window or at high browser zoom the panes stack in the page flow and a **Workflow &
properties** button collapses them, so the drawing field and the stage actions remain reachable. The
empty drawing field is white and has no import button: the Import stage owns the file picker and its
onboarding text.

Each workflow step shows its configuration state:

- **check** — the required configuration is complete.
- **circle** — not configured yet.
- **lock** — blocked because a prerequisite step is incomplete.

Completion is derived from the saved setup, not from whether you opened the step.

## 2. Basic workflow

The 2D workflow is **Import -> Components -> Materials -> Mesh -> Mounting -> Contact -> Motion -> Results**. Mesh produces elements only; **Mounting** owns the fixed-node selection and **Contact** owns the contact law and friction, and neither blocks the other. **Prepare input deck** and **Submit Abaqus analysis** are not a stage: they stay in the left **Analysis actions** group throughout an editable 2D setup. **Results** and historical submitted setups remain reachable.

The header shows one language button labelled with the destination language (`English` while the interface is Japanese, `日本語` while it is English). One click switches; the current model, step, camera, selection and unsaved values are kept.


1. **Dashboard → Create project**. This creates a *project group* and its first model in one step. A
   group is a container ("5q45"); a model is one analysed configuration inside it. Leave *Model name*
   blank to reuse the project name. **Every new model starts empty**: it opens at Import with “No drawing
   imported”. There is no example checkbox; synthetic example models created earlier or through the test
   API stay readable. A clean installation therefore shows an empty dashboard, not a seeded model.
2. **Add more models** with **New model** inside the group header. Each model keeps its own revision
   history and runs; **Revisions** lists them and **Duplicate model** creates an independent copy in the
   same group.
3. **Import** a DXF/DWG directly — there is no unit checkbox or dialog. The drawing's own header decides
   and the decision is recorded on the revision: millimetres import directly; every other recognised CAD
   length unit (inches, feet, centimetres, metres, US survey units and the rest of the DXF/DWG
   enumeration) is converted to project millimetres **once**, with the original declaration, numeric
   factor and provenance; a unitless header is interpreted as mm and a missing header is recorded
   separately. Unreadable codes, contradictory `$MEASUREMENT` metadata and converted coordinates outside
   ±1e6 mm are reported by name; scale is never guessed or silently clamped. Reopening, saving or
   duplicating never converts twice. DWG files are read
   **natively** — no CAD converter, no ODA configuration, no upload to a third party. The import runs in
   the background and creates a new revision when it finishes. `LINE`, `ARC`, `CIRCLE`, closed
   `LWPOLYLINE` and `SPLINE` entities are supported. A spline is kept as an exact B-spline
   (control polygon, knots and weights) or, for fit-point splines, as the AutoCAD-compatible cubic
   through its fit points, so display and meshing follow the drawn curve rather than a chord.
   A failed import leaves the last good drawing usable; a first failed import leaves the model empty
   with an error you can act on.
4. **Components** — assign each component a role: weatherstrip seal, door panel, and so on. The same
   stage lists section regions and owns the projected partition: selecting a region highlights it and
   makes it the partition target without leaving Components; **Assign material to this region** is the
   explicit link to the Materials editor.
5. **Materials** — assign a material card to every material region and edit card properties as needed. The
   library supports linear elastic, hyperfoam test data and a **compressible neo-Hookean** solid
   rubber card (C10 in MPa, D1 in MPa⁻¹).
6. **Motion** — the step sequence is **derived from the assigned roles** and shown as a readable summary:
   one seal plus one door panel is a single Closing step; one participating body panel as well gives
   Body seating then Closing. There is no manual mode selector. Set a nonnegative **stroke** and an
   in-plane **direction angle** (0° = +X, 90° = +Y, positive counterclockwise); the Δ vector is shown for
   both the door and body. A stroke of **0 mm is a valid hold** and reports the assembled role direction.
   New doors default to 10 mm at −90° (downward) over 1.0 s; a held body is 0 mm. This is a prescribed
   movement, not an automatically calculated gap or a safe compression recommendation: review initial
   clearance and deformation; reaching the gap does not guarantee valid contact. **Preview door** and
   **Preview body** animate the profile along its vector and back to the exact assembled pose before a
   mesh exists; it is a display-only preview, not a solver animation, and writes nothing. New models are
   placed as drawn; a retained legacy offset is shown read-only. **Contact** sets hard normal behaviour
   and three independent dimensionless Coulomb coefficients — door ↔ seal, body ↔ seal and seal ↔ self —
   each 0–5 inclusive and default 0.7 for new models. Old revisions keep their single historical
   coefficient, including zero and explicit non-defaults. Motion edits preserve contact settings. Press
   **Save revision**; unsaved changes are flagged in the footer. The same Motion stage owns the small
   **Analysis settings** group: the represented reporting width **W** (default 100 mm), total/per-mm
   force reporting, and the **solver thickness t** (1 mm for new setups) as a read-only fact. W is a
   display basis only; it never enters the deck or changes the section.
7. **Mesh → Generate mesh** meshes the section. A new model defaults to 0.5 mm. Rubber
   quadrilaterals always use reduced integration (CPS4R); the enforced setting and the CPS4R/CPS3/R2D2
   explanations are shown beside the controls. Mesh owns sizing, generation and regeneration only.
8. **Mounting** — tick **Fixed-node box mode**, then drag a rectangle over the weatherstrip mesh nodes
   you want to hold. Left drag selects, **Shift + drag** pans and the wheel zooms. Choose
   **Replace / Add / Subtract** for the rectangle, use **Clear selection** to start over, and check
   the node count. Press **Save fixed nodes**. Only the nodes you selected are fixed; a rectangle never
   expands to a whole CAD edge. Editable legacy models can use **Resolve N old mounting edges to
   nodes**, inspect the highlighted result, and save it as the reviewed fixture.
9. **Analysis actions → Prepare input deck** (first, blue) is always available in the left group and
   writes an `.inp` from the reviewed mesh, fixed nodes, materials, contact and motion. It never
   enqueues a mesh job and never submits. The button is enabled only for a saved revision whose
   engineering inputs are complete; a missing or stale deck never blocks preparation. When ready,
   **Input ready** appears with **Inspect input deck** and **Download INP**. If disabled, the reason
   beside the button names the issue and its owning stage.
10. **Submit Abaqus analysis** (second) runs that exact prepared deck and reviewed fixture; preparation
    and execution are separate. Set the run name and CPU count in the same group. If disabled, follow
    the displayed reason: save the revision, correct invalid input, generate a compatible mesh, review
    fixed nodes, configure the Abaqus launcher or prepare a current deck. A motion-only edit reuses the
    mesh but needs a new deck and revision.
11. **Results** — opens on **von Mises** and element probing when the run contains stress (otherwise
    on displacement magnitude and node probing). Switch the **Field**, set the displacement (0–5 mm) or stress (0–0.50 MPa) range
    (fixed default, run-wide auto, or editable limits), toggle mesh edges and
    node markers independently, scale the deformation, and probe cells or nodes. The canvas is solid
    white. Play frames (Loop is on by default), read the door panel response curve, export the displayed curve, and download the
    raw history CSV (missing measurements stay empty, not zero).

### Operator workflows

**Create an empty model and import its drawing.** Dashboard → New project → name the project and its
first model → Create project. The model opens at Import with no
drawing. Choose the DXF or DWG directly (no unit confirmation); a unitless drawing is interpreted as
mm and the basis is shown in the import summary. The viewport shows
the returned geometry, and that revision's original drawing stays downloadable.

**Archive or delete a model/project.** The dashboard has **Show archived** and an Archive/Restore
action on every model and project. Archived models are hidden by default and open read-only; their
revisions, runs and downloads remain available. Permanent deletion is offered directly from the ordinary listing:
it shows the dependent model, revision and job counts, the artifacts to be removed, and any active or unresolved work, then requires typing
the exact name. Cancel or Escape makes no change; a changed impact is re-confirmed. Deletion is refused while work is queued, running or unresolved. Shared drawings used
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

**Run a two-step body panel seating analysis.** In Motion, choose **Body panel seating, then door panel closing** and
assign exactly one body panel and one door panel in Components. Set the body panel offset, signed travel
and seating duration, then the door panel travel and duration. Step 1 moves the body panel and holds the door panel;
step 2 holds the body panel at its seated position and closes the door panel, carrying the seal and contact state
forward. The mesh includes both rigid profiles as R2D2 elements. Results offer a curve-step selector
so the body panel and door panel travel/force curves are read separately. This template is generated and
integration-tested but has **not** been validated with a licensed solve yet; treat it as unqualified
until that evidence exists.

**Change travel and rerun with the same mounting.** Open the model → Motion → change the signed travel
→ Save revision. The mesh stays compatible; the analysis action group prepares a new deck with the same reviewed
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
display name, role, inclusion, element type and count; an intentionally excluded body panel is marked
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

### Partition one seal region into materials

The **Components** stage can split one material-bearing seal region into independently selectable
child regions that share bonded, conforming interfaces. The operator draws projected guides on the
viewport; the browser never edits triangles or FE labels. This is a material partition, not a
physical gap.

1. Select a section region in the Components list (or click its face). The target is stated beside
   **Partition region**; the selection is highlighted and does not route away from Components.
   **Assign material to this region** opens the Materials editor explicitly.
2. Click **Partition region**, then click two arbitrary points across the target wall. The guide does
   not need to touch the boundary or be typed as X/Y. The server intersects the guide's supporting
   line with the canonical analytic boundary, selects the material intervals the drawn segment actually
   touches, and extends them to their true boundary hits. A short stroke inside one wall cuts that wall;
   a stroke through both walls of a hollow seal selects both, producing two regions in one commit.
3. The preview reports the authoritative region count and areas. A single radial cut that opens an
   annulus but leaves one connected region is kept as a draft and **Apply partition** stays disabled;
   draw a second cut. A guide outside the target material is a visible no-hit. A mixed draft also
   identifies guides whose seams do not yet separate two children; remove the indicated guide or
   complete the other wall. **Remove guide** removes an individual stroke, **Undo last guide**
   removes the latest draft stroke, **Cancel cut** clears the draft, and **Esc** cancels from the
   viewport. Precision XY entry is an optional accessible alternative; it adds a guide, it is not
   required.
4. **Apply partition** saves one revision atomically. Each child inherits the parent material and a
   stable CAD ID and keeps analytic line/arc/spline edges. The internal seam is excluded from exterior
   contact and is shared by one element on each side. Assign a different card to either child and
   **Save revision**.
5. The topology change produces a new mesh digest. Regenerate the mesh and re-review the fixed nodes;
   a prepared deck and its FE-node fixture are not transferred by coincidence. A child can be
   partitioned again.

A rejected or incomplete arrangement leaves the revision count, setup and source drawing unchanged.
Line, circular-arc and clamped spline boundaries, including fit-point and closed non-periodic
fit-point curves, are supported; genuinely periodic and unclamped spline
variants are rejected by name rather than approximated. Partitioning is disabled on submitted (locked)
snapshots, 3D previews and revisions with unsaved edits; save first.

### Permanent deletion

Every model card and project-group header in **Dashboard** has a destructive **Delete … permanently**
action, available without archiving first; Archive / Restore remain separate. One accessible dialog
shows the exact target, type, child-model count, revisions and jobs, the artifacts that will be
removed, and any active or unresolved work. Type the current name to enable **Delete permanently**;
Cancel or Escape makes no change and returns focus. If the impact changed after preview — for example
someone added a model or queued work — the dialog shows the revised counts and asks for confirmation
again. Shared drawing sources are removed only with their last reference; material-library cards,
sibling models and unrelated groups are kept. If file cleanup cannot finish, the result says
`cleanup pending` and the journal finishes it at the next startup.

## 4. Reading results

- **Variable** is U (displacement). **Component** selects the magnitude or |U1| / |U2| / |U3|. Component
  contours use the absolute value; the probe field reports the signed value.
- **Colour range** applies independently to displacement and stress. Displacement magnitude and U
  components start at a fixed **0–5 mm**; von Mises and the stress components start at **0–0.50 MPa**.
  `Fixed` is a display default, `Auto` uses the measured run-wide maximum for that quantity, and
  `Manual` accepts an editable minimum and maximum with the displayed unit. **Reset range** restores
  the default. A blank, non-finite or inverted pair is rejected locally and the last valid render
  stays on screen; zero is a valid minimum. The range never rewrites solver values.
- The legend shows both endpoints with units and marks values clipped above the maximum or below a
  positive minimum. Probe readings, the chart and the exported CSV are never clipped.
- The contour palette is one saturated blue–cyan–green–yellow–red scale shared by the viewport,
  actor colours and legend. Material colours and chart axes are separate.
- A rigid panel has no integration-point stress but still moves with its measured nodal U; its
  stress-free surface keeps a neutral stroke and a contour is not invented for it. A node without a
  measured U stays at its base position and the probe says the value is unavailable.
- Probes are labelled `instance · kind number`. Labels are never mixed across instances.
- **Unavailable outputs** lists variables that were not requested or could not be extracted. A missing
  value is never shown as zero.
- The camera, zoom, pan and colour scale stay fixed for the whole run. Playback never refits
  automatically; use **Fit and reset view** (F) to return explicitly. Stepping, scrubbing, playback,
  component changes and the deformed/undeformed toggle keep the camera. Each quantity's colour scale
  and legend come from measured run-wide values and do not change between frames.
- **Mesh edges** are on by default in Results and remain an independent toggle. **Play frames** starts
  paused. **Loop** is on by default: after the last displayed frame is held for one playback interval,
  playback wraps to the first frame and repeats. Turn **Loop** off to stop on the final frame. Pause
  and scrub work at any time; a failed frame leaves the last valid scene visible and names the frame.
  The slider keeps its own stable track, while frame count, time, load/error status and Loop occupy a
  fixed status row, so a pending frame cannot reflow the controls. Zero- and one-frame runs show a
  static frame and never start a timer.
- **Panel response** plots the selected step's reference-point reaction projected onto that step's own
  motion direction against the step-relative travel. The readout under the chart names the step, role,
  instance and RP label, the actual direction **d** = (dx, dy) and its angle counterclockwise from
  global +X, and the force basis. Body seating and Closing therefore use different axes; the body's
  upward seating is never projected onto the door's closing direction. A legacy record without step
  metadata is labelled as such instead of borrowing another step's direction.
- **Displayed signs** reverses the X and/or Y sign for reading. It changes the chart and the exported
  displayed curve only; the stored results are never rewritten. When Reverse Y is on, the panel states
  that the Y axis is inverted for display and that the raw solver force is unchanged.
- **Export displayed curve** downloads a spreadsheet-ready CSV with exactly **two numeric rows** and
  one column per aligned sample in the selected step: row 1 is the step-relative measured displacement
  magnitude √((U1−U1₀)²+(U2−U2₀)²) in mm; row 2 is the signed projected force in the selected reporting
  basis — (RF·d)·W/t in N for total, (RF·d)/t in N/mm for per-length. There is no preamble, header,
  index or time column. Missing measurements are empty cells; a measured zero is `0`. The filename and
  the text beside the button state panel, step, unit, width and sign. Flipping the display flips row 2
  too. **Download history CSV** keeps the raw signed components and original artifacts unchanged.
- Results produced before the projected door panel response existed still open: the chart shows their
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
| Unreadable drawing unit code | Set a recognised unit in the CAD header; the importer never guesses. |
| Converted coordinate is outside the ±1e6 mm range | Check the declared unit instead of rescaling the drawing. |
| Drawing metadata is inconsistent | Correct `$INSUNITS`/`$MEASUREMENT`; the unit header is authoritative and the conflict is recorded. |
| Unsupported DXF entities | Explode blocks and export `LINE`, `ARC`, `CIRCLE`, `SPLINE` or closed `LWPOLYLINE`. |
| Spline knot vector length must equal control points + degree + 1 | Re-export the curve; the file stores an inconsistent B-spline definition. |
| Spline endpoints disagree with its vertices | Re-export the drawing so the spline ends meet the adjoining curves exactly. |
| Every seal edge must belong to a material region | Fix the drawing so every edge belongs to a region. |
| Assign the seal role and a material to every section region | Resolve unassigned regions in Materials. |
| Requested mesh exceeds the pilot mesh budget | Increase the global element size. |
| The active mesh file is missing or unreadable | Generate the mesh again in Mesh, then review and save the fixed nodes; Review never remeshes automatically. Completed runs stay readable. |
| Degenerate or inverted element | Change the element size or repair the boundary. |
| A guide does not cross the target material | Draw the stroke across a wall of the selected region; the preview names the unused guide. |
| The cut crosses a cavity | Use separate cuts that stay inside the material. |
| This boundary curve cannot be split safely | Use a line or circular-arc boundary; other spline variants are not approximated. |
| The deletion impact changed after it was previewed | Review the revised counts in the dialog and type the name again. |
| Unknown / worker disconnected | Inspect the run directory logs and processes; see the recovery document. |

## 7. Known limitations

- Analysis is 2D plane stress only. 3D is preview only.
- Supported elements are CPS3 / CPS4R with a single R2D2 rigid panel.
- Contact is hard. Door ↔ seal, body ↔ seal and seal ↔ self coefficients are independent; the interior
  bonded partition seam is not exposed and rigid-to-rigid contact is excluded.
- Partitioning accepts one projected operation with one or more straight guides on one
  material-bearing seal region at a time; it can produce two or more children. Line and
  circular-arc boundaries and clamped control-point or fit-point splines are split analytically,
  including closed non-periodic fit-point curves. Periodic or unclamped splines cannot be split.
  Slivers and mixed arrangements containing missed or unfinished seams leave the revision unchanged.
  A one-region draft stays editable; remove a guide, undo the last draft guide or cancel it.
  After Apply the new revision is immutable: continue from an earlier revision or delete through the
  normal deletion rules.
- Fragments created by a cut have no FE-node fixture transfer: remesh and re-review the fixed nodes.
- The fixed nodes are a mesh-node selection; a mesh-changing edit still requires a new mesh and a
  reviewed fixture, because coincident node numbers are not proof that an old selection is right.
- Splines are imported exactly, but a spline is meshed through its declared chord tolerance when OCC
  cannot take the exact B-spline (closed or periodic curves). The default tolerance is 0.02 mm.
- A DWG is read by the packaged native reader. If the helper is incomplete the import names the missing
  packaged component and asks you to restore `integrations/dwg/bin`; no ODA installation is required.
- Physical validity (contact onset, reaction magnitude, mesh convergence) is **not validated** against a
  trusted reference. One licensed door-panel-only closing case has been executed and is recorded in
  [engineering-validation.md](engineering-validation.md).

## 8. Where data lives

Data is stored in `%LOCALAPPDATA%\SimplifyAbaqus`. The directory keeps its original name on purpose so
existing projects stay visible. See [migration-and-recovery.md](migration-and-recovery.md) for backup
and restore.
