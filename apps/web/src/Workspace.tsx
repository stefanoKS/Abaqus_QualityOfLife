import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  ArrowDownToLine,
  Axis3D,
  Box,
  Boxes,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Copy,
  Eye,
  EyeOff,
  FileInput,
  FileText,
  Grid2X2,
  Layers3,
  Link2,
  LoaderCircle,
  MousePointer2,
  MoveVertical,
  Play,
  Save,
  ScanLine,
  SlidersHorizontal,
  Waypoints,
} from 'lucide-react'
import Viewport from './Viewport'
import type { Display, ViewMesh, Picked, SelectionMode } from './viewportModel'
import { Plot } from './Plot'
import {
  artifact,
  demoNotice,
  err,
  go,
  request,
  type Job,
  type Project,
  type Revision,
} from './api'

const steps = [
  { name: 'Import', icon: FileInput },
  { name: 'Components', icon: Boxes },
  { name: 'Materials', icon: Layers3 },
  { name: 'Mounting / Contact', icon: Link2 },
  { name: 'Motion', icon: MoveVertical },
  { name: 'Mesh', icon: Grid2X2 },
  { name: 'Review / Run', icon: Play },
  { name: 'Results', icon: Activity },
]
const roleNames = {
  seal: 'Weatherstrip seal',
  moving_panel: 'Moving panel',
  vehicle_body: 'Vehicle body',
  unassigned: 'Unassigned',
}
type Mesh = ViewMesh & { counts: Record<string, number> }
type Props = { initial: Revision; locked?: Job; notify: (msg: string) => void }
function NumberInput({
  label,
  value,
  onChange,
  min,
  step = 'any',
}: {
  label: string
  value: number
  onChange: (v: number) => void
  min?: number
  step?: string
}) {
  return (
    <label>
      {label}
      <input
        type="number"
        step={step}
        min={min}
        key={value}
        defaultValue={value}
        onBlur={(e) => {
          const n = e.currentTarget.valueAsNumber
          if (Number.isFinite(n) && n !== value) onChange(n)
          else e.currentTarget.value = String(value)
        }}
      />
    </label>
  )
}
function Facts({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl>
      {rows.map(([k, v]) => (
        <div key={k}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  )
}

export default function Workspace({ initial, locked, notify }: Props) {
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
  const [build, setBuild] = useState<Job | null>(null),
    [mesh, setMesh] = useState<Mesh | null>(null),
    [showMesh, setShowMesh] = useState(false)
  const [working, setBusy] = useState(false),
    [info, message] = useState(''),
    [issue, setIssue] = useState(''),
    [generation, refresh] = useState(0)
  const [cap, setCap] = useState<Record<string, string>>({}),
    [related, setRelated] = useState<Job[]>([])
  const [execution, setExecution] = useState('DEMO'),
    [scenario, setScenario] = useState('success'),
    [runName, setRunName] = useState('Closing analysis'),
    [cpus, setCpus] = useState(1)
  const [unitConfirmed, confirmUnit] = useState(false),
    [expanded, expand] = useState<string[]>([])
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
          select(null)
          hide([])
          setBuild(null)
          setMesh(null)
          message('Drawing imported. Review roles, materials, and mounting.')
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
  }, [drawingJob, rev.id, problem])
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
  useEffect(() => {
    let live = true
    async function poll() {
      try {
        const [bs, rs] = await Promise.all([
          request<Job[]>('/api/builds'),
          request<Job[]>('/api/runs'),
        ])
        if (live) {
          setBuild(bs.find((b) => b.revision === rev.id) ?? null)
          setRelated(rs.filter((r) => r.revision === rev.id))
        }
      } catch (e) {
        if (live) problem(e)
      }
    }
    void poll()
    const timer = setInterval(poll, 1400)
    return () => {
      live = false
      clearInterval(timer)
    }
  }, [rev.id, generation, problem])
  const ready = build?.status === 'Completed' && !dirty
  useEffect(() => {
    setMesh(null)
    setPlacement(null)
    if (!build?.manifest.includes('mesh.json') || dirty) return
    const ac = new AbortController()
    if (build.manifest.includes('result-metadata.json'))
      request<{ placement: { initial_vertical_mesh_clearance_mm: number } }>(
        artifact(build.id, 'result-metadata.json'),
        'GET',
        undefined,
        ac.signal,
      )
        .then((meta) => setPlacement(meta.placement))
        .catch((e) => {
          if (!ac.signal.aborted) problem(e)
        })
    request<Mesh>(artifact(build.id, 'mesh.json'), 'GET', undefined, ac.signal)
      .then(setMesh)
      .catch((e) => {
        if (!ac.signal.aborted) problem(e)
      })
    return () => ac.abort()
  }, [build?.id, build?.status, dirty, problem])
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
    setBuild(null)
    setMesh(null)
    message('Revision ' + saved.number + ' saved.')
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
    const b = await request<Job>('/api/builds', 'POST', {
      revision: r.id,
      token: crypto.randomUUID(),
    })
    setBuild(b)
    setShowMesh(true)
    refresh((g) => g + 1)
    message('')
  }
  async function submit() {
    if (!ready || !build) return
    const r = await request<Job>('/api/runs', 'POST', {
      name: runName,
      revision: rev.id,
      build: build.id,
      token: token.current,
      cpus,
      mode: execution,
      scenario: execution === 'DEMO' ? scenario : 'success',
    })
    token.current = crypto.randomUUID()
    go('diagnostics/' + r.id)
  }
  async function importFile(f: File) {
    if (!unitConfirmed) throw new Error('Confirm that the drawing coordinates are in millimetres.')
    const r = await save(),
      form = new FormData()
    form.append('base', r.id)
    form.append('units', 'N-mm-s-tonne')
    form.append('file', f)
    const job = await request<Job>('/api/projects/' + r.project + '/drawing', 'POST', form)
    sessionStorage.setItem('import:' + r.id, job.id)
    setDrawingJob(job.id)
    message('Drawing import queued.')
  }
  function switchDimension(value: Project['dimension']) {
    edit((n) => {
      n.dimension = value
      n.formulation = value === '2D' ? 'plane_stress' : 'extrusion_preview'
    })
    setShowMesh(false)
    select(null)
  }
  const selectionName = pick?.instance
    ? pick.id
    : pick?.kind === 'component'
      ? component?.name
      : (edge?.name ?? face?.name ?? pick?.id)
  const dimension = p.dimension === '3D'
  return (
    <main className="workspace page">
      <div className="crumb">
        <span>Workbench</span>
        <ChevronRight />
        <button onClick={() => go('dashboard')}>Projects</button>
        <ChevronRight />
        Revision {String(rev.number).padStart(2, '0')}
      </div>
      <div className="page-heading">
        <div>
          <h1>{p.name}</h1>
          <div className="subtitle">
            <span className="dimension">
              <Axis3D />
              {p.dimension}
            </span>
            <span>{dimension ? 'Straight extrusion preview' : 'Plane stress'}</span>
            <i />
            N–mm–s–tonne
            <i />
            {p.source.kind === 'synthetic' ? 'Synthetic example' : p.source.filename}
          </div>
        </div>
        <div className="actions">
          {locked ? (
            <>
              <span className="badge">Submitted setup</span>
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
                Duplicate setup
              </button>
            </>
          ) : (
            <>
              <button disabled={!dirty || busy} onClick={() => execute(save)}>
                <Save />
                Save revision
              </button>
              <button className="primary" onClick={() => changeStage(6)}>
                <Play />
                Review / Run
              </button>
            </>
          )}
        </div>
      </div>
      <div className="workgrid">
        <aside className="left card">
          <div className="panel-title">
            <Waypoints />
            Workflow
          </div>
          <nav className="steps" aria-label="Workflow">
            {steps.map(({ name, icon: Icon }, i) => (
              <button
                key={name}
                className={stage === i ? 'selected' : ''}
                onClick={() => changeStage(i)}
              >
                <Icon />
                {name}
                {stage === i && <ChevronRight />}
              </button>
            ))}
          </nav>
          <div className="panel-title tree-title">
            <Boxes />
            Assembly tree
          </div>
          <div className="tree">
            {p.components.map((c) => (
              <div key={c.id}>
                <div className={'tree-row ' + (component?.id === c.id ? 'current' : '')}>
                  <button
                    aria-label={'Expand ' + c.name}
                    onClick={() =>
                      expand((old) =>
                        old.includes(c.id) ? old.filter((v) => v !== c.id) : [...old, c.id],
                      )
                    }
                  >
                    {expanded.includes(c.id) ? <ChevronDown /> : <ChevronRight />}
                  </button>
                  <button
                    className="tree-item"
                    onClick={() => {
                      setMode('component')
                      select({ kind: 'component', id: c.id, component: c.id })
                      setStage(1)
                    }}
                  >
                    <Box />
                    {c.name}
                  </button>
                  <button
                    aria-label={'Toggle visibility ' + c.name}
                    onClick={() =>
                      hide((old) =>
                        old.includes(c.id) ? old.filter((id) => id !== c.id) : [...old, c.id],
                      )
                    }
                  >
                    {hidden.includes(c.id) ? <EyeOff /> : <Eye />}
                  </button>
                </div>
                {expanded.includes(c.id) && (
                  <div className="children">
                    {[
                      ...p.faces
                        .filter((f) => f.component === c.id)
                        .map((f) => ({ ...f, kind: 'face' as const })),
                      ...p.edges
                        .filter((e) => e.component === c.id)
                        .map((e) => ({ ...e, kind: 'edge' as const })),
                    ].map((t) => (
                      <button
                        key={t.id}
                        className={chosen === t.id ? 'active' : ''}
                        onClick={() => {
                          setMode(t.kind)
                          setStage(t.kind === 'face' ? 2 : 3)
                          select({ kind: t.kind, id: t.id, entity: t.id, component: c.id })
                        }}
                      >
                        {t.kind === 'face' ? <Layers3 /> : <ScanLine />}
                        {t.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </aside>
        <section className="canvas-card card">
          <div className="panel-title">
            <Box />
            Geometry viewport
            <div className="spacer" />
            <span className="view-label">{dimension ? '3D MODEL' : 'SECTION XY'}</span>
          </div>
          <div className="canvas-toolbar">
            <div className="segment">
              {(['2D', '3D'] as const).map((d) => (
                <button
                  key={d}
                  disabled={!!locked && p.dimension !== d}
                  className={p.dimension === d ? 'active' : ''}
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
                aria-label="Selection mode"
                value={mode}
                onChange={(e) => target(e.target.value as SelectionMode)}
              >
                <option value="component">Component</option>
                <option value="face">{dimension ? 'Face' : 'Region'}</option>
                <option value="edge">Edge</option>
                {mesh && showMesh && (
                  <>
                    <option value="element">Element</option>
                    <option value="node">Node</option>
                  </>
                )}
              </select>
            </label>
            <div className="spacer" />
            {mesh && (
              <button
                className={'icon ' + (showMesh ? 'active' : '')}
                title="Toggle mesh"
                aria-label="Toggle mesh"
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
              mesh={showMesh ? mesh : null}
              panelOffset={p.motion.offset}
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
              Rigid panel
            </span>
          </div>
          <div className="canvas-footer">
            <span>
              <MousePointer2 />
              {dimension ? 'Drag to orbit' : 'Drag to pan'} · Scroll to zoom
            </span>
            <span>
              {p.faces.length} regions · {p.edges.length} edges
            </span>
          </div>
        </section>
        <aside className="right card">
          <div className="panel-title">
            <SlidersHorizontal />
            Properties
          </div>
          <div className="property-body">
            <div className="eyebrow"> {steps[stage].name}</div>
            <fieldset disabled={!!locked || busy}>
              {stage === 0 && (
                <>
                  <h2>Drawing source</h2>
                  <label>
                    Project name
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
                      ['Source', p.source.filename],
                      ['Section plane', 'XY · Z = 0'],
                      ['Units', 'N–mm–s–tonne'],
                    ]}
                  />
                  {rev.source_id && (
                    <a className="asset" href={'/api/revisions/' + rev.id + '/drawing'} download>
                      <ArrowDownToLine />
                      Download source drawing
                    </a>
                  )}
                  <p>
                    Import a clean planar section with closed regions and a panel profile. A
                    replacement drawing starts a new revision with fresh selections.
                  </p>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={unitConfirmed}
                      onChange={(e) => confirmUnit(e.target.checked)}
                    />
                    Drawing coordinates are in mm
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
                    Import DXF / DWG
                  </button>
                  <small>{cap.dwg === 'Configured' ? 'ODA converter configured' : cap.dwg}</small>
                </>
              )}
              {stage === 1 && (
                <>
                  <h2>{component?.name ?? 'Select a component'}</h2>
                  {component && (
                    <>
                      <span className="kind-tag">
                        <Box />
                        Component
                      </span>
                      <label>
                        Engineering role
                        <select
                          value={component.role}
                          onChange={(e) =>
                            edit((n) => {
                              n.components.find((c) => c.id === component.id)!.role = e.target
                                .value as typeof component.role
                            })
                          }
                        >
                          {Object.entries(roleNames).map(([id, name]) => (
                            <option key={id} value={id}>
                              {name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <Facts
                        rows={[
                          ['Regions', p.faces.filter((f) => f.component === component.id).length],
                          [
                            'Boundary edges',
                            p.edges.filter((e) => e.component === component.id).length,
                          ],
                        ]}
                      />
                    </>
                  )}
                  <h3>Section regions</h3>
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
                  <h2>{face?.name ?? 'Select a region'}</h2>
                  {face && (
                    <>
                      <span className="kind-tag">
                        <Layers3 />
                        Material region
                      </span>
                      <label>
                        Material card
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
                            {face.cavity ? 'Cavity (unfilled)' : 'Unassigned'}
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
                              ['Card version', mat.version],
                              [
                                'Model',
                                mat.model === 'hyperfoam_test'
                                  ? 'Hyperfoam · test data'
                                  : 'Linear elastic',
                              ],
                              ['Density (tonne/mm³)', mat.density.toExponential(2)],
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
                            xlabel="Nominal strain"
                            ylabel="Stress (MPa)"
                          />
                        </>
                      )}
                    </>
                  )}
                </>
              )}
              {stage === 3 && (
                <>
                  <h2>Mounting & contact</h2>
                  <label>
                    Selected boundary
                    <input readOnly value={edge?.name ?? 'Select a section edge'} />
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
                              : mount.entities.filter((t) => t !== edge.id)
                          })
                        }
                      />
                      Fix this edge
                    </label>
                  )}
                  <Facts
                    rows={[
                      ['Mounting', mount.entities.length + ' fixed edges'],
                      ['Normal contact', 'Hard'],
                      ['Contact domain', 'All exterior'],
                    ]}
                  />
                  <NumberInput
                    label="Friction coefficient"
                    value={p.contact.friction}
                    min={0}
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
                  <h2>Panel motion</h2>
                  <NumberInput
                    label="Initial Y offset (mm)"
                    value={p.motion.offset}
                    onChange={(v) =>
                      edit((n) => {
                        n.motion.offset = v
                      })
                    }
                  />
                  <NumberInput
                    label="Prescribed Y travel (mm)"
                    value={p.motion.travel}
                    onChange={(v) =>
                      edit((n) => {
                        n.motion.travel = v
                      })
                    }
                  />
                  <NumberInput
                    label="Step duration (s)"
                    min={0}
                    value={p.motion.duration}
                    onChange={(v) =>
                      edit((n) => {
                        n.motion.duration = v
                      })
                    }
                  />
                  <p>
                    Travel starts at the assembled panel position. Contact onset requires a geometry
                    or results check.
                  </p>
                </>
              )}
              {dimension && stage !== 7 && (
                <>
                  <h3>Extruded segment</h3>
                  <NumberInput
                    label="Segment length (mm)"
                    value={p.extrusion.length}
                    onChange={(v) =>
                      edit((n) => {
                        n.extrusion.length = v
                      })
                    }
                  />
                  <NumberInput
                    label="Longitudinal subdivisions"
                    value={p.extrusion.subdivisions}
                    step="1"
                    onChange={(v) =>
                      edit((n) => {
                        n.extrusion.subdivisions = v
                      })
                    }
                  />
                  <small>Geometry preview only. Solving is available in 2D.</small>
                </>
              )}
              {stage === 5 && !dimension && (
                <>
                  <h2>Section mesh</h2>
                  <NumberInput
                    label="Global size (mm)"
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
                    Recombine triangles into quads
                  </label>
                  <label>
                    Local edge
                    <select
                      value={edge?.id ?? ''}
                      onChange={(e) => {
                        const x = p.edges.find((t) => t.id === e.target.value)
                        if (x) {
                          setMode('edge')
                          select({ kind: 'edge', id: x.id, entity: x.id, component: x.component })
                        }
                      }}
                    >
                      <option value="">Select an edge</option>
                      {p.edges.map((e) => (
                        <option key={e.id} value={e.id}>
                          {e.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {edge && (
                    <NumberInput
                      label="Edge size (mm)"
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
                  <h2>Closing analysis</h2>
                  <Facts
                    rows={[
                      ['Formulation', 'Plane stress'],
                      ['Step', 'Implicit dynamic'],
                      ['Geometry', 'Nonlinear'],
                    ]}
                  />
                  <NumberInput
                    label="Section thickness (mm)"
                    value={p.analysis.thickness}
                    onChange={(v) =>
                      edit((n) => {
                        n.analysis.thickness = v
                      })
                    }
                  />
                  <label>
                    Force reporting
                    <select
                      value={p.analysis.force_normalization}
                      onChange={(e) =>
                        edit((n) => {
                          n.analysis.force_normalization = e.target.value as 'total' | 'per_mm'
                        })
                      }
                    >
                      <option value="total">Total reaction (N)</option>
                      <option value="per_mm">Per mm of thickness (N/mm)</option>
                    </select>
                  </label>
                </>
              )}
              {(stage === 5 || stage === 6) && !dimension && (
                <>
                  <button
                    className="primary wide"
                    disabled={
                      busy ||
                      !!(
                        build &&
                        !['Failed', 'Completed', 'Cancelled'].includes(build.status) &&
                        !dirty
                      )
                    }
                    onClick={() => execute(generate)}
                  >
                    <Grid2X2 />
                    Generate mesh & input
                  </button>
                  {build && !dirty && (
                    <div className="build-info">
                      <strong>{build.status === 'Completed' ? 'Input ready' : build.status}</strong>
                      {mesh && (
                        <small>
                          {Object.entries(mesh.counts)
                            .map(([k, v]) => v + ' ' + k)
                            .join(' · ')}
                        </small>
                      )}
                      {placement && (
                        <>
                          <small>
                            Initial vertical clearance ·{' '}
                            {placement.initial_vertical_mesh_clearance_mm.toFixed(3)} mm
                          </small>
                          <small>Prescribed Y travel · {p.motion.travel} mm</small>
                          <small>
                            Travel beyond the initial gap ·{' '}
                            {Math.max(
                              0,
                              -p.motion.travel - placement.initial_vertical_mesh_clearance_mm,
                            ).toFixed(3)}{' '}
                            mm (geometric)
                          </small>
                        </>
                      )}
                      {build.diagnostic && <p className="error-text">{build.diagnostic}</p>}
                      {ready && (
                        <a
                          href={artifact(build.id, 'analysis.inp')}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <FileText />
                          Inspect input deck
                        </a>
                      )}
                    </div>
                  )}
                </>
              )}
              {stage === 6 && !dimension && (
                <>
                  <h3>Submit simulation</h3>
                  <label>
                    Run name
                    <input
                      maxLength={100}
                      value={runName}
                      onChange={(e) => setRunName(e.target.value)}
                    />
                  </label>
                  <label>
                    Execution mode
                    <select
                      value={execution}
                      onChange={(e) => {
                        setExecution(e.target.value)
                        token.current = crypto.randomUUID()
                      }}
                    >
                      <option>DEMO</option>
                      <option>ABAQUS</option>
                    </select>
                  </label>
                  {execution === 'DEMO' ? (
                    <>
                      <small className="mode-label">{demoNotice}</small>
                      <label>
                        Scenario
                        <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
                          <option value="success">Successful closing</option>
                          <option value="failure">Solver failure</option>
                          <option value="slow">Slow run for cancellation</option>
                          <option value="extraction_failure">Extraction fails once</option>
                        </select>
                      </label>
                    </>
                  ) : (
                    <>
                      <small>{cap.abaqus}</small>
                      <NumberInput
                        label="Solver CPUs"
                        value={cpus}
                        min={1}
                        step="1"
                        onChange={setCpus}
                      />
                    </>
                  )}
                  <button
                    className="primary wide"
                    disabled={
                      !ready ||
                      busy ||
                      !runName.trim() ||
                      (execution === 'ABAQUS' && cap.abaqus !== 'Configured')
                    }
                    onClick={() => execute(submit)}
                  >
                    <Play />
                    {execution === 'ABAQUS' ? 'Submit licensed analysis' : 'Submit demo run'}
                  </button>
                </>
              )}
            </fieldset>
            {stage === 7 && (
              <>
                <h2>Revision results</h2>
                {related.length === 0 ? (
                  <p>No runs have been submitted for this revision.</p>
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
                        {r.mode} · {r.status}
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
            ? 'Validation'
            : dirty
              ? 'Unsaved changes'
              : locked
                ? 'Historical revision'
                : 'Revision saved'}
        </strong>
        <span>
          {issue ||
            info ||
            build?.diagnostic ||
            (busy
              ? 'Working…'
              : selectionName
                ? 'Selected · ' + selectionName
                : 'Select geometry to inspect properties.')}
        </span>
        <span className="spacer" />
        <span>
          <CircleDot />
          {build && !dirty ? build.phase : 'Local project'}
        </span>
      </div>
    </main>
  )
}
