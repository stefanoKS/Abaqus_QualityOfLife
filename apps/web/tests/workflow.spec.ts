import { test, expect } from './fixtures'
import { saveRevision } from './save'
import { resolve } from 'node:path'
import type { Revision } from '../src/api'

test('edit, run, reload and reopen an immutable closing setup', async ({ page, request }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(String(e)))
  // Synthetic seed geometry comes from the existing test API, not from a
  // dashboard checkbox: creating a model never seeds the public example.
  const seeded = await request.post('/api/projects', {
    data: { name: 'Closure test', example: true },
  })
  expect(seeded.ok()).toBeTruthy()
  const revision = await seeded.json()
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await page.getByLabel('Door panel stroke (mm)').fill('6.5')
  await page.getByLabel('Door panel stroke (mm)').press('Tab')
  await saveRevision(page)
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  const savedURL = page.url()
  await page.reload()
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await expect(page.getByLabel('Door panel stroke (mm)')).toHaveValue('6.5')
  await workflow.getByRole('button', { name: 'Mesh' }).click()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 60000 })
  // The deck cannot be prepared before a fixed-node selection exists.
  await workflow.locator('[data-stage="results"]').click()
  const prepare = page.getByRole('button', { name: 'Prepare input deck' })
  await expect(prepare).toBeDisabled()
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Mounting' }).click()
  await page.getByRole('button', { name: /Resolve .* mounting edges to nodes/ }).click()
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await workflow.locator('[data-stage="results"]').click()
  await expect(prepare).toBeEnabled()
  await prepare.click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', {
    timeout: 60000,
  })
  const submit = page.getByRole('button', { name: 'Submit Abaqus analysis' })
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
  await expect(page.locator('.run-banner')).toContainText('ABAQUS')
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  await page.getByRole('button', { name: 'Play frames' }).click()
  await expect.poll(() => page.getByRole('slider').inputValue()).not.toBe('0')
  await page.getByRole('button', { name: 'Pause playback' }).click()
  await page.getByRole('slider').fill('30')
  await expect(page.locator('.playback')).toContainText('1.000 s')
  await page.getByLabel('Deformed geometry').uncheck()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  const viewport = (await page.getByRole('application').boundingBox())!
  const metadata = await (
    await page.request.get('/api/jobs/' + runId + '/display-metadata')
  ).json()
  const [xmin, xmax, ymin, ymax] = metadata.bounds.extent as number[]
  const scale = Math.min(viewport.width / (xmax - xmin), viewport.height / (ymax - ymin)) / 1.2
  const cx = (xmin + xmax) / 2,
    cy = (ymin + ymax) / 2
  // Mounting-foot vertex at (-9, 0) in the undeformed synthetic section.
  await page.mouse.click(
    viewport.x + viewport.width / 2 + (-9 - cx) * scale,
    viewport.y + viewport.height / 2 - (0 - cy) * scale,
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
  ).toContain('MANUFACTURED TEST EVIDENCE')
  await page.reload()
  await expect(page.getByRole('slider')).toBeVisible()
  await page.goto(savedURL)
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await page.getByLabel('Door panel stroke (mm)').fill('4')
  await page.getByLabel('Door panel stroke (mm)').press('Tab')
  await saveRevision(page)
  await expect(page.locator('.crumb')).toContainText('Revision 03')
  await page.goto('/#setup/' + runId)
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await expect(page.getByLabel('Door panel stroke (mm)')).toHaveValue('6.5')
  await expect(page.getByLabel('Door panel stroke (mm)')).toBeDisabled()
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
  await saveRevision(page)
  await expect(page.locator('.crumb')).toContainText('Revision 03')
})
