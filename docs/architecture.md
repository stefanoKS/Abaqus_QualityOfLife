# Architecture

## Runtime shape

```
browser (React + VTK.js + Plotly)
   │  JSON / FormData over loopback only
   ▼
FastAPI  services/api        ───────────────┐
   │  reads/writes                       store.py
   ▼                                        │
SQLite (WAL)  %LOCALAPPDATA%\SimplifyAbaqus ─┘
   ▲
   │  claim / heartbeat / update
worker   services/worker  ── Gmsh, ezdxf, Abaqus launcher, ODB extractor
```

Three processes are independent. The browser polls persisted state; closing a tab or restarting the API
does not stop the worker or lose a queued job.

`start-abaqus-qol.cmd` is a thin bootstrap: it locates a Python 3.11+ interpreter once and delegates to
`scripts/serve.py`. The launcher prepares the repository-local `.venv` and browser bundle when they are
missing, verifies `GET /api/health` reports `product: "Abaqus QOL"`, reuses an instance only when its
build, API generation and data-directory identity match this checkout, refuses to start when another
application owns the port, serialises simultaneous launches through `.local/serve-<port>.lock`, and
opens the browser only after readiness. A lock whose process is still alive is joined, not stolen.
`--test-data` and `--no-browser` stay browser-free for automated tests.

### Matched browser releases

`npm --prefix apps/web run build` runs Vite and then `apps/web/scripts/publish-release.mjs`. The
publisher copies the built tree into `apps/web/releases/<content-id>/` and writes
`apps/web/dist/release.json` (`id`, `entry`, `css`, `api`). The id is a SHA-256 of the entry assets, so
an uncommitted build gets its own identity; a Git commit alone cannot name a build.

`services/release.py` resolves the manifest **once at import**. `services/api/main.py` mounts only that
release directory and reports it in `/api/health`. Because `vite build` empties `dist/`, releases live
beside it under `apps/web/releases/`, outside the emptied tree: a build that happens while an instance
is running cannot delete or replace the files it serves. A checkout built before this mechanism has no
manifest and is served from `dist` with `releaseLegacy: true`.

### Compatibility and write gating

`/api/health` carries `api` (the interface generation), `frontend` (the pinned entry asset) and `data`
(a digest of the resolved data directory). `apps/web/src/compatibility.ts` compares the tab's own
`import.meta.url` entry with `frontend` and its compiled `EXPECTED_API` with `api`. A mismatch disables
project creation, import, deck preparation and submission and renders one recovery message. Every
browser request sends `X-Abaqus-QOL-Api` and `X-Abaqus-QOL-Client`; the API rejects an identified
write from a mismatched pair with 409 while an unidentified script keeps the original contract.

### Data-directory ownership

`<data>/instance.json` records the owning PID, port, release and data digest. The launcher claims it
before starting the worker and the API lifespan re-claims it re-entrantly; a second process on the same
data directory is refused before it can claim any job. The record is removed on clean shutdown and
taken over only when the recorded process is gone. A different port with a separate `SEAL_DATA`
therefore stays independent, while two ports on one data directory cannot both run a worker.

## Browser modules

| Path | Responsibility |
|---|---|
| `src/main.tsx` | Route (`location.hash`), header, language selector, toast |
| `src/i18n/` | Typed ja/en dictionaries, provider, `t`, locale date and number formatting |
| `src/theme/tokens.css` | Design tokens (colour, type, spacing), contrast-verified pairs, `.sr-only` |
| `src/style.css` | Application styles consuming the tokens |
| `src/Dashboard.tsx` | Project groups, named models, revision browsing, run table, filters, job actions |
| `src/Workspace.tsx` | Owns draft setup state and orchestrates the workflow stages |
| `src/RunView.tsx` | Diagnostics and results: frame playback, component selector, projected door response, sign controls, displayed-curve export, logs |
| `src/Viewport.tsx` | VTK host, pointer/keyboard interaction, legend, view tools, rectangular node selection |
| `src/viewportModel.ts` | Pure scene construction from display primitives, mesh or results |
| `src/viewportPicking.ts` | Screen-space picking with instance-qualified identity |
| `src/viewportRenderer.ts` | VTK.js actor lifecycle, camera, box selection projection and fixture overlay |
| `src/Plot.tsx` | Plotly wrapper; created once per dataset, updated on active-sample change |
| `src/features/workspace/` | `WorkflowNavigation`, `AssemblyTree`, derived `workflowStates`, `readiness` types |
| `src/Compatibility.tsx` | Provider and banner that gate writes on a matched browser/API pair |
| `src/compatibility.ts` | Pure compatibility assessment from `/api/health` and the loaded entry |
| `src/plotAxis.ts` | Refit-or-mirror axis interval when a displayed series is sign-reversed |
| `src/features/materials/` | `MaterialEditor`, card validation, version semantics |
| `src/features/mesh/` | `meshQuality` (measured metrics), `MeshReview` |
| `src/shared/components/` | `NumberInput` (draft-then-commit, invalid drafts block writes), `draftGuard`, `Facts` |
| `src/generated.ts` | OpenAPI-derived contract; regenerated by `scripts/schema.py` |
| `src/assets.d.ts` | Ambient declaration for bundled image imports (the header wordmark) |

### State ownership

| State | Owner | Notes |
|---|---|---|
| Saved engineering setup | `Revision` from the API | Immutable; never mutated in place |
| Draft setup | `Workspace` `useState` | `structuredClone` per edit; `dirty = p !== rev.setup` |
| Committed numeric value | `NumberInput` draft → `onChange` | A half-typed number never reaches the draft setup |
| Geometry selection | `Workspace` | `Picked` carries CAD entity and instance-qualified labels |
| Camera | `ViewportRenderer` | Never rebuilt on language change or frame change |
| Build / run state | API (SQLite) | Polled; the browser holds only a cache |
| Playback frame | `RunView` | Frames fetched on demand |
| Language | `i18n` provider | `localStorage['abaqus-qol.language']`, default `ja` |

No global state library is used. Shared state is passed explicitly, which keeps the engineering state
single-sourced and testable.

## Server modules

| Path | Responsibility |
|---|---|
| `services/api/main.py` | HTTP contract, loopback/origin/compatibility guards, artifact allowlist, pinned static release |
| `services/api/contracts.py` | Request/response models |
| `services/release.py` | Resolve the pinned, content-addressed browser release at startup |
| `services/readiness.py` | One revision readiness calculation with stable reason codes and owning stages |
| `services/store.py` | SQLite schema, project groups, atomic group+first-model creation, data-root ownership, mesh identity and fixtures, append-only revisions, durable queue, configuration precedence |
| `services/worker/__main__.py` | Claim, heartbeat, child supervision, extraction, publication |
| `packages/engineering/model.py` | Validated project schema (schema version 1) |
| `packages/engineering/identity.py` | Mesh-determining inputs and their compatibility digest |
| `packages/engineering/fixture.py` | Eligible nodes, label validation, legacy edge resolution |
| `packages/engineering/mesh.py` | Gmsh/OCC conforming mesh; rejects inverted elements |
| `integrations/abaqus/deck.py` | Deterministic INP writer |
| `integrations/abaqus/launcher.py` | Explicit launcher, completion evidence, cancellation |
| `integrations/abaqus/results.py` | Result manifest, synthetic playback, metadata |
| `integrations/abaqus/extract_odb.py` | Runs under `abaqus python`; reads the ODB only |

## Data flow for one run

1. `PUT /api/projects/{id}` appends a revision; material versions are recomputed server-side.
2. `POST /api/meshes` queues a `MESH` job. The worker meshes, writes `mesh.json` and
   `mesh-identity.json`, and records the mesh digest and the mesh-compatibility digest on the job.
3. `PUT /api/meshes/{id}/fixture` stores the reviewed fixed-node labels against that mesh digest.
   `POST /api/meshes/{id}/fixture/edges` resolves a legacy CAD-edge mounting selection for inspection.
4. `POST /api/decks` validates the mesh compatibility digest, the fixture and the motion, then queues a
   `DECK` job. The worker reloads the stored mesh, re-verifies its digest, and writes `analysis.inp`
   and `result-metadata.json`; it records the INP SHA-256 and the fixture hash it consumed.
5. `POST /api/runs` validates that the deck belongs to the same revision, is completed, and that the
   fixture hash still matches; the run copies the deck's `input_hash` and mesh digest.
6. The worker re-copies the deck artifacts and refuses to run if the INP digest or the mesh digest
   differs.
7. On solve completion the worker verifies completion evidence (exit code, `THE ANALYSIS HAS
   COMPLETED SUCCESSFULLY`, non-empty ODB) before marking the solver as succeeded.
8. Extraction is a separate claimable stage; retry requeues only extraction.

## Mesh identity and the fixed-node fixture

- `packages/engineering/identity.py` digests the mesh-determining inputs as canonical JSON:
  dimension/formulation/plane, vertices, analytic edges, face topology with cavity-fill presence,
  component roles, and global/local mesh controls. Material values, motion, contact, thickness and the
  fixture are excluded, which is what allows a physics edit to reuse the mesh.
- Each `MESH` job stores `mesh_digest` (SHA-256 of `mesh.json`) and `mesh_compat` (the input digest),
  and writes a reviewable `mesh-identity.json` with both plus the inputs. A revision response carries
  `mesh_compat` so the browser can compare without recomputing anything.
- `fixtures(job, mesh_digest, labels_hash, labels, updated)` stores the reviewed labels. The mesh digest
  records which mesh the review belongs to and `labels_hash` records the exact selection, so a deck
  prepared before a fixture edit is stale.
- `DECK` jobs record `mesh`, `mesh_digest` and `fixture_hash`; `DEMO`/`ABAQUS` jobs record `build`
  (the prepared deck), `mesh_digest` and `fixture_hash`. Submission and the worker both re-check them,
  so a direct API call cannot submit a stale combination.
- Label validation rejects unknown labels, rigid-panel nodes, another instance and malformed strings;
  duplicates are collapsed and the output is deterministically ordered. An empty selection is valid at
  the mesh stage and rejected at the deck stage.

## Project grouping

A group (`groups` table) is a logical container above the existing model histories. A model is still a
`projects` row with its own append-only revision history, so revision IDs, run IDs, artifact
directories (`jobs/<job-id>`) and drawing directories (`drawings/<source-id>`) are unchanged.

| Table | Role |
|---|---|
| `groups(id, name, created)` | User-visible project ("5q45") holding several models |
| `projects(id, head, group_id)` | One model history; `group_id` is nullable only during migration |

- `initialize()` adds `group_id` with `ALTER TABLE` and backfills orphans inside one `BEGIN IMMEDIATE`
  transaction. Both steps are idempotent, so an interrupted or repeated start converges without
  duplicating groups or moving data.
- Ungrouped legacy models land in a single `Imported projects` group rather than failing.
- `POST /api/groups` creates a group; `POST /api/projects` with `group` creates a model inside it;
  `POST /api/projects/{id}/duplicate` copies the head revision into a **new** model in the same group;
  job duplication keeps the group too.
- `GET /api/groups` returns groups with their models, and `GET /api/projects/{id}/revisions` lists a
  model's revisions newest-first.

## Readiness contract

`GET /api/revisions/{id}/readiness` is the single calculation behind the workspace header, Review and
a direct API check. Each finding is `{code, stage, action, severity, artifact, params}`: the code is
stable and translated in both dictionaries, `stage` names the step that resolves it, and `artifact`
identifies the revision, mesh job or deck it refers to. The document also reports `state`
(`empty | blocked | ready | running | failed`), `first_blocker` and `next_action`.

The rules are deliberately conservative: an empty model is never Import-complete; an unassigned role,
an unmaterialed region, a missing compatible mesh or an unreviewed fixture is a blocker; a completed
mesh is only considered for its own mesh-compatibility digest, so a mesh-control change cannot make a
changed revision ready; a deck whose mesh is no longer active or whose fixture hash changed is stale;
a non-head revision is marked historical.

The workspace still derives per-step visual states for navigation, but the actionable header message
and its "Open this step" link come from this document, so a direct API rejection and the screen cannot
disagree about the blocker.

## Fixture and deck concurrency

`PUT /api/meshes/{id}/fixture` accepts `expected_hash`: the hash of the selection the editor loaded.
The empty string means "no fixture is saved yet". A mismatch returns 409 with the current node count
and leaves the stored fixture untouched. `POST /api/decks` accepts the reviewed `fixture_hash`; if the
fixture changed between review and preparation, the deck is refused before enqueueing. Both fields are
optional so pre-existing clients keep working; the bundled browser always sends them.

## Result contract extensions

`results.json` keeps version 1 and every previous field. Two additions:

- `closing` — panel component, instance, reference label, normalized direction, distance, whether travel
  is measured from the step start, and the ordered step roles (`door`).
- history rows gain `step`, `u1`, `u2`, `rf1`, `rf2` alongside `displacement`, `force` and
  `total_force_N`.

`history.csv` adds `step`, `panel_U1_mm`, `panel_RF1_N`, `closing_displacement_mm` and
`closing_force_<unit>` while keeping `time_s`, `panel_U2_mm`, `panel_RF2_N` and `panel_total_RF2_N`.
The client-side "Export displayed curve" CSV is generated from the same arrays that are plotted and
carries panel, step, direction, units, signs, normalization and provenance in `#`-prefixed lines; it
never rewrites the artifacts.

## Localization rules

- Translation keys live in `apps/web/src/i18n/ja.ts`; `en.ts` is typed `Record<TranslationKey, string>`
  so `tsc` fails on any missing or extra key.
- `node scripts/check-translations.mjs` (`npm run test:i18n`) is an independent CI gate.
- Backend vocabulary (job status, worker phase, run mode) is translated for display only; the raw value
  stays in `data-state` and in the API payload.
- Engineering identifiers, units, element types, file extensions and SHA digests are never translated.
- `document.documentElement.lang` follows the selection, and Japanese locale formatting uses `ja-JP`.
