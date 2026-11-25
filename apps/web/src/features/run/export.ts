/**
 * Two-row CSV resampling for the Results load and door-pressure graphs.
 *
 * The contract is deliberately small and deterministic:
 *   row 1: the engineering abscissa label in A1, numeric samples from B1;
 *   row 2: the engineering ordinate label in A2, numeric samples from B2.
 *
 * Uniform grids are built from integer indices (`q = k * spacing`) so 0.65 mm
 * samples produce 1.95 mm rather than a drifting sum. The exact last measured
 * position is appended once when it falls between grid points. Measured values
 * win at a measured coordinate; between two adjacent valid samples the value is
 * linearly interpolated. Missing values stay empty cells and are never bridged.
 *
 * User input is validated here, not in the browser download path, and the grid
 * is bounded so an impractically small interval cannot allocate without limit.
 */

export type Sample = {
  /** Measured abscissa in mm, or null when the sample has no measured stroke. */
  x: number | null
  /** Measured ordinate, or null when it was not measured. */
  y: number | null
  /**
   * An acquisition break (step boundary or an unreadable block). No uniform
   * sample may be interpolated across it.
   */
  break?: boolean
}

export type UniformResult =
  | {
      kind: 'ok'
      points: Sample[]
      /** True when the exact last measured position was appended once. */
      appended: boolean
    }
  | { kind: 'invalid'; reason: 'spacing' | 'too_many' }
  | { kind: 'ambiguous'; reason: 'multivalued' | 'unordered' | 'no_samples' }

/** mm. A grid endpoint within this distance of the last measured position snaps. */
export const GRID_TOLERANCE_MM = 1e-9

/** The largest uniform grid this client will build. */
export const MAX_GRID_POINTS = 200_000

/** Distinct measured values at the same position are a multivalued curve. */
const VALUE_TOLERANCE = 1e-12

export const DEFAULT_STROKE_INTERVAL_MM = 1.0
export const DEFAULT_STATION_INTERVAL_MM = 1.3

/** Parse a user-entered interval. Blank, zero, negative and non-finite fail. */
export function parseSpacing(
  text: string,
): { ok: true; value: number } | { ok: false; reason: 'blank' | 'invalid' | 'bounds' } {
  const trimmed = text.trim()
  if (trimmed === '') return { ok: false, reason: 'blank' }
  const value = Number(trimmed)
  if (!Number.isFinite(value) || value <= 0) return { ok: false, reason: 'invalid' }
  // Guard against values that are finite but so small that every grid is
  // unbounded; the exact allocation limit is enforced by uniformSamples.
  if (value < 1e-9) return { ok: false, reason: 'bounds' }
  return { ok: true, value }
}

function sameValue(one: number | null, other: number | null) {
  if (one === null || other === null) return one === other
  return (
    Math.abs(one - other) <=
    VALUE_TOLERANCE * Math.max(1, Math.abs(one), Math.abs(other))
  )
}

type Measured = { x: number; y: number | null; index: number }

function measured(samples: Sample[]): Measured[] {
  const points: Measured[] = []
  samples.forEach((sample, index) => {
    if (sample.x !== null && Number.isFinite(sample.x)) {
      points.push({ x: sample.x, y: sample.y, index })
    }
  })
  return points
}

/**
 * True when the acquisition order between two measured samples contains an
 * unlocated sample, a missing ordinate, an explicit break or an unreadable
 * block. Interpolating across any of them would invent a measurement.
 */
function blocked(samples: Sample[], from: number, to: number) {
  for (let index = from + 1; index < to; index++) {
    const sample = samples[index]
    if (sample.break) return true
    if (sample.x === null || sample.y === null) return true
    if (!Number.isFinite(sample.x) || !Number.isFinite(sample.y)) return true
  }
  return false
}

/**
 * Validate the measured support before building a uniform grid.
 *
 * A dwell with different loads at one stroke, or an unload/reload, is a
 * multivalued curve: averaging or sorting it would invent a physical state.
 * The caller can offer the original ordered samples instead.
 */
function ambiguity(samples: Measured[]): 'unordered' | 'multivalued' | null {
  for (let index = 0; index < samples.length; index++) {
    const current = samples[index]
    if (index > 0) {
      const previous = samples[index - 1]
      if (current.x < previous.x - GRID_TOLERANCE_MM) return 'unordered'
      if (Math.abs(current.x - previous.x) <= GRID_TOLERANCE_MM) {
        if (previous.y === null || current.y === null) continue
        if (!sameValue(previous.y, current.y)) return 'multivalued'
      }
    }
  }
  return null
}

/** Value at an exact measured coordinate, or a conflict when it is multivalued. */
function exactValue(
  samples: Measured[],
  q: number,
): { found: boolean; value: number | null; conflict: boolean } {
  let found = false
  let value: number | null = null
  for (const sample of samples) {
    if (Math.abs(sample.x - q) > GRID_TOLERANCE_MM) continue
    if (!found) {
      found = true
      value = sample.y
      continue
    }
    if (!sameValue(value, sample.y)) return { found: true, value: null, conflict: true }
  }
  return { found, value, conflict: false }
}

/** Interpolate at q from the adjacent measured samples, honouring gaps. */
function interpolate(samples: Sample[], points: Measured[], q: number): number | null {
  let before = -1
  let after = -1
  for (let index = 0; index < points.length; index++) {
    if (points[index].x < q - GRID_TOLERANCE_MM) before = index
    else {
      after = index
      break
    }
  }
  if (before < 0 || after < 0) return null
  const x0 = points[before]
  const x1 = points[after]
  // A missing stroke, missing ordinate or explicit break between the two
  // bracketing samples is a real gap, not a straight line.
  if (blocked(samples, x0.index, x1.index)) return null
  if (x0.y === null || x1.y === null) return null
  if (x1.x - x0.x <= GRID_TOLERANCE_MM) return x0.y
  return x0.y + ((x1.y - x0.y) * (q - x0.x)) / (x1.x - x0.x)
}

/**
 * Build the uniform resampled export.
 *
 * Samples may be in acquisition order (load) or station order (pressure). The
 * exact last measured position is appended once when it is not already a grid
 * point within {@link GRID_TOLERANCE_MM}; a position on the grid is written once.
 */
export function uniformSamples(samples: Sample[], spacing: number): UniformResult {
  const points = measured(samples)
  if (!points.length) return { kind: 'ambiguous', reason: 'no_samples' }
  if (!Number.isFinite(spacing) || spacing <= 0) return { kind: 'invalid', reason: 'spacing' }
  const ambiguous = ambiguity(points)
  if (ambiguous) return { kind: 'ambiguous', reason: ambiguous }
  const last = points[points.length - 1].x
  let count = Math.floor(last / spacing)
  // A measured end within tolerance of the next grid point snaps to it instead
  // of being duplicated by a near-zero append.
  while ((count + 1) * spacing <= last + GRID_TOLERANCE_MM) count++
  if (count + 2 > MAX_GRID_POINTS) return { kind: 'invalid', reason: 'too_many' }

  const result: Sample[] = []
  let snapped = false
  for (let index = 0; index <= count; index++) {
    let q = index * spacing
    if (Math.abs(q - last) <= GRID_TOLERANCE_MM) {
      q = last
      snapped = true
    }
    if (q > last + GRID_TOLERANCE_MM) break
    const exact = exactValue(points, q)
    if (exact.conflict) return { kind: 'ambiguous', reason: 'multivalued' }
    result.push({ x: q, y: exact.found ? exact.value : interpolate(samples, points, q) })
  }
  let appended = false
  if (!snapped && Math.abs(result[result.length - 1].x! - last) > GRID_TOLERANCE_MM) {
    result.push({ x: last, y: points[points.length - 1].y })
    appended = true
  }
  return { kind: 'ok', points: result, appended }
}

/** Original measured samples, in acquisition/station order, with nulls kept. */
export function originalSamples(samples: Sample[]): Sample[] {
  return samples.map((sample) => ({ ...sample }))
}

/** Trim floating-point artifacts without discarding engineering precision. */
export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return ''
  const cleaned = Number(value.toPrecision(12))
  if (Object.is(cleaned, -0) || Object.is(value, -0)) return '0'
  return String(cleaned)
}

/** Exactly two comma-delimited rows, labels in column A, CRLF terminators. */
export function twoRowCsv(xLabel: string, yLabel: string, points: Sample[]): string {
  const xs = points.map((point) => (point.x === null ? '' : formatNumber(point.x)))
  const ys = points.map((point) => (point.y === null ? '' : formatNumber(point.y)))
  return [xLabel, ...xs].join(',') + '\r\n' + [yLabel, ...ys].join(',') + '\r\n'
}

/** Filesystem-safe token for a generated filename. */
export function safeName(value: string): string {
  const cleaned = value
    .normalize('NFKD')
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
  return cleaned || 'value'
}

/**
 * The displayed load ordinate label. The values in the result already carry
 * their recorded basis; this only names that basis and never rescales them.
 */
export function loadOrdinateLabel(index: {
  force_normalization?: string
  force_unit?: string
  force_basis?: string
  reporting_width_basis?: string
  reporting_width_mm?: number
}): string {
  const perLength =
    index.force_normalization === 'per_mm' || index.force_unit === 'N/mm'
  if (perLength) return 'F (N/mm)'
  const legacy =
    index.force_basis === 'legacy_unscaled' ||
    index.reporting_width_basis === 'legacy_thickness'
  const width = index.reporting_width_mm
  if (legacy || width === undefined || width === null || !Number.isFinite(width)) {
    return 'F (N)'
  }
  if (Math.abs(width - 1) <= 1e-12) return 'F (N/mm)'
  return `F (N/${formatNumber(width)}mm)`
}

/** Filename tag for the same recorded basis (no second rescaling). */
export function loadBasisTag(index: {
  force_normalization?: string
  force_unit?: string
  force_basis?: string
  reporting_width_basis?: string
  reporting_width_mm?: number
}): string {
  const perLength =
    index.force_normalization === 'per_mm' || index.force_unit === 'N/mm'
  if (perLength) return 'per-mm'
  const legacy =
    index.force_basis === 'legacy_unscaled' ||
    index.reporting_width_basis === 'legacy_thickness'
  const width = index.reporting_width_mm
  if (legacy || width === undefined || width === null || !Number.isFinite(width)) {
    return 'legacy-N'
  }
  if (Math.abs(width - 1) <= 1e-12) return 'per-mm'
  return `W${formatNumber(width)}mm`
}
