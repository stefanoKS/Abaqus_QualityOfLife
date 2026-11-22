import { useCallback, useEffect, useMemo, useState } from 'react'
import { Archive, ArchiveRestore, Copy, FlaskConical, Plus, Save, Search, Upload } from 'lucide-react'
import {
  err,
  request,
  type LibraryCard,
  type LibraryDetail,
  type LibrarySummary,
  type MaterialImportResult,
  type Project,
  type Summary,
} from './api'
import { useI18n } from './i18n'
import { NumberInput } from './shared/components/NumberInput'
import { hasInvalidField, useAnyInvalidField } from './shared/components/draftGuard'
import {
  TestDataTable,
  materialIssues,
} from './features/materials/MaterialEditor'
import { ComparisonPlot, type CompareSeries } from './features/materials/ComparisonPlot'

type Card = Project['materials'][number]
type Triple = [number, number, number]
type FullCard = LibraryCard & { test_data: Triple[] }

function fullCard(card: LibraryCard): FullCard {
  return { ...card, test_data: (card.test_data ?? []) as Triple[] }
}

const DEFAULT_CARD: FullCard = {
  model: 'linear_elastic',
  color: '#2f7a6b',
  density: 1.1e-9,
  young: 5,
  poisson: 0.49,
  test_data: [],
}

interface Compared {
  label: string
  name: string
  version: number
  card: FullCard
}

export default function MaterialsPage({ notify }: { notify: (message: string) => void }) {
  const { t, formatDate } = useI18n()
  const invalidField = useAnyInvalidField()
  const [items, setItems] = useState<LibrarySummary[]>([])
  const [projects, setProjects] = useState<Summary[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<LibraryDetail | null>(null)
  const [query, setQuery] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const [name, setName] = useState('')
  const [draft, setDraft] = useState<FullCard>(DEFAULT_CARD)
  const [busy, setBusy] = useState(false)
  const [compare, setCompare] = useState<Record<string, Compared>>({})
  const [importProject, setImportProject] = useState('')

  const refresh = useCallback(async () => {
    const [list, heads] = await Promise.all([
      request<LibrarySummary[]>(
        '/api/materials?include_archived=' + (showArchived ? 'true' : 'false'),
      ),
      request<Summary[]>('/api/projects'),
    ])
    setItems(list)
    setProjects(heads)
    setSelected((current) =>
      current && list.some((row) => row.id === current) ? current : (list[0]?.id ?? null),
    )
  }, [showArchived])

  useEffect(() => {
    void refresh().catch((error) => notify(err(error)))
  }, [refresh, notify])

  const load = useCallback(async (id: string) => {
    const found = await request<LibraryDetail>('/api/materials/' + id)
    setDetail(found)
    setName(found.name)
    setDraft(fullCard(found.card))
  }, [])

  useEffect(() => {
    if (selected) {
      void load(selected).catch((error) => notify(err(error)))
    } else {
      setDetail(null)
    }
  }, [selected, load, notify])

  const draftMaterial: Card = useMemo(
    () => ({
      id: 'library',
      name: name.trim() || 'Library material',
      version: detail?.current_version ?? 1,
      ...draft,
      young: draft.young ?? null,
      poisson: draft.poisson ?? null,
      library_id: null,
      library_version: null,
    }),
    [draft, name, detail?.current_version],
  )
  const issues = materialIssues(draftMaterial)
  const filtered = items.filter(
    (row) => !query || row.name.toLowerCase().includes(query.toLowerCase()),
  )

  async function run(work: () => Promise<void>) {
    if (busy) return
    setBusy(true)
    try {
      await work()
    } catch (error) {
      notify(err(error))
    } finally {
      setBusy(false)
    }
  }

  function add() {
    void run(async () => {
      const created = await request<LibraryDetail>('/api/materials', 'POST', {
        name: t('materialsLibrary.defaultName'),
        card: DEFAULT_CARD,
      })
      await refresh()
      setSelected(created.id)
    })
  }

  function save() {
    if (!detail) return
    if (hasInvalidField()) {
      notify(t('validation.invalidDraft'))
      return
    }
    void run(async () => {
      const updated = await request<LibraryDetail>('/api/materials/' + detail.id, 'PUT', {
        name: name.trim(),
        card: draft,
      })
      setDetail(updated)
      setName(updated.name)
      setDraft(fullCard(updated.card))
      await refresh()
      notify(t('materialsLibrary.saved', { version: updated.current_version }))
    })
  }

  function duplicate() {
    if (!detail) return
    void run(async () => {
      const copy = await request<LibraryDetail>(
        '/api/materials/' + detail.id + '/duplicate',
        'POST',
        { name: detail.name + ' · copy' },
      )
      await refresh()
      setSelected(copy.id)
    })
  }

  function setArchived(next: boolean) {
    if (!detail) return
    void run(async () => {
      await request(
        '/api/materials/' + detail.id + (next ? '/archive' : '/restore'),
        'POST',
      )
      await refresh()
      await load(detail.id)
    })
  }

  function adoptVersion(version: number, card: LibraryCard) {
    setDraft({ ...fullCard(card) })
    notify(t('materialsLibrary.loadedVersion', { version }))
  }

  function toggleVersion(version: number, card: LibraryCard) {
    if (!detail) return
    const key = detail.id + '@' + version
    setCompare((old) => {
      if (old[key]) {
        const next = { ...old }
        delete next[key]
        return next
      }
      return {
        ...old,
        [key]: {
          label: detail.name + ' v' + version,
          name: detail.name,
          version,
          card: fullCard(card),
        },
      }
    })
  }

  function toggleCurrent(summary: LibrarySummary) {
    const key = summary.id + '@' + summary.current_version
    setCompare((old) => {
      if (old[key]) {
        const next = { ...old }
        delete next[key]
        return next
      }
      return {
        ...old,
        [key]: {
          label: summary.name + ' v' + summary.current_version,
          name: summary.name,
          version: summary.current_version,
          card: fullCard(summary.card),
        },
      }
    })
  }

  function importCards() {
    if (!importProject) return
    void run(async () => {
      const project = projects.find((row) => row.id === importProject)
      if (!project) return
      const imported = await request<MaterialImportResult[]>('/api/materials/import', 'POST', {
        revision: project.revision,
        material_ids: [],
      })
      await refresh()
      notify(t('materialsLibrary.imported', { count: imported.length }))
    })
  }

  const stress: CompareSeries[] = Object.values(compare)
    .filter((row) => row.card.test_data.length >= 2)
    .map((row) => ({
      label: row.label,
      color: row.card.color,
      x: row.card.test_data.map((sample) => sample[1]),
      y: row.card.test_data.map((sample) => sample[0]),
    }))
  const lateral: CompareSeries[] = Object.values(compare)
    .filter((row) => row.card.test_data.length >= 2)
    .map((row) => ({
      label: row.label,
      color: row.card.color,
      x: row.card.test_data.map((sample) => sample[1]),
      y: row.card.test_data.map((sample) => sample[2]),
    }))
  const comparedCount = Object.keys(compare).length

  return (
    <main className="materials-page page">
      <div className="page-heading">
        <div>
          <div className="eyebrow">
            <FlaskConical size={15} /> {t('materialsLibrary.eyebrow')}
          </div>
          <h1>{t('materialsLibrary.title')}</h1>
          <p className="subtitle">{t('materialsLibrary.subtitle')}</p>
        </div>
        <button className="primary" onClick={add} disabled={busy}>
          <Plus />
          {t('materialsLibrary.new')}
        </button>
      </div>

      <div className="library-grid">
        <aside className="card library-list">
          <label className="search">
            <Search size={15} />
            <input
              aria-label={t('materialsLibrary.search')}
              placeholder={t('materialsLibrary.search')}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(event) => setShowArchived(event.target.checked)}
            />
            {t('materialsLibrary.includeArchived')}
          </label>
          <div className="material-list">
            {filtered.map((row) => (
              <div className="material-row-wrap" key={row.id}>
                <button
                  type="button"
                  data-material-id={row.id}
                  className={'material-row ' + (selected === row.id ? 'active' : '')}
                  aria-pressed={selected === row.id}
                  onClick={() => setSelected(row.id)}
                >
                  <span className="swatch" style={{ background: row.card.color }} />
                  <span className="material-name">{row.name}</span>
                  <small>
                    {row.card.model === 'hyperfoam_test'
                      ? t('materials.modelHyperfoam')
                      : t('materials.modelLinear')}{' '}
                    · v{row.current_version} ·{' '}
                    {t('materialsLibrary.usedByCount', { count: row.usage_count })}
                    {row.archived ? ' · ' + t('materialsLibrary.archived') : ''}
                  </small>
                </button>
                <input
                  type="checkbox"
                  className="compare-toggle"
                  aria-label={t('materialsLibrary.compareCurrent', { name: row.name })}
                  checked={Boolean(compare[row.id + '@' + row.current_version])}
                  onChange={() => toggleCurrent(row)}
                />
              </div>
            ))}
            {!filtered.length && <p className="empty-line">{t('materialsLibrary.empty')}</p>}
          </div>
          <div className="import-panel">
            <h3>
              <Upload size={15} /> {t('materialsLibrary.importTitle')}
            </h3>
            <p>{t('materialsLibrary.importHelp')}</p>
            <select
              aria-label={t('materialsLibrary.importModel')}
              value={importProject}
              onChange={(event) => setImportProject(event.target.value)}
            >
              <option value="">{t('materialsLibrary.chooseModel')}</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
            <button type="button" onClick={importCards} disabled={!importProject || busy}>
              {t('materialsLibrary.importButton')}
            </button>
          </div>
        </aside>

        <section className="card library-editor">
          {detail ? (
            <>
              <div className="library-editor-head">
                <label>
                  {t('materials.name')}
                  <input
                    aria-label={t('materialsLibrary.libraryName')}
                    value={name}
                    maxLength={100}
                    onChange={(event) => setName(event.target.value)}
                  />
                </label>
                <span className="badge">
                  {detail.archived
                    ? t('materialsLibrary.archived')
                    : t('materialsLibrary.currentVersion', { version: detail.current_version })}
                </span>
              </div>
              <div className="row-actions">
                <button
                  type="button"
                  className="primary"
                  onClick={save}
                  disabled={busy || !name.trim() || issues.errors.length > 0 || invalidField}
                >
                  <Save />
                  {t('materialsLibrary.save')}
                </button>
                <button type="button" onClick={duplicate} disabled={busy}>
                  <Copy />
                  {t('materials.duplicate')}
                </button>
                <button
                  type="button"
                  onClick={() => setArchived(!detail.archived)}
                  disabled={busy}
                >
                  {detail.archived ? <ArchiveRestore /> : <Archive />}
                  {detail.archived
                    ? t('materialsLibrary.restore')
                    : t('materialsLibrary.archive')}
                </button>
              </div>
              <label>
                {t('materials.model')}
                <select
                  value={draft.model}
                  onChange={(event) => {
                    const model = event.target.value as LibraryCard['model']
                    setDraft((old) => ({
                      ...old,
                      model,
                      test_data:
                        model === 'hyperfoam_test' && old.test_data.length < 3
                          ? [
                              [0, 0.05, -0.025],
                              [0, 0.1, -0.05],
                              [0, 0.15, -0.075],
                            ]
                          : old.test_data,
                      young: model === 'linear_elastic' ? (old.young ?? 5) : old.young,
                      poisson: model === 'linear_elastic' ? (old.poisson ?? 0.49) : old.poisson,
                    }))
                  }}
                >
                  <option value="linear_elastic">{t('materials.modelLinear')}</option>
                  <option value="hyperfoam_test">{t('materials.modelHyperfoam')}</option>
                </select>
              </label>
              <label>
                {t('materials.color')}
                <input
                  type="color"
                  value={draft.color}
                  onChange={(event) => setDraft((old) => ({ ...old, color: event.target.value }))}
                />
              </label>
              <NumberInput
                label={t('materials.density')}
                value={draft.density}
                min={1e-15}
                onChange={(density) => setDraft((old) => ({ ...old, density }))}
              />
              {draft.model === 'linear_elastic' ? (
                <>
                  <NumberInput
                    label={t('materials.young')}
                    value={draft.young ?? 5}
                    min={1e-9}
                    onChange={(young) => setDraft((old) => ({ ...old, young }))}
                  />
                  <NumberInput
                    label={t('materials.poisson')}
                    value={draft.poisson ?? 0.49}
                    min={-0.999}
                    max={0.4999}
                    onChange={(poisson) => setDraft((old) => ({ ...old, poisson }))}
                  />
                </>
              ) : (
                <>
                  <h3>
                    {t('materials.testData')} ·{' '}
                    {t('materials.samples', { count: draft.test_data.length })}
                  </h3>
                  <TestDataTable
                    material={draftMaterial}
                    disabled={busy}
                    onChange={(rows) => setDraft((old) => ({ ...old, test_data: rows }))}
                  />
                </>
              )}
              {issues.errors.length > 0 && (
                <ul className="issue-list">
                  {issues.errors.map((key) => (
                    <li key={key} className="issue error">
                      {t(key)}
                    </li>
                  ))}
                </ul>
              )}

              <h3>{t('materialsLibrary.versions')}</h3>
              <ul className="version-list" data-testid="version-history">
                {[...detail.versions].reverse().map((version) => {
                  const key = detail.id + '@' + version.version
                  return (
                    <li key={version.version}>
                      <label className="check">
                        <input
                          type="checkbox"
                          checked={Boolean(compare[key])}
                          aria-label={t('materialsLibrary.compareVersion', {
                            name: detail.name,
                            version: version.version,
                          })}
                          onChange={() => toggleVersion(version.version, version.card)}
                        />
                        <strong>v{version.version}</strong>
                        <small>{formatDate(version.created)}</small>
                        {version.note && <small>{version.note}</small>}
                      </label>
                      <button
                        type="button"
                        onClick={() => adoptVersion(version.version, version.card)}
                      >
                        {t('materialsLibrary.loadVersion')}
                      </button>
                    </li>
                  )
                })}
              </ul>

              <h3>{t('materialsLibrary.usage')}</h3>
              {detail.usage.length ? (
                <ul className="usage-list">
                  {detail.usage.map((row) => (
                    <li key={row.revision}>
                      {row.model_name} · {t('dashboard.revision', { number: row.number })} ·{' '}
                      {t('materialsLibrary.pinnedVersion', {
                        version: row.pinned_version ?? '—',
                      })}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-line">{t('materialsLibrary.noUsage')}</p>
              )}
            </>
          ) : (
            <p className="empty-line">{t('materialsLibrary.empty')}</p>
          )}
        </section>
      </div>

      <section className="card comparison-card">
        <div className="card-heading">
          <h2>{t('materialsLibrary.comparison')}</h2>
          <small>{t('materialsLibrary.compared', { count: comparedCount })}</small>
        </div>
        <p className="field-hint">{t('materialsLibrary.measuredOnly')}</p>
        <p className="field-hint">{t('materialsLibrary.sourceNote')}</p>
        {stress.length ? (
          <>
            <h3>{t('materialsLibrary.stressStrain')}</h3>
            <ComparisonPlot
              series={stress}
              xlabel={t('materials.nominalStrain') + ' (–)'}
              ylabel={t('materials.stress') + ' (N/mm²)'}
              testId="compare-stress"
            />
            <h3>{t('materialsLibrary.lateralAxial')}</h3>
            <ComparisonPlot
              series={lateral}
              xlabel={t('materials.nominalStrain') + ' (–)'}
              ylabel={t('materialsLibrary.lateralStrain') + ' (–)'}
              testId="compare-lateral"
            />
          </>
        ) : (
          <p className="empty-line">{t('materialsLibrary.noCurves')}</p>
        )}
      </section>
    </main>
  )
}
