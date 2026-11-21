import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  ArrowDownToLine,
  Axis3D,
  Box,
  Boxes,
  CheckCheck,
  ChevronRight,
  CircleDot,
  Copy,
  FileInput,
  FileText,
  Grid2X2,
  Layers3,
  LoaderCircle,
  MousePointer2,
  Play,
  Save,
  ScanLine,
  SlidersHorizontal,
  Waypoints,
} from 'lucide-react'
import Viewport from './Viewport'
import type { Display, ViewMesh, Picked, SelectionMode } from './viewportModel'
import { Plot } from './Plot'
import { artifact, err, go, request, type FixtureInfo, type Job, type Project, type Revision } from './api'
import { useI18n, labelFrom } from './i18n'
import type { TranslationKey } from './i18n'
import { ACTIVE_POLL_MS, IDLE_POLL_MS, anyActive } from './shared/hooks/polling'
import { Facts } from './shared/components/Facts'
import { NumberInput } from './shared/components/NumberInput'
import { AssemblyTree } from './features/workspace/AssemblyTree'
import { WORKFLOW_STEPS, WorkflowNavigation } from './features/workspace/WorkflowNavigation'
import { workflowStates } from './features/workspace/workflowStates'
import {
  MaterialEditor,
  freshCard,
  materialIssues,
} from './features/materials/MaterialEditor'
import { meshQuality, type MeshFile } from './features/mesh/meshQuality'
import { MeshReview } from './features/mesh/MeshReview'

type Mesh = ViewMesh & MeshFile
type Props = { initial: Revision; locked?: Job; notify: (msg: string) => void }

export default function Workspace({ initial, locked, notify }: Props) {
  const { t } = useI18n()
  const [rev, setRev] = useState(initial),
    [p, setP] = useState(initial.setup)
  const [stage, setStage] = useState(1),
    [mode, setMode] = useState<SelectionMode>('component')
  const [pick, select] = useState<Picked | null>({
    kind: 'component',
    id: p.components[0].id,
    component: p.components[0].id,
  })
  const [hidden, hide] = useState<string[]>([]),
    [display, setDisplay] = useState<Display | null>(null)
  const [meshJobs, setMeshJobs] = useState<Job[]>([]),
    [deckJobs, setDeckJobs] = useState<Job[]>([]),
    [meshFile, setMeshFile] = useState<Mesh | null>(null),
    [showMesh, setShowMesh] = useState(false)
  // Fixed-node fixture review: a pending selection is shown but not stored until
  // Save, so a rectangle can be corrected before it becomes WSFIX.
  const [fixtureMode, setFixtureMode] = useState(false),
    [pendingFixture, setPendingFixture] = useState<string[] | null>(null),
    [boxOperation, setBoxOperation] = useState<'replace' | 'add' | 'subtract'>('replace')
  const [working, setBusy] = useState(false),
    [info, message] = useState(''),
    [issue, setIssue] = useState(''),
    [generation, refresh] = useState(0)
  const [cap, setCap] = useState<Record<string, string>>({}),
    [related, setRelated] = useState<Job[]>([])
  const [execution, setExecution] = useState('DEMO'),
    [scenario, setScenario] = useState('success'),
    [runName, setRunName] = useState(() => t('review.defaultRunName')),
    [cpus, setCpus] = useState(1)
  const [unitConfirmed, confirmUnit] = useState(false),
    [expanded, expand] = useState<string[]>([])
  const [activeMaterial, setActiveMaterial] = useState<string | null>(p.materials[0]?.id ?? null)
  const [placement, setPlacement] = useState<{ initial_vertical_mesh_clearance_mm: number } | null>(
    null,
  )
  const file = useRef<HTMLInputElement>(null),
    token = useRef(crypto.randomUUID())
  const [drawingJob, setDrawingJob] = useState<string | null>(() =>
    locked ? null : sessionStorage.getItem('import:' + initial.id),
  )
  const busy = working || !!drawingJob
  const dirty = p !== rev.setup
  const problem = useCallback(
    (e: unknown) => {
      setIssue(err(e))
      notify(err(e))
    },
    [notify],
  )
  useEffect(() => {
    if (!drawingJob) return
    const ac = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const clear = () => {
      sessionStorage.removeItem('import:' + rev.id)
      setDrawingJob(null)
    }
    async function check() {
      try {
        const job = await request<Job>('/api/jobs/' + drawingJob, 'GET', undefined, ac.signal)
        message(job.phase)
        if (job.status === 'Completed') {
          const next = await request<Revision>(
            '/api/jobs/' + drawingJob + '/imported',
            'GET',
            undefined,
            ac.signal,
          )
          clear()
          history.replaceState(null, '', '#workspace/' + next.id)
          setRev(next)
          setP(next.setup)
          setActiveMaterial(next.setup.materials[0]?.id ?? null)
          select(null)
          hide([])
          setMeshFile(null)
          setPendingFixture(null)
          message(t('import.done'))
          setStage(1)
        } else if (['Cancelled', 'Failed', 'Unknown / worker disconnected'].includes(job.status)) {
          throw new Error(job.diagnostic || job.status)
        } else timer = setTimeout(check, 500)
      } catch (e) {
        if (!ac.signal.aborted) {
          clear()
          problem(e)
        }
      }
    }
    void check()
    return () => {
      ac.abort()
      clearTimeout(timer)
    }
  }, [drawingJob, rev.id, problem, t])
  useEffect(() => {
    request<Record<string, string>>('/api/capabilities').then(setCap).catch(problem)
  }, [problem])
  useEffect(() => {
    const ac = new AbortController()
    request<Display>('/api/display', 'POST', p, ac.signal)
      .then(setDisplay)
      .catch((e) => {
        if (!ac.signal.aborted) {
          setDisplay(null)
          problem(e)
        }
      })
    return () => ac.abort()
  }, [p, problem])
  const active = anyActive([...meshJobs, ...deckJobs, ...related])
  useEffect(() => {
    let live = true
    async function poll() {
      try {
        const [ms, ds, rs] = await Promise.all([
          request<Job[]>('/api/meshes'),
          request<Job[]>('/api/decks'),
          request<Job[]>('/api/runs'),
        ])
        if (live) {
          setMeshJobs(ms.filter((j) => j.project === rev.project))
          setDeckJobs(ds.filter((j) => j.project === rev.project))
          setRelated(rs.filter((r) => r.revision === rev.id))
        }
      } catch (e) {
        if (live) problem(e)
      }
    }
    void poll()
    // Faster cadence only while a job can still change; the interval is rebuilt on
    // the transition to idle, not on every poll result.
    const timer = setInterval(poll, active ? ACTIVE_POLL_MS : IDLE_POLL_MS)
    return () => {
      live = false
      clearInterval(timer)
    }
  }, [rev.id, rev.project, generation, problem, active])
  // Mesh identity is decided by the saved revision, never by the draft: editing a
  // motion value must reuse the mesh, editing geometry or mesh controls must not.
  const completedMeshes = meshJobs.filter((j) => j.mode === 'MESH' && j.status === 'Completed')
  const meshJob = completedMeshes[0] ?? null
  const compatibleMesh = meshJob && meshJob.mesh_compat === rev.mesh_compat ? meshJob : null
  const fixture = compatibleMesh?.fixture ?? null
  const fixtureReviewed = !!fixture && fixture.count > 0
  const motionValid = p.motion.travel < 0 && p.motion.duration > 0
  const deck =
    deckJobs.find(
      (j) => j.revision === rev.id && j.mesh === compatibleMesh?.id && j.status === 'Completed',
    ) ?? null
  // A deck prepared before the fixture changed is stale even for the same mesh.
  const deckReady = !!deck && !!fixture && deck.fixture_hash === fixture.hash
  useEffect(() => {
    setPendingFixture(null)
    setFixtureMode(false)
    if (!compatibleMesh) {
      setMeshFile(null)
      return
    }
    const ac = new AbortController()
    request<Mesh>(artifact(compatibleMesh.id, 'mesh.json'), 'GET', undefined, ac.signal)
      .then(setMeshFile)
      .catch((e) => {
        if (!ac.signal.aborted) {
          setMeshFile(null)
          problem(e)
        }
      })
    return () => ac.abort()
  }, [compatibleMesh?.id, generation, problem])
  useEffect(() => {
    setPlacement(null)
    if (!deck?.manifest.includes('result-metadata.json')) return
    const ac = new AbortController()
    request<{ placement: { initial_vertical_mesh_clearance_mm: number } }>(
      artifact(deck.id, 'result-metadata.json'),
      'GET',
      undefined,
      ac.signal,
    )
      .then((meta) => setPlacement(meta.placement))
      .catch((e) => {
        if (!ac.signal.aborted) problem(e)
      })
    return () => ac.abort()
  }, [deck?.id, problem])
  useEffect(() => {
    if (!dirty) return
    const guard = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [dirty])
  function edit(fn: (next: Project) => void) {
    if (locked) return
    setP((old) => {
      const n = structuredClone(old)
      fn(n)
      return n
    })
    setIssue('')
    message('')
    token.current = crypto.randomUUID()
  }
  const chosen = pick?.source ?? pick?.entity ?? pick?.id
  const face = p.faces.find((f) => f.id === chosen),
    edge = p.edges.find((e) => e.id === chosen)
  const component = p.components.find(
    (c) => c.id === (pick?.component ?? face?.component ?? edge?.component ?? pick?.id),
  )
  const mat = p.materials.find((m) => m.id === face?.material)
  const mount = p.selections.find((s) => s.id === p.mounting.selection)!
  const colors = useMemo(
    () =>
      Object.fromEntries(
        p.faces.map((f) => [
          f.id,
          p.materials.find((m) => m.id === f.material)?.color ?? '#acb7b9',
        ]),
      ),
    [p],
  )
  const quality = useMemo(() => (meshFile ? meshQuality(meshFile, p) : null), [meshFile, p])
  const invalidMaterials = useMemo(
    () => p.materials.filter((material) => materialIssues(material).errors.length > 0),
    [p.materials],
  )
  const steps = useMemo(
    () => WORKFLOW_STEPS.map((step) => t(step.nameKey)),
    [t],
  )
  const states = useMemo(
    () =>
      workflowStates({
        project: p,
        mesh: meshJob,
        compatibleMesh,
        fixture,
        deck: deckReady ? deck : null,
        runs: related,
      }),
    [p, meshJob, compatibleMesh, fixture, deck, deckReady, related],
  )
  function target(next: SelectionMode) {
    setMode(next)
    if (next === 'component') {
      const c = component ?? p.components[0]
      select({ kind: next, id: c.id, component: c.id })
    } else if (next === 'face' && p.faces.length) {
      const f = face ?? p.faces[0]
      select({ kind: next, id: f.id, entity: f.id, component: f.component })
    } else if (next === 'edge') {
      const e = edge ?? p.edges.find((e) => mount.entities.includes(e.id)) ?? p.edges[0]
      select({ kind: next, id: e.id, entity: e.id, component: e.component })
    } else select(null)
  }
  function changeStage(i: number) {
    setStage(i)
    setShowMesh(i === 5 || i === 6)
    target(i === 2 ? 'face' : i === 3 ? 'edge' : 'component')
  }
  async function save() {
    if (!dirty) return rev
    const saved = await request<Revision>('/api/projects/' + rev.project, 'PUT', {
      base: rev.id,
      setup: p,
    })
    history.replaceState(null, '', '#workspace/' + saved.id)
    setRev(saved)
    setP(saved.setup)
    // The mesh is not cleared: its identity decides whether it is still reusable.
    message(t('status.revisionSaved', { number: saved.number }))
    return saved
  }
  async function execute(fn: () => Promise<unknown>) {
    if (busy) return
    setBusy(true)
    setIssue('')
    try {
      await fn()
    } catch (e) {
      problem(e)
    } finally {
      setBusy(false)
    }
  }
  async function generate() {
    const r = await save()
    await request<Job>('/api/meshes', 'POST', {
      revision: r.id,
      token: crypto.randomUUID(),
    })
    setShowMesh(true)
    setFixtureMode(false)
    setPendingFixture(null)
    refresh((g) => g + 1)
    message('')
  }
  async function prepareDeck() {
    if (!compatibleMesh || !fixtureReviewed) return
    await request<Job>('/api/decks', 'POST', {
      revision: rev.id,
      token: crypto.randomUUID(),
      mesh: compatibleMesh.id,
    })
    refresh((g) => g + 1)
    message('')
  }
  async function saveFixture(labels: string[]) {
    if (!compatibleMesh) return
    await request<Job>('/api/meshes/' + compatibleMesh.id + '/fixture', 'PUT', { labels })
    setPendingFixture(null)
    refresh((g) => g + 1)
    message(t('mesh.fixtureSaved', { count: labels.length }))
  }
  async function resolveLegacyFixture() {
    if (!compatibleMesh) return
    const resolved = await request<FixtureInfo>(
      '/api/meshes/' + compatibleMesh.id + '/fixture/edges',
      'POST',
      {},
    )
    setPendingFixture(resolved.labels)
    setFixtureMode(true)
    setShowMesh(true)
    target('node')
    message(t('mesh.fixtureResolved', { count: resolved.count }))
  }
  function boxSelect(labels: string[]) {
    setPendingFixture((old) => {
      const base = old ?? fixture?.labels ?? []
      if (boxOperation === 'replace') return labels
      const merged =
        boxOperation === 'add' ? [...new Set([...base, ...labels])] : base.filter((l) => !labels.includes(l))
      return merged.sort(
        (a, b) => Number(a.split(':')[1]) - Number(b.split(':')[1]),
      )
    })
  }
  async function submit() {
    if (!deckReady || !deck) return
    const r = await request<Job>('/api/runs', 'POST', {
      name: runName,
      revision: rev.id,
      deck: deck.id,
      token: token.current,
      cpus,
      mode: execution,
      scenario: execution === 'DEMO' ? scenario : 'success',
    })
    token.current = crypto.randomUUID()
    go('diagnostics/' + r.id)
  }
  async function importFile(f: File) {
    if (!unitConfirmed) throw new Error(t('import.needsUnits'))
    const r = await save(),
      form = new FormData()
    form.append('base', r.id)
    form.append('units', 'N-mm-s-tonne')
    form.append('file', f)
    const job = await request<Job>('/api/projects/' + r.project + '/drawing', 'POST', form)
    sessionStorage.setItem('import:' + r.id, job.id)
    setDrawingJob(job.id)
    message(t('import.queued'))
  }
  function switchDimension(value: Project['dimension']) {
    edit((n) => {
      n.dimension = value
      n.formulation = value === '2D' ? 'plane_stress' : 'extrusion_preview'
    })
    setShowMesh(false)
    select(null)
  }
  function updateMaterial(id: string, patch: Partial<Project['materials'][number]>) {
    edit((n) => {
      const card = n.materials.find((m) => m.id === id)
      if (card) Object.assign(card, patch)
    })
  }
  const selectionName = pick?.instance
    ? pick.id
    : pick?.kind === 'component'
      ? component?.name
      : (edge?.name ?? face?.name ?? pick?.id)
  const dimension = p.dimension === '3D'
  const blockedReason = invalidMaterials.length
    ? invalidMaterials.map((m) => m.name).join(' · ')
    : ''
  return (
    <main className="workspace page">
      <div className="crumb">
        <span>{t('workspace.workbench')}</span>
        <ChevronRight />
        <button onClick={() => go('dashboard')}>{t('workspace.projects')}</button>
        {rev.group_name && (
          <>
            <ChevronRight />
            <span className="crumb-group">{rev.group_name}</span>
          </>
        )}
        <ChevronRight />
        <span className="crumb-model">{p.name}</span>
        <ChevronRight />
        {t('workspace.revision', { number: String(rev.number).padStart(2, '0') })}
      </div>
      <div className="page-heading">
        <div>
          <h1>{p.name}</h1>
          <div className="subtitle">
            <span className="dimension">
              <Axis3D />
              {p.dimension}
            </span>
            <span>{dimension ? t('workspace.extrusionPreview') : t('workspace.planeStress')}</span>
            <i />
            N–mm–s–tonne
            <i />
            {p.source.kind === 'synthetic' ? t('workspace.synthetic') : p.source.filename}
          </div>
        </div>
        <div className="actions">
          {locked ? (
            <>
              <span className="badge">{t('workspace.submittedSetup')}</span>
              <button
                onClick={() =>
                  execute(async () => {
                    const r = await request<Revision>(
                      '/api/jobs/' + locked.id + '/duplicate',
                      'POST',
                    )
                    go('workspace/' + r.id)
                  })
                }
              >
                <Copy />
                {t('dashboard.duplicate')}
              </button>
            </>
          ) : (
            <>
              <button
                disabled={!dirty || busy || !!blockedReason}
                title={blockedReason || undefined}
                onClick={() => execute(save)}
              >
                <Save />
                {t('workspace.saveRevision')}
              </button>
              <button className="primary" onClick={() => changeStage(6)}>
                <Play />
                {t('workspace.reviewRun')}
              </button>
            </>
          )}
        </div>
      </div>
      {blockedReason && (
        <p className="error-text blocked-banner" role="alert">
          {t('materials.err.finite')} — {blockedReason}
        </p>
      )}
      <div className="workgrid">
        <aside className="left card">
          <div className="panel-title">
            <Waypoints />
            {t('workspace.workflow')}
          </div>
          <WorkflowNavigation stage={stage} states={states} onSelect={changeStage} />
          <div className="panel-title tree-title">
            <Boxes />
            {t('workspace.assemblyTree')}
          </div>
          <AssemblyTree
            project={p}
            currentComponent={component?.id}
            chosen={chosen}
            hidden={hidden}
            expanded={expanded}
            onExpand={(id) =>
              expand((old) =>
                old.includes(id) ? old.filter((value) => value !== id) : [...old, id],
              )
            }
            onVisibility={(id) =>
              hide((old) =>
                old.includes(id) ? old.filter((value) => value !== id) : [...old, id],
              )
            }
            onPick={(kind, id, componentId) => {
              setMode(kind)
              setStage(kind === 'face' ? 2 : kind === 'edge' ? 3 : 1)
              select({ kind, id, entity: id, component: componentId })
            }}
          />
        </aside>
        <section className="canvas-card card">
          <div className="panel-title">
            <Box />
            {t('workspace.geometryViewport')}
            <div className="spacer" />
            <span className="view-label">
              {dimension ? t('workspace.view3d') : t('workspace.view2d')}
            </span>
          </div>
          <div className="canvas-toolbar">
            <div className="segment">
              {(['2D', '3D'] as const).map((d) => (
                <button
                  key={d}
                  disabled={!!locked && p.dimension !== d}
                  className={p.dimension === d ? 'active' : ''}
                  aria-pressed={p.dimension === d}
                  onClick={() => {
                    if (d !== p.dimension) switchDimension(d)
                  }}
                >
                  {d}
                </button>
              ))}
            </div>
            <div className="divider" />
            <label className="pick-mode">
              <MousePointer2 />
              <select
                aria-label={t('workspace.selectionMode')}
                value={mode}
                onChange={(e) => target(e.target.value as SelectionMode)}
              >
                <option value="component">{t('sel.component')}</option>
                <option value="face">{dimension ? t('sel.face') : t('sel.region')}</option>
                <option value="edge">{t('sel.edge')}</option>
                {meshFile && showMesh && (
                  <>
                    <option value="element">{t('sel.element')}</option>
                    <option value="node">{t('sel.node')}</option>
                  </>
                )}
              </select>
            </label>
            <div className="spacer" />
            {meshFile && compatibleMesh && (
              <button
                className={'icon ' + (fixtureMode ? 'active' : '')}
                title={t('mesh.fixedNodesMode')}
                aria-label={t('mesh.fixedNodesMode')}
                aria-pressed={fixtureMode}
                onClick={() => {
                  const next = !fixtureMode
                  setFixtureMode(next)
                  setShowMesh(true)
                  if (next) target('node')
                }}
              >
                <CircleDot />
              </button>
            )}
            {meshFile && (
              <button
                className={'icon ' + (showMesh ? 'active' : '')}
                title={t('workspace.toggleMesh')}
                aria-label={t('workspace.toggleMesh')}
                aria-pressed={showMesh}
                onClick={() => setShowMesh((v) => !v)}
              >
                <Grid2X2 />
              </button>
            )}
          </div>
          <div className="viewport-wrap">
            <Viewport
              dimension={p.dimension}
              display={display}
              mode={mode}
              selection={pick}
              onSelect={(hit) => {
                select(hit)
                message('')
                if (hit?.kind === 'face' && stage === 1) setStage(2)
                if (hit?.kind === 'edge' && stage === 1) setStage(3)
              }}
              colors={colors}
              hidden={hidden}
              mesh={showMesh ? meshFile : null}
              panelOffset={p.motion.offset}
              boxSelect={fixtureMode && !!compatibleMesh}
              boxOperation={boxOperation}
              selectedNodes={pendingFixture ?? fixture?.labels ?? []}
              nodeInstances={['WS-1']}
              onBoxSelect={boxSelect}
            />
          </div>
          <div className="legend">
            {p.materials.map((m) => (
              <span key={m.id}>
                <b style={{ background: m.color }} />
                {m.name}
              </span>
            ))}
            <span>
              <b style={{ background: '#50616e' }} />
              {t('workspace.rigidPanel')}
            </span>
          </div>
          <div className="canvas-footer">
            <span>
              <MousePointer2 />
              {dimension ? t('workspace.hint3d') : t('workspace.hint2d')}
            </span>
            <span>
              {t('workspace.selectionCounts', { regions: p.faces.length, edges: p.edges.length })}
            </span>
          </div>
        </section>
        <aside className="right card">
          <div className="panel-title">
            <SlidersHorizontal />
            {t('workspace.properties')}
          </div>
          <div className="property-body">
            <div className="eyebrow">{steps[stage]}</div>
            <fieldset disabled={!!locked || busy}>
              {stage === 0 && (
                <>
                  <h2>{t('import.title')}</h2>
                  <label>
                    {t('import.projectName')}
                    <input
                      value={p.name}
                      maxLength={100}
                      onChange={(e) =>
                        edit((n) => {
                          n.name = e.target.value
                        })
                      }
                    />
                  </label>
                  <Facts
                    rows={[
                      [t('import.source'), p.source.filename],
                      [t('import.sectionPlane'), 'XY · Z = 0'],
                      [t('import.units'), 'N–mm–s–tonne'],
                    ]}
                  />
                  {rev.source_id && (
                    <a className="asset" href={'/api/revisions/' + rev.id + '/drawing'} download>
                      <ArrowDownToLine />
                      {t('import.download')}
                    </a>
                  )}
                  <p>{t('import.help')}</p>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={unitConfirmed}
                      onChange={(e) => confirmUnit(e.target.checked)}
                    />
                    {t('import.confirmUnits')}
                  </label>
                  <input
                    ref={file}
                    hidden
                    type="file"
                    accept=".dxf,.dwg"
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) void execute(() => importFile(f))
                      e.target.value = ''
                    }}
                  />
                  <button disabled={!unitConfirmed} onClick={() => file.current?.click()}>
                    <FileInput />
                    {t('import.action')}
                  </button>
                  <small>
                    {cap.dwg === 'Configured' ? t('import.odaConfigured') : cap.dwg}
                  </small>
                </>
              )}
              {stage === 1 && (
                <>
                  <h2>{component?.name ?? t('components.select')}</h2>
                  {component && (
                    <>
                      <span className="kind-tag">
                        <Box />
                        {t('components.kind')}
                      </span>
                      <label>
                        {t('components.role')}
                        <select
                          value={component.role}
                          onChange={(e) =>
                            edit((n) => {
                              n.components.find((c) => c.id === component.id)!.role = e.target
                                .value as typeof component.role
                            })
                          }
                        >
                          {(
                            ['seal', 'moving_panel', 'vehicle_body', 'unassigned'] as const
                          ).map((role) => (
                            <option key={role} value={role}>
                              {t(('role.' + role) as TranslationKey)}
                            </option>
                          ))}
                        </select>
                      </label>
                      <Facts
                        rows={[
                          [
                            t('components.regions'),
                            p.faces.filter((f) => f.component === component.id).length,
                          ],
                          [
                            t('components.boundaryEdges'),
                            p.edges.filter((e) => e.component === component.id).length,
                          ],
                        ]}
                      />
                    </>
                  )}
                  <h3>{t('components.sectionRegions')}</h3>
                  <div className="region-list">
                    {p.faces
                      .filter((f) => !component || f.component === component.id)
                      .map((f) => (
                        <button
                          key={f.id}
                          onClick={() => {
                            setStage(2)
                            setMode('face')
                            select({ kind: 'face', id: f.id, entity: f.id, component: f.component })
                          }}
                        >
                          <span className="swatch" style={{ background: colors[f.id] }} />
                          {f.name}
                          <ChevronRight />
                        </button>
                      ))}
                  </div>
                </>
              )}
              {stage === 2 && (
                <>
                  <h2>{face?.name ?? t('materials.select')}</h2>
                  {face && (
                    <>
                      <span className="kind-tag">
                        <Layers3 />
                        {t('materials.kind')}
                      </span>
                      <label>
                        {t('materials.card')}
                        <select
                          value={face.material ?? ''}
                          onChange={(e) =>
                            edit((n) => {
                              n.faces.find((f) => f.id === face.id)!.material =
                                e.target.value || null
                            })
                          }
                        >
                          <option value="">
                            {face.cavity ? t('materials.cavity') : t('materials.unassigned')}
                          </option>
                          {p.materials.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      {mat && (
                        <>
                          <Facts
                            rows={[
                              [t('materials.cardVersion'), mat.version],
                              [
                                t('materials.model'),
                                mat.model === 'hyperfoam_test'
                                  ? t('materials.modelHyperfoam')
                                  : t('materials.modelLinear'),
                              ],
                              [t('materials.density'), mat.density.toExponential(2)],
                            ]}
                          />
                          <Plot
                            x={
                              mat.model === 'hyperfoam_test'
                                ? mat.test_data.map((d) => d[1])
                                : [0, 0.01]
                            }
                            y={
                              mat.model === 'hyperfoam_test'
                                ? mat.test_data.map((d) => d[0])
                                : [0, (mat.young ?? 0) * 0.01]
                            }
                            xlabel={t('materials.nominalStrain')}
                            ylabel={t('materials.stress')}
                          />
                        </>
                      )}
                      <h3>{t('materials.list')}</h3>
                      <MaterialEditor
                        materials={p.materials}
                        faces={p.faces}
                        selected={activeMaterial}
                        onSelect={setActiveMaterial}
                        onAdd={() => {
                          const card = freshCard(p.materials, t('materials.defaultName'))
                          edit((n) => {
                            n.materials.push(card)
                          })
                          return card
                        }}
                        onDuplicate={(id) => {
                          const source = p.materials.find((m) => m.id === id)
                          if (!source) return
                          const copy: Project['materials'][number] = {
                            ...structuredClone(source),
                            id: freshCard(p.materials, source.name).id,
                            name: source.name + ' · copy',
                            version: 1,
                          }
                          edit((n) => {
                            n.materials.push(copy)
                          })
                          setActiveMaterial(copy.id)
                        }}
                        onDelete={(id) => {
                          edit((n) => {
                            n.materials = n.materials.filter((m) => m.id !== id)
                          })
                          setActiveMaterial(p.materials.find((m) => m.id !== id)?.id ?? null)
                        }}
                        onUpdate={updateMaterial}
                        disabled={!!locked || busy}
                        onRevealRegion={(faceId) => {
                          const target = p.faces.find((f) => f.id === faceId)
                          if (!target) return
                          setMode('face')
                          select({
                            kind: 'face',
                            id: target.id,
                            entity: target.id,
                            component: target.component,
                          })
                        }}
                      />
                    </>
                  )}
                </>
              )}
              {stage === 3 && (
                <>
                  <h2>{t('contact.title')}</h2>
                  <label>
                    {t('contact.selectedBoundary')}
                    <input readOnly value={edge?.name ?? t('contact.selectEdge')} />
                  </label>
                  {edge && component?.role === 'seal' && (
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={mount.entities.includes(edge.id)}
                        onChange={(e) =>
                          edit((n) => {
                            n.selections.find((s) => s.id === mount.id)!.entities = e.target.checked
                              ? [...mount.entities, edge.id]
                              : mount.entities.filter((t2) => t2 !== edge.id)
                          })
                        }
                      />
                      {t('contact.fixEdge')}
                    </label>
                  )}
                  <Facts
                    rows={[
                      [t('contact.mounting'), t('contact.fixedEdges', { count: mount.entities.length })],
                      [t('contact.normal'), t('contact.hard')],
                      [t('contact.domain'), t('contact.allExterior')],
                    ]}
                  />
                  <NumberInput
                    label={t('contact.friction')}
                    value={p.contact.friction}
                    min={0}
                    max={5}
                    rangeHint="0 – 5"
                    onChange={(v) =>
                      edit((n) => {
                        n.contact.friction = v
                      })
                    }
                  />
                </>
              )}
              {stage === 4 && (
                <>
                  <h2>{t('motion.title')}</h2>
                  <NumberInput
                    label={t('motion.offset')}
                    unit="mm"
                    value={p.motion.offset}
                    onChange={(v) =>
                      edit((n) => {
                        n.motion.offset = v
                      })
                    }
                  />
                  <NumberInput
                    label={t('motion.travel')}
                    unit="mm"
                    max={0}
                    rangeHint="< 0 (closing direction)"
                    value={p.motion.travel}
                    onChange={(v) =>
                      edit((n) => {
                        n.motion.travel = v
                      })
                    }
                  />
                  <NumberInput
                    label={t('motion.duration')}
                    unit="s"
                    min={1e-9}
                    value={p.motion.duration}
                    onChange={(v) =>
                      edit((n) => {
                        n.motion.duration = v
                      })
                    }
                  />
                  <p>{t('motion.help')}</p>
                </>
              )}
              {dimension && stage !== 7 && (
                <>
                  <h3>{t('extrusion.title')}</h3>
                  <NumberInput
                    label={t('extrusion.length')}
                    unit="mm"
                    min={1e-9}
                    value={p.extrusion.length}
                    onChange={(v) =>
                      edit((n) => {
                        n.extrusion.length = v
                      })
                    }
                  />
                  <NumberInput
                    label={t('extrusion.subdivisions')}
                    step="1"
                    min={1}
                    max={100}
                    value={p.extrusion.subdivisions}
                    onChange={(v) =>
                      edit((n) => {
                        n.extrusion.subdivisions = v
                      })
                    }
                  />
                  <small>{t('extrusion.previewOnly')}</small>
                </>
              )}
              {stage === 5 && !dimension && (
                <>
                  <h2>{t('mesh.title')}</h2>
                  <NumberInput
                    label={t('mesh.globalSize')}
                    unit="mm"
                    min={0.01}
                    max={10000}
                    rangeHint="0.01 – 10000"
                    value={p.mesh.size}
                    onChange={(v) =>
                      edit((n) => {
                        n.mesh.size = v
                      })
                    }
                  />
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={p.mesh.recombine}
                      onChange={(e) =>
                        edit((n) => {
                          n.mesh.recombine = e.target.checked
                        })
                      }
                    />
                    {t('mesh.recombine')}
                  </label>
                  <label>
                    {t('mesh.localEdge')}
                    <select
                      value={edge?.id ?? ''}
                      onChange={(e) => {
                        const x = p.edges.find((t2) => t2.id === e.target.value)
                        if (x) {
                          setMode('edge')
                          select({ kind: 'edge', id: x.id, entity: x.id, component: x.component })
                        }
                      }}
                    >
                      <option value="">{t('mesh.selectEdge')}</option>
                      {p.edges.map((e) => (
                        <option key={e.id} value={e.id}>
                          {e.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {edge && (
                    <NumberInput
                      label={t('mesh.edgeSize')}
                      unit="mm"
                      min={0.01}
                      max={10000}
                      value={p.mesh.local[edge.id] ?? p.mesh.size}
                      onChange={(v) =>
                        edit((n) => {
                          n.mesh.local[edge.id] = v
                        })
                      }
                    />
                  )}
                </>
              )}
              {stage === 6 && !dimension && (
                <>
                  <h2>{t('review.title')}</h2>
                  <Facts
                    rows={[
                      [t('review.formulation'), t('review.planeStress')],
                      [t('review.step'), t('review.implicitDynamic')],
                      [t('review.geometry'), t('review.nonlinear')],
                    ]}
                  />
                  <NumberInput
                    label={t('review.thickness')}
                    unit="mm"
                    min={1e-9}
                    value={p.analysis.thickness}
                    onChange={(v) =>
                      edit((n) => {
                        n.analysis.thickness = v
                      })
                    }
                  />
                  <label>
                    {t('review.forceReporting')}
                    <select
                      value={p.analysis.force_normalization}
                      onChange={(e) =>
                        edit((n) => {
                          n.analysis.force_normalization = e.target.value as 'total' | 'per_mm'
                        })
                      }
                    >
                      <option value="total">{t('review.totalReaction')}</option>
                      <option value="per_mm">{t('review.perMm')}</option>
                    </select>
                  </label>
                </>
              )}
              {(stage === 5 || stage === 6) && !dimension && (
                <>
                  <h3>{t('mesh.meshSection')}</h3>
                  <button
                    className="primary wide"
                    disabled={busy || !!blockedReason}
                    title={blockedReason || undefined}
                    onClick={() => execute(generate)}
                  >
                    <Grid2X2 />
                    {t('mesh.generate')}
                  </button>
                  {meshJob && !dirty && (
                    <div className="build-info" data-testid="mesh-status">
                      <strong>
                        {compatibleMesh ? t('mesh.meshReady') : t('mesh.meshStale')}
                      </strong>
                      {meshJob.diagnostic && <p className="error-text">{meshJob.diagnostic}</p>}
                      {compatibleMesh && meshJob.mesh_digest && (
                        <small>
                          {t('mesh.meshDigest')} {meshJob.mesh_digest.slice(0, 12)}
                        </small>
                      )}
                    </div>
                  )}
                  {quality && meshFile && compatibleMesh && !dirty && (
                    <MeshReview
                      quality={quality}
                      project={p}
                      clearance={placement?.initial_vertical_mesh_clearance_mm ?? null}
                    />
                  )}
                </>
              )}
              {stage === 5 && !dimension && compatibleMesh && !dirty && (
                <>
                  <h3>{t('mesh.fixedNodes')}</h3>
                  <p>{t('mesh.fixedNodesHelp')}</p>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={fixtureMode}
                      onChange={(e) => {
                        setFixtureMode(e.target.checked)
                        setShowMesh(true)
                        if (e.target.checked) target('node')
                      }}
                    />
                    {t('mesh.fixedNodesCheck')}
                  </label>
                  <label>
                    {t('mesh.rectangleOperation')}
                    <select
                      value={boxOperation}
                      onChange={(e) =>
                        setBoxOperation(e.target.value as 'replace' | 'add' | 'subtract')
                      }
                    >
                      <option value="replace">{t('mesh.op.replace')}</option>
                      <option value="add">{t('mesh.op.add')}</option>
                      <option value="subtract">{t('mesh.op.subtract')}</option>
                    </select>
                  </label>
                  <Facts
                    rows={[
                      [
                        t('mesh.fixedNodeCount'),
                        (pendingFixture ?? fixture?.labels ?? []).length,
                      ],
                      [t('mesh.fixtureSource'), fixture ? t('mesh.sourceNodes') : t('mesh.sourceNone')],
                    ]}
                  />
                  <div className="fixture-actions">
                    <button
                      className="primary"
                      disabled={!pendingFixture}
                      onClick={() => execute(() => saveFixture(pendingFixture ?? []))}
                    >
                      <CheckCheck />
                      {t('mesh.saveFixture')}
                    </button>
                    <button
                      disabled={!(pendingFixture ?? fixture?.labels ?? []).length}
                      onClick={() => setPendingFixture([])}
                    >
                      {t('mesh.clear')}
                    </button>
                  </div>
                  {pendingFixture && (
                    <small>{t('mesh.fixtureUnsaved', { count: pendingFixture.length })}</small>
                  )}
                  {!fixture && mount.entities.length > 0 && (
                    <button
                      className="wide"
                      disabled={busy}
                      onClick={() => execute(resolveLegacyFixture)}
                    >
                      <ScanLine />
                      {t('mesh.resolveEdges', { count: mount.entities.length })}
                    </button>
                  )}
                </>
              )}
              {(stage === 5 || stage === 6) && !dimension && compatibleMesh && !dirty && (
                <>
                  <h3>{t('mesh.deckSection')}</h3>
                  <button
                    className="primary wide"
                    disabled={busy || !fixtureReviewed || !motionValid}
                    title={!fixtureReviewed ? t('hint.fixtureRequired') : !motionValid ? t('hint.motion') : undefined}
                    onClick={() => execute(prepareDeck)}
                  >
                    <FileText />
                    {t('mesh.prepareDeck')}
                  </button>
                  {deck && (
                    <div className="build-info" data-testid="deck-status">
                      <strong>{deckReady ? t('mesh.inputReady') : t('mesh.deckStale')}</strong>
                      {deckReady ? (
                        <a href={artifact(deck.id, 'analysis.inp')} target="_blank" rel="noreferrer">
                          <FileText />
                          {t('mesh.inspectDeck')}
                        </a>
                      ) : (
                        <small>{t('mesh.deckStaleHint')}</small>
                      )}
                    </div>
                  )}
                </>
              )}
              {stage === 6 && !dimension && (
                <>
                  <h3>{t('review.submit')}</h3>
                  <label>
                    {t('review.runName')}
                    <input
                      maxLength={100}
                      value={runName}
                      onChange={(e) => setRunName(e.target.value)}
                    />
                  </label>
                  <label>
                    {t('review.mode')}
                    <select
                      value={execution}
                      onChange={(e) => {
                        setExecution(e.target.value)
                        token.current = crypto.randomUUID()
                      }}
                    >
                      <option value="DEMO">{t('mode.demo')}</option>
                      <option value="ABAQUS">{t('mode.abaqus')}</option>
                    </select>
                  </label>
                  {execution === 'DEMO' ? (
                    <>
                      <small className="mode-label">{t('demo.notice')}</small>
                      <label>
                        {t('review.scenario')}
                        <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
                          <option value="success">{t('review.scenarioSuccess')}</option>
                          <option value="failure">{t('review.scenarioFailure')}</option>
                          <option value="slow">{t('review.scenarioSlow')}</option>
                          <option value="extraction_failure">{t('review.scenarioExtraction')}</option>
                        </select>
                      </label>
                    </>
                  ) : (
                    <>
                      <small>{cap.abaqus}</small>
                      <NumberInput
                        label={t('review.cpus')}
                        value={cpus}
                        min={1}
                        max={32}
                        step="1"
                        rangeHint="1 – 32"
                        onChange={setCpus}
                      />
                    </>
                  )}
                  <button
                    className="primary wide"
                    disabled={
                      !deckReady ||
                      dirty ||
                      busy ||
                      !runName.trim() ||
                      (execution === 'ABAQUS' && cap.abaqus !== 'Configured')
                    }
                    title={
                      !deckReady
                        ? t('hint.deckRequired')
                        : execution === 'ABAQUS' && cap.abaqus !== 'Configured'
                          ? cap.abaqus
                          : undefined
                    }
                    onClick={() => execute(submit)}
                  >
                    <Play />
                    {execution === 'ABAQUS' ? t('review.submitLicensed') : t('review.submitDemo')}
                  </button>
                </>
              )}
            </fieldset>
            {stage === 7 && (
              <>
                <h2>{t('results.revisionResults')}</h2>
                {related.length === 0 ? (
                  <p>{t('results.noRuns')}</p>
                ) : (
                  related.map((r) => (
                    <button
                      className="result-link"
                      key={r.id}
                      onClick={() =>
                        go((r.status === 'Completed' ? 'results/' : 'diagnostics/') + r.id)
                      }
                    >
                      {r.name}
                      <small>
                        {r.mode} · {labelFrom(t, 'state', r.status)}
                      </small>
                    </button>
                  ))
                )}
              </>
            )}
          </div>
        </aside>
      </div>
      <div className={'statusbar ' + (issue ? 'has-error' : '')} role="status">
        {busy ? <LoaderCircle className="spin" /> : issue ? <Activity /> : <CheckCheck />}
        <strong>
          {issue
            ? t('status.validation')
            : dirty
              ? t('status.unsaved')
              : locked
                ? t('status.historical')
                : t('status.saved')}
        </strong>
        <span>
          {issue ||
            info ||
            meshJob?.diagnostic ||
            deck?.diagnostic ||
            (busy
              ? t('status.working')
              : fixtureMode
                ? t('status.fixtureSelection', {
                    count: (pendingFixture ?? fixture?.labels ?? []).length,
                  })
                : selectionName
                  ? t('status.selected', { name: selectionName })
                : t('status.selectPrompt'))}
        </span>
        <span className="spacer" />
        <span>
          <CircleDot />
          {meshJob && !dirty
            ? labelFrom(t, 'phase', (deck ?? meshJob).phase)
            : t('status.localProject')}
        </span>
      </div>
    </main>
  )
}
