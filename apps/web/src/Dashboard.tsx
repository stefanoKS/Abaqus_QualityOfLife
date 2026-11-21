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
  elapsed,
  go,
  err,
  type Group,
  type Job,
  type Revision,
  type RevisionSummary,
} from './api'
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
  const [groups, gs] = useState<Group[]>([]),
    [runs, rs] = useState<Job[]>([])
  const [filter, pf] = useState(''),
    [status, sf] = useState(''),
    [creatingGroup, createGroupForm] = useState(false),
    [name, nm] = useState(''),
    [firstModel, first] = useState(''),
    [dim, dm] = useState('2D')
  const [modelGroup, setModelGroup] = useState<string | null>(null),
    [modelName, mn] = useState(''),
    [modelDim, md] = useState('2D')
  const [openRevisions, revealRevisions] = useState<string | null>(null),
    [history, setHistory] = useState<RevisionSummary[]>([])
  const [busy, setBusy] = useState(false)
  async function refresh() {
    try {
      const [a, b] = await Promise.all([request<Group[]>('/api/groups'), request<Job[]>('/api/runs')])
      gs(a)
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
  const projects = groups.flatMap((group) => group.models)
  async function addGroup(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const group = await request<Group>('/api/groups', 'POST', { name: name.trim() })
      // A group without a model has nothing to open, so the first model is
      // created in the same action; it falls back to the project name.
      const r = await request<Revision>('/api/projects', 'POST', {
        name: (firstModel.trim() || name).trim(),
        dimension: dim,
        group: group.id,
      })
      createGroupForm(false)
      nm('')
      first('')
      go('workspace/' + r.id)
    } catch (e) {
      notify(err(e))
    } finally {
      setBusy(false)
    }
  }
  async function addModel(e: React.FormEvent, group: string) {
    e.preventDefault()
    setBusy(true)
    try {
      const r = await request<Revision>('/api/projects', 'POST', {
        name: modelName.trim(),
        dimension: modelDim,
        group,
      })
      setModelGroup(null)
      mn('')
      await refresh()
      go('workspace/' + r.id)
    } catch (e) {
      notify(err(e))
    } finally {
      setBusy(false)
    }
  }
  async function duplicateModel(id: string) {
    try {
      await request<Revision>('/api/projects/' + id + '/duplicate', 'POST', {})
      notify(t('dashboard.modelDuplicated'))
      await refresh()
    } catch (e) {
      notify(err(e))
    }
  }
  async function showRevisions(id: string) {
    if (openRevisions === id) {
      revealRevisions(null)
      return
    }
    try {
      setHistory(await request<RevisionSummary[]>('/api/projects/' + id + '/revisions'))
      revealRevisions(id)
    } catch (e) {
      notify(err(e))
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
        <button className="primary" onClick={() => createGroupForm(!creatingGroup)}>
          <Plus />
          {t('dashboard.newProject')}
        </button>
      </div>
      {creatingGroup && (
        <form className="create-form card" onSubmit={addGroup}>
          <p className="create-hint">{t('dashboard.groupHint')}</p>
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
            {t('dashboard.modelName')}
            <input
              maxLength={100}
              placeholder={name}
              value={firstModel}
              onChange={(e) => first(e.target.value)}
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
          <button type="button" onClick={() => createGroupForm(false)}>
            {t('common.cancel')}
          </button>
        </form>
      )}
      <h2>
        <FolderOpen />
        {t('dashboard.projects')} <small>{groups.length}</small>
      </h2>
      <div className="group-list">
        {groups.map((group) => (
          <section className="group-card card" key={group.id}>
            <div className="group-heading">
              <span className="group-symbol">
                <FolderOpen />
              </span>
              <div>
                <strong>{group.name}</strong>
                <small>
                  {t('dashboard.modelsCount', { count: group.models.length })} ·{' '}
                  {formatDate(group.created)}
                </small>
              </div>
              <div className="spacer" />
              <button onClick={() => setModelGroup(modelGroup === group.id ? null : group.id)}>
                <Plus />
                {t('dashboard.newModel')}
              </button>
            </div>
            {modelGroup === group.id && (
              <form className="create-form inline" onSubmit={(e) => addModel(e, group.id)}>
                <label>
                  {t('dashboard.modelName')}
                  <input
                    autoFocus
                    required
                    maxLength={100}
                    value={modelName}
                    onChange={(e) => mn(e.target.value)}
                  />
                </label>
                <label>
                  {t('dashboard.startingGeometry')}
                  <select value={modelDim} onChange={(e) => md(e.target.value)}>
                    <option value="2D">{t('dashboard.section2d')}</option>
                    <option value="3D">{t('dashboard.section3d')}</option>
                  </select>
                </label>
                <button className="primary" disabled={busy || !modelName.trim()}>
                  {t('dashboard.createModel')}
                </button>
                <button type="button" onClick={() => setModelGroup(null)}>
                  {t('common.cancel')}
                </button>
              </form>
            )}
            {group.models.length ? (
              <div className="project-cards">
                {group.models.map((p) => (
                  <div className="model-entry" key={p.id}>
                    <button className="project-card" onClick={() => go('workspace/' + p.revision)}>
                      <span className="project-symbol">
                        <Layers3 />
                      </span>
                      <span>
                        <strong>{p.name}</strong>
                        <small>
                          {p.dimension} · {t('dashboard.revision', { number: p.number })} ·{' '}
                          {t('dashboard.revisionCount', { count: p.revisions })}
                        </small>
                      </span>
                      <ChevronRight />
                    </button>
                    <div className="model-tools">
                      <button
                        onClick={() => showRevisions(p.id)}
                        aria-expanded={openRevisions === p.id}
                        title={t('dashboard.revisions')}
                      >
                        <History />
                        {t('dashboard.revisions')}
                      </button>
                      <button
                        onClick={() => duplicateModel(p.id)}
                        title={t('dashboard.duplicateModel')}
                        aria-label={t('dashboard.duplicateModel') + ' · ' + p.name}
                      >
                        <Copy />
                      </button>
                    </div>
                    {openRevisions === p.id && (
                      <div className="revision-list">
                        {history.map((row) => (
                          <button key={row.id} onClick={() => go('workspace/' + row.id)}>
                            {t('dashboard.revision', { number: row.number })}
                            <small>{formatDate(row.created)}</small>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="empty-line">{t('dashboard.noModels')}</p>
            )}
          </section>
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
