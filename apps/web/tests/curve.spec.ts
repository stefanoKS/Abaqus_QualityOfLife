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
  await page.getByRole('button', { name: 'Export displayed curve (2 rows)' }).click()
  const file = await pending
  const path = await file.path()
  expect(path).toBeTruthy()
  return { csv: readFileSync(path!, 'utf8'), name: file.suggestedFilename() }
}

function rows(csv: string) {
  return csv
    .split(/\r?\n/)
    .filter((line) => line.length > 0)
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

  const { csv: plain, name: plainName } = await exportCsv(page)
  expect(plainName).toMatch(/^door-curve-.+-closing-total-W100mm\.csv$/)
  // Exactly two numeric rows and one column per aligned sample: no preamble,
  // header, index or time column.
  expect(plain.startsWith('#')).toBe(false)
  expect(plain).not.toContain('time_s')
  const first = rows(plain)
  expect(first).toHaveLength(2)
  expect(first[0].length).toBe(first[1].length)
  expect(first[0].length).toBeGreaterThan(2)
  // Row 1: step-relative displacement magnitude (starts at zero, grows).
  expect(Number(first[0][0])).toBeCloseTo(0, 6)
  expect(Number(first[0].at(-1))).toBeGreaterThan(0)
  // Row 2: signed projected force in the selected total basis (100 mm width).
  expect(Number(first[1][0])).toBeCloseTo(0, 6)
  expect(Number(first[1].at(-1))).toBeGreaterThan(0)
  expect(
    first.flat().every((value) => value === '' || Number.isFinite(Number(value))),
  ).toBeTruthy()
  // The basis is stated next to the button, and in the filename.
  await expect(page.getByTestId('export-basis')).toContainText('W = 100 mm')

  await page.getByLabel('Reverse Y sign').check()
  const { csv: flipped, name: flippedName } = await exportCsv(page)
  expect(flippedName).toContain('-force-flipped')
  const mirrored = rows(flipped)
  expect(mirrored).toHaveLength(2)
  // Magnitudes stay nonnegative; the displayed force matches the flipped sign.
  expect(Number(mirrored[0].at(-1))).toBeCloseTo(Number(first[0].at(-1)), 6)
  expect(Number(mirrored[1].at(-1))).toBeCloseTo(-Number(first[1].at(-1)), 6)
  await expect(page.getByTestId('export-basis')).toContainText('displayed force flipped')

  // The raw artifact keeps its original signed values regardless of display.
  const raw = await (await request.get('/api/jobs/' + run.id + '/artifacts/history.csv')).text()
  expect(raw.split(/\r?\n/)[0]).toContain('panel_RF2_N')
  expect(raw).not.toContain('# x_sign')

  // A later model edit must not disturb reopening this historical run.
  const edited = structuredClone(revision.setup)
  edited.motion.stroke = 4
  edited.motion.angle = -90
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
  await plot.scrollIntoViewIfNeeded()
  let box = null
  for (let attempt = 0; attempt < 20 && !box; attempt++) {
    const first = await plot.boundingBox()
    await page.waitForTimeout(120)
    const second = await plot.boundingBox()
    if (first && second && JSON.stringify(first) === JSON.stringify(second)) box = second
  }
  expect(box).not.toBeNull()
  await page.mouse.move(box!.x + box!.width * 0.7, box!.y + box!.height * 0.3)
  await page.mouse.down()
  await page.mouse.move(box!.x + box!.width * 0.35, box!.y + box!.height * 0.75, { steps: 10 })
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
