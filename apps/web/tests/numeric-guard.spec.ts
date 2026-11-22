import { expect, test, type Page } from './fixtures'
import type { Revision } from '../src/api'

/**
 * A cleared required numeric field is invalid, not "unchanged". The old code
 * treated blank as valid, restored the committed value on blur and let Save
 * return 200 while the field looked empty.
 */
async function forceClick(page: Page, name: string) {
  const button = page.getByRole('button', { name })
  await button.evaluate((element) => element.removeAttribute('disabled'))
  await button.click()
}

async function head(request: import('@playwright/test').APIRequestContext, project: string) {
  const projects = (await (await request.get('/api/projects')).json()) as {
    id: string
    revision: string
  }[]
  return projects.find((entry) => entry.id === project)!.revision
}

test('blank required numeric fields block save and restore only on Escape', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Blank numeric', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Motion' }).click()

  const writes: string[] = []
  page.on('request', (req) => {
    if (['PUT', 'POST'].includes(req.method())) writes.push(req.method() + ' ' + req.url())
  })

  const travel = page.getByLabel('Prescribed Y travel (mm)')
  await travel.fill('-6.1')
  await travel.press('Tab')
  await expect(travel).toHaveValue('-6.1')

  // Clear it. The blank draft stays visible with required-field feedback.
  await travel.fill('')
  await expect(travel).toHaveValue('')
  await expect(page.getByText('This numeric field is required.')).toBeVisible()
  const save = page.getByRole('button', { name: 'Save revision' })
  await expect(save).toBeDisabled()

  writes.length = 0
  await forceClick(page, 'Save revision')
  await expect.poll(() => writes.length).toBe(0)
  expect(await head(request, revision.project)).toBe(revision.id)

  // Escape is the explicit restoration, never an automatic blur restore.
  await travel.press('Escape')
  await expect(travel).toHaveValue('-6.1')
  await expect(page.getByText('This numeric field is required.')).toHaveCount(0)
  await expect(save).toBeEnabled()

  // A valid new value saves normally.
  await travel.fill('-4.2')
  await travel.press('Tab')
  await save.click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  const saved = (await (await request.get('/api/revisions/' + (await head(request, revision.project)))).json()) as Revision
  expect(saved.setup.motion.travel).toBe(-4.2)

  // Duration and initial offset use the same guard. The milestone default step
  // duration is 1.0 s.
  for (const [label, value] of [
    ['Step duration (s)', '1'],
    ['Initial Y offset (mm)', '0'],
  ] as const) {
    const field = page.getByLabel(label)
    await expect(field).toHaveValue(value)
    await field.fill('')
    await expect(field).toHaveValue('')
    writes.length = 0
    await forceClick(page, 'Save revision')
    await expect.poll(() => writes.length).toBe(0)
    await field.press('Escape')
    await expect(field).toHaveValue(value)
  }
})

test('blank mesh size and thickness block their actions', async ({ page, request }) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Blank size', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Mesh' }).click()

  const writes: string[] = []
  page.on('request', (req) => {
    if (['PUT', 'POST'].includes(req.method())) writes.push(req.method() + ' ' + req.url())
  })

  const size = page.getByLabel('Global size (mm)')
  await size.fill('')
  await expect(size).toHaveValue('')
  const generate = page.getByRole('button', { name: 'Generate mesh', exact: true })
  await expect(generate).toBeDisabled()
  writes.length = 0
  await forceClick(page, 'Generate mesh')
  await expect.poll(() => writes.length).toBe(0)
  await size.press('Escape')
  await expect(size).not.toHaveValue('')

  await workflow.getByRole('button', { name: 'Review / Run' }).click()
  const thickness = page.getByLabel('Section thickness (mm)')
  await thickness.fill('')
  await expect(thickness).toHaveValue('')
  writes.length = 0
  await forceClick(page, 'Save revision')
  await expect.poll(() => writes.length).toBe(0)
  await thickness.press('Escape')
  await expect(thickness).not.toHaveValue('')
})
