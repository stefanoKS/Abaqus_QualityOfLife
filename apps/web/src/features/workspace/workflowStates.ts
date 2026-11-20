import type { Project, Job } from '../../api'
import type { TranslationKey } from '../../i18n'

/**
 * Workflow completion is derived from the saved engineering configuration, never
 * from "the user visited this step". An unfinished prerequisite blocks the steps
 * that depend on it instead of merely looking inactive.
 */
export type StepState = 'complete' | 'incomplete' | 'blocked'

export interface StepDefinition {
  nameKey: TranslationKey
  /** Short reason shown to the user when the step is incomplete or blocked. */
  state: StepState
}

export function workflowStates(p: Project, build: Job | null, runs: Job[]): StepState[] {
  const roles = p.components.map((c) => c.role)
  const allRolesAssigned = roles.every((role) => role === 'seal' || role === 'moving_panel')
  const hasPanel = roles.filter((role) => role === 'moving_panel').length === 1
  const regionsWithMaterial = p.faces.filter((f) => !f.cavity || f.material).filter((f) => f.material)
  const everyRegionAssigned =
    p.faces.filter((f) => !f.cavity).length > 0 &&
    p.faces.filter((f) => !f.cavity).every((f) => !!f.material)
  const mounting = p.selections.find((s) => s.id === p.mounting.selection)
  const mounted = !!mounting && mounting.entities.length > 0
  const motionValid = p.motion.travel < 0 && p.motion.duration > 0
  const meshed = build?.status === 'Completed'
  const submitted = runs.length > 0
  const solved = runs.some((r) => r.status === 'Completed')

  const states: StepState[] = [
    'complete',
    allRolesAssigned && hasPanel ? 'complete' : 'incomplete',
    regionsWithMaterial.length > 0 && everyRegionAssigned ? 'complete' : 'incomplete',
    mounted ? 'complete' : 'incomplete',
    motionValid ? 'complete' : 'incomplete',
    meshed ? 'complete' : 'incomplete',
    submitted ? 'complete' : 'incomplete',
    solved ? 'complete' : 'incomplete',
  ]
  // A step cannot be completed before the configuration it depends on exists.
  if (!allRolesAssigned) {
    for (let i = 2; i < states.length; i++) if (states[i] !== 'complete') states[i] = 'blocked'
  } else if (!everyRegionAssigned) {
    for (let i = 5; i < states.length; i++) if (states[i] !== 'complete') states[i] = 'blocked'
  } else if (!mounted) {
    for (let i = 5; i < states.length; i++) if (states[i] !== 'complete') states[i] = 'blocked'
  }
  return states
}
