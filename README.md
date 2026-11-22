# Abaqus QOL

A local engineering workbench for automotive weatherstrip sections. Open a section, select CAD
regions and boundaries, assign materials and mounting, generate a conforming mesh and Abaqus input,
then inspect a run's saved setup, diagnostics and frame-by-frame results.

界面は日本語を既定とし、英語へ切り替えられます。Abaqus QOL is a local, single-user workbench; the
interface defaults to Japanese and can be switched to English at any time.

The first milestone targets **Abaqus/Standard 2024**, with plane stress and implicit dynamic panel
closing. The same workspace displays straight 3D extrusions for selection and property assignment.

> Abaqus QOL is an independent internal tool. It is not affiliated with, endorsed by or supported by
> Dassault Systèmes. "Abaqus" is a trademark of its owner and is used here only to describe the
> solver format this tool reads and writes.

## Start on Windows

The simplest start is to double-click **`start-abaqus-qol.cmd`**. With Python 3.11+ and Node.js
installed, the first launch creates the repository environment, installs the pinned dependencies,
builds the browser bundle, starts the workbench and its worker, waits until `/api/health` reports
ready, and opens the default browser. A second double-click reuses the running instance. If a
prerequisite is missing, or the port belongs to another application, the launcher prints exactly what
to do. No execution-policy change and no login are required.

To set it up manually instead:

~~~powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
npm --prefix apps/web ci
npm --prefix apps/web run build
.\.venv\Scripts\python scripts/serve.py
~~~

Useful launcher flags: `--port 8766` (different port), `--no-browser`, `--rebuild` (force a browser
rebuild), `--prepare` (prepare the environment and exit).

### Matched browser and API releases

`npm --prefix apps/web run build` now publishes a content-addressed release into
`apps/web/releases/<id>/` and records `apps/web/dist/release.json`. The API resolves that manifest
once at startup and serves only that directory, so building a newer release never replaces the files a
running instance is using. `/api/health` reports the pinned release, its entry asset, the API
generation (`api`) and the data-directory identity (`data`).

A tab compares the release it actually loaded with `/api/health`. If the pair is incompatible it shows
one recovery message: **Reload** for a stale tab, or close the workbench and start it again from
`start-abaqus-qol.cmd` when the API generation differs. Project creation, import, deck preparation and
submission stay disabled until the pair matches. The API also rejects a *write* that identifies itself
from a different release or API generation (HTTP 409), and an unidentified script keeps the older
contract.

One data directory has one owner. A second API/worker pair on another port pointing at the same
`SEAL_DATA` is refused before it can claim a job, with the owning PID and port in the message; use a
separate `SEAL_DATA` for an independent test instance. `--takeover` stops the old instance only when
no job is active **and** the running job list was readable.

Open [the local workbench](http://127.0.0.1:8765). The command starts FastAPI, serves the built UI
and starts an independent worker. Close the browser freely. Press **Ctrl+C** in the serving terminal
to stop the API and let the worker finish its current operation. Queued work resumes at the next
start. The database and artifacts stay in `%LOCALAPPDATA%\SimplifyAbaqus` — the directory keeps its
original name so existing installations keep their projects.

## First run

A clean installation opens an empty dashboard. Select **新規プロジェクト** (New project) to create a
project and its first model. **A new model starts with no drawing**: it opens at
**図面読込** (Import) with “No drawing imported” and a DXF/DWG chooser. Nothing is seeded, and
refreshing the browser or opening the workspace never invents geometry.

1. At **Import**, confirm millimetres and choose a DXF or DWG. The native DWG reader needs no
   separate converter; a missing reader is reported before the file is read. The imported drawing
   becomes a new revision and the workspace shows its group, model, drawing name and revision.
2. In **材料設定** (Materials), select a region and assign a material card or a shared library
   material. Card definitions, experimental data and version history live on the top-level
   **材料ライブラリ** (Materials) page; a model keeps the exact version it was assigned, and a newer
   library version is adopted explicitly. **移動条件** (Motion) sets the initial Y offset, signed
   panel travel and duration. **リビジョンを保存** (Save revision) keeps your changes.
3. In **メッシュ** (Mesh), choose a global size or select an edge for local sizing, then generate the
   mesh. Review element counts, edge lengths, per-region counts, initial vertical clearance and the
   concrete INP. **Mounting** owns fixed-node selection, so a reviewed fixture is never edited in
   Review.
4. In **解析条件確認・実行** (Review / Run), prepare the input deck and submit an **Abaqus** analysis.
   Deck preparation writes an `.inp` from the reviewed mesh, fixed nodes, materials, contact and
   motion; it never enqueues a mesh job. A missing prerequisite names the stage that owns it.
5. Open **解析結果** (Results) from the run or dashboard. Play frames, probe nodes or elements, switch
   the contoured displacement component, select a force-curve sample, or download signed panel
   history. **設定** (Setup) opens the submitted revision. **設定を複製** (Duplicate setup) creates an
   independently editable project from that revision.
6. Switch the viewport to **3D** to inspect section caps and side faces. Side-face material
   selection maps back to its section region. 3D is a preview only — solving requires a 2D section.
   An imported section keeps a 3D preview model in its 3D mode.

The public drawing in [examples/hollow-section.dxf](examples/hollow-section.dxf) exercises LINE, ARC,
CIRCLE and polyline bulges and remains available from the opt-in **公開サンプル断面から開始する**
(Start from the public example section) checkbox when creating a model. Loading that example is
geometry only; it is not permission to start a simulation.

### Operator workflows

**Create an empty model and import its drawing.** Dashboard → New project → name the project and its
first model (leave the example checkbox clear) → Create project. The model opens at Import with no
drawing. Confirm millimetres, choose the DXF or DWG, and wait for the new revision. The viewport
shows the returned geometry, and the original drawing stays downloadable from that revision.

**Reopen another model or an earlier revision.** Dashboard → open the model card for its saved head,
or **リビジョン** (Revisions) → choose an earlier revision. Reload, Back/Forward, the logo and the
Workspace button all resolve the same way; an invalid link names the missing revision and offers
**Back to Projects** instead of opening a different model.

**Change travel and rerun with the same mounting.** Open the model → Motion → change the signed
travel → Save revision. The mesh stays compatible; Review / Run prepares a new deck with the same
reviewed fixed nodes, then submits Abaqus. The previous revision, deck, fixture and result stay
readable.

**Intentionally regenerate the mesh and review the fixed nodes again.** Open Mesh and choose
Generate mesh. When a reviewed fixture exists, the app names how many fixed nodes are affected and
requires **Regenerate** or **Cancel**. Cancel leaves everything untouched; a successful regeneration
starts with zero reviewed nodes, so Mounting must be reviewed before a deck is prepared.

**Paste laboratory data safely.** In Materials, open a hyperfoam card's test data and choose **Paste
table data**. The paste is parsed into a review, not applied directly: a documented header row and
blank lines are accepted, every data row must have exactly three finite values (stress, axial strain,
lateral strain), and any malformed non-blank row is listed with its source row number. **Apply** stays
disabled while a rejection exists, **Cancel** leaves the saved card untouched, and the accepted rows
are shown on a preview curve before they are committed.

**Correct an invalid number.** Type the value and leave the field; the invalid text stays visible with
a field-specific message, and Save, Generate mesh, Prepare and Submit stay disabled. A **cleared
required field is invalid** — it is never treated as “unchanged” and never saves the previous value.
Press **Escape** to restore the saved value deliberately, or correct the value. Leaving the step with
an invalid draft is refused so the edit is not silently discarded.

The dashboard has separate **project** (group) and **model** filters. Each run row shows the model,
dimension, revision, a short run ID and a timestamp with seconds, so two same-named runs are distinct.

Archive is the reversible way to hide a model or project: **Show archived** reveals it again, and
archived items stay readable but read-only. **Permanent deletion** is offered only for archived items,
names the dependent revision/job counts, asks for confirmation and then requires typing the exact
name. It is refused while work is queued, running or unresolved; shared drawings and library
materials are preserved.

## Abaqus only, with identifiable history

New submissions run Abaqus/Standard. The execution-mode and synthetic-scenario selectors are gone.
An explicit `DEMO` submission returns an actionable validation error and queues nothing; a queued
legacy DEMO job is retired with a written diagnostic instead of being converted or relaunched.
Historical DEMO rows, result views, exports and their `DEMO — synthetic results, not an Abaqus
analysis.` label remain readable. DEMO output must never be used as engineering evidence.

## Configuration

Optional variables are read from the process environment at startup. Submissions are Abaqus-only;
a missing launcher is reported in Diagnostics and on Review / Run before anything is queued.

~~~powershell
# Data directory. SEAL_DATA wins when both are set (documented precedence).
$env:SEAL_DATA = 'C:\SealWorkbench\data'          # legacy name, still supported
$env:ABAQUS_QOL_DATA = 'C:\SealWorkbench\data'    # newer alias

# Abaqus launcher. SIMPLIFY_ABAQUS_LAUNCHER wins when both are set.
$env:SIMPLIFY_ABAQUS_LAUNCHER = 'C:\SIMULIA\Commands\abq2024.bat'
$env:ABAQUS_QOL_LAUNCHER = 'C:\SIMULIA\Commands\abq2024.bat'

# Optional ODA converter, needed only for the optional DXF round-trip tooling.
$env:SEAL_ODA = 'C:\path-to-installed-ODA\ODAFileConverter.exe'
$env:ABAQUS_QOL_ODA = 'C:\path-to-installed-ODA\ODAFileConverter.exe'
~~~

Set only the options you use. The data path must be on a local disk. Native DXF and DWG import needs
no ODA installation; the DWG reader reports exactly which packaged component is missing if the
helper is incomplete. Select **ライセンス解析を投入** (Submit Abaqus analysis) to request real solver
execution. Direct solver runs use the installation's solver license.
[Abaqus adapter and troubleshooting](integrations/abaqus/README.md) ·
[configuration and recovery](docs/migration-and-recovery.md)

For frontend development, run the API, worker and Vite in three repository-root terminals. Vite
proxies the API through loopback.

~~~powershell
.\.venv\Scripts\python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8765
.\.venv\Scripts\python -m services.worker
npm --prefix apps/web run dev
~~~

## Verify

~~~powershell
.\.venv\Scripts\python -m pytest -q
npm --prefix apps/web run test:i18n
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
npm --prefix apps/web run test:browser
~~~

The Playwright suite starts its own API and worker on port 8876 with disposable local data and a
license-free launcher double at the solver/extractor boundary. It uses installed Edge, an executable
specified with `SEAL_BROWSER`, or Playwright Chromium. If neither browser is installed, run
`npx playwright install chromium` from `apps/web`. Regenerate the checked-in TypeScript API contract
after schema changes with `.\.venv\Scripts\python scripts/schema.py`.

For the optional installed-runtime test, set `SIMPLIFY_ABAQUS_TEST_LAUNCHER` to the Abaqus 2024
launcher and run pytest. It creates and reads a manufactured ODB using `abaqus python` and submits no
solver job.

## Documentation

| Document | Contents |
|---|---|
| [AGENTS.md](AGENTS.md) | Repository conventions, entry points and regression commands for contributors |
| [agent.md](agent.md) | Current implementation handoff, remaining 2D work, acceptance checks and known defects |
| [docs/user-guide-ja.md](docs/user-guide-ja.md) | 日本語ユーザーガイド |
| [docs/user-guide-en.md](docs/user-guide-en.md) | English user guide |
| [docs/architecture.md](docs/architecture.md) | Components, data flow, state ownership |
| [docs/engineering-validation.md](docs/engineering-validation.md) | Supported models, assumptions, benchmark procedure, limitations |
| [docs/migration-and-recovery.md](docs/migration-and-recovery.md) | Data location, backup, restore, unknown-job recovery, rollback |
| [docs/release-checklist.md](docs/release-checklist.md) | Release gates and CI checks |
| [docs/implementation-report.md](docs/implementation-report.md) | Latest 2D delivery report and reported verification results |
| [docs/engineering.md](docs/engineering.md) | Detailed engineering and operations notes |

## Milestone status

Real paths include clean-DXF import, analytic CAD reconstruction, Gmsh/OCC meshing, INP generation,
immutable revisions, durable jobs, project grouping, read-only ODB extraction, a projected
door-response export, and a mesh-first fixture workflow: generate the mesh, box-select the fixed
weatherstrip nodes on the actual mesh, prepare the deck from that mesh, and submit. Mesh identity is
separate from the analysis revision, so a motion or friction edit reuses the mesh while a geometry or
mesh-control change forces fixture review.

Two small authorized Abaqus/Standard 2024 door-only closing cases were executed through the normal
workflow and reached contact (edge-based and box-selected fixtures). Run IDs, input/mesh hashes,
`WSFIX` membership, reference-point trajectories, contact onset, projected force and tolerances are
recorded in [docs/engineering-validation.md](docs/engineering-validation.md).

**Implemented but not physically validated:** the two-step **body seating → door closing** mode
(`analysis.mode = body_then_door`) is generated as a real two-step Abaqus input with separate rigid
body/door reference points and propagated boundary conditions. It has license-free deck and
integration tests only; no licensed two-step solve has been run, so no physical or numerical claim is
made for it.

**Not yet implemented:** drawing-role review before region construction, the material-region
partition tool, role-aware arbitrary in-plane motion, per-pair friction overrides and 3D solving. A request for one of those methods is refused before a license is spent: the API names the
unsupported method, and the interface does not present it as available. **Not yet verified:** physical
solution accuracy, contact convergence, mesh convergence and production license behaviour — these need
a trusted reference curve and an agreed engineering tolerance. Historical DEMO output is not evidence.
New submissions are Abaqus-only. 3D remains a preview.
