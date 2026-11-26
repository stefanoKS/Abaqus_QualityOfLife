import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import {
  Archive,
  ArchiveRestore,
  Copy,
  FileDown,
  FlaskConical,
  FolderOpen,
  Plus,
  Save,
  Search,
  Upload,
} from 'lucide-react'
import {
  err,
  request,
  type LibraryCard,
  type LibraryDetail,
  type LibrarySummary,
  type Project,
} from './api'
import { useI18n, type TranslationKey } from './i18n'
import { NumberInput } from './shared/components/NumberInput'
import {
  hasInvalidField,
  setFieldInvalid,
  useAnyInvalidField,
} from './shared/components/draftGuard'
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

/** A CAE library card as the preview endpoint reports it. */
interface CaeReason {
  code: string
  property?: string
  detail?: string
}
interface CaeLawBlock {
  n?: number
  test_data?: boolean
  moduli?: string
  moduli_time_scale?: string
  lateral?: boolean
  type?: string
  table?: number[][]
  uniaxial?: number[][]
  time?: string
}
interface CaeAssessment {
  registrable: boolean
  available: boolean
  model: string | null
  law: string[]
  family_hint: 'polymer' | 'metal'
  needs: string[]
  reasons: CaeReason[]
  blocks: Record<string, CaeLawBlock>
}
interface CaeCard {
  key: string
  name: string
  category: string
  dataError: string
  assessment: CaeAssessment
}
interface CaePreview {
  file: string
  sha256: string
  bytes: number
  cards: CaeCard[]
  registrable: number
  available: number
}

/** Read-only presentation of the registered CAE law blocks. */
function lawRows(block: CaeLawBlock | null | undefined): number[][] {
  if (!block) return []
  return block.table?.length ? block.table : (block.uniaxial ?? [])
}

const DEFAULT_CARD: FullCard = {
  model: 'linear_elastic',
  color: '#2f7a6b',
  density: 1.1e-9,
  young: 5,
  poisson: 0.49,
  c10: null,
  d1: null,
  test_data: [],
  family: 'polymer',
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
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<LibraryDetail | null>(null)
  const [query, setQuery] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const [name, setName] = useState('')
  const [draft, setDraft] = useState<FullCard>(DEFAULT_CARD)
  // A registered CAE card may have no density. It is shown empty so the engineer
  // can supply the missing input in a new version; it is never pre-filled.
  const [densityText, setDensityText] = useState(String(DEFAULT_CARD.density))
  const [busy, setBusy] = useState(false)
  const [compare, setCompare] = useState<Record<string, Compared>>({})
  const [cae, setCae] = useState<CaePreview | null>(null)
  const [caeFile, setCaeFile] = useState<File | null>(null)
  const [caeKeys, setCaeKeys] = useState<string[]>([])
  const [caeFamily, setCaeFamily] = useState<'polymer' | 'metal'>('polymer')
  // One declared family per record: a single bulk value would misclassify a
  // metal card in a mixed import.
  const [caeFamilies, setCaeFamilies] = useState<Record<string, 'polymer' | 'metal'>>({})
  const [caeUnits, setCaeUnits] = useState('N-mm-s-tonne')
  const [exportFolder, setExportFolder] = useState('')
  const caeInput = useRef<HTMLInputElement>(null)
  // Only the response for the most recently selected card may populate the
  // editor. Without this token a slow earlier request could replace a newer
  // selection (or leave its fields editable under the wrong heading).
  const loadToken = useRef(0)
  // The same ordering rule applies to the list: an older filter response must
  // not reset the selection after "Include archived" or a newer refresh.
  const refreshToken = useRef(0)
  // Latest requested selection, readable after an await without a stale closure.
  const selectedRef = useRef<string | null>(null)
  const caeDensityId = useId()

  const refresh = useCallback(async () => {
    const token = ++refreshToken.current
    const list = await request<LibrarySummary[]>(
      '/api/materials?include_archived=' + (showArchived ? 'true' : 'false'),
    )
    // A newer filter/refresh has been issued; its response is authoritative.
    if (token !== refreshToken.current) return null
    setItems(list)
    setSelected((current) =>
      current && list.some((row) => row.id === current) ? current : (list[0]?.id ?? null),
    )
    return list
  }, [showArchived])

  useEffect(() => {
    void refresh().catch((error) => notify(err(error)))
  }, [refresh, notify])

  const load = useCallback(async (id: string) => {
    const token = ++loadToken.current
    const found = await request<LibraryDetail>('/api/materials/' + id)
    // A newer selection, or a newer load, has taken over. Never write a card
    // into an editor whose selection has already moved on.
    if (token !== loadToken.current || selectedRef.current !== id) return
    setDetail(found)
    setName(found.name)
    setDraft(fullCard(found.card))
    setDensityText(found.card.density == null ? '' : String(found.card.density))
  }, [])

  useEffect(() => {
    selectedRef.current = selected
    if (selected) {
      // Freeze the editor until the clicked card's own detail arrives: the old
      // card must not stay editable (or saveable) under the new selection.
      setDetail(null)
      void load(selected).catch((error) => notify(err(error)))
    } else {
      loadToken.current++
      setDetail(null)
    }
  }, [selected, load, notify])

  // The CAE density is a plain text draft (blank means "not supplied"), but a
  // typed zero/negative/non-finite value must block Save exactly like the
  // numeric density field used by the other models.
  const caeDensityInvalid =
    draft.model === 'cae_law' &&
    densityText.trim() !== '' &&
    (!Number.isFinite(Number(densityText)) || Number(densityText) <= 0)
  useEffect(() => {
    setFieldInvalid(caeDensityId, caeDensityInvalid)
    return () => setFieldInvalid(caeDensityId, false)
  }, [caeDensityId, caeDensityInvalid])

  const draftMaterial: Card = useMemo(
    () => ({
      id: 'library',
      name: name.trim() || 'Library material',
      version: detail?.current_version ?? 1,
      ...draft,
      density: draft.density ?? null,
      young: draft.young ?? null,
      poisson: draft.poisson ?? null,
      c10: draft.c10 ?? null,
      d1: draft.d1 ?? null,
      test_data: draft.test_data ?? [],
      hyperfoam: draft.hyperfoam ?? null,
      hyperelastic: draft.hyperelastic ?? null,
      viscoelastic: draft.viscoelastic ?? null,
      plastic: draft.plastic ?? null,
      mullins: draft.mullins ?? null,
      thermal: draft.thermal ?? null,
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
    if (!detail || detail.id !== selected) return
    if (hasInvalidField()) {
      notify(t('validation.invalidDraft'))
      return
    }
    const card: FullCard = { ...draft }
    if (card.model === 'cae_law') {
      const text = densityText.trim()
      const density = text === '' ? null : Number(text)
      if (density !== null && (!Number.isFinite(density) || density <= 0)) {
        notify(t('materials.err.density'))
        return
      }
      card.density = density
    }
    void run(async () => {
      const updated = await request<LibraryDetail>('/api/materials/' + detail.id, 'PUT', {
        name: name.trim(),
        card,
      })
      setDetail(updated)
      setName(updated.name)
      setDraft(fullCard(updated.card))
      setDensityText(updated.card.density == null ? '' : String(updated.card.density))
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
    const id = detail.id
    void run(async () => {
      await request('/api/materials/' + id + (next ? '/archive' : '/restore'), 'POST')
      await refresh()
      // Reload the affected card; `load` discards the response when refresh has
      // already moved the selection elsewhere.
      await load(id)
    })
  }

  function adoptVersion(version: number, card: LibraryCard) {
    setDraft({ ...fullCard(card) })
    setDensityText(card.density == null ? '' : String(card.density))
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

  /**
   * CAE library exchange. The preview never registers anything: every decoded
   * record is shown with its law, the declared family and what a *new run*
   * still needs. Registering is separate from running, so a well-formed record
   * is selectable even when its source omits a density.
   */
  async function previewCae(file: File) {
    setCaeFile(file)
    await run(async () => {
      const form = new FormData()
      form.append('file', file)
      const payload = await request<CaePreview>(
        '/api/material-library/cae/preview',
        'POST',
        form,
      )
      setCae(payload)
      setCaeKeys(payload.cards.filter((card) => card.assessment.registrable).map((card) => card.key))
      setCaeFamilies(
        Object.fromEntries(
          payload.cards
            .filter((card) => card.assessment.registrable)
            .map((card) => [card.key, card.assessment.family_hint]),
        ),
      )
    })
  }

  function importCae() {
    if (!caeFile || !caeKeys.length) return
    void run(async () => {
      const form = new FormData()
      form.append('file', caeFile)
      form.append('keys', JSON.stringify(caeKeys))
      form.append('family', caeFamily)
      form.append('families', JSON.stringify(caeFamilies))
      form.append('units', caeUnits)
      const result = await request<{
        registered: { library_id: string; existing: boolean }[]
        skipped: { name: string; reasons: CaeReason[] }[]
        conflicts: { name: string; registered_as: string }[]
      }>('/api/material-library/cae/import', 'POST', form)
      await refresh()
      setCae(null)
      setCaeFile(null)
      setCaeKeys([])
      setCaeFamilies({})
      notify(
        t('materialsLibrary.caeImported', {
          count: result.registered.filter((item) => !item.existing).length,
          skipped: result.skipped.length + result.conflicts.length,
        }),
      )
    })
  }

  async function chooseFolder() {
    await run(async () => {
      const result = await request<{ path: string }>(
        '/api/files/pick?mode=folder&title=' +
          encodeURIComponent(t('materialsLibrary.caeFolderTitle')),
      )
      if (result.path) setExportFolder(result.path)
    })
  }

  function exportCae() {
    if (!exportFolder.trim()) return
    void run(async () => {
      const result = await request<{
        files: { path: string; sha256: string; cards: string[] }[]
        skipped: { sha256: string; reason: string }[]
      }>('/api/material-library/cae/export', 'POST', {
        folder: exportFolder.trim(),
        material_ids: [],
      })
      notify(
        t('materialsLibrary.caeExported', {
          count: result.files.length,
          skipped: result.skipped.length,
        }),
      )
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
                      : row.card.model === 'neo_hookean'
                        ? t('materials.modelNeoHookean')
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
          <div className="cae-panel" data-testid="cae-library">
            <h3>
              <Upload size={15} /> {t('materialsLibrary.caeTitle')}
            </h3>
            <p>{t('materialsLibrary.caeHelp')}</p>
            <input
              ref={caeInput}
              type="file"
              accept=".lib"
              className="sr-only"
              aria-label={t('materialsLibrary.caeChoose')}
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void previewCae(file)
                event.target.value = ''
              }}
            />
            <button
              type="button"
              data-testid="cae-preview"
              disabled={busy}
              onClick={() => caeInput.current?.click()}
            >
              <Upload /> {t('materialsLibrary.caeChoose')}
            </button>
            {cae && (
              <div className="cae-preview" data-testid="cae-preview-panel">
                <p className="field-hint">
                  {cae.file} · {cae.sha256.slice(0, 10)} ·{' '}
                  {t('materialsLibrary.caeSummary', {
                    registrable: cae.registrable,
                    available: cae.available,
                    total: cae.cards.length,
                  })}
                </p>
                <div className="cae-cards">
                  {cae.cards.map((card) => {
                    const assessment = card.assessment
                    return (
                      <div
                        key={card.key}
                        className={
                          'cae-card ' +
                          (assessment.available
                            ? 'eligible'
                            : assessment.registrable
                              ? 'needs'
                              : 'blocked')
                        }
                        data-testid={
                          assessment.available ? 'cae-card-available' : 'cae-card-registrable'
                        }
                        title={assessment.reasons.map((reason) => reason.code).join(' · ')}
                      >
                        <label className="check">
                          <input
                            type="checkbox"
                            disabled={!assessment.registrable}
                            checked={caeKeys.includes(card.key)}
                            onChange={(event) =>
                              setCaeKeys((current) =>
                                event.target.checked
                                  ? [...current, card.key]
                                  : current.filter((key) => key !== card.key),
                              )
                            }
                          />
                          <span>{card.name}</span>
                        </label>
                        <small>
                          {assessment.available
                            ? t('materialsLibrary.caeAvailable')
                            : assessment.registrable
                              ? assessment.needs
                                  .map((need) =>
                                    t(
                                      ('materialsLibrary.caeNeed.' + need) as TranslationKey,
                                    ),
                                  )
                                  .join(' · ')
                              : assessment.reasons
                                  .map((reason) =>
                                    t(('readiness.' + reason.code) as TranslationKey),
                                  )
                                  .join(' · ')}
                        </small>
                        {assessment.registrable && (
                          <label className="cae-family">
                            {t('materialsLibrary.caeFamily')}
                            <select
                              aria-label={
                                t('materialsLibrary.caeFamily') + ' · ' + card.name
                              }
                              value={caeFamilies[card.key] ?? assessment.family_hint}
                              onChange={(event) =>
                                setCaeFamilies((current) => ({
                                  ...current,
                                  [card.key]: event.target.value as 'polymer' | 'metal',
                                }))
                              }
                            >
                              <option value="polymer">{t('materials.familyPolymer')}</option>
                              <option value="metal">{t('materials.familyMetal')}</option>
                            </select>
                          </label>
                        )}
                      </div>
                    )
                  })}
                </div>
                <label>
                  {t('materialsLibrary.caeFamilyDefault')}
                  <select
                    aria-label={t('materialsLibrary.caeFamilyDefault')}
                    value={caeFamily}
                    onChange={(event) =>
                      setCaeFamily(event.target.value as 'polymer' | 'metal')
                    }
                  >
                    <option value="polymer">{t('materials.familyPolymer')}</option>
                    <option value="metal">{t('materials.familyMetal')}</option>
                  </select>
                </label>
                <label>
                  {t('materialsLibrary.caeUnits')}
                  <select
                    aria-label={t('materialsLibrary.caeUnits')}
                    value={caeUnits}
                    onChange={(event) => setCaeUnits(event.target.value)}
                  >
                    <option value="N-mm-s-tonne">N · mm · s · tonne</option>
                  </select>
                </label>
                <button
                  type="button"
                  data-testid="cae-import"
                  disabled={busy || !caeKeys.length}
                  onClick={importCae}
                >
                  {t('materialsLibrary.caeImport', { count: caeKeys.length })}
                </button>
              </div>
            )}
            <h3>
              <FileDown size={15} /> {t('materialsLibrary.caeExportTitle')}
            </h3>
            <p>{t('materialsLibrary.caeExportHelp')}</p>
            <label>
              {t('materialsLibrary.caeFolder')}
              <input
                value={exportFolder}
                placeholder="C:\\path\\to\\folder"
                onChange={(event) => setExportFolder(event.target.value)}
              />
            </label>
            <div className="row-actions">
              <button type="button" disabled={busy} onClick={chooseFolder}>
                <FolderOpen /> {t('materialsLibrary.caeBrowse')}
              </button>
              <button
                type="button"
                data-testid="cae-export"
                disabled={busy || !exportFolder.trim()}
                onClick={exportCae}
              >
                <FileDown /> {t('materialsLibrary.caeExport')}
              </button>
            </div>
          </div>
        </aside>

        <section
          className="card library-editor"
          data-material-id={detail?.id ?? ''}
          data-loading={selected && detail?.id !== selected ? 'true' : 'false'}
        >
          {detail && detail.id === selected ? (
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
              {draft.model === 'cae_law' ? (
                <div className="cae-law" data-testid="cae-law-view">
                  <h3>{t('materialsLibrary.caeLawTitle')}</h3>
                  <p className="field-hint">{t('materialsLibrary.caeLawReadOnly')}</p>
                  {Object.entries({
                    elastic:
                      draft.young != null && draft.poisson != null
                        ? ({
                            table: [[draft.young, draft.poisson]],
                          } as CaeLawBlock)
                        : undefined,
                    hyperfoam: draft.hyperfoam as CaeLawBlock | null | undefined,
                    hyperelastic: draft.hyperelastic as CaeLawBlock | null | undefined,
                    viscoelastic: draft.viscoelastic as CaeLawBlock | null | undefined,
                    mullins: draft.mullins as CaeLawBlock | null | undefined,
                    plastic: draft.plastic as CaeLawBlock | null | undefined,
                  })
                    .filter(([, block]) => Boolean(block))
                    .map(([key, block]) => (
                      <section key={key} className="cae-law-block">
                        <h4>
                          {key}
                          {block?.type ? ' · ' + block.type : ''}
                          {block?.n ? ' · N=' + block.n : ''}
                          {block?.moduli ? ' · ' + block.moduli : ''}
                          {block?.moduli_time_scale ? ' · ' + block.moduli_time_scale : ''}
                          {block?.time ? ' · ' + block.time : ''}
                        </h4>
                        <table className="cae-table">
                          <tbody>
                            {lawRows(block)
                              .slice(0, 12)
                              .map((row, index) => (
                                <tr key={index}>
                                  {row.map((value, column) => (
                                    <td key={column}>{value}</td>
                                  ))}
                                </tr>
                              ))}
                          </tbody>
                        </table>
                        {lawRows(block).length > 12 && (
                          <small>
                            {t('materialsLibrary.caeRowsShown', {
                              shown: 12,
                              total: lawRows(block).length,
                            })}
                          </small>
                        )}
                      </section>
                    ))}
                  <small>{t('materialsLibrary.caeSourceNote')}</small>
                </div>
              ) : (
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
                        c10: model === 'neo_hookean' ? (old.c10 ?? 0.5) : old.c10,
                        d1: model === 'neo_hookean' ? (old.d1 ?? 0.01) : old.d1,
                      }))
                    }}
                  >
                    <option value="linear_elastic">{t('materials.modelLinear')}</option>
                    <option value="hyperfoam_test">{t('materials.modelHyperfoam')}</option>
                    <option value="neo_hookean">{t('materials.modelNeoHookean')}</option>
                  </select>
                </label>
              )}
              <label>
                {t('materials.family')}
                <select
                  aria-label={t('materials.family')}
                  value={draft.family}
                  onChange={(event) =>
                    setDraft((old) => ({
                      ...old,
                      family: event.target.value as 'polymer' | 'metal',
                    }))
                  }
                >
                  <option value="polymer">{t('materials.familyPolymer')}</option>
                  <option value="metal">{t('materials.familyMetal')}</option>
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
              {draft.model === 'cae_law' ? (
                <label>
                  {t('materials.density')} <span className="unit">t/mm³</span>
                  <input
                    aria-label={t('materials.density')}
                    aria-invalid={caeDensityInvalid || undefined}
                    inputMode="decimal"
                    value={densityText}
                    placeholder={t('materialsLibrary.densityMissing')}
                    onChange={(event) => setDensityText(event.target.value)}
                  />
                  <small>{t('materialsLibrary.densityHelp')}</small>
                </label>
              ) : (
                <NumberInput
                  label={t('materials.density')}
                  value={draft.density ?? 1.1e-9}
                  min={1e-15}
                  onChange={(density) => setDraft((old) => ({ ...old, density }))}
                />
              )}
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
              ) : draft.model === 'neo_hookean' ? (
                <>
                  <NumberInput
                    label={t('materials.c10')}
                    value={draft.c10 ?? 0.5}
                    min={1e-9}
                    onChange={(c10) => setDraft((old) => ({ ...old, c10 }))}
                  />
                  <small>{t('materials.c10Hint')}</small>
                  <NumberInput
                    label={t('materials.d1')}
                    value={draft.d1 ?? 0.01}
                    min={1e-9}
                    onChange={(d1) => setDraft((old) => ({ ...old, d1 }))}
                  />
                  <small>{t('materials.d1Hint')}</small>
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
          ) : selected ? null : (
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
