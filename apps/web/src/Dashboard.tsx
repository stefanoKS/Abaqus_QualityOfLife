import { useEffect, useRef, useState } from 'react'
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
  Archive,
  ArchiveRestore,
  Trash2,
  FilePlus2,
  XCircle,
} from 'lucide-react'
import {
  request,
  elapsed,
  go,
  err,
  type Group,
  type DeletionInfo,
  type Job,
  type Revision,
  type RevisionSummary,
} from './api'
import { labelFrom, useI18n } from './i18n'
import { useCompatibility } from './Compat'
import { ACTIVE_POLL_MS, IDLE_POLL_MS, anyActive } from './shared/hooks/polling'
import { FileBar } from './features/files/FileBar'

/** One user action: a project group and its first model, created atomically. */
type GroupCreated = { group: Group; model: Revision }

function requestToken() {
  try {
    return crypto.randomUUID()
  } catch {
    // Older embedded browsers: a UUID-shaped random string is sufficient here.
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0
      return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
    })
  }
}

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
  const compat = useCompatibility()
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
  const result = (job.result ?? {}) as {
    state?: string
    available?: boolean
    summary?: Record<string, unknown>
  }
  const extractionActive = ['Queued', 'Running'].includes(job.extraction)
  const extractionRecoverable =
    ['Failed', 'Cancelled'].includes(job.extraction) &&
    ['Succeeded', 'Failed', 'Cancelled'].includes(job.solver)
  const canExtract =
    ['Failed', 'Cancelled'].includes(job.solver) &&
    !result.available &&
    !extractionActive &&
    !extractionRecoverable
  return (
    <div className="run-actions">
      {(job.status === 'Completed' || result.available === true) &&
        job.mode !== 'BUILD' && (
          <button
            onClick={() => go('results/' + job.id)}
            data-testid={result.state === 'partial' ? 'open-partial-results' : undefined}
          >
            <ChartNoAxesCombined />
            {result.state === 'partial'
              ? t('dashboard.jobPartialResults')
              : t('dashboard.jobResults')}
          </button>
        )}
      <button onClick={() => go('setup/' + job.id)}>
        <FileText />
        {t('dashboard.jobSetup')}
      </button>
      <button
        title={t('dashboard.duplicate')}
        aria-label={t('dashboard.duplicate')}
        disabled={!compat.ok}
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
      {(!['Completed', 'Failed', 'Cancelled', 'Cancel requested'].includes(job.status) ||
        extractionActive) && (
        <button
          title={t('dashboard.cancelJob')}
          aria-label={t('dashboard.cancelJob')}
          disabled={!compat.ok}
          onClick={() => act('cancel')}
        >
          <Square />
        </button>
      )}
      {extractionRecoverable && (
        <button onClick={() => act('retry')} disabled={!compat.ok}>
          <RotateCcw />
          {t('dashboard.retryExtraction')}
        </button>
      )}
      {canExtract && (
        <button
          onClick={() => act('extract')}
          disabled={!compat.ok}
          data-testid="extract-available"
        >
          <RotateCcw />
          {t('run.extractAvailable')}
        </button>
      )}
    </div>
  )
}

export default function Dashboard({ notify }: { notify: (s: string) => void }) {
  const { t, formatDate, formatDateTime } = useI18n()
  const compat = useCompatibility()
  const [groups, gs] = useState<Group[]>([]),
    [runs, rs] = useState<Job[]>([]),
    [showArchived, setShowArchived] = useState(false)
  // Project (group) and model are separate filters: a model is not a project.
  const [projectFilter, pf] = useState(''),
    [modelFilter, mf] = useState(''),
    [status, sf] = useState(''),
    [creatingGroup, createGroupForm] = useState(false),
    [name, nm] = useState(''),
    [firstModel, first] = useState(''),
    [dim, dm] = useState('2D'),
    // One token per create-form attempt. A retry after a lost response reuses
    // it, so the server returns the project and model it already created.
    [creationToken, setCreationToken] = useState(requestToken)
  const [modelGroup, setModelGroup] = useState<string | null>(null),
    [modelName, mn] = useState(''),
    [modelDim, md] = useState('2D')
  const [openRevisions, revealRevisions] = useState<string | null>(null),
    [history, setHistory] = useState<RevisionSummary[]>([])
  const [busy, setBusy] = useState(false)
  // One accessible confirmation dialog for permanent deletion. It is opened
  // from an ordinary (non-archived) listing as well as from an archived one.
  const [deleteTarget, setDeleteTarget] = useState<{
    kind: 'model' | 'group'
    id: string
    info: DeletionInfo
  } | null>(null)
  const [deleteTyped, setDeleteTyped] = useState('')
  const [deleteChanged, setDeleteChanged] = useState(false)
  const deleteFocus = useRef<HTMLElement | null>(null)
  // A late response for the previous archive filter must not overwrite the
  // list produced by the current one after the user toggles the checkbox.
  const showArchivedRef = useRef(showArchived)
  showArchivedRef.current = showArchived
  async function refresh() {
    const include = showArchivedRef.current
    try {
      const [a, b] = await Promise.all([
        request<Group[]>('/api/groups?include_archived=' + (include ? 'true' : 'false')),
        request<Job[]>('/api/runs'),
      ])
      if (include !== showArchivedRef.current) return
      gs(a)
      rs(b)
    } catch (e) {
      notify(err(e))
    }
  }
  useEffect(() => {
    void refresh()
  }, [notify, showArchived])
  // Faster cadence only while a run can still change; an idle dashboard settles to
  // a slow refresh instead of polling every 1.4 s forever.
  const active = anyActive(runs)
  useEffect(() => {
    const id = setInterval(refresh, active ? ACTIVE_POLL_MS : IDLE_POLL_MS)
    return () => clearInterval(id)
  }, [active, showArchived])
  const projects = groups.flatMap((group) => group.models)
  async function addGroup(e: React.FormEvent) {
    e.preventDefault()
    if (!compat.ok) {
      notify(t('compat.writesDisabled'))
      return
    }
    setBusy(true)
    try {
      // One request, one transaction: a group can never exist without its first
      // model, and a retry with the same token returns the original pair.
      const created = await request<GroupCreated>('/api/project-groups', 'POST', {
        name: name.trim(),
        model_name: (firstModel.trim() || name).trim(),
        dimension: dim,
        token: creationToken,
      })
      createGroupForm(false)
      nm('')
      first('')
      setCreationToken(requestToken())
      await refresh()
      go('workspace/' + created.model.id)
    } catch (e) {
      notify(err(e))
    } finally {
      setBusy(false)
    }
  }

  function toggleCreateForm() {
    createGroupForm(!creatingGroup)
    if (!creatingGroup) setCreationToken(requestToken())
  }
  async function addModel(e: React.FormEvent, group: string) {
    e.preventDefault()
    if (!compat.ok) {
      notify(t('compat.writesDisabled'))
      return
    }
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
  /** Copy a stranded (archived) model into a new, independently editable one. */
  async function recoverModel(id: string) {
    if (!compat.ok) return
    setBusy(true)
    try {
      const copy = await request<Revision>('/api/projects/' + id + '/recover', 'POST', {})
      await refresh()
      notify(t('dashboard.modelRecovered'))
      go('workspace/' + copy.id)
    } catch (e) {
      notify(err(e))
    } finally {
      setBusy(false)
    }
  }
  async function setArchived(kind: 'model' | 'group', id: string, archived: boolean) {
    if (!compat.ok) return
    try {
      await request(
        `/api/${kind === 'model' ? 'projects' : 'groups'}/${id}/${archived ? 'archive' : 'restore'}`,
        'POST',
      )
      await refresh()
      notify(t(archived ? 'dashboard.archived' : 'dashboard.restored'))
    } catch (e) {
      notify(err(e))
    }
  }

  async function openDelete(kind: 'model' | 'group', id: string) {
    if (!compat.ok) {
      notify(t('compat.writesDisabled'))
      return
    }
    try {
      const info = await request<DeletionInfo>(
        `/api/${kind === 'model' ? 'projects' : 'groups'}/${id}/deletion-info`,
      )
      const activeJobs = info.active_jobs ?? []
      if (!info.deletable || activeJobs.length) {
        notify(
          t('dashboard.deleteBlocked', {
            reason: activeJobs.length
              ? t('dashboard.deleteActive', { jobs: activeJobs.join(', ') })
              : t('dashboard.deleteUnresolved'),
          }),
        )
        return
      }
      deleteFocus.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null
      setDeleteTyped('')
      setDeleteChanged(false)
      setDeleteTarget({ kind, id, info })
    } catch (e) {
      notify(err(e))
    }
  }

  function closeDelete() {
    setDeleteTarget(null)
    setDeleteTyped('')
    setDeleteChanged(false)
    // Cancel/Escape restores focus to the control that opened the dialog.
    window.setTimeout(() => deleteFocus.current?.focus(), 0)
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    const { kind, id, info } = deleteTarget
    if (deleteTyped.trim() !== info.name) {
      notify(t('dashboard.deleteNameMismatch'))
      return
    }
    const url = `/api/${kind === 'model' ? 'projects' : 'groups'}/${id}`
    try {
      // Refresh the impact immediately before execution. If scope changed, show
      // the revised impact and require a fresh typed confirmation.
      const fresh = await request<DeletionInfo>(`${url}/deletion-info`)
      if (fresh.active_jobs?.length || !fresh.deletable) {
        setDeleteTarget({ kind, id, info: fresh })
        setDeleteTyped('')
        setDeleteChanged(true)
        return
      }
      const changed =
        fresh.revisions !== info.revisions ||
        fresh.jobs !== info.jobs ||
        (kind === 'group' && fresh.models !== info.models)
      if (changed) {
        setDeleteTarget({ kind, id, info: fresh })
        setDeleteTyped('')
        setDeleteChanged(true)
        return
      }
      const result = await request<{ cleanup: string }>(`${url}/delete`, 'POST', {
        confirm: deleteTyped,
        expected_models: fresh.models,
        expected_revisions: fresh.revisions,
        expected_jobs: fresh.jobs,
      })
      setDeleteTarget(null)
      setDeleteTyped('')
      setDeleteChanged(false)
      notify(
        result.cleanup === 'pending'
          ? t('dashboard.deletedPending', { name: info.name })
          : t('dashboard.deleted', { name: info.name }),
      )
      await refresh()
    } catch (e) {
      const message = err(e)
      // The server re-checked the impact under its write lock. Re-present the
      // revised scope instead of forcing the user to guess what changed.
      if (/impact changed/i.test(message)) {
        try {
          const fresh = await request<DeletionInfo>(`${url}/deletion-info`)
          setDeleteTarget({ kind, id, info: fresh })
          setDeleteTyped('')
          setDeleteChanged(true)
          return
        } catch {
          // Fall through to the original message.
        }
      }
      notify(message)
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
  const models = projectFilter
    ? projects.filter((p) => p.group === projectFilter)
    : projects
  const visible = runs.filter(
    (r) =>
      (!projectFilter || r.group === projectFilter) &&
      (!modelFilter || modelFilter === r.project) &&
      (!status || status === r.status),
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
        <label className="check archive-toggle">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />
          {t('dashboard.showArchived')}
        </label>
        <button className="primary" onClick={toggleCreateForm} disabled={!compat.ok}>
          <Plus />
          {t('dashboard.newProject')}
        </button>
      </div>
      <FileBar notify={notify} onChanged={() => void refresh()} />
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
          <small className="create-note">{t('dashboard.startsEmpty')}</small>
          <button className="primary" disabled={busy || !name.trim() || !compat.ok}>
            {t('dashboard.createProject')}
          </button>
          <button type="button" onClick={() => createGroupForm(false)}>
            {t('common.cancel')}
          </button>
          {!compat.ok && <small className="error-text">{t('compat.writesDisabled')}</small>}
        </form>
      )}
      <h2>
        <FolderOpen />
        {t('dashboard.projects')} <small>{groups.length}</small>
      </h2>
      <div className="group-list">
        {!groups.length && !creatingGroup && (
          <section className="card empty" data-testid="no-projects">
            <FolderOpen />
            <h3>{t('dashboard.noProjects')}</h3>
            <p>{t('dashboard.noProjectsHint')}</p>
            <button className="primary" onClick={() => createGroupForm(true)}>
              <Plus />
              {t('dashboard.createProject')}
            </button>
          </section>
        )}
        {groups.map((group) => (
          <section className="group-card card" key={group.id}>
            <div className="group-heading">
              <span className="group-symbol">
                <FolderOpen />
              </span>
              <div>
                <strong title={group.name}>
                  {group.internal ? t('dashboard.fileDocuments') : group.name}
                </strong>
                <small>
                  {group.archived ? t('dashboard.archivedBadge') + ' · ' : ''}
                  {t('dashboard.modelsCount', { count: group.models.length })} ·{' '}
                  {group.internal
                    ? t('dashboard.fileDocumentsHint')
                    : formatDate(group.created)}
                </small>
              </div>
              <div className="spacer" />
              {/* The file-document owner is application-managed: it has no archive
                  or delete control, and the API refuses both actions. */}
              {!group.internal && (
                <>
                  <button
                    type="button"
                    title={group.archived ? t('dashboard.restore') : t('dashboard.archive')}
                    aria-label={
                      (group.archived ? t('dashboard.restore') : t('dashboard.archive')) +
                      ' · ' +
                      group.name
                    }
                    disabled={!compat.ok}
                    onClick={() => setArchived('group', group.id, !group.archived)}
                  >
                    {group.archived ? <ArchiveRestore /> : <Archive />}
                  </button>
                  <button
                    type="button"
                    className="destructive"
                    title={t('dashboard.deleteGroup')}
                    aria-label={t('dashboard.deleteGroup') + ' · ' + group.name}
                    disabled={!compat.ok}
                    onClick={() => openDelete('group', group.id)}
                  >
                    <Trash2 />
                  </button>
                </>
              )}
              <button
                onClick={() => setModelGroup(modelGroup === group.id ? null : group.id)}
                disabled={group.archived}
              >
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
                <small className="create-note">{t('dashboard.startsEmpty')}</small>
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
                  <div
                    className={
                      'model-entry' + (p.archived || p.group_archived ? ' archived' : '')
                    }
                    key={p.id}
                  >
                    <button className="project-card" onClick={() => go('workspace/' + p.revision)}>
                      <span className="project-symbol">
                        <Layers3 />
                      </span>
                      <span>
                        <strong title={p.name}>{p.name}</strong>
                        <small>
                          {p.archived || p.group_archived
                            ? t('dashboard.archivedBadge') + ' · '
                            : ''}
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
                      {(p.archived || p.group_archived) && (
                        <button
                          type="button"
                          disabled={!compat.ok || busy}
                          title={t('dashboard.recoverModel')}
                          aria-label={t('dashboard.recoverModel') + ' · ' + p.name}
                          onClick={() => recoverModel(p.id)}
                        >
                          <FilePlus2 />
                        </button>
                      )}
                      <button
                        type="button"
                        title={p.archived ? t('dashboard.restore') : t('dashboard.archive')}
                        aria-label={
                          (p.archived ? t('dashboard.restore') : t('dashboard.archive')) +
                          ' · ' +
                          p.name
                        }
                        disabled={!compat.ok}
                        onClick={() => setArchived('model', p.id, !p.archived)}
                      >
                        {p.archived ? <ArchiveRestore /> : <Archive />}
                      </button>
                      <button
                        type="button"
                        className="destructive"
                        title={t('dashboard.deleteModel')}
                        aria-label={t('dashboard.deleteModel') + ' · ' + p.name}
                        disabled={!compat.ok}
                        onClick={() => openDelete('model', p.id)}
                      >
                        <Trash2 />
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
          <div className="filters" data-testid="run-filters">
            <ListFilter />
            <select
              aria-label={t('dashboard.filterProject')}
              title={groups.find((g) => g.id === projectFilter)?.name || t('dashboard.allProjects')}
              value={projectFilter}
              onChange={(e) => {
                pf(e.target.value)
                mf('')
              }}
            >
              <option value="">{t('dashboard.allProjects')}</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
            <select
              aria-label={t('dashboard.filterModel')}
              title={projects.find((p) => p.id === modelFilter)?.name || t('dashboard.allModels')}
              value={modelFilter}
              onChange={(e) => mf(e.target.value)}
            >
              <option value="">{t('dashboard.allModels')}</option>
              {models.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <select
              aria-label={t('dashboard.filterStatus')}
              title={status ? labelFrom(t, 'state', status) : t('dashboard.allStatuses')}
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
          <div
            className="table-scroll"
            data-testid="run-table-scroll"
            role="region"
            aria-label={t('dashboard.runsRegion')}
            tabIndex={0}
          >
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
                  <tr key={r.id} data-run-status={r.status}>
                    <td>
                      <strong title={r.name}>{r.name}</strong>
                      <small>
                        {(r.group_name ? r.group_name + ' · ' : '') + r.project_name} ·{' '}
                        {r.dimension} · Rev {r.number}
                      </small>
                      <small className="run-identity">
                        {t('dashboard.runId')} {r.id.slice(0, 8)} · {formatDateTime(r.created)}
                      </small>
                      <small className="mode-label">
                        {r.mode === 'DEMO' ? t('demo.notice') : r.mode}
                      </small>
                    </td>
                    <td data-label={t('dashboard.colState')}>
                      <Badge value={r.status} />
                      <small>
                        {labelFrom(t, 'phase', r.step || r.phase)}
                        {r.increment != null
                          ? ' · ' + t('dashboard.increment', { value: r.increment })
                          : ''}
                      </small>
                    </td>
                    <td data-label={t('dashboard.colSubmitted')}>{formatDate(r.created)}</td>
                    <td data-label={t('dashboard.colElapsed')}>{elapsed(r)}</td>
                    <td data-label={t('dashboard.colOutput')}>
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
      {deleteTarget && (
        <div
          className="dialog-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeDelete()
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-dialog-title"
            className="dialog card"
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.stopPropagation()
                closeDelete()
              }
            }}
          >
            <h2 id="delete-dialog-title">
              {t(
                deleteTarget.kind === 'model'
                  ? 'dashboard.deleteModelTitle'
                  : 'dashboard.deleteGroupTitle',
              )}
            </h2>
            <p className="dialog-target">
              {t('dashboard.deleteTarget', {
                kind: t(
                  deleteTarget.kind === 'model'
                    ? 'dashboard.targetModel'
                    : 'dashboard.targetGroup',
                ),
                name: deleteTarget.info.name,
              })}
            </p>
            <dl className="dialog-impact">
              {deleteTarget.kind === 'group' && (
                <div>
                  <dt>{t('dashboard.deleteModels')}</dt>
                  <dd>{deleteTarget.info.models}</dd>
                </div>
              )}
              <div>
                <dt>{t('dashboard.deleteRevisions')}</dt>
                <dd>{deleteTarget.info.revisions}</dd>
              </div>
              <div>
                <dt>{t('dashboard.deleteJobs')}</dt>
                <dd>{deleteTarget.info.jobs}</dd>
              </div>
            </dl>
            <p className="notice">{t('dashboard.deleteArtifacts')}</p>
            {deleteChanged && (
              <p className="error-text" role="alert" data-testid="delete-impact-changed">
                {t('dashboard.deleteImpactChanged')}
              </p>
            )}
            <label>
              {t('dashboard.deleteTypeNameShort', { name: deleteTarget.info.name })}
              <input
                autoFocus
                value={deleteTyped}
                maxLength={200}
                onChange={(event) => setDeleteTyped(event.target.value)}
              />
            </label>
            <div className="dialog-actions">
              <button type="button" onClick={closeDelete}>
                {t('common.cancel')}
              </button>
              <button
                type="button"
                className="destructive solid"
                disabled={deleteTyped.trim() !== deleteTarget.info.name}
                onClick={confirmDelete}
              >
                <Trash2 />
                {t('dashboard.deletePermanent')}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}
