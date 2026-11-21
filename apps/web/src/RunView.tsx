import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  Archive,
  ChevronRight,
  Clock,
  Download,
  FileText,
  Pause,
  Play,
  ScanLine,
  Terminal,
} from 'lucide-react'
import { artifact, elapsed, err, go, request, type Job } from './api'
import { Badge, JobActions } from './Dashboard'
import Viewport from './Viewport'
import type { Picked, ResultFrame, ResultInstance } from './viewportModel'
import { Plot } from './Plot'
import { labelFrom, useI18n } from './i18n'
import { ACTIVE_POLL_MS, IDLE_POLL_MS, anyActive } from './shared/hooks/polling'

interface HistoryRow {
  time: number
  step?: string | null
  displacement: number
  force: number
  total_force_N?: number
  u1?: number
  u2?: number
  rf1?: number
  rf2?: number
}

interface Closing {
  panel?: string
  instance?: string
  direction?: number[]
  distance_mm?: number
  measure_from_step_start?: boolean
  steps?: { name: string; role: string }[]
}

interface Index {
  notice: string
  mode: string
  frames: { time: number; step?: string; file: string }[]
  history: HistoryRow[]
  force_unit: string
  instances: ResultInstance[]
  unavailable: string[]
  thickness: number
  averaging?: string
  force_normalization?: 'total' | 'per_mm'
  closing?: Closing | null
  history_components?: string[]
}

/** Fields the extractor may publish in addition to displacements. */
interface Frame extends ResultFrame {
  fields?: Record<string, unknown>
  unavailable?: string[]
}

type Component = 'magnitude' | 'U1' | 'U2' | 'U3'

const COMPONENTS: Component[] = ['magnitude', 'U1', 'U2', 'U3']

/**
 * Display-only sign controls. They transform the projected curve for reading
 * and for the exported CSV; the stored result artifacts are never rewritten.
 */
function displayedCurve(history: HistoryRow[], reverseX: boolean, reverseY: boolean) {
  return {
    x: history.map((row) => (reverseX ? -row.displacement : row.displacement)),
    y: history.map((row) => (reverseY ? -row.force : row.force)),
  }
}

function csvCell(value: unknown) {
  const text = value === undefined || value === null ? '' : String(value)
  return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text
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
function nearestIndex<T extends { time: number; step?: string | null }>(
  samples: T[],
  time: number,
  step?: string | null,
) {
  if (!samples.length) return 0
  const eligible = samples
    .map((sample, index) => ({ sample, index }))
    .filter(({ sample }) => !step || !sample.step || sample.step === step)
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
  const [component, setComponent] = useState<Component>('magnitude')
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
  useEffect(() => {
    if (!index) return
    const ac = new AbortController()
    setFrame(null)
    request<Frame>(artifact(id, index.frames[n].file), 'GET', undefined, ac.signal)
      .then(setFrame)
      .catch((e) => {
        if (!ac.signal.aborted) {
          playing(false)
          notify(err(e))
        }
      })
    return () => ac.abort()
  }, [index, n, id, notify])
  useEffect(() => {
    if (!play || !frame || !index) return
    const t2 = setTimeout(() => {
      if (n + 1 === index.frames.length) {
        playing(false)
      } else setN(n + 1)
    }, 220)
    return () => clearTimeout(t2)
  }, [play, n, index, frame])
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
  const closingStep = index?.closing?.steps?.[0]?.name ?? null
  // Open on the door-closing step by default in both modes.
  useEffect(() => {
    if (!index) return
    const first = index.frames.findIndex((frame) => !closingStep || frame.step === closingStep)
    setN(Math.max(0, first))
  }, [index, closingStep])
  const curve = useMemo(
    () => displayedCurve(index?.history ?? [], reverseX, reverseY),
    [index, reverseX, reverseY],
  )
  const frameStep = index?.frames[n]?.step
  const activeSample =
    index && index.frames.length ? nearestIndex(index.history, index.frames[n].time, frameStep) : undefined
  const plotPick = useCallback(
    (i: number) => {
      if (index) {
        playing(false)
        setN(nearestIndex(index.frames, index.history[i].time, index.history[i].step))
      }
    },
    [index],
  )
  function exportCurve() {
    if (!index) return
    const direction = index.closing?.direction ?? [0, -1]
    const provenance = index.mode === 'DEMO' ? 'DEMO synthetic' : 'ABAQUS solver'
    const header = [
      ['# Abaqus QOL displayed door response'],
      ['# panel', index.closing?.panel ?? 'panel'],
      ['# instance', index.closing?.instance ?? 'PANEL-1'],
      ['# closing_step', closingStep ?? 'all steps'],
      ['# direction', direction.join(' ')],
      ['# length_unit', 'mm'],
      ['# force_unit', index.force_unit],
      ['# x_sign', reverseX ? '-1' : '1'],
      ['# y_sign', reverseY ? '-1' : '1'],
      ['# normalization', index.force_normalization ?? 'total'],
      ['# provenance', provenance],
      ['# note', 'Displayed values only. Raw signed components follow; artifacts are unchanged.'],
    ].map((row) => row.map(csvCell).join(','))
    header.push(
      [
        'displayed_displacement_mm',
        'displayed_force_' + index.force_unit,
        'time_s',
        'step',
        'raw_u1_mm',
        'raw_u2_mm',
        'raw_rf1_N',
        'raw_rf2_N',
        'normalization',
        'provenance',
      ].join(','),
    )
    index.history.forEach((row, i) => {
      header.push(
        [
          curve.x[i],
          curve.y[i],
          row.time,
          row.step ?? '',
          row.u1 ?? '',
          row.u2 ?? '',
          row.rf1 ?? '',
          row.rf2 ?? '',
          index.force_normalization ?? 'total',
          provenance,
        ]
          .map(csvCell)
          .join(','),
      )
    })
    download('door-response-' + id.slice(0, 8) + '.csv', header.join('\r\n') + '\r\n')
  }
  if (!job) return <main className="page">{t('run.opening')}</main>
  const disabled = index?.unavailable ?? []
  const displacementAvailable = !!frame && !!index && !disabled.includes('U')
  const probe =
    sel?.kind === 'node' &&
    sel.instance &&
    frame?.displacements[sel.instance]?.find((r) => r[0] === sel.label)
  const probeText = (() => {
    if (!sel) return t('run.probePrompt')
    const identity = sel.instance + ' · ' + sel.kind + ' ' + sel.label
    if (sel.kind !== 'node') return identity
    if (!probe) return identity + ' · ' + t('run.uUnavailable')
    if (component === 'magnitude')
      return identity + ' · |U| ' + Math.hypot(...probe.slice(1)).toPrecision(4) + ' mm'
    const axis = component === 'U1' ? 1 : component === 'U2' ? 2 : 3
    return (
      identity +
      ' · ' +
      component +
      ' ' +
      (probe[axis] ?? 0).toPrecision(4) +
      ' mm'
    )
  })()
  const componentLabel = component === 'magnitude' ? t('run.magnitude') : component
  const legendLabel = t('run.legendTitle', { variable: 'U', component: componentLabel })
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
        <span className="spacer" />
        <Clock />
        {elapsed(job)}
      </div>
      {resultView && index ? (
        <div className="result-grid">
          <section className="card">
            <div className="panel-title">
              <ScanLine />
              {t('run.displacementField')}
              <div className="spacer" />
              <select
                aria-label={t('run.variable')}
                value="U"
                onChange={() => undefined}
                disabled={!displacementAvailable}
              >
                <option value="U">U</option>
              </select>
              <select
                aria-label={t('run.component')}
                value={component}
                onChange={(e) => {
                  setComponent(e.target.value as Component)
                  select(null)
                }}
                disabled={!displacementAvailable}
              >
                {COMPONENTS.map((option) => (
                  <option key={option} value={option}>
                    {option === 'magnitude' ? t('run.magnitude') : '|' + option + '|'}
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
                <option value="node">{t('run.probeNode')}</option>
                <option value="element">{t('run.probeElement')}</option>
              </select>
            </div>
            <div className="result-viewport">
              <Viewport
                display={null}
                dimension="2D"
                mode={mode}
                selection={sel}
                onSelect={select}
                results={displacementAvailable ? { instances: index.instances, frame } : null}
                deformed={deformed}
                resultComponent={component}
                resultLabel={legendLabel}
              />
            </div>
            <div className="playback">
              <button
                aria-label={play ? t('run.pausePlayback') : t('run.playFrames')}
                onClick={() => {
                  if (!play && n === index.frames.length - 1) setN(0)
                  playing(!play)
                }}
              >
                {play ? <Pause /> : <Play />}
              </button>
              <label>
                {t('run.frame', { current: n + 1, total: index.frames.length })}
                <input
                  aria-label={t('run.frame', { current: n + 1, total: index.frames.length })}
                  type="range"
                  min={0}
                  max={index.frames.length - 1}
                  value={n}
                  onChange={(e) => {
                    playing(false)
                    setN(+e.target.value)
                  }}
                />
              </label>
              <span>{index.frames[n].time.toFixed(3)} s</span>
            </div>
            <div className="legend">
              <label className="check">
                <input
                  type="checkbox"
                  checked={deformed}
                  onChange={(e) => deform(e.target.checked)}
                />
                {t('run.deformed')}
              </label>
              <span>{probeText}</span>
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
              {index.history.length ? (
                <>
                  <Plot
                    x={curve.x}
                    y={curve.y}
                    xlabel={index.closing ? t('run.doorTravel') : t('run.panelU2')}
                    ylabel={
                      index.closing
                        ? t('run.doorReaction', { unit: index.force_unit })
                        : t('run.panelRF2', { unit: index.force_unit })
                    }
                    active={activeSample}
                    onPick={plotPick}
                  />
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
                  <button className="wide" onClick={exportCurve}>
                    <Download />
                    {t('run.exportCurve')}
                  </button>
                </>
              ) : (
                <p>{t('run.historyUnavailable')}</p>
              )}
              <dl>
                <div>
                  <dt>{t('run.thickness')}</dt>
                  <dd>{index.thickness} mm</dd>
                </div>
                <div>
                  <dt>{t('run.forceUnit')}</dt>
                  <dd>{index.force_unit}</dd>
                </div>
                {index.closing?.direction && (
                  <div>
                    <dt>{t('run.closingDirection')}</dt>
                    <dd>{index.closing.direction.map((v) => Number(v).toFixed(3)).join(', ')}</dd>
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
      ) : (
        <div className="result-grid">
          <section className="card">
            <div className="panel-title">
              <Terminal />
              {t('run.diagnosticsTitle')}
            </div>
            <div className="property-body">
              <h2>{labelFrom(t, 'phase', job.phase)}</h2>
              {job.diagnostic && <p className="error-text">{job.diagnostic}</p>}
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
      )}
    </main>
  )
}
