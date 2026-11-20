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
import {
  request,
  date,
  elapsed,
  go,
  err,
  demoNotice,
  type Summary,
  type Job,
  type Revision,
} from './api'

export function Badge({ value }: { value: string }) {
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
    >
      {value}
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
          Results
        </button>
      )}
      <button onClick={() => go('setup/' + job.id)}>
        <FileText />
        Setup
      </button>
      <button title="Duplicate setup" aria-label="Duplicate setup" onClick={() => act('duplicate')}>
        <Copy />
      </button>
      <button
        title="Open diagnostics"
        aria-label="Open diagnostics"
        onClick={() => go('diagnostics/' + job.id)}
      >
        <Activity />
      </button>
      {!['Completed', 'Failed', 'Cancelled', 'Cancel requested'].includes(job.status) && (
        <button title="Cancel job" aria-label="Cancel job" onClick={() => act('cancel')}>
          <Square />
        </button>
      )}
      {job.solver === 'Succeeded' && ['Failed', 'Cancelled'].includes(job.extraction) && (
        <button onClick={() => act('retry')}>
          <RotateCcw />
          Retry extraction
        </button>
      )}
    </div>
  )
}
export default function Dashboard({ notify }: { notify: (s: string) => void }) {
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
    const id = setInterval(refresh, 1400)
    return () => clearInterval(id)
  }, [])
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
            <Boxes size={15} /> LOCAL WORKBENCH
          </div>
          <h1>Simulation dashboard</h1>
        </div>
        <button className="primary" onClick={() => create(!creating)}>
          <Plus />
          New project
        </button>
      </div>
      {creating && (
        <form className="create-form card" onSubmit={add}>
          <label>
            Project name
            <input
              autoFocus
              required
              maxLength={100}
              value={name}
              onChange={(e) => nm(e.target.value)}
            />
          </label>
          <label>
            Starting geometry
            <select value={dim} onChange={(e) => dm(e.target.value)}>
              <option value="2D">2D hollow bulb section</option>
              <option value="3D">3D extruded segment</option>
            </select>
          </label>
          <button className="primary" disabled={busy || !name.trim()}>
            Create project
          </button>
          <button type="button" onClick={() => create(false)}>
            Cancel
          </button>
        </form>
      )}
      <h2>
        <FolderOpen />
        Projects <small>{projects.length}</small>
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
                {p.dimension} · Revision {p.number} · {date(p.created)}
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
            Simulation runs
          </h2>
          <div className="filters">
            <ListFilter />
            <select
              aria-label="Filter by project"
              value={filter}
              onChange={(e) => pf(e.target.value)}
            >
              <option value="">All projects</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <select
              aria-label="Filter by status"
              value={status}
              onChange={(e) => sf(e.target.value)}
            >
              <option value="">All statuses</option>
              {[...new Set(runs.map((r) => r.status).concat(status || []))].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
        </div>
        {visible.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {['Run / project', 'State', 'Submitted', 'Elapsed', 'Setup & output'].map((t) => (
                    <th key={t}>{t}</th>
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
                        {r.mode === 'DEMO' ? demoNotice : 'ABAQUS'}
                      </small>
                    </td>
                    <td>
                      <Badge value={r.status} />
                      <small>
                        {r.step || r.phase}
                        {r.increment != null ? ' · Inc ' + r.increment : ''}
                      </small>
                    </td>
                    <td>{date(r.created)}</td>
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
            <h3>{runs.length ? 'No matching runs' : 'No simulations submitted'}</h3>
            <p>
              {runs.length
                ? 'Change the project or status filter.'
                : 'Open a project, generate its input deck, and submit a run from Review / Run.'}
            </p>
          </div>
        )}
      </section>
    </main>
  )
}
