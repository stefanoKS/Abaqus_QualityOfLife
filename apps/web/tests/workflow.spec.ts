import { test, expect } from './fixtures'
import { resolve } from 'node:path'
import type { Revision } from '../src/api'

test('edit, run, reload and reopen an immutable closing setup', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(String(e)))
  await page.goto('/#dashboard')
  await page.getByRole('button', { name: 'New project' }).click()
  await page.getByLabel('Project name').fill('Closure test')
  await page.getByRole('button', { name: 'Create project' }).click()
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await page.getByLabel('Prescribed Y travel (mm)').fill('-6.5')
  await page.getByLabel('Prescribed Y travel (mm)').press('Tab')
  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  const savedURL = page.url()
  await page.reload()
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await expect(page.getByLabel('Prescribed Y travel (mm)')).toHaveValue('-6.5')
  await workflow.getByRole('button', { name: 'Mesh' }).click()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 60000 })
  // The deck cannot be prepared before a fixed-node selection exists.
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Review / Run' }).click()
  const prepare = page.getByRole('button', { name: 'Prepare input deck' })
  await expect(prepare).toBeDisabled()
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Mounting' }).click()
  await page.getByRole('button', { name: /Resolve .* mounting edges to nodes/ }).click()
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Review / Run' }).click()
  await expect(prepare).toBeEnabled()
  await prepare.click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', {
    timeout: 60000,
  })
  await workflow.getByRole('button', { name: 'Review / Run' }).click()
  const submit = page.getByRole('button', { name: 'Submit demo run' })
  await expect(submit).toBeEnabled({ timeout: 20000 })
  // Inspect the executable deck for this exact revision.
  const link = await page.getByRole('link', { name: 'Inspect input deck' }).getAttribute('href')
  expect(await (await page.request.get(link!)).text()).toContain('PANEL_RP, 2, 2, -6.5')
  await submit.click()
  await page.waitForURL('**/#diagnostics/*')
  const runId = page.url().split('/').pop()!
  await page.reload()
  await page.getByRole('button', { name: 'Results', exact: true }).click({ timeout: 30000 })
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  await expect(page.locator('.run-banner')).toContainText(
    'DEMO — synthetic results, not an Abaqus analysis.',
  )
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  await page.getByRole('button', { name: 'Play frames' }).click()
  await expect.poll(() => page.getByRole('slider').inputValue()).not.toBe('0')
  await page.getByRole('button', { name: 'Pause playback' }).click()
  await page.getByRole('slider').fill('30')
  await expect(page.locator('.playback')).toContainText('1.300 s')
  await page.getByLabel('Deformed geometry').uncheck()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  const viewport = (await page.getByRole('application').boundingBox())!
  const scale = Math.min(viewport.width / 24, viewport.height / 14) / 1.2
  // Mounting-foot vertex at (-9, 0) in the undeformed synthetic section.
  await page.mouse.click(
    viewport.x + viewport.width / 2 - 9 * scale,
    viewport.y + viewport.height / 2 + 7 * scale,
  )
  await expect(page.locator('.legend')).toContainText('WS-1 · node')
  await expect(page.locator('.legend')).toContainText('|U| 0.000 mm')
  const sample = (await page
    .locator('.scatterlayer .trace')
    .first()
    .locator('path.point')
    .nth(16)
    .boundingBox())!
  await page.mouse.click(sample.x + sample.width / 2, sample.y + sample.height / 2)
  await expect(page.getByRole('slider')).toHaveValue('16')
  expect(
    await (await page.request.get('/api/jobs/' + runId + '/artifacts/history.csv')).text(),
  ).toContain('DEMO — synthetic results')
  await page.reload()
  await expect(page.getByRole('slider')).toBeVisible()
  await page.goto(savedURL)
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await page.getByLabel('Prescribed Y travel (mm)').fill('-4')
  await page.getByLabel('Prescribed Y travel (mm)').press('Tab')
  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 03')
  await page.goto('/#setup/' + runId)
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await expect(page.getByLabel('Prescribed Y travel (mm)')).toHaveValue('-6.5')
  await expect(page.getByLabel('Prescribed Y travel (mm)')).toBeDisabled()
  await page.getByRole('button', { name: 'Duplicate setup' }).click()
  await expect(page.getByRole('heading', { name: 'Closure test · copy' })).toBeVisible()
  expect(errors).toEqual([])
})

test('clean DXF upload appears in the workspace and clears assignments', async ({ page }) => {
  const r: Revision = await (
    await page.request.post('/api/projects', { data: { name: 'Import check' } })
  ).json()
  await page.goto('/#workspace/' + r.id)
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Import' })
    .click()
  await expect(page.getByText('Native DWG reader ready')).toBeVisible()
  await page.getByLabel('Drawing coordinates are in mm').check()
  await page.locator('input[type=file]').setInputFiles(resolve('../../examples/hollow-section.dxf'))
  await expect(page.locator('.subtitle')).toContainText('hollow-section.dxf')
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  await expect(page.getByRole('application').locator('canvas')).toBeVisible()
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Materials' })
    .click()
  await expect(page.getByLabel('Material card')).toHaveValue('')
  await page.getByLabel('Material card').selectOption('base_rubber')
  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 03')
})
