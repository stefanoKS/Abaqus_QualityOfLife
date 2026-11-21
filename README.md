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

Open [the local workbench](http://127.0.0.1:8765). The command starts FastAPI, serves the built UI
and starts an independent worker. Close the browser freely. Press **Ctrl+C** in the serving terminal
to stop the API and let the worker finish its current operation. Queued work resumes at the next
start. The database and artifacts stay in `%LOCALAPPDATA%\SimplifyAbaqus` — the directory keeps its
original name so existing installations keep their projects.

## First run

1. The first launch creates **Hollow bulb section**, a fictional two-material seal with a rigid panel
   and a fixed mounting foot. Use **ダッシュボード → 新規プロジェクト** (Dashboard → New project) for
   another section or extrusion.
2. In **材料設定** (Materials), select a region and pick a material card; edit the card's density,
   elastic constants or hyperfoam test data directly. **固定条件・接触条件** (Mounting / Contact) lets
   you pick edges and fix or release them. **移動条件** (Motion) sets the initial Y offset, signed
   panel travel and duration. **リビジョンを保存** (Save revision) keeps your changes.
3. In **メッシュ** (Mesh), choose a global size or select an edge for local sizing. Click
   **メッシュと入力を生成** (Generate mesh & input). Review element counts, edge lengths, per-region
   counts, initial vertical clearance and the concrete INP. Edits require a fresh build.
4. In **解析条件確認・実行** (Review / Run), select **DEMO** and submit. The demonstration uses the real
   queue, saved input deck and artifact store, but its field values and force curve are **synthetic**.
   The scenario selector also provides a solver failure, a slow run for cancellation and a one-time
   extraction failure.
5. Open **解析結果** (Results) from the run or dashboard. Play frames, probe nodes or elements, switch
   the contoured displacement component, select a force-curve sample, or download signed panel
   history. **設定** (Setup) opens the submitted revision. **設定を複製** (Duplicate setup) creates an
   independently editable project from that revision.
6. Switch the viewport to **3D** to inspect section caps and side faces. Side-face material
   selection maps back to its section region. 3D is a preview only — solving requires a 2D section.

The public drawing in [examples/hollow-section.dxf](examples/hollow-section.dxf) exercises LINE, ARC,
CIRCLE and polyline bulges. Under **図面読込** (Import), confirm millimetres and select the drawing.
Assign section and panel roles, materials and a mounting edge before meshing. Empty nested cells can
be selected from the assembly tree and explicitly filled. Replacing a drawing creates a revision and
resets geometry assignments.

## DEMO versus Abaqus

| | DEMO | ABAQUS |
|---|---|---|
| Process | Real queue, worker, artifacts and extraction contract | Real licensed Abaqus/Standard run |
| Field values | Synthetic playback curves | Solver output from the ODB |
| Labelling | `DEMO — synthetic results, not an Abaqus analysis.` on the dashboard, run banner, result page, legend, CSV and metadata | `ABAQUS` |
| Use | Workflow, UI and queue verification only | Engineering evaluation |

DEMO output must never be used as engineering evidence or as validation of the material model.

## Configuration

Optional variables are read from the process environment at startup. A fresh installation defaults
to DEMO. Installing Abaqus on the machine does not automatically enable paid submissions.

~~~powershell
# Data directory. SEAL_DATA wins when both are set (documented precedence).
$env:SEAL_DATA = 'C:\SealWorkbench\data'          # legacy name, still supported
$env:ABAQUS_QOL_DATA = 'C:\SealWorkbench\data'    # newer alias

# Abaqus launcher. SIMPLIFY_ABAQUS_LAUNCHER wins when both are set.
$env:SIMPLIFY_ABAQUS_LAUNCHER = 'C:\SIMULIA\Commands\abq2024.bat'
$env:ABAQUS_QOL_LAUNCHER = 'C:\SIMULIA\Commands\abq2024.bat'

# DWG converter. SEAL_ODA wins when both are set.
$env:SEAL_ODA = 'C:\path-to-installed-ODA\ODAFileConverter.exe'
$env:ABAQUS_QOL_ODA = 'C:\path-to-installed-ODA\ODAFileConverter.exe'
~~~

Set only the options you use. The data path must be on a local disk. Select **ABAQUS** and
**ライセンス解析を投入** (Submit licensed analysis) to request real solver execution. A missing launcher
or converter produces a diagnostic. Direct solver runs use the installation's solver license.
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

The Playwright suite starts its own API and worker on port 8876 with disposable local data and
disabled paid execution. It uses installed Edge, an executable specified with `SEAL_BROWSER`, or
Playwright Chromium. If neither browser is installed, run `npx playwright install chromium` from
`apps/web`. Regenerate the checked-in TypeScript API contract after schema changes with
`.\.venv\Scripts\python scripts/schema.py`.

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

**Not yet implemented:** drawing-role review before region construction, the material-region
partition tool, role-aware arbitrary in-plane motion, and per-pair friction overrides. **Not yet
verified:** physical solution accuracy, contact convergence, mesh convergence and production license
behaviour — these need a trusted reference curve and an agreed engineering tolerance. DEMO output is
not evidence. 3D remains a preview.
