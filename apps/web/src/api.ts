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
export type LibraryCard = components['schemas']['MaterialCard-Output']
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

/**
 * Point the URL at the current working head without telling the router to
 * rebuild the page. An automatic save advances the model inside the same form:
 * remounting there would drop focus, an in-progress draft, the viewport camera,
 * the selection and the active stage.
 */
export function replaceRouteSilent(route: string) {
  try {
    history.replaceState(null, '', '#' + route)
  } catch {
    // A denied history write only leaves the URL on the previous revision id;
    // the open form and the saved head are unaffected.
  }
}

export interface RecentFile {
  path: string
  kind: 'model' | 'result'
}

const RECENT_FILES = 'abaqus-qol.recent-files'

/** Read the recent-file list; a private-mode browser simply has none. */
export function recentFiles(): RecentFile[] {
  try {
    const raw = localStorage.getItem(RECENT_FILES)
    const parsed = raw ? (JSON.parse(raw) as RecentFile[]) : []
    return Array.isArray(parsed) ? parsed.slice(0, 5) : []
  } catch {
    return []
  }
}

/**
 * Record a deliberate save or open. Closing a document never removes a recent
 * entry: the file is exactly how it is reopened afterwards.
 */
export function rememberRecentFile(entry: RecentFile): RecentFile[] {
  const merged = [entry, ...recentFiles().filter((row) => row.path !== entry.path)].slice(0, 5)
  try {
    localStorage.setItem(RECENT_FILES, JSON.stringify(merged))
  } catch {
    // The list is a convenience, not state the model depends on.
  }
  return merged
}

const LAST_MODEL = 'abaqus-qol.lastModel'
// Per-tab document session. ``ACTIVE`` names the document this tab is working
// on; ``CLOSED`` records the document this tab deliberately closed so neither
// the Workspace entry point nor a refresh silently reopens it. Both live in
// sessionStorage, so another tab keeps its own document.
const ACTIVE_DOCUMENT = 'abaqus-qol.activeDocument'
const CLOSED_DOCUMENT = 'abaqus-qol.closedDocument'

export interface ActiveDocument {
  project: string
  /** Current working head this tab is showing. */
  revision: string
  name: string
  /** Empty for an untitled document. */
  path: string
  /** Fingerprint of the file this session last wrote, else empty. */
  sha: string
  /** Revision that was packaged into ``path``; empty before the first save. */
  fileRevision: string
  /** A valid edit is not committed yet, so the head will still move. */
  dirty: boolean
}

function readActive(): ActiveDocument | null {
  try {
    const raw = sessionStorage.getItem(ACTIVE_DOCUMENT)
    return raw ? (JSON.parse(raw) as ActiveDocument) : null
  } catch {
    return null
  }
}

/** The document this tab is working on, if any. */
export function activeDocument(): ActiveDocument | null {
  const active = readActive()
  if (!active) return null
  try {
    if (sessionStorage.getItem(CLOSED_DOCUMENT) === active.project) return null
  } catch {
    // A storage denial only loses the closed marker, never the document.
  }
  return active
}

/** Remember or refresh the current tab's document without changing the route. */
export function rememberActiveDocument(document: ActiveDocument) {
  try {
    sessionStorage.setItem(ACTIVE_DOCUMENT, JSON.stringify(document))
    sessionStorage.removeItem(CLOSED_DOCUMENT)
  } catch {
    // The workspace still works; only the tab-scoped convenience is lost.
  }
}

/**
 * End this tab's document session. Recents and the working head are untouched,
 * and another tab's file or an already queued analysis is unaffected.
 */
export function closeActiveDocument(project: string) {
  try {
    sessionStorage.setItem(CLOSED_DOCUMENT, project)
    sessionStorage.removeItem(ACTIVE_DOCUMENT)
  } catch {
    // Nothing else changes: lastModel still opens the model explicitly.
  }
  try {
    if (localStorage.getItem(LAST_MODEL) === project) localStorage.removeItem(LAST_MODEL)
  } catch {
    // A denied write cannot resurrect a closed document in this tab.
  }
}

/** Remember the model the user explicitly opened, never a substituted one. */
export function rememberModel(project: string) {
  try {
    localStorage.setItem(LAST_MODEL, project)
    sessionStorage.removeItem(CLOSED_DOCUMENT)
  } catch {
    // Private-mode storage denial only loses the convenience, not the model.
  }
}

export function lastModel(): string | null {
  try {
    const stored = localStorage.getItem(LAST_MODEL)
    if (!stored) return null
    // A document this tab closed is not reopened by the Workspace entry point.
    if (sessionStorage.getItem(CLOSED_DOCUMENT) === stored) return null
    return stored
  } catch {
    return null
  }
}

/**
 * What the Workspace entry point should open in this tab: the tab's own active
 * document first, then the last explicitly opened model.
 */
export function workspaceTarget(): string | null {
  return activeDocument()?.revision ?? lastModel()
}

export function err(e: unknown) {
  return e instanceof Error ? e.message : String(e)
}
