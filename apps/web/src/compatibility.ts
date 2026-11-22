/**
 * Frontend/API compatibility.
 *
 * The running API pins one immutable browser release at startup and reports it
 * in `/api/health`. A tab compares the release it was loaded from with the one
 * the API serves, and the API generation it was built against with the one the
 * API implements. A mismatch disables writes and shows one recovery action; it
 * never lets a half-matched pair mutate projects or queue a solver.
 */

export const EXPECTED_API = 3

export type CompatibilityHealth = {
  product?: string
  api?: number
  frontend?: string
  release?: string
  releaseLegacy?: boolean
  pid?: number
}

export type CompatibilityKind = 'ok' | 'stale-tab' | 'api-mismatch' | 'unreachable'

export interface Compatibility {
  ok: boolean
  kind: CompatibilityKind
  /** The tab's own entry asset name, when it can be determined. */
  entry: string
  /** Release id reported by the API, for display and logs. */
  release: string
  api: number
}

/** Entry asset this document actually loaded, e.g. `index-D8N6_7rq.js`. */
export function ownEntry(): string {
  try {
    const url = new URL(import.meta.url)
    return decodeURIComponent(url.pathname.split('/').pop() || '')
  } catch {
    return ''
  }
}

/** A published entry is content-hashed; a Vite dev URL is a source module. */
function published(entry: string) {
  return /^index-[^/]+\.js$/.test(entry)
}

export function assess(
  health: CompatibilityHealth | null,
  entry: string,
  expectedApi = EXPECTED_API,
): Compatibility {
  const release = String(health?.release ?? '')
  const api = Number(health?.api ?? 0)
  if (!health || !health.product) {
    return { ok: false, kind: 'unreachable', entry, release, api }
  }
  if (api !== expectedApi) {
    return { ok: false, kind: 'api-mismatch', entry, release, api }
  }
  if (published(entry) && health.frontend && entry !== health.frontend) {
    return { ok: false, kind: 'stale-tab', entry, release, api }
  }
  return { ok: true, kind: 'ok', entry, release, api }
}

export function compatibilityMessageKey(kind: CompatibilityKind): string {
  if (kind === 'stale-tab') return 'compat.staleTab'
  if (kind === 'api-mismatch') return 'compat.apiMismatch'
  if (kind === 'unreachable') return 'compat.unreachable'
  return 'compat.ok'
}
