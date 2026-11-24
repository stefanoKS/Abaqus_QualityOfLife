/**
 * Three-way reconciliation for a concurrent edit.
 *
 * A second window (or a second engineer's window) that started from the same
 * revision must never resubmit its whole stale snapshot: doing so reverts every
 * field the other window committed. The controller therefore keeps the base it
 * loaded, computes the local delta against that base, and rebases that delta
 * onto the newest head.
 *
 * Safety rules:
 *  - a field changed only locally takes the local value;
 *  - a field changed only on the newer head keeps the head value;
 *  - a field changed to different values in both is a conflict, reported by
 *    path, and nothing is written;
 *  - geometry/topology is interdependent: when the newer head changed the
 *    drawing or its assignments, a local draft that changes anything is a
 *    conflict, because CAD ids, region selections and the mesh identity would
 *    otherwise be mixed from two different drawings;
 *  - arrays of objects with unique string `id`s merge per element when the
 *    membership is unchanged; every other array is atomic.
 *
 * The function is pure so the same rule is reused by the file save controller.
 */

export type ReconcileResult =
  | { ok: true; setup: Record<string, unknown>; changed: boolean }
  | { ok: false; conflicts: string[] }

type Json = unknown

function same(left: Json, right: Json): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

function isObject(value: Json): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** Unique string ids of an object array, or null when it is not id-keyed. */
function idSet(value: Json): string[] | null {
  if (!Array.isArray(value) || value.length === 0) return null
  const ids: string[] = []
  for (const item of value) {
    if (!isObject(item) || typeof item.id !== 'string') return null
    ids.push(item.id)
  }
  return new Set(ids).size === ids.length ? ids : null
}

const CONFLICT = Symbol('conflict')

function mergeValue(base: Json, head: Json, draft: Json, path: string, out: string[]): Json {
  if (same(head, draft)) return head
  // Local side untouched: adopt the newer head.
  if (same(base, draft)) return head
  // Head side untouched: keep the local value.
  if (same(base, head)) return draft

  if (isObject(base) && isObject(head) && isObject(draft)) {
    const keys = new Set([...Object.keys(base), ...Object.keys(head), ...Object.keys(draft)])
    const merged: Record<string, unknown> = {}
    for (const key of keys) {
      const prefix = path ? path + '.' + key : key
      const value = mergeValue(base[key], head[key], draft[key], prefix, out)
      if (value === CONFLICT) {
        out.push(prefix)
        // Keep the head value in the merged view so a partially merged preview
        // can still be shown; the write is blocked while a conflict exists.
        merged[key] = head[key]
      } else {
        merged[key] = value
      }
    }
    return merged
  }

  const baseIds = idSet(base)
  const headIds = idSet(head)
  const draftIds = idSet(draft)
  if (baseIds && headIds && draftIds) {
    const union = new Set([...baseIds, ...headIds, ...draftIds])
    const sameMembership = union.size === baseIds.length && union.size === headIds.length
    if (sameMembership) {
      const byId = (list: Json) =>
        new Map((list as Record<string, unknown>[]).map((item) => [String(item.id), item]))
      const baseMap = byId(base)
      const headMap = byId(head)
      const draftMap = byId(draft)
      const order = headIds
      const merged: Record<string, unknown>[] = []
      for (const id of order) {
        const value = mergeValue(
          baseMap.get(id),
          headMap.get(id),
          draftMap.get(id),
          path + '[' + id + ']',
          out,
        )
        if (value === CONFLICT) {
          out.push(path + '[' + id + ']')
          merged.push(headMap.get(id) as Record<string, unknown>)
        } else {
          merged.push(value as Record<string, unknown>)
        }
      }
      return merged
    }
  }

  out.push(path || 'setup')
  return CONFLICT
}

/**
 * The geometry/topology projection the API compares before accepting a write.
 * A draft whose drawing differs from the current head cannot be merged.
 */
export function topologyKey(setup: Record<string, unknown>): string {
  const faces = (setup.faces as Record<string, unknown>[] | undefined) ?? []
  const components = (setup.components as Record<string, unknown>[] | undefined) ?? []
  return JSON.stringify([
    setup.vertices,
    setup.edges,
    setup.source,
    setup.plane,
    faces.map((face) => [face.id, face.component, face.loops, face.cavity ?? false]),
    components.map((component) => component.id),
  ])
}

export function reconcile(
  base: Record<string, unknown>,
  head: Record<string, unknown>,
  draft: Record<string, unknown>,
): ReconcileResult {
  // Editing while the drawing changed elsewhere would mix selections from two
  // drawings. The server rejects a changed topology anyway; report it clearly.
  if (topologyKey(base) !== topologyKey(head) && !same(base, draft)) {
    return { ok: false, conflicts: ['geometry'] }
  }
  const conflicts: string[] = []
  const setup = mergeValue(base, head, draft, '', conflicts) as Record<string, unknown>
  if (conflicts.length) return { ok: false, conflicts }
  return { ok: true, setup, changed: !same(setup, head) }
}
