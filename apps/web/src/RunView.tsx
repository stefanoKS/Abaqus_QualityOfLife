import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  Archive,
  CheckCircle2,
  ChevronRight,
  Clock,
  Download,
  FileText,
  Pause,
  Play,
  ScanLine,
  Terminal,
} from 'lucide-react'
import { artifact, displayMetadata, elapsed, err, go, request, type Job, type Revision } from './api'
import { Badge, JobActions } from './Dashboard'
import Viewport from './Viewport'
import type { Picked, ResultFrame, ResultInstance } from './viewportModel'
import {
  materialTopology,
  type MaterialFaceAssignment,
} from './viewportModel'
import {
  contactForceSamples,
  contactForceValues,
  elementDisplayValues,
  misesFrom,
  stressCells,
  type FieldId,
  type StressCell,
} from './features/run/fields'
export type { FieldId } from './features/run/fields'
import { Plot } from './Plot'
import { ProgressSummary } from './features/run/ProgressSummary'
import {
  DEFAULT_STATION_INTERVAL_MM,
  DEFAULT_STROKE_INTERVAL_MM,
  formatNumber,
  loadBasisTag,
  loadOrdinateLabel,
  originalSamples,
  parseSpacing,
  safeName,
  twoRowCsv,
  uniformSamples,
  type Sample,
  type UniformResult,
} from './features/run/export'
import { labelFrom, useI18n, type TranslationKey } from './i18n'
import { ACTIVE_POLL_MS, IDLE_POLL_MS, anyActive } from './shared/hooks/polling'

interface HistoryRow {
  time: number
  step?: string | null
  step_id?: string | null
  displacement: number
  /** Null when the projection needs a component the extractor never measured. */
  force: number | null
  total_force_N?: number | null
  u1?: number | null
  u2?: number | null
  rf1?: number | null
  rf2?: number | null
}

interface Closing {
  panel?: string
  /** User-facing component name/alias captured when the run was extracted. */
  panel_name?: string
  instance?: string
  reference_label?: number
  direction?: number[]
  angle_deg?: number
  distance_mm?: number
  delta_mm?: number[]
  measure_from_step_start?: boolean
  steps?: {
    name: string
    id?: string
    role: string
    instance?: string
    reference_label?: number
    direction?: number[]
    angle_deg?: number
    distance_mm?: number
    delta_mm?: number[]
  }[]
}

interface Index {
  notice: string
  mode: string
  units?: string
  /** A validated partial generation is distinguishable from a complete one. */
  availability?: 'partial' | 'complete'
  solver_outcome?: string
  failure_reason?: string
  history_only?: boolean
  initial_only?: boolean
  frames: {
    time: number
    step?: string
    step_id?: string
    file: string
    frame_ordinal?: number
    native_frame_id?: number | null
    increment?: number | null
    local_time?: number
    total_time?: number
  }[]
  history: HistoryRow[]
  force_unit: string
  instances: ResultInstance[]
  unavailable: string[]
  thickness: number
  thickness_mm?: number
  reporting_width_mm?: number
  reporting_width_basis?: string
  force_basis?: string
  averaging?: string
  force_normalization?: 'total' | 'per_mm'
  closing?: Closing | null
  body?: Closing | null
  door_pressure?: DoorPressureIndex | null
  steps?: {
    name: string
    id?: string
    role: string
    instance?: string
    reference_label?: number
    direction?: number[]
    angle_deg?: number
    distance_mm?: number
    delta_mm?: number[]
    travel_mm?: number
    stroke_mm?: number
  }[]
  history_components?: string[]
}

/** ODB-derived door profile axis, persisted once per result. */
interface DoorProfileDefinition {
  id: string
  instance: string
  component?: string | null
  alias: string
  origin_node: number
  labels: number[]
  stations_mm: number[]
  points_mm: number[][]
  length_mm: number
  topology: string
  supported: boolean
  reason?: string | null
  orientation?: string
  maximum_pressure_kpa?: number
}

interface DoorPressureIndex {
  enabled: boolean
  profiles?: DoorProfileDefinition[]
  instances?: { instance: string; component?: string | null; alias?: string }[]
  native_unit?: string
  display_unit?: string
  conversion?: number
  force_unit?: string
  field_location?: string
  contact_attribution?: { kind?: string; label?: string; basis?: string }
  fields?: { pressure?: string[]; force?: string[] }
  unavailable?: string[]
}

interface DoorProfileFrame {
  supported?: boolean
  reason?: string | null
  /** Instance that owns these node labels; absent on legacy frames. */
  instance?: string | null
  labels?: number[]
  pressure_mpa?: (number | null)[]
  pressure_kpa?: (number | null)[]
  cnormf_n?: ((number[] | null) | null)[]
  force_magnitude_n?: (number | null)[]
  ambiguous?: [number, string, string][]
  availability?: Record<string, string>
}

interface DoorFrame {
  profiles?: Record<string, DoorProfileFrame>
  pressure_domain?: string | null
  force_domain?: string | null
  domains?: { pressure?: string[]; force?: string[] }
  unavailable?: string[]
}

/** Fields the extractor may publish in addition to displacements. */
interface Frame extends ResultFrame {
  fields?: Record<string, unknown>
  unavailable?: string[]
  door_pressure?: DoorFrame | null
}

/** Run-wide display metadata recorded by extraction or derived for a retained run. */
interface DisplayMeta {
  version: number
  bounds: { undeformed: number[]; deformed: number[]; extent: number[] }
  ranges: Partial<
    Record<Component | 'mises' | 'S11' | 'S22' | 'S33' | 'S12' | 'CNormf' | 'pressure', number>
  >
  source: string
}

type Component = 'magnitude' | 'U1' | 'U2' | 'U3'

const COMPONENTS: Component[] = ['magnitude', 'U1', 'U2', 'U3']

type RangeMode = 'fixed' | 'auto' | 'manual'
type RangeKind = 'stress' | 'displacement' | 'contact'
const DEFAULT_RANGE: Record<RangeKind, { min: number; max: number }> = {
  stress: { min: 0, max: 0.5 },
  displacement: { min: 0, max: 5 },
  contact: { min: 0, max: 0.5 },
}
const DEFAULT_DRAFT: Record<RangeKind, { min: string; max: string }> = {
  stress: { min: '0', max: '0.5' },
  displacement: { min: '0', max: '5' },
  contact: { min: '0', max: '0.5' },
}

const STRESS_FIELDS: FieldId[] = ['mises', 'S11', 'S22', 'S33', 'S12']
const DISPLACEMENT_FIELDS: FieldId[] = ['Umag', 'U1', 'U2']
const isStressField = (field: FieldId) => STRESS_FIELDS.includes(field)

/**
 * Display-only sign controls. They transform the projected curve for reading
 * and for the exported CSV; the stored result artifacts are never rewritten.
 */
function displayedCurve(
  history: HistoryRow[],
  reverseX: boolean,
  reverseY: boolean,
  factor = 1,
) {
  return {
    x: history.map((row) => (reverseX ? -row.displacement : row.displacement)),
    // A missing measurement stays a gap: JavaScript's -null would become -0 and
    // silently invent a measured zero. NaN is Plotly's gap marker.
    y: history.map((row) => {
      const force = row.force
      if (force === null || force === undefined || !Number.isFinite(force)) return Number.NaN
      const scaled = force * factor
      return reverseY ? -scaled : scaled
    }),
  }
}

/** Apply the display factor once; an absent measurement stays absent. */
function scaledValue(value: number | null | undefined, factor: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value * factor : null
}

/**
 * One measured load sample per aligned result row.
 *
 * Row 1 of the export is the step-relative displacement magnitude,
 * ``hypot(U1-U1_ref, U2-U2_ref)``, from a valid common reference sample — never
 * the projected travel field. Row 2 is the step-direction projection already
 * normalized by ``align_histories``. Missing components stay null; the display
 * sign is applied exactly once to the force.
 */
function loadExportSamples(rows: HistoryRow[], reverseY: boolean, factor = 1): Sample[] {
  const ordered = [...rows].sort((a, b) => a.time - b.time)
  const finite = (value: unknown): value is number =>
    typeof value === 'number' && Number.isFinite(value)
  const reference = ordered.find((row) => finite(row.u1) && finite(row.u2))
  const referenceU1 = reference && finite(reference.u1) ? reference.u1 : undefined
  const referenceU2 = reference && finite(reference.u2) ? reference.u2 : undefined
  return ordered.map((row) => {
    const x =
      referenceU1 !== undefined &&
      referenceU2 !== undefined &&
      finite(row.u1) &&
      finite(row.u2)
        ? Math.hypot(row.u1 - referenceU1, row.u2 - referenceU2)
        : null
    const y =
      finite(row.force) ? (reverseY ? -row.force : row.force) * factor : null
    return { x, y }
  })
}

function exportUnavailableKey(result: UniformResult | null, spacingOk: boolean) {
  if (!spacingOk) return 'run.exportSpacingInvalid'
  if (!result) return 'run.exportUnavailable'
  if (result.kind === 'invalid') {
    return result.reason === 'too_many'
      ? 'run.exportTooMany'
      : 'run.exportSpacingInvalid'
  }
  if (result.kind === 'ambiguous') {
    return result.reason === 'multivalued'
      ? 'run.exportMultivalued'
      : result.reason === 'unordered'
        ? 'run.exportUnordered'
        : 'run.exportUnavailable'
  }
  return null
}

function sourceLog(job: Job) {
  const preferred = /extract/i.test(job.phase) ? 'extract.log' : 'solver.log'
  return job.manifest.includes(preferred) ? preferred : 'worker.log'
}

function csvCell(value: unknown) {
  const text = value === undefined || value === null ? '' : String(value)
  return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text
}

/** Display-only range endpoint, never a rewrite of a solver value. */
function formatRange(value: number) {
  return Number.isFinite(value) ? String(Number(value.toPrecision(4))) : '—'
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

/** Nearest sample in the same step: a curve point must match its own step, not just a time. */
function nearestIndex<T extends { time: number; step?: string | null; step_id?: string | null }>(
  samples: T[],
  time: number,
  step?: string | null,
  stepName?: string | null,
) {
  if (!samples.length) return 0
  const inStep = (sample: T) =>
    !step ||
    (sample.step_id ? sample.step_id === step : !stepName || sample.step === stepName)
  const eligible = samples
    .map((sample, index) => ({ sample, index }))
    .filter(({ sample }) => inStep(sample))
  const pool = eligible.length
    ? eligible
    : samples.map((sample, index) => ({ sample, index }))
  return pool.reduce(
    (best, entry) =>
      Math.abs(entry.sample.time - time) < Math.abs(best.sample.time - time) ? entry : best,
    pool[0],
  ).index
}



export function RunView({
  id,
  resultView,
  notify,
}: {
  id: string
  resultView: boolean
  notify: (s: string) => void
}) {
  const { t, formatDate } = useI18n()
  const [job, setJob] = useState<Job | null>(null),
    [tick, refresh] = useState(0),
    [index, setIndex] = useState<Index | null>(null),
    [indexGeneration, setIndexGeneration] = useState(-1)
  const [n, setN] = useState(0),
    [frame, setFrame] = useState<Frame | null>(null),
    [play, playing] = useState(false)
  const [sel, select] = useState<Picked | null>(null),
    [mode, setMode] = useState<'node' | 'element'>('node'),
    [deformed, deform] = useState(true)
  const [field, setField] = useState<FieldId>('Umag')
  // Displacement and stress keep independent range state: a display choice for
  // one quantity must not rewrite the other's limits.
  const [rangeModes, setRangeModes] = useState<Record<RangeKind, RangeMode>>({
    stress: 'fixed',
    displacement: 'fixed',
    contact: 'fixed',
  })
  const [rangeDrafts, setRangeDrafts] =
    useState<Record<RangeKind, { min: string; max: string }>>(DEFAULT_DRAFT)
  const [rangeLimits, setRangeLimits] =
    useState<Record<RangeKind, { min: number; max: number }>>(DEFAULT_RANGE)
  const [loop, setLoop] = useState(true)
  // Independent display toggles. They never touch the solver artifacts.
  const [edges, setEdges] = useState(true)
  const [markers, setMarkers] = useState(false)
  // Display preference only, default off; it never rewrites solver evidence.
  const [materialOutlines, setMaterialOutlines] = useState(false)
  const [deformationScale, setDeformationScale] = useState(1)
  const [scaleDraft, setScaleDraft] = useState('1')
  const [displayedFrame, setDisplayedFrame] = useState<number | null>(null)
  const [pendingFrame, setPendingFrame] = useState<number | null>(null)
  const [frameError, setFrameError] = useState<number | null>(null)
  const [displayMeta, setDisplayMeta] = useState<DisplayMeta | null>(null)
  const frameCache = useRef(new Map<string, Frame>())
  const [setup, setSetup] = useState<Revision['setup'] | null>(null)
  const [now, setNow] = useState(() => Date.now() / 1000)
  const [logs, setLogs] = useState(''),
    [logFile, setLogFile] = useState('worker.log')
  // Display-only sign controls; the artifacts on disk keep their signed values.
  const [reverseX, setReverseX] = useState(false),
    [reverseY, setReverseY] = useState(false)
  // Door-panel pressure view state. The profile axis is fixed per result; the
  // arrows and the spatial graph always read the displayed frame's arrays.
  const [pressureProfile, setPressureProfile] = useState<string | null>(null)
  const [showPressureArrows, setShowPressureArrows] = useState(true)
  const [pressureSelected, setPressureSelected] = useState<number | null>(null)
  const [pressureHover, setPressureHover] = useState<number | null>(null)
  // Two-row export controls. The interval is user-editable and independent per
  // graph; the defaults match the accepted load (1.0 mm) and door-pressure
  // station (1.3 mm) contracts. Uniform grids can be replaced by the original
  // ordered samples when a curve is multivalued.
  const [strokeInterval, setStrokeInterval] = useState(String(DEFAULT_STROKE_INTERVAL_MM))
  const [stationInterval, setStationInterval] = useState(String(DEFAULT_STATION_INTERVAL_MM))
  const [loadExportMode, setLoadExportMode] = useState<'uniform' | 'original'>('uniform')
  const [pressureExportMode, setPressureExportMode] = useState<'uniform' | 'original'>(
    'uniform',
  )
  // One dimensionless display factor for engineering responses. It is separate
  // from geometric deformation exaggeration and from the reporting width; the
  // stored measurements are never rewritten.
  const [multiplier, setMultiplier] = useState(1)
  const [multiplierDraft, setMultiplierDraft] = useState('1')
  const [multiplierError, setMultiplierError] = useState(false)
  // Pressure-arrow calibration: Automatic screen size is the initial mode;
  // Manual keeps its own last valid model-space calibration per open result.
  const [arrowMode, setArrowMode] = useState<'auto' | 'manual'>('auto')
  const [manualMm, setManualMm] = useState('5')
  const [manualMmValue, setManualMmValue] = useState(5)
  const [manualMmError, setManualMmError] = useState(false)
  const active = !!job && anyActive([job])
  const resultInfo = (job?.result ?? {}) as {
    state?: string
    available?: boolean
    summary?: Record<string, unknown>
    generation?: number
  }
  const resultGeneration = Number(resultInfo.generation || 0)
  const resultGenerationRef = useRef(resultGeneration)
  resultGenerationRef.current = resultGeneration
  const artifactUrl = (name: string) =>
    artifact(
      id,
      name,
      /^(results\.json|history\.csv|frame-\d+\.json)$/.test(name) ? resultGeneration : 0,
    )
  const resultSummary = resultInfo.summary ?? {}
  const resultOpen = !!job && (job.status === 'Completed' || resultInfo.available === true)
  const resultPartial = resultOpen && resultInfo.state === 'partial'
  useEffect(() => {
    const ctrl = new AbortController()
    const poll = () =>
      request<Job>('/api/jobs/' + id, 'GET', undefined, ctrl.signal)
        .then(setJob)
        .catch((e) => {
          if (!ctrl.signal.aborted) notify(err(e))
        })
    void poll()
    // Keep watching a live job closely; a finished job only needs an occasional
    // refresh so a retry started elsewhere still appears.
    const timer = setInterval(poll, active ? ACTIVE_POLL_MS : IDLE_POLL_MS)
    return () => {
      ctrl.abort()
      clearInterval(timer)
    }
  }, [id, tick, notify, active])
  // Configured step durations come from the exact revision the job ran, so a
  // later edit cannot change this run's progress denominator.
  useEffect(() => {
    if (!job) return
    const ac = new AbortController()
    request<Revision>('/api/revisions/' + job.revision, 'GET', undefined, ac.signal)
      .then((revision) => setSetup(revision.setup))
      .catch(() => {
        if (!ac.signal.aborted) setSetup(null)
      })
    return () => ac.abort()
  }, [job?.revision])
  // Re-evaluate the stale-heartbeat warning without re-fetching the job.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), 5000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => {
    if (!resultView || !resultOpen) return
    const ac = new AbortController()
    request<Index>(artifact(id, 'results.json', resultGeneration), 'GET', undefined, ac.signal)
      .then((payload) => {
        setIndex(payload)
        setIndexGeneration(resultGeneration)
      })
      .catch((e) => {
        if (!ac.signal.aborted) notify(err(e))
      })
    return () => ac.abort()
  }, [resultOpen, resultView, id, notify, resultInfo.generation])
  // Run-wide bounds and colour ranges, recorded by extraction or derived once
  // server-side for a retained result. They never change during playback.
  useEffect(() => {
    if (!resultView || !resultOpen) return
    const ac = new AbortController()
    request<DisplayMeta>(displayMetadata(id, resultGeneration), 'GET', undefined, ac.signal)
      .then(setDisplayMeta)
      .catch((e) => {
        // A missing derived metadata must not hide the geometry; the viewport
        // then uses a bounded fallback and says the range is derived.
        if (!ac.signal.aborted) {
          setDisplayMeta(null)
          notify(err(e))
        }
      })
    return () => ac.abort()
  }, [resultOpen, resultView, id, notify, resultInfo.generation])
  // A new run starts from a clean frame state: no old probe, frame or camera key.
  useEffect(() => {
    frameCache.current.clear()
    setFrame(null)
    setDisplayedFrame(null)
    setPendingFrame(null)
    setFrameError(null)
    setDisplayMeta(null)
    setIndex(null)
    // A newly opened result starts at ×1 and Automatic arrows, including a
    // portable file reopened under a new job identity.
    setMultiplier(1)
    setMultiplierDraft('1')
    setMultiplierError(false)
    setArrowMode('auto')
    setManualMm('5')
    setManualMmError(false)
    setReverseX(false)
    setReverseY(false)
  }, [id])
  // Only the newest request may commit. The last complete frame stays on screen
  // while the next one loads, so playback never blanks the viewport.
  const frameRequest = useRef(0)
  const generation = useRef(0)
  const deadline = useRef(0)
  const inflight = useRef(new Map<string, Promise<Frame>>())
  const CACHE_LIMIT = 96
  const READ_AHEAD = 6
  const CADENCE_MS = 220
  const loadFrame = useCallback(
    (file: string): Promise<Frame> => {
      // The cache key and URL carry the generation: a retry can never serve a
      // frame from the previous generation under the same file name.
      const gen = resultGenerationRef.current
      const key = gen + ':' + file
      const cached = frameCache.current.get(key)
      if (cached) {
        // Refresh LRU position: replaying a nearby frame stays cheap.
        frameCache.current.delete(key)
        frameCache.current.set(key, cached)
        return Promise.resolve(cached)
      }
      const queued = inflight.current.get(key)
      if (queued) return queued
      const load = request<Frame>(artifact(id, file, gen), 'GET')
        .then((loaded) => {
          // Discard an out-of-order completion from a superseded generation.
          if (gen === resultGenerationRef.current) {
            frameCache.current.set(key, loaded)
            while (frameCache.current.size > CACHE_LIMIT) {
              const oldest = frameCache.current.keys().next().value
              if (!oldest) break
              frameCache.current.delete(oldest)
            }
          }
          inflight.current.delete(key)
          return loaded
        })
        .catch((error) => {
          inflight.current.delete(key)
          throw error
        })
      inflight.current.set(key, load)
      return load
    },
    [id],
  )
  useEffect(() => {
    if (!index || indexGeneration !== resultGeneration) return
    const target = index.frames[n]
    if (!target) return
    const sequence = ++frameRequest.current
    const cached = frameCache.current.get(resultGeneration + ':' + target.file)
    if (cached) {
      setFrame(cached)
      setDisplayedFrame(n)
      setFrameError(null)
      setPendingFrame(null)
      return
    }
    setPendingFrame(n)
    loadFrame(target.file)
      .then((loaded) => {
        if (sequence !== frameRequest.current) return
        setFrame(loaded)
        setDisplayedFrame(n)
        setFrameError(null)
        setPendingFrame(null)
      })
      .catch((error) => {
        if (sequence !== frameRequest.current) return
        // Keep the last good frame visible and say which one failed.
        setFrameError(n)
        setPendingFrame(null)
        playing(false)
        deadline.current = 0
        notify(err(error))
      })
  }, [index, n, loadFrame, notify, resultGeneration, indexGeneration])
  // Bounded read-ahead: upcoming frames (including the loop boundary) are
  // fetched while the current one is displayed. Requests are deduplicated and
  // the cache never exceeds its limit, so scrubbing cannot runaway.
  useEffect(() => {
    if (!play || !index || indexGeneration !== resultGeneration || displayedFrame === null) return
    const total = index.frames.length
    if (total <= 1) return
    for (let step = 1; step <= READ_AHEAD; step++) {
      const upcoming = index.frames[(displayedFrame + step) % total]
      if (!upcoming) continue
      void loadFrame(upcoming.file).catch(() => {
        // Prefetch failures are silent; the request on demand reports them.
      })
    }
  }, [play, index, displayedFrame, loadFrame, indexGeneration, resultGeneration])
  // A new run or a deliberate seek restarts the cadence cleanly.
  useEffect(() => {
    generation.current += 1
    deadline.current = 0
  }, [id, n])
  // Monotonic per-frame deadlines. The timer arms only once the requested frame
  // is on screen, so a slow frame holds the last image and then resumes without
  // a catch-up burst or duplicate advance.
  useEffect(() => {
    if (!play || !index || index.frames.length <= 1) return
    if (displayedFrame !== n) return
    const last = index.frames.length - 1
    if (n >= last && !loop) {
      playing(false)
      deadline.current = 0
      return
    }
    const now = performance.now()
    if (!deadline.current) deadline.current = now + CADENCE_MS
    const target = Math.max(now, deadline.current)
    const wait = Math.max(0, target - now)
    const timer = setTimeout(() => {
      deadline.current = target + CADENCE_MS
      setN(n >= last ? 0 : n + 1)
    }, wait)
    return () => clearTimeout(timer)
  }, [play, n, index, displayedFrame, loop])
  const hasLog = job?.manifest.includes(logFile)
  useEffect(() => {
    if (resultView || !hasLog) {
      setLogs('')
      return
    }
    const ac = new AbortController()
    const poll = () =>
      request<{ text: string }>('/api/jobs/' + id + '/tail/' + logFile, 'GET', undefined, ac.signal)
        .then((data) => setLogs(data.text))
        .catch((e) => {
          if (!ac.signal.aborted) notify(err(e))
        })
    void poll()
    const t2 = setInterval(poll, 2000)
    return () => {
      clearInterval(t2)
      ac.abort()
    }
  }, [resultView, id, hasLog, logFile, notify])
  // Two-step runs open on the door-closing step, not the body-seating step.
  const closingStepEntry =
    index?.steps?.find((step) => step.role === 'door') ??
    index?.closing?.steps?.find((step) => step.role === 'door') ??
    index?.steps?.[0] ??
    index?.closing?.steps?.[0] ??
    null
  const closingStepId = closingStepEntry?.id ?? closingStepEntry?.name ?? null
  const closingStepName = closingStepEntry?.name ?? null
  const frameRestored = useRef(false)
  const curveRestored = useRef(false)
  useEffect(() => {
    frameRestored.current = false
    curveRestored.current = false
  }, [id, resultGeneration])
  // A retry publishes a new generation: discard every cached frame and any
  // selected point so nothing from the previous generation is shown under the
  // new index. Display preferences (multiplier, arrows, ranges) stay as set.
  const seenGeneration = useRef(resultGeneration)
  useEffect(() => {
    if (seenGeneration.current === resultGeneration) return
    seenGeneration.current = resultGeneration
    frameCache.current.clear()
    inflight.current.clear()
    frameRequest.current += 1
    setFrame(null)
    setDisplayedFrame(null)
    setPendingFrame(null)
    setFrameError(null)
    setDisplayMeta(null)
    setIndex(null)
    setIndexGeneration(-1)
    select(null)
    setPressureSelected(null)
    setPressureHover(null)
  }, [resultGeneration])
  // A partial result lands paused on its last readable saved frame. A completed
  // result keeps its established door-closing opening. Either choice survives
  // Diagnostics, delayed requests and polling refreshes for this result.
  useEffect(() => {
    if (!index || indexGeneration !== resultGeneration || frameRestored.current) return
    frameRestored.current = true
    try {
      const saved = window.sessionStorage.getItem('aqol.frame.' + id)
      const previous = saved === null ? Number.NaN : Number(saved)
      if (
        Number.isInteger(previous) &&
        previous >= 0 &&
        previous < index.frames.length
      ) {
        setN(previous)
        return
      }
    } catch {
      // A denied storage API only loses the restored position.
    }
    if (index.availability === 'partial') {
      setN(Math.max(0, index.frames.length - 1))
      return
    }
    const first = index.frames.findIndex(
      (frame) =>
        !closingStepId ||
        (frame.step_id ? frame.step_id === closingStepId : frame.step === closingStepName),
    )
    setN(Math.max(0, first))
  }, [index, closingStepId, closingStepName, id, indexGeneration, resultGeneration])
  useEffect(() => {
    if (!index) return
    try {
      window.sessionStorage.setItem('aqol.frame.' + id, String(n))
    } catch {
      // Position persistence is a convenience only.
    }
  }, [id, n, index])
  const [curveStep, setCurveStep] = useState<string | null>(null)
  const stepOptions = index?.steps?.length
    ? index.steps
    : (index?.closing?.steps ?? [])
  useEffect(() => {
    if (!index || indexGeneration !== resultGeneration || curveRestored.current) return
    curveRestored.current = true
    try {
      const saved = window.sessionStorage.getItem('aqol.step.' + id)
      if (saved && stepOptions.some((step) => (step.id ?? step.name) === saved)) {
        setCurveStep(saved)
        return
      }
    } catch {
      // Ignore denied storage.
    }
    // A history-only result has no frame cursor. Open the latest step that
    // actually carries measured history; never borrow the planned Closing step.
    if (!index.frames.length) {
      const rows = index.history ?? []
      const last = rows[rows.length - 1]
      const entry = last
        ? stepOptions.find(
            (step) => (step.id ?? step.name) === (last.step_id ?? last.step),
          )
        : undefined
      if (entry) {
        setCurveStep(entry.id ?? entry.name)
        return
      }
    }
    // A partial result opens on the step that owns the displayed last frame; a
    // planned step that never ran is not selected as if it had data.
    if (index.availability === 'partial' && index.frames.length) {
      const last = index.frames[index.frames.length - 1]
      const entry = stepOptions.find(
        (step) => (step.id ?? step.name) === (last.step_id ?? last.step),
      )
      if (entry) {
        setCurveStep(entry.id ?? entry.name)
        return
      }
    }
    const preferred = stepOptions.find((step) => step.role === 'door') ?? stepOptions[stepOptions.length - 1]
    setCurveStep(preferred ? (preferred.id ?? preferred.name) : null)
  }, [index, id, stepOptions, indexGeneration, resultGeneration])
  useEffect(() => {
    if (!curveStep) return
    try {
      window.sessionStorage.setItem('aqol.step.' + id, curveStep)
    } catch {
      // Ignore denied storage.
    }
  }, [id, curveStep])
  const curveStepEntry = stepOptions.find(
    (step) => (step.id ?? step.name) === curveStep,
  )
  const curveStepName = curveStepEntry?.name ?? curveStep
  const stepRole = curveStepEntry?.role
  // The readout follows the SELECTED step. It must never display the closing
  // door direction while Body seating is on screen.
  const stepBlock = stepRole === 'body' ? index?.body : index?.closing
  const stepDirection = curveStepEntry?.direction ?? stepBlock?.direction ?? null
  const stepAngle = curveStepEntry?.angle_deg ?? stepBlock?.angle_deg
  const stepReference =
    curveStepEntry?.reference_label ??
    (stepRole === 'body' ? index?.body?.reference_label : index?.closing?.reference_label)
  const stepInstance =
    curveStepEntry?.instance ?? (stepRole === 'body' ? 'BODY-1' : 'PANEL-1')
  const stepProvenance = curveStepEntry
    ? 'step'
    : stepBlock
      ? 'legacy'
      : 'unknown'
  const forceBasisText =
    index?.reporting_width_basis === 'legacy_thickness' || index?.force_basis === 'legacy_unscaled'
      ? t('run.forceBasisLegacy')
      : index?.force_normalization === 'per_mm'
        ? t('run.forceBasisPerMm', {
            thickness: String(index.thickness_mm ?? index.thickness),
          })
        : t('run.forceBasisTotal', {
            width: String(index?.reporting_width_mm ?? index?.thickness ?? '—'),
            thickness: String(index?.thickness_mm ?? index?.thickness ?? '—'),
          })
  /**
   * Full engineering description versus the short axis titles.
   *
   * The rotated Y title used to contain the whole phrase ("Door panel reaction
   * along closing direction (N)"). Rotated 90 degrees it needed about 269 px of
   * height inside a 210 px plot, so it was clipped above and below the SVG at
   * every window width. The full phrase now lives in a wrapping semantic caption
   * next to the plot and the axes keep a concise, unit-bearing title that really
   * fits. The plotted series, zoom, picking and the exported two-row CSV are
   * unchanged by this layout decision.
   */
  const forceUnit = index?.force_unit ?? 'N'
  const factorTag = multiplier === 1 ? '' : ' ×' + formatNumber(multiplier)
  const travelAxisLabel =
    stepRole === 'body'
      ? t('run.bodyTravel')
      : index?.closing
        ? t('run.doorTravel')
        : t('run.panelU2')
  const forceAxisLabel =
    (stepRole === 'body'
      ? t('run.bodyReaction', { unit: forceUnit })
      : index?.closing && stepProvenance !== 'unknown'
        ? t('run.doorReaction', { unit: forceUnit })
        : stepDirection
          ? t('run.projectedReaction', { unit: forceUnit })
          : t('run.panelRF2', { unit: forceUnit })) + factorTag
  const shortTravelAxis = t('run.displacementAxis')
  const shortForceAxis = t('run.forceAxis', { unit: forceUnit }) + factorTag
  const plotDescription = `${travelAxisLabel} · ${forceAxisLabel}`
  const historyRows = useMemo(
    () =>
      curveStep
        ? (index?.history ?? []).filter((row) =>
            row.step_id ? row.step_id === curveStep : row.step === curveStepName,
          )
        : (index?.history ?? []),
    [index, curveStep, curveStepName],
  )
  const curve = useMemo(
    () => displayedCurve(historyRows, reverseX, reverseY, multiplier),
    [historyRows, reverseX, reverseY, multiplier],
  )
  // Load export: one measured sample per aligned row, then an optional uniform
  // stroke grid or the original acquisition-ordered samples. Reverse X is a
  // display choice for the chart only; the exported stroke stays positive.
  const loadSamples = useMemo(
    () => loadExportSamples(historyRows, reverseY, multiplier),
    [historyRows, reverseY, multiplier],
  )
  const loadSpacing = parseSpacing(strokeInterval)
  const loadSpacingValue = loadSpacing.ok ? loadSpacing.value : 0
  const loadGrid = useMemo<UniformResult | null>(
    () => (loadSpacingValue > 0 ? uniformSamples(loadSamples, loadSpacingValue) : null),
    [loadSamples, loadSpacingValue],
  )
  const loadExportPoints =
    loadExportMode === 'original'
      ? originalSamples(loadSamples)
      : loadGrid?.kind === 'ok'
        ? loadGrid.points
        : []
  const loadExportIssue =
    loadExportMode === 'original'
      ? loadExportPoints.length
        ? null
        : 'run.exportUnavailable'
      : exportUnavailableKey(loadGrid, loadSpacing.ok) ??
        (loadExportPoints.length ? null : 'run.exportUnavailable')
  const loadOrdinate = loadOrdinateLabel(index ?? {})
  const loadBasis = loadBasisTag(index ?? {})
  // The frame identity that is actually on screen, not the one being requested.
  const shownFrame = displayedFrame ?? n
  const shownEntry = index?.frames[shownFrame]
  const frameStep = shownEntry?.step
  const activeSample =
    index && shownEntry
      ? nearestIndex(
          historyRows,
          shownEntry.time,
          shownEntry.step_id ?? shownEntry.step,
          shownEntry.step,
        )
      : undefined
  const stressAvailable = !!displayMeta && displayMeta.ranges.mises !== undefined
  const contactAvailable = !!displayMeta && displayMeta.ranges.CNormf !== undefined
  const fieldIsContact = field === 'CNormf'
  const contactSamples = useMemo(() => contactForceSamples(frame), [frame])
  const contactValues = useMemo(() => contactForceValues(contactSamples), [contactSamples])
  // The contour and the probe read the same displayed magnitude. The stored
  // signed components remain in `contactSamples`; the factor is applied once.
  const contactDisplayValues = useMemo(() => {
    const values: Record<string, Record<number, number>> = {}
    for (const [instance, nodes] of Object.entries(contactValues)) {
      values[instance] = {}
      for (const [node, value] of Object.entries(nodes)) values[instance][Number(node)] = value * multiplier
    }
    return values
  }, [contactValues, multiplier])
  // Default to von Mises with element probing whenever the run carries stress.
  useEffect(() => {
    if (!displayMeta) return
    const stress = displayMeta.ranges.mises !== undefined
    setField(stress ? 'mises' : 'Umag')
    setMode(stress ? 'element' : 'node')
    select(null)
  }, [displayMeta])
  const fieldIsStress = isStressField(field)
  useEffect(() => {
    setMode(fieldIsStress ? 'element' : 'node')
    select(null)
  }, [fieldIsStress])
  const stressSampleCells = useMemo(
    () => (fieldIsStress ? stressCells(frame, field) : new Map<string, StressCell>()),
    [fieldIsStress, frame, field],
  )
  const elementValues = useMemo(
    () => (fieldIsStress ? elementDisplayValues(stressSampleCells, field) : undefined),
    [fieldIsStress, stressSampleCells, field],
  )
  const displayElementValues = useMemo(() => {
    if (!elementValues) return undefined
    const values: Record<string, Record<number, number>> = {}
    for (const [instance, cells] of Object.entries(elementValues)) {
      values[instance] = {}
      for (const [element, value] of Object.entries(cells)) {
        values[instance][Number(element)] = value * multiplier
      }
    }
    return values
  }, [elementValues, multiplier])
  // Face-to-material assignments, names and colours come from the job's
  // immutable submitted revision, never from a later editable head. The key is
  // the effective pinned card identity, so two distinct CAD faces that share a
  // material (or a pinned library version) can never create a false interface.
  const faceMaterials = useMemo(() => {
    const map: Record<string, MaterialFaceAssignment> = {}
    // A diagnostics response for a synthetic route may carry only the motion
    // subset of a revision; material overlays then simply stay unavailable.
    if (!setup?.materials || !setup?.faces) return map
    const cards = new Map(setup.materials.map((card) => [card.id, card]))
    for (const face of setup.faces) {
      const card = face.material ? cards.get(face.material) : undefined
      if (!card) continue
      map[face.id] = {
        key: card.library_id
          ? card.library_id + '@' + (card.library_version ?? 0)
          : 'card:' + card.id,
        name: card.name,
        color: card.color,
        version: card.library_version ?? card.version,
      }
    }
    return map
  }, [setup])
  // Edge adjacency is built once per result topology and pinned material map.
  const materialInfo = useMemo(
    () => materialTopology(index?.instances, faceMaterials),
    [index?.instances, faceMaterials],
  )
  const materialLegend = useMemo(() => {
    const seen = new Set<string>()
    const rows: { key: string; name: string; color: string; version?: number | null }[] = []
    for (const face of setup?.faces ?? []) {
      const entry = faceMaterials[face.id]
      if (!entry || seen.has(entry.key)) continue
      seen.add(entry.key)
      rows.push({ ...entry })
    }
    return rows
  }, [setup, faceMaterials])
  const displacementKey: Component =
    field === 'U1' ? 'U1' : field === 'U2' ? 'U2' : 'magnitude'
  const rangeKey: Component | 'mises' | 'S11' | 'S22' | 'S33' | 'S12' | 'CNormf' =
    fieldIsContact
      ? 'CNormf'
      : fieldIsStress
        ? field === 'mises'
          ? 'mises'
          : (field as 'S11' | 'S22' | 'S33' | 'S12')
        : displacementKey
  const autoRange = displayMeta ? (displayMeta.ranges[rangeKey] ?? null) : undefined
  const rangeKind: RangeKind = fieldIsContact
    ? 'contact'
    : fieldIsStress
      ? 'stress'
      : 'displacement'
  const rangeMode = rangeModes[rangeKind]
  const manual = rangeDrafts[rangeKind]
  const limits = rangeLimits[rangeKind]
  const fallback = DEFAULT_RANGE[rangeKind]
  // A fixed range is a display choice. Auto follows the run-wide measured
  // maximum for the selected quantity; manual uses the last valid applied pair.
  const effectiveMax =
    rangeMode === 'fixed'
      ? fallback.max
      : rangeMode === 'auto'
        ? (autoRange ?? fallback.max)
        : limits.max
  const effectiveMin = rangeMode === 'manual' ? limits.min : fallback.min
  const resultRange = effectiveMax
  // A quantity recorded as absent must stay visibly unavailable: a manual range
  // cannot invent solver evidence.
  const rangeUnavailable =
    displayMeta !== null && displayMeta.ranges[rangeKey] === undefined
  const unit = fieldIsContact
    ? 'N'
    : fieldIsStress
      ? index?.units === 'N-mm-s-tonne'
        ? 'MPa'
        : t('run.unitUnknown')
      : 'mm'
  const fieldLabel = t(('run.field.' + field) as TranslationKey)
  // Scalar values actually drawn: magnitudes for displacement, max-IP values
  // for stress, |CNORMF| for contact force. Probe readings stay unclipped.
  const displayValues = useMemo(() => {
    if (fieldIsContact)
      return Object.values(contactDisplayValues).flatMap((values) => Object.values(values))
    if (fieldIsStress)
      return Object.values(displayElementValues ?? {}).flatMap((values) => Object.values(values))
    if (!frame) return []
    const axis = displacementKey === 'U1' ? 0 : displacementKey === 'U2' ? 1 : -1
    const values: number[] = []
    for (const rows of Object.values(frame.displacements ?? {}))
      for (const row of rows) {
        const u = row.slice(1)
        const value = axis < 0 ? Math.hypot(...u) : Math.abs(u[axis] ?? 0)
        if (Number.isFinite(value)) values.push(value)
      }
    return values
  }, [fieldIsContact, contactDisplayValues, fieldIsStress, displayElementValues, frame, displacementKey])
  let frameMax = 0
  let frameMin = 0
  for (const value of displayValues) {
    if (value > frameMax) frameMax = value
    if (value < frameMin) frameMin = value
  }
  const saturated =
    !rangeUnavailable && resultRange != null && frameMax > resultRange + 1e-12
  const underflow =
    !rangeUnavailable && effectiveMin > 0 && frameMin < effectiveMin - 1e-12
  const manualMin = Number(manual.min),
    manualMax = Number(manual.max)
  const manualBlank = manual.min.trim() === '' || manual.max.trim() === ''
  const manualInvalid =
    rangeMode === 'manual' &&
    (manualBlank || !Number.isFinite(manualMin) || !Number.isFinite(manualMax) || manualMax <= manualMin)
  const stressOptions = STRESS_FIELDS.filter((option) => {
    const key = (option === 'mises' ? 'mises' : option) as
      | 'mises'
      | 'S11'
      | 'S22'
      | 'S33'
      | 'S12'
    return displayMeta?.ranges[key] !== undefined
  })
  const fieldOptions: FieldId[] = [
    ...(stressAvailable ? stressOptions : []),
    ...(contactAvailable ? (['CNormf'] as FieldId[]) : []),
    ...DISPLACEMENT_FIELDS,
  ]
  // --- Door-panel contact pressure -----------------------------------------
  const doorIndex = index?.door_pressure ?? null
  const doorProfiles = useMemo(
    () =>
      (doorIndex?.profiles ?? []).filter(
        (entry) => entry.supported && (entry.labels?.length ?? 0) > 0,
      ),
    [doorIndex],
  )
  // Persisted orientation: choosing a profile never re-derives its axis. The
  // default is the profile with the largest run-wide measured pressure.
  useEffect(() => {
    if (!doorProfiles.length) {
      setPressureProfile(null)
      return
    }
    setPressureProfile((current) =>
      doorProfiles.some((entry) => entry.id === current)
        ? current
        : [...doorProfiles].sort(
            (a, b) => (b.maximum_pressure_kpa ?? 0) - (a.maximum_pressure_kpa ?? 0),
          )[0].id,
    )
  }, [doorProfiles])
  const pressureEntry =
    doorProfiles.find((entry) => entry.id === pressureProfile) ?? doorProfiles[0] ?? null
  useEffect(() => {
    setPressureSelected(null)
    setPressureHover(null)
  }, [pressureEntry?.id])
  const pressureFrame = frame?.door_pressure ?? null
  const pressureData = pressureEntry
    ? (pressureFrame?.profiles?.[pressureEntry.id] ?? null)
    : null
  // Native sample order is not necessarily the profile station order. Map every
  // consumer (chart, arrows, probe, CSV) through one identity join; a clean
  // permutation is reversible, while duplicates, unknown labels or a wrong
  // instance suppress the spatial values instead of shifting them.
  const pressureMapping = useMemo(() => {
    if (!pressureEntry || !pressureData) {
      return { ok: false as const, reason: 'profile_missing', positions: [] as number[] }
    }
    if (pressureData.instance && pressureData.instance !== pressureEntry.instance) {
      return { ok: false as const, reason: 'wrong_instance', positions: [] as number[] }
    }
    const profileLabels = pressureEntry.labels ?? []
    const labels = pressureData.labels
    if (!Array.isArray(labels)) {
      return { ok: false as const, reason: 'labels_missing', positions: [] as number[] }
    }
    if (labels.length !== profileLabels.length) {
      return { ok: false as const, reason: 'label_count_mismatch', positions: [] as number[] }
    }
    const positions = new Map<number, number>()
    for (const [index, label] of labels.entries()) {
      const key = Number(label)
      if (!Number.isFinite(key) || positions.has(key)) {
        return { ok: false as const, reason: 'duplicate_node', positions: [] as number[] }
      }
      positions.set(key, index)
    }
    const mapped = profileLabels.map((label) => positions.get(Number(label)))
    if (mapped.some((position) => position === undefined)) {
      return { ok: false as const, reason: 'unknown_node', positions: [] as number[] }
    }
    const arrays = [
      pressureData.pressure_kpa,
      pressureData.pressure_mpa,
      pressureData.cnormf_n,
    ]
    if (arrays.some((values) => Array.isArray(values) && values.length !== labels.length)) {
      return { ok: false as const, reason: 'array_length_mismatch', positions: [] as number[] }
    }
    return { ok: true as const, reason: '', positions: mapped as number[] }
  }, [pressureEntry, pressureData])
  const pressureAt = (position: number) =>
    pressureMapping.ok ? pressureMapping.positions[position] : undefined
  const displacementByLabel = useMemo(() => {
    const rows = pressureEntry ? (frame?.displacements?.[pressureEntry.instance] ?? []) : []
    return new Map(rows.map((row) => [row[0], row.slice(1)]))
  }, [frame, pressureEntry?.instance])
  const pressureRows = useMemo(() => {
    if (!pressureEntry) return []
    const scale = deformed ? deformationScale : 0
    return (pressureEntry.labels ?? []).map((label, position) => {
      const xy = pressureEntry.points_mm?.[position] ?? null
      const u = displacementByLabel.get(label)
      // A deformed arrow needs an identifiable measured displacement for THIS
      // node. Falling back to zero would draw the undeformed anchor as if it
      // were deformed, so the anchor is withheld instead.
      const anchor = xy
        ? deformed && !u
          ? null
          : ([
              xy[0] + (u?.[0] ?? 0) * scale,
              xy[1] + (u?.[1] ?? 0) * scale,
            ] as [number, number])
        : null
      const source = pressureAt(position)
      const rawPressure =
        source === undefined ? null : (pressureData?.pressure_kpa?.[source] ?? null)
      const native =
        source === undefined ? null : (pressureData?.pressure_mpa?.[source] ?? null)
      const rawForce =
        source === undefined ? null : (pressureData?.cnormf_n?.[source] ?? null)
      // The display factor is applied exactly once to the engineering response;
      // the recorded native values stay available for the readout.
      const force =
        rawForce === null || rawForce === undefined
          ? null
          : rawForce.map((component) => Number(component) * multiplier)
      const magnitude = force ? Math.hypot(...force) : 0
      const rawMagnitude = rawForce ? Math.hypot(...rawForce) : 0
      const stationValue = pressureEntry.stations_mm?.[position]
      return {
        label,
        station:
          typeof stationValue === 'number' && Number.isFinite(stationValue)
            ? stationValue
            : null,
        pressure: scaledValue(rawPressure, multiplier),
        rawPressure,
        native,
        force,
        rawForce,
        magnitude,
        anchor,
        direction:
          rawForce && rawMagnitude > 1e-12
            ? ([rawForce[0] / rawMagnitude, rawForce[1] / rawMagnitude] as [
                number,
                number,
              ])
            : null,
      }
    })
  }, [pressureEntry, pressureData, displacementByLabel, deformed, deformationScale, multiplier])
  const pressureMaximum = useMemo(() => {
    const recorded = displayMeta?.ranges.pressure
    if (typeof recorded === 'number' && recorded > 0) return recorded
    return pressureRows.reduce(
      (largest, row) =>
        row.rawPressure === null
          ? largest
          : Math.max(largest, Math.abs(row.rawPressure)),
      0,
    )
  }, [displayMeta?.ranges.pressure, pressureRows])
  const displayedPressureMaximum = pressureMaximum * multiplier
  const pressureStationsOk =
    !!pressureEntry &&
    Array.isArray(pressureEntry.stations_mm) &&
    pressureEntry.stations_mm.length === pressureEntry.labels.length &&
    pressureEntry.stations_mm.every(
      (value, index, values) =>
        typeof value === 'number' &&
        Number.isFinite(value) &&
        (index === 0 || value >= values[index - 1]),
    )
  const pressurePointsOk =
    !!pressureEntry &&
    (!pressureEntry.points_mm ||
      (pressureEntry.points_mm.length === pressureEntry.labels.length &&
        pressureEntry.points_mm.every(
          (point) =>
            Array.isArray(point) &&
            point.length >= 2 &&
            point.slice(0, 2).every((value) => Number.isFinite(value)),
        )))
  const pressureArrows = useMemo(() => {
    if (!pressureEntry) return null
    // Spatial arrows need a valid station axis and finite profile anchors; an
    // invalid order or a short point list suppresses the glyphs rather than
    // drawing a misleading direction.
    if (!pressureStationsOk || !pressurePointsOk) return null
    const arrows = pressureRows.flatMap((row, rowIndex) =>
      row.anchor && row.direction && row.pressure !== null && Math.abs(row.pressure) > 0
        ? [
            {
              anchor: row.anchor,
              direction: row.direction,
              // The glyph length reads the displayed (multiplied) pressure; its
              // automatic denominator stays the unscaled run reference.
              pressureKpa: row.pressure,
              station: row.station ?? 0,
              node: row.label,
              row: rowIndex,
            },
          ]
        : [],
    )
    const first = pressureRows[0]
    const second = pressureRows[1]
    let hint: [number, number] | null = null
    if (first?.anchor && second?.anchor) {
      const dx = second.anchor[0] - first.anchor[0]
      const dy = second.anchor[1] - first.anchor[1]
      const length = Math.hypot(dx, dy)
      if (length > 1e-12) hint = [dx / length, dy / length]
    }
    return {
      profileId: pressureEntry.id,
      name: pressureEntry.alias,
      arrows,
      pixelsPerKPa: 0,
      maximumKpa: pressureMaximum,
      mode: arrowMode,
      manualMmPer10Kpa: manualMmValue,
      origin: first?.anchor ?? null,
      directionHint: hint,
      selected: pressureHover ?? pressureSelected,
    }
  }, [
    pressureEntry,
    pressureRows,
    pressureMaximum,
    arrowMode,
    manualMmValue,
    pressureHover,
    pressureSelected,
    pressureStationsOk,
    pressurePointsOk,
  ])
  const pressureStation = pressureHover ?? pressureSelected
  const pressureFocus =
    pressureStation !== null ? (pressureRows[pressureStation] ?? null) : null
  const pressureHasSamples = pressureRows.some((row) => row.pressure !== null)
  const pressureReason = !doorIndex
    ? ('no_metadata' as const)
    : !doorIndex.enabled
      ? ('disabled' as const)
      : !doorProfiles.length
        ? (doorIndex.profiles?.find((entry) => !entry.supported)?.reason ?? 'no_profile')
        : !pressureFrame
          ? ('frame_missing' as const)
          : pressureData?.supported === false
            ? (pressureData.reason ?? 'no_profile')
            : !pressureMapping.ok
              ? (null as string | null)
              : pressureData?.availability?.pressure === 'pressure_field_missing'
              ? ('pressure_field_missing' as const)
              : pressureData?.availability?.pressure === 'pressure_not_reported_for_instance'
                ? ('pressure_not_reported_for_instance' as const)
                : !pressureHasSamples
                  ? ('no_samples' as const)
                  : null
  // Pressure export: the selected profile's ordered station axis against the
  // displayed frame's door-side pressure. The profile ID, ordered node identity
  // and frame are checked before any bytes are produced; a mismatched or
  // missing array is an explanatory state, never a silent substitution.
  const pressureIdentityOk =
    pressureStationsOk &&
    pressureMapping.ok &&
    !!pressureData &&
    !!pressureEntry &&
    pressureRows.length === pressureEntry.labels.length
  const pressureSamples = useMemo<Sample[]>(
    () =>
      pressureRows.map((row) => ({
        x: Number.isFinite(row.station) ? row.station : null,
        y:
          typeof row.pressure === 'number' && Number.isFinite(row.pressure)
            ? row.pressure
            : null,
      })),
    [pressureRows],
  )
  const pressureSpacing = parseSpacing(stationInterval)
  const pressureSpacingValue = pressureSpacing.ok ? pressureSpacing.value : 0
  const pressureGrid = useMemo<UniformResult | null>(
    () =>
      pressureSpacingValue > 0
        ? uniformSamples(pressureSamples, pressureSpacingValue)
        : null,
    [pressureSamples, pressureSpacingValue],
  )
  const pressureExportPoints =
    pressureExportMode === 'original'
      ? originalSamples(pressureSamples)
      : pressureGrid?.kind === 'ok'
        ? pressureGrid.points
        : []
  const pressureExportIssue = pressureReason
    ? 'run.pressureExportUnavailable'
    : !pressureStationsOk
      ? 'run.pressureStationsUnavailable'
      : !pressureIdentityOk
        ? 'run.pressureArrayMismatch'
        : pressureExportMode === 'original'
          ? pressureExportPoints.length
            ? null
            : 'run.pressureExportUnavailable'
          : exportUnavailableKey(pressureGrid, pressureSpacing.ok) ??
            (pressureExportPoints.length ? null : 'run.pressureExportUnavailable')
  const pressureCurve = {
    x: pressureRows.map((row) => row.station),
    y: pressureRows.map((row) =>
      row.pressure === null || !Number.isFinite(row.pressure) ? Number.NaN : row.pressure,
    ),
  }
  const pressureAxisLabel = t('run.pressureAxis') + factorTag
  // The exported two-row header keeps its established ×1 form so existing
  // spreadsheets and golden comparisons remain valid; a factor is appended once.
  const pressureExportLabel = 'CPRESS (kPa)' + factorTag
  const loadOrdinateDisplay = loadOrdinate + factorTag
  const pressurePositive = pressureRows.filter(
    (row) => row.pressure !== null && row.pressure > 0,
  ).length
  const pressureGaps = pressureRows.filter((row) => row.pressure === null).length
  const pressurePatches = pressureRows.reduce(
    (count, row, index) => {
      const positive = row.pressure !== null && row.pressure > 0
      const previous =
        index > 0 && pressureRows[index - 1].pressure !== null && pressureRows[index - 1].pressure! > 0
      return count + (positive && !previous ? 1 : 0)
    },
    0,
  )
  function applyManual(next: { min: string; max: string }) {
    setRangeDrafts((old) => ({ ...old, [rangeKind]: next }))
    const min = Number(next.min),
      max = Number(next.max)
    // Keep the last valid render while a draft is blank, non-finite or inverted.
    if (
      next.min.trim() !== '' &&
      next.max.trim() !== '' &&
      Number.isFinite(min) &&
      Number.isFinite(max) &&
      max > min
    )
      setRangeLimits((old) => ({ ...old, [rangeKind]: { min, max } }))
  }
  function changeRangeMode(next: RangeMode) {
    setRangeModes((old) => ({ ...old, [rangeKind]: next }))
    if (next === 'manual') applyManual(rangeDrafts[rangeKind])
  }
  function resetRange() {
    setRangeModes((old) => ({ ...old, [rangeKind]: 'fixed' }))
    setRangeDrafts((old) => ({ ...old, [rangeKind]: DEFAULT_DRAFT[rangeKind] }))
    setRangeLimits((old) => ({ ...old, [rangeKind]: DEFAULT_RANGE[rangeKind] }))
  }
  // The multiplier is committed from its own draft. Negative, non-finite and
  // blank values never replace the last valid factor; the reason is localized.
  function applyMultiplier(text: string) {
    setMultiplierDraft(text)
    const trimmed = text.trim()
    if (trimmed === '') {
      setMultiplierError(false)
      return
    }
    const value = Number(trimmed)
    if (!Number.isFinite(value) || value < 0) {
      setMultiplierError(true)
      return
    }
    setMultiplierError(false)
    setMultiplier(value)
  }
  function resetMultiplier() {
    setMultiplier(1)
    setMultiplierDraft('1')
    setMultiplierError(false)
  }
  // Manual arrow calibration: 10 kPa = N mm. Invalid drafts keep the last valid
  // physical calibration so the viewport never renders a fabricated length.
  function applyManualMm(text: string) {
    setManualMm(text)
    const trimmed = text.trim()
    if (trimmed === '') {
      setManualMmError(false)
      return
    }
    const value = Number(trimmed)
    if (!Number.isFinite(value) || value <= 0) {
      setManualMmError(true)
      return
    }
    setManualMmError(false)
    setManualMmValue(value)
  }
  async function recoverResults(kind: 'extract' | 'retry') {
    try {
      await request('/api/jobs/' + id + '/' + kind, 'POST')
      refresh((value) => value + 1)
    } catch (error) {
      notify(err(error))
    }
  }
  const plotPick = useCallback(
    (i: number) => {
      if (index && historyRows[i]) {
        playing(false)
        setN(
          nearestIndex(
            index.frames,
            historyRows[i].time,
            historyRows[i].step_id ?? historyRows[i].step,
            historyRows[i].step,
          ),
        )
      }
    },
    [index, historyRows],
  )
  function exportLoad() {
    if (!index || loadExportIssue || !loadExportPoints.length) return
    const role = stepRole === 'body' ? 'body' : 'door'
    const step = curveStep ?? 'step'
    const interval = loadExportMode === 'original' ? 'original' : `dx${formatNumber(loadSpacingValue)}mm`
    const filename =
      role +
      '-' +
      safeName(stepInstance) +
      '-load-' +
      id.slice(0, 8) +
      '-' +
      safeName(step) +
      '-' +
      loadBasis +
      '-' +
      safeName(interval) +
      (loadExportMode === 'original' ? '-ordered' : '') +
      (reverseY ? '-force-flipped' : '') +
      (multiplier === 1 ? '' : '-x' + formatNumber(multiplier)) +
      (resultPartial ? '-partial' : '') +
      '.csv'
    // Two rows only: the engineering label in column A and numeric samples from
    // column B. Adjacent UI and the filename carry panel, step, basis, sign and
    // interval; no preamble, header or time column is written.
    download(filename, twoRowCsv('stroke(mm)', loadOrdinateDisplay, loadExportPoints))
  }
  function exportPressure() {
    if (!index || !pressureEntry || pressureExportIssue || !pressureExportPoints.length) return
    const interval =
      pressureExportMode === 'original'
        ? 'original'
        : `dx${formatNumber(pressureSpacingValue)}mm`
    const frame = `frame-${String(shownFrame).padStart(5, '0')}`
    const filename =
      'door-pressure-' +
      id.slice(0, 8) +
      '-' +
      safeName(pressureEntry.id) +
      '-' +
      safeName(frame) +
      '-' +
      safeName(pressureEntry.alias) +
      '-' +
      safeName(interval) +
      (pressureExportMode === 'original' ? '-nodes' : '') +
      (multiplier === 1 ? '' : '-x' + formatNumber(multiplier)) +
      (resultPartial ? '-partial' : '') +
      '.csv'
    download(filename, twoRowCsv('door station(mm)', pressureExportLabel, pressureExportPoints))
  }
  if (!job) return <main className="page">{t('run.opening')}</main>
  // A history-only or entirely empty generation has no playable frame. Playback,
  // scrub, probe and field-only controls are not offered at all; the CLD curve
  // and its exports remain available from the measured history.
  const hasFrames = (index?.frames.length ?? 0) > 0
  const disabled = index?.unavailable ?? []
  const displacementAvailable = !!frame && !!index && !disabled.includes('U')
  const stressUnavailable = !stressAvailable
  const probeText = (() => {
    if (!sel) return t('run.probePrompt')
    const identity = sel.instance + ' · ' + sel.kind + ' ' + sel.label
    const factorTag =
      multiplier === 1 ? '' : ' · ×' + formatNumber(multiplier)
    if (fieldIsContact) {
      const sample =
        sel.instance && sel.label !== undefined
          ? contactSamples.get(sel.instance + ':' + sel.label)
          : undefined
      if (!sample) return identity + ' · ' + t('run.contactForceUnavailable')
      const components = sample.components
        .map((value, axis) => {
          const name = axis === 0 ? 'Fx' : axis === 1 ? 'Fy' : 'Fz'
          return name + ' ' + Number((value * multiplier).toPrecision(4))
        })
        .join(', ')
      return (
        identity +
        ' · |CNORMF| ' +
        Number((sample.magnitude * multiplier).toPrecision(4)) +
        ' N · ' +
        components +
        ' N' +
        factorTag
      )
    }
    if (sel.kind === 'element' && fieldIsStress) {
      const cell =
        sel.instance && sel.label !== undefined
          ? stressSampleCells.get(sel.instance + ':' + sel.label)
          : undefined
      if (!cell || !cell.samples.length)
        return identity + ' · ' + t('run.stressUnavailable')
      const maximum = Math.max(
        ...cell.samples.map((sample) => sample.value * multiplier),
      )
      const samples = cell.samples
        .map(
          (sample) =>
            (sample.ip === undefined ? '' : 'IP ' + sample.ip + ': ') +
            Number((sample.value * multiplier).toPrecision(4)) +
            (sample.section === undefined ? '' : ' (SP ' + sample.section + ')'),
        )
        .join(', ')
      return (
        identity +
        ' · ' +
        t('run.misesMaxIp', { value: maximum.toPrecision(4), unit }) +
        ' · ' +
        t('run.samples') +
        ': ' +
        samples +
        factorTag
      )
    }
    if (sel.kind === 'element') {
      const instance = index?.instances.find((item) => item.name === sel.instance)
      const element = instance?.elements.find((item) => item.label === sel.label)
      if (!element) return identity
      const rows = (sel.instance ? frame?.displacements[sel.instance] : undefined) ?? []
      const nodes = element.connectivity.map((label) => {
        const row = rows.find((item) => item[0] === label)
        return (
          label +
          ': ' +
          (row ? Math.hypot(...row.slice(1)).toPrecision(4) + ' mm' : t('run.uUnavailable'))
        )
      })
      return (
        identity +
        ' · ' +
        t('run.elementNodes', { count: element.connectivity.length }) +
        ' · ' +
        nodes.join(', ')
      )
    }
    const probe =
      sel.instance && frame?.displacements[sel.instance]?.find((r) => r[0] === sel.label)
    if (!probe) return identity + ' · ' + t('run.uUnavailable')
    // A quantity with no run-wide measurement is unavailable, even if the frame
    // carries a placeholder value.
    if (rangeUnavailable && field !== 'Umag')
      return identity + ' · ' + field + ' ' + t('run.uUnavailable')
    if (field === 'Umag')
      return identity + ' · |U| ' + Math.hypot(...probe.slice(1)).toPrecision(4) + ' mm'
    const axis = field === 'U1' ? 1 : 2
    const value = probe[axis]
    // A missing component stays identifiable instead of becoming a zero.
    if (value === undefined || value === null)
      return identity + ' · ' + field + ' ' + t('run.uUnavailable')
    return identity + ' · ' + field + ' ' + value.toPrecision(4) + ' mm'
  })()
  const legendLabel = fieldIsContact
    ? t('run.legendContactForce', { field: fieldLabel, unit })
    : fieldIsStress
      ? t('run.legendStress', { field: fieldLabel, unit })
      : t('run.legendTitle', { variable: 'U', component: fieldLabel })
  return (
    <main className="page run-view">
      <div className="crumb">
        <button onClick={() => go('dashboard')}>{t('nav.dashboard')}</button>
        <ChevronRight />
        {resultView ? t('run.results') : t('run.diagnosticsTitle')}
      </div>
      <div className="page-heading">
        <div>
          <h1>{job.name}</h1>
          <div className="subtitle">
            {job.project_name}
            <i />
            {job.dimension}
            <i />
            {t('workspace.revision', { number: job.number })}
          </div>
        </div>
        <JobActions job={job} notify={notify} refresh={() => refresh((x) => x + 1)} />
      </div>
      <div className="run-banner">
        <Badge value={job.status} />
        <span>{job.mode === 'DEMO' ? t('demo.notice') : job.mode}</span>
        {resultView && index && !resultPartial && (
          // A usable completed result is stated here instead of in a full-width
          // progress card, so the geometry and response panes get the height.
          <span className="banner-complete" data-testid="run-complete">
            <CheckCircle2 aria-hidden="true" />
            {t('progress.compactTitle')}
          </span>
        )}
        <span className="spacer" />
        {resultView && index && (
          <button
            type="button"
            className="banner-action"
            data-testid="open-diagnostics"
            onClick={() => go('diagnostics/' + id)}
          >
            <Terminal />
            {t('progress.openDiagnostics')}
          </button>
        )}
        <Clock />
        {elapsed(job)}
      </div>
      {resultPartial && (
        <div className="partial-notice" data-testid="partial-notice" data-state="partial">
          <strong>
            {t('run.partialTitle', {
              outcome: labelFrom(
                t,
                'state',
                String((resultSummary.solver_outcome as string | undefined) || 'Unknown'),
              ),
            })}
          </strong>
          <span data-testid="partial-step">
            {t('run.partialStep', {
              step: String(resultSummary.last_step ?? '—'),
            })}
          </span>
          <span data-testid="partial-frame">
            {t('run.partialFrame', {
              ordinal: String(resultSummary.frame_ordinal ?? '—'),
              total: String(resultSummary.frames ?? 0),
            })}
          </span>
          <span data-testid="partial-time">
            {t('run.partialTime', {
              local:
                typeof resultSummary.last_local_s === 'number'
                  ? Number(resultSummary.last_local_s).toFixed(3)
                  : '—',
              total:
                typeof resultSummary.last_total_s === 'number'
                  ? Number(resultSummary.last_total_s).toFixed(3)
                  : '—',
            })}
          </span>
          {job.increment != null && job.step_time != null && (
            <span data-testid="partial-solver-progress">
              {t('run.partialSolverProgress', {
                increment: String(job.increment),
                time: Number(job.step_time).toFixed(3),
              })}
            </span>
          )}
          {Boolean(resultSummary.history_only) && (
            <span data-testid="partial-history-only">{t('run.partialHistoryOnly')}</span>
          )}
          {Boolean(resultSummary.initial_only) && (
            <span data-testid="partial-initial-only">{t('run.partialInitialOnly')}</span>
          )}
          {!!job.extraction_error && (
            <span className="error-text" data-testid="partial-extraction-error">
              {job.extraction_error}
            </span>
          )}
          {!!job.diagnostic && (
            <span className="error-text" data-testid="partial-diagnostic">
              {job.diagnostic}
            </span>
          )}
          <button type="button" onClick={() => go('diagnostics/' + id)}>
            {t('progress.openDiagnostics')}
          </button>
        </div>
      )}
      {resultView && index ? (
        <>
          {/* A usable completed result gives its height back to the geometry and
              response panes. Completion identity and Diagnostics remain one click
              away; a failed or unreadable extraction keeps the full status card. */}
          <div className="result-grid results-layout">
          <section className="card">
            <div className="panel-title">
              <ScanLine />
              {t('run.field')}
              <div className="spacer" />
              <select
                aria-label={t('run.field')}
                value={field}
                onChange={(e) => setField(e.target.value as FieldId)}
                disabled={!hasFrames || !fieldOptions.length}
              >
                {fieldOptions.map((option) => (
                  <option key={option} value={option}>
                    {t(('run.field.' + option) as TranslationKey)}
                  </option>
                ))}
              </select>
              <select
                aria-label={t('run.probeMode')}
                value={mode}
                disabled={!hasFrames}
                onChange={(e) => {
                  setMode(e.target.value as 'node' | 'element')
                  select(null)
                }}
              >
                {!fieldIsStress && <option value="node">{t('run.probeNode')}</option>}
                <option value="element">{t('run.probeElement')}</option>
              </select>
            </div>
            {fieldIsStress && stressUnavailable && (
              <p className="notice" data-testid="stress-unavailable">
                {t('run.stressUnavailable')}
              </p>
            )}
            {fieldIsContact && !contactAvailable && (
              <p className="notice" data-testid="contact-force-unavailable">
                {t('run.contactForceUnavailable')}
              </p>
            )}
            {!fieldIsStress && !fieldIsContact && !displacementAvailable && frame && (
              <p className="notice" data-testid="displacement-unavailable">
                {t('run.uUnavailable')}
              </p>
            )}
            <div className="result-viewport">
              <Viewport
                display={null}
                dimension="2D"
                mode={mode}
                selection={sel}
                onSelect={select}
                results={{ instances: index.instances, frame, bounds: displayMeta?.bounds?.extent ?? null }}
                deformed={deformed}
                deformationScale={deformationScale}
                elementValues={fieldIsStress ? displayElementValues : undefined}
                nodalValues={fieldIsContact ? contactDisplayValues : undefined}
                pressureArrows={showPressureArrows ? pressureArrows : null}
                resultComponent={fieldIsStress || fieldIsContact ? 'magnitude' : displacementKey}
                resultRange={rangeUnavailable ? null : (resultRange ?? null)}
                resultMin={effectiveMin}
                resultUnit={unit}
                resultSaturated={saturated}
                resultUnderflow={underflow}
                resultLabel={legendLabel}
                showMeshEdges={edges}
                nodeMarkers={markers}
                materialOutlines={materialOutlines}
                faceMaterials={faceMaterials}
                plain
              />
            </div>
            {hasFrames ? (
              <div className="playback" data-testid="playback">
                <button
                  className="play-toggle"
                  aria-label={play ? t('run.pausePlayback') : t('run.playFrames')}
                  disabled={index.frames.length < 2}
                  onClick={() => {
                    deadline.current = 0
                    if (!play && n === index.frames.length - 1) setN(0)
                    playing(!play)
                  }}
                >
                  {play ? <Pause /> : <Play />}
                </button>
                <div className="playback-body">
                  <input
                    className="playback-slider"
                    aria-label={t('run.frame', { current: Math.min(n + 1, index.frames.length), total: index.frames.length })}
                    type="range"
                    min={0}
                    max={Math.max(0, index.frames.length - 1)}
                    value={Math.min(n, Math.max(0, index.frames.length - 1))}
                    disabled={index.frames.length < 2}
                    onChange={(e) => {
                      playing(false)
                      deadline.current = 0
                      setN(+e.target.value)
                    }}
                  />
                  <div className="playback-status-row">
                    <span className="frame-count" data-testid="frame-count">
                      {Math.min(n + 1, index.frames.length)} / {index.frames.length}
                    </span>
                    <span className="frame-time" data-testid="frame-time">
                      {shownEntry ? shownEntry.time.toFixed(3) + ' s' : '—'}
                    </span>
                    <span
                      className={pendingFrame !== null && pendingFrame !== displayedFrame ? 'loading-note' : 'playback-note'}
                      role={frameError !== null ? 'alert' : 'status'}
                      data-testid="playback-status"
                      data-displayed={displayedFrame ?? ''}
                    >
                      {frameError !== null
                        ? t('run.frameFailed', { frame: frameError + 1 })
                        : pendingFrame !== null && pendingFrame !== displayedFrame
                          ? t('run.loadingFrame')
                          : t('run.frameReady')}
                    </span>
                    <label className="check loop-toggle">
                      <input
                        type="checkbox"
                        checked={loop}
                        disabled={index.frames.length < 2}
                        aria-label={t('run.loop')}
                        onChange={(e) => setLoop(e.target.checked)}
                      />
                      {t('run.loop')}
                    </label>
                  </div>
                </div>
              </div>
            ) : (
              <p className="notice" data-testid="no-field-frames">
                {t('run.noFieldFrames')}
              </p>
            )}
            <div className="result-controls" data-testid="result-controls">
              <fieldset>
                <legend>{t('run.range')}</legend>
                <label>
                  {t('run.rangeMode')}
                  <select
                    aria-label={t('run.rangeMode')}
                    value={rangeMode}
                    onChange={(e) => changeRangeMode(e.target.value as RangeMode)}
                  >
                    <option value="fixed">
                      {t('run.rangeFixed', {
                        min: fallback.min.toFixed(2),
                        max: fallback.max.toFixed(2),
                        unit,
                      })}
                    </option>
                    <option value="auto">{t('run.rangeAuto')}</option>
                    <option value="manual">{t('run.rangeManual')}</option>
                  </select>
                </label>
                <label>
                  {t('run.rangeMin', { unit })}
                  <input
                    type="number"
                    step="any"
                    aria-label={t('run.rangeMin', { unit })}
                    value={manual.min}
                    disabled={rangeMode !== 'manual'}
                    onChange={(e) => applyManual({ ...manual, min: e.target.value })}
                  />
                </label>
                <label>
                  {t('run.rangeMax', { unit })}
                  <input
                    type="number"
                    step="any"
                    aria-label={t('run.rangeMax', { unit })}
                    value={manual.max}
                    disabled={rangeMode !== 'manual'}
                    onChange={(e) => applyManual({ ...manual, max: e.target.value })}
                  />
                </label>
                <span className="range-summary" data-testid="range-summary">
                  {formatRange(effectiveMin)} – {formatRange(effectiveMax)} {unit}
                </span>
                {rangeMode === 'auto' && multiplier !== 1 && autoRange != null && (
                  <small data-testid="range-auto-reference">
                    {t('run.rangeAutoReference', {
                      value: formatRange(autoRange),
                      unit,
                    })}
                  </small>
                )}
                {multiplier !== 1 && !rangeUnavailable && (
                  <small data-testid="range-extrema">
                    {t('run.rangeExtrema', {
                      max: formatRange(frameMax),
                      unit,
                    })}
                  </small>
                )}
                <button type="button" onClick={resetRange}>
                  {t('run.rangeReset')}
                </button>
                {manualInvalid && (
                  <small className="error-text" role="alert" data-testid="range-error">
                    {t('run.rangeInvalid')}
                  </small>
                )}
              </fieldset>
              <div className="control-row">
                <label className="check">
                  <input
                    type="checkbox"
                    checked={edges}
                    onChange={(e) => setEdges(e.target.checked)}
                  />
                  {t('run.meshEdges')}
                </label>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={markers}
                    onChange={(e) => setMarkers(e.target.checked)}
                  />
                  {t('run.nodeMarkers')}
                </label>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={deformed}
                    onChange={(e) => deform(e.target.checked)}
                  />
                  {t('run.deformed')}
                </label>
                <label>
                  {t('run.deformationScale')}
                  <input
                    type="number"
                    min={0.01}
                    step="0.5"
                    aria-label={t('run.deformationScale')}
                    value={scaleDraft}
                    onChange={(e) => {
                      setScaleDraft(e.target.value)
                      const value = Number(e.target.value)
                      if (Number.isFinite(value) && value > 0) setDeformationScale(value)
                    }}
                  />
                </label>
              </div>
              {/* Pressure arrows live with the other field-visualization
                  controls below the viewport. One compact group serves every
                  field; its calibration is independent of zoom and deformation. */}
              <div
                className="arrow-controls"
                data-testid="arrow-controls"
                role="group"
                aria-label={t('run.pressureArrows')}
              >
                <label className="check">
                  <input
                    type="checkbox"
                    data-testid="pressure-arrows-toggle"
                    checked={showPressureArrows}
                    disabled={!doorProfiles.length}
                    title={
                      doorProfiles.length
                        ? undefined
                        : t('run.pressureArrowsUnavailable')
                    }
                    onChange={(event) => setShowPressureArrows(event.target.checked)}
                  />
                  {t('run.pressureArrows')}
                </label>
                <label>
                  <span className="visually-hidden">{t('run.arrowMode')}</span>
                  <select
                    data-testid="arrow-mode"
                    aria-label={t('run.arrowMode')}
                    value={arrowMode}
                    disabled={!doorProfiles.length}
                    onChange={(event) =>
                      setArrowMode(event.target.value as 'auto' | 'manual')
                    }
                  >
                    <option value="auto">{t('run.arrowAuto')}</option>
                    <option value="manual">{t('run.arrowManual')}</option>
                  </select>
                </label>
                {arrowMode === 'manual' ? (
                  <label>
                    <span>{t('run.arrowManualCalibration')}</span>
                    <input
                      type="number"
                      min={1e-9}
                      step="any"
                      inputMode="decimal"
                      data-testid="arrow-manual-mm"
                      aria-label={t('run.arrowManualCalibration')}
                      value={manualMm}
                      onChange={(event) => applyManualMm(event.target.value)}
                    />
                    <small>{t('run.arrowManualUnit')}</small>
                  </label>
                ) : (
                  <small data-testid="arrow-auto-note">
                    {t('run.arrowAutoNote', {
                      value: Number(pressureMaximum.toPrecision(4)),
                      unit: doorIndex?.display_unit ?? 'kPa',
                    })}
                  </small>
                )}
                {manualMmError && (
                  <small className="error-text" role="alert" data-testid="arrow-manual-error">
                    {t('run.arrowManualInvalid')}
                  </small>
                )}
                {!doorProfiles.length && (
                  <small className="field-hint" data-testid="arrow-unavailable">
                    {t('run.pressureArrowsUnavailable')}
                  </small>
                )}
              </div>
              {/* Material outlines are an independent display preference (default
                  off). They are separate from mesh edges, node markers, the
                  selected field and the deformation scale. */}
              <div className="control-row material-controls">
                <label className="check">
                  <input
                    type="checkbox"
                    data-testid="material-outlines"
                    checked={materialOutlines}
                    disabled={!materialInfo.mapped}
                    title={materialInfo.mapped ? undefined : t('run.materialNoMapping')}
                    onChange={(e) => setMaterialOutlines(e.target.checked)}
                  />
                  {t('run.materialOutlines')}
                </label>
                {!materialInfo.mapped && (
                  <small className="field-hint" data-testid="material-outlines-unavailable">
                    {t('run.materialNoMapping')}
                  </small>
                )}
              </div>
              {materialOutlines && materialInfo.mapped > 0 && (
                <div className="material-legend" data-testid="material-legend">
                  <strong>{t('run.materialLegend')}</strong>
                  <div className="material-swatches">
                    {materialLegend.map((row) => (
                      <span key={row.key}>
                        <b style={{ background: row.color }} />
                        {row.name}
                        {row.version ? ' v' + row.version : ''}
                      </span>
                    ))}
                  </div>
                  <small data-testid="material-interface-count">
                    {t('run.materialInterfaceCount', {
                      count: materialInfo.interfaces.length,
                    })}
                  </small>
                  {materialInfo.mapped < materialInfo.total && (
                    <small data-testid="material-coverage">
                      {t('run.materialPartial', {
                        mapped: materialInfo.mapped,
                        total: materialInfo.total,
                      })}
                    </small>
                  )}
                  {materialInfo.materials.length < 2 && (
                    <small data-testid="material-single">{t('run.materialSingle')}</small>
                  )}
                </div>
              )}
            </div>
            <div className="legend">
              <span>{probeText}</span>
              {displayMeta === null && (
                <span className="notice">{t('run.displayMetadataFallback')}</span>
              )}
            </div>
          </section>
          <aside className="card">
            <div className="panel-title">
              <Activity />
              {t('run.doorResponse')}
            </div>
            <div className="property-body">
              <fieldset className="result-multiplier" data-testid="result-multiplier">
                <legend>{t('run.resultMultiplier')}</legend>
                <label>
                  {t('run.multiplierLabel')}
                  <input
                    type="number"
                    min={0}
                    step="any"
                    inputMode="decimal"
                    aria-label={t('run.resultMultiplier')}
                    data-testid="result-multiplier-input"
                    value={multiplierDraft}
                    onChange={(event) => applyMultiplier(event.target.value)}
                    onBlur={() => {
                      if (multiplierDraft.trim() === '') setMultiplierError(true)
                    }}
                  />
                  <small>×</small>
                </label>
                <button type="button" onClick={resetMultiplier} data-testid="multiplier-reset">
                  {t('run.multiplierReset')}
                </button>
                {multiplierError && (
                  <small className="error-text" role="alert" data-testid="multiplier-error">
                    {t('run.multiplierInvalid')}
                  </small>
                )}
                {multiplier !== 1 && (
                  <small data-testid="multiplier-active">
                    {t('run.multiplierActive', { factor: formatNumber(multiplier) })}
                  </small>
                )}
              </fieldset>
              <h2>{t('run.forceDisplacement')}</h2>
              <p>{index.closing ? t('run.plotHelp') : t('run.plotHelpLegacy')}</p>
              {stepOptions.length > 1 && (
                <label>
                  {t('run.curveStep')}
                  <select
                    aria-label={t('run.curveStep')}
                    data-testid="curve-step"
                    value={curveStep ?? ''}
                    onChange={(e) => setCurveStep(e.target.value || null)}
                  >
                    {stepOptions.map((step) => (
                      <option key={step.id ?? step.name} value={step.id ?? step.name}>
                        {step.name} · {t(step.role === 'body' ? 'run.roleBody' : 'run.roleDoor')}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {historyRows.length ? (
                <>
                  <p
                    className="plot-caption"
                    id="force-plot-caption"
                    data-testid="force-caption"
                  >
                    <span>{forceAxisLabel}</span>
                    <span className="plot-caption-x">{travelAxisLabel}</span>
                  </p>
                  <Plot
                    x={curve.x}
                    y={curve.y}
                    xlabel={shortTravelAxis}
                    ylabel={shortForceAxis}
                    label={plotDescription}
                    describedBy="force-plot-caption"
                    active={activeSample}
                    onPick={plotPick}
                  />
                  <div className="force-basis" data-testid="force-basis">
                    <p data-testid="selected-step">
                      {t('run.selectedStep', {
                        step: curveStepName ?? '—',
                        role: t(stepRole === 'body' ? 'run.roleBody' : 'run.roleDoor'),
                      })}
                    </p>
                    <p data-testid="selected-rp">
                      {t('run.referencePoint', {
                        instance: stepInstance,
                        label: String(stepReference ?? '—'),
                      })}
                    </p>
                    {stepDirection ? (
                      <p data-testid="selected-direction">
                        {t('run.projectionDirection', {
                          dx: Number(stepDirection[0]).toFixed(3),
                          dy: Number(stepDirection[1]).toFixed(3),
                          angle:
                            stepAngle === undefined ? '—' : Number(stepAngle).toFixed(1),
                        })}
                      </p>
                    ) : (
                      <p data-testid="selected-direction">{t('run.projectionUnknown')}</p>
                    )}
                    <p data-testid="force-basis-text">{forceBasisText}</p>
                    {reverseY && (
                      <p className="error-text" data-testid="reverse-y-indicator">
                        {t('run.reverseYActive')}
                      </p>
                    )}
                  </div>
                  <fieldset className="sign-controls">
                    <legend>{t('run.displaySigns')}</legend>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={reverseX}
                        onChange={(e) => setReverseX(e.target.checked)}
                      />
                      {t('run.reverseX')}
                    </label>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={reverseY}
                        onChange={(e) => setReverseY(e.target.checked)}
                      />
                      {t('run.reverseY')}
                    </label>
                  </fieldset>
                  <div className="export-controls" data-testid="load-export">
                    <label className="action-field export-interval">
                      {t('run.exportInterval')}
                      <input
                        type="number"
                        min={1e-9}
                        step="any"
                        inputMode="decimal"
                        data-testid="stroke-interval"
                        value={strokeInterval}
                        onChange={(event) => setStrokeInterval(event.target.value)}
                      />
                      <small>{t('run.exportIntervalUnit')}</small>
                    </label>
                    <label className="action-field export-mode">
                      {t('run.exportSampling')}
                      <select
                        data-testid="load-sampling"
                        value={loadExportMode}
                        onChange={(event) =>
                          setLoadExportMode(event.target.value as 'uniform' | 'original')
                        }
                      >
                        <option value="uniform">{t('run.exportUniform')}</option>
                        <option value="original">{t('run.exportOriginal')}</option>
                      </select>
                    </label>
                  </div>
                  <p className="export-note" data-testid="export-endpoint-rule">
                    {t('run.exportEndpointRule')}
                  </p>
                  <button
                    className="wide"
                    onClick={exportLoad}
                    data-testid="export-curve"
                    disabled={!!loadExportIssue}
                    title={loadExportIssue ? t(loadExportIssue as TranslationKey) : undefined}
                  >
                    <Download />
                    {t('run.exportLoadTwoRows')}
                  </button>
                  {loadExportIssue ? (
                    <p className="notice" data-testid="load-export-issue">
                      {t(loadExportIssue as TranslationKey)}
                    </p>
                  ) : (
                    <small data-testid="export-basis">
                      {t('run.exportBasis', {
                        panel: stepInstance,
                        step: curveStepName ?? 'Closing',
                        unit: loadOrdinate,
                        sign: reverseY ? t('run.exportFlipped') : t('run.exportAsMeasured'),
                      })}
                    </small>
                  )}
                </>
              ) : (
                <p>{t('run.historyUnavailable')}</p>
              )}
              {/* Door-panel contact pressure is a separate spatial view. Its
                  curve and its glyphs read the same displayed frame, so a
                  scrub, playback step or delayed frame cannot desynchronize. */}
              <h2>{t('run.doorPressure')}</h2>
              <p>{t('run.doorPressureHelp')}</p>
              {doorProfiles.length ? (
                <>
                  {doorProfiles.length > 1 && (
                    <label>
                      {t('run.pressureProfile')}
                      <select
                        aria-label={t('run.pressureProfile')}
                        data-testid="pressure-profile"
                        value={pressureEntry?.id ?? ''}
                        onChange={(event) => setPressureProfile(event.target.value)}
                      >
                        {doorProfiles.map((entry) => (
                          <option key={entry.id} value={entry.id}>
                            {entry.alias}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <div className="pressure-controls">
                    {pressureEntry && (
                      <small data-testid="pressure-profile-basis">
                        {t('run.pressureProfileBasis', {
                          profile: pressureEntry.alias,
                          length: Number(pressureEntry.length_mm.toPrecision(6)),
                        })}
                      </small>
                    )}
                  </div>
                  {pressureReason ? (
                    <p className="notice" data-testid="pressure-unavailable">
                      {t('run.pressureUnavailable')} · {pressureReason}
                    </p>
                  ) : (
                    <>
                      {!pressureMapping.ok && (
                        <p className="notice" data-testid="pressure-identity-unavailable">
                          {t('run.pressureIdentityUnavailable')}
                        </p>
                      )}
                      <p
                        className="plot-caption"
                        id="pressure-plot-caption"
                        data-testid="pressure-caption"
                      >
                        <span>{pressureAxisLabel}</span>
                        <span className="plot-caption-x">{t('run.pressureDistanceAxis')}</span>
                      </p>
                      {pressureStationsOk && pressureMapping.ok ? (
                        <div
                          data-testid="pressure-chart"
                          data-profile={pressureEntry?.id ?? ''}
                          data-samples={pressureRows.length}
                          data-positive={pressurePositive}
                          data-patches={pressurePatches}
                          data-gaps={pressureGaps}
                          data-maximum-kpa={pressureMaximum}
                          data-displayed-maximum-kpa={displayedPressureMaximum}
                        >
                          <Plot
                            x={pressureCurve.x}
                            y={pressureCurve.y}
                            xlabel={t('run.pressureDistanceAxis')}
                            ylabel={pressureAxisLabel}
                            label={
                              pressureAxisLabel + ' · ' + t('run.pressureDistanceAxis')
                            }
                            describedBy="pressure-plot-caption"
                            active={pressureStation ?? undefined}
                            onPick={(index) => setPressureSelected(index)}
                            onHover={setPressureHover}
                          />
                        </div>
                      ) : !pressureStationsOk ? (
                        <p className="notice" data-testid="pressure-stations-unavailable">
                          {t('run.pressureStationsUnavailable')}
                        </p>
                      ) : null}
                      {showPressureArrows && pressureStationsOk && pressureMapping.ok && (
                        <div className="pressure-scale" data-testid="pressure-scale">
                          <svg width={70} height={12} aria-hidden="true">
                            <line
                              x1={2}
                              y1={6}
                              x2={58}
                              y2={6}
                              stroke="#0f6b57"
                              strokeWidth={2}
                            />
                            <polygon points="58,1 68,6 58,11" fill="#0f6b57" />
                          </svg>
                          <small data-testid="pressure-reference">
                            {arrowMode === 'manual'
                              ? t('run.arrowManualLegend', {
                                  mm: formatNumber(manualMmValue),
                                })
                              : t('run.pressureReferenceScale', {
                                  value: Number(pressureMaximum.toPrecision(4)),
                                  unit: doorIndex?.display_unit ?? 'kPa',
                                })}
                          </small>
                        </div>
                      )}
                      {pressureFocus ? (
                        <div
                          className="pressure-readout"
                          data-testid="pressure-readout"
                          data-node={pressureFocus.label}
                          data-station={pressureFocus.station ?? ''}
                          data-pressure={pressureFocus.pressure ?? ''}
                          data-native-mpa={pressureFocus.native ?? ''}
                          data-raw-kpa={pressureFocus.rawPressure ?? ''}
                          data-fx={pressureFocus.force?.[0] ?? ''}
                          data-fy={pressureFocus.force?.[1] ?? ''}
                        >
                          <p>
                            {t('run.pressureStationReadout', {
                              profile: pressureEntry?.alias ?? '',
                              node: String(pressureFocus.label),
                              station:
                                pressureFocus.station === null
                                  ? '—'
                                  : Number(pressureFocus.station.toPrecision(6)),
                            })}
                          </p>
                          <p>
                            {t('run.pressureValueReadout', {
                              pressure:
                                pressureFocus.pressure === null
                                  ? '—'
                                  : Number(pressureFocus.pressure.toPrecision(6)),
                              unit: doorIndex?.display_unit ?? 'kPa',
                              native:
                                pressureFocus.native === null
                                  ? '—'
                                  : Number(pressureFocus.native.toPrecision(6)),
                              nativeUnit: doorIndex?.native_unit ?? 'MPa',
                            })}
                            {multiplier !== 1 && (
                              <span data-testid="pressure-factor">
                                {' · '}
                                {t('run.multiplierActive', {
                                  factor: formatNumber(multiplier),
                                })}
                              </span>
                            )}
                          </p>
                          {pressureFocus.force ? (
                            <p>
                              {t('run.pressureForceReadout', {
                                fx: Number(pressureFocus.force[0].toPrecision(6)),
                                fy: Number(
                                  (pressureFocus.force[1] ?? 0).toPrecision(6),
                                ),
                                unit: doorIndex?.force_unit ?? 'N',
                              })}
                            </p>
                          ) : (
                            <p>{t('run.pressureNoForce')}</p>
                          )}
                        </div>
                      ) : (
                        <small data-testid="pressure-readout-prompt">
                          {t('run.pressureSelectStation')}
                        </small>
                      )}
                      <div className="export-controls" data-testid="pressure-export">
                        <label className="action-field export-interval">
                          {t('run.exportInterval')}
                          <input
                            type="number"
                            min={1e-9}
                            step="any"
                            inputMode="decimal"
                            data-testid="station-interval"
                            value={stationInterval}
                            onChange={(event) => setStationInterval(event.target.value)}
                          />
                          <small>{t('run.exportIntervalUnit')}</small>
                        </label>
                        <label className="action-field export-mode">
                          {t('run.exportSampling')}
                          <select
                            data-testid="pressure-sampling"
                            value={pressureExportMode}
                            onChange={(event) =>
                              setPressureExportMode(
                                event.target.value as 'uniform' | 'original',
                              )
                            }
                          >
                            <option value="uniform">{t('run.exportUniform')}</option>
                            <option value="original">{t('run.exportOriginalNodes')}</option>
                          </select>
                        </label>
                      </div>
                      <p className="export-note" data-testid="pressure-endpoint-rule">
                        {t('run.pressureEndpointRule', {
                          frame: String(shownFrame),
                          step: shownEntry?.step ?? '—',
                        })}
                      </p>
                      <button
                        className="wide"
                        onClick={exportPressure}
                        data-testid="export-pressure"
                        disabled={!!pressureExportIssue}
                        title={
                          pressureExportIssue
                            ? t(pressureExportIssue as TranslationKey)
                            : undefined
                        }
                      >
                        <Download />
                        {t('run.exportPressureTwoRows')}
                      </button>
                      {pressureExportIssue ? (
                        <p className="notice" data-testid="pressure-export-issue">
                          {t(pressureExportIssue as TranslationKey)}
                        </p>
                      ) : (
                        <small data-testid="pressure-export-basis">
                          {t('run.pressureExportBasis', {
                            profile: pressureEntry?.alias ?? '—',
                            step: shownEntry?.step ?? '—',
                            frame: String(shownFrame),
                            unit: doorIndex?.display_unit ?? 'kPa',
                          })}
                        </small>
                      )}
                    </>
                  )}
                  {!!pressureData?.ambiguous?.length && (
                    <p className="error-text" data-testid="pressure-ambiguous">
                      {t('run.pressureAmbiguous', {
                        count: pressureData?.ambiguous?.length ?? 0,
                      })}
                    </p>
                  )}
                </>
              ) : (
                <p data-testid="pressure-unavailable">{t('run.pressureUnavailable')}</p>
              )}
              <dl>
                <div>
                  <dt>{t('run.thickness')}</dt>
                  <dd>{index.thickness_mm ?? index.thickness} mm</dd>
                </div>
                <div>
                  <dt>{t('run.reportingWidth')}</dt>
                  <dd>
                    {(index.reporting_width_mm ?? index.thickness_mm ?? index.thickness)} mm
                    {index.reporting_width_basis === 'legacy_thickness'
                      ? ' · ' + t('run.legacyBasis')
                      : ''}
                  </dd>
                </div>
                <div>
                  <dt>{t('run.forceUnit')}</dt>
                  <dd>{index.force_unit}</dd>
                </div>
                {stepDirection ? (
                  <div>
                    <dt>{t('run.closingDirection')}</dt>
                    <dd>
                      {stepDirection.map((v) => Number(v).toFixed(3)).join(', ')}
                      {stepAngle !== undefined ? ' · ' + Number(stepAngle).toFixed(1) + '°' : ''}
                    </dd>
                  </div>
                ) : (
                  <div>
                    <dt>{t('run.closingDirection')}</dt>
                    <dd>{t('run.directionUnknown')}</dd>
                  </div>
                )}
                <div>
                  <dt>{t('run.provenance')}</dt>
                  <dd>
                    {index.mode === 'DEMO' ? t('run.provenanceSynthetic') : t('run.provenanceSolver')}
                  </dd>
                </div>
              </dl>
              <a className="button" href={artifactUrl('history.csv')} download>
                <Download />
                {t('run.downloadCsv')}
              </a>
              {index.unavailable.length > 0 && (
                <>
                  <h3>{t('run.unavailableOutputs')}</h3>
                  {/* Names stay in their raw contract form; they are engineering identifiers. */}
                  <p>{index.unavailable.join(' · ')}</p>
                </>
              )}
            </div>
          </aside>
        </div>
        </>
      ) : (
        <>
          <ProgressSummary job={job} setup={setup} now={now} />
          <div className="result-grid">
          <section className="card">
            <div className="panel-title">
              <Terminal />
              {t('run.diagnosticsTitle')}
            </div>
            <div className="property-body">
              <h2>{labelFrom(t, 'phase', job.phase)}</h2>
              {job.diagnostic && (
                <>
                  <p className="error-text">{job.diagnostic}</p>
                  <button
                    type="button"
                    onClick={() => setLogFile(sourceLog(job))}
                  >
                    {t('diag.openSourceLog')}
                  </button>
                </>
              )}
              {['Failed', 'Cancelled'].includes(job.solver) && !resultOpen && (
                <div className="recovery-actions" data-testid="recovery-actions">
                  <button
                    type="button"
                    data-testid="extract-available"
                    onClick={() => void recoverResults('extract')}
                  >
                    {t('run.extractAvailable')}
                  </button>
                  {['Failed', 'Cancelled'].includes(job.extraction) && (
                    <button
                      type="button"
                      data-testid="retry-extraction"
                      onClick={() => void recoverResults('retry')}
                    >
                      {t('dashboard.retryExtraction')}
                    </button>
                  )}
                  <small>{t('run.extractAvailableHelp')}</small>
                </div>
              )}
              <dl>
                {(
                  [
                    [t('diag.solver'), labelFrom(t, 'state', job.solver)],
                    [t('diag.extraction'), labelFrom(t, 'state', job.extraction)],
                    [t('diag.submitted'), formatDate(job.created)],
                    [t('diag.started'), job.started ? formatDate(job.started) : '—'],
                    [t('diag.finished'), job.ended ? formatDate(job.ended) : '—'],
                    [t('diag.step'), job.step ?? '—'],
                    [t('diag.increment'), job.increment ?? '—'],
                    [t('diag.stepTime'), job.step_time ?? '—'],
                    [t('diag.solverExit'), job.exit_code ?? '—'],
                    [t('diag.extractorExit'), job.extraction_exit ?? '—'],
                    [t('diag.processId'), job.pid ?? '—'],
                    [t('diag.lastHeartbeat'), job.heartbeat ? formatDate(job.heartbeat) : '—'],
                    [t('diag.jobId'), id],
                    [t('diag.inputHash'), job.input_hash ?? t('diag.inputHashPending')],
                  ] as [string, string | number][]
                ).map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </section>
          <aside className="card">
            <div className="panel-title">
              <Archive />
              {t('run.runArtifacts')}
            </div>
            <div className="property-body">
              {job.manifest
                .filter((f) => !f.startsWith('frame-'))
                .map((f) => (
                  <a className="asset" key={f} href={artifactUrl(f)} download>
                    <FileText />
                    {f}
                    <Download />
                  </a>
                ))}
              {!job.manifest.length && <p>{t('run.artifactsPending')}</p>}
            </div>
          </aside>
          <div className="card log-card">
            <div className="panel-title">
              <Terminal />
              {t('run.logTail')}
              <div className="spacer" />
              <select
                aria-label={t('run.logFile')}
                value={logFile}
                onChange={(e) => setLogFile(e.target.value)}
              >
                {[
                  ...new Set([
                    'worker.log',
                    ...job.manifest.filter((f) => /\.(log|msg|sta|dat)$/.test(f)),
                  ]),
                ].map((f) => (
                  <option key={f}>{f}</option>
                ))}
              </select>
            </div>
            <pre>{logs || t('run.waitingLog')}</pre>
          </div>
          </div>
        </>
      )}
    </main>
  )
}
