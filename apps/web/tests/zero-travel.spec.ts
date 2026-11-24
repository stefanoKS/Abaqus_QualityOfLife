import { expect, test, type Page } from './fixtures'
import { meshAndDeck } from './pipeline'
import type { Display, Revision } from '../src/api'

/**
 * Gate C: zero travel is a true hold, and a draft validation error never
 * blanks the last valid geometry. The model is the named two-panel template so
 * the body and the door are both real rigid instances.
 */
async function twoPanel(request: import('@playwright/test').APIRequestContext) {
  const revision: Revision = await (
    await request.post('/api/projects', {
      data: { name: 'Zero travel', example: true, template: 'two-panel' },
    })
  ).json()
  return revision
}

async function actors(page: Page) {
  return Number(await page.getByTestId('vtk-viewport').getAttribute('data-scene-actors'))
}

async function at(page: Page, bounds: number[], x: number, y: number) {
  const viewport = page.getByRole('application', { name: '2D engineering viewport' })
  const box = (await viewport.boundingBox())!
  const [xmin, xmax, ymin, ymax] = bounds
  const scale = Math.min(box.width / (xmax - xmin), box.height / (ymax - ymin)) / 1.2
  return {
    x: box.x + box.width / 2 + (x - (xmin + xmax) / 2) * scale,
    y: box.y + box.height / 2 - (y - (ymin + ymax) / 2) * scale,
  }
}

test('zero travel holds, drafts keep geometry, and the deck has true zeros', async ({
  page,
  request,
}) => {
  let revision = await twoPanel(request)
  const display: Display = await (
    await request.post('/api/display', { data: revision.setup })
  ).json()

  await page.goto('/#workspace/' + revision.id)
  await expect(page.getByRole('application', { name: '2D engineering viewport' })).toBeVisible()
  await expect.poll(() => actors(page)).toBeGreaterThan(0)

  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Motion' }).click()
  const body = page.getByLabel('Body panel stroke (mm)')
  await body.fill('0')
  await body.press('Tab')
  await expect(page.getByTestId('motion-zero-hold')).toBeVisible()
  await expect(page.getByText('No visible geometry')).toHaveCount(0)

  // A temporarily blank field is a local error and the drawing stays visible.
  const travel = page.getByLabel('Door panel stroke (mm)')
  await travel.fill('')
  await travel.press('Tab')
  await expect(page.getByText('This numeric field is required.')).toBeVisible()
  await expect.poll(() => actors(page)).toBeGreaterThan(0)
  await expect(page.getByText('No visible geometry')).toHaveCount(0)
  await travel.focus()
  await travel.press('Escape')
  await expect(travel).toHaveValue('10')

  // Save the zero-body hold, navigate away, reopen.
  await body.fill('0')
  await body.press('Tab')
  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  const savedId = page.url().split('/').pop()!
  await page.getByRole('button', { name: 'Dashboard' }).click()
  await page.goto('/#workspace/' + savedId)
  await expect.poll(() => actors(page)).toBeGreaterThan(0)
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await expect(page.getByLabel('Body panel stroke (mm)')).toHaveValue('0')

  // Language switching keeps the geometry and the hold explanation.
  await page.locator('.lang-button').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'ja')
  await expect(page.getByTestId('motion-zero-hold')).toBeVisible()
  await expect.poll(() => actors(page)).toBeGreaterThan(0)
  await page.locator('.lang-button').click()

  // Geometry is still selectable after the zero-travel save.
  await workflow.getByRole('button', { name: 'Materials' }).click()
  const crown = await at(page, display.bounds, 0, 11.75)
  await page.mouse.click(crown.x, crown.y)
  await expect(
    page.locator('.property-body').getByRole('heading', { name: 'Hollow bulb' }),
  ).toBeVisible()

  // Hold-only: both steps preserve their assembled positions.
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await page.getByLabel('Door panel stroke (mm)').fill('0')
  await page.getByLabel('Door panel stroke (mm)').press('Tab')
  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 03')
  revision = await (
    await request.get('/api/revisions/' + page.url().split('/').pop())
  ).json()
  expect(revision.setup.motion.body.travel).toBe(0)
  expect(revision.setup.motion.travel).toBe(0)

  const prepared = await meshAndDeck(request, revision)
  // The mesh was prepared out of band, so reload the workspace to refresh
  // readiness before reviewing the measured assembly.
  await page.goto('/#workspace/' + revision.id)
  await page.reload()
  await expect(page.getByText('Two hold steps (assembled positions preserved)')).toBeVisible()
  await expect(page.getByTestId('assembly-door')).toContainText('Hold (assembled position)')
  await expect(page.getByTestId('assembly-body')).toContainText('Hold (assembled position)')

  const inp = await (
    await request.get('/api/jobs/' + prepared.deck.id + '/artifacts/analysis.inp')
  ).text()
  const steps = inp.split('*Step, name=')
  expect(steps.length).toBe(3)
  for (const step of steps.slice(1)) {
    expect(step).toContain('BODY_RP, 2, 2, 0')
    expect(step).toContain('PANEL_RP, 2, 2, 0')
    expect(step).not.toMatch(/2, 2, 1e-/)
  }
})


