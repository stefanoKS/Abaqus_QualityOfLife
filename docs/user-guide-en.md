# Abaqus QOL user guide

Audience: design and analysis engineers working on weatherstrip sections.

Abaqus QOL is a single-user workbench that runs entirely on the local PC. No project data leaves the
machine. The interface is Japanese by default; use the language selector in the header to switch to
English. The choice is remembered across reloads. Engineering values — numbers, units, material IDs,
node and element numbers — never change with the interface language.

## 1. Layout

| Area | Contents |
|---|---|
| Header | Product name, Workspace / Dashboard switch, session indicator, language selector |
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

1. **Dashboard → New project**. The starting geometry is a 2D hollow bulb section or a 3D extruded
   segment.
2. **Import** a DXF/DWG only after confirming the drawing coordinates are in millimetres. The import
   runs in the background and creates a new revision when it finishes.
3. **Components** — assign each component a role: weatherstrip seal, moving panel, and so on.
4. **Materials** — assign a material card to each region and edit card properties as needed.
5. **Mounting / Contact** — select the edges to fix and set the friction coefficient.
6. **Motion** — set the initial Y offset, the prescribed Y travel (negative) and the step duration.
7. Press **Save revision**. Unsaved changes are flagged in the footer.
8. **Mesh → Generate mesh & input** creates the mesh and the input deck.
9. **Review / Run** — check the summary, then submit as DEMO or ABAQUS.
10. **Results** — play frames, probe nodes and elements, read the force–displacement curve and
    download the CSV.

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
- **Force–displacement** plots panel U2 against RF2 (signed). Units appear on the axis labels.

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
| DWG converter not configured | Configure the ODA File Converter path, or export DXF instead. |
| Every seal edge must belong to a material region | Fix the drawing so every edge belongs to a region. |
| Assign the seal role and a material to every section region | Resolve unassigned regions in Materials. |
| Requested mesh exceeds the pilot mesh budget | Increase the global element size. |
| Degenerate or inverted element | Change the element size or repair the boundary. |
| Unknown / worker disconnected | Inspect the run directory logs and processes; see the recovery document. |

## 7. Known limitations

- Analysis is 2D plane stress only. 3D is preview only.
- Supported elements are CPS3 / CPS4R with a single R2D2 rigid panel.
- Contact is hard, one moving panel, closing along Y only.
- Physical validity (contact onset, reaction magnitude, mesh convergence) is **not yet validated**.
  See [engineering-validation.md](engineering-validation.md).

## 8. Where data lives

Data is stored in `%LOCALAPPDATA%\SimplifyAbaqus`. The directory keeps its original name on purpose so
existing projects stay visible. See [migration-and-recovery.md](migration-and-recovery.md) for backup
and restore.
