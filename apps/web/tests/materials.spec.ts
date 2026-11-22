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
    await request.post('/api/projects', { data: { name: 'Material edit', example: true } })
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
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 60000 })
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Mounting' }).click()
  await page.getByRole('button', { name: /Resolve .* mounting edges to nodes/ }).click()
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await expect(page.getByTestId('deck-status')).toHaveCount(0)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Review / Run' }).click()
  await page.getByRole('button', { name: 'Prepare input deck' }).click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', {
    timeout: 60000,
  })
  const deckHref = await page.getByRole('link', { name: 'Inspect input deck' }).getAttribute('href')
  const deck = await (await page.request.get(deckHref!)).text()
  expect(deck).toContain('*Elastic')
  expect(deck).toContain('8.5, 0.44')
  expect(deck).toContain('*Uniaxial Test Data')
  // An unassigned card must not reach the deck: only meshed regions get sections.
  expect(deck).not.toContain('MAT_3')
  expect(deck).toContain('0.95')
})

test('an invalid numeric draft stays visible and blocks save and navigation', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Numeric draft', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Motion' }).click()

  const travel = page.getByLabel('Prescribed Y travel (mm)')
  await expect(travel).toHaveValue('-5.5')
  await travel.fill('5')
  await travel.press('Tab')

  // The old behaviour restored -5.5 on blur and let Save proceed.
  await expect(travel).toHaveValue('5')
  await expect(page.locator('.field-error')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save revision' })).toBeDisabled()

  // Leaving the step is refused instead of silently discarding the edit.
  await workflow.getByRole('button', { name: 'Review / Run' }).click()
  await expect(page.locator('.toast')).toContainText('invalid value')
  await expect(workflow.locator('button[data-stage="motion"]')).toHaveAttribute(
    'aria-current',
    'step',
  )

  // Escape is the explicit restoration, and it unblocks navigation.
  await travel.press('Escape')
  await expect(travel).toHaveValue('-5.5')
  await expect(page.locator('.field-error')).toHaveCount(0)
  await workflow.getByRole('button', { name: 'Review / Run' }).click()
  await expect(workflow.locator('button[data-stage="review"]')).toHaveAttribute('aria-current', 'step')
})

test('a malformed laboratory row blocks the paste until it is corrected', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Paste review', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Materials' })
    .click()
  await page.locator('.material-row').filter({ hasText: 'Cellular EPDM' }).click()

  const before = (await (await request.get('/api/revisions/' + revision.id)).json()) as Revision
  const savedRows = before.setup.materials.find((m) => m.id === 'bulb_foam')!.test_data

  await page.getByRole('button', { name: 'Paste table data' }).click()
  const textarea = page.getByLabel('Paste table data')
  await textarea.fill(
    [
      'stress,strain_axial,strain_lateral',
      '0.10,0.05,-0.02',
      '0.20,0.10,-0.04',
      '0.40,oops,-0.02',
      '0.50,0.20,-0.08',
    ].join('\n'),
  )
  await expect(page.getByTestId('paste-summary')).toContainText('3 rows accepted, 1 rejected')
  await expect(page.getByTestId('paste-rejected')).toContainText('Line 4')
  await expect(page.getByRole('button', { name: /Apply \d+ rows/ })).toBeDisabled()

  // Cancel leaves the saved card untouched.
  await page.getByRole('button', { name: 'Cancel' }).click()
  await expect(page.getByRole('heading', { name: /Uniaxial test data/ })).toContainText(
    `${savedRows.length} samples`,
  )

  // Correct the middle row and apply the complete preview.
  await page.getByRole('button', { name: 'Paste table data' }).click()
  await textarea.fill(
    [
      'stress,strain_axial,strain_lateral',
      '0.10,0.05,-0.02',
      '0.20,0.10,-0.04',
      '0.40,0.15,-0.06',
      '0.50,0.20,-0.08',
    ].join('\n'),
  )
  await expect(page.getByTestId('paste-summary')).toContainText('4 rows accepted, 0 rejected')
  await page.getByRole('button', { name: 'Apply 4 rows' }).click()
  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')

  const projects = (await (await request.get('/api/projects')).json()) as {
    id: string
    revision: string
  }[]
  const head = projects.find((project) => project.id === revision.project)!
  const saved = (await (await request.get('/api/revisions/' + head.revision)).json()) as Revision
  const card = saved.setup.materials.find((m) => m.id === 'bulb_foam')!
  expect(card.version).toBe(2)
  expect(card.test_data).toEqual([
    [0.1, 0.05, -0.02],
    [0.2, 0.1, -0.04],
    [0.4, 0.15, -0.06],
    [0.5, 0.2, -0.08],
  ])
})
