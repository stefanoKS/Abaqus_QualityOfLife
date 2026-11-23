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
        mode: 'ABAQUS',
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
    await request.post('/api/projects', { data: { name: 'Door panel response', example: true } })
  ).json()
  const run = await completedRun(request, revision, 'Door panel response run')

  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  await expect(page.getByText('Door panel response', { exact: true })).toBeVisible()
  // The closing direction is stated instead of being implied by an axis name.
  await expect(page.locator('.property-body')).toContainText('0.000, -1.000')

  const plain = await exportCsv(page)
  expect(plain).toContain('# provenance,ABAQUS solver')
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
  await expect(page.getByText('Door panel response', { exact: true })).toBeVisible()
})

test('reverse axes refit an automatic axis and mirror a zoomed one', async ({ page, request }) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Axis range', example: true } })
  ).json()
  const run = await completedRun(request, revision, 'Axis range run')
  await page.goto('/#results/' + run.id)
  await expect(page.locator('.run-banner')).toBeVisible({ timeout: 20000 })
  await expect(page.getByRole('heading', { name: /Force.displacement/ })).toBeVisible({
    timeout: 20000,
  })

  type Axis = { range: number[]; autorange: boolean | string }
  async function axis(which: 'xaxis' | 'yaxis'): Promise<Axis> {
    return page.evaluate((name) => {
      const el = document.querySelector('.plot') as unknown as {
        layout: Record<string, { range: number[]; autorange: boolean | string }>
      }
      const found = el.layout[name]
      return { range: found.range, autorange: found.autorange }
    }, which)
  }
  await page.waitForFunction(() => {
    const el = document.querySelector('.plot') as unknown as {
      data?: { x?: number[] }[]
      layout?: { xaxis?: { range?: number[] } }
    }
    return !!el?.data?.[0]?.x?.length && !!el.layout?.xaxis?.range
  })

  // Full view: the positive-travel curve spans positive X before reversing.
  const before = await axis('xaxis')
  expect(before.range[1]).toBeGreaterThan(3)

  await page.getByLabel('Reverse X sign').check()
  // The old defect kept positive limits and clipped the negated curve. The
  // refitted axis must actually span the mirrored travel.
  await expect.poll(async () => (await axis('xaxis')).range[0]).toBeLessThan(-3)
  const flipped = await axis('xaxis')
  expect(flipped.range[1]).toBeLessThan(1)

  // Reversing twice restores the automatically fitted interval.
  await page.getByLabel('Reverse X sign').uncheck()
  await expect.poll(async () => (await axis('xaxis')).range[1]).toBeGreaterThan(3)
  const restored = await axis('xaxis')
  expect(restored.range[0]).toBeCloseTo(before.range[0], 3)
  expect(restored.range[1]).toBeCloseTo(before.range[1], 3)

  // A deliberate zoom is preserved as the same physical portion, mirrored.
  const plot = page.locator('.plot')
  const box = (await plot.boundingBox())!
  await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.3)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width * 0.35, box.y + box.height * 0.75)
  await page.mouse.up()
  await expect.poll(async () => (await axis('xaxis')).autorange).not.toBe(true)
  const zoomed = await axis('xaxis')
  expect(zoomed.range[1] - zoomed.range[0]).toBeLessThan(before.range[1] - before.range[0])

  await page.getByLabel('Reverse X sign').check()
  await expect
    .poll(async () => (await axis('xaxis')).range[1])
    .toBeCloseTo(-zoomed.range[0], 2)
  const mirrored = await axis('xaxis')
  expect(mirrored.range[0]).toBeCloseTo(-zoomed.range[1], 2)

  // Reversing back restores the deliberately zoomed interval.
  await page.getByLabel('Reverse X sign').uncheck()
  await expect
    .poll(async () => (await axis('xaxis')).range[0])
    .toBeCloseTo(zoomed.range[0], 2)
})
