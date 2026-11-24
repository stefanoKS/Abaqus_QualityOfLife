import { expect, test } from './fixtures'
import { saveRevision } from './save'
import type { Revision } from '../src/api'

async function revisionNumber(page: import('@playwright/test').Page) {
  const match = /Revision\s+(\d+)/.exec(await page.locator('.crumb').innerText())
  return match ? Number(match[1]) : 0
}

test('independent coefficients persist and review actions live in Properties', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Contact persistence', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.locator('[data-stage="contact"]').click()

  // New setups expose the three independent pair coefficients together.
  const door = page.getByLabel('Door panel ↔ seal coefficient')
  const self = page.getByLabel('Seal ↔ seal coefficient')
  await expect(page.getByLabel('Body panel ↔ seal coefficient')).toHaveCount(0)
  const describedBy = await door.getAttribute('aria-describedby')
  expect(describedBy).toBeTruthy()
  await expect(page.locator(`[id="${describedBy}"]`)).toHaveText(
    'Dimensionless Coulomb coefficient, from 0 to 5 (inclusive).',
  )
  const before = await revisionNumber(page)
  for (const value of ['0', '0.17', '1', '2.5', '5']) {
    await door.fill(value)
    await door.press('Tab')
    await expect(door).toHaveValue(value)
  }
  for (const invalid of ['-1', '5.1']) {
    await door.fill(invalid)
    await door.press('Tab')
    await expect(page.getByText('Enter a value within the permitted range.')).toBeVisible()
    await door.press('Escape')
  }
  await door.fill('')
  await door.press('Tab')
  await expect(page.getByText('This numeric field is required.')).toBeVisible()
  await door.press('Escape')
  await door.fill('0.17')
  await door.press('Tab')
  await self.fill('0.81')
  await self.press('Tab')
  // The stage clears itself once the automatic write commits: no Save contact
  // action and no visit to another tab is required.
  await saveRevision(page)
  await expect(workflow.locator('[data-stage="contact"]')).toHaveAttribute(
    'data-state',
    'complete',
  )
  // Every valid committed edit advanced the head automatically; the exact count
  // is a coalescing detail, not a contract.
  expect(await revisionNumber(page)).toBeGreaterThan(before)

  // A motion edit leaves contact untouched and reuses the mesh identity.
  await workflow.locator('[data-stage="motion"]').click()
  const stroke = page.getByLabel('Door panel stroke (mm)')
  await expect(stroke).toHaveValue('10')
  await stroke.fill('')
  await workflow.locator('[data-stage="contact"]').click()
  await expect(stroke).toBeVisible()
  await stroke.press('Escape')
  await stroke.fill('0')
  await stroke.press('Tab')
  await expect(workflow.locator('[data-stage="contact"]')).toHaveAttribute(
    'data-state',
    'complete',
  )
  await workflow.locator('[data-stage="contact"]').click()
  await expect(door).toHaveValue('0.17')
  await expect(self).toHaveValue('0.81')

  // Japanese labels stay aligned with the visible coefficient fields.
  await page.locator('.lang-button').click()
  await expect(page.getByLabel('ドアパネル ↔ シール係数')).toHaveValue('0.17')
  await expect(
    page.getByText('無次元のクーロン係数です。0 以上 5 以下で入力してください。').first(),
  ).toBeVisible()
  await page.locator('.lang-button').click()

  await saveRevision(page)
  await page.reload()
  await expect(workflow.locator('[data-stage="contact"]')).toHaveAttribute(
    'data-state',
    'complete',
  )
  const currentId = page.url().split('/').pop()!
  const saved = (await (await request.get('/api/revisions/' + currentId)).json()) as Revision
  expect(saved.setup.contact.scope).toBe('named_pairs')
  expect(saved.setup.contact.friction).toBeNull()
  expect(saved.setup.contact.door_seal).toBe(0.17)
  expect(saved.setup.contact.seal_self).toBe(0.81)
  expect(saved.setup.motion.stroke).toBe(0)

  // Prepare and Submit live at the top of the Results properties, once.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .locator('[data-stage="results"]')
    .click()
  const actions = page.getByTestId('action-group')
  await expect(actions.getByRole('button', { name: 'Prepare input deck' })).toBeDisabled()
  await expect(actions.getByRole('button', { name: 'Submit Abaqus analysis' })).toBeDisabled()
  const right = (await page.locator('.workgrid > .right').boundingBox())!
  const prepare = (await actions.locator('[data-testid="prepare"]').boundingBox())!
  const submit = (await actions.locator('[data-testid="submit"]').boundingBox())!
  expect(prepare.x).toBeGreaterThanOrEqual(right.x - 1)
  expect(submit.x + submit.width).toBeLessThanOrEqual(right.x + right.width + 1)
  expect(prepare.y).toBeLessThan(submit.y)
  await expect(page.getByRole('button', { name: 'Go to Mesh' })).toHaveCount(0)
  await page.setViewportSize({ width: 700, height: 900 })
  const prepareNarrow = (await actions.locator('[data-testid="prepare"]').boundingBox())!
  const submitNarrow = (await actions.locator('[data-testid="submit"]').boundingBox())!
  expect(prepareNarrow.y).toBeLessThan(submitNarrow.y)
})
