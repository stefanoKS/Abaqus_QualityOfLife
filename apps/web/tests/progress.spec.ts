import { expect, test, type Page } from './fixtures'
import type { Job } from '../src/api'

const JOB_ID = '11111111-1111-4111-8111-111111111111'
const REVISION_ID = '22222222-2222-4222-8222-222222222222'

const setup = {
  analysis: { mode: 'body_then_door' },
  motion: {
    duration: 1.3,
    travel: -5.5,
    offset: 0,
    body: { duration: 1.0, travel: -3.0, offset: 0 },
  },
}

function baseJob(overrides: Partial<Job>): Job {
  const now = Date.now() / 1000
  return {
    id: JOB_ID,
    revision: REVISION_ID,
    project: '33333333-3333-4333-8333-333333333333',
    number: 1,
    project_name: 'Progress model',
    name: 'Progress run',
    dimension: '2D',
    mode: 'ABAQUS',
    status: 'Running',
    solver: 'Running',
    extraction: 'Pending',
    scenario: 'success',
    phase: 'Solving',
    created: now - 30,
    started: now - 20,
    ended: null,
    heartbeat: now,
    pid: 4242,
    process_started: now - 20,
    step: null,
    increment: null,
    step_time: null,
    exit_code: null,
    extraction_exit: null,
    cpus: 1,
    build: null,
    mesh: null,
    mesh_digest: null,
    mesh_compat: null,
    fixture_hash: null,
    fixture: null,
    fixture_labels: null,
    diagnostic: '',
    manifest: [],
    input_hash: 'a'.repeat(64),
    ...overrides,
  } as Job
}

async function mount(page: Page, job: Job) {
  await page.unroute('**/api/jobs/' + JOB_ID).catch(() => undefined)
  await page.unroute('**/api/jobs/' + JOB_ID + '/tail/**').catch(() => undefined)
  await page.route('**/api/jobs/' + JOB_ID, (route) => route.fulfill({ json: job }))
  await page.route('**/api/jobs/' + JOB_ID + '/tail/**', (route) =>
    route.fulfill({ json: { text: '' } }),
  )
  await page.route('**/api/revisions/' + REVISION_ID, (route) =>
    route.fulfill({ json: { setup } }),
  )
  await page.goto('/#diagnostics/' + JOB_ID)
  await expect(page.getByTestId('run-progress')).toBeVisible()
}

function step(page: Page, name: string) {
  return page.locator(`[data-testid="progress-steps"] li[data-step="${name}"]`)
}

test('progress follows simulated step time for both steps without an ETA', async ({ page }) => {
  await mount(
    page,
    baseJob({ step: 'Body seating', step_time: 0.5, increment: 12 }),
  )
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '22')
  await expect(step(page, 'Body seating')).toHaveAttribute('data-state', 'active')
  await expect(step(page, 'Closing')).toHaveAttribute('data-state', 'pending')
  await expect(page.getByText('No completion time is estimated.')).toBeVisible()

  await mount(
    page,
    baseJob({ step: 'Closing', step_time: 0.65, increment: 44 }),
  )
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '72')
  await expect(step(page, 'Body seating')).toHaveAttribute('data-state', 'complete')
  await expect(step(page, 'Closing')).toHaveAttribute('data-state', 'active')
})

test('100 percent appears only after solver and extraction both succeed', async ({ page }) => {
  await mount(
    page,
    baseJob({ solver: 'Succeeded', extraction: 'Running', phase: 'Extracting results', step: 'Closing' }),
  )
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '99')
  await expect(page.getByTestId('awaiting-extraction')).toBeVisible()
  await expect(page.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow', '100')

  await mount(
    page,
    baseJob({
      status: 'Completed',
      solver: 'Succeeded',
      extraction: 'Succeeded',
      phase: 'Results ready',
      step: 'Closing',
      step_time: 1.3,
    }),
  )
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100')
  await expect(page.getByTestId('run-progress')).toContainText('Solver and result extraction completed')
  await expect(step(page, 'Body seating')).toHaveAttribute('data-state', 'complete')
  await expect(step(page, 'Closing')).toHaveAttribute('data-state', 'complete')
})

test('license wait, unknown step, queue and stale heartbeat are clearly distinguishable', async ({
  page,
}) => {
  await mount(
    page,
    baseJob({ solver: 'Waiting for license', phase: 'Waiting for license', step: null }),
  )
  await expect(page.getByRole('progressbar')).toHaveAttribute('data-indeterminate', 'true')
  await expect(page.getByTestId('license-wait')).toBeVisible()

  await mount(page, baseJob({ step: 'Unknown step', step_time: 0.2 }))
  await expect(page.getByRole('progressbar')).toHaveAttribute('data-indeterminate', 'true')

  await mount(
    page,
    baseJob({ status: 'Queued', solver: 'Queued', extraction: 'Pending', phase: 'Queued for solver', heartbeat: null }),
  )
  await expect(page.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '0')

  await mount(
    page,
    baseJob({
      step: 'Body seating',
      step_time: 0.5,
      heartbeat: Date.now() / 1000 - 120,
    }),
  )
  await expect(page.getByTestId('stale-heartbeat')).toBeVisible()
})

test('a failed extraction never looks complete', async ({ page }) => {
  await mount(
    page,
    baseJob({
      status: 'Failed',
      solver: 'Succeeded',
      extraction: 'Failed',
      phase: 'Extraction failed',
      step: 'Closing',
      diagnostic: 'ODB extraction failed. See extract.log.',
    }),
  )
  await expect(page.getByTestId('extraction-failed')).toBeVisible()
  await expect(page.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow', '100')
})
