/**
 * Gate C browser journey: the real Materials page registers the supplied CAE
 * library, a registered foam is assigned to a closed seal region, and Prepare
 * emits its faithful law. Skips when the local private library is absent.
 */
import { existsSync } from 'node:fs'
import { expect, test, type Page } from './fixtures'
import type { LibrarySummary, Revision } from '../src/api'

const LIBRARY = 'I:\\GithubProjects\\AbaqusLibrary\\HK_matlib.lib'

const FOAM_NAMES = [
  'E13',
  'SSS',
  'NISHIDA_FX-TPO70N',
  'NISHIDA_FX-TPO70B',
  'E27H',
  'E17',
  'EPTO_E110',
  'E-35-8_CALIBRATED',
  'SSS_CALIBRATED',
  'DKSPONGETASHA',
  'DKSPONGEHK',
]

test.skip(!existsSync(LIBRARY), 'the local CAE library fixture is absent')

async function create(request: Page['request'], name: string): Promise<Revision> {
  return (
    await request.post('/api/projects', { data: { name, example: true } })
  ).json()
}

function row(page: Page, name: string) {
  return page.locator('.material-list .material-row').filter({ hasText: name }).first()
}

test('the Materials page registers all 27 CAE records and prepares a coupled foam', async ({
  page,
  request,
}) => {
  test.setTimeout(180000)
  const revision = await create(request, 'CAE foam journey')
  await page.goto('/#materials')
  const chooser = page.waitForEvent('filechooser')
  await page.getByTestId('cae-preview').click()
  await (await chooser).setFiles(LIBRARY)

  const panel = page.getByTestId('cae-preview-panel')
  await expect(panel).toBeVisible({ timeout: 60000 })
  // 27 decoded records, all registrable, 19 ready for a new run.
  await expect(panel.locator('.cae-card')).toHaveCount(27)
  await expect(panel.getByTestId('cae-card-available')).toHaveCount(19)
  await expect(panel.locator('.cae-card.blocked')).toHaveCount(0)
  // All 11 Hyperfoam records are present and selectable.
  for (const name of FOAM_NAMES) {
    await expect(panel.locator('.cae-card').filter({ hasText: name }).first()).toBeVisible()
  }
  // The seven source records without a density say exactly what they need.
  await expect(
    panel.locator('.cae-card').filter({ hasText: 'TP1303' }).first(),
  ).toContainText('Needs a density')
  // A mixed import declares a family per card; METAL defaults to metal.
  const metalCard = panel
    .locator('.cae-card')
    .filter({ has: page.getByText('METAL', { exact: true }) })
  await expect(metalCard.getByRole('combobox')).toHaveValue('metal')

  await page.getByTestId('cae-import').click()
  await expect(page.locator('.toast')).toContainText('registered', { timeout: 60000 })
  const library = (await (await request.get('/api/materials')).json()) as LibrarySummary[]
  for (const name of FOAM_NAMES) {
    expect(library.some((entry) => entry.name === name)).toBe(true)
  }

  // Assign the coupled 5-term foam to a closed seal region.
  const foam = library.find((entry) => entry.name === 'DKSPONGEHK')!
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Components' }).click()
  await page.locator('.region-list button', { hasText: 'Mounting foot' }).first().click()
  await page.getByTestId('assign-material').click()
  await page.getByLabel('Assign from the material library').selectOption(foam.id)
  await expect(page.locator('.property-body')).toContainText('DKSPONGEHK')

  // The registered law is shown read-only in the Materials stage.
  await workflow.getByRole('button', { name: 'Materials' }).click()
  await expect(page.getByTestId('cae-law-view')).toBeVisible()
  await expect(page.getByTestId('cae-law-view')).toContainText('hyperfoam · N=5 · INSTANTANEOUS')
  await expect(page.getByTestId('cae-law-view')).toContainText('viscoelastic · PRONY')

  // Real Prepare flow on the closed seal region.
  await workflow.getByRole('button', { name: 'Mesh' }).click()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 60000 })
  await workflow.getByRole('button', { name: 'Mounting' }).click()
  await page.getByRole('button', { name: /Resolve .* mounting edges to nodes/ }).click()
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await workflow.locator('[data-stage="results"]').click()
  await page.getByRole('button', { name: 'Prepare input deck' }).click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', {
    timeout: 60000,
  })
  const href = await page
    .getByRole('link', { name: 'Inspect input deck' })
    .getAttribute('href')
  const deck = await (await request.get(href!)).text()
  expect(deck).toContain('*Hyperfoam, n=5, moduli=INSTANTANEOUS')
  expect(deck).toContain('*Viscoelastic, time=PRONY')
})
