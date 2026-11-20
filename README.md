# SimplifyAbaqus

A local engineering workbench for automotive weatherstrip sections. Open a section, select CAD regions and boundaries, assign materials and mounting, generate a conforming mesh and Abaqus input, then inspect a run's saved setup, diagnostics and frame-by-frame results.

The first milestone targets **Abaqus/Standard 2024**, with plane stress and implicit dynamic panel closing. The same workspace displays straight 3D extrusions for selection and property assignment.

## Start on Windows

From the repository root in PowerShell, install into an ordinary Python 3.11 virtual environment. The browser build requires Node.js and npm. Use a browser with WebGL enabled.

~~~powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
npm --prefix apps/web ci
npm --prefix apps/web run build
.\.venv\Scripts\python scripts/serve.py
~~~

Open [the local workbench](http://127.0.0.1:8765). The command starts FastAPI, serves the built UI and starts an independent worker. Close the browser freely. Press **Ctrl+C** in the serving terminal to stop the API and let the worker finish its current operation. Queued work resumes at the next start. The default database and artifacts live in `%LOCALAPPDATA%\SimplifyAbaqus`.

## First run

1. The first launch creates **Hollow bulb section**, a fictional two-material seal with a rigid panel and a fixed mounting foot. Use **Dashboard → New project** for another section or extrusion.
2. In **Materials**, click the bulb wall or mounting foot. **Mounting / Contact** lets you pick edges and fix or release them. **Motion** sets the initial Y offset, signed panel travel and duration. **Save revision** keeps your changes.
3. In **Mesh**, choose a global size or select an edge for local sizing. Click **Generate mesh & input**. Inspect the section mesh, element counts, initial vertical clearance and the concrete INP. Edits require a fresh build.
4. In **Review / Run**, select **DEMO** and submit. The demonstration uses the real queue, saved input deck and artifact store. Its field values and force curve are synthetic. The scenario selector also provides a solver failure, a slow run for cancellation and a one-time extraction failure.
5. Open **Results** from the run or dashboard. Play frames, probe nodes or elements, select a force-curve sample, or download signed panel history. **Setup** opens the submitted revision. **Duplicate setup** creates an independently editable project from that revision.
6. Switch the viewport to **3D** to inspect section caps and side faces. Side-face material selection maps back to its section region. Length controls the preview. The project stores longitudinal subdivisions for future volume meshing.

The public drawing in [examples/hollow-section.dxf](examples/hollow-section.dxf) exercises LINE, ARC, CIRCLE and polyline bulges. Under **Import**, confirm millimetres and select the drawing. Assign section and panel roles, materials and a mounting edge before meshing. Empty nested cells can be selected from the assembly tree and explicitly filled. Replacing a drawing creates a revision and resets geometry assignments.

## Configuration

These optional variables are read from the process environment at startup. A fresh installation defaults to DEMO. Installing Abaqus on the machine does not automatically enable paid submissions.

~~~powershell
$env:SEAL_DATA = 'C:\SealWorkbench\data'
$env:SIMPLIFY_ABAQUS_LAUNCHER = 'C:\SIMULIA\Commands\abq2024.bat'
$env:SEAL_ODA = 'C:\path-to-installed-ODA\ODAFileConverter.exe'
~~~

Set only the options you use. The data path must be on a local disk. Select **ABAQUS** and **Submit licensed analysis** to request real solver execution. A missing launcher or converter produces a diagnostic. Direct solver runs use the installation's solver license. [Abaqus adapter and troubleshooting](integrations/abaqus/README.md)

For frontend development, run the API, worker and Vite in three repository-root terminals. Vite proxies the API through loopback.

~~~powershell
.\.venv\Scripts\python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8765
.\.venv\Scripts\python -m services.worker
npm --prefix apps/web run dev
~~~

## Verify

~~~powershell
.\.venv\Scripts\python -m pytest -q
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
npm --prefix apps/web run test:browser
~~~

The Playwright suite starts its own API and worker on port 8876 with disposable local data and disabled paid execution. It uses installed Edge, an executable specified with `SEAL_BROWSER`, or Playwright Chromium. If neither browser is installed, run `npx playwright install chromium` from `apps/web`. Regenerate the checked-in TypeScript API contract after schema changes with `.\.venv\Scripts\python scripts/schema.py`.

For the optional installed-runtime test, set `SIMPLIFY_ABAQUS_TEST_LAUNCHER` to the Abaqus 2024 launcher and run pytest. It creates and reads a manufactured ODB using `abaqus python`. The test includes no solver submission.

## Milestone status

Real paths include clean-DXF import, analytic CAD reconstruction, Gmsh/OCC meshing, INP generation, immutable revisions, durable jobs and read-only ODB extraction. The Abaqus command adapter was exercised with a Windows batch fixture. Abaqus 2024 Python parsed a generated deck and extracted a manufactured ODB. Physical solution accuracy, contact convergence and production license behavior await an authorized analysis. The installed ODA conversion path also awaits a configured converter.

The next engineering milestone is to run one authorized closing case, compare contact onset, mesh convergence, displacement and signed RF2 against a trusted ODB/curve, then establish acceptance tolerances. Representative drawings and reference solver outputs are needed for that comparison.

See [architecture, supported features and operations](docs/engineering.md) for data contracts, failure handling, tested versions, distribution considerations and later 3D work.
