/**
 * Axis behaviour when the displayed series is mirrored.
 *
 * A sign control negates the data. The old plot kept the previous positive axis
 * limits, so a reversed positive-travel curve was clipped. Two cases must be
 * treated differently:
 *
 *  - an automatically fitted axis is refitted to the transformed series;
 *  - a deliberately zoomed axis mirrors its visible interval, so the same
 *    physical portion stays visible and reversing twice restores the range.
 */

export interface AxisLike {
  range?: number[]
  autorange?: boolean | 'reversed' | 'min' | 'max'
}

function finiteInterval(value: number[] | undefined): value is [number, number] {
  return (
    Array.isArray(value) &&
    value.length === 2 &&
    Number.isFinite(value[0]) &&
    Number.isFinite(value[1])
  )
}

function sameLength(a: number[], b: number[]) {
  return a.length === b.length && a.length > 0
}

/** True when `next` is `previous` with every value negated, within tolerance. */
export function isMirrored(previous: number[], next: number[]) {
  if (!sameLength(previous, next)) return false
  const scale = Math.max(1, ...previous.map((v) => Math.abs(v)))
  const tolerance = scale * 1e-9
  return previous.every(
    (value, index) => Math.abs(next[index] + value) <= tolerance,
  )
}

/** The same visible interval on the opposite side of zero. */
export function mirrorInterval([low, high]: [number, number]): [number, number] {
  return [-high, -low]
}

/**
 * The range to request for one axis given the previous and next series.
 *
 * Returns `undefined` to let Plotly refit the axis automatically.
 */
export function nextAxisRange(
  previous: number[] | undefined,
  next: number[],
  axis: AxisLike | undefined,
): number[] | undefined {
  // Plotly reports `autorange: true` while the axis follows the data. Any other
  // value with a concrete interval is a deliberate zoom that must be mirrored.
  const zoomed = axis?.autorange !== true && finiteInterval(axis?.range)
  if (!previous) return zoomed ? axis!.range : undefined
  if (isMirrored(previous, next)) {
    if (zoomed) return mirrorInterval(axis!.range as [number, number])
    return undefined
  }
  return zoomed ? axis!.range : undefined
}
