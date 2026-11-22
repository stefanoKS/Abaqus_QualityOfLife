import { expect, test } from './fixtures'
import type { Revision } from '../src/api'

/**
 * The workspace header shows the first actual blocker and links to the stage
 * that resolves it. An empty model is never Import-complete and a new empty
 * model never invents geometry.
 */
test('the header names the first blocker and opens its stage', async ({ page, request }) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Readiness empty', example: false } })
  ).json()

  const readiness = await (
    await request.get('/api/revisions/' + revision.id + '/readiness')
  ).json()
  expect(readiness.state).toBe('empty')
  expect(readiness.first_blocker.code).toBe('drawing.missing')

  await page.goto('/#workspace/' + revision.id)
  const next = page.getByTestId('next-action')
  await expect(next).toBeVisible()
  await expect(next).toContainText('No drawing yet')
  await next.getByRole('button', { name: 'Open this step' }).click()
  await expect(
    page.getByRole('navigation', { name: 'Workflow' }).locator('button[data-stage="import"]'),
  ).toHaveAttribute('aria-current', 'step')
  await expect(page.getByTestId('no-drawing')).toBeVisible()
})

test('a drawing-backed revision reports the real next engineering step', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Readiness mesh', example: true } })
  ).json()
  const readiness = await (
    await request.get('/api/revisions/' + revision.id + '/readiness')
  ).json()
  expect(readiness.state).toBe('blocked')
  expect(readiness.first_blocker.code).toBe('mesh.missing')
  expect(readiness.first_blocker.stage).toBe('mesh')

  await page.goto('/#workspace/' + revision.id)
  await expect(page.getByTestId('next-action')).toContainText('no mesh')
})
