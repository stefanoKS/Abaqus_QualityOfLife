import { readFileSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { expect, test } from './fixtures'
import { meshAndDeck } from './pipeline'
import type { Job, Revision } from '../src/api'

async function completedRun(
  request: import('@playwright/test').APIRequestContext,
  revision: Revision,
  name: string,
): Promise<Job> {
  const { deck } = await meshAndDeck(request, revision)
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name,
        scenario: 'success',
        mode: 'DEMO',
      },
    })
  ).json()
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + run.id)).json()) as Job).status, {
      timeout: 60000,
    })
    .toBe('Completed')
  return run
}

async function exportCsv(page: import('@playwright/test').Page) {
  const pending = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export displayed curve' }).click()
  const file = await pending
  const path = await file.path()
  expect(path).toBeTruthy()
  return readFileSync(path!, 'utf8')
}

function rows(csv: string) {
  return csv
    .split(/\r?\n/)
    .filter((line) => line && !line.startsWith('#'))
    .slice(1)
    .map((line) => line.split(','))
}

test('door response is projected, sign-reversible and exported as displayed', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Door response' } })
  ).json()
  const run = await completedRun(request, revision, 'Door response run')

  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  await expect(page.getByText('Door response', { exact: true })).toBeVisible()
  // The closing direction is stated instead of being implied by an axis name.
  await expect(page.locator('.property-body')).toContainText('0.000, -1.000')

  const plain = await exportCsv(page)
  expect(plain).toContain('# provenance,DEMO synthetic')
  expect(plain).toContain('# x_sign,1')
  expect(plain).toContain('# y_sign,1')
  expect(plain).toContain('# closing_step,Closing')
  const first = rows(plain)
  // Travel along the closing direction is positive; the required closing force
  // is positive too (Abaqus reports RF2 < 0 while the seal resists).
  expect(Number(first[0][0])).toBeCloseTo(0, 6)
  expect(Number(first.at(-1)![0])).toBeGreaterThan(0)
  expect(Number(first.at(-1)![1])).toBeGreaterThan(0)
  // Raw signed global components remain available in the same export.
  expect(Number(first.at(-1)![5])).toBeLessThan(0)
  expect(Number(first.at(-1)![7])).toBeLessThan(0)

  await page.getByLabel('Reverse X sign').check()
  await page.getByLabel('Reverse Y sign').check()
  const flipped = await exportCsv(page)
  expect(flipped).toContain('# x_sign,-1')
  expect(flipped).toContain('# y_sign,-1')
  const mirrored = rows(flipped)
  expect(Number(mirrored.at(-1)![0])).toBeCloseTo(-Number(first.at(-1)![0]), 6)
  expect(Number(mirrored.at(-1)![1])).toBeCloseTo(-Number(first.at(-1)![1]), 6)
  // The raw components are untouched by the display transformation.
  expect(mirrored.at(-1)![6]).toBe(first.at(-1)![6])
  expect(mirrored.at(-1)![8]).toBe(first.at(-1)![8])

  // The raw artifact keeps its original signed values regardless of display.
  const raw = await (await request.get('/api/jobs/' + run.id + '/artifacts/history.csv')).text()
  expect(raw.split(/\r?\n/)[0]).toContain('panel_RF2_N')
  expect(raw).not.toContain('# x_sign')

  // A later model edit must not disturb reopening this historical run.
  const edited = structuredClone(revision.setup)
  edited.motion.travel = -4
  const saved = await request.put('/api/projects/' + revision.project, {
    data: { base: revision.id, setup: edited },
  })
  expect(saved.ok()).toBeTruthy()
  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  await expect(page.getByText('Door response', { exact: true })).toBeVisible()
})
