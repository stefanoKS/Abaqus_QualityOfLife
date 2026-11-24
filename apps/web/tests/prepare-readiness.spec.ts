/**
 * Gate B: one action-specific readiness decision.
 *
 * Reproduces the two reported Prepare failures against the real UI and verifies
 * that Prepare recovers on a semantic revert, that a missing deck blocks only
 * Submit, that a valid positive-delta-Y motion is accepted, and that a failed
 * readiness read is distinct from loading and recoverable.
 */
import { expect, test, type Page } from './fixtures'
import { meshAndFixture } from './pipeline'
import type { Job, Revision } from '../src/api'

/** Prepare and Submit live at the top of the Results properties, once. */
async function openResults(page: Page) {
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .locator('[data-stage="results"]')
    .click()
  await expect(page.getByTestId('action-group')).toBeVisible()
}

async function preparedModel(request: import('@playwright/test').APIRequestContext, name: string) {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name, example: true } })
  ).json()
  const { mesh } = await meshAndFixture(request, revision)
  return { revision, mesh }
}

async function newestDeck(
  request: import('@playwright/test').APIRequestContext,
  revisionId: string,
) {
  const decks: Job[] = await (await request.get('/api/decks')).json()
  return decks.find((job) => job.revision === revisionId) ?? null
}

test('a valid edit replaces the current head automatically and Prepare follows it', async ({
  page,
  request,
}) => {
  const { revision, mesh } = await preparedModel(request, 'Prepare width revert')
  await page.goto('/#workspace/' + revision.id)
  await openResults(page)

  const prepare = page.getByRole('button', { name: 'Prepare input deck' })
  const submit = page.getByRole('button', { name: 'Submit Abaqus analysis' })
  await expect(prepare).toBeEnabled()
  await expect(submit).toBeDisabled()
  await expect(page.getByTestId('submit-reason')).toContainText('No input deck')

  // The ordinary workspace no longer offers a manual Save revision gesture.
  await expect(page.getByRole('button', { name: 'Save revision' })).toHaveCount(0)

  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Motion' })
    .click()
  const width = page.getByLabel('Reporting width W (mm)')
  await expect(width).toHaveValue('100')

  // A committed numeric edit is persisted without a Save click. Prepare pauses
  // only while the write is genuinely in flight and then returns on its own.
  await width.fill('101')
  await width.press('Tab')
  await expect(page.getByTestId('save-state')).toHaveAttribute('data-state', 'saved', {
    timeout: 15000,
  })
  await openResults(page)
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  await expect(prepare).toBeEnabled()
  await expect(page.getByTestId('prepare-reason')).toContainText('Ready to prepare')

  // A second committed edit replaces the head again; the model identity is
  // unchanged and no form state is lost.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Motion' })
    .click()
  await width.fill('100')
  await width.press('Tab')
  await expect(page.getByTestId('save-state')).toHaveAttribute('data-state', 'saved', {
    timeout: 15000,
  })
  await openResults(page)
  await expect(page.locator('.crumb')).toContainText('Revision 03')
  await expect(prepare).toBeEnabled()
  const head: Revision = await (
    await request.get('/api/revisions/' + page.url().split('/').pop())
  ).json()
  expect(head.project).toBe(revision.project)
  expect(head.setup.analysis.reporting_width).toBe(100)

  await prepare.click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', { timeout: 60000 })
  await expect(submit).toBeEnabled()
  // The deck belongs to the head the engine can see, not to an older revision.
  const deck = await newestDeck(request, head.id)
  expect(deck).toBeTruthy()
  expect(deck!.mesh).toBe(mesh.id)
  const currentMesh = (await (await request.get('/api/meshes')).json()) as Job[]
  const active = currentMesh.find((job) => job.id === mesh.id)!
  expect(deck!.fixture_hash).toBe(active.fixture!.hash)

  // A further valid edit advances the head again. The old deck is now stale:
  // Submit is blocked for the new revision while Prepare stays available.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Motion' })
    .click()
  await width.fill('101')
  await width.press('Tab')
  await expect(page.getByTestId('save-state')).toHaveAttribute('data-state', 'saved', {
    timeout: 15000,
  })
  await openResults(page)
  await expect(page.locator('.crumb')).toContainText('Revision 04')
  await expect(prepare).toBeEnabled()
  await expect(submit).toBeDisabled()
  await expect(page.getByTestId('submit-reason')).toContainText('No input deck')
})

test('a positive delta-Y motion from below the seal prepares and writes PANEL_RP, 2, 2, 3', async ({
  page,
  request,
}) => {
  // The public two-panel template has the door above and the body below. Swap
  // the roles so the moving panel is the profile below the seal, then command
  // +90°: the historical predicate rejected this valid motion.
  const created: Revision = await (
    await request.post('/api/projects', {
      data: { name: 'Prepare +Y below', example: true, template: 'two-panel' },
    })
  ).json()
  const setup = structuredClone(created.setup)
  for (const component of setup.components) {
    if (component.id === 'panel') component.role = 'vehicle_body'
    if (component.id === 'body') component.role = 'moving_panel'
  }
  setup.motion.stroke = 3
  setup.motion.angle = 90
  setup.motion.duration = 1
  setup.motion.body.stroke = 0
  setup.motion.body.angle = 0
  setup.motion.body.duration = 1
  const saved: Revision = await (
    await request.put('/api/projects/' + created.project, {
      data: { base: created.id, setup },
    })
  ).json()
  expect(saved.setup.motion.travel).toBe(3)
  await meshAndFixture(request, saved)

  const readiness = await (
    await request.get('/api/revisions/' + saved.id + '/readiness')
  ).json()
  expect(readiness.can_prepare).toBe(true)
  expect(
    readiness.findings.filter(
      (finding: { stage: string; severity: string }) =>
        finding.stage === 'motion' && finding.severity === 'blocker',
    ),
  ).toHaveLength(0)

  await page.goto('/#workspace/' + saved.id)
  await openResults(page)
  const prepare = page.getByRole('button', { name: 'Prepare input deck' })
  await expect(prepare).toBeEnabled()
  await prepare.click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', { timeout: 60000 })

  const deck = await newestDeck(request, saved.id)
  expect(deck).toBeTruthy()
  const inp = await (
    await request.get('/api/jobs/' + deck!.id + '/artifacts/analysis.inp')
  ).text()
  expect(inp).toMatch(/PANEL_RP,\s*2,\s*2,\s*3(?:\.0*)?/)
})

test('a warning-only missed path stays a warning and does not disable Prepare', async ({
  page,
  request,
}) => {
  const created: Revision = await (
    await request.post('/api/projects', { data: { name: 'Prepare warning', example: true } })
  ).json()
  const setup = structuredClone(created.setup)
  // 0.5 mm downward cannot reach the seal foot ~1.8 mm below the door profile.
  setup.motion.stroke = 0.5
  setup.motion.angle = -90
  setup.motion.duration = 1
  const saved: Revision = await (
    await request.put('/api/projects/' + created.project, { data: { base: created.id, setup } })
  ).json()
  await meshAndFixture(request, saved)
  const readiness = await (
    await request.get('/api/revisions/' + saved.id + '/readiness')
  ).json()
  expect(readiness.can_prepare).toBe(true)
  expect(
    readiness.findings.some(
      (finding: { code: string; severity: string }) =>
        finding.code === 'motion.path_misses_seal' && finding.severity === 'warning',
    ),
  ).toBe(true)

  await page.goto('/#workspace/' + saved.id)
  await openResults(page)
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeEnabled()
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Motion' })
    .click()
  await expect(
    page.getByRole('navigation', { name: 'Workflow' }).locator('[data-stage="motion"]'),
  ).toHaveAttribute('data-warning', 'motion.path_misses_seal')
})

test('a failed readiness read is distinct from loading, disables actions and retries', async ({
  page,
  request,
}) => {
  const { revision } = await preparedModel(request, 'Readiness retry')
  let fail = true
  await page.route('**/readiness', (route) => {
    if (fail) return route.abort()
    return route.continue()
  })
  await page.goto('/#workspace/' + revision.id)
  await openResults(page)
  const error = page.getByTestId('readiness-error')
  await expect(error).toBeVisible()
  await expect(error).toContainText('Readiness could not be read')
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeDisabled()
  await expect(page.getByTestId('prepare-reason')).toContainText('Readiness could not be read')

  fail = false
  await error.getByRole('button', { name: 'Retry' }).click()
  await expect(page.getByTestId('readiness-error')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeEnabled()
})

test('the Results action group is the only Prepare/Submit owner after the stage removal', async ({
  page,
  request,
}) => {
  const { revision } = await preparedModel(request, 'Single action owner')
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await expect(workflow.locator('[data-stage="review"]')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Review / Run' })).toHaveCount(0)
  // No duplicate run controls anywhere in the workspace before Results opens.
  await expect(page.getByTestId('prepare')).toHaveCount(0)
  await openResults(page)
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toHaveCount(1)
  await expect(page.getByRole('button', { name: 'Submit Abaqus analysis' })).toHaveCount(1)
  await expect(page.getByTestId('action-group')).toHaveCount(1)
  // It is part of the Results properties, not the left workflow pane.
  await expect(page.locator('.property-body [data-testid="action-group"]')).toHaveCount(1)
  await expect(page.locator('.workflow-pane [data-testid="action-group"]')).toHaveCount(0)
  await expect(page.locator('.left [data-testid="action-group"]')).toHaveCount(0)
})
