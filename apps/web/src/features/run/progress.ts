import type { Job, Revision } from '../../api'

export interface StepPlan {
  name: string
  role: 'body' | 'door'
  duration: number
}

export interface ProgressView {
  /** False when no reliable fraction exists (unknown step, license wait, ...). */
  determinate: boolean
  /** 0–100 only when determinate. Never 100 before extraction succeeds. */
  percent: number | null
  steps: StepPlan[]
  /** Index of the active step, or null when unknown/not started. */
  active: number | null
  /** Number of fully completed steps. */
  completed: number
  /** True only when solver and extraction both succeeded. */
  complete: boolean
  /** The solver is finished but extraction has not succeeded yet. */
  awaitingExtraction: boolean
}

function setupSteps(setup: Revision['setup'] | null): StepPlan[] {
  if (!setup) return []
  if (setup.analysis?.mode === 'body_then_door') {
    return [
      { name: 'Body seating', role: 'body', duration: setup.motion.body.duration },
      { name: 'Closing', role: 'door', duration: setup.motion.duration },
    ]
  }
  return [{ name: 'Closing', role: 'door', duration: setup.motion.duration }]
}

function normalize(value: string | null | undefined) {
  return (value ?? '').trim().toLowerCase()
}

/**
 * Progress from solver-reported step time and the configured step durations.
 * Simulated time is not a wall-clock completion estimate, and no ETA is derived.
 */
export function progressOf(job: Job, setup: Revision['setup'] | null): ProgressView {
  const steps = setupSteps(setup)
  const complete = job.solver === 'Succeeded' && job.extraction === 'Succeeded'
  const solverDone = job.solver === 'Succeeded'
  const reported = normalize(job.step)
  let active: number | null = null
  if (reported) {
    const found = steps.findIndex((step) => normalize(step.name) === reported)
    if (found >= 0) active = found
  }
  if (solverDone) {
    return {
      // The solver's simulated time is genuinely complete, but overall
      // completion is capped below 100 until extraction succeeds.
      determinate: true,
      percent: complete ? 100 : 99,
      steps,
      active: steps.length - 1,
      completed: steps.length,
      complete,
      awaitingExtraction: !complete,
    }
  }
  const activeStage = ['Queued', 'Preparing', 'Running', 'Waiting for license'].includes(
    job.solver,
  )
  if (!activeStage || !steps.length) {
    return {
      determinate: false,
      percent: null,
      steps,
      active,
      completed: 0,
      complete: false,
      awaitingExtraction: false,
    }
  }
  if (job.solver === 'Queued') {
    return {
      determinate: true,
      percent: 0,
      steps,
      active: null,
      completed: 0,
      complete: false,
      awaitingExtraction: false,
    }
  }
  if (active === null || typeof job.step_time !== 'number') {
    return {
      determinate: false,
      percent: null,
      steps,
      active,
      completed: 0,
      complete: false,
      awaitingExtraction: false,
    }
  }
  const total = steps.reduce((sum, step) => sum + Math.max(0, step.duration), 0)
  if (!(total > 0)) {
    return {
      determinate: false,
      percent: null,
      steps,
      active,
      completed: active,
      complete: false,
      awaitingExtraction: false,
    }
  }
  const before = steps
    .slice(0, active)
    .reduce((sum, step) => sum + Math.max(0, step.duration), 0)
  const current = Math.min(Math.max(0, job.step_time), Math.max(0, steps[active].duration))
  const percent = Math.min(99, Math.max(0, ((before + current) / total) * 100))
  return {
    determinate: true,
    percent,
    steps,
    active,
    completed: active,
    complete: false,
    awaitingExtraction: false,
  }
}

export function isStale(job: Job, nowSeconds: number, threshold = 30) {
  const active =
    ['Queued', 'Preparing', 'Running', 'Waiting for license'].includes(job.solver) ||
    ['Queued', 'Running'].includes(job.extraction)
  if (!active) return false
  const stamp = job.heartbeat ?? job.started ?? job.created
  return !!stamp && nowSeconds - stamp > threshold
}
