import type { Picked, SelectionMode, Surface } from './viewportModel'

export type ScreenPoint = [number, number, number]
export interface Projected {
  surface: Surface
  points: ScreenPoint[]
}

function segmentDistance(x: number, y: number, a: ScreenPoint, b: ScreenPoint) {
  const dx = b[0] - a[0],
    dy = b[1] - a[1]
  const t = Math.max(
    0,
    Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy || 1))
  )
  return {
    distance: Math.hypot(x - a[0] - t * dx, y - a[1] - t * dy),
    depth: a[2] + t * (b[2] - a[2]),
  }
}

function triangleDepth(
  x: number,
  y: number,
  a: ScreenPoint,
  b: ScreenPoint,
  c: ScreenPoint
) {
  const d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
  if (Math.abs(d) < 1e-10) return null
  const u = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / d
  const v = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / d
  const w = 1 - u - v
  return Math.min(u, v, w) >= -1e-8 ? a[2] * u + b[2] * v + c[2] * w : null
}

function selection(
  s: Surface,
  index: number,
  mode: SelectionMode
): Picked | null {
  if (mode === 'element' || mode === 'node') {
    const label =
      mode === 'element' ? s.elements?.[index]?.id : s.nodeIds?.[index]
    if (label === undefined) return null
    return {
      kind: mode,
      id: `${s.instance}:${label}`,
      instance: s.instance,
      label,
      value: mode === 'node' ? s.magnitudes?.[index] : undefined,
    }
  }
  const cad = s.cad ?? s.elements?.[index]
  const id = mode === 'component' ? cad?.component : cad?.entity
  return id
    ? {
        kind: mode,
        id,
        source: s.cad?.source,
        entity: cad?.entity,
        component: cad?.component,
      }
    : null
}

/** All distances are CSS pixels; projection includes device pixel ratio. */
export function pickAt(
  scene: Projected[],
  mode: SelectionMode,
  x: number,
  y: number
): Picked | null {
  let result: Picked | null = null
  let bestDistance = Infinity,
    bestDepth = Infinity
  const consider = (
    distance: number,
    depth: number,
    s: Surface,
    index: number
  ) => {
    if (
      distance > bestDistance ||
      (distance === bestDistance && depth >= bestDepth)
    )
      return
    const candidate = selection(s, index, mode)
    if (candidate) {
      result = candidate
      bestDepth = depth
      bestDistance = distance
    }
  }
  for (const { surface: s, points } of scene) {
    if (mode === 'node') {
      if (!s.nodeIds) continue
      for (let i = 0; i < points.length; i++) {
        const p = points[i],
          d = Math.hypot(p[0] - x, p[1] - y)
        if (d <= 9) consider(d, p[2], s, i)
      }
      continue
    }
    if (mode === 'element' && !s.elements) continue
    if ((mode === 'edge' || mode === 'face') && mode !== s.kind) continue
    for (let i = 0; i < s.cells.length; i++) {
      const cell = s.cells[i]
      if (s.kind === 'edge') {
        for (let k = 1; k < cell.length; k++) {
          const hit = segmentDistance(
            x,
            y,
            points[cell[k - 1]],
            points[cell[k]]
          )
          if (hit.distance <= 7) consider(hit.distance, hit.depth, s, i)
        }
      } else {
        for (let k = 2; k < cell.length; k++) {
          const depth = triangleDepth(
            x,
            y,
            points[cell[0]],
            points[cell[k - 1]],
            points[cell[k]]
          )
          if (depth !== null) {
            consider(0, depth, s, i)
            break
          }
        }
      }
    }
  }
  return result
}

function matches(s: Surface, index: number, picked: Picked) {
  const candidate = selection(s, index, picked.kind)
  if (
    (picked.kind === 'face' || picked.kind === 'edge') &&
    s.kind !== picked.kind
  )
    return false
  return candidate?.id === picked.id
}

/** Highlight only exterior edges of a patch. Shared display diagonals are hidden. */
export function outline(
  ctx: CanvasRenderingContext2D,
  scene: Projected[],
  picked: Picked,
  hover: boolean
) {
  ctx.save()
  ctx.lineWidth = hover ? 2 : 3
  ctx.strokeStyle = hover ? '#147d9a' : '#d77514'
  ctx.fillStyle = '#fff'
  for (const { surface: s, points } of scene) {
    if (picked.kind === 'node') {
      if (s.instance !== picked.instance) continue
      const index = s.nodeIds?.indexOf(picked.label!) ?? -1
      if (index < 0) continue
      ctx.beginPath()
      ctx.arc(points[index][0], points[index][1], 5, 0, 2 * Math.PI)
      ctx.fill()
      ctx.stroke()
      continue
    }
    const edges = new Map<string, [number, number]>()
    for (let i = 0; i < s.cells.length; i++) {
      if (!matches(s, i, picked)) continue
      const cell = s.cells[i]
      const count = s.kind === 'face' ? cell.length : cell.length - 1
      for (let j = 0; j < count; j++) {
        const a = cell[j],
          b = cell[(j + 1) % cell.length]
        const key = a < b ? a + ',' + b : b + ',' + a
        if (edges.has(key)) edges.delete(key)
        else edges.set(key, [a, b])
      }
    }
    ctx.beginPath()
    for (const [a, b] of edges.values()) {
      ctx.moveTo(points[a][0], points[a][1])
      ctx.lineTo(points[b][0], points[b][1])
    }
    ctx.stroke()
  }
  ctx.restore()
}
