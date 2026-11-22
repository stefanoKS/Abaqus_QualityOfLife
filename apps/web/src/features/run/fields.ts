/** Pure result-field helpers shared by the Results view and its tests.
 *
 * Nothing here touches the DOM or the stored artifacts. A cell is keyed by
 * ``instance:element`` so two instances may carry the same ODB label without
 * merging; samples keep their integration-point identity; a missing component
 * is omitted rather than turned into a measured zero.
 */

export type FieldId = 'mises' | 'S11' | 'S22' | 'S33' | 'S12' | 'Umag' | 'U1' | 'U2'

export interface FieldSample {
  instance?: string
  element?: number
  integration_point?: number
  section_point?: number
  data?: number[]
}

export interface FieldFrame {
  fields?: Record<string, unknown> | null
}

export interface StressSample {
  value: number
  ip?: number
  section?: number
}

export interface StressCell {
  instance: string
  element: number
  samples: StressSample[]
}

/** Component-label-aware Mises invariant, mirroring the extractor. */
export function misesFrom(labels: string[], data: number[]): number | null {
  const index = new Map(labels.map((label, position) => [label.toUpperCase(), position]))
  if (!index.has('S11') && !index.has('S22')) return null
  const value = (name: string) => {
    const position = index.get(name)
    return position === undefined ? 0 : (data[position] ?? 0)
  }
  const s11 = value('S11'),
    s22 = value('S22'),
    s33 = value('S33'),
    s12 = value('S12'),
    s13 = value('S13'),
    s23 = value('S23')
  const squared =
    0.5 * ((s11 - s22) ** 2 + (s22 - s33) ** 2 + (s33 - s11) ** 2) +
    3 * (s12 ** 2 + s13 ** 2 + s23 ** 2)
  return Math.sqrt(Math.max(0, squared))
}

/** One element-keyed stress cell per instance; samples keep their IP identity. */
export function stressCells(frame: FieldFrame | null, field: FieldId) {
  const cells = new Map<string, StressCell>()
  const fields = (frame?.fields ?? {}) as Record<
    string,
    { components?: string[]; values?: FieldSample[] }
  >
  const add = (entry: FieldSample, value: number) => {
    if (!entry.instance || entry.element === undefined) return
    const key = entry.instance + ':' + entry.element
    const cell =
      cells.get(key) ?? ({ instance: entry.instance, element: entry.element, samples: [] } as StressCell)
    cell.samples.push({
      value,
      ip: entry.integration_point,
      section: entry.section_point,
    })
    cells.set(key, cell)
  }
  if (field === 'mises') {
    const invariant = fields.Mises
    if (invariant?.values?.length) {
      for (const entry of invariant.values) {
        const value = entry.data?.[0]
        if (typeof value === 'number') add(entry, value)
      }
    } else {
      const tensor = fields.S
      for (const entry of tensor?.values ?? []) {
        const value = misesFrom(tensor?.components ?? [], entry.data ?? [])
        if (value !== null) add(entry, value)
      }
    }
  } else {
    const tensor = fields.S
    const position = (tensor?.components ?? []).indexOf(field)
    if (position >= 0)
      for (const entry of tensor?.values ?? []) {
        const value = entry.data?.[position]
        if (typeof value === 'number') add(entry, value)
      }
  }
  return cells
}

/**
 * Cell display values: one value per element. The declared policy is the
 * maximum integration-point value; a component's colour is its magnitude while
 * the probe keeps the signed samples.
 */
export function elementDisplayValues(cells: Map<string, StressCell>, field: FieldId) {
  const values: Record<string, Record<number, number>> = {}
  for (const cell of cells.values()) {
    if (!cell.samples.length) continue
    const value =
      field === 'mises'
        ? Math.max(...cell.samples.map((sample) => sample.value))
        : Math.max(...cell.samples.map((sample) => Math.abs(sample.value)))
    ;(values[cell.instance] ??= {})[cell.element] = value
  }
  return values
}
