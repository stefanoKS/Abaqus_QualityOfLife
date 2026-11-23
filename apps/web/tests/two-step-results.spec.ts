import { existsSync, readFileSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { expect, test } from './fixtures'

/**
 * Gate G/F: replay a licensed two-step result (re-extracted from its ODB).
 * Opt-in: needs the isolated 8892 instance and its .local seed. It verifies the
 * door step opens by default, the body step is selectable, and the exported
 * curve carries the canonical step identity.
 */
const BASE = 'http://127.0.0.1:8892'
const seedPath = resolve('../../.local/milestone/two-step-seed.json')
const seed = existsSync(seedPath)
  ? (JSON.parse(readFileSync(seedPath, 'utf8')) as { run: string })
  : null

test('a licensed two-step result opens on the door step and switches to the body step', async ({
  page,
}) => {
  test.skip(!seed, 'two-step replay seed is absent (.local is not in Git)')
  const health = await page.request.get(`${BASE}/api/health`).catch(() => null)
  test.skip(!health?.ok(), 'isolated two-step replay is not running on 8892')
  const run = seed!.run

  await page.goto(`${BASE}/#results/${run}`)
  await expect(page.getByRole('heading', { name: 'Licensed two-step held body' })).toBeVisible()
  await expect(page.getByLabel('Field')).toHaveValue('mises')
  await expect(page.getByLabel('Probe mode')).toHaveValue('element')

  // Two canonical steps, opening on Closing.
  const step = page.getByLabel('Curve step')
  await expect(step).toHaveValue('closing')
  const options = await step.locator('option').allTextContents()
  expect(options.join('|')).toContain('Body seating')
  expect(options.join('|')).toContain('Closing')
  await expect(page.getByTestId('vtk-viewport')).toHaveAttribute('data-frame-time', '1')

  // Switch to the body-seating step: the curve/CSV identity follows the
  // selector while the displayed frame and field/probe policy are retained.
  await step.selectOption('bodyseating')
  await expect(page.getByLabel('Field')).toHaveValue('mises')
  await expect(page.getByLabel('Probe mode')).toHaveValue('element')

  const exported = async () => {
    const pending = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Export displayed curve (2 rows)' }).click()
    const download = await pending
    return {
      text: await readFile((await download.path())!, 'utf8'),
      name: download.suggestedFilename(),
    }
  }
  const body = await exported()
  expect(body.name).toContain('body-curve-')
  expect(body.name).toContain('bodyseating')
  expect(body.text.split(/\r?\n/).filter(Boolean)).toHaveLength(2)

  // Return to the door step; the closing curve reaches the commanded travel.
  await step.selectOption('closing')
  await expect(page.getByTestId('vtk-viewport')).toHaveAttribute('data-frame-time', '1')
  await page.getByRole('slider').fill('116')
  await expect
    .poll(async () =>
      Number(await page.getByTestId('vtk-viewport').getAttribute('data-frame-time')),
    )
    .toBeCloseTo(2.3)
  const door = await exported()
  expect(door.name).toContain('door-curve-')
  expect(door.name).toContain('closing')
  const rows = door.text.split(/\r?\n/).filter(Boolean)
  expect(rows).toHaveLength(2)
  // Row 1 is the step-relative measured displacement magnitude.
  expect(Number(rows[0].split(',').at(-1))).toBeCloseTo(5.5, 2)
})
