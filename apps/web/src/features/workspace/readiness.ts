import type { Translate, TranslationKey } from '../../i18n'
import type { StageId } from './stages'

/**
 * One revision-readiness document, calculated by the API and shared by the
 * sidebar, the action group and the direct API acceptance tests. Preparation
 * and submission are separate decisions: a missing or stale deck never blocks
 * preparation.
 */
export interface ReadinessFinding {
  code: string
  stage: string
  action: string
  severity: 'blocker' | 'warning' | 'info'
  artifact: string | null
  params: Record<string, string | number>
  /** Actions this finding prevents: ``prepare`` and/or ``submit``. */
  actions?: string[]
}

/** One measured rigid-profile placement on the assembled mesh. */
export interface AssemblyMotion {
  role: 'door' | 'body'
  instance: string
  side: 'above' | 'below'
  direction: number[]
  initial_offset_mm: number
  clearance_mm: number
  travel_mm: number
  duration_s: number
  /** True when travel is exactly 0: the panel holds its assembled position. */
  hold?: boolean
  reaches_initial_gap: boolean
}

/**
 * Geometric assembly measurement from the queued mesh. This is not solver
 * evidence: it says whether the commanded travel can cross the measured gap,
 * never that contact occurs.
 */
export interface AssemblyAssessment {
  door: AssemblyMotion | null
  body: AssemblyMotion | null
  /** Stable clearance code when the deck writer would refuse this assembly. */
  code?: string
  error?: string
  details?: Record<string, string | number>
}

export interface ActionDecision {
  allowed: boolean
  issues: ReadinessFinding[]
}

export interface StageState {
  state: 'complete' | 'incomplete' | 'blocked'
  code?: string
  warning?: string
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
  can_prepare: boolean
  can_submit: boolean
  setup_issues: ReadinessFinding[]
  submit_issues: ReadinessFinding[]
  actions: { prepare: ActionDecision; submit: ActionDecision }
  stage_states: Record<StageId, StageState>
  /** Null before a compatible mesh exists. */
  assembly?: AssemblyAssessment | null
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

/**
 * Translate the structured parameters of a readiness finding.
 *
 * Role and side values are engineering identifiers from the API; they are
 * localized here so an English token never leaks into the Japanese interface.
 */
export function findingVars(
  finding: ReadinessFinding,
  t: Translate,
): Record<string, string | number> {
  const vars: Record<string, string | number> = { ...finding.params }
  if (vars.label === 'door' || vars.label === 'body')
    vars.label = t(('assembly.role.' + vars.label) as TranslationKey)
  if (vars.side === 'above') vars.side = t('assembly.sideAbove')
  else if (vars.side === 'below') vars.side = t('assembly.sideBelow')
  return vars
}
