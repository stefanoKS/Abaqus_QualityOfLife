import { useEffect, useId, useMemo, useState } from 'react'
import { AlertTriangle, CircleAlert, Copy, Plus, Trash2 } from 'lucide-react'
import type { Project } from '../../api'
import { useTranslate } from '../../i18n'
import type { TranslationKey } from '../../i18n'
import { Plot } from '../../Plot'
import { setFieldInvalid } from '../../shared/components/draftGuard'

type Material = Project['materials'][number]
type Triple = [number, number, number]

export interface MaterialIssues {
  errors: TranslationKey[]
  warnings: TranslationKey[]
}

const MODELS: { id: Material['model']; labelKey: TranslationKey }[] = [
  { id: 'linear_elastic', labelKey: 'materials.modelLinear' },
  { id: 'hyperfoam_test', labelKey: 'materials.modelHyperfoam' },
  { id: 'neo_hookean', labelKey: 'materials.modelNeoHookean' },
]

/**
 * Card-level validation. Errors block saving; warnings are engineering advice
 * and never prevent a legitimate Abaqus convention from being submitted.
 */
export function materialIssues(material: Material): MaterialIssues {
  const errors: TranslationKey[] = []
  const warnings: TranslationKey[] = []
  if (!material.name.trim()) errors.push('materials.err.empty')
  // A registered CAE record may legitimately have no density: it stays visible
  // and exportable, and the run path names the missing input. An explicitly
  // zero or negative density is still an error.
  if (material.density === null || material.density === undefined) {
    warnings.push('materials.warn.densityMissing')
  } else if (!Number.isFinite(material.density) || material.density <= 0) {
    errors.push('materials.err.density')
  }
  if (material.model === 'linear_elastic') {
    if (material.young === null || !Number.isFinite(material.young) || material.young <= 0)
      errors.push('materials.err.young')
    if (
      material.poisson === null ||
      !Number.isFinite(material.poisson) ||
      material.poisson <= -1 ||
      material.poisson >= 0.5
    )
      errors.push('materials.err.poisson')
  } else if (material.model === 'neo_hookean') {
    if (material.c10 === null || !Number.isFinite(material.c10) || material.c10 <= 0)
      errors.push('materials.err.c10')
    if (material.d1 === null || !Number.isFinite(material.d1) || material.d1 <= 0)
      errors.push('materials.err.d1')
  } else if (material.model === 'cae_law') {
    // The registered law is typed and validated by the server; the simplified
    // editor never rewrites it. Only the density may be completed here.
    const blocks = ['hyperfoam', 'hyperelastic', 'plastic', 'thermal'] as const
    if (!blocks.some((key) => Boolean((material as unknown as Record<string, unknown>)[key]))) {
      errors.push('materials.err.noLaw')
    }
  } else {
    const rows = material.test_data
    if (rows.length < 3) errors.push('materials.err.samples')
    if (rows.some((row) => row.some((value) => !Number.isFinite(value))))
      errors.push('materials.err.finite')
    if (!errors.length) {
      const strains = rows.map((row) => row[1])
      if (strains.some((strain, index) => index > 0 && strain <= strains[index - 1]))
        warnings.push('materials.warn.strainOrder')
      if (rows.some((row) => Math.abs(row[2]) > Math.abs(row[1])))
        warnings.push('materials.warn.lateral')
    }
  }
  return { errors, warnings }
}

function nextMaterialId(materials: Material[]) {
  const used = new Set(materials.map((m) => m.id))
  let index = materials.length + 1
  while (used.has('material_' + index)) index++
  return 'material_' + index
}

const PALETTE = ['#2f9e8f', '#5d8b3a', '#b4762b', '#7a5ba8', '#2f6f9e', '#a34b54']

function freshCard(materials: Material[], name: string): Material {
  const id = nextMaterialId(materials)
  return {
    id,
    name,
    version: 1,
    color: PALETTE[materials.length % PALETTE.length],
    model: 'linear_elastic',
    density: 1.1e-9,
    young: 5,
    poisson: 0.49,
    c10: null,
    d1: null,
    test_data: [],
    family: 'polymer',
    library_id: null,
    library_version: null,
    hyperfoam: null,
    hyperelastic: null,
    viscoelastic: null,
    plastic: null,
    mullins: null,
    thermal: null,
  }
}

/** Compact draft cell so a half-typed number never reaches the saved setup. */
function Cell({
  value,
  onCommit,
  label,
  disabled,
  invalid,
}: {
  value: number
  onCommit: (value: number) => void
  label: string
  disabled?: boolean
  invalid?: boolean
}) {
  const id = useId()
  const [draft, setDraft] = useState(() => String(value))
  useEffect(() => setDraft(String(value)), [value])
  const malformed = draft.trim() !== '' && !Number.isFinite(Number(draft))
  useEffect(() => {
    setFieldInvalid(id, malformed)
    return () => setFieldInvalid(id, false)
  }, [id, malformed])
  return (
    <input
      type="number"
      inputMode="decimal"
      step="any"
      aria-label={label}
      aria-invalid={invalid || malformed || undefined}
      disabled={disabled}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        const next = Number(draft)
        if (Number.isFinite(next) && draft.trim() !== '') {
          if (next !== value) onCommit(next)
        }
        // Keep a malformed draft visible; Escape is the explicit way back.
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') e.currentTarget.blur()
        if (e.key === 'Escape') {
          setDraft(String(value))
          setFieldInvalid(id, false)
        }
      }}
    />
  )
}

interface PasteLine {
  line: number
  cells: string[]
  row: Triple | null
  reason: 'columns' | 'number' | null
}

interface PasteAnalysis {
  lines: PasteLine[]
  rows: Triple[]
  headerLine: number | null
}

/**
 * Parse pasted laboratory data into a reviewable draft.
 *
 * Documented headers (three alphabetic column names) and blank lines are
 * supported. Any other non-blank line that is not exactly three finite numbers
 * is rejected with its source row number; the caller must not apply the paste
 * while a rejection exists.
 */
function analysePaste(paste: string): PasteAnalysis {
  const lines: PasteLine[] = []
  const rows: Triple[] = []
  let headerLine: number | null = null
  paste.split(/\r?\n/).forEach((raw, index) => {
    const line = index + 1
    if (!raw.trim()) return
    const cells = raw.trim().split(/[\s,;]+/).filter(Boolean)
    if (cells.length !== 3) {
      lines.push({ line, cells, row: null, reason: 'columns' })
      return
    }
    const numbers = cells.map((cell) => Number(cell))
    if (numbers.every((value) => Number.isFinite(value))) {
      const row = numbers as Triple
      rows.push(row)
      lines.push({ line, cells, row, reason: null })
      return
    }
    const alphabetic = cells.every((cell) => /[A-Za-z]/.test(cell) && !/\d/.test(cell))
    if (headerLine === null && lines.length === 0 && alphabetic) {
      headerLine = line
      return
    }
    lines.push({ line, cells, row: null, reason: 'number' })
  })
  return { lines, rows, headerLine }
}

function TestDataTable({
  material,
  disabled,
  onChange,
}: {
  material: Material
  disabled: boolean
  onChange: (rows: Triple[]) => void
}) {
  const t = useTranslate()
  const [paste, setPaste] = useState('')
  const [pasting, setPasting] = useState(false)
  const rows = material.test_data
  // Parse into a draft first. A malformed non-blank row blocks applying, and the
  // saved card stays untouched until the engineer accepts a complete preview.
  const analysis = useMemo(() => analysePaste(paste), [paste])
  const rejected = analysis.lines.filter((line) => !line.row)
  const canApply = rejected.length === 0 && analysis.rows.length > 0
  function update(index: number, column: 0 | 1 | 2, value: number) {
    const next = rows.map((row, i) =>
      i === index ? ([column === 0 ? value : row[0], column === 1 ? value : row[1], column === 2 ? value : row[2]] as Triple) : row,
    )
    onChange(next)
  }
  function applyPaste() {
    if (!canApply) return
    // Values are kept exactly as parsed, in source order. Nothing is sorted,
    // rounded, deduplicated or invented.
    onChange(analysis.rows)
    setPaste('')
    setPasting(false)
  }
  return (
    <div className="test-data">
      <div className="table-scroll">
        <table className="test-table">
          <thead>
            <tr>
              <th scope="col">{t('materials.row', { row: '#' })}</th>
              <th scope="col">{t('materials.stress')}</th>
              <th scope="col">{t('materials.nominalStrain')} (軸)</th>
              <th scope="col">{t('materials.nominalStrain')} (横)</th>
              <th scope="col">
                <span className="sr-only">{t('materials.removeRow')}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const bad = row.some((value) => !Number.isFinite(value))
              return (
                <tr key={index}>
                  <td>{index + 1}</td>
                  <td>
                    <Cell
                      value={row[0]}
                      label={t('materials.row', { row: index + 1 }) + ' ' + t('materials.stress')}
                      invalid={bad}
                      disabled={disabled}
                      onCommit={(value) => update(index, 0, value)}
                    />
                  </td>
                  <td>
                    <Cell
                      value={row[1]}
                      label={
                        t('materials.row', { row: index + 1 }) + ' ' + t('materials.nominalStrain') + ' 軸'
                      }
                      invalid={bad}
                      disabled={disabled}
                      onCommit={(value) => update(index, 1, value)}
                    />
                  </td>
                  <td>
                    <Cell
                      value={row[2]}
                      label={
                        t('materials.row', { row: index + 1 }) + ' ' + t('materials.nominalStrain') + ' 横'
                      }
                      invalid={bad}
                      disabled={disabled}
                      onCommit={(value) => update(index, 2, value)}
                    />
                  </td>
                  <td>
                    <button
                      type="button"
                      className="icon"
                      aria-label={t('materials.row', { row: index + 1 }) + ' ' + t('materials.removeRow')}
                      disabled={disabled || rows.length <= 1}
                      onClick={() => onChange(rows.filter((_, i) => i !== index))}
                    >
                      <Trash2 />
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="row-actions">
        <button
          type="button"
          disabled={disabled}
          onClick={() => {
            const last = rows[rows.length - 1]
            const nextStrain = last ? last[1] + 0.05 : 0.05
            onChange([...rows, [0, nextStrain, -nextStrain / 2] as Triple])
          }}
        >
          <Plus />
          {t('materials.addRow')}
        </button>
        <button type="button" disabled={disabled} onClick={() => setPasting((v) => !v)}>
          {t('materials.pasteTitle')}
        </button>
      </div>
      {pasting && (
        <div className="paste-panel">
          <small>{t('materials.pasteHint')}</small>
          <small className="field-hint">{t('materials.pasteConventions')}</small>
          <textarea
            aria-label={t('materials.pasteTitle')}
            value={paste}
            rows={5}
            onChange={(e) => setPaste(e.target.value)}
          />
          {paste.trim() !== '' && (
            <p className="paste-summary" data-testid="paste-summary">
              {t('materials.pasteSummary', {
                accepted: analysis.rows.length,
                rejected: rejected.length,
              })}
            </p>
          )}
          {analysis.headerLine !== null && (
            <small>{t('materials.pasteHeader', { line: analysis.headerLine })}</small>
          )}
          {rejected.length > 0 && (
            <ul className="paste-rejected" data-testid="paste-rejected">
              {rejected.map((line) => (
                <li key={line.line}>
                  {line.reason === 'columns'
                    ? t('materials.pasteColumns', { line: line.line, count: line.cells.length })
                    : t('materials.pasteNumber', { line: line.line })}
                </li>
              ))}
            </ul>
          )}
          {analysis.rows.length >= 2 && (
            <Plot
              x={analysis.rows.map((row) => row[1])}
              y={analysis.rows.map((row) => row[0])}
              xlabel={t('materials.nominalStrain')}
              ylabel={t('materials.stress')}
            />
          )}
          <div className="row-actions">
            <button type="button" disabled={!canApply} onClick={applyPaste}>
              {t('materials.pasteApplyCount', { count: analysis.rows.length })}
            </button>
            <button
              type="button"
              onClick={() => {
                setPaste('')
                setPasting(false)
              }}
            >
              {t('common.cancel')}
            </button>
          </div>
          {rejected.length > 0 && (
            <small className="field-error" role="alert">
              {t('materials.pasteBlocked')}
            </small>
          )}
        </div>
      )}
      {rows.length >= 2 && (
        <Plot
          x={rows.map((row) => row[1])}
          y={rows.map((row) => row[0])}
          xlabel={t('materials.nominalStrain')}
          ylabel={t('materials.stress')}
        />
      )}
    </div>
  )
}

export function MaterialEditor({
  materials,
  faces,
  selected,
  onSelect,
  onAdd,
  onDuplicate,
  onDelete,
  onUpdate,
  disabled,
  onRevealRegion,
}: {
  materials: Material[]
  faces: Project['faces']
  selected: string | null
  onSelect: (id: string) => void
  onAdd: () => Material
  onDuplicate: (id: string) => void
  onDelete: (id: string) => void
  onUpdate: (id: string, patch: Partial<Material>) => void
  disabled: boolean
  onRevealRegion: (faceId: string) => void
}) {
  const t = useTranslate()
  const nameId = useId()
  const card = materials.find((m) => m.id === selected) ?? materials[0]
  const usage = useMemo(() => {
    const map = new Map<string, string[]>()
    for (const face of faces) {
      if (!face.material) continue
      map.set(face.material, [...(map.get(face.material) ?? []), face.name])
    }
    return map
  }, [faces])
  const issues = card ? materialIssues(card) : { errors: [], warnings: [] }
  const used = card ? (usage.get(card.id) ?? []) : []
  return (
    <div className="material-editor">
      <div className="material-list">
        {materials.map((material) => (
          <button
            type="button"
            key={material.id}
            className={'material-row ' + (card?.id === material.id ? 'active' : '')}
            aria-pressed={card?.id === material.id}
            onClick={() => onSelect(material.id)}
          >
            <span className="swatch" style={{ background: material.color }} />
            <span className="material-name">{material.name}</span>
            <small>
              v{material.version} · {t('materials.usedBy', { count: usage.get(material.id)?.length ?? 0 })}
            </small>
          </button>
        ))}
      </div>
      <div className="row-actions">
        <button type="button" disabled={disabled} onClick={() => onSelect(onAdd().id)}>
          <Plus />
          {t('materials.new')}
        </button>
        {card && (
          <>
            <button type="button" disabled={disabled} onClick={() => onDuplicate(card.id)}>
              <Copy />
              {t('materials.duplicate')}
            </button>
            <button
              type="button"
              disabled={disabled || used.length > 0}
              aria-label={t('materials.delete')}
              title={
                used.length
                  ? t('materials.deleteBlocked', { count: used.length })
                  : t('materials.delete')
              }
              onClick={() => {
                if (window.confirm(t('materials.deleteConfirm', { name: card.name }))) onDelete(card.id)
              }}
            >
              <Trash2 />
            </button>
          </>
        )}
      </div>
      {used.length > 0 && (
        <div className="usage-list">
          <small>{t('materials.usedBy', { count: used.length })}</small>
          <div className="region-list">
            {faces
              .filter((face) => face.material === card?.id)
              .map((face) => (
                <button key={face.id} type="button" onClick={() => onRevealRegion(face.id)}>
                  <span className="swatch" style={{ background: card?.color }} />
                  {face.name}
                </button>
              ))}
          </div>
        </div>
      )}
      {card && (
        <>
          <label htmlFor={nameId}>
            {t('materials.name')}
            <input
              id={nameId}
              maxLength={160}
              value={card.name}
              disabled={disabled}
              onChange={(e) => onUpdate(card.id, { name: e.target.value })}
            />
          </label>
          <label>
            {t('materials.model')}
            <select
              value={card.model}
              // A registered CAE card's law is not rewritten by this simplified
              // editor; a new library version is how a missing input is supplied.
              disabled={disabled || card.model === 'cae_law'}
              onChange={(e) => {
                const model = e.target.value as Material['model']
                // Switching to hyperfoam needs the minimum sample set to stay valid.
                const rows =
                  model === 'hyperfoam_test' && card.test_data.length < 3
                    ? [
                        [0, 0.05, -0.025],
                        [0, 0.1, -0.05],
                        [0, 0.15, -0.075],
                      ]
                    : card.test_data
                onUpdate(card.id, {
                  model,
                  test_data: rows as Triple[],
                  young: model === 'linear_elastic' ? (card.young ?? 5) : card.young,
                  poisson: model === 'linear_elastic' ? (card.poisson ?? 0.49) : card.poisson,
                  c10: model === 'neo_hookean' ? (card.c10 ?? 0.5) : card.c10,
                  d1: model === 'neo_hookean' ? (card.d1 ?? 0.01) : card.d1,
                })
              }}
            >
              {card.model === 'cae_law' && (
                <option value="cae_law">{t('materialsLibrary.caeLawTitle')}</option>
              )}
              {MODELS.map((option) => (
                <option key={option.id} value={option.id}>
                  {t(option.labelKey)}
                </option>
              ))}
            </select>
          </label>
          <label>
            {t('materials.family')}
            <select
              aria-label={t('materials.family')}
              value={card.family ?? 'polymer'}
              disabled={disabled}
              onChange={(e) =>
                onUpdate(card.id, { family: e.target.value as Material['family'] })
              }
            >
              <option value="polymer">{t('materials.familyPolymer')}</option>
              <option
                value="metal"
                disabled={card.model !== 'linear_elastic' && card.model !== 'cae_law'}
              >
                {t('materials.familyMetal')}
              </option>
            </select>
          </label>
          <label>
            {t('materials.color')}
            <input
              type="color"
              value={card.color}
              disabled={disabled}
              onChange={(e) => onUpdate(card.id, { color: e.target.value })}
            />
          </label>
          <label>
            {t('materials.density')}
            <input
              type="number"
              inputMode="decimal"
              step="any"
              min={0}
              value={
                card.density != null && Number.isFinite(card.density) ? card.density : ''
              }
              disabled={disabled}
              onChange={(e) => onUpdate(card.id, { density: Number(e.target.value) })}
            />
          </label>
          {card.model === 'linear_elastic' ? (
            <>
              <label>
                {t('materials.young')}
                <input
                  type="number"
                  inputMode="decimal"
                  step="any"
                  min={0}
                  value={card.young ?? ''}
                  disabled={disabled}
                  onChange={(e) => onUpdate(card.id, { young: Number(e.target.value) })}
                />
              </label>
              <label>
                {t('materials.poisson')}
                <input
                  type="number"
                  inputMode="decimal"
                  step="any"
                  min={-0.999}
                  max={0.4999}
                  value={card.poisson ?? ''}
                  disabled={disabled}
                  onChange={(e) => onUpdate(card.id, { poisson: Number(e.target.value) })}
                />
              </label>
            </>
          ) : card.model === 'neo_hookean' ? (
            <>
              <label>
                {t('materials.c10')}
                <input
                  type="number"
                  inputMode="decimal"
                  step="any"
                  min={0}
                  value={card.c10 ?? ''}
                  disabled={disabled}
                  onChange={(e) => onUpdate(card.id, { c10: Number(e.target.value) })}
                />
                <small>{t('materials.c10Hint')}</small>
              </label>
              <label>
                {t('materials.d1')}
                <input
                  type="number"
                  inputMode="decimal"
                  step="any"
                  min={0}
                  value={card.d1 ?? ''}
                  disabled={disabled}
                  onChange={(e) => onUpdate(card.id, { d1: Number(e.target.value) })}
                />
                <small>{t('materials.d1Hint')}</small>
              </label>
            </>
          ) : card.model === 'cae_law' ? (
            <div className="cae-law" data-testid="cae-law-view">
              <h3>{t('materialsLibrary.caeLawTitle')}</h3>
              <p className="field-hint">{t('materialsLibrary.caeLawReadOnly')}</p>
              <ul className="issue-list">
                {(
                  [
                    ['elastic', card.young != null && card.poisson != null, ''],
                    [
                      'hyperfoam',
                      Boolean(card.hyperfoam),
                      card.hyperfoam
                        ? `N=${card.hyperfoam.n} · ${card.hyperfoam.moduli}${
                            card.hyperfoam.test_data ? ' · test data' : ''
                          }`
                        : '',
                    ],
                    [
                      'hyperelastic',
                      Boolean(card.hyperelastic),
                      card.hyperelastic
                        ? `${card.hyperelastic.type} · ${card.hyperelastic.moduli_time_scale}`
                        : '',
                    ],
                    [
                      'viscoelastic',
                      Boolean(card.viscoelastic),
                      card.viscoelastic ? card.viscoelastic.time : '',
                    ],
                    ['mullins', Boolean(card.mullins), ''],
                    ['plastic', Boolean(card.plastic), ''],
                    ['thermal', Boolean(card.thermal), ''],
                  ] as [string, boolean, string][]
                )
                  .filter(([, present]) => present)
                  .map(([key, , detail]) => (
                    <li key={key}>
                      {key}
                      {detail ? ' · ' + detail : ''}
                    </li>
                  ))}
              </ul>
              <small>{t('materialsLibrary.caeSourceNote')}</small>
            </div>
          ) : (
            <>
              <h3>
                {t('materials.testData')} ·{' '}
                {t('materials.samples', { count: card.test_data.length })}
              </h3>
              <TestDataTable
                material={card}
                disabled={disabled}
                onChange={(rows) => onUpdate(card.id, { test_data: rows })}
              />
            </>
          )}
          <dl>
            <div>
              <dt>{t('materials.cardVersion')}</dt>
              <dd>v{card.version}</dd>
            </div>
          </dl>
          <small>{t('materials.versionBump')}</small>
          {(issues.errors.length > 0 || issues.warnings.length > 0) && (
            <ul className="issue-list">
              {issues.errors.map((key) => (
                <li key={key} className="issue error">
                  <CircleAlert />
                  {t(key)}
                </li>
              ))}
              {issues.warnings.map((key) => (
                <li key={key} className="issue warning">
                  <AlertTriangle />
                  {t(key)}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}

export { freshCard, TestDataTable }
