import type { Readiness } from './readiness'
import type { StageId } from './stages'
import { STAGE_ORDER } from './stages'
import type { TranslationKey } from '../../i18n'

/**
 * Sidebar completion is derived from the API's revision readiness snapshot,
 * never from "the user visited this step". A small browser overlay adds only
 * state the server cannot know: unsaved edits, invalid numeric drafts,
 * pending fixture reviews and in-flight operations. The server remains the
 * authority for setup blockers and for Prepare/Submit eligibility.
 */
export type StepState = 'complete' | 'incomplete' | 'blocked'

export interface StepStatus {
  state: StepState
  /** Localized hint key when the state is not complete. */
  hint?: TranslationKey
  /** Stable readiness code, if the server owns the reason. */
  code?: string
  /** Stable non-blocking warning code from the server. */
  warning?: string
}

export interface WorkflowInput {
  readiness: Readiness | null
  /** True while the readiness read is in flight with no prior document. */
  loading: boolean
  /** Stages whose persisted fields differ from the saved revision. */
  dirtyStages?: Set<StageId>
  /** A reviewed fixed-node set has not been saved yet. */
  fixturePending?: boolean
  /** A numeric draft is invalid and must be corrected before leaving. */
  invalidDraft?: boolean
  /** True when any operation is in flight (mesh, deck, run, save). */
  busy?: boolean
}

export function workflowStates(input: WorkflowInput): Record<StageId, StepStatus> {
  const { readiness, loading, dirtyStages, fixturePending, invalidDraft } = input
  const states = {} as Record<StageId, StepStatus>
  for (const id of STAGE_ORDER) {
    const server = readiness?.stage_states?.[id]
    if (!server) {
      states[id] = {
        state: 'incomplete',
        hint: loading || !readiness ? 'actions.checking' : 'actions.readinessUnavailable',
      }
      continue
    }
    states[id] = {
      state: server.state,
      code: server.code,
      warning: server.warning,
      hint:
        server.state === 'blocked'
          ? 'hint.blocked'
          : server.state === 'incomplete'
            ? 'hint.incomplete'
            : undefined,
    }
  }
  // Unsaved edits are only visible at the stage that owns the changed input.
  if (dirtyStages) {
    for (const id of dirtyStages) {
      if (!states[id]) continue
      if (states[id].state !== 'blocked') {
        states[id] = { state: 'incomplete', hint: 'status.unsaved' }
      }
    }
  }
  if (fixturePending && states.mounting.state !== 'blocked') {
    states.mounting = { state: 'incomplete', hint: 'hint.fixturePending' }
  }
  if (invalidDraft && states.motion.state !== 'blocked') {
    states.motion = { state: 'incomplete', hint: 'validation.invalidDraft' }
  }
  return states
}
