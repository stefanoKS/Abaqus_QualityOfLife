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

On desktop, the drawing field stays fixed while the side panes scroll. In a short window,
scroll the left pane below the assembly tree to reach the analysis actions.

| Area | Contents |
|---|---|
| Header | Product logo and name, **Dashboard → Workspace → Materials** in that order, session indicator, language selector |
| Model header | Model name, revision, dimension, unit system, readiness notice; automatic save state and **Duplicate setup** |
| Left work area | Two-column workflow (with per-step configuration state) and the assembly tree |
| Property editor | Editor for the selected workflow stage or CAD entity; scrolls on its own |
| Drawing field | White geometry, mesh and result viewport with zoom / fit tools on the right |
| Analysis actions | Below the assembly tree in every setup stage. Includes **Prepare input deck**, **Submit Abaqus analysis**, deck status, inspection and download, run name, CPU count, launcher status and the active-run link |
| Footer | Save state, validation message, worker phase |

The application opens on the **Dashboard**, which is the file entry point: **New model**, **Open
model…**, **Open result…**, the recent-file list and **Close model**. Workspace opens the document
this tab is working on; Materials is a detour that returns to it.

On a narrow window or at high browser zoom the panes stack in the page flow and a **Workflow &
properties** button collapses them, so the drawing field and the stage actions remain reachable. The
empty drawing field is white and has no import button: the Import stage owns the file picker and its
onboarding text. On the Dashboard, the run filters wrap inside the run card and a long run list scrolls
with the page; at narrow widths each run becomes one compact labelled row (identity, state, submitted,
elapsed, actions) instead of a wide table.

Each workflow step shows its configuration state:

- **check** — the required configuration is complete.
- **circle** — not configured yet, with the missing input named in its tooltip and the next-action banner.
- **lock** — reserved for a genuine read-only restriction, such as the deferred 3D extrusion. A missing
  role, material, mesh, mounting selection or contact value is correctable and never shows a lock.

Completion is derived from the automatically saved setup, not from whether you opened the step.

## 2. Basic workflow

The 2D workflow is **Import -> Components -> Materials -> Mesh -> Mounting -> Contact -> Motion -> Results**. Mesh produces elements only; **Mounting** owns the fixed-node selection and **Contact** owns the contact law and friction, and neither blocks the other. **Prepare input deck** and **Submit Abaqus analysis** are not a stage: they live once, at the top of the **Results properties**, and Results opens before a mesh, deck or run exists. **Results** and historical submitted setups remain reachable.

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
   An **open-only drawing** (curves that do not close) is now accepted as a saved, inspectable model:
   the viewport shows every spline or line, both disconnected profiles stay selectable and saveable,
   and the import summary reports zero closed material regions. Simulation stays blocked with the
   specific reason **No closed seal** until the contour is closed in CAD. Compatible evaluated
   endpoints within 1e-6 mm are joined; a larger gap is reported with its measured size and is never
   bridged.
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
   force reporting, the **solver thickness t** (1 mm for new setups) as a read-only fact, and
   **Door-panel contact pressure output**. W is a display basis only; it never enters the deck or
   changes the section. The pressure output is on by default: every prepared step requests door-node
   `CFORCE` (`CNORMF`) and `CPRESS` alongside the existing outputs and keeps door `U` for deformed
   anchors. Clear it before **Prepare input deck** to omit the door set and contact request. A
   prepared or submitted deck never changes; a changed output plan needs a new Prepare, which keeps
   the compatible mesh and reviewed fixed nodes reusable.
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
   enqueues a mesh job and never submits. The button is enabled only when the engineering inputs of the
   current setup are complete; a missing or stale deck never blocks preparation. When ready,
   **Input ready** appears with **Inspect input deck** and **Download INP**. The deck card names the
   actual state: missing, preparing, failed, cancelled, a newer deck, a superseded mesh or a proven
   changed fixture. A failed preparation keeps the worker diagnostic and the failed stage, points to
   **Open diagnostics**, and offers recovery. **The fixed nodes changed** appears only when the
   recorded fixture hash really differs from the saved one. If disabled, the reason beside the button
   names the issue and its owning stage; a branched, disconnected, self-intersecting or
   contact-side-ambiguous rigid profile is reported there before the worker is asked to prepare it.
10. **Submit Abaqus analysis** (second) runs that exact prepared deck and reviewed fixture; preparation
    and execution are separate. Set the run name and CPU count in the same group. If disabled, follow
    the displayed reason: correct invalid input, generate a compatible mesh, review fixed nodes,
    configure the Abaqus launcher or prepare a current deck. A motion-only or friction edit reuses the
    mesh but needs a new deck.
11. **Results** — opens on **von Mises** and element probing when the run contains stress (otherwise
    on displacement magnitude and node probing). Switch the **Field**, set the displacement (0–5 mm) or stress (0–0.50 MPa) range
    (fixed default, run-wide auto, or editable limits), toggle mesh edges and
    node markers independently, scale the deformation, and probe cells or nodes. An optional
    **Material outlines** layer draws material perimeters and internal interfaces with a compact
    swatch legend; it is independent of mesh edges, node markers, the field and the deformation scale.
    The canvas is solid
    white. Play frames (Loop is on by default), read the door panel response curve, export the load
    CSV or door pressure CSV at an editable interval, and download the raw history CSV (missing
    measurements stay empty, not zero).

### Automatic saving, branching and history

The workspace edits **one current model**. Every valid committed setting is saved automatically: type a
value and press Enter or leave the field, choose a role or card, or tick an option, and the compact
**Saved automatically** status confirms the new current revision. There is no Save revision button and
no separate Save contact action. While a write is in flight the status reads **Saving changes…** and
Prepare pauses with that temporary reason; if persistence fails, **Save failed** appears with the cause
and a **Retry** button, and the typed values stay on screen. A conflict from another tab is resolved by
rebasing only your own changed fields: if another window changed the reporting width and you changed
the mesh size, Retry keeps both. If you both changed the same field, the message names it and offers
**Reload revision**; nothing is overwritten.

**Save and Save As (portable model files).** The header shows the current `.aqmodel` filename or
**Not saved to a file**. **Save** writes the current model to that file (Ctrl+S does the same); the
first Save, or **Save As…**, asks for a folder and a file name. A model file carries the drawing source,
every CAD ID, the material snapshots, mesh settings, the compatible mesh and reviewed fixture, contact,
motion and run settings. If the file changed on disk since this session saved it, you are asked before
overwriting, and Save As always leaves the original untouched. Opening a model file creates an
independent head in this installation; it never overwrites the file another engineer has open.

**Result files.** In the Results properties, set an optional **Result folder** before Submit. After a
successful extraction the worker writes `<model>-<run>-<timestamp>-<short-id>.aqresult` there, even if
the browser is closed. A failed solver with a validated partial generation writes a distinguishable
`…-partial.aqresult` carrying the solver outcome, failure reason, extraction state and last saved
frame. A failed save is reported separately from solver and extraction state; you can
retry it without resubmitting the solver. Open a result file from Dashboard → File → **Open result…**;
it is read-only evidence with its frames, history, index and provenance, and a partial file keeps its
partial badge and last frame in a fresh installation.

**Duplicate setup** (and Duplicate on the Dashboard) is the explicit way to branch into an independent
model. New project and New model still start a fresh model. A submitted setup link
(**Setup** on a run row) always opens exactly the revision that ran, read-only; later edits never change
its setup, mesh, deck or results.


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

**Run a two-step body panel seating analysis.** Assign exactly one seal, one door panel and one body
panel in Components; the step sequence is derived from those roles (Body seating, then Closing). In
Motion set the body panel stroke and direction angle plus its seating duration, then the door panel
stroke, direction angle and duration. Step 1 moves the body panel and holds the door panel; step 2
holds the body panel at its seated position and closes the door panel, carrying the seal and contact
state forward. The mesh includes both rigid profiles as R2D2 elements. A curved profile — including a
local return in X, vertical portions or equal-X endpoints — is supported: the deck follows the open
chain in CAD topology, keeps every original R2D2 element and node identity, and chooses the physical
SPOS face from the locally measured first-contact neighborhood. A branched, disconnected,
self-intersecting or contact-side-ambiguous profile is refused with a typed reason before Prepare.
Results offer a curve-step selector so the body panel and door panel travel/force curves are read
separately. This template is generated and integration-tested but has **not** been validated with a
licensed solve yet; treat it as unqualified until that evidence exists.

**Change travel or friction and rerun with the same mounting.** Open the model → Motion (or Contact) →
change the value. The edit is saved automatically, the mesh stays compatible, Mounting stays visible
and keeps the reviewed fixed nodes, and the analysis action group prepares a new deck with them and
submits Abaqus. The earlier deck, fixture and result stay readable. A material-card value change also
reuses the mesh; changing mesh size/sizing or the roles that decide the mesh requires a new mesh and a
fresh fixed-node review, which the stage explains.

**Intentionally regenerate the mesh and review the fixed nodes again.** Open Mesh and choose Generate
mesh. When a reviewed fixture exists, the app states how many fixed nodes are affected and requires
**Regenerate** or **Cancel**. Cancel changes nothing. A successful regeneration starts with zero
reviewed nodes, so Mounting must be reviewed before a deck can be prepared. Even identical node
labels or mesh bytes require that fresh review.

**Correct an invalid number.** A number you type stays visible even when it is invalid. A **cleared
required field is invalid**, never “unchanged”: it cannot save the previous value. The field explains
the problem, nothing is written, and **Generate mesh**, **Prepare input deck** and submit stay
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

**Import a CAE material library.** In the Materials page, **Import a CAE material library** reads an
Abaqus/CAE `.lib` file without executing it and shows every record with its law, its engineering
family and whether it is **ready for a new 2D run**, **needs a density** or has **no structural law**.
Every well-formed record is registered when ticked — registering and running are separate. Declare
the family per card (polymer or metal); the default comes from the card's modulus and can be changed
before importing, so a mixed library never misclassifies a metal card. An identical reimport reuses
the existing entry; two different records with the same name are both registered and distinguished
by a content suffix. **Export a CAE material library** writes the original CAE record bytes to a
folder, verifies the round-trip and publishes the file atomically; it is labelled an *original-file*
export because the untouched source stream is not a rebuilt selection.

**Registered CAE laws.** A registered card shows a read-only property/table view of the source law
(hyperfoam, hyperelastic, viscoelastic, plastic, Mullins, thermal) with its options, columns and rows
exactly as the source defines them. The simplified editor never rewrites that law. If the source
omits a density, the density field is empty and the card says *needs a density*: enter the value and
save to create a new version. Saved revisions keep pinning the earlier version, so a historical run
is unaffected. A direct `*Hyperfoam` row is written packed at most eight values per line in keyword
order; a Hyperfoam test-data card whose source lateral strain flag is OFF is written with two active
columns, never with its zero-filled storage column.

**Engineering family and element type.** Each card declares a family. Polymer quadrilaterals are
reduced-integration **CPS4R**; deformable metal quadrilaterals are full-integration **CPS4**. Triangle
seal elements stay CPS3 and rigid profiles stay R2D2. The INP writes one element block and one
per-region ELSET/section per type. Changing the family requires a new mesh; changing a coefficient
reuses the mesh and the reviewed fixture but stales the deck.

**File documents and Close.** Models created or opened from the File commands live in an internal
*File documents* owner that has no archive or delete control, so they stay editable even when a
project group is archived. **Close model** on the Dashboard ends only this tab's document session and
names the document it will close; recent files, the saved model and any queued analysis are
unaffected. If the file on disk is behind the working head, Close offers **Save and close**,
**Close without saving** or **Cancel**. Save, `Ctrl+S`, Save As and Save and close all commit a valid
field edit first and then write the exact revision the workspace just saved. A model stranded in an
archived group can be recovered with **Recover as an editable copy**, which creates a distinct
editable model and leaves the original archived.

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
- **Partial results after a failed or cancelled analysis.** When the solver
  ends unsuccessfully but left a readable ODB, the run keeps its **Failed** or
  **Cancelled** badge and exposes **Partial results** from the Dashboard and the
  workspace response list. The worker queues one extraction-only attempt
  automatically; **Extract available results** (diagnostics) and **Retry
  extraction** never relaunch the solver. Results opens paused on the last
  readable saved field frame at its actual step and time, with a compact notice
  naming the step, the last saved local and total time and the solver
  diagnostic. Earlier frames remain available and playback only visits
  published frames. A planned step that never ran stays visible in the curve
  selector as unstarted rather than being shown as measured. A frame that
  carries only some fields keeps the missing quantities unavailable. If only
  native history is readable, the result opens as **history only** with field
  visualization unavailable; an initial-state-only ODB is labelled as such.
  The last reported solver increment and status time are shown separately and
  are not a failure time. A partial result can be reopened from its
  `-partial.aqresult` file in a fresh installation.
- **Result multiplier.** Above the right-side response charts, one labelled
  **Result multiplier (×)** and **Reset to ×1** apply a single dimensionless
  factor to the displayed engineering response: the closing force curve,
  door pressure, `CNORMF` components and magnitude, and the stress contour.
  It applies exactly once and never changes stroke, station, displacement,
  geometry, material assignment, mesh or the recorded force basis. ×0 displays
  zero for measured responses and leaves missing data missing. Negative,
  non-finite and blank values are rejected with a localized reason while the
  last valid factor stays on screen. The factor resets to ×1 on every newly
  opened result, including a portable file. It is separate from the geometric
  deformation scale and from the reporting width.
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
- **Mesh edges** are on by default in Results and remain an independent toggle. **Material outlines**
  is an independent display preference, off by default: it draws each material's perimeter in the
  material colour and every internal interface between two different materials as one thicker neutral
  line, with a compact swatch/name legend and an interface count. It follows the displayed frame's
  displacements, the Deformed toggle and the deformation scale, never changes the field, range, probes
  or exports, and is unavailable (with the reason shown) for a legacy result without regional material
  data. **Play frames** starts
  paused. **Loop** is on by default: after the last displayed frame is held for one playback interval,
  playback wraps to the first frame and repeats. Turn **Loop** off to stop on the final frame. Pause
  and scrub work at any time; a failed frame leaves the last valid scene visible and names the frame.
  The slider keeps its own stable track, while frame count, time, load/error status and Loop occupy a
  fixed status row, so a pending frame cannot reflow the controls. Zero- and one-frame runs show a
  static frame and never start a timer.
- **Panel response** plots the selected step's reference-point reaction projected onto that step's own
  motion direction against the step-relative travel. The full description (step direction, panel and
  unit, for example “Door panel reaction along closing direction (N)”) is shown as a wrapping caption
  immediately above the plot, and the rotated Y axis uses a short unit-bearing title such as
  “Force (N)” so it fits the plot height at every window width and at 200% zoom. The readout under the
  chart names the step, role,
  instance and RP label, the actual direction **d** = (dx, dy) and its angle counterclockwise from
  global +X, and the force basis. Body seating and Closing therefore use different axes; the body's
  upward seating is never projected onto the door's closing direction. A legacy record without step
  metadata is labelled as such instead of borrowing another step's direction.
- **Door contact pressure** appears below the force–displacement response when the submitted deck
  requested it. The graph plots the displayed frame's door-side nodal `CPRESS` in **kPa** against
  cumulative distance along the selected door profile in **mm**. Profile orientation and stations are
  derived once from the ODB's own R2D2 connectivity (an open chain starts at the
  lexicographically smallest endpoint `(x, y, nodeLabel)`), so translating or rotating the door,
  reversing connectivity, changing frames or zooming does not move the axis. `p_kPa = 1000 ×
  CPRESS_MPa` is the only conversion; reporting width, solver thickness, force normalization and
  Reverse Y never scale it. The station readout also shows the native MPa value. A profile selector
  appears when more than one connected door profile qualifies.
- **Pressure arrows** sit with the other field controls below the white
  viewport, next to **Mesh edges**, **Node markers** and **Deformed**. One
  independent toggle serves every field, including von Mises and `CNORMF`; off
  removes the shafts, heads and arrow-scale key immediately and across
  playback, step and field changes while the pressure graph and station
  selection stay usable. The arrow direction is the same node's measured
  `CNORMF` in the assembly frame, normalized. **Automatic (screen size)** is
  the initial calibration: the run-wide raw maximum maps to
  `clamp(24, 0.10 × min(viewport width, viewport height), 80)` CSS pixels and
  every arrow is `reference × |displayed pressure| / raw maximum`, so zoom
  never changes the screen length and a viewport resize recomputes it.
  **Manual (model mm)** uses the editable calibration **10 kPa = [5] mm**;
  `L_mm = |displayed pressure| × calibration / 10` and the tip is the
  deformed model tail plus the normalized direction times that physical
  length, projected with the current camera. DPR, zoom, pan and deformation
  exaggeration therefore do not change the physical calibration, and a short
  arrow's head stays inside its tail-to-tip span. Arrows are not pick targets,
  never enter Fit bounds and never change the field, probes or artifacts. A
  measured pressure with no `CNORMF` direction stays on the graph without an
  arrow. Hovering or selecting a graph station identifies the same node on the
  door and shows the profile, station, pressure in kPa, native MPa and signed
  `CNORMF` components in N. Measured zeros remain a zero line; missing samples
  break the line; conflicting duplicate observations are withheld and counted.
- **CNORMF (contact normal force)** is selectable in the field list when it was measured. The
  contour is the nodal magnitude in N and the probe keeps the signed Fx/Fy components. The door-side
  contact domain is labelled from the submitted definition (the app's door–seal pair, or a
  general-contact aggregate for an external ODB); the same node label in the seal, body or a rigid
  reference point is a different identity. A missing pressure or force field stays explicitly
  unavailable and is never estimated. Results produced before this feature and DEMO results show
  "Door-panel contact pressure is unavailable" while the force–displacement curve, exports and
  original artifacts stay readable.
- **Displayed signs** reverses the X and/or Y sign for reading. It changes the chart and the exported
  displayed curve only; the stored results are never rewritten. When Reverse Y is on, the panel states
  that the Y axis is inverted for display and that the raw solver force is unchanged.
- **Export load CSV (2 rows)** downloads a spreadsheet-ready CSV with the engineering label in
  column A and numeric samples from column B. Row 1 is `stroke(mm)`, the step-relative measured
  displacement magnitude √((U1−U1₀)²+(U2−U2₀)²) from a valid common reference sample. Row 2 is
  `F (…)`, the signed projection already normalized by the recorded basis — `F (N/100mm)` for the
  default 100 mm represented width, `F (N/80mm)` for 80 mm, `F (N/mm)` for a per-length result and
  `F (N)` for a legacy result whose represented width is unknown. The values are never rescaled a
  second time. The **stroke interval** is editable (default **1.0 mm**); the grid is built from
  integer indices and the exact last measured stroke is appended once when it is not already on the
  grid. At a measured stroke its value is used; between two adjacent valid samples the value is
  linearly interpolated. A missing stroke or ordinate, an unreadable block or a step boundary
  breaks the bridge: the affected sample stays an empty cell. If the step has
  a dwell with different loads at one stroke or an unload/reload, uniform resampling is ambiguous:
  the action explains why and **Original ordered samples** exports the acquisition-ordered rows
  instead, including a row whose stroke is missing. Reverse X never negates the exported stroke;
  Reverse Y is applied exactly once to the force. The active multiplier is applied exactly once and
  the filename carries `-x2`, `-x0.5` and `-partial` markers when they apply. The filename also names
  the panel, step, basis, interval and sign.
- **Export door pressure CSV (2 rows)** downloads `door station(mm)` and `CPRESS (kPa)` for the
  selected door profile at the **displayed** frame. The **station interval** is editable (default
  **1.3 mm**); interpolation is against arc-length station, not time or global X. The measured end
  station is appended once. Missing samples stay empty and a measured all-zero profile is valid.
  **Original profile nodes** keeps every measured node, including a narrow peak that a coarse uniform
  grid can miss. Switching profile, scrubbing, a delayed frame or a profile whose pressure array does
  not match the frame changes the chart, the exported bytes and the filename together; an unavailable
  or mismatched array disables the action with the reason. A missing or shortened station axis
  disables spatial plotting and export with a specific reason instead of inventing station zero.
  The active multiplier appears once in the ordinate label and the filename marker. The filename also
  names the profile, frame, step and interval.
- **Download history CSV** keeps the raw signed components and original artifacts unchanged; all
  display sign controls and export spacings live only in the browser.
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
