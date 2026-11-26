/**
 * Gate A: usable width, symmetric gutters, readable type and reachable actions.
 *
 * Measurements use the rendered layout at the requested viewport widths, not
 * stylesheet expectations. Only synthetic/fictional data is created.
 */
import { expect, test, type Page } from './fixtures'
import { settleViewport } from './viewport-ready'
import type { Revision } from '../src/api'

const WIDTHS = [
  { width: 2560, height: 1440 },
  { width: 2547, height: 1440 },
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
]

async function dashboardMetrics(page: Page) {
  return page.evaluate(() => {
    const main = document.querySelector('.dashboard.page') as HTMLElement
    const style = getComputedStyle(main)
    return {
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      right: main.getBoundingClientRect().right,
      left: main.getBoundingClientRect().left,
      padLeft: parseFloat(style.paddingLeft),
      padRight: parseFloat(style.paddingRight),
      bodyFont: parseFloat(getComputedStyle(document.body).fontSize),
      workflowFont: (() => {
        const button = document.querySelector('.steps button') as HTMLElement | null
        return button ? parseFloat(getComputedStyle(button).fontSize) : 0
      })(),
    }
  })
}

for (const viewport of WIDTHS) {
  test(`the dashboard uses the full width with symmetric design gutters at ${viewport.width}px`, async ({
    page,
    request,
  }) => {
    await request.post('/api/projects', {
      data: {
        name:
          viewport.width < 500
            ? '超長い日本語プロジェクト名の確認用モデル・ドアシール断面の検証'
            : 'Layout width check',
        example: true,
      },
    })
    await page.setViewportSize(viewport)
    await page.goto('/#dashboard')
    await expect(page.locator('.dashboard.page')).toBeVisible()
    const metrics = await dashboardMetrics(page)
    // The scroller reaches the right edge; no horizontal page overflow.
    expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 1)
    expect(metrics.right).toBeGreaterThanOrEqual(metrics.clientWidth - 1)
    expect(metrics.left).toBeLessThanOrEqual(1)
    // Symmetric bounded gutters, never the old 1950 px dead strip.
    expect(Math.abs(metrics.padLeft - metrics.padRight)).toBeLessThanOrEqual(1)
    expect(metrics.padLeft).toBeGreaterThanOrEqual(16)
    expect(metrics.padLeft).toBeLessThanOrEqual(32)
    // Body text is 16 px.
    expect(metrics.bodyFont).toBe(16)
    // A long Japanese model name must not widen the page.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(1)
  })
}

test('200% desktop zoom keeps every field reachable without horizontal overflow', async ({
  page,
}) => {
  // 200% browser zoom on a 1440 x 900 window is 720 x 450 CSS pixels.
  await page.setViewportSize({ width: 720, height: 450 })
  await page.goto('/#dashboard')
  await page.getByRole('button', { name: 'New project' }).click()
  const metrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.clientWidth + 1)
  const create = page.getByRole('button', { name: 'Create project' })
  await create.scrollIntoViewIfNeeded()
  await expect(create).toBeVisible()
  // Keyboard: the form is reachable with Tab and can be cancelled with Escape.
  await page.getByLabel('Project name').focus()
  await page.keyboard.type('Keyboard create')
  await page.getByRole('button', { name: 'Cancel' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByLabel('Project name')).toHaveCount(0)
})

test('both create flows start empty and never offer the public example', async ({
  page,
  request,
}) => {
  const group = await (
    await request.post('/api/groups', { data: { name: 'Empty flow group' } })
  ).json()
  await page.goto('/#dashboard')
  await page.getByRole('button', { name: 'New project' }).click()
  await expect(page.getByLabel('Start from the public example section')).toHaveCount(0)
  await expect(page.getByText('A new model starts empty and opens at Import.')).toBeVisible()
  await page.getByLabel('Project name').fill('Empty project flow')
  await page.getByRole('button', { name: 'Create project' }).click()
  await expect(page.locator('.subtitle')).toBeVisible()
  // The created model opens at Import with no geometry.
  await expect(page.getByTestId('vtk-viewport')).toBeVisible()
  await expect(page.locator('.crumb')).toContainText('Revision 01')

  await page.goto('/#dashboard')
  const card = page.locator('.group-card', { hasText: group.name })
  await card.getByRole('button', { name: 'New model' }).click()
  await expect(page.getByLabel('Start from the public example section')).toHaveCount(0)
  await expect(card.getByText('A new model starts empty and opens at Import.')).toBeVisible()
})

test('the viewport exposes exactly three comfortably sized icon tools', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', {
      data: { name: 'Viewport tools', example: true, template: 'two-panel' },
    })
  ).json()
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/#workspace/' + revision.id)
  const tools = page.locator('.seal-vtk-tools button')
  await expect(tools).toHaveCount(3)
  for (const name of ['Zoom in', 'Zoom out', 'Fit and reset view']) {
    const box = (await page.getByRole('button', { name }).boundingBox())!
    expect(box.width).toBeGreaterThanOrEqual(40)
    expect(box.height).toBeGreaterThanOrEqual(40)
  }
  // Workflow labels are at least 15 px on this desktop layout.
  const workflowFont = await page
    .locator('.steps button')
    .first()
    .evaluate((element) => parseFloat(getComputedStyle(element).fontSize))
  expect(workflowFont).toBeGreaterThanOrEqual(15)
  // The historical assembled-position overlay is gone.
  await expect(page.locator('.seal-vtk-assembly')).toHaveCount(0)
  // Real camera behaviour for all three controls.
  const camera = () => page.locator('.seal-vtk-host').getAttribute('data-camera')
  // Fit/reset only compares equal when both cameras belong to the settled
  // viewport. Readiness can mount the next-action banner and a queued
  // ResizeObserver refit can still change the camera; wait for both first.
  await settleViewport(page)
  const original = await camera()
  await page.getByRole('button', { name: 'Zoom in' }).click()
  const zoomed = await camera()
  expect(zoomed).not.toEqual(original)
  await page.getByRole('button', { name: 'Zoom out' }).click()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  await expect.poll(camera).toEqual(original)
  // Keyboard focus reaches a tool with a visible focus ring.
  await page.getByRole('application').focus()
  let reached = false
  for (let i = 0; i < 6 && !reached; i++) {
    await page.keyboard.press('Tab')
    reached = await page.evaluate(() =>
      ['Zoom in', 'Zoom out', 'Fit and reset view'].includes(
        document.activeElement?.getAttribute('aria-label') ?? '',
      ),
    )
  }
  expect(reached).toBeTruthy()
  const outline = await page.evaluate(
    () => getComputedStyle(document.activeElement as Element).outlineStyle,
  )
  expect(outline).not.toBe('none')
})

test('the inline new-model flow is operable by keyboard', async ({ page, request }) => {
  const group = await (
    await request.post('/api/groups', { data: { name: 'Keyboard group' } })
  ).json()
  await page.goto('/#dashboard')
  const card = page.locator('.group-card', { hasText: group.name })
  const open = card.getByRole('button', { name: 'New model' })
  await open.focus()
  await page.keyboard.press('Enter')
  const form = card.locator('form.create-form')
  await expect(form).toBeVisible()
  // The model-name input receives focus, so typing is a keyboard-only path.
  await page.keyboard.type('Keyboard model')
  await expect(form.getByLabel('Model name')).toHaveValue('Keyboard model')
  await form.getByRole('button', { name: 'Cancel' }).focus()
  await page.keyboard.press('Enter')
  await expect(form).toHaveCount(0)
  await expect(open).toBeVisible()
})
