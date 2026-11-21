import type { Project, Job, FixtureInfo } from '../../api'
import type { TranslationKey } from '../../i18n'

/**
 * Workflow completion is derived from the saved engineering configuration, never
 * from "the user visited this step". An unfinished prerequisite blocks the steps
 * that depend on it instead of merely looking inactive.
 */
export type StepState = 'complete' | 'incomplete' | 'blocked'

export interface StepStatus {
  state: StepState
  /** Why the step is not complete, so a disabled action can explain itself. */
  hint?: TranslationKey
}

export interface WorkflowInput {
  project: Project
  /** Newest completed mesh for this model, whatever its inputs. */
  mesh: Job | null
  /** Newest mesh whose inputs still match the saved revision. */
  compatibleMesh: Job | null
  fixture: FixtureInfo | null
  /** Deck prepared for this exact revision from the compatible mesh. */
  deck: Job | null
  runs: Job[]
}

export function workflowStates(input: WorkflowInput): StepStatus[] {
  const { project: p, mesh, compatibleMesh, fixture, deck, runs } = input
  const roles = p.components.map((c) => c.role)
  const allRolesAssigned = roles.every((role) => role === 'seal' || role === 'moving_panel')
  const hasPanel = roles.filter((role) => role === 'moving_panel').length === 1
  const everyRegionAssigned =
    p.faces.filter((f) => !f.cavity).length > 0 &&
    p.faces.filter((f) => !f.cavity).every((f) => !!f.material)
  const fixtureReviewed = !!fixture && fixture.count > 0
  const motionValid = p.motion.travel < 0 && p.motion.duration > 0
  const solved = runs.some((r) => r.status === 'Completed')

  const meshReady = !!compatibleMesh
  const meshComplete = meshReady && fixtureReviewed
  const deckComplete = meshComplete && !!deck

  const states: StepStatus[] = [
    { state: 'complete' },
    { state: allRolesAssigned && hasPanel ? 'complete' : 'incomplete', hint: 'hint.roles' },
    { state: everyRegionAssigned ? 'complete' : 'incomplete', hint: 'hint.materials' },
    {
      state: fixtureReviewed ? 'complete' : 'incomplete',
      hint: 'hint.fixedNodesRequired',
    },
    { state: motionValid ? 'complete' : 'incomplete', hint: 'hint.motion' },
    {
      state: meshComplete ? 'complete' : 'incomplete',
      hint: !mesh
        ? 'hint.meshRequired'
        : !meshReady
          ? 'hint.meshStale'
          : !fixtureReviewed
            ? 'hint.fixtureRequired'
            : undefined,
    },
    {
      state: deckComplete ? 'complete' : 'incomplete',
      hint: !meshComplete
        ? 'hint.deckBlockedByMesh'
        : !motionValid
          ? 'hint.motion'
          : 'hint.deckRequired',
    },
    { state: solved ? 'complete' : 'incomplete', hint: 'hint.results' },
  ]
  // A step cannot be completed before the configuration it depends on exists.
  if (!allRolesAssigned || !hasPanel) {
    for (let i = 2; i < states.length; i++) if (states[i].state !== 'complete') states[i].state = 'blocked'
  } else if (!everyRegionAssigned) {
    for (const i of [5, 6, 7]) if (states[i].state !== 'complete') states[i].state = 'blocked'
  } else if (!meshComplete) {
    for (const i of [6, 7]) if (states[i].state !== 'complete') states[i].state = 'blocked'
  } else if (!deckComplete && states[7].state !== 'complete') {
    states[7].state = 'blocked'
  }
  return states
}
