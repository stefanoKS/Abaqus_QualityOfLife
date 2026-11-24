/**
 * Gate 5: one vertical workflow and exactly one place to prepare and run.
 *
 * The stage order is read from the DOM, visual Y and keyboard order; Prepare and
 * Submit exist only at the top of the Results properties, including before a
 * mesh, deck or run exists. Reason codes are compared with the API.
 */
import { expect, test, type Page } from './fixtures'
import { meshAndDeck } from './pipeline'
import type { Revision } from '../src/api'

const STAGES = [
  'import',
  'components',
  'materials',
  'mesh',
  'mounting',
  'contact',
  'motion',
  'results',
]

async function rows(page: Page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll('[data-stage]')).map((element) => ({
      stage: element.getAttribute('data-stage'),
      y: element.getBoundingClientRect().top,
      order: Number(element.getAttribute('tabindex') ?? 0),
    })),
  )
}

async function openResults(page: Page) {
  await page
    .getByRole('navigation', { name: /Workflow|ワークフロー/ })
    .locator('[data-stage="results"]')
    .click()
  await expect(page.getByTestId('action-group')).toBeVisible()
}

test('the eight stage rows keep DOM, visual and keyboard order once per language', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Vertical workflow', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  await expect(page.locator('[data-stage]')).toHaveCount(8, { timeout: 20000 })
  for (const language of ['ja', 'en'] as const) {
    if ((await page.locator('html').getAttribute('lang')) !== language) {
      await page.locator('.lang-button').click()
    }
    await expect(page.locator('html')).toHaveAttribute('lang', language)
    const layout = await rows(page)
    expect(layout.map((row) => row.stage)).toEqual(STAGES)
    // A single column: every row is at least a row-height lower than the last.
    for (let index = 1; index < layout.length; index += 1) {
      expect(layout[index].y).toBeGreaterThan(layout[index - 1].y + 8)
    }
    // The workflow is the first focusable block; tabbing walks the rows in order.
    await page.locator('[data-stage="import"]').focus()
    for (const stage of STAGES.slice(1)) {
      await page.keyboard.press('Tab')
      await expect(page.locator('[data-stage="' + stage + '"]')).toBeFocused()
    }
  }
})

test('Results opens before any artifact and owns the only Prepare/Submit controls', async ({
  page,
  request,
}) => {
  const created: Revision = await (
    await request.post('/api/projects', { data: { name: 'Results first' } })
  ).json()
  await page.goto('/#workspace/' + created.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  // No run controls exist before Results opens.
  await expect(page.getByTestId('action-group')).toHaveCount(0)
  await openResults(page)
  await expect(page.getByTestId('action-group')).toHaveCount(1)
  const document = await (
    await request.get('/api/revisions/' + created.id + '/readiness')
  ).json()
  expect(document.can_prepare).toBe(false)
  expect(document.can_submit).toBe(false)
  // The first displayed blocker is the API's first blocker, at its owning stage.
  await expect(page.getByTestId('prepare')).toBeDisabled()
  await expect(page.getByTestId('prepare-reason')).not.toHaveText('')
  const next = document.next_action
  await expect(workflow.locator(`[data-stage="${next.stage}"]`)).toBeVisible()
  // One action group only, and it is in the Results properties.
  await expect(page.locator('.left [data-testid="action-group"]')).toHaveCount(0)
  await expect(page.locator('.right [data-testid="action-group"]')).toHaveCount(1)
  // Reload (a reopened file) keeps the same single owner and stage order.
  await page.reload()
  await openResults(page)
  await expect(page.locator('[data-stage]')).toHaveCount(8)
  await expect(page.locator('.left [data-testid="action-group"]')).toHaveCount(0)
})

test('short and zoomed layouts keep every stage and the action group reachable', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Short workflow', example: true } })
  ).json()
  for (const size of [
    { width: 1280, height: 520 },
    { width: 1120, height: 560 },
  ]) {
    await page.setViewportSize(size)
    await page.goto('/#workspace/' + revision.id)
    await expect(page.locator('[data-stage]')).toHaveCount(8, { timeout: 20000 })
    const layout = await rows(page)
    expect(layout.map((row) => row.stage)).toEqual(STAGES)
    for (let index = 1; index < layout.length; index += 1) {
      expect(layout[index].y).toBeGreaterThan(layout[index - 1].y + 8)
    }
    await page.getByTestId('vtk-viewport').waitFor()
    await openResults(page)
    await page.getByTestId('action-group').scrollIntoViewIfNeeded()
    await expect(page.getByTestId('prepare')).toBeVisible()
    await expect(page.getByTestId('submit')).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(1)
  }
})

test('Submit-only run parameters name their reason and never block Prepare', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Run parameters', example: true } })
  ).json()
  await meshAndDeck(request, revision)
  await page.goto('/#workspace/' + revision.id)
  await openResults(page)
  await expect(page.getByTestId('submit')).toBeEnabled()
  await page.getByTestId('action-group').getByLabel(/CPUs|CPU/).fill('0')
  await expect(page.getByTestId('submit')).toBeDisabled()
  await expect(page.getByTestId('submit-reason')).toContainText(/CPU/)
  await expect(page.getByTestId('prepare')).toBeEnabled()
  await page.getByTestId('action-group').getByLabel(/CPUs|CPU/).fill('2')
  await page.getByTestId('action-group').getByLabel(/Run name|解析名/).fill('')
  await expect(page.getByTestId('submit')).toBeDisabled()
  await expect(page.getByTestId('submit-reason')).toContainText(/run name|解析名/)
  await page.getByTestId('action-group').getByLabel(/Run name|解析名/).fill('Vertical run')
  await expect(page.getByTestId('submit')).toBeEnabled()
  // A visible multi-row assembly tree remains usable on this short-ish desktop.
  await expect(page.locator('.left .tree [role="button"], .left .tree button')).not.toHaveCount(0)
})
