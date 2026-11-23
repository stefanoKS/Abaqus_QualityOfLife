import type { Project, Job, FixtureInfo } from '../../api'
import type { TranslationKey } from '../../i18n'
import { STAGE_ORDER, type StageId } from './stages'
import { stepPlan } from './stepSequence'

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
  /** True when contact differs from the saved revision. */
  contactChanged?: boolean
}

export function workflowStates(input: WorkflowInput): Record<StageId, StepStatus> {
  const { project: p, mesh, compatibleMesh, fixture, deck, runs, contactChanged = false } = input
  const roles = p.components.map((c) => c.role)
  const allRolesAssigned = roles.every(
    (role) => role === 'seal' || role === 'moving_panel' || role === 'vehicle_body',
  )
  const hasPanel = roles.filter((role) => role === 'moving_panel').length === 1
  const everyRegionAssigned =
    p.faces.filter((f) => !f.cavity).length > 0 &&
    p.faces.filter((f) => !f.cavity).every((f) => !!f.material)
  const fixtureReviewed = !!fixture && fixture.count > 0
  // The role-derived plan is authoritative for a draft too; the server stores
  // the same derived mode on save.
  const twoStep = stepPlan(p).mode === 'body_then_door'
  // Zero travel is a valid hold: the panel keeps its assembled position for
  // the full positive step duration. Only the duration and a numeric travel
  // are required here; the deck writer checks a nonzero travel's direction
  // against the measured contact side.
  const motion = p.schema_version >= 4
    ? Number.isFinite(p.motion.stroke) &&
      p.motion.stroke >= 0 &&
      Number.isFinite(p.motion.angle) &&
      Math.abs(p.motion.angle) <= 360 &&
      (!twoStep ||
        (Number.isFinite(p.motion.body?.stroke ?? 0) &&
          (p.motion.body?.stroke ?? 0) >= 0 &&
          Number.isFinite(p.motion.body?.angle ?? 0) &&
          Math.abs(p.motion.body?.angle ?? 0) <= 360))
    : Number.isFinite(p.motion.travel) && Number.isFinite(p.motion.body?.travel ?? 0)
  const motionValid =
    motion &&
    p.motion.duration > 0 &&
    (!twoStep || (p.motion.body?.duration ?? 0) > 0)
  const inRange = (value: number) => Number.isFinite(value) && value >= 0 && value <= 5
  const contactValid =
    p.contact.friction !== null
      ? inRange(p.contact.friction)
      : inRange(p.contact.door_seal) &&
        inRange(p.contact.body_seal) &&
        inRange(p.contact.seal_self)
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
      state: contactValid && !contactChanged ? 'complete' : 'incomplete',
      hint: !contactValid ? 'hint.contactInvalid' : contactChanged ? 'hint.contactSave' : undefined,
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
