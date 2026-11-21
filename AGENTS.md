# Working on Abaqus QOL

This file applies throughout the repository. Read the [current handoff](agent.md) before choosing work. The [implementation report](docs/implementation-report.md) records the last delivery; the [engineering validation record](docs/engineering-validation.md) states which solver cases were exercised. Compare those records with the current working tree, including uncommitted changes. Use the user's current instructions to determine the scope of the turn.

## Where changes belong

| Concern | Entry points and conventions |
|---|---|
| Browser workflow | [Workspace](apps/web/src/Workspace.tsx), [workspace features](apps/web/src/features/workspace), [dashboard](apps/web/src/Dashboard.tsx). Japanese is the default. Extend both [translation dictionaries](apps/web/src/i18n) and retain locale-independent engineering identifiers. Reuse the material editor, mesh review and shared input controls. |
| Viewport and results | [Viewport](apps/web/src/Viewport.tsx), [scene model](apps/web/src/viewportModel.ts), [picking](apps/web/src/viewportPicking.ts), [results view](apps/web/src/RunView.tsx). Preserve CAD IDs for geometric assignments and instance-qualified FE labels for probes and mesh-node fixtures. |
| Schema and API | [Engineering models](packages/engineering/model.py), [HTTP contracts](services/api/contracts.py), [routes](services/api/main.py). Regenerate [frontend types](apps/web/src/generated.ts) with [scripts/schema.py](scripts/schema.py) when contracts change. |
| Import, mesh and solver | [DXF](packages/engineering/dxf.py), [mesher](packages/engineering/mesh.py), [deck](integrations/abaqus/deck.py), [metadata/DEMO](integrations/abaqus/results.py), [ODB extraction](integrations/abaqus/extract_odb.py), [result interchange](integrations/abaqus/interchange.py). Application Python owns CAD and web dependencies. The extractor runs under Abaqus Python with its bundled libraries. |
| Persistence and execution | [SQLite store](services/store.py), [worker](services/worker/__main__.py), [startup](scripts/serve.py). A UI project group owns models; the database still calls model histories `projects`. Keep existing IDs, UUID artifact directories, revision links and historical results readable. |

## Engineering and operating constraints

- This phase targets 2D plane stress and Abaqus/Standard 2024 implicit dynamics. 3D models can be grouped and previewed. The user deferred 3D simulation until 2D validation.
- Keep exact submitted setups, decks, meshes and original result artifacts immutable. Preserve separate solver and extraction states. A lost heartbeat requires process reconciliation; never blindly relaunch a potentially active analysis. See [migration and recovery](docs/migration-and-recovery.md).
- Keep the default local SQLite location and existing environment-variable precedence. Use an isolated local data directory for development runs. Keep vendor tools, proprietary fixtures, logs, databases and ODBs out of Git and external uploads.
- Keep DEMO visibly labeled. The user authorized small local licensed synthetic verification cases for the 2D implementation. CI stays license-free. Report solver execution, extraction, numerical sensitivity and physical correlation separately.
- Record unit system, thickness, force normalization, step, panel, axis/sign convention and field location when they affect a result. Missing measurements must remain identifiable. Display preferences must not rewrite solver evidence.

## Running and verifying changes

For a normal local session, double-click [start-abaqus-qol.cmd](start-abaqus-qol.cmd). For setup, development services and configuration, see the [README](README.md). From the repository root, the standard regression commands are:

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix apps/web run test:i18n
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
npm --prefix apps/web run test:browser
~~~

For schema changes, run `.\.venv\Scripts\python.exe scripts\schema.py` after installing frontend dependencies, inspect the generated diff, then typecheck. The opt-in `SIMPLIFY_ABAQUS_TEST_LAUNCHER` test exercises a manufactured ODB with Abaqus Python. A licensed solve is a separate normal API → worker → solver → extractor run. [CI workflow](.github/workflows/ci.yml) · [Release checklist](docs/release-checklist.md)

When handing over work, update [agent.md](agent.md) with the next executable slice, the tests actually run and outstanding dependencies. Record licensed measurements and artifact identifiers in the validation record. Update both language guides when the user workflow changes.
