import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { expect, test, type Page } from './fixtures'
import type { Revision } from '../src/api'

const MM = resolve('tests/fixtures/units/millimetres.dxf')
const UNITLESS = resolve('tests/fixtures/units/unitless.dxf')
const INCHES = resolve('tests/fixtures/units/inches.dxf')

async function openImport(page: Page, id: string) {
  await page.goto('/#workspace/' + id)
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Import' })
    .click()
}

test('Import is immediate, records the unit basis and survives failures', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Unit policy' } })
  ).json()
  await openImport(page, revision.id)

  // The checkbox and its confirmation gate are gone; the policy is explained.
  await expect(page.getByTestId('import-unit-policy')).toBeVisible()
  await expect(page.getByLabel('Drawing coordinates are in mm')).toHaveCount(0)
  const button = page
    .locator('.property-body')
    .getByRole('button', { name: 'Import DXF / DWG' })
  await expect(button).toBeEnabled()

  // The first click opens the file picker. Cancelling changes nothing.
  const chooserPromise = page.waitForEvent('filechooser')
  await button.click()
  const chooser = await chooserPromise
  await chooser.setFiles([])
  await page.waitForTimeout(400)
  const revisions = await (
    await request.get('/api/projects/' + revision.project + '/revisions')
  ).json()
  expect(revisions.length).toBe(1)
  await expect(page.getByTestId('no-drawing')).toBeVisible()

  // A unitless drawing imports as project millimetres and says so.
  const unitlessChooser = page.waitForEvent('filechooser')
  await button.click()
  await (await unitlessChooser).setFiles(UNITLESS)
  await expect(page.locator('.subtitle')).toContainText('unitless.dxf', { timeout: 60000 })
  const imported: Revision = await (
    await page.request.get('/api/revisions/' + page.url().split('/').pop())
  ).json()
  expect(imported.setup.source.unit_basis).toBe('unitless_as_mm')
  await openImport(page, imported.id)
  await expect(page.getByTestId('import-unit-basis')).toContainText(
    'Unitless drawing interpreted as mm.',
  )
  await expect(page.getByTestId('import-unit-basis')).not.toContainText('confirmed')

  // An inches drawing is rejected by name and never replaces the saved drawing.
  await page.locator('input[type=file]').setInputFiles(INCHES)
  await expect(page.locator('.toast')).toContainText('inches', { timeout: 60000 })
  await expect(page.locator('.subtitle')).toContainText('unitless.dxf')

  // A corrupt file fails as a job with a readable error; the drawing survives.
  const scratch = mkdtempSync(join(tmpdir(), 'units-browser-'))
  const broken = join(scratch, 'broken.dxf')
  writeFileSync(broken, 'not a dxf')
  await page.locator('input[type=file]').setInputFiles(broken)
  await expect(page.locator('.toast')).toContainText('DXF', { timeout: 60000 })
  await expect(page.locator('.subtitle')).toContainText('unitless.dxf')

  // The imported revision is bound to this model only.
  const other: Revision = await (
    await request.post('/api/projects', { data: { name: 'Other model' } })
  ).json()
  await openImport(page, other.id)
  await expect(page.getByTestId('no-drawing')).toBeVisible()
  await openImport(page, imported.id)
  await expect(page.locator('.subtitle')).toContainText('unitless.dxf')
})

test('a declared-millimetre drawing imports directly', async ({ page, request }) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'MM import' } })
  ).json()
  await openImport(page, revision.id)
  await page.locator('input[type=file]').setInputFiles(MM)
  await expect(page.locator('.subtitle')).toContainText('millimetres.dxf', { timeout: 60000 })
  const imported: Revision = await (
    await page.request.get('/api/revisions/' + page.url().split('/').pop())
  ).json()
  expect(imported.setup.source.unit_basis).toBe('declared_mm')
  await openImport(page, imported.id)
  await expect(page.getByTestId('import-unit-basis')).toContainText(
    'Drawing declares millimetres; imported directly.',
  )
})
