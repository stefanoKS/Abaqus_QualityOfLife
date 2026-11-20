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

interface Index {
  notice: string
  mode: string
  frames: { time: number; file: string }[]
  history: { time: number; displacement: number; force: number }[]
  force_unit: string
  instances: ResultInstance[]
  unavailable: string[]
  thickness: number
  averaging?: string
}

/** Fields the extractor may publish in addition to displacements. */
interface Frame extends ResultFrame {
  fields?: Record<string, unknown>
  unavailable?: string[]
}

type Component = 'magnitude' | 'U1' | 'U2' | 'U3'

const COMPONENTS: Component[] = ['magnitude', 'U1', 'U2', 'U3']

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
  const xy = useMemo(
    () => ({
      x: index?.history.map((h) => h.displacement) ?? [],
      y: index?.history.map((h) => h.force) ?? [],
    }),
    [index],
  )
  const nearest = (samples: { time: number }[], time: number) =>
    samples.reduce(
      (best, row, i) => (Math.abs(row.time - time) < Math.abs(samples[best].time - time) ? i : best),
      0,
    )
  const plotPick = useCallback(
    (i: number) => {
      if (index) {
        playing(false)
        setN(nearest(index.frames, index.history[i].time))
      }
    },
    [index],
  )
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
              {t('run.panelResponse')}
            </div>
            <div className="property-body">
              <h2>{t('run.forceDisplacement')}</h2>
              <p>{t('run.plotHelp')}</p>
              {index.history.length ? (
                <Plot
                  x={xy.x}
                  y={xy.y}
                  xlabel={t('run.panelU2')}
                  ylabel={t('run.panelRF2', { unit: index.force_unit })}
                  active={nearest(index.history, index.frames[n].time)}
                  onPick={plotPick}
                />
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
