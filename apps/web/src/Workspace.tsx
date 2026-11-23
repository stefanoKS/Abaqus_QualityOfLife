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
  FlaskConical,
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
import { useCompatibility } from './Compat'
import type { Display, ViewMesh, Picked, SelectionMode } from './viewportModel'
import {
  artifact,
  err,
  go,
  replaceRoute,
  request,
  type FixtureInfo,
  type Job,
  type LibraryDetail,
  type LibrarySummary,
  type Project,
  type Revision,
} from './api'
import { useI18n, labelFrom } from './i18n'
import type { TranslationKey } from './i18n'
import { ACTIVE_POLL_MS, IDLE_POLL_MS, anyActive } from './shared/hooks/polling'
import { Facts } from './shared/components/Facts'
import { NumberInput } from './shared/components/NumberInput'
import { hasInvalidField, useAnyInvalidField } from './shared/components/draftGuard'
import { AssemblyTree } from './features/workspace/AssemblyTree'
import { AssemblyDiagnostics } from './features/workspace/AssemblyDiagnostics'
import { componentLabel } from './features/workspace/componentLabel'
import { WORKFLOW_STEPS, WorkflowNavigation } from './features/workspace/WorkflowNavigation'
import { orderedStates } from './features/workspace/workflowStates'
import { findingKey, findingVars, type Readiness } from './features/workspace/readiness'
import { motionDelta, stepPlan } from './features/workspace/stepSequence'
import {
  MESH_STAGES,
  STAGE,
  STAGE_ORDER,
  stageId,
  stageMode,
} from './features/workspace/stages'
import { freshCard, materialIssues } from './features/materials/MaterialEditor'
import { meshQuality, type MeshFile } from './features/mesh/meshQuality'
import { MeshReview } from './features/mesh/MeshReview'

type Mesh = ViewMesh & MeshFile
type Props = { initial: Revision; locked?: Job; notify: (msg: string) => void }

type PartitionPlan = {
  line: number[][]
  child_a: string
  child_b: string
  area_a: number
  area_b: number
  split_edges: string[]
  start: number[]
  end: number[]
}

const PARTITION_CODES = [
  'face_missing',
  'face_cavity',
  'face_not_seal',
  'bad_request',
  'endpoint_off_boundary',
  'endpoint_on_hole',
  'degenerate_cut',
  'cut_outside_face',
  'cut_crosses_hole',
  'cut_disjoint',
  'sliver_cut',
  'tangent_cut',
  'ambiguous_loop',
  'ambiguous_hole',
  'area_mismatch',
  'overlapping_children',
  'invalid_result',
  'unsupported_curve',
]

export default function Workspace({ initial, locked, notify }: Props) {
  const { t } = useI18n()
  const compatibility = useCompatibility()
  const [rev, setRev] = useState(initial),
    [p, setP] = useState(initial.setup)
  const [stage, setStage] = useState(() => {
    // An empty model opens at Import. The stage is remembered per revision and
    // per model so a save-induced remount cannot send the user back to step one.
    try {
      const saved =
        sessionStorage.getItem('stage:' + initial.id) ??
        sessionStorage.getItem('stage-project:' + initial.project)
      if (saved !== null) return Math.max(0, Math.min(STAGE_ORDER.length - 1, Number(saved) || 0))
    } catch {
      // Storage denial falls back to the explicit default.
    }
    return initial.setup.source.kind === 'empty' ? STAGE.import : STAGE.components
  }),
    [mode, setMode] = useState<SelectionMode>(() => {
      const id = stageId(stage)
      return id === 'materials' ? 'face' : id === 'mesh' ? 'edge' : id === 'mounting' ? 'node' : 'component'
    })
  const [pick, select] = useState<Picked | null>(() => {
    // A restored stage must restore a matching selection, or its editor would
    // render without an entity after a save-triggered remount.
    const face = p.faces[0]
    if (stage === STAGE.materials && face)
      return { kind: 'face', id: face.id, entity: face.id, component: face.component }
    const edge = p.edges[0]
    if (stage === STAGE.mesh && edge)
      return { kind: 'edge', id: edge.id, entity: edge.id, component: edge.component }
    return p.components[0]
      ? { kind: 'component', id: p.components[0].id, component: p.components[0].id }
      : null
  })
  const [hidden, hide] = useState<string[]>([]),
    [display, setDisplay] = useState<Display | null>(null)
  const [meshJobs, setMeshJobs] = useState<Job[]>([]),
    [deckJobs, setDeckJobs] = useState<Job[]>([]),
    [meshFile, setMeshFile] = useState<Mesh | null>(null),
    [showMesh, setShowMesh] = useState(() => MESH_STAGES.includes(stageId(stage)))
  // A just-queued deck must become the visible deck before submission, or the
  // server would correctly reject an older deck as superseded.
  const [pendingDeck, setPendingDeck] = useState<string | null>(null)
  const [reviewAction, setReviewAction] = useState<'prepare' | 'submit' | null>(null)
  // Fixed-node fixture review: a pending selection is shown but not stored until
  // Save, so a rectangle can be corrected before it becomes WSFIX.
  const [fixtureMode, setFixtureMode] = useState(() => stageId(stage) === 'mounting'),
    [pendingFixture, setPendingFixture] = useState<string[] | null>(null),
    [boxOperation, setBoxOperation] = useState<'replace' | 'add' | 'subtract'>('replace')
  const [working, setBusy] = useState(false),
    [info, message] = useState(''),
    [issue, setIssue] = useState(''),
    [generation, refresh] = useState(0)
  const [cap, setCap] = useState<Record<string, string>>({}),
    [related, setRelated] = useState<Job[]>([]),
    [readiness, setReadiness] = useState<Readiness | null>(null)
  const [runName, setRunName] = useState(() => t('review.defaultRunName')),
    [cpus, setCpus] = useState(1)
  // Narrow and zoomed layouts can collapse the workflow/properties panes so the
  // canvas and the primary actions remain reachable without clipping.
  const [panesOpen, setPanesOpen] = useState(true)
  // Straight two-point material partition. The primary interaction is on the
  // white viewport; the XY fields remain as optional precision entry.
  const [cutStart, setCutStart] = useState({ x: 0, y: 0 })
  const [cutEnd, setCutEnd] = useState({ x: 0, y: 0 })
  const [cutPhase, setCutPhase] = useState<'idle' | 'start' | 'end' | 'previewed'>('idle')
  const [cutPointA, setCutPointA] = useState<[number, number] | null>(null)
  const [cutPointB, setCutPointB] = useState<[number, number] | null>(null)
  const [cutHover, setCutHover] = useState<[number, number] | null>(null)
  const [cutPrecision, setCutPrecision] = useState(false)
  const [cutPlan, setCutPlan] = useState<PartitionPlan | null>(null)
  const [cutDisplay, setCutDisplay] = useState<Display | null>(null)
  const [cutError, setCutError] = useState('')
  // Prescribed-motion preview: a display-only animation of the rigid profile.
  const [preview, setPreview] = useState<{ role: 'door' | 'body' } | null>(null)
  const [previewProgress, setPreviewProgress] = useState(0)
  // Regeneration supersedes a reviewed fixture, so it is a deliberate choice.
  const [confirmRegenerate, setConfirmRegenerate] = useState(false)
  // A submitted setup replays its own archived mesh, never the newest one.
  const invalidField = useAnyInvalidField()
  const [archived, setArchived] = useState<{ mesh: Job | null; error: string }>({
    mesh: null,
    error: '',
  })
  const [expanded, expand] = useState<string[]>([])
  const [library, setLibrary] = useState<LibrarySummary[]>([])
  const [placement, setPlacement] = useState<{ initial_vertical_mesh_clearance_mm: number } | null>(
    null,
  )
  const file = useRef<HTMLInputElement>(null),
    token = useRef(crypto.randomUUID()),
    rightPane = useRef<HTMLElement>(null)
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
          if (next.project !== rev.project) {
            throw new Error(t('import.otherModel'))
          }
          clear()
          try {
            sessionStorage.setItem('stage:' + next.id, String(STAGE.components))
            sessionStorage.setItem('stage-project:' + next.project, String(STAGE.components))
          } catch {
            // The remount falls back to Components for a drawing-backed model.
          }
          replaceRoute('workspace/' + next.id)
          setRev(next)
          setP(next.setup)
      
          select(null)
          hide([])
          setMeshFile(null)
          setPendingFixture(null)
          message(t('import.done'))
          setStage(STAGE.components)
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
    try {
      sessionStorage.setItem('stage:' + rev.id, String(stage))
      sessionStorage.setItem('stage-project:' + rev.project, String(stage))
    } catch {
      // Remembering the step is a convenience; the workflow stays usable without it.
    }
  }, [stage, rev.id, rev.project])
  useEffect(() => {
    // A submitted setup is replayed through the mesh job its deck recorded, and
    // only when every recorded digest agrees. The newest compatible mesh is never
    // substituted for the archived one.
    if (!locked) {
      setArchived({ mesh: null, error: '' })
      return
    }
    const ac = new AbortController()
    async function resolve() {
      try {
        const deck = await request<Job>('/api/jobs/' + locked!.build, 'GET', undefined, ac.signal)
        if (!deck.mesh) throw new Error(t('mesh.archiveMissing'))
        const mesh = await request<Job>('/api/jobs/' + deck.mesh, 'GET', undefined, ac.signal)
        if (
          !mesh.mesh_digest ||
          mesh.mesh_digest !== deck.mesh_digest ||
          (locked!.mesh_digest && locked!.mesh_digest !== mesh.mesh_digest)
        ) {
          throw new Error(t('mesh.archiveMismatch'))
        }
        setArchived({ mesh, error: '' })
      } catch (e) {
        if (!ac.signal.aborted) setArchived({ mesh: null, error: err(e) })
      }
    }
    void resolve()
    return () => ac.abort()
  }, [locked, t])
  // Last revision whose geometry was successfully rendered. A draft-only
  // validation error must never clear a drawing the engineer already had.
  const displayedRevision = useRef<string | null>(null)
  useEffect(() => {
    const ac = new AbortController()
    request<Display>('/api/display', 'POST', p, ac.signal)
      .then((next) => {
        displayedRevision.current = rev.id
        setDisplay(next)
      })
      .catch((e) => {
        if (ac.signal.aborted) return
        // The draft is the last valid geometry until Save, so keep it visible.
        // Only a failure before this revision rendered anything is a real
        // empty scene worth reporting.
        if (displayedRevision.current === rev.id) return
        setDisplay(null)
        problem(e)
      })
    return () => ac.abort()
  }, [p, rev.id, problem])
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
  // The active mesh is the newest completed mesh with the saved revision's mesh
  // inputs. An explicit remesh (same bytes or not) therefore becomes active and
  // starts without a reviewed fixture.
  const compatibleMesh = completedMeshes.find((j) => j.mesh_compat === rev.mesh_compat) ?? null
  const fixture = compatibleMesh?.fixture ?? null
  const fixtureReviewed = !!fixture && fixture.count > 0
  // A submitted setup replays the fixture archived with its deck, never the live
  // selection for the current mesh.
  const archivedFixture = locked?.fixture_labels ?? null
  // The displayed mesh is the archived one only after its identity is verified.
  const verifiedMesh = locked ? archived.mesh : compatibleMesh
  const shownFixture = locked
    ? archived.mesh
      ? (archivedFixture ?? [])
      : []
    : (pendingFixture ?? fixture?.labels ?? [])
  // A changed or cleared selection must block preparation and submission until
  // it is saved or discarded.
  const fixturePending = pendingFixture !== null
  // Zero travel is a valid hold; only a non-positive duration (or a blank
  // numeric draft, handled separately) blocks the motion step.
  const motionValid = p.motion.travel <= 0 && p.motion.duration > 0
  const deck = pendingDeck
    ? (deckJobs.find((j) => j.id === pendingDeck) ?? null)
    : (deckJobs.find(
        (j) => j.revision === rev.id && j.mesh === compatibleMesh?.id && j.status === 'Completed',
      ) ?? null)
  // The server treats the newest deck for the revision as the only submittable one.
  const newestDeck = deckJobs.find((j) => j.revision === rev.id) ?? null
  // A deck prepared before the fixture changed is stale even for the same mesh.
  const deckReady =
    !!deck &&
    deck.status === 'Completed' &&
    deck.id === newestDeck?.id &&
    !!fixture &&
    deck.fixture_hash === fixture.hash
  useEffect(() => {
    if (!pendingDeck) return
    const pending = deckJobs.find((job) => job.id === pendingDeck)
    if (!pending) return
    if (pending.status === 'Completed') setPendingDeck(null)
    else if (pending.status === 'Failed' || pending.status === 'Cancelled') {
      setPendingDeck(null)
      message(pending.diagnostic || t('mesh.deckFailed'))
    }
  }, [pendingDeck, deckJobs, t])
  useEffect(() => {
    setPendingDeck(null)
  }, [rev.id])
  useEffect(() => {
    // Only a change of the displayed mesh resets the review, never a poll or a save.
    setPendingFixture(null)
    setFixtureMode(false)
    if (!verifiedMesh) {
      setMeshFile(null)
      return
    }
    const ac = new AbortController()
    request<Mesh>(artifact(verifiedMesh.id, 'mesh.json'), 'GET', undefined, ac.signal)
      .then(setMeshFile)
      .catch((e) => {
        if (!ac.signal.aborted) {
          setMeshFile(null)
          problem(e)
        }
      })
    return () => ac.abort()
  }, [verifiedMesh?.id, problem])
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
  // The API owns the readiness calculation so the header, Review and a direct
  // API request cannot disagree about the next engineering action.
  useEffect(() => {
    const ac = new AbortController()
    request<Readiness>('/api/revisions/' + rev.id + '/readiness', 'GET', undefined, ac.signal)
      .then(setReadiness)
      .catch(() => {
        if (!ac.signal.aborted) setReadiness(null)
      })
    return () => ac.abort()
  }, [rev.id, generation])
  useEffect(() => {
    const ac = new AbortController()
    request<LibrarySummary[]>('/api/materials', 'GET', undefined, ac.signal)
      .then(setLibrary)
      .catch(() => {
        if (!ac.signal.aborted) setLibrary([])
      })
    return () => ac.abort()
  }, [generation])
  useEffect(() => {
    if (!dirty) return
    const guard = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', guard)
    return () => window.removeEventListener('beforeunload', guard)
  }, [dirty])
  const archivedModel = rev.archived || rev.group_archived
  function edit(fn: (next: Project) => void) {
    if (locked || archivedModel) return
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
  // A pending cut belongs to one face; changing selection invalidates it.
  useEffect(() => {
    setCutPlan(null)
    setCutError('')
  }, [face?.id])
  const component = p.components.find(
    (c) => c.id === (pick?.component ?? face?.component ?? edge?.component ?? pick?.id),
  )
  const mat = p.materials.find((m) => m.id === face?.material)
  const assignedLibrary = mat?.library_id
    ? library.find((entry) => entry.id === mat.library_id)
    : undefined
  const libraryNewer = Boolean(
    assignedLibrary &&
      mat?.library_version &&
      assignedLibrary.current_version > mat.library_version,
  )
  const mount = p.selections.find((s) => s.id === p.mounting.selection)
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
      orderedStates({
        project: p,
        mesh: meshJob,
        compatibleMesh,
        fixture,
        deck: deckReady ? deck : null,
        runs: related,
        contactChanged: JSON.stringify(p.contact) !== JSON.stringify(rev.setup.contact),
      }),
    [p, rev.setup.contact, meshJob, compatibleMesh, fixture, deck, deckReady, related],
  )
  const plan = useMemo(() => stepPlan(p), [p])
  const twoStep = plan.mode === 'body_then_door'
  // A measured motion rejection (penetration, wrong direction, missing X
  // overlap) is shown next to the motion fields, not only as a toast.
  const motionFinding =
    readiness?.findings.find(
      (finding) => finding.stage === 'motion' && finding.severity === 'blocker',
    ) ?? null
  const participantNames = useMemo(
    () =>
      p.components
        .filter(
          (c) =>
            c.role === 'seal' ||
            c.role === 'moving_panel' ||
            (p.analysis.mode === 'body_then_door' && c.role === 'vehicle_body'),
        )
        .map(componentLabel),
    [p.components, p.analysis.mode],
  )
  const panelEdges = useMemo(() => {
    const panel = p.components.find((component) => component.role === 'moving_panel')
    return panel ? p.edges.filter((edge) => edge.component === panel.id) : []
  }, [p.components, p.edges])
  const bodyNames = useMemo(
    () => p.components.filter((c) => c.role === 'vehicle_body').map(componentLabel),
    [p.components],
  )
  // The viewport draws each rigid profile on its own assembled instance at its
  // own initial offset; the body is never shifted by the door offset.
  const rigidInstances = useMemo(
    () =>
      p.components
        .filter(
          (c) =>
            c.role === 'moving_panel' ||
            (p.analysis.mode === 'body_then_door' && c.role === 'vehicle_body'),
        )
        .map((c) =>
          c.role === 'moving_panel'
            ? { component: c.id, instance: 'PANEL-1', offset: p.motion.offset }
            : { component: c.id, instance: 'BODY-1', offset: p.motion.body.offset },
        ),
    [p.components, p.analysis.mode, p.motion.offset, p.motion.body.offset],
  )
  // Eligible cut boundary: the selected face's outer loop as tessellated model
  // points. Arc/spline samples are within the display chord tolerance, and the
  // server snaps the canonical point with its own 0.05 mm tolerance.
  const cutFace = face && !face.cavity ? face : null
  const cutBoundary = useMemo(() => {
    if (!cutFace) return []
    const edges = new Map(
      (display?.primitives ?? [])
        .filter((primitive) => primitive.kind === 'edge')
        .map((primitive) => [primitive.entity, primitive]),
    )
    const points: number[][] = []
    for (const token of cutFace.loops[0] ?? []) {
      const primitive = edges.get(token.replace(/^-/, ''))
      if (!primitive) continue
      const ordered = token.startsWith('-')
        ? [...primitive.points].reverse()
        : primitive.points
      for (const point of ordered) {
        const last = points[points.length - 1]
        if (last && Math.hypot(last[0] - point[0], last[1] - point[1]) < 1e-9) continue
        points.push([point[0], point[1]])
      }
    }
    return points
  }, [cutFace, display])
  const previewComponent = preview
    ? p.components.find(
        (component) =>
          component.role === (preview.role === 'door' ? 'moving_panel' : 'vehicle_body'),
      )
    : undefined
  const previewTranslation = useMemo(() => {
    if (!preview || !previewComponent) return undefined
    const motion = preview.role === 'door' ? p.motion : p.motion.body
    const [dx, dy] = motionDelta(motion.stroke, motion.angle)
    return {
      [previewComponent.id]: [
        dx * previewProgress,
        dy * previewProgress,
      ] as [number, number],
    }
  }, [preview, previewComponent, previewProgress, p.motion, p.motion.body])
  function stopPreview() {
    setPreview(null)
    setPreviewProgress(0)
  }
  function previewMotion(role: 'door' | 'body') {
    if (preview?.role === role) {
      stopPreview()
      return
    }
    const motion = role === 'door' ? p.motion : p.motion.body
    if (!(motion.stroke > 0)) {
      message(t('motion.holdPreview'))
      return
    }
    setPreview({ role })
    setPreviewProgress(0)
  }
  // A preview is display-only and must cancel on any route, stage or draft
  // change; it never mutates the saved setup or queues work.
  useEffect(() => {
    stopPreview()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stage, rev.id])
  useEffect(() => {
    if (!preview) return
    stopPreview()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.motion.stroke, p.motion.angle, p.motion.body.stroke, p.motion.body.angle])
  useEffect(() => {
    if (!preview) return
    const reduced =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      setPreviewProgress(1)
      const timer = setTimeout(() => {
        setPreviewProgress(0)
        setPreview(null)
      }, 500)
      return () => clearTimeout(timer)
    }
    const duration = Math.max(320, Math.min(1200, p.motion.duration * 1000))
    const hold = 220
    const back = 360
    const started = performance.now()
    let frame = 0
    const tick = (now: number) => {
      const elapsed = now - started
      if (elapsed < duration) setPreviewProgress(elapsed / duration)
      else if (elapsed < duration + hold) setPreviewProgress(1)
      else if (elapsed < duration + hold + back)
        setPreviewProgress(1 - (elapsed - duration - hold) / back)
      else {
        setPreviewProgress(0)
        setPreview(null)
        return
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
    // The animation restarts only for a new preview request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview])
  function target(next: SelectionMode) {
    setMode(next)
    if (next === 'component') {
      const c = component ?? p.components[0]
      select(c ? { kind: next, id: c.id, component: c.id } : null)
    } else if (next === 'face' && p.faces.length) {
      const f = face ?? p.faces[0]
      select({ kind: next, id: f.id, entity: f.id, component: f.component })
    } else if (next === 'edge' && p.edges.length) {
      const e =
        edge ??
        p.edges.find((item) => mount?.entities.includes(item.id)) ??
        p.edges[0]
      select({ kind: next, id: e.id, entity: e.id, component: e.component })
    } else select(null)
  }
  function assertNumericDrafts() {
    // Synchronous source of truth, not a possibly stale render value.
    if (hasInvalidField()) throw new Error(t('validation.invalidDraft'))
  }
  function changeStage(i: number) {
    // An invalid numeric draft is not silently committed or discarded by leaving
    // the step: keep it visible and make the engineer correct it or press Escape.
    if (invalidField || hasInvalidField()) {
      notify(t('validation.invalidDraft'))
      return
    }
    const id = stageId(i)
    setStage(i)
    setShowMesh(MESH_STAGES.includes(id))
    setFixtureMode(id === 'mounting')
    target(stageMode(id))
    // The action group of a newly selected stage must be reachable at the top of
    // its own scrolling pane; a previous stage's scroll position is not kept.
    requestAnimationFrame(() => rightPane.current?.scrollTo({ top: 0 }))
  }
  async function save() {
    assertNumericDrafts()
    if (!dirty) return rev
    const saved = await request<Revision>('/api/projects/' + rev.project, 'PUT', {
      base: rev.id,
      setup: p,
    })
    replaceRoute('workspace/' + saved.id)
    setRev(saved)
    setP(saved.setup)
    // The mesh is not cleared: its identity decides whether it is still reusable.
    message(t('status.revisionSaved', { number: saved.number }))
    return saved
  }
  function cutPoints(): number[] {
    return [cutStart.x, cutStart.y, cutEnd.x, cutEnd.y]
  }
  function cutDraftValid() {
    if (invalidField || hasInvalidField()) {
      setCutError(t('validation.invalidDraft'))
      return false
    }
    return true
  }
  function partitionMessage(message: string) {
    const code = message.split(':')[0].trim()
    return PARTITION_CODES.includes(code)
      ? t(('partition.error.' + code) as TranslationKey)
      : message
  }
  function setCutPoints(a: [number, number] | null, b: [number, number] | null) {
    if (a) setCutStart({ x: Number(a[0].toFixed(6)), y: Number(a[1].toFixed(6)) })
    if (b) setCutEnd({ x: Number(b[0].toFixed(6)), y: Number(b[1].toFixed(6)) })
  }
  function startCut() {
    setCutPhase('start')
    setCutPointA(null)
    setCutPointB(null)
    setCutHover(null)
    setCutPlan(null)
    setCutDisplay(null)
    setCutError('')
  }
  function resetCut() {
    setCutPhase('idle')
    setCutPointA(null)
    setCutPointB(null)
    setCutHover(null)
    setCutPlan(null)
    setCutDisplay(null)
    setCutError('')
  }
  function backCut() {
    if (cutPhase === 'previewed') {
      setCutPlan(null)
      setCutDisplay(null)
      setCutPointB(null)
      setCutError('')
      setCutPhase('end')
    } else if (cutPhase === 'end') {
      setCutPointA(null)
      setCutPointB(null)
      setCutPlan(null)
      setCutPhase('start')
    }
  }
  async function previewCutAt(a: [number, number], b: [number, number]) {
    if (!face) return
    try {
      const result = await request<{ plan: PartitionPlan; display: Display }>(
        '/api/partition/preview',
        'POST',
        { setup: p, cut: { face: face.id, start: [a[0], a[1]], end: [b[0], b[1]] } },
      )
      setCutError('')
      setCutPlan(result.plan)
      setCutDisplay(result.display)
      setCutPhase('previewed')
    } catch (e) {
      setCutPlan(null)
      setCutDisplay(null)
      setCutError(partitionMessage(err(e)))
      setCutPhase('end')
    }
  }
  function placeCutPoint(point: [number, number]) {
    if (cutPhase === 'start') {
      setCutPointA(point)
      setCutPoints(point, null)
      setCutPointB(null)
      setCutPlan(null)
      setCutError('')
      setCutPhase('end')
      return
    }
    if (cutPhase === 'end' && cutPointA) {
      setCutPointB(point)
      setCutPoints(cutPointA, point)
      void previewCutAt(cutPointA, point)
    }
  }
  async function previewTypedCut() {
    if (!face) return
    if (!cutDraftValid()) {
      setCutPlan(null)
      return
    }
    const values = cutPoints()
    const a: [number, number] = [values[0], values[1]]
    const b: [number, number] = [values[2], values[3]]
    setCutPointA(a)
    setCutPointB(b)
    await previewCutAt(a, b)
  }
  async function applyCut() {
    if (!face || !cutPlan) return
    const plan = cutPlan
    if (cutPhase !== 'previewed') return
    try {
      const saved = await request<Revision>(
        '/api/projects/' + rev.project + '/partition',
        'POST',
        {
          base: rev.id,
          cut: {
            face: face.id,
            start: [plan.start[0], plan.start[1]],
            end: [plan.end[0], plan.end[1]],
          },
        },
      )
      replaceRoute('workspace/' + saved.id)
      setRev(saved)
      setP(saved.setup)
      resetCut()
      select({
        kind: 'face',
        id: plan.child_a,
        entity: plan.child_a,
        component: face.component,
      })
      message(t('partition.applied', { number: saved.number }))
      refresh((g) => g + 1)
    } catch (e) {
      setCutError(partitionMessage(err(e)))
    }
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
    assertNumericDrafts()
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
    assertNumericDrafts()
    if (!compatibleMesh || !fixtureReviewed || pendingDeck) return
    const job = await request<Job>('/api/decks', 'POST', {
      revision: rev.id,
      token: crypto.randomUUID(),
      mesh: compatibleMesh.id,
      // The exact fixture the engineer reviewed. If another tab saved a newer
      // selection, the server rejects this deck instead of snapshotting it.
      fixture_hash: fixture?.hash ?? '',
    })
    setPendingDeck(job.id)
    refresh((g) => g + 1)
    message(t('mesh.preparingDeck'))
  }
  async function saveFixture(labels: string[]) {
    assertNumericDrafts()
    if (!compatibleMesh) return
    await request<Job>('/api/meshes/' + compatibleMesh.id + '/fixture', 'PUT', {
      labels,
      // Optimistic concurrency: reject a save from a tab that loaded an older
      // fixture instead of overwriting the other tab's reviewed set.
      expected_hash: fixture?.hash ?? '',
    })
    setPendingFixture(null)
    refresh((g) => g + 1)
    message(t('mesh.fixtureSaved', { count: labels.length }))
  }
  async function resolveLegacyFixture() {
    if (!compatibleMesh) return
    const resolved = await request<FixtureInfo>(
      '/api/meshes/' + compatibleMesh.id + '/fixture/edges?revision=' + rev.id,
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
    assertNumericDrafts()
    if (!deckReady || !deck) return
    const r = await request<Job>('/api/runs', 'POST', {
      name: runName,
      revision: rev.id,
      deck: deck.id,
      token: token.current,
      cpus,
      mode: 'ABAQUS',
    })
    token.current = crypto.randomUUID()
    go('diagnostics/' + r.id)
  }
  async function importFile(f: File) {
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
  async function assignLibrary(libraryId: string) {
    if (!face) return
    const detail = await request<LibraryDetail>('/api/materials/' + libraryId)
    execute(async () => {
      edit((n) => {
        let card = n.materials.find(
          (item) =>
            item.library_id === detail.id &&
            item.library_version === detail.current_version,
        )
        if (!card) {
          card = {
            id: freshCard(n.materials, detail.name).id,
            name: detail.name,
            version: 1,
            model: detail.card.model,
            color: detail.card.color,
            density: detail.card.density,
            young: detail.card.young ?? null,
            poisson: detail.card.poisson ?? null,
            c10: detail.card.c10 ?? null,
            d1: detail.card.d1 ?? null,
            test_data: (detail.card.test_data ?? []).map(
              (row) => [row[0], row[1], row[2]] as [number, number, number],
            ),
            library_id: detail.id,
            library_version: detail.current_version,
          }
          n.materials.push(card)
        }
        n.faces.find((item) => item.id === face.id)!.material = card.id
      })
    })
  }

  async function adoptLibrary(cardId: string, libraryId: string) {
    const detail = await request<LibraryDetail>('/api/materials/' + libraryId)
    execute(async () => {
      edit((n) => {
        const card = n.materials.find((item) => item.id === cardId)
        if (!card) return
        card.model = detail.card.model
        card.color = detail.card.color
        card.density = detail.card.density
        card.young = detail.card.young ?? null
        card.poisson = detail.card.poisson ?? null
        card.c10 = detail.card.c10 ?? null
        card.d1 = detail.card.d1 ?? null
        card.test_data = (detail.card.test_data ?? []).map(
          (row) => [row[0], row[1], row[2]] as [number, number, number],
        )
        card.library_id = detail.id
        card.library_version = detail.current_version
      })
    })
  }
  const selectionName = pick?.instance
    ? pick.id
    : pick?.kind === 'component'
      ? component
        ? componentLabel(component)
        : undefined
      : (edge?.name ?? face?.name ?? pick?.id)
  const dimension = p.dimension === '3D'
  const blockedReason = invalidField
    ? t('validation.invalidDraft')
    : invalidMaterials.length
      ? invalidMaterials.map((m) => m.name).join(' · ')
      : ''
  const preparationBlocker = readiness?.findings.find(
    (finding) => finding.severity === 'blocker' && !finding.code.startsWith('deck.'),
  )
  const prepareReason = !compatibility.ok ? t('compat.writesDisabled')
    : archivedModel ? t('workspace.archivedReadOnly')
    : dimension ? t('workspace.extrusionPreview')
      : dirty ? t('status.unsaved')
        : blockedReason || (fixturePending ? t('hint.fixturePending')
          : !compatibleMesh ? t('hint.meshRequired')
            : !fixtureReviewed ? t('hint.fixtureRequired')
              : !motionValid ? t('hint.motion')
                : !readiness || readiness.revision !== rev.id ? t('actions.checking')
                  : preparationBlocker ? t(findingKey(preparationBlocker.code), findingVars(preparationBlocker, t))
                    : '')
  const submitReason = prepareReason || (!deckReady ? t('hint.deckRequired')
    : !runName.trim() ? t('actions.runNameRequired')
      : !Number.isInteger(cpus) || cpus < 1 || cpus > 32 ? t('actions.cpuRequired')
      : cap.abaqus !== 'Configured' ? cap.abaqus || t('actions.checking') : '')
  const activeRun = related.find((run) => anyActive([run]))
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
            {p.source.kind === 'synthetic' ? t('workspace.synthetic') : p.source.kind === 'empty' ? t('workspace.noDrawing') : p.source.filename}
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
                disabled={!dirty || busy || !!blockedReason || archivedModel}
                title={archivedModel ? t('workspace.archivedReadOnly') : blockedReason || undefined}
                onClick={() => execute(save)}
              >
                <Save />
                {t('workspace.saveRevision')}
              </button>
              <button className="primary" onClick={() => changeStage(STAGE.review)}>
                <Play />
                {t('workspace.reviewRun')}
              </button>
            </>
          )}
        </div>
      </div>
      {archivedModel && !locked && (
        <p className="notice blocked-banner" data-testid="archived-banner">
          {t('workspace.archivedReadOnly')}
        </p>
      )}
      {blockedReason && (
        <p className="error-text blocked-banner" role="alert">
          {t('materials.err.finite')} — {blockedReason}
        </p>
      )}
      {!locked && !dirty && readiness?.first_blocker && (
        <div className="readiness-banner" aria-live="polite" data-testid="next-action">
          <span>{t(findingKey(readiness.first_blocker.code), findingVars(readiness.first_blocker, t))}</span>
          <button
            type="button"
            onClick={() =>
              changeStage(
                (STAGE as Record<string, number>)[readiness.first_blocker!.stage] ?? stage,
              )
            }
          >
            {t('workspace.resolveBlocker')}
          </button>
        </div>
      )}
      <button
        type="button"
        className="pane-toggle"
        aria-expanded={panesOpen}
        aria-controls="workbench-panes"
        onClick={() => setPanesOpen((open) => !open)}
      >
        <SlidersHorizontal />
        {t('workspace.panes')}
      </button>
      <div
        id="workbench-panes"
        className={
          'workgrid' + (panesOpen ? '' : ' panes-closed')
        }
      >
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
              setStage(STAGE[kind === 'face' ? 'materials' : kind === 'edge' ? 'mesh' : 'components'])
              select({ kind, id, entity: id, component: componentId })
            }}
            onRename={(id, alias) =>
              edit((next) => {
                const target = next.components.find((item) => item.id === id)
                if (target) target.alias = alias
              })
            }
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
              display={cutPhase === 'previewed' && cutDisplay ? cutDisplay : display}
              mode={mode}
              selection={pick}
              onSelect={(hit) => {
                select(hit)
                message('')
                if (hit?.kind === 'face' && stage === STAGE.components) setStage(STAGE.materials)
                if (hit?.kind === 'edge' && stage === STAGE.components) setStage(STAGE.mesh)
              }}
              colors={colors}
              hidden={hidden}
              mesh={showMesh ? meshFile : null}
              panelOffset={p.motion.offset}
              rigidInstances={rigidInstances}
              boxSelect={fixtureMode && !!compatibleMesh}
              boxOperation={boxOperation}
              selectedNodes={shownFixture}
              nodeInstances={['WS-1']}
              onBoxSelect={boxSelect}
              previewTranslation={previewTranslation}
              cut={
                stage === STAGE.materials && cutPhase !== 'idle'
                  ? {
                      active: true,
                      boundary: cutBoundary,
                      start: cutPointA,
                      end: cutPointB,
                      phase: cutPhase,
                      invalid: !!cutError,
                    }
                  : null
              }
              onCutPoint={placeCutPoint}
              onCutHover={setCutHover}
              onCutCancel={resetCut}
              guide={null}
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
        <aside className="right card" ref={rightPane}>
          <div className="panel-title">
            <SlidersHorizontal />
            {t('workspace.properties')}
          </div>
          <div className="property-body">
        {stage === STAGE.review && !locked && (
          <div className="review-actions in-properties" data-testid="review-actions">
            <section className="review-action card">
              <h2>{t('mesh.prepareDeck')}</h2>
              <p>{pendingDeck || reviewAction === 'prepare' ? t('mesh.preparingDeck') : prepareReason || (deckReady ? t('mesh.inputReady') : t('actions.readyPrepare'))}</p>
              <small>{t('review.prepareNeverMesh')}</small>
              <button className="review-prepare" disabled={busy || !!prepareReason || !!pendingDeck}
                title={prepareReason || undefined} onClick={() => execute(async () => {
                  setReviewAction('prepare')
                  try { await prepareDeck() } finally { setReviewAction(null) }
                })}>
                <FileText /> {t('mesh.prepareDeck')}
              </button>
              {deck && (
                <div className="build-info" data-testid="deck-status">
                  <strong>{deckReady ? t('mesh.inputReady') : t('mesh.deckStale')}</strong>
                  {deckReady ? (
                    <a href={artifact(deck.id, 'analysis.inp')} target="_blank" rel="noreferrer">
                      <FileText /> {t('mesh.inspectDeck')}
                    </a>
                  ) : <small>{t('mesh.deckStaleHint')}</small>}
                </div>
              )}
            </section>
            <section className="review-action card">
              <h2>{t('review.submitLicensed')}</h2>
              <p>{reviewAction === 'submit' ? t('actions.submitting') : submitReason || t('actions.readySubmit')}</p>
              {activeRun && <small>{t('actions.activeRun', { state: labelFrom(t, 'state', activeRun.status) })}</small>}
              <label>{t('review.runName')}
                <input maxLength={100} value={runName} onChange={(e) => setRunName(e.target.value)} />
              </label>
              <NumberInput label={t('review.cpus')} value={cpus} min={1} max={32} step="1"
                rangeHint="1 – 32" onChange={setCpus} />
              <small>{cap.abaqus}</small>
              <button className="review-submit" disabled={busy || !!submitReason || !!pendingDeck}
                title={submitReason || undefined} onClick={() => execute(async () => {
                  setReviewAction('submit')
                  try { await submit() } finally { setReviewAction(null) }
                })}>
                <Play /> {t('review.submitLicensed')}
              </button>
            </section>
                    </div>
        )}
            <div className="eyebrow">{steps[stage]}</div>
            <fieldset disabled={!!locked || busy}>
              {stage === STAGE.import && (
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
                      [
                        t('import.source'),
                        p.source.kind === 'empty' ? t('import.none') : p.source.filename,
                      ],
                      [t('import.sectionPlane'), 'XY · Z = 0'],
                      [t('import.units'), 'N–mm–s–tonne'],
                    ]}
                  />
                  {p.source.unit_basis && (
                    <p className="notice" data-testid="import-unit-basis">
                      {t('import.drawingUnitBasis')}
                      {': '}
                      {t(
                        ('import.unitBasis.' + p.source.unit_basis) as TranslationKey,
                        {
                          declaration: p.source.unit_declaration,
                          factor: String(p.source.unit_factor),
                        },
                      )}
                    </p>
                  )}
                  {p.source.kind === 'empty' && (
                    <p className="notice" data-testid="no-drawing">
                      {t('import.noDrawing')}
                    </p>
                  )}
                  {rev.source_id && (
                    <a className="asset" href={'/api/revisions/' + rev.id + '/drawing'} download>
                      <ArrowDownToLine />
                      {t('import.download')}
                    </a>
                  )}
                  <p>{t('import.help')}</p>
                  <p className="quality-note subtle" data-testid="import-unit-policy">
                    {t('import.unitPolicy')}
                  </p>
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
                  <button onClick={() => file.current?.click()}>
                    <FileInput />
                    {t('import.action')}
                  </button>
                  <small>
                    {cap.dwg === 'Configured' ? t('import.odaConfigured') : cap.dwg}
                  </small>
                </>
              )}
              {stage === STAGE.components && (
                <>
                  <h2>{component ? componentLabel(component) : t('components.select')}</h2>
                  {component && (
                    <span className="role-tag" data-testid="component-role">
                      {t(('role.' + component.role) as TranslationKey)}
                    </span>
                  )}
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
                            setStage(STAGE.materials)
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
              {stage === STAGE.materials && (
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
                      {!face.cavity && !locked && !dimension && (
                        <section className="partition-block" data-testid="partition-editor">
                          <h3>{t('partition.title')}</h3>
                          <p>{t('partition.help')}</p>
                          {cutPhase === 'idle' ? (
                            <button
                              type="button"
                              className="primary wide"
                              data-testid="cut-region"
                              disabled={busy}
                              onClick={startCut}
                            >
                              <ScanLine />
                              {t('partition.cutRegion')}
                            </button>
                          ) : (
                            <>
                              <p
                                className={cutError ? 'error-text' : 'cut-status'}
                                role={cutError ? 'alert' : 'status'}
                                data-testid="cut-status"
                                data-phase={cutPhase}
                              >
                                {cutError ||
                                  (cutPhase === 'start'
                                    ? t('partition.pickStart')
                                    : cutPhase === 'end'
                                      ? t('partition.pickEnd')
                                      : t('partition.previewReady'))}
                              </p>
                              {cutPhase !== 'previewed' && cutHover && (
                                <p className="motion-vector" data-testid="cut-hover">
                                  {t('partition.candidate', {
                                    x: cutHover[0].toFixed(3),
                                    y: cutHover[1].toFixed(3),
                                  })}
                                </p>
                              )}
                              <div className="actions">
                                <button type="button" onClick={backCut} disabled={cutPhase === 'start'}>
                                  {t('partition.back')}
                                </button>
                                <button
                                  type="button"
                                  className="primary"
                                  onClick={() => execute(applyCut)}
                                  disabled={busy || cutPhase !== 'previewed' || !cutPlan}
                                >
                                  {t('partition.apply')}
                                </button>
                                <button type="button" onClick={resetCut}>
                                  {t('partition.cancel')}
                                </button>
                              </div>
                            </>
                          )}
                          <button
                            type="button"
                            className="link-button"
                            aria-expanded={cutPrecision}
                            onClick={() => setCutPrecision((open) => !open)}
                          >
                            {t('partition.precisionEntry')}
                          </button>
                          {cutPrecision && (
                            <div className="cut-points">
                              <NumberInput
                                label={t('partition.startX')}
                                unit="mm"
                                value={cutStart.x}
                                onChange={(x) => setCutStart((v) => ({ ...v, x }))}
                              />
                              <NumberInput
                                label={t('partition.startY')}
                                unit="mm"
                                value={cutStart.y}
                                onChange={(y) => setCutStart((v) => ({ ...v, y }))}
                              />
                              <NumberInput
                                label={t('partition.endX')}
                                unit="mm"
                                value={cutEnd.x}
                                onChange={(x) => setCutEnd((v) => ({ ...v, x }))}
                              />
                              <NumberInput
                                label={t('partition.endY')}
                                unit="mm"
                                value={cutEnd.y}
                                onChange={(y) => setCutEnd((v) => ({ ...v, y }))}
                              />
                              <button
                                type="button"
                                onClick={() => execute(previewTypedCut)}
                                disabled={busy}
                              >
                                {t('partition.preview')}
                              </button>
                            </div>
                          )}
                          {cutPlan && (
                            <div className="build-info" data-testid="partition-plan">
                              <strong>{t('partition.previewReady')}</strong>
                              <small>
                                {t('partition.areas', {
                                  a: cutPlan.area_a.toFixed(3),
                                  b: cutPlan.area_b.toFixed(3),
                                })}
                              </small>
                              <small>
                                {t('partition.intersections', {
                                  count: cutPlan.split_edges.length,
                                })}
                              </small>
                            </div>
                          )}
                        </section>
                      )}
                      {mat && (
                        <>
                          <h3>{t('materials.assigned')}</h3>
                          <Facts
                            rows={[
                              [t('materials.name'), mat.name],
                              [
                                t('materials.model'),
                                mat.model === 'hyperfoam_test'
                                  ? t('materials.modelHyperfoam')
                                  : t('materials.modelLinear'),
                              ],
                              [t('materials.cardVersion'), 'v' + mat.version],
                              [t('materials.density'), mat.density.toExponential(2)],
                              ...(mat.model === 'hyperfoam_test'
                                ? [
                                    [
                                      t('materials.samples'),
                                      String(mat.test_data.length),
                                    ] as [string, string],
                                  ]
                                : [
                                    [t('materials.young'), String(mat.young ?? '—')] as [
                                      string,
                                      string,
                                    ],
                                  ]),
                              [
                                t('materials.libraryVersion'),
                                mat.library_id
                                  ? t('materials.pinnedVersion', {
                                      version: mat.library_version ?? '—',
                                    })
                                  : t('materials.localCard'),
                              ],
                            ]}
                          />
                          {libraryNewer && assignedLibrary && (
                            <div className="notice" data-testid="library-newer">
                              <p>
                                {t('materials.newLibraryVersion', {
                                  name: assignedLibrary.name,
                                  version: assignedLibrary.current_version,
                                })}
                              </p>
                              <button
                                type="button"
                                disabled={!!locked || busy}
                                onClick={() =>
                                  void adoptLibrary(mat.id, mat.library_id!).catch((error) =>
                                    notify(err(error)),
                                  )
                                }
                              >
                                {t('materials.adoptVersion', {
                                  version: assignedLibrary.current_version,
                                })}
                              </button>
                            </div>
                          )}
                        </>
                      )}
                      <label>
                        {t('materials.assignFromLibrary')}
                        <select
                          value=""
                          disabled={!!locked || busy || !mat || !library.length}
                          onChange={(e) => {
                            if (e.target.value) {
                              void assignLibrary(e.target.value).catch((error) =>
                                notify(err(error)),
                              )
                            }
                          }}
                        >
                          <option value="">{t('materials.chooseLibraryMaterial')}</option>
                          {library
                            .filter((entry) => !entry.archived)
                            .map((entry) => (
                              <option key={entry.id} value={entry.id}>
                                {entry.name} · v{entry.current_version}
                              </option>
                            ))}
                        </select>
                      </label>
                      <button
                        type="button"
                        className="wide"
                        onClick={() => go('materials')}
                      >
                        <FlaskConical />
                        {t('materials.openLibrary')}
                      </button>
                    </>
                  )}
                </>
              )}
              {stage === STAGE.mounting && !dimension && (
                <>
                  <h2>{t('mounting.title')}</h2>
                  <p>{t('mounting.help')}</p>
                  {!compatibleMesh && (
                    <button className="primary wide" onClick={() => changeStage(STAGE.mesh)}>
                      <Grid2X2 />
                      {t('mounting.generateFirst')}
                    </button>
                  )}
                  {compatibleMesh && (
                    <Facts
                      rows={[
                        [
                          t('mounting.selection'),
                          pendingFixture
                            ? t('mounting.pending', { count: pendingFixture.length })
                            : t('mounting.saved', { count: shownFixture.length }),
                        ],
                      ]}
                    />
                  )}
                  <small data-testid="fixture-count">{shownFixture.length}</small>
                  <small>{t('mounting.newFixtureOnly')}</small>
                </>
              )}
      {stage === STAGE.contact && !dimension && (
                <>
                  <h2>{t('contact.title')}</h2>
                  <Facts
                    rows={[
                      [t('contact.normal'), t('contact.hard')],
                      [t('contact.domain'), t('contact.pairsDomain')],
                      [t('contact.participants'), participantNames.join(', ') || t('contact.none')],
                      [t('contact.excluded'), bodyNames.join(', ') || t('contact.none')],
                    ]}
                  />
                  {p.contact.friction !== null ? (
                    <p className="notice" data-testid="contact-legacy">
                      {t('contact.legacyScalar', { value: String(p.contact.friction) })}
                    </p>
                  ) : (
                    <>
                      <NumberInput
                        label={t('contact.doorSeal')}
                        value={p.contact.door_seal}
                        min={0}
                        max={5}
                        rangeHint={t('contact.muRange')}
                        onChange={(v) =>
                          edit((n) => {
                            n.contact.door_seal = v
                          })
                        }
                      />
                      {twoStep && (
                        <NumberInput
                          label={t('contact.bodySeal')}
                          value={p.contact.body_seal}
                          min={0}
                          max={5}
                          rangeHint={t('contact.muRange')}
                          onChange={(v) =>
                            edit((n) => {
                              n.contact.body_seal = v
                            })
                          }
                        />
                      )}
                      <NumberInput
                        label={t('contact.sealSelf')}
                        value={p.contact.seal_self}
                        min={0}
                        max={5}
                        rangeHint={t('contact.muRange')}
                        onChange={(v) =>
                          edit((n) => {
                            n.contact.seal_self = v
                          })
                        }
                      />
                      <small>{t('contact.pairHelp')}</small>
                    </>
                  )}
                  {!twoStep && bodyNames.length > 0 && (
                    <p className="notice" data-testid="body-excluded">
                      {t('body.excluded')}
                    </p>
                  )}
                  <button
                    className="primary wide"
                    disabled={busy || !dirty}
                    title={dirty ? undefined : t('contact.saved')}
                    onClick={() => execute(save)}
                  >
                    <CheckCheck />
                    {t('contact.save')}
                  </button>
                  <small>{t('contact.noFixtureAction')}</small>
                </>
              )}
              {stage === STAGE.motion && !dimension && (
                <>
                  <h2>{t('motion.title')}</h2>
                  <div className="step-plan" data-testid="step-plan">
                    <strong>
                      {twoStep ? t('motion.planTwoStep') : t('motion.planOneStep')}
                    </strong>
                    <ol>
                      {plan.steps.map((step) => (
                        <li key={step.id}>
                          {step.role === 'body'
                            ? t('motion.step1Body')
                            : twoStep
                              ? t('motion.step2Door')
                              : t('motion.stepDoorOnly')}
                        </li>
                      ))}
                    </ol>
                    {plan.findings.map((item) => (
                      <p
                        key={item.code}
                        className="error-text"
                        data-testid={'step-plan-' + item.code}
                      >
                        {t(('readiness.' + item.code) as TranslationKey)}
                      </p>
                    ))}
                  </div>
                  {twoStep && (
                    <>
                      <h3>{t('motion.step1Body')}</h3>
                      <NumberInput
                        label={t('motion.bodyStroke')}
                        unit="mm"
                        min={0}
                        max={10000}
                        value={p.motion.body.stroke}
                        onChange={(v) =>
                          edit((n) => {
                            n.motion.body.stroke = v
                            n.motion.body.travel = 0
                          })
                        }
                      />
                      <NumberInput
                        label={t('motion.bodyAngle')}
                        unit="°"
                        min={-360}
                        max={360}
                        rangeHint={t('motion.angleHint')}
                        value={p.motion.body.angle}
                        onChange={(v) =>
                          edit((n) => {
                            n.motion.body.angle = v
                          })
                        }
                      />
                      <p className="motion-vector" data-testid="motion-body-vector">
                        {t('motion.vectorSummary', {
                          dx: motionDelta(p.motion.body.stroke, p.motion.body.angle)[0].toFixed(3),
                          dy: motionDelta(p.motion.body.stroke, p.motion.body.angle)[1].toFixed(3),
                        })}
                      </p>
                      <NumberInput
                        label={t('motion.bodyDuration')}
                        unit="s"
                        min={1e-9}
                        value={p.motion.body.duration}
                        onChange={(v) =>
                          edit((n) => {
                            n.motion.body.duration = v
                          })
                        }
                      />
                      <button
                        type="button"
                        data-testid="preview-body"
                        disabled={!twoStep || !(p.motion.body.stroke > 0)}
                        onClick={() => previewMotion('body')}
                      >
                        <Play />
                        {preview?.role === 'body' ? t('motion.stopPreview') : t('motion.previewBody')}
                      </button>
                      {p.motion.body.offset !== 0 && (
                        <p className="notice" data-testid="retained-body-offset">
                          {t('motion.retainedOffset', {
                            instance: 'BODY-1',
                            offset: String(p.motion.body.offset),
                          })}
                        </p>
                      )}
                      <h3>{t('motion.step2Door')}</h3>
                    </>
                  )}
                  <NumberInput
                    label={t('motion.doorStroke')}
                    unit="mm"
                    min={0}
                    max={10000}
                    value={p.motion.stroke}
                    onChange={(v) =>
                      edit((n) => {
                        n.motion.stroke = v
                        n.motion.travel = 0
                      })
                    }
                  />
                  <NumberInput
                    label={t('motion.doorAngle')}
                    unit="°"
                    min={-360}
                    max={360}
                    rangeHint={t('motion.angleHint')}
                    value={p.motion.angle}
                    onChange={(v) =>
                      edit((n) => {
                        n.motion.angle = v
                      })
                    }
                  />
                  <p className="motion-vector" data-testid="motion-vector">
                    {t('motion.vectorSummary', {
                      dx: motionDelta(p.motion.stroke, p.motion.angle)[0].toFixed(3),
                      dy: motionDelta(p.motion.stroke, p.motion.angle)[1].toFixed(3),
                    })}
                  </p>
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
                  <button
                    type="button"
                    data-testid="preview-door"
                    disabled={!(p.motion.stroke > 0)}
                    onClick={() => previewMotion('door')}
                  >
                    <Play />
                    {preview?.role === 'door' ? t('motion.stopPreview') : t('motion.previewDoor')}
                  </button>
                  {p.motion.offset !== 0 && (
                    <p className="notice" data-testid="retained-door-offset">
                      {t('motion.retainedOffset', {
                        instance: 'PANEL-1',
                        offset: String(p.motion.offset),
                      })}
                    </p>
                  )}
                  <p>{t('motion.help')}</p>
                  <p className="quality-note subtle" data-testid="motion-zero-hold">
                    {t('motion.zeroHolds')}
                  </p>
                  {motionFinding && !dirty && (
                    <p className="error-text" role="alert" data-testid="motion-error">
                      {t(
                        findingKey(motionFinding.code),
                        findingVars(motionFinding, t),
                      )}
                    </p>
                  )}
                  <AssemblyDiagnostics
                    assessment={readiness?.assembly ?? null}
                    dirty={dirty}
                  />
                </>
              )}
      {dimension && stage !== STAGE.results && (
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
              {stage === STAGE.mesh && !dimension && (
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
                  {panelEdges.length > 0 ? (
                    <>
                      <NumberInput
                        label={t('mesh.panelSize')}
                        unit="mm"
                        min={0.01}
                        max={10000}
                        value={p.mesh.local[panelEdges[0].id] ?? p.mesh.size}
                        onChange={(v) =>
                          edit((n) => {
                            for (const item of panelEdges) n.mesh.local[item.id] = v
                          })
                        }
                      />
                      <small>{t('mesh.panelSizeHint')}</small>
                      <small>{t('mesh.panelSizeEffect')}</small>
                    </>
                  ) : (
                    <small>{t('mesh.panelSizeMissing')}</small>
                  )}
                  {!twoStep && bodyNames.length > 0 && (
              <small>{t('mesh.bodyPreviewOnly')}</small>
            )}
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
                  <fieldset className="enforced-setting" data-testid="reduced-integration-policy">
                    <legend>{t('mesh.reducedIntegration')}</legend>
                    <label className="check">
                      <input type="checkbox" checked disabled readOnly />
                      {t('mesh.reducedIntegrationLabel')}
                    </label>
                    <small>{t('mesh.reducedIntegrationHelp')}</small>
                  </fieldset>
                </>
              )}
              {stage === STAGE.review && !dimension && (
                <>
                  <h2>{t('review.title')}</h2>
                  <Facts
                    rows={[
                      [t('review.formulation'), t('review.planeStress')],
                      [t('review.step'), t('review.implicitDynamic')],
                      [t('review.geometry'), t('review.nonlinear')],
                    ]}
                  />
                  <Facts
                    rows={[
                      [
                        t('review.mounting'),
                        fixture
                          ? t('review.fixtureSummary', { count: fixture.count })
                          : t('hint.fixtureRequired'),
                      ],
                      [
                        t('review.contact'),
                        p.contact.friction !== null
                          ? t('review.contactSummaryLegacy', {
                              friction: String(p.contact.friction),
                            })
                          : t('review.contactSummaryPairs', {
                              door: String(p.contact.door_seal),
                              body: String(p.contact.body_seal),
                              self: String(p.contact.seal_self),
                            }),
                      ],
                      [t('review.panels'), participantNames.join(', ') || t('contact.none')],
                      [
                        t('review.stepSequence'),
                        plan.mode === 'door_only'
                          ? p.motion.stroke === 0
                            ? t('review.stepDoorHold')
                            : t('review.stepDoorOnly')
                          : p.motion.body.stroke === 0 && p.motion.stroke === 0
                            ? t('review.stepHoldOnly')
                            : p.motion.stroke === 0
                              ? t('review.stepBodyThenHold')
                              : t('review.stepBodyThenDoor'),
                      ],
                      ...(plan.mode === 'body_then_door'
                        ? [
                            [
                              t('review.bodyTravel'),
                              t('review.bodyMotionSummaryV2', {
                                stroke: String(p.motion.body.stroke),
                                angle: String(p.motion.body.angle),
                                duration: String(p.motion.body.duration),
                              }),
                            ] as [string, string],
                          ]
                        : []),
                    ]}
                  />
                  {!twoStep && bodyNames.length > 0 && (
                    <p className="notice" data-testid="body-excluded">
                      {t('body.excluded')}
                    </p>
                  )}
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
                  <small>{t('review.thicknessHelp')}</small>
                  <NumberInput
                    label={t('review.reportingWidth')}
                    unit="mm"
                    min={1e-9}
                    max={1e6}
                    value={p.analysis.reporting_width}
                    onChange={(v) =>
                      edit((n) => {
                        n.analysis.reporting_width = v
                      })
                    }
                  />
                  <small data-testid="reporting-width-help">{t('review.reportingWidthHelp')}</small>
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
                  {p.analysis.reporting_width_basis === 'legacy_thickness' && (
                    <p className="notice" data-testid="legacy-force-basis">
                      {t('review.legacyForceBasis', {
                        width: String(p.analysis.reporting_width),
                      })}
                    </p>
                  )}
                  {p.contact.friction === null && (
                    <p className="motion-vector" data-testid="review-contact-pairs">
                      {t('contact.pairSummary', {
                        door: String(p.contact.door_seal),
                        body: String(p.contact.body_seal),
                        self: String(p.contact.seal_self),
                      })}
                    </p>
                  )}
                  <AssemblyDiagnostics
                    assessment={readiness?.assembly ?? null}
                    dirty={dirty}
                  />
                </>
              )}
              {stage === STAGE.mesh && !dimension && (
                <>
                  <h3>{t('mesh.meshSection')}</h3>
                  {confirmRegenerate && compatibleMesh ? (
                    <div className="notice" role="alertdialog" data-testid="regenerate-confirm">
                      <p>
                        {t('mesh.regeneratePrompt', {
                          count: compatibleMesh.fixture?.count ?? 0,
                        })}
                      </p>
                      <div className="fixture-actions">
                        <button
                          className="primary"
                          onClick={() => {
                            setConfirmRegenerate(false)
                            void execute(generate)
                          }}
                        >
                          {t('mesh.regenerate')}
                        </button>
                        <button onClick={() => setConfirmRegenerate(false)}>
                          {t('common.cancel')}
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      className="primary wide"
                      disabled={busy || !!blockedReason}
                      title={blockedReason || undefined}
                      onClick={() => {
                        if (fixtureReviewed && compatibleMesh) setConfirmRegenerate(true)
                        else void execute(generate)
                      }}
                    >
                      <Grid2X2 />
                      {t('mesh.generate')}
                    </button>
                  )}
                  {meshJob && !dirty && (
                    <div className="build-info" data-testid="mesh-status">
                      <strong>
                        {compatibleMesh ? t('mesh.meshReady') : t('mesh.meshStale')}
                      </strong>
                      {meshJob.diagnostic && <p className="error-text">{meshJob.diagnostic}</p>}
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
              {stage === STAGE.review && !dimension && compatibleMesh && !locked && (
                <>
                  <h3>{t('review.meshIdentity')}</h3>
                  <Facts
                    rows={[
                      [t('review.meshNodes'), quality?.nodes ?? '—'],
                      [t('review.meshElements'), quality?.elements ?? '—'],
                      [
                        t('review.fixedNodes'),
                        fixture ? fixture.count : t('hint.fixtureRequired'),
                      ],
                    ]}
                  />
                  <p>{t('review.meshOwnedByMesh')}</p>
                  {quality && meshFile && !dirty && (
                    <MeshReview
                      quality={quality}
                      project={p}
                      clearance={placement?.initial_vertical_mesh_clearance_mm ?? null}
                    />
                  )}
                </>
              )}
              {locked && (
                <>
                  <h3>{t('review.archivedMesh')}</h3>
                  {archived.mesh ? (
                    <Facts
                      rows={[[t('review.fixedNodes'), archivedFixture?.length ?? 0]]}
                    />
                  ) : (
                    <p className="error-text" data-testid="archive-mesh-error">
                      {archived.error || t('mesh.archiveResolving')}
                    </p>
                  )}
                  <p>{t('review.archivedMeshHelp')}</p>
                </>
              )}
              {locked && archivedFixture && (
                <>
                  <h3>{t('mesh.fixedNodes')}</h3>
                  <p>{t('mesh.archivedFixtureHelp')}</p>
                  <Facts
                    rows={[
                      [t('mesh.fixedNodeCount'), archivedFixture.length],
                      [t('mesh.fixtureSource'), t('mesh.sourceArchived')],
                    ]}
                  />
                </>
              )}
              {stage === STAGE.mounting && !dimension && !locked && compatibleMesh && !dirty && (
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
                      [t('mesh.fixedNodeCount'), shownFixture.length],
                      [
                        t('mesh.fixtureSource'),
                        archivedFixture
                          ? t('mesh.sourceArchived')
                          : fixture
                            ? t('mesh.sourceNodes')
                            : t('mesh.sourceNone'),
                      ],
                    ]}
                  />
                  <div className="fixture-actions">
                    <button
                      className="primary"
                      disabled={!fixturePending}
                      onClick={() => execute(() => saveFixture(pendingFixture ?? []))}
                    >
                      <CheckCheck />
                      {t('mesh.saveFixture')}
                    </button>
                    <button disabled={!fixturePending} onClick={() => setPendingFixture(null)}>
                      {t('mesh.discard')}
                    </button>
                  </div>
                  <small>{t('mesh.regenerateClears')}</small>
                  <button
                    className="wide"
                    disabled={!shownFixture.length && !pendingFixture}
                    onClick={() => setPendingFixture([])}
                  >
                    {t('mesh.clear')}
                  </button>
                  {fixturePending && (
                    <small>{t('mesh.fixtureUnsaved', { count: pendingFixture.length })}</small>
                  )}
                  {!fixture && !archivedFixture && (mount?.entities.length ?? 0) > 0 && (
                    <button
                      className="wide"
                      disabled={busy}
                      onClick={() => execute(resolveLegacyFixture)}
                    >
                      <ScanLine />
                      {t('mesh.resolveEdges', { count: mount?.entities.length ?? 0 })}
                    </button>
                  )}
                </>
              )}
              {stage === STAGE.review && !dimension && !compatibleMesh && (
                <>
                  <h3>{t('mesh.meshSection')}</h3>
                  <p>{t('hint.meshRequired')}</p>
                </>
              )}
              {stage === STAGE.review &&
                !dimension &&
                compatibleMesh &&
                (dirty || !fixtureReviewed) &&
                !locked && (
                  <>
                    <h3>{t('mesh.fixtureSection')}</h3>
                    <p>{dirty ? t('status.unsaved') : t('review.fixtureNeedsReview')}</p>
                    {!dirty && (
                      <button className="wide" onClick={() => changeStage(STAGE.mounting)}>
                        {t('review.goToMounting')}
                      </button>
                    )}
                  </>
                )}
            </fieldset>
            {stage === STAGE.results && (
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
              : fixtureMode && mode === 'node'
                ? t('status.fixtureSelection', {
                    count: shownFixture.length,
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
