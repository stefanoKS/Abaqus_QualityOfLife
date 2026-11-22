import type { components } from './generated'
import { EXPECTED_API, ownEntry } from './compatibility'

export type Revision = components['schemas']['Revision']
export type Project = Revision['setup']
export type Job = components['schemas']['Job']
export type Summary = components['schemas']['Summary']
export type Group = components['schemas']['GroupSummary']
export type RevisionSummary = components['schemas']['RevisionSummary']
export type FixtureInfo = components['schemas']['FixtureInfo']
export type LibrarySummary = components['schemas']['LibrarySummary']
export type LibraryDetail = components['schemas']['LibraryDetail']
export type LibraryCard = components['schemas']['MaterialCard']
export type MaterialImportResult = components['schemas']['MaterialImportResult']
export type DeletionInfo = components['schemas']['DeletionInfo']

export async function request<T>(
  path: string,
  method = 'GET',
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const form = body instanceof FormData
  // Every request identifies the browser release and API generation it was
  // built against. The API rejects a write from a half-matched pair; an
  // unidentified script keeps the original contract.
  const entry = ownEntry()
  const headers: Record<string, string> = {
    'X-Abaqus-QOL-Api': String(EXPECTED_API),
    // A Vite dev URL is a source module, not a published release entry. The API
    // accepts the literal `dev` for that case and still enforces `api`.
    'X-Abaqus-QOL-Client': /^index-.*\.js$/.test(entry) ? entry : 'dev',
  }
  if (!form && body !== undefined) headers['Content-Type'] = 'application/json'
  const response = await fetch(path, {
    method,
    signal,
    headers,
    body: body === undefined ? undefined : form ? body : JSON.stringify(body),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    throw new Error(
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.loc.slice(1).join('.') + ' ' + d.msg).join(' · ')
          : response.statusText,
    )
  }
  return response.json() as Promise<T>
}

export function artifact(id: string, name: string) {
  return '/api/jobs/' + id + '/artifacts/' + encodeURIComponent(name)
}

/**
 * Elapsed wall time. Unit suffixes stay in engineering notation (s, m) in both
 * languages because they are measurement units, not interface prose.
 */
export function elapsed(job: Job) {
  if (!job.started) return '—'
  const s = Math.max(0, Math.floor((job.ended ?? Date.now() / 1000) - job.started))
  return s < 60 ? s + ' s' : Math.floor(s / 60) + ' m ' + (s % 60) + ' s'
}

export function go(route: string) {
  location.hash = route
}

/**
 * Replace the current history entry without losing the in-page state that the
 * caller already updated, and tell the router to reread the URL. A save or a
 * completed import therefore leaves the URL, the router and the displayed
 * revision describing the same model.
 */
export function replaceRoute(route: string) {
  history.replaceState(null, '', '#' + route)
  window.dispatchEvent(new Event('abaqus-qol:route'))
}

const LAST_MODEL = 'abaqus-qol.lastModel'

/** Remember the model the user explicitly opened, never a substituted one. */
export function rememberModel(project: string) {
  try {
    localStorage.setItem(LAST_MODEL, project)
  } catch {
    // Private-mode storage denial only loses the convenience, not the model.
  }
}

export function lastModel(): string | null {
  try {
    return localStorage.getItem(LAST_MODEL)
  } catch {
    return null
  }
}

export function err(e: unknown) {
  return e instanceof Error ? e.message : String(e)
}
