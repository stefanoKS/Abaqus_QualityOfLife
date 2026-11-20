import { useEffect, useState } from 'react'
import {
  Plus,
  Layers3,
  FolderOpen,
  ChevronRight,
  Activity,
  Boxes,
  ListFilter,
  History,
  Copy,
  FileText,
  ChartNoAxesCombined,
  Square,
  RotateCcw,
} from 'lucide-react'
import { request, elapsed, go, err, type Summary, type Job, type Revision } from './api'
import { labelFrom, useI18n } from './i18n'
import { ACTIVE_POLL_MS, IDLE_POLL_MS, anyActive } from './shared/hooks/polling'

export function Badge({ value }: { value: string }) {
  const { t } = useI18n()
  return (
    <span
      className={
        'badge ' +
        (value === 'Completed'
          ? 'good'
          : value === 'Failed'
            ? 'bad'
            : value === 'Running' || value === 'Processing results'
              ? 'live'
              : '')
      }
      data-status={value}
      title={value}
    >
      {labelFrom(t, 'state', value)}
    </span>
  )
}

export function JobActions({
  job,
  refresh,
  notify,
}: {
  job: Job
  refresh: () => void
  notify: (s: string) => void
}) {
  const { t } = useI18n()
  async function act(kind: string) {
    try {
      if (kind === 'duplicate') {
        const rev = await request<Revision>('/api/jobs/' + job.id + '/duplicate', 'POST')
        go('workspace/' + rev.id)
      } else {
        await request('/api/jobs/' + job.id + '/' + kind, 'POST')
        refresh()
      }
    } catch (e) {
      notify(err(e))
    }
  }
  return (
    <div className="run-actions">
      {job.status === 'Completed' && job.mode !== 'BUILD' && (
        <button onClick={() => go('results/' + job.id)}>
          <ChartNoAxesCombined />
          {t('dashboard.jobResults')}
        </button>
      )}
      <button onClick={() => go('setup/' + job.id)}>
        <FileText />
        {t('dashboard.jobSetup')}
      </button>
      <button
        title={t('dashboard.duplicate')}
        aria-label={t('dashboard.duplicate')}
        onClick={() => act('duplicate')}
      >
        <Copy />
      </button>
      <button
        title={t('dashboard.diagnostics')}
        aria-label={t('dashboard.diagnostics')}
        onClick={() => go('diagnostics/' + job.id)}
      >
        <Activity />
      </button>
      {!['Completed', 'Failed', 'Cancelled', 'Cancel requested'].includes(job.status) && (
        <button
          title={t('dashboard.cancelJob')}
          aria-label={t('dashboard.cancelJob')}
          onClick={() => act('cancel')}
        >
          <Square />
        </button>
      )}
      {job.solver === 'Succeeded' && ['Failed', 'Cancelled'].includes(job.extraction) && (
        <button onClick={() => act('retry')}>
          <RotateCcw />
          {t('dashboard.retryExtraction')}
        </button>
      )}
    </div>
  )
}

export default function Dashboard({ notify }: { notify: (s: string) => void }) {
  const { t, formatDate } = useI18n()
  const [projects, ps] = useState<Summary[]>([]),
    [runs, rs] = useState<Job[]>([])
  const [filter, pf] = useState(''),
    [status, sf] = useState(''),
    [creating, create] = useState(false),
    [name, nm] = useState(''),
    [dim, dm] = useState('2D')
  const [busy, setBusy] = useState(false)
  async function refresh() {
    try {
      const [a, b] = await Promise.all([
        request<Summary[]>('/api/projects'),
        request<Job[]>('/api/runs'),
      ])
      ps(a)
      rs(b)
    } catch (e) {
      notify(err(e))
    }
  }
  useEffect(() => {
    void refresh()
  }, [notify])
  // Faster cadence only while a run can still change; an idle dashboard settles to
  // a slow refresh instead of polling every 1.4 s forever.
  const active = anyActive(runs)
  useEffect(() => {
    const id = setInterval(refresh, active ? ACTIVE_POLL_MS : IDLE_POLL_MS)
    return () => clearInterval(id)
  }, [active])
  async function add(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const r = await request<Revision>('/api/projects', 'POST', {
        name: name.trim(),
        dimension: dim,
      })
      go('workspace/' + r.id)
    } catch (e) {
      notify(err(e))
    } finally {
      setBusy(false)
    }
  }
  const visible = runs.filter(
    (r) => (!filter || filter === r.project) && (!status || status === r.status),
  )
  return (
    <main className="dashboard page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            <Boxes size={15} /> {t('dashboard.eyebrow')}
          </div>
          <h1>{t('dashboard.title')}</h1>
        </div>
        <button className="primary" onClick={() => create(!creating)}>
          <Plus />
          {t('dashboard.newProject')}
        </button>
      </div>
      {creating && (
        <form className="create-form card" onSubmit={add}>
          <label>
            {t('dashboard.projectName')}
            <input
              autoFocus
              required
              maxLength={100}
              value={name}
              onChange={(e) => nm(e.target.value)}
            />
          </label>
          <label>
            {t('dashboard.startingGeometry')}
            <select value={dim} onChange={(e) => dm(e.target.value)}>
              <option value="2D">{t('dashboard.section2d')}</option>
              <option value="3D">{t('dashboard.section3d')}</option>
            </select>
          </label>
          <button className="primary" disabled={busy || !name.trim()}>
            {t('dashboard.createProject')}
          </button>
          <button type="button" onClick={() => create(false)}>
            {t('common.cancel')}
          </button>
        </form>
      )}
      <h2>
        <FolderOpen />
        {t('dashboard.projects')} <small>{projects.length}</small>
      </h2>
      <div className="project-cards">
        {projects.map((p) => (
          <button key={p.id} className="project-card" onClick={() => go('workspace/' + p.revision)}>
            <span className="project-symbol">
              <Layers3 />
            </span>
            <span>
              <strong>{p.name}</strong>
              <small>
                {p.dimension} · {t('dashboard.revision', { number: p.number })} ·{' '}
                {formatDate(p.created)}
              </small>
            </span>
            <ChevronRight />
          </button>
        ))}
      </div>
      <section className="card run-card">
        <div className="card-heading">
          <h2>
            <History />
            {t('dashboard.runs')}
          </h2>
          <div className="filters">
            <ListFilter />
            <select
              aria-label={t('dashboard.filterProject')}
              value={filter}
              onChange={(e) => pf(e.target.value)}
            >
              <option value="">{t('dashboard.allProjects')}</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <select
              aria-label={t('dashboard.filterStatus')}
              value={status}
              onChange={(e) => sf(e.target.value)}
            >
              <option value="">{t('dashboard.allStatuses')}</option>
              {[...new Set(runs.map((r) => r.status).concat(status || []))].map((s) => (
                /* The option value stays the raw contract value; only the label is translated. */
                <option key={s} value={s}>
                  {labelFrom(t, 'state', s)}
                </option>
              ))}
            </select>
          </div>
        </div>
        {visible.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {[
                    t('dashboard.colRun'),
                    t('dashboard.colState'),
                    t('dashboard.colSubmitted'),
                    t('dashboard.colElapsed'),
                    t('dashboard.colOutput'),
                  ].map((heading) => (
                    <th key={heading}>{heading}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <strong>{r.name}</strong>
                      <small>
                        {r.project_name} · {r.dimension} · Rev {r.number}
                      </small>
                      <small className="mode-label">
                        {r.mode === 'DEMO' ? t('demo.notice') : r.mode}
                      </small>
                    </td>
                    <td>
                      <Badge value={r.status} />
                      <small>
                        {labelFrom(t, 'phase', r.step || r.phase)}
                        {r.increment != null
                          ? ' · ' + t('dashboard.increment', { value: r.increment })
                          : ''}
                      </small>
                    </td>
                    <td>{formatDate(r.created)}</td>
                    <td>{elapsed(r)}</td>
                    <td>
                      <JobActions job={r} notify={notify} refresh={refresh} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">
            <History />
            <h3>{runs.length ? t('dashboard.noMatchingRuns') : t('dashboard.noRuns')}</h3>
            <p>{runs.length ? t('dashboard.noMatchingHint') : t('dashboard.noRunsHint')}</p>
          </div>
        )}
      </section>
    </main>
  )
}
