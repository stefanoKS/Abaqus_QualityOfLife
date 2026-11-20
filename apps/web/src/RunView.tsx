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
import { artifact, date, demoNotice, elapsed, err, go, request, type Job } from './api'
import { Badge, JobActions } from './Dashboard'
import Viewport from './Viewport'
import type { Picked, ResultFrame, ResultInstance } from './viewportModel'
import { Plot } from './Plot'

interface Index {
  notice: string
  mode: string
  frames: { time: number; file: string }[]
  history: { time: number; displacement: number; force: number }[]
  force_unit: string
  instances: ResultInstance[]
  unavailable: string[]
  thickness: number
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
  const [job, setJob] = useState<Job | null>(null),
    [tick, refresh] = useState(0),
    [index, setIndex] = useState<Index | null>(null)
  const [n, setN] = useState(0),
    [frame, setFrame] = useState<ResultFrame | null>(null),
    [play, playing] = useState(false)
  const [sel, select] = useState<Picked | null>(null),
    [mode, setMode] = useState<'node' | 'element'>('node'),
    [deformed, deform] = useState(true)
  const [logs, setLogs] = useState(''),
    [logFile, setLogFile] = useState('worker.log')
  useEffect(() => {
    const ctrl = new AbortController()
    const poll = () =>
      request<Job>('/api/jobs/' + id, 'GET', undefined, ctrl.signal)
        .then(setJob)
        .catch((e) => {
          if (!ctrl.signal.aborted) notify(err(e))
        })
    void poll()
    const t = setInterval(poll, 1200)
    return () => {
      ctrl.abort()
      clearInterval(t)
    }
  }, [id, tick, notify])
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
    request<ResultFrame>(artifact(id, index.frames[n].file), 'GET', undefined, ac.signal)
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
    const t = setTimeout(() => {
      if (n + 1 === index.frames.length) {
        playing(false)
      } else setN(n + 1)
    }, 220)
    return () => clearTimeout(t)
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
    const t = setInterval(poll, 2000)
    return () => {
      clearInterval(t)
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
      (best, row, i) =>
        Math.abs(row.time - time) < Math.abs(samples[best].time - time) ? i : best,
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
  if (!job) return <main className="page">Opening run…</main>
  const probe =
    sel?.kind === 'node' &&
    sel.instance &&
    frame?.displacements[sel.instance]?.find((r) => r[0] === sel.label)
  return (
    <main className="page run-view">
      <div className="crumb">
        <button onClick={() => go('dashboard')}>Dashboard</button>
        <ChevronRight />
        {resultView ? 'Results' : 'Run diagnostics'}
      </div>
      <div className="page-heading">
        <div>
          <h1>{job.name}</h1>
          <div className="subtitle">
            {job.project_name}
            <i />
            {job.dimension}
            <i />
            Revision {job.number}
          </div>
        </div>
        <JobActions job={job} notify={notify} refresh={() => refresh((x) => x + 1)} />
      </div>
      <div className="run-banner">
        <Badge value={job.status} />
        <span>{job.mode === 'DEMO' ? demoNotice : job.mode}</span>
        <span className="spacer" />
        <Clock />
        {elapsed(job)}
      </div>
      {resultView && index ? (
        <div className="result-grid">
          <section className="card">
            <div className="panel-title">
              <ScanLine />
              Displacement field
              <div className="spacer" />
              <select
                aria-label="Probe mode"
                value={mode}
                onChange={(e) => {
                  setMode(e.target.value as 'node' | 'element')
                  select(null)
                }}
              >
                <option value="node">Probe node</option>
                <option value="element">Probe element</option>
              </select>
            </div>
            <div className="result-viewport">
              <Viewport
                display={null}
                dimension="2D"
                mode={mode}
                selection={sel}
                onSelect={select}
                results={{ instances: index.instances, frame }}
                deformed={deformed}
              />
            </div>
            <div className="playback">
              <button
                aria-label={play ? 'Pause playback' : 'Play frames'}
                onClick={() => {
                  if (!play && n === index.frames.length - 1) setN(0)
                  playing(!play)
                }}
              >
                {play ? <Pause /> : <Play />}
              </button>
              <label>
                Frame {n + 1} / {index.frames.length}
                <input
                  aria-label="Result frame"
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
                Deformed geometry · 1×
              </label>
              <span>
                {sel
                  ? sel.instance + ' · ' + sel.kind + ' ' + sel.label
                  : 'Select a node or element to probe'}
                {sel?.kind === 'node' &&
                  (probe
                    ? ' · |U| ' + Math.hypot(...probe.slice(1)).toPrecision(4) + ' mm'
                    : ' · U unavailable')}
              </span>
            </div>
          </section>
          <aside className="card">
            <div className="panel-title">
              <Activity />
              Panel response
            </div>
            <div className="property-body">
              <h2>Force–displacement</h2>
              <p>Signed panel reaction along Y. Select a sample to open its nearest frame.</p>
              {index.history.length ? (
                <Plot
                  x={xy.x}
                  y={xy.y}
                  xlabel="Panel U2 (mm)"
                  ylabel={'Panel RF2 (' + index.force_unit + ')'}
                  active={nearest(index.history, index.frames[n].time)}
                  onPick={plotPick}
                />
              ) : (
                <p>Panel history unavailable.</p>
              )}
              <dl>
                <div>
                  <dt>Thickness</dt>
                  <dd>{index.thickness} mm</dd>
                </div>
                <div>
                  <dt>Force unit</dt>
                  <dd>{index.force_unit}</dd>
                </div>
              </dl>
              <a className="button" href={artifact(id, 'history.csv')} download>
                <Download />
                Download history CSV
              </a>
              {index.unavailable.length > 0 && (
                <>
                  <h3>Unavailable outputs</h3>
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
              Run diagnostics
            </div>
            <div className="property-body">
              <h2>{job.phase}</h2>
              {job.diagnostic && <p className="error-text">{job.diagnostic}</p>}
              <dl>
                {Object.entries({
                  Solver: job.solver,
                  Extraction: job.extraction,
                  Submitted: date(job.created),
                  Started: job.started ? date(job.started) : '—',
                  Finished: job.ended ? date(job.ended) : '—',
                  Step: job.step ?? '—',
                  Increment: job.increment ?? '—',
                  'Step time (s)': job.step_time ?? '—',
                  'Solver exit': job.exit_code ?? '—',
                  'Extractor exit': job.extraction_exit ?? '—',
                  'Process ID': job.pid ?? '—',
                  'Last heartbeat': job.heartbeat ? date(job.heartbeat) : '—',
                  'Job ID': id,
                  'Input SHA-256': job.input_hash ?? 'Preparing',
                }).map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </section>
          <aside className="card">
            <div className="panel-title">
              <Archive />
              Run artifacts
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
              {!job.manifest.length && <p>Artifacts appear as the worker processes this job.</p>}
            </div>
          </aside>
          <div className="card log-card">
            <div className="panel-title">
              <Terminal />
              Log tail
              <div className="spacer" />
              <select
                aria-label="Log file"
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
            <pre>{logs || 'Waiting for log output…'}</pre>
          </div>
        </div>
      )}
    </main>
  )
}
