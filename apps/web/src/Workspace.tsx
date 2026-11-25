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
  RefreshCw,
  RotateCcw,
  Save,
  SaveAll,
  ScanLine,
  FolderOpen,
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
  rememberActiveDocument,
  rememberRecentFile,
  replaceRoute,
  replaceRouteSilent,
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
import { STAGE_LABELS, WorkflowNavigation } from './features/workspace/WorkflowNavigation'
import { workflowStates } from './features/workspace/workflowStates'
import { findingKey, findingVars, type Readiness } from './features/workspace/readiness'
import { AnalysisActions } from './features/workspace/AnalysisActions'
import { useAutoSave } from './features/workspace/autosave'
import { motionDelta, stepPlan } from './features/workspace/stepSequence'
import {
  MESH_STAGES,
  STAGE_ORDER,
  decodeStage,
  stageMode,
  type StageId,
} from './features/workspace/stages'
import { freshCard, materialIssues } from './features/materials/MaterialEditor'
import { meshQuality, type MeshFile } from './features/mesh/meshQuality'
import { MeshReview } from './features/mesh/MeshReview'

type Mesh = ViewMesh & MeshFile
type Props = { initial: Revision; locked?: Job; notify: (msg: string) => void }

/**
 * Effective motion policy for the stored schema. Version 4 validates stroke,
 * angle and duration (a hold at zero stroke is valid); older revisions keep
 * their signed travel and duration. The sign is never an unconditional
 * blocker: the deck writer tests the measured contact side and direction.
 */
function motionPolicyValid(project: Project): boolean {
  const body = project.analysis.mode === 'body_then_door'
  const check = (motion: {
    stroke?: number
    angle?: number
    duration: number
    travel?: number
  }) => {
    if (!(Number.isFinite(motion.duration) && motion.duration > 0)) return false
    if (project.schema_version >= 4)
      return (
        Number.isFinite(motion.stroke) &&
        (motion.stroke as number) >= 0 &&
        Number.isFinite(motion.angle) &&
        Math.abs(motion.angle as number) <= 360
      )
    return Number.isFinite(motion.travel)
  }
  if (!check(project.motion)) return false
  if (body && !check(project.motion.body)) return false
  return true
}

type PartitionGuide = {
  index: number
  status: 'selected' | 'no_hit'
  start: number[]
  end: number[]
  intervals: number[][][]
  length_mm: number
}

type PartitionChild = {
  id: string | null
  name: string | null
  area: number
  material: string | null
}

type PartitionPlan = {
  face: string
  status: 'valid' | 'one_region' | 'mixed' | 'redundant'
  guides: PartitionGuide[]
  unused_guides: number[]
  seams: string[]
  split_edges: string[]
  children: PartitionChild[]
  areas: number[]
  area_parent: number
  area_children: number
  child_count: number
  /** Historical two-child aliases, kept for older callers. */
  child_a?: string | null
  child_b?: string | null
  area_a?: number
  area_b?: number
  cut_edge?: string | null
  line?: number[][]
  start?: number[]
  end?: number[]
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
  'cut_no_hit',
  'sliver_cut',
  'tangent_cut',
  'ambiguous_loop',
  'ambiguous_hole',
  'area_mismatch',
  'overlapping_children',
  'invalid_result',
  'unsupported_curve',
  'one_region',
  'mixed',
  'redundant',
]

/**
 * Stages whose persisted values differ between the draft and the saved
 * revision. Material-only face edits belong to Materials; topology belongs to
 * Components. Used only to place the local "Unsaved" badge; the server owns
 * readiness.
 */
function changedStages(a: Project, b: Project): Set<StageId> {
  const changed = new Set<StageId>()
  const differs = (left: unknown, right: unknown) =>
    JSON.stringify(left) !== JSON.stringify(right)
  if (differs([a.name, a.source, a.dimension, a.formulation, a.plane, a.extrusion], [b.name, b.source, b.dimension, b.formulation, b.plane, b.extrusion]))
    changed.add('import')
  const topology = (p: Project) =>
    p.faces.map((face) => [face.id, face.name, face.component, face.cavity, face.loops])
  if (differs([a.components, a.vertices, a.edges, topology(a)], [b.components, b.vertices, b.edges, topology(b)]))
    changed.add('components')
  const materials = (p: Project) => [p.materials, p.faces.map((face) => [face.id, face.material])]
  if (differs(materials(a), materials(b))) changed.add('materials')
  if (differs([a.mesh], [b.mesh])) changed.add('mesh')
  if (differs([a.selections, a.mounting], [b.selections, b.mounting])) changed.add('mounting')
  if (differs([a.contact], [b.contact])) changed.add('contact')
  if (differs([a.motion, a.analysis], [b.motion, b.analysis])) changed.add('motion')
  return changed
}

export default function Workspace({ initial, locked, notify }: Props) {
  const { t } = useI18n()
  const compatibility = useCompatibility()
  const [rev, setRev] = useState(initial),
    [p, setP] = useState(initial.setup)
  const [stage, setStage] = useState<StageId>(() => {
    // An empty model opens at Import. The stage is remembered per revision and
    // per model so a save-induced remount cannot send the user back to step one.
    // Legacy numeric indexes are decoded explicitly (7 = old Review/Run).
    const fallback: StageId = initial.setup.source.kind === 'empty' ? 'import' : 'components'
    try {
      const saved =
        sessionStorage.getItem('stage:' + initial.id) ??
        sessionStorage.getItem('stage-project:' + initial.project)
      return decodeStage(saved, fallback)
    } catch {
      // Storage denial falls back to the explicit default.
      return fallback
    }
  }),
    [mode, setMode] = useState<SelectionMode>(() => stageMode(stage))
  const [pick, select] = useState<Picked | null>(() => {
    // A restored stage or a just-saved partition restores its matching
    // selection, or the editor would render without an entity after a remount.
    try {
      const stored = sessionStorage.getItem('pick:' + initial.id)
      if (stored) {
        const parsed = JSON.parse(stored) as Picked
        const face = initial.setup.faces.find((item) => item.id === parsed.id)
        const edge = initial.setup.edges.find((item) => item.id === parsed.id)
        if (parsed.kind === 'face' && face)
          return { kind: 'face', id: face.id, entity: face.id, component: face.component }
        if (parsed.kind === 'edge' && edge)
          return { kind: 'edge', id: edge.id, entity: edge.id, component: edge.component }
      }
    } catch {
      // A denied or stale selection falls back to the stage default.
    }
    const face = p.faces[0]
    if ((stage === 'components' || stage === 'materials') && face)
      return { kind: 'face', id: face.id, entity: face.id, component: face.component }
    const edge = p.edges[0]
    if (stage === 'mesh' && edge)
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
    [showMesh, setShowMesh] = useState(() => MESH_STAGES.includes(stage))
  // A just-queued deck must become the visible deck before submission, or the
  // server would correctly reject an older deck as superseded.
  const [pendingDeck, setPendingDeck] = useState<string | null>(null)
  const [actionBusy, setActionBusy] = useState<'prepare' | 'submit' | null>(null)
  // Fixed-node fixture review: a pending selection is shown but not stored until
  // Save, so a rectangle can be corrected before it becomes WSFIX.
  const [fixtureMode, setFixtureMode] = useState(() => stage === 'mounting'),
    [pendingFixture, setPendingFixture] = useState<string[] | null>(null),
    [boxOperation, setBoxOperation] = useState<'replace' | 'add' | 'subtract'>('replace')
  const [working, setBusy] = useState(false),
    [info, message] = useState(''),
    [issue, setIssue] = useState(''),
    [generation, refresh] = useState(0)
  const [cap, setCap] = useState<Record<string, string>>({}),
    [related, setRelated] = useState<Job[]>([]),
    [readiness, setReadiness] = useState<Readiness | null>(null),
    [readinessError, setReadinessError] = useState(false),
    [readinessLoading, setReadinessLoading] = useState(true)
  const [runName, setRunName] = useState(() => t('review.defaultRunName')),
    [cpus, setCpus] = useState(1)
  // Portable file: the active pathname and the exact fingerprint this session
  // last wrote. A different on-disk file is a conflict until overwrite is chosen.
  const [filePath, setFilePath] = useState('')
  const [fileSha, setFileSha] = useState('')
  // The revision actually packaged into ``filePath``. It is tracked separately
  // from the working head so Close can tell "the file is behind the model".
  const [fileRevision, setFileRevision] = useState('')
  const [fileDialog, setFileDialog] = useState(false)
  const [folderDraft, setFolderDraft] = useState('')
  const [nameDraft, setNameDraft] = useState('')
  const [fileBusy, setFileBusy] = useState(false)
  // Folder captured at submit, so the worker can publish the .aqresult even when
  // the browser tab is closed.
  const [outputDir, setOutputDir] = useState('')
  // Narrow and zoomed layouts can collapse the workflow/properties panes so the
  // canvas and the primary actions remain reachable without clipping.
  const [panesOpen, setPanesOpen] = useState(true)
  // Projected material partition. The operator draws arbitrary two-click
  // strokes on the white viewport while staying in Components; the XY fields
  // are an optional accessible precision alternative. Pending guides remain a
  // draft until Apply commits one revision.
  const [cutTarget, setCutTarget] = useState<string | null>(null)
  const [cutArmed, setCutArmed] = useState(false)
  const [cutDraft, setCutDraft] = useState<{
    a: [number, number]
    b: [number, number] | null
  } | null>(null)
  const [cutStrokes, setCutStrokes] = useState<
    { a: [number, number]; b: [number, number] }[]
  >([])
  const [cutHover, setCutHover] = useState<[number, number] | null>(null)
  const [cutPrecision, setCutPrecision] = useState(false)
  const [cutStart, setCutStart] = useState({ x: 0, y: 0 })
  const [cutEnd, setCutEnd] = useState({ x: 0, y: 0 })
  const [cutPlan, setCutPlan] = useState<PartitionPlan | null>(null)
  const [cutError, setCutError] = useState('')
  const [cutBusy, setCutBusy] = useState(false)
  const cutRequest = useRef(0)
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
  // Semantic persisted-value equality: returning exactly to the saved values
  // must clear the dirty state even though the object identity changed.
  const serializedProject = useMemo(() => JSON.stringify(p), [p])
  const savedProject = useMemo(() => JSON.stringify(rev.setup), [rev.setup])
  const dirty = serializedProject !== savedProject
  const archivedModel = rev.archived || rev.group_archived
  /**
   * One current model, one working head. A valid committed edit replaces the
   * current setup automatically; the model identity (and every immutable
   * revision a run already points at) stays unchanged. A locked replay and an
   * archived model are read-only and never write.
   */
  const autosave = useAutoSave({
    projectId: rev.project,
    baseId: rev.id,
    baseline: savedProject,
    // A 3D extrusion preview is still an editable model (its name, dimension
    // and extrusion settings persist); only simulation is deferred.
    enabled: !locked && !archivedModel,
    onSaved: (saved, sent, adopt) => {
      setRev(saved)
      // Adopt the server-normalized setup when no newer edit arrived while the
      // write was in flight; otherwise the newer draft stays on screen. A reload
      // or a rebased write explicitly adopts the newest committed document.
      setP((current) =>
        adopt || JSON.stringify(current) === JSON.stringify(sent) ? saved.setup : current,
      )
      // Follow the head in the URL without a router-visible remount, so focus,
      // selection, the viewport camera and the active stage survive the save.
      replaceRouteSilent('workspace/' + saved.id)
    },
  })
  const savePhase = autosave.state.phase
  // The action handlers read the newest rendered draft, never a stale closure.
  const latestDraft = useRef(p)
  latestDraft.current = p
  useEffect(() => {
    if (locked || !dirty) return
    autosave.queue(p)
    // The serialized draft is the only change signal; queueing is idempotent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serializedProject, savedProject, locked])
  useEffect(() => {
    // Restore the active file for this model. The fingerprint is what makes an
    // external edit a conflict rather than a silent overwrite.
    try {
      const raw = localStorage.getItem('model-file:' + initial.project)
      const parsed = raw
        ? (JSON.parse(raw) as { path?: string; sha?: string; revision?: string })
        : null
      setFilePath(parsed?.path ?? '')
      setFileSha(parsed?.sha ?? '')
      setFileRevision(parsed?.revision ?? '')
    } catch {
      setFilePath('')
      setFileSha('')
      setFileRevision('')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial.project])
  // The tab-scoped document session is what Dashboard's Close control acts on.
  // It records the working head and the exact revision the file contains.
  useEffect(() => {
    if (locked) return
    rememberActiveDocument({
      project: rev.project,
      revision: rev.id,
      name: rev.setup.name,
      path: filePath,
      sha: fileSha,
      fileRevision,
      dirty: dirty || autosave.state.dirty || autosave.state.phase === 'pending',
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    rev.project,
    rev.id,
    rev.setup.name,
    filePath,
    fileSha,
    fileRevision,
    dirty,
    autosave.state.dirty,
    autosave.state.phase,
    locked,
  ])
  // Ctrl+S flushes the current model to the portable file. A ref keeps the
  // listener stable while the handler sees the newest path and head.
  const saveShortcut = useRef<() => void>(() => undefined)
  saveShortcut.current = saveModel
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        saveShortcut.current()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])
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
            sessionStorage.setItem('stage:' + next.id, 'components')
            sessionStorage.setItem('stage-project:' + next.project, 'components')
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
          setStage('components')
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
      sessionStorage.setItem('stage:' + rev.id, stage)
      sessionStorage.setItem('stage-project:' + rev.project, stage)
    } catch {
      // Remembering the step is a convenience; the workflow stays usable without it.
    }
  }, [stage, rev.id, rev.project])
  useEffect(() => {
    try {
      if (pick) sessionStorage.setItem('pick:' + rev.id, JSON.stringify(pick))
      else sessionStorage.removeItem('pick:' + rev.id)
    } catch {
      // Restoring the selected entity is a convenience, never a workflow gate.
    }
  }, [pick, rev.id])
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
  // Version 4 stores a nonnegative stroke and a direction angle, so a positive
  // delta-Y is valid when the measured geometry permits it. Only a historical
  // revision is judged by its signed travel field; the deck writer still owns
  // the geometric direction check.
  const motionValid = motionPolicyValid(p)
  // The server treats the newest deck for the revision as the only submittable
  // one. A deck prepared before the fixture or mesh changed is stale.
  const newestDeck = deckJobs.find((j) => j.revision === rev.id) ?? null
  const deck = pendingDeck
    ? (deckJobs.find((j) => j.id === pendingDeck) ?? null)
    : newestDeck
  const deckReady =
    !!deck &&
    deck.status === 'Completed' &&
    deck.id === newestDeck?.id &&
    deck.mesh === compatibleMesh?.id &&
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
  // The API owns the readiness calculation so the sidebar, the action group and
  // a direct API request cannot disagree about Prepare or Submit. A short
  // debounce keys the read to the mesh/deck/fixture identity, so idle polling
  // does not re-evaluate a large mesh on every tick.
  const readinessRequest = useRef(0)
  const readinessKey = [
    rev.id,
    compatibleMesh?.id ?? '',
    compatibleMesh?.mesh_digest ?? '',
    fixture?.hash ?? '',
    newestDeck?.id ?? '',
    newestDeck?.status ?? '',
    newestDeck?.mesh ?? '',
    newestDeck?.fixture_hash ?? '',
    related[0]?.id ?? '',
    related[0]?.status ?? '',
    pendingDeck ?? '',
    pendingFixture ? pendingFixture.length : '',
    // The draft itself is covered by the local overlay; only its dimension and
    // schema affect server eligibility.
    p.dimension,
    p.schema_version,
  ].join('|')
  useEffect(() => {
    const requestId = ++readinessRequest.current
    const ac = new AbortController()
    setReadinessLoading(true)
    const timer = setTimeout(() => {
      request<Readiness>('/api/revisions/' + rev.id + '/readiness', 'GET', undefined, ac.signal)
        .then((next) => {
          if (ac.signal.aborted || requestId !== readinessRequest.current) return
          // Guard a late response from a previous revision or save.
          if (next.revision !== rev.id) return
          setReadiness(next)
          setReadinessError(false)
          setReadinessLoading(false)
        })
        .catch(() => {
          if (ac.signal.aborted || requestId !== readinessRequest.current) return
          setReadinessError(true)
          setReadinessLoading(false)
        })
    }, 180)
    return () => {
      clearTimeout(timer)
      ac.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readinessKey, generation])
  // A stale tab returning to focus synchronizes with another tab's fixture,
  // mesh or deck transition without waiting for the next idle poll.
  useEffect(() => {
    const bump = () => refresh((g) => g + 1)
    const visible = () => {
      if (!document.hidden) bump()
    }
    window.addEventListener('focus', bump)
    document.addEventListener('visibilitychange', visible)
    return () => {
      window.removeEventListener('focus', bump)
      document.removeEventListener('visibilitychange', visible)
    }
  }, [])
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
  const dirtyStages = useMemo(() => changedStages(p, rev.setup), [p, rev.setup])
  const states = useMemo(
    () =>
      workflowStates({
        readiness,
        loading: readinessLoading && !readiness,
        dirtyStages,
        fixturePending,
        invalidDraft: invalidField,
      }),
    [readiness, readinessLoading, dirtyStages, fixturePending, invalidField],
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
  // Projected cut target: the selected face wins; a component with one material
  // face is an unambiguous target. A multi-face component asks the operator to
  // narrow the target explicitly in the region list.
  const cutFace = face && !face.cavity ? face : null
  const cutCandidates = useMemo(
    () =>
      p.faces.filter(
        (item) => !item.cavity && (!component || item.component === component.id),
      ),
    [p.faces, component],
  )
  const activeCutFace =
    p.faces.find((item) => item.id === cutTarget && !item.cavity) ??
    cutFace ??
    (cutCandidates.length === 1 ? cutCandidates[0] : null)
  // A pending partition belongs to one face; changing the target invalidates
  // the draft but never writes anything.
  useEffect(() => {
    setCutPlan(null)
    setCutError('')
    setCutStrokes([])
    setCutDraft(null)
    setCutArmed(false)
  }, [activeCutFace?.id])
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
  function changeStage(id: StageId) {
    // An invalid numeric draft is not silently committed or discarded by leaving
    // the step: keep it visible and make the engineer correct it or press Escape.
    if (invalidField || hasInvalidField()) {
      notify(t('validation.invalidDraft'))
      return
    }
    if (cutArmed) resetCut()
    setStage(id)
    setShowMesh(MESH_STAGES.includes(id))
    setFixtureMode(id === 'mounting')
    target(stageMode(id))
    // The action group of a newly selected stage must be reachable at the top of
    // its own scrolling pane; a previous stage's scroll position is not kept.
    requestAnimationFrame(() => rightPane.current?.scrollTo({ top: 0 }))
  }
  /**
   * Commit every valid pending edit and return the head the next operation must
   * use. Callers that queue work (mesh, partition, deck, submit, duplicate) await
   * this first, so work is never queued from the previous settings. A failed or
   * conflicting write throws and the operation is abandoned with its cause.
   */
  async function save() {
    assertNumericDrafts()
    // Register the newest rendered draft synchronously: the debounced effect may
    // not have run yet, and a queued job must never use the previous settings.
    autosave.queue(latestDraft.current)
    const saved = await autosave.flush()
    if (saved) message('')
    return saved ?? rev
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
  function partitionMessage(text: string) {
    const code = text.split(':')[0].trim()
    return PARTITION_CODES.includes(code)
      ? t(('partition.error.' + code) as TranslationKey)
      : text
  }
  function setCutPoints(a: [number, number] | null, b: [number, number] | null) {
    if (a) setCutStart({ x: Number(a[0].toFixed(6)), y: Number(a[1].toFixed(6)) })
    if (b) setCutEnd({ x: Number(b[0].toFixed(6)), y: Number(b[1].toFixed(6)) })
  }
  function startCut() {
    if (!activeCutFace) {
      notify(t('partition.chooseTarget'))
      return
    }
    // Any pending edit is committed by the preview/apply flush; arming the tool
    // never forces a manual save first.
    resetCut()
    setCutArmed(true)
    setCutPrecision(false)
    setCutPoints([0, 0], [0, 0])
    message(t('partition.drawHint'))
  }
  function resetCut() {
    setCutArmed(false)
    setCutDraft(null)
    setCutStrokes([])
    setCutHover(null)
    setCutPlan(null)
    setCutError('')
    cutRequest.current += 1
  }
  function removeCut(index: number) {
    const next = cutStrokes.filter((_, strokeIndex) => strokeIndex !== index)
    setCutStrokes(next)
    setCutDraft(null)
    cutRequest.current += 1
    if (next.length) void previewStrokes(next)
    else {
      setCutPlan(null)
      setCutError('')
    }
  }
  function undoCut() {
    removeCut(cutStrokes.length - 1)
  }
  async function previewStrokes(strokes: { a: [number, number]; b: [number, number] }[]) {
    if (!activeCutFace) return
    const requestId = ++cutRequest.current
    setCutBusy(true)
    try {
      // Commit the visible draft first. Preview and commit then share one saved
      // base, so the child IDs the engineer reviews are the IDs that are saved.
      const base = await save()
      const result = await request<{ plan: PartitionPlan }>('/api/partition/preview', 'POST', {
        setup: base.setup,
        base: base.id,
        face: activeCutFace.id,
        strokes: strokes.map((stroke) => [
          [stroke.a[0], stroke.a[1]],
          [stroke.b[0], stroke.b[1]],
        ]),
      })
      if (requestId !== cutRequest.current) return
      setCutPlan(result.plan)
      setCutError('')
    } catch (e) {
      if (requestId !== cutRequest.current) return
      setCutPlan(null)
      setCutError(partitionMessage(err(e)))
    } finally {
      if (requestId === cutRequest.current) setCutBusy(false)
    }
  }
  function placeCutPoint(point: [number, number]) {
    if (!cutArmed) return
    if (!cutDraft) {
      setCutDraft({ a: point, b: null })
      setCutPoints(point, null)
      setCutError('')
      return
    }
    const stroke = { a: cutDraft.a, b: point }
    const next = [...cutStrokes, stroke]
    setCutDraft(null)
    setCutStrokes(next)
    setCutPoints(stroke.a, stroke.b)
    void previewStrokes(next)
  }
  function addTypedCut() {
    if (!activeCutFace) return
    if (!cutDraftValid()) {
      setCutPlan(null)
      return
    }
    const values = cutPoints()
    const a: [number, number] = [values[0], values[1]]
    const b: [number, number] = [values[2], values[3]]
    if (Math.hypot(b[0] - a[0], b[1] - a[1]) <= 1e-6) {
      setCutError(t('partition.error.degenerate_cut'))
      return
    }
    const next = [...cutStrokes, { a, b }]
    setCutStrokes(next)
    setCutDraft(null)
    void previewStrokes(next)
  }
  async function applyCut() {
    if (!activeCutFace || !cutPlan || cutPlan.status !== 'valid') return
    if (!cutStrokes.length) return
    setCutBusy(true)
    try {
      // A partition is its own validated operation, but it still starts from the
      // committed head so preview and commit describe the same base revision.
      const base = await save()
      const saved = await request<Revision>(
        '/api/projects/' + base.project + '/partition',
        'POST',
        {
          base: base.id,
          face: activeCutFace.id,
          strokes: cutStrokes.map((stroke) => [
            [stroke.a[0], stroke.a[1]],
            [stroke.b[0], stroke.b[1]],
          ]),
        },
      )
      replaceRoute('workspace/' + saved.id)
      setRev(saved)
      setP(saved.setup)
      const child = cutPlan.children[0]
      const component = activeCutFace.component
      resetCut()
      if (child?.id) {
        // Persist the selection before the route remount so the persisted
        // child region opens highlighted in Components.
        try {
          sessionStorage.setItem(
            'pick:' + saved.id,
            JSON.stringify({ kind: 'face', id: child.id, entity: child.id, component }),
          )
          sessionStorage.setItem('stage:' + saved.id, 'components')
        } catch {
          // The remount falls back to the first region.
        }
        select({ kind: 'face', id: child.id, entity: child.id, component })
      }
      message(t('partition.applied', { number: saved.number }))
      refresh((g) => g + 1)
    } catch (e) {
      setCutError(partitionMessage(err(e)))
    } finally {
      setCutBusy(false)
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
    // Commit the visible edit before the deck is prepared: a deck always names
    // the current head revision, never the previous settings. The server
    // rechecks the same action-specific decision and stays authoritative.
    const head = await save()
    if (!compatibleMesh || !fixtureReviewed || pendingDeck) return
    const job = await request<Job>('/api/decks', 'POST', {
      revision: head.id,
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
    // Submit-only settings are validated locally, then the current head is
    // flushed so the run pins the setup the engineer can see.
    const head = await save()
    if (!deckReady || !deck) return
    const r = await request<Job>('/api/runs', 'POST', {
      name: runName,
      revision: head.id,
      deck: deck.id,
      token: token.current,
      cpus,
      mode: 'ABAQUS',
      output_dir: outputDir.trim() || undefined,
    })
    token.current = crypto.randomUUID()
    go('diagnostics/' + r.id)
  }
  function sanitizedFile(name: string) {
    return (
      name
        .trim()
        .replace(/[^0-9A-Za-z._-]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 60) || 'model'
    )
  }
  /**
   * Package a file. This is the one save path for the Save button, Ctrl+S,
   * Save As and Save & Close: a valid field edit is committed by the workspace
   * autosave first, and the revision returned by that flush is what the file
   * contains. Packaging the previously rendered head would silently leave the
   * newest edit on disk-out-of-date.
   */
  async function writeModel(path: string, overwrite = false) {
    setFileBusy(true)
    try {
      const head = await save()
      const saved = await request<{ path: string; sha256: string }>(
        '/api/files/model/save',
        'POST',
        {
          revision: head.id,
          path,
          base_sha: fileSha || undefined,
          overwrite,
        },
      )
      setFilePath(saved.path)
      setFileSha(saved.sha256)
      setFileRevision(head.id)
      try {
        localStorage.setItem(
          'model-file:' + rev.project,
          JSON.stringify({ path: saved.path, sha: saved.sha256, revision: head.id }),
        )
      } catch {
        // The pathname is still shown for this session.
      }
      // A saved file is how the user finds the document again after Close.
      rememberRecentFile({ path: saved.path, kind: 'model' })
      // The disk write is what "saved to file" means; the working-head write
      // alone never reports it.
      notify(t('file.savedTo', { path: saved.path }))
    } catch (error) {
      const message = err(error)
      if (!overwrite && /differs from the version/i.test(message)) {
        if (window.confirm(t('file.overwriteConfirm', { path }))) {
          setFileBusy(false)
          await writeModel(path, true)
          return
        }
      } else {
        // Keep the draft and the document open when the disk write fails.
        notify(message)
      }
    } finally {
      setFileBusy(false)
    }
  }
  function saveModel() {
    if (locked || archivedModel || fileBusy) return
    if (filePath) {
      void writeModel(filePath)
      return
    }
    beginSaveAs()
  }
  function beginSaveAs() {
    setFolderDraft(filePath ? filePath.replace(/[\\/][^\\/]*$/, '') : '')
    setNameDraft(filePath ? filePath.split(/[\\/]/).pop() || '' : sanitizedFile(rev.setup.name) + '.aqmodel')
    setFileDialog(true)
  }
  async function chooseSaveFolder() {
    try {
      const picked = await request<{ path: string }>(
        '/api/files/pick?mode=folder&title=' + encodeURIComponent(t('file.chooseFolder')),
      )
      if (picked.path) setFolderDraft(picked.path)
    } catch (error) {
      notify(err(error))
    }
  }
  function commitSaveAs() {
    const folder = folderDraft.trim().replace(/[\\/]+$/, '')
    const name = nameDraft.trim()
    if (!folder || !name) return
    const path = folder + '/' + (name.toLowerCase().endsWith('.aqmodel') ? name : name + '.aqmodel')
    setFileDialog(false)
    void writeModel(path)
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
            density: detail.card.density ?? null,
            young: detail.card.young ?? null,
            poisson: detail.card.poisson ?? null,
            c10: detail.card.c10 ?? null,
            d1: detail.card.d1 ?? null,
            test_data: (detail.card.test_data ?? []).map(
              (row) => [row[0], row[1], row[2]] as [number, number, number],
            ),
            family: detail.card.family ?? 'polymer',
            hyperfoam: detail.card.hyperfoam ?? null,
            hyperelastic: detail.card.hyperelastic ?? null,
            viscoelastic: detail.card.viscoelastic ?? null,
            plastic: detail.card.plastic ?? null,
            mullins: detail.card.mullins ?? null,
            thermal: detail.card.thermal ?? null,
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
        card.density = detail.card.density ?? null
        card.young = detail.card.young ?? null
        card.poisson = detail.card.poisson ?? null
        card.c10 = detail.card.c10 ?? null
        card.d1 = detail.card.d1 ?? null
        card.test_data = (detail.card.test_data ?? []).map(
          (row) => [row[0], row[1], row[2]] as [number, number, number],
        )
        card.hyperfoam = detail.card.hyperfoam ?? null
        card.hyperelastic = detail.card.hyperelastic ?? null
        card.viscoelastic = detail.card.viscoelastic ?? null
        card.plastic = detail.card.plastic ?? null
        card.mullins = detail.card.mullins ?? null
        card.thermal = detail.card.thermal ?? null
        card.family = detail.card.family ?? 'polymer'
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
  // One action-specific decision from the saved revision. Deck state belongs to
  // Submit; it never disables Prepare.
  const readinessMismatch = !readiness || readiness.revision !== rev.id
  const prepareIssue = readiness?.setup_issues?.[0] ?? null
  const submitIssue = readiness?.submit_issues?.[0] ?? null
  function issueText(issue: { code: string; stage: string; params: Record<string, string | number> }) {
    const text = t(findingKey(issue.code), findingVars(issue as never, t))
    const label = STAGE_LABELS[issue.stage as StageId]
    return label ? text + ' · ' + t(label) : text
  }
  const prepareReason = locked
    ? t('actions.submittedSetup')
    : !compatibility.ok
      ? t('compat.writesDisabled')
      : archivedModel
        ? t('workspace.archivedReadOnly')
        : dimension
          ? t('workspace.extrusionPreview')
          : blockedReason
            ? blockedReason
            : savePhase === 'error'
              ? t('status.saveFailedReason')
              : dirty || savePhase === 'saving'
                ? t('status.saving')
                : fixturePending
                  ? t('hint.fixturePending')
                  : readinessLoading && !readiness
                    ? t('actions.checking')
                    : readinessError
                      ? t('actions.readinessUnavailable')
                      : readinessMismatch
                        ? t('actions.checking')
                        : !readiness!.can_prepare
                          ? prepareIssue
                            ? issueText(prepareIssue)
                            : t('actions.notReady')
                          : ''
  const submitReason = prepareReason
    ? prepareReason
    : !readiness!.can_submit
      ? submitIssue
        ? issueText(submitIssue)
        : t('actions.notReady')
      : !deckReady
        ? t('hint.deckRequired')
        : !runName.trim()
          ? t('actions.runNameRequired')
          : !Number.isInteger(cpus) || cpus < 1 || cpus > 32
            ? t('actions.cpuRequired')
            : cap.abaqus !== 'Configured'
              ? cap.abaqus || t('actions.checking')
              : ''
  const activeRun = related.find((run) => anyActive([run])) ?? null
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
              {/* Automatic persistence: the state is visible, but there is no
                  manual Save revision step in the ordinary workspace. Duplicate
                  remains the explicit way to branch into an independent model. */}
              <span
                className="save-state"
                data-testid="save-state"
                data-state={savePhase}
                data-dirty={dirty ? 'true' : 'false'}
                aria-live="polite"
              >
                {savePhase === 'saving' || savePhase === 'pending' ? (
                  <LoaderCircle className="spin" />
                ) : savePhase === 'error' ? (
                  <Activity />
                ) : (
                  <CheckCheck />
                )}
                {savePhase === 'saving'
                  ? t('status.saving')
                  : savePhase === 'pending'
                    ? t('status.pendingSave')
                    : savePhase === 'error'
                      ? t('status.saveFailed')
                      : t('status.autosaved')}
              </span>
              {savePhase === 'error' && (
                <button
                  type="button"
                  data-testid="save-retry"
                  onClick={() => void execute(() => autosave.retry())}
                >
                  <RefreshCw />
                  {t('actions.retry')}
                </button>
              )}
              {savePhase === 'error' && autosave.state.conflicts.length > 0 && (
                // A field changed in both windows cannot be merged. Keep the
                // local draft until the engineer chooses the other revision.
                <button
                  type="button"
                  data-testid="save-reload"
                  onClick={() => void execute(() => autosave.reload())}
                >
                  <RotateCcw />
                  {t('actions.reload')}
                </button>
              )}
              <span
                className="model-file"
                data-testid="model-file"
                title={filePath || t('file.noFile')}
              >
                {filePath ? filePath.split(/[\\/]/).pop() : t('file.notSaved')}
              </span>
              <button
                type="button"
                data-testid="model-save"
                disabled={fileBusy || archivedModel}
                onClick={saveModel}
                title={t('file.saveHint')}
              >
                <Save />
                {t('file.save')}
              </button>
              <button
                type="button"
                data-testid="model-save-as"
                disabled={fileBusy || archivedModel}
                onClick={beginSaveAs}
              >
                <SaveAll />
                {t('file.saveAs')}
              </button>
              <button
                disabled={busy || archivedModel}
                title={archivedModel ? t('workspace.archivedReadOnly') : undefined}
                onClick={() =>
                  execute(async () => {
                    // Duplicate the latest valid setup, not the last manual save.
                    const head = await save()
                    const copy = await request<Revision>(
                      '/api/projects/' + head.project + '/duplicate',
                      'POST',
                      {},
                    )
                    go('workspace/' + copy.id)
                  })
                }
              >
                <Copy />
                {t('dashboard.duplicate')}
              </button>
            </>
          )}
        </div>
      </div>
      {savePhase === 'error' && (
        <p className="error-text blocked-banner" role="alert" data-testid="save-error">
          {autosave.state.error}
        </p>
      )}
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
      {/* Keep the next-action banner mounted across a background save: hiding it
          while the head advances changed the canvas height and re-fitted the
          viewport. It reflects the last known readiness and updates when the
          new document arrives. */}
      {!locked &&
        readiness?.first_blocker &&
        (STAGE_ORDER as readonly string[]).includes(readiness.first_blocker.stage) && (
          <div className="readiness-banner" aria-live="polite" data-testid="next-action">
            <span>{issueText(readiness.first_blocker)}</span>
            <button
              type="button"
              onClick={() =>
                changeStage(readiness.first_blocker!.stage as StageId)
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
              // Components owns region selection. Choosing a face no longer
              // routes to Materials automatically; the explicit "Assign
              // material" action does that.
              setStage(kind === 'edge' ? 'mesh' : 'components')
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
              display={display}
              mode={mode}
              selection={pick}
              onSelect={(hit) => {
                select(hit)
                message('')
                if (hit?.kind === 'face') {
                  // Selecting a region highlights it and narrows the partition
                  // target. It never routes away from Components or opens the
                  // material editor implicitly.
                  if (stage === 'components') setCutTarget(hit.id)
                  else if (stage !== 'materials') setStage('components')
                }
                if (hit?.kind === 'edge' && stage === 'components') setStage('mesh')
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
                stage === 'components' && cutArmed
                  ? {
                      active: true,
                      boundary: [],
                      start: cutDraft?.a ?? null,
                      end: cutDraft?.b ?? null,
                      phase: cutDraft ? (cutDraft.b ? 'previewed' : 'end') : 'start',
                      invalid: !!cutError,
                      hover: cutHover,
                      strokes: cutStrokes,
                      segments: (cutPlan?.guides ?? []).flatMap((guide) =>
                        guide.intervals.map((interval) => ({
                          a: interval[0] as [number, number],
                          b: interval[1] as [number, number],
                        })),
                      ),
                      status: cutPlan?.status ?? null,
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
            <div className="eyebrow">{t(STAGE_LABELS[stage])}</div>
            <fieldset disabled={!!locked || busy}>
              {stage === 'import' && (
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
              {stage === 'components' && (
                <>
                  <h2>
                    {face
                      ? face.name
                      : component
                        ? componentLabel(component)
                        : t('components.select')}
                  </h2>
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
                  <p className="quality-note subtle">{t('components.selectRegionHint')}</p>
                  <div className="region-list">
                    {p.faces
                      .filter((f) => !component || f.component === component.id)
                      .map((f) => (
                        <button
                          key={f.id}
                          type="button"
                          className={activeCutFace?.id === f.id ? 'selected' : ''}
                          aria-pressed={activeCutFace?.id === f.id}
                          onClick={() => {
                            setMode('face')
                            select({ kind: 'face', id: f.id, entity: f.id, component: f.component })
                            setCutTarget(f.id)
                          }}
                        >
                          <span className="swatch" style={{ background: colors[f.id] }} />
                          {f.name}
                          {f.cavity && <small>{t('materials.cavity')}</small>}
                        </button>
                      ))}
                  </div>
                  {activeCutFace ? (
                    <section className="partition-block" data-testid="partition-editor">
                      <h3>{t('partition.title')}</h3>
                      <p className="partition-target" data-testid="partition-target">
                        {t('partition.target', { name: activeCutFace.name })}
                      </p>
                      <p>{t('partition.help')}</p>
                      {!cutArmed ? (
                        <button
                          type="button"
                          className="primary wide"
                          data-testid="cut-region"
                          disabled={busy || !!locked || dimension}
                          title={dimension ? t('workspace.extrusionPreview') : undefined}
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
                            data-phase={
                              cutPlan
                                ? 'previewed'
                                : cutDraft?.b
                                  ? 'previewed'
                                  : cutDraft
                                    ? 'end'
                                    : 'start'
                            }
                          >
                            {cutError ||
                              (cutDraft
                                ? cutDraft.b
                                  ? t('partition.previewPending')
                                  : t('partition.pickEnd')
                                : cutStrokes.length
                                  ? cutBusy
                                    ? t('partition.previewPending')
                                    : t('partition.pickAnother')
                                  : t('partition.pickStart'))}
                          </p>
                          {cutHover && !cutDraft?.b && (
                            <p className="motion-vector" data-testid="cut-hover">
                              {t('partition.candidate', {
                                x: cutHover[0].toFixed(3),
                                y: cutHover[1].toFixed(3),
                              })}
                            </p>
                          )}
                          {(cutStrokes.length > 0 || cutDraft) && (
                            <ol className="cut-guides" data-testid="cut-guides">
                              {cutStrokes.map((stroke, index) => (
                                <li key={index}>
                                  {t('partition.guide', {
                                    index: index + 1,
                                    x1: stroke.a[0].toFixed(2),
                                    y1: stroke.a[1].toFixed(2),
                                    x2: stroke.b[0].toFixed(2),
                                    y2: stroke.b[1].toFixed(2),
                                  })}
                                  <button
                                    type="button"
                                    className="link-button"
                                    disabled={cutBusy}
                                    onClick={() => removeCut(index)}
                                  >
                                    {t('partition.removeGuide', { index: index + 1 })}
                                  </button>
                                </li>
                              ))}
                              {cutDraft && (
                                <li className="draft">
                                  {t('partition.guideDraft', {
                                    x: cutDraft.a[0].toFixed(2),
                                    y: cutDraft.a[1].toFixed(2),
                                  })}
                                </li>
                              )}
                            </ol>
                          )}
                          <div className="actions">
                            <button
                              type="button"
                              onClick={undoCut}
                              disabled={!cutStrokes.length || cutBusy}
                            >
                              {t('partition.undo')}
                            </button>
                            <button
                              type="button"
                              className="primary"
                              data-testid="apply-partition"
                              onClick={() => execute(applyCut)}
                              disabled={
                                busy || cutBusy || cutPlan?.status !== 'valid' || !cutStrokes.length
                              }
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
                        onClick={() => {
                          if (!cutArmed) startCut()
                          setCutPrecision((open) => !open)
                        }}
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
                            onClick={addTypedCut}
                            disabled={busy || cutBusy}
                          >
                            {t('partition.addGuide')}
                          </button>
                        </div>
                      )}
                      {cutPlan && (
                        <div
                          className="build-info"
                          data-testid="partition-plan"
                          data-status={cutPlan.status}
                        >
                          <strong>
                            {cutPlan.status === 'valid'
                              ? t('partition.previewReady')
                              : cutPlan.status === 'one_region'
                                ? t('partition.oneRegion')
                                : cutPlan.status === 'mixed'
                                  ? t('partition.mixed')
                                  : t('partition.redundant')}
                          </strong>
                          <small>
                            {t('partition.childAreas', {
                              count: String(cutPlan.child_count),
                              areas: cutPlan.areas.map((area) => area.toFixed(3)).join(' · '),
                            })}
                          </small>
                          {cutPlan.unused_guides.length > 0 && (
                            <small className="error-text">
                              {t('partition.unused', {
                                guides: cutPlan.unused_guides
                                  .map((index) => index + 1)
                                  .join(', '),
                              })}
                            </small>
                          )}
                          {cutPlan.status === 'one_region' && (
                            <small>{t('partition.oneRegionHint')}</small>
                          )}
                          <small>
                            {t('partition.intersections', {
                              count: cutPlan.split_edges.length,
                            })}
                          </small>
                        </div>
                      )}
                    </section>
                  ) : (
                    <p className="notice" data-testid="partition-choose-target">
                      {t('partition.chooseTarget')}
                    </p>
                  )}
                  {activeCutFace && (
                    <button
                      type="button"
                      className="wide"
                      data-testid="assign-material"
                      onClick={() => changeStage('materials')}
                    >
                      <Layers3 />
                      {t('components.assignMaterial')}
                    </button>
                  )}
                </>
              )}
              {stage === 'materials' && (
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
                      {mat?.model === 'cae_law' && (
                        <div className="cae-law" data-testid="cae-law-view">
                          <h3>{t('materialsLibrary.caeLawTitle')}</h3>
                          <ul className="issue-list">
                            {(
                              [
                                [
                                  'hyperfoam',
                                  mat.hyperfoam
                                    ? `N=${mat.hyperfoam.n} · ${mat.hyperfoam.moduli}${
                                        mat.hyperfoam.test_data ? ' · test data' : ''
                                      }`
                                    : '',
                                ],
                                [
                                  'hyperelastic',
                                  mat.hyperelastic
                                    ? `${mat.hyperelastic.type} · ${mat.hyperelastic.moduli_time_scale}`
                                    : '',
                                ],
                                [
                                  'viscoelastic',
                                  mat.viscoelastic ? mat.viscoelastic.time : '',
                                ],
                                ['plastic', mat.plastic ? mat.plastic.hardening : ''],
                                ['mullins', mat.mullins ? mat.mullins.definition : ''],
                                ['thermal', mat.thermal ? 'conductivity' : ''],
                              ] as [string, string][]
                            )
                              .filter(([, detail]) => detail)
                              .map(([key, detail]) => (
                                <li key={key}>
                                  {key} · {detail}
                                </li>
                              ))}
                          </ul>
                          <small>{t('materialsLibrary.caeLawReadOnly')}</small>
                        </div>
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
                              [
                                t('materials.density'),
                                mat.density == null ? '—' : mat.density.toExponential(2),
                              ],
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
              {stage === 'mounting' && !dimension && (
                <>
                  <h2>{t('mounting.title')}</h2>
                  <p>{t('mounting.help')}</p>
                  {!compatibleMesh && (
                    <button className="primary wide" onClick={() => changeStage('mesh')}>
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
      {stage === 'contact' && !dimension && (
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
                  {/* Contact values are ordinary model settings: a valid edit is
                      committed automatically. There is no separate save action
                      that could discard an unrelated pending setup edit. */}
                  <small>{t('contact.autoSaved')}</small>
                  <small>{t('contact.noFixtureAction')}</small>
                </>
              )}
              {stage === 'motion' && !dimension && (
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
                  <Facts
                    rows={[
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
                  {motionFinding && readiness?.revision === rev.id && (
                    <p className="error-text" role="alert" data-testid="motion-error">
                      {t(
                        findingKey(motionFinding.code),
                        findingVars(motionFinding, t),
                      )}
                    </p>
                  )}
                  {/* The assessment describes the committed mesh. A pending
                      automatic save is not a reason to hide it or the fields. */}
                  <AssemblyDiagnostics
                    assessment={readiness?.assembly ?? null}
                    dirty={false}
                  />
                  {/* Analysis settings live with Motion; the viewport is not
                      touched. Solver thickness stays read-only so a navigation
                      change can never rewrite a revision's physical meaning. */}
                  <div className="analysis-settings" data-testid="analysis-settings">
                    <h3>{t('motion.analysisSettings')}</h3>
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
                    <small data-testid="reporting-width-help">
                      {t('review.reportingWidthHelp')}
                    </small>
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
                    <Facts
                      rows={[
                        [
                          t('motion.solverThickness'),
                          t('motion.solverThicknessValue', {
                            value: String(p.analysis.thickness),
                          }),
                        ],
                      ]}
                    />
                    <small>{t('motion.solverThicknessHelp')}</small>
                    {p.analysis.reporting_width_basis === 'legacy_thickness' && (
                      <p className="notice" data-testid="legacy-force-basis">
                        {t('review.legacyForceBasis', {
                          width: String(p.analysis.reporting_width),
                        })}
                      </p>
                    )}
                  </div>
                </>
              )}
      {dimension && stage !== 'results' && (
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
              {stage === 'mesh' && !dimension && (
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
              {stage === 'mesh' && !dimension && (
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
                  {meshJob && (
                    <div className="build-info" data-testid="mesh-status">
                      <strong>
                        {compatibleMesh ? t('mesh.meshReady') : t('mesh.meshStale')}
                      </strong>
                      {meshJob.diagnostic && <p className="error-text">{meshJob.diagnostic}</p>}
                    </div>
                  )}
                  {compatibleMesh && (
                    <>
                      <h3>{t('mesh.identity')}</h3>
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
                    </>
                  )}
                  {quality && meshFile && compatibleMesh && (
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
              {/* The fixed-node picker belongs to a compatible mesh, not to the
                  absence of a pending automatic save: an unrelated friction or
                  motion edit must keep Mounting visible and usable. */}
              {stage === 'mounting' && !dimension && !locked && compatibleMesh && (
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
            </fieldset>
            {stage === 'results' && (
              <>
                {/* One place to prepare and run: the action group lives at the
                    top of the Results properties, so it is reachable before a
                    mesh or deck exists and there is no duplicate control set. */}
                <AnalysisActions
                  locked={locked}
                  archived={archivedModel}
                  pendingDeck={!!pendingDeck}
                  preparing={actionBusy === 'prepare'}
                  submitting={actionBusy === 'submit'}
                  deck={deck}
                  deckReady={deckReady}
                  prepareReason={prepareReason}
                  submitReason={submitReason}
                  runName={runName}
                  setRunName={setRunName}
                  cpus={cpus}
                  setCpus={setCpus}
                  outputDir={outputDir}
                  setOutputDir={setOutputDir}
                  cap={cap}
                  activeRun={activeRun}
                  readinessError={readinessError}
                  readinessLoading={readinessLoading}
                  onRetry={() => refresh((g) => g + 1)}
                  onPrepare={() => {
                    void execute(async () => {
                      setActionBusy('prepare')
                      try {
                        await prepareDeck()
                      } finally {
                        setActionBusy(null)
                      }
                    })
                  }}
                  onSubmit={() => {
                    void execute(async () => {
                      setActionBusy('submit')
                      try {
                        await submit()
                      } finally {
                        setActionBusy(null)
                      }
                    })
                  }}
                />
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
        {busy || savePhase === 'saving' || savePhase === 'pending' ? (
          <LoaderCircle className="spin" />
        ) : issue || savePhase === 'error' ? (
          <Activity />
        ) : (
          <CheckCheck />
        )}
        <strong>
          {issue
            ? t('status.validation')
            : savePhase === 'error'
              ? t('status.saveFailed')
              : savePhase === 'saving' || savePhase === 'pending'
                ? t('status.saving')
                : locked
                  ? t('status.historical')
                  : t('status.autosaved')}
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
          {meshJob
            ? labelFrom(t, 'phase', (deck ?? meshJob).phase)
            : t('status.localProject')}
        </span>
      </div>
      {fileDialog && (
        <div className="dialog-backdrop" role="presentation">
          <form
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-label={t('file.saveAs')}
            data-testid="save-as-dialog"
            onSubmit={(event) => {
              event.preventDefault()
              commitSaveAs()
            }}
          >
            <h2>{t('file.saveAs')}</h2>
            <p>{t('file.saveAsHelp')}</p>
            <label>
              {t('file.folder')}
              <input
                value={folderDraft}
                placeholder="C:\\models"
                onChange={(event) => setFolderDraft(event.target.value)}
              />
            </label>
            <button type="button" onClick={() => void chooseSaveFolder()}>
              <FolderOpen /> {t('file.browse')}
            </button>
            <label>
              {t('file.fileName')}
              <input
                value={nameDraft}
                maxLength={120}
                onChange={(event) => setNameDraft(event.target.value)}
              />
            </label>
            <div className="row-actions">
              <button type="button" onClick={() => setFileDialog(false)}>
                {t('common.cancel')}
              </button>
              <button
                type="submit"
                className="primary"
                data-testid="save-as-confirm"
                disabled={!folderDraft.trim() || !nameDraft.trim()}
              >
                {t('file.save')}
              </button>
            </div>
          </form>
        </div>
      )}
    </main>
  )
}
