import type { TranslationKey } from '../../i18n'

/**
 * One revision-readiness document, calculated by the API and shared by the
 * sidebar, the workspace header, Review and the direct API acceptance tests.
 */
export interface ReadinessFinding {
  code: string
  stage: string
  action: string
  severity: 'blocker' | 'warning' | 'info'
  artifact: string | null
  params: Record<string, string | number>
}

export interface Readiness {
  revision: string
  project: string
  number: number
  head: string
  state: 'empty' | 'blocked' | 'ready' | 'running' | 'failed'
  findings: ReadinessFinding[]
  first_blocker: ReadinessFinding | null
  next_action: { stage: string; action: string } | null
  counts: Record<string, unknown>
  updated: string
  setup_updated: string
}

/** Stable reason code to localized explanation. */
export function findingKey(code: string): TranslationKey {
  return ('readiness.' + code) as TranslationKey
}

export function blockerCount(document: Readiness | null) {
  return document ? document.findings.filter((f) => f.severity === 'blocker').length : 0
}
