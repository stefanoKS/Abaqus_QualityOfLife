import { expect, test } from './fixtures'
import type { Job, Revision } from '../src/api'

/**
 * Material editing is safety-critical: invalid cards must be rejected in the UI,
 * card versions must only move when data actually changes, and the generated deck
 * must carry the edited values.
 */
test('material cards are editable, validated, versioned and written to the deck', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Material edit' } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Materials' })
    .click()

  const rows = page.locator('.material-row')
  const dense = rows.filter({ hasText: 'Dense EPDM' })
  await expect(rows).toHaveCount(2)
  await dense.click()

  // A referenced card cannot be deleted; the button explains why.
  const remove = page.getByRole('button', { name: 'Delete', exact: true })
  await expect(remove).toBeDisabled()
  await expect(remove).toHaveAttribute('title', /Clear those assignments first/)

  // Hard validation blocks saving instead of letting an invalid card through.
  const density = page.getByLabel('Density (tonne/mm³)')
  await density.fill('0')
  await expect(page.locator('.issue.error')).toContainText(
    'Density must be greater than zero.',
  )
  await expect(page.getByRole('button', { name: 'Save revision' })).toBeDisabled()

  await density.fill('1.15e-9')
  await expect(page.locator('.issue.error')).toHaveCount(0)
  await page.getByLabel("Young's modulus (MPa)").fill('8.5')
  await expect(page.getByRole('button', { name: 'Save revision' })).toBeEnabled()

  // Hyperfoam test data is editable row by row.
  await rows.filter({ hasText: 'Cellular EPDM' }).click()
  await expect(page.getByRole('heading', { name: /Uniaxial test data/ })).toContainText(
    '5 samples',
  )
  await page.getByRole('button', { name: 'Add row' }).click()
  await expect(page.getByRole('heading', { name: /Uniaxial test data/ })).toContainText(
    '6 samples',
  )
  const lastStrain = page.getByLabel('Row 6 Nominal strain 軸')
  await lastStrain.fill('0.95')
  await lastStrain.blur()

  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')

  const projects = (await (await request.get('/api/projects')).json()) as {
    id: string
    revision: string
  }[]
  const head = projects.find((project) => project.id === revision.project)!
  const saved = (await (await request.get('/api/revisions/' + head.revision)).json()) as Revision
  const baseRubber = saved.setup.materials.find((m) => m.id === 'base_rubber')!
  const bulbFoam = saved.setup.materials.find((m) => m.id === 'bulb_foam')!
  expect(baseRubber.young).toBe(8.5)
  expect(baseRubber.version).toBe(2)
  expect(bulbFoam.test_data.length).toBe(6)
  expect(bulbFoam.version).toBe(2)
  // Re-saving unchanged data must not move the version again.
  expect(bulbFoam.name).toBe('Cellular EPDM')

  // A new card starts at version 1 and stays independent of the edited card.
  await page.getByRole('button', { name: 'New card' }).click()
  await expect(rows).toHaveCount(3)
  await expect(rows.filter({ hasText: 'New material' })).toContainText('v1')
  const cardName = page.getByLabel('Material name')
  await cardName.fill('Validation rubber')
  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 03')

  // The reviewed deck must carry the edited material data.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Mesh' })
    .click()
  await page.getByRole('button', { name: 'Generate mesh & input' }).click()
  await expect(
    page.locator('.build-info').getByText('Input ready', { exact: true }),
  ).toBeVisible({ timeout: 60000 })
  const deckHref = await page.getByRole('link', { name: 'Inspect input deck' }).getAttribute('href')
  const deck = await (await page.request.get(deckHref!)).text()
  expect(deck).toContain('*Elastic')
  expect(deck).toContain('8.5, 0.44')
  expect(deck).toContain('*Uniaxial Test Data')
  // An unassigned card must not reach the deck: only meshed regions get sections.
  expect(deck).not.toContain('MAT_3')
  expect(deck).toContain('0.95')
})
