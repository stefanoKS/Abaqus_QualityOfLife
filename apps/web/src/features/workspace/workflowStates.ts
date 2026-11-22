import type { Project, Job, FixtureInfo } from '../../api'
import type { TranslationKey } from '../../i18n'
import { STAGE_ORDER, type StageId } from './stages'

/**
 * Workflow completion is derived from the saved engineering configuration, never
 * from "the user visited this step". An unfinished prerequisite blocks the steps
 * that depend on it instead of merely looking inactive. Mesh, Mounting and
 * Contact each have their own prerequisites and completion condition.
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
  /** True while the open revision has unsaved edits. */
  dirty?: boolean
}

export function workflowStates(input: WorkflowInput): Record<StageId, StepStatus> {
  const { project: p, mesh, compatibleMesh, fixture, deck, runs, dirty = false } = input
  const roles = p.components.map((c) => c.role)
  const allRolesAssigned = roles.every(
    (role) => role === 'seal' || role === 'moving_panel' || role === 'vehicle_body',
  )
  const hasPanel = roles.filter((role) => role === 'moving_panel').length === 1
  const everyRegionAssigned =
    p.faces.filter((f) => !f.cavity).length > 0 &&
    p.faces.filter((f) => !f.cavity).every((f) => !!f.material)
  const fixtureReviewed = !!fixture && fixture.count > 0
  const twoStep = p.analysis.mode === 'body_then_door'
  const motionValid =
    p.motion.travel < 0 &&
    p.motion.duration > 0 &&
    (!twoStep ||
      ((p.motion.body?.travel ?? 0) !== 0 && (p.motion.body?.duration ?? 0) > 0))
  const contactValid =
    Number.isFinite(p.contact.friction) && p.contact.friction >= 0 && p.contact.friction <= 5
  const solved = runs.some((r) => r.status === 'Completed')

  const geometryReady = allRolesAssigned && hasPanel
  const meshReady = !!compatibleMesh
  const deckReady = meshReady && fixtureReviewed && motionValid && contactValid && !!deck

  const states: Record<StageId, StepStatus> = {
    import: { state: 'complete' },
    components: {
      state: geometryReady ? 'complete' : 'incomplete',
      hint: 'hint.roles',
    },
    materials: {
      state: everyRegionAssigned ? 'complete' : 'incomplete',
      hint: 'hint.materials',
    },
    mesh: {
      state: meshReady ? 'complete' : 'incomplete',
      hint: meshReady ? undefined : geometryReady ? 'hint.meshRequired' : 'hint.roles',
    },
    mounting: {
      state: fixtureReviewed ? 'complete' : 'incomplete',
      hint: !meshReady ? 'hint.meshRequired' : fixtureReviewed ? undefined : 'hint.fixtureRequired',
    },
    // Contact readiness is deliberately independent of the fixed-node selection.
    contact: {
      state: contactValid && !dirty ? 'complete' : 'incomplete',
      hint: !contactValid ? 'hint.contactInvalid' : dirty ? 'hint.contactSave' : undefined,
    },
    motion: { state: motionValid ? 'complete' : 'incomplete', hint: 'hint.motion' },
    review: {
      state: deckReady ? 'complete' : 'incomplete',
      hint: !meshReady
        ? 'hint.deckBlockedByMesh'
        : !fixtureReviewed
          ? 'hint.fixtureRequired'
          : !motionValid
            ? 'hint.motion'
            : !deckReady
              ? 'hint.deckRequired'
              : undefined,
    },
    results: { state: solved ? 'complete' : 'incomplete', hint: 'hint.results' },
  }

  // A step cannot be completed before the configuration it depends on exists.
  const requires: Partial<Record<StageId, StageId[]>> = {
    materials: ['components'],
    mesh: ['materials'],
    mounting: ['mesh'],
    contact: ['materials'],
    motion: ['materials'],
    review: ['mesh', 'mounting', 'motion'],
    results: ['review'],
  }
  for (const id of STAGE_ORDER) {
    const unmet = (requires[id] ?? []).some(
      (prerequisite) => states[prerequisite].state !== 'complete',
    )
    if (unmet && states[id].state !== 'complete') states[id].state = 'blocked'
  }
  return states
}

/** Ordered array in `STAGE_ORDER`, for the navigation component. */
export function orderedStates(input: WorkflowInput): StepStatus[] {
  const states = workflowStates(input)
  return STAGE_ORDER.map((id) => states[id])
}
