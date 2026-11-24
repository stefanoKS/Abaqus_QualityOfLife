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
import { artifact, elapsed, err, go, request, type Job, type Revision } from './api'
import { Badge, JobActions } from './Dashboard'
import Viewport from './Viewport'
import type { Picked, ResultFrame, ResultInstance } from './viewportModel'
import {
  materialTopology,
  type MaterialFaceAssignment,
} from './viewportModel'
import {
  elementDisplayValues,
  misesFrom,
  stressCells,
  type FieldId,
  type StressCell,
} from './features/run/fields'
export type { FieldId } from './features/run/fields'
import { Plot } from './Plot'
import { ProgressSummary } from './features/run/ProgressSummary'
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
  frames: { time: number; step?: string; step_id?: string; file: string }[]
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

/** Fields the extractor may publish in addition to displacements. */
interface Frame extends ResultFrame {
  fields?: Record<string, unknown>
  unavailable?: string[]
}

/** Run-wide display metadata recorded by extraction or derived for a retained run. */
interface DisplayMeta {
  version: number
  bounds: { undeformed: number[]; deformed: number[]; extent: number[] }
  ranges: Partial<Record<Component | 'mises' | 'S11' | 'S22' | 'S33' | 'S12', number>>
  source: string
}

type Component = 'magnitude' | 'U1' | 'U2' | 'U3'

const COMPONENTS: Component[] = ['magnitude', 'U1', 'U2', 'U3']

type RangeMode = 'fixed' | 'auto' | 'manual'
type RangeKind = 'stress' | 'displacement'
const DEFAULT_RANGE: Record<RangeKind, { min: number; max: number }> = {
  stress: { min: 0, max: 0.5 },
  displacement: { min: 0, max: 5 },
}
const DEFAULT_DRAFT: Record<RangeKind, { min: string; max: string }> = {
  stress: { min: '0', max: '0.5' },
  displacement: { min: '0', max: '5' },
}

const STRESS_FIELDS: FieldId[] = ['mises', 'S11', 'S22', 'S33', 'S12']
const DISPLACEMENT_FIELDS: FieldId[] = ['Umag', 'U1', 'U2']
const isStressField = (field: FieldId) => STRESS_FIELDS.includes(field)

/**
 * Display-only sign controls. They transform the projected curve for reading
 * and for the exported CSV; the stored result artifacts are never rewritten.
 */
function displayedCurve(history: HistoryRow[], reverseX: boolean, reverseY: boolean) {
  return {
    x: history.map((row) => (reverseX ? -row.displacement : row.displacement)),
    // A missing measurement stays a gap: JavaScript's -null would become -0 and
    // silently invent a measured zero. NaN is Plotly's gap marker.
    y: history.map((row) => {
      const force = row.force
      if (force === null || force === undefined || !Number.isFinite(force)) return Number.NaN
      return reverseY ? -force : force
    }),
  }
}

/**
 * Gate D export: exactly two numeric rows, one column per aligned sample, in
 * the selected step. Row 1 is the step-relative displacement magnitude from the
 * measured U1/U2, row 2 the signed projected force in the selected basis.
 * Missing measurements stay empty cells; a measured zero stays `0`.
 */
function twoRowExport(rows: HistoryRow[], reverseY: boolean) {
  const sorted = [...rows].sort((a, b) => a.time - b.time)
  const number = (value: unknown): value is number =>
    typeof value === 'number' && Number.isFinite(value)
  const firstU1 = sorted.find((row) => number(row.u1))?.u1 as number | undefined
  const firstU2 = sorted.find((row) => number(row.u2))?.u2 as number | undefined
  const magnitudes = sorted.map((row) => {
    if (!number(row.u1) || !number(row.u2) || firstU1 === undefined || firstU2 === undefined)
      return ''
    return String(Number(Math.hypot(row.u1 - firstU1, row.u2 - firstU2).toPrecision(12)))
  })
  const forces = sorted.map((row) => {
    if (!number(row.force)) return ''
    const value = reverseY ? -row.force : row.force
    return String(Number(value.toPrecision(12)))
  })
  return { magnitudes, forces, count: sorted.length }
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
    [index, setIndex] = useState<Index | null>(null)
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
  const active = !!job && anyActive([job])
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
    if (!resultView || job?.status !== 'Completed') return
    const ac = new AbortController()
    request<Index>(artifact(id, 'results.json'), 'GET', undefined, ac.signal)
      .then(setIndex)
      .catch((e) => {
        if (!ac.signal.aborted) notify(err(e))
      })
    return () => ac.abort()
  }, [job?.status, resultView, id, notify])
  // Run-wide bounds and colour ranges, recorded by extraction or derived once
  // server-side for a retained result. They never change during playback.
  useEffect(() => {
    if (!resultView || job?.status !== 'Completed') return
    const ac = new AbortController()
    request<DisplayMeta>('/api/jobs/' + id + '/display-metadata', 'GET', undefined, ac.signal)
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
  }, [job?.status, resultView, id, notify])
  // A new run starts from a clean frame state: no old probe, frame or camera key.
  useEffect(() => {
    frameCache.current.clear()
    setFrame(null)
    setDisplayedFrame(null)
    setPendingFrame(null)
    setFrameError(null)
    setDisplayMeta(null)
  }, [id])
  // Only the newest request may commit. The last complete frame stays on screen
  // while the next one loads, so playback never blanks the viewport.
  const frameRequest = useRef(0)
  const generation = useRef(0)
  const deadline = useRef(0)
  const inflight = useRef(new Map<string, Promise<Frame>>())
  const CACHE_LIMIT = 24
  const READ_AHEAD = 4
  const CADENCE_MS = 220
  const loadFrame = useCallback(
    (file: string): Promise<Frame> => {
      const cached = frameCache.current.get(file)
      if (cached) {
        // Refresh LRU position: replaying a nearby frame stays cheap.
        frameCache.current.delete(file)
        frameCache.current.set(file, cached)
        return Promise.resolve(cached)
      }
      const queued = inflight.current.get(file)
      if (queued) return queued
      const load = request<Frame>(artifact(id, file), 'GET')
        .then((loaded) => {
          frameCache.current.set(file, loaded)
          while (frameCache.current.size > CACHE_LIMIT) {
            const oldest = frameCache.current.keys().next().value
            if (!oldest) break
            frameCache.current.delete(oldest)
          }
          inflight.current.delete(file)
          return loaded
        })
        .catch((error) => {
          inflight.current.delete(file)
          throw error
        })
      inflight.current.set(file, load)
      return load
    },
    [id],
  )
  useEffect(() => {
    if (!index) return
    const target = index.frames[n]
    if (!target) return
    const sequence = ++frameRequest.current
    const cached = frameCache.current.get(target.file)
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
  }, [index, n, loadFrame, notify])
  // Bounded read-ahead: upcoming frames (including the loop boundary) are
  // fetched while the current one is displayed. Requests are deduplicated and
  // the cache never exceeds its limit, so scrubbing cannot runaway.
  useEffect(() => {
    if (!play || !index || displayedFrame === null) return
    const total = index.frames.length
    if (total <= 1) return
    for (let step = 1; step <= READ_AHEAD; step++) {
      const upcoming = index.frames[(displayedFrame + step) % total]
      if (!upcoming) continue
      void loadFrame(upcoming.file).catch(() => {
        // Prefetch failures are silent; the request on demand reports them.
      })
    }
  }, [play, index, displayedFrame, loadFrame])
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
  // Open on the door-closing step by default in both modes.
  useEffect(() => {
    if (!index) return
    const first = index.frames.findIndex(
      (frame) =>
        !closingStepId ||
        (frame.step_id ? frame.step_id === closingStepId : frame.step === closingStepName),
    )
    setN(Math.max(0, first))
  }, [index, closingStepId, closingStepName])
  const [curveStep, setCurveStep] = useState<string | null>(null)
  const stepOptions = index?.steps?.length
    ? index.steps
    : (index?.closing?.steps ?? [])
  useEffect(() => {
    if (!index) return
    const options = index.steps?.length ? index.steps : (index.closing?.steps ?? [])
    const preferred = options.find((step) => step.role === 'door') ?? options[options.length - 1]
    setCurveStep(preferred ? (preferred.id ?? preferred.name) : null)
  }, [index])
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
  const travelAxisLabel =
    stepRole === 'body'
      ? t('run.bodyTravel')
      : index?.closing
        ? t('run.doorTravel')
        : t('run.panelU2')
  const forceAxisLabel =
    stepRole === 'body'
      ? t('run.bodyReaction', { unit: forceUnit })
      : index?.closing && stepProvenance !== 'unknown'
        ? t('run.doorReaction', { unit: forceUnit })
        : stepDirection
          ? t('run.projectedReaction', { unit: forceUnit })
          : t('run.panelRF2', { unit: forceUnit })
  const shortTravelAxis = t('run.displacementAxis')
  const shortForceAxis = t('run.forceAxis', { unit: forceUnit })
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
    () => displayedCurve(historyRows, reverseX, reverseY),
    [historyRows, reverseX, reverseY],
  )
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
  const rangeKey: Component | 'mises' | 'S11' | 'S22' | 'S33' | 'S12' = fieldIsStress
    ? field === 'mises'
      ? 'mises'
      : (field as 'S11' | 'S22' | 'S33' | 'S12')
    : displacementKey
  const autoRange = displayMeta ? (displayMeta.ranges[rangeKey] ?? null) : undefined
  const rangeKind: RangeKind = fieldIsStress ? 'stress' : 'displacement'
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
  const unit = fieldIsStress
    ? index?.units === 'N-mm-s-tonne'
      ? 'MPa'
      : t('run.unitUnknown')
    : 'mm'
  const fieldLabel = t(('run.field.' + field) as TranslationKey)
  // Scalar values actually drawn: magnitudes for displacement, max-IP values
  // for stress. Probe and CSV readings stay unclipped.
  const displayValues = useMemo(() => {
    if (fieldIsStress)
      return Object.values(elementValues ?? {}).flatMap((values) => Object.values(values))
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
  }, [fieldIsStress, elementValues, frame, displacementKey])
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
  const fieldOptions: FieldId[] = stressAvailable
    ? [...stressOptions, ...DISPLACEMENT_FIELDS]
    : DISPLACEMENT_FIELDS
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
  function exportCurve() {
    if (!index) return
    const { magnitudes, forces, count } = twoRowExport(historyRows, reverseY)
    if (!count) return
    const role = stepRole === 'body' ? 'body' : 'door'
    const width = index.reporting_width_mm ?? index.thickness
    const basis = index.force_normalization === 'per_mm' ? 'per_mm' : 'total'
    const step = curveStep ?? 'step'
    const filename =
      role +
      '-curve-' +
      id.slice(0, 8) +
      '-' +
      step.replace(/[^A-Za-z0-9_-]/g, '') +
      '-' +
      basis +
      (basis === 'total' ? '-W' + String(Number(width)) + 'mm' : '') +
      (reverseY ? '-force-flipped' : '') +
      '.csv'
    // Two numeric rows only: no preamble, header, index or time column. Adjacent
    // UI and the filename carry panel, step, unit, width and sign.
    download(filename, [magnitudes.join(','), forces.join(',')].join('\r\n') + '\r\n')
  }
  if (!job) return <main className="page">{t('run.opening')}</main>
  const disabled = index?.unavailable ?? []
  const displacementAvailable = !!frame && !!index && !disabled.includes('U')
  const stressUnavailable = !stressAvailable
  const probeText = (() => {
    if (!sel) return t('run.probePrompt')
    const identity = sel.instance + ' · ' + sel.kind + ' ' + sel.label
    if (sel.kind === 'element' && fieldIsStress) {
      const cell =
        sel.instance && sel.label !== undefined
          ? stressSampleCells.get(sel.instance + ':' + sel.label)
          : undefined
      if (!cell || !cell.samples.length)
        return identity + ' · ' + t('run.stressUnavailable')
      const maximum = Math.max(...cell.samples.map((sample) => sample.value))
      const samples = cell.samples
        .map(
          (sample) =>
            (sample.ip === undefined ? '' : 'IP ' + sample.ip + ': ') +
            sample.value.toPrecision(4) +
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
        samples
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
  const legendLabel = fieldIsStress
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
        {resultView && index && (
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
                disabled={!fieldOptions.length}
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
            {!fieldIsStress && !displacementAvailable && frame && (
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
                elementValues={fieldIsStress ? elementValues : undefined}
                resultComponent={fieldIsStress ? 'magnitude' : displacementKey}
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
            <div className="playback" data-testid="playback">
              <button
                className="play-toggle"
                aria-label={play ? t('run.pausePlayback') : t('run.playFrames')}
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
                  aria-label={t('run.frame', { current: n + 1, total: index.frames.length })}
                  type="range"
                  min={0}
                  max={index.frames.length - 1}
                  value={n}
                  onChange={(e) => {
                    playing(false)
                    deadline.current = 0
                    setN(+e.target.value)
                  }}
                />
                <div className="playback-status-row">
                  <span className="frame-count" data-testid="frame-count">
                    {n + 1} / {index.frames.length}
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
                      aria-label={t('run.loop')}
                      onChange={(e) => setLoop(e.target.checked)}
                    />
                    {t('run.loop')}
                  </label>
                </div>
              </div>
            </div>
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
              <h2>{t('run.forceDisplacement')}</h2>
              <p>{index.closing ? t('run.plotHelp') : t('run.plotHelpLegacy')}</p>
              {stepOptions.length > 1 && (
                <label>
                  {t('run.curveStep')}
                  <select
                    aria-label={t('run.curveStep')}
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
                  <button className="wide" onClick={exportCurve} data-testid="export-curve">
                    <Download />
                    {t('run.exportCurveTwoRows')}
                  </button>
                  <small data-testid="export-basis">
                    {t('run.exportBasis', {
                      panel: stepInstance,
                      step: curveStepName ?? 'Closing',
                      unit: index.force_unit,
                      width: String(index.reporting_width_mm ?? index.thickness),
                      sign: reverseY ? t('run.exportFlipped') : t('run.exportAsMeasured'),
                    })}
                  </small>
                </>
              ) : (
                <p>{t('run.historyUnavailable')}</p>
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
              <a className="button" href={artifact(id, 'history.csv')} download>
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
                  <a className="asset" key={f} href={artifact(id, f)} download>
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
