/**
 * Polling cadence shared by the dashboard, workspace and run view.
 *
 * Jobs move quickly while queued or running, then stop changing. Polling a
 * finished job every 1.4 s forever is wasted work on a single-user local API, so
 * callers switch to the idle cadence as soon as nothing can still change.
 */
export const ACTIVE_POLL_MS = 1400
export const IDLE_POLL_MS = 10000

/** Terminal states from the job contract; any other state can still change. */
const TERMINAL = new Set(['Completed', 'Failed', 'Cancelled'])

export function anyActive(jobs: { status: string }[]): boolean {
  return jobs.some((job) => !TERMINAL.has(job.status))
}