/**
 * Gate C: the actual plot trace, the selected-step readout and the exported
 * second CSV row follow the selected step's own projection direction.
 *
 * A manufactured test run supplies the transport; the results index is cloned
 * only in the browser route so both steps carry distinct directions and force
 * samples. This is frontend evidence, not solver evidence.
 */
import { randomUUID } from 'node:crypto'
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from './fixtures'
import { meshAndDeck } from './pipeline'
import type { Job, Revision } from '../src/api'

test('the trace, direction readout and export switch with the selected step', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Force axis', example: true } })
  ).json()
  const { deck } = await meshAndDeck(request, revision)
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name: 'Force axis run',
        mode: 'ABAQUS',
      },
    })
  ).json()
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + run.id)).json()) as Job).status, {
      timeout: 90000,
    })
    .toBe('Completed')

  const index = await (
    await request.get('/api/jobs/' + run.id + '/artifacts/results.json')
  ).json()
  const modified = structuredClone(index)
  modified.steps = [
    {
      name: 'Body seating',
      id: 'bodyseating',
      role: 'body',
      instance: 'BODY-1',
      reference_label: 9001,
      direction: [0, 1],
      angle_deg: 90,
      distance_mm: 3,
    },
    {
      name: 'Closing',
      id: 'closing',
      role: 'door',
      instance: 'PANEL-1',
      reference_label: 2,
      direction: [0, -1],
      angle_deg: -90,
      distance_mm: 5,
    },
  ]
  modified.closing = {
    ...(modified.closing ?? {}),
    instance: 'PANEL-1',
    reference_label: 2,
    direction: [0, -1],
    angle_deg: -90,
  }
  modified.body = {
    panel: 'body',
    instance: 'BODY-1',
    reference_label: 9001,
    direction: [0, 1],
    angle_deg: 90,
  }
  modified.force_unit = 'N'
  modified.force_normalization = 'total'
  modified.reporting_width_mm = 100
  modified.thickness_mm = 1
  modified.reporting_width_basis = 'default_100_mm'
  modified.force_basis = 'total_width'
  modified.history = [
    { step: 'Body seating', step_id: 'bodyseating', time: 0, displacement: 0, force: 4, u1: 0, u2: 0, rf1: 4, rf2: 0 },
    { step: 'Body seating', step_id: 'bodyseating', time: 1, displacement: 2, force: -3, u1: 0, u2: 2, rf1: -3, rf2: 0 },
    { step: 'Closing', step_id: 'closing', time: 2, displacement: 0, force: 0.5, u1: 0, u2: 0, rf1: 0, rf2: -0.5 },
    { step: 'Closing', step_id: 'closing', time: 3, displacement: 5, force: -7, u1: 0, u2: 5, rf1: 0, rf2: 7 },
  ]
  modified.frames = modified.frames.map(
    (frame: { step?: string; step_id?: string }, index: number) => ({
      ...frame,
      step: index < modified.frames.length / 2 ? 'Closing' : 'Body seating',
      step_id: index < modified.frames.length / 2 ? 'closing' : 'bodyseating',
    }),
  )
  await page.route('**/results.json', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(modified),
    }),
  )

  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  const trace = () =>
    page.evaluate(() => {
      const el = document.querySelector('.plot') as unknown as { data?: { y?: number[] }[] }
      return (el.data?.[0]?.y ?? []).map((value) => Number(value))
    })
  await expect.poll(trace).toEqual([0.5, -7])
  await expect(page.getByTestId('selected-direction')).toContainText('(0.000, -1.000)')
  await expect(page.getByTestId('selected-direction')).toContainText('-90.0')
  await expect(page.getByTestId('selected-rp')).toContainText('PANEL-1')
  await expect(page.getByTestId('force-basis-text')).toContainText('W = 100 mm')

  const step = page.getByLabel('Curve step')
  await step.selectOption('bodyseating')
  await expect.poll(trace).toEqual([4, -3])
  await expect(page.getByTestId('selected-direction')).toContainText('(0.000, 1.000)')
  await expect(page.getByTestId('selected-direction')).toContainText('90.0')
  await expect(page.getByTestId('selected-rp')).toContainText('BODY-1')
  await expect(page.getByTestId('selected-step')).toContainText('Body seating')

  const download = async () => {
    const pending = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Export displayed curve (2 rows)' }).click()
    return readFileSync((await (await pending).path())!, 'utf8')
  }
  const bodyCsv = await download()
  const bodyRows = bodyCsv.trim().split(/\r?\n/)
  expect(bodyRows).toHaveLength(2)
  expect(bodyRows[1]).toBe('4,-3')

  // Reverse Y is a visible display convention; the trace and export mirror but
  // the direction readout does not change.
  await page.getByLabel('Reverse Y sign').check()
  await expect.poll(trace).toEqual([-4, 3])
  await expect(page.getByTestId('reverse-y-indicator')).toContainText('inverted for display')
  const flippedCsv = await download()
  expect(flippedCsv.trim().split(/\r?\n/)[1]).toBe('-4,3')

  await step.selectOption('closing')
  await expect.poll(trace).toEqual([-0.5, 7])
  await expect(page.getByTestId('selected-direction')).toContainText('(0.000, -1.000)')
})

/**
 * Gate D: the full force description must stay readable.
 *
 * The measured defect was the rotated Y title "Door panel reaction along closing
 * direction (N)": about 269 px of text in a 210 px Plotly host, extending 45 px
 * above and 14 px below the SVG. The fix moves the full phrase into a wrapping
 * caption beside the plot and keeps a concise unit-bearing axis title. This test
 * measures the rendered SVG text against the actual clipping container instead
 * of comparing a string.
 */
type Box = { top: number; bottom: number; left: number; right: number; width: number; height: number }

async function axisLayout(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const rect = (element: Element | null): Box | null => {
      if (!element) return null
      const box = element.getBoundingClientRect()
      return {
        top: box.top,
        bottom: box.bottom,
        left: box.left,
        right: box.right,
        width: box.width,
        height: box.height,
      }
    }
    const plot = document.querySelector('.plot') as HTMLElement | null
    const caption = document.querySelector('[data-testid="force-caption"]') as HTMLElement | null
    const yTitle = document.querySelector('.plot .ytitle')
    const xTitle = document.querySelector('.plot .xtitle')
    return {
      plot: rect(plot),
      y: rect(yTitle),
      x: rect(xTitle),
      yText: yTitle?.textContent ?? '',
      xText: xTitle?.textContent ?? '',
      caption: caption?.textContent ?? '',
      captionBox: rect(caption),
      aria: plot?.getAttribute('aria-label') ?? '',
      describedBy: plot?.getAttribute('aria-describedby') ?? '',
    }
  })
}

test('the full force description is visible and the axis titles fit the plot at every width', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Force axis layout', example: true } })
  ).json()
  const { deck } = await meshAndDeck(request, revision)
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name: 'Force axis layout run',
        mode: 'ABAQUS',
      },
    })
  ).json()
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + run.id)).json()) as Job).status, {
      timeout: 90000,
    })
    .toBe('Completed')
  const base = await (
    await request.get('/api/jobs/' + run.id + '/artifacts/results.json')
  ).json()
  const withUnit = (unit: string) => {
    const copy = structuredClone(base)
    copy.steps = [
      {
        name: 'Body seating',
        id: 'bodyseating',
        role: 'body',
        instance: 'BODY-1',
        reference_label: 9001,
        direction: [0, 1],
        angle_deg: 90,
        distance_mm: 3,
      },
      {
        name: 'Closing',
        id: 'closing',
        role: 'door',
        instance: 'PANEL-1',
        reference_label: 2,
        direction: [0, -1],
        angle_deg: -90,
        distance_mm: 5,
      },
    ]
    copy.closing = {
      ...(copy.closing ?? {}),
      instance: 'PANEL-1',
      reference_label: 2,
      direction: [0, -1],
      angle_deg: -90,
    }
    copy.body = {
      panel: 'body',
      instance: 'BODY-1',
      reference_label: 9001,
      direction: [0, 1],
      angle_deg: 90,
    }
    copy.force_unit = unit
    copy.history = [
      { step: 'Closing', step_id: 'closing', time: 0, displacement: 0, force: 0 },
      { step: 'Closing', step_id: 'closing', time: 1, displacement: 5, force: -7 },
      { step: 'Body seating', step_id: 'bodyseating', time: 2, displacement: 0, force: 4 },
      { step: 'Body seating', step_id: 'bodyseating', time: 3, displacement: 3, force: -3 },
    ]
    return copy
  }
  let current = withUnit('N')
  const measurements: Record<string, unknown>[] = []
  await page.route('**/results.json', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(current),
    })
  })
  await page.goto('/#results/' + run.id)
  await expect(page.locator('.js-plotly-plot')).toBeVisible()
  await expect(page.locator('.plot .ytitle')).toHaveText('Force (N)')

  const expectFits = async (label: string) => {
    // Plotly re-lays out axis titles asynchronously after a responsive resize;
    // measure only after two consecutive identical geometries.
    let previous = ''
    await expect
      .poll(
        async () => {
          const layout = await axisLayout(page)
          const key = JSON.stringify([layout.plot?.width, layout.x?.right, layout.y?.height])
          const stable = key === previous && key !== ''
          previous = key
          return stable
        },
        { timeout: 15000, intervals: [250] },
      )
      .toBe(true)
    const layout = await axisLayout(page)
    measurements.push({
      label,
      plot: layout.plot,
      yTitle: layout.y,
      xTitle: layout.x,
      yText: layout.yText,
      xText: layout.xText,
      caption: layout.caption,
      aria: layout.aria,
    })
    expect(layout.plot, label + ' plot').toBeTruthy()
    expect(layout.y, label + ' y title').toBeTruthy()
    expect(layout.x, label + ' x title').toBeTruthy()
    // The clipped titles were the reported defect: both axis titles now render
    // completely inside the plot host, above and below included.
    expect(layout.y!.top, label + ' y top').toBeGreaterThanOrEqual(layout.plot!.top - 1)
    expect(layout.y!.bottom, label + ' y bottom').toBeLessThanOrEqual(layout.plot!.bottom + 1)
    expect(layout.x!.left, label + ' x left').toBeGreaterThanOrEqual(layout.plot!.left - 1)
    expect(layout.x!.right, label + ' x right').toBeLessThanOrEqual(layout.plot!.right + 1)
    // The full direction, panel and units stay visible in the caption.
    expect(layout.caption.length, label + ' caption').toBeGreaterThan(20)
    expect(layout.describedBy).toBe('force-plot-caption')
    expect(layout.aria.length).toBeGreaterThan(layout.caption.length)
  }

  for (const size of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 720, height: 450 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(size)
    await page.goto('/#results/' + run.id)
    await expect(page.locator('.plot .ytitle')).toHaveText('Force (N)')
    let layout = await axisLayout(page)
    expect(layout.caption).toContain(
      'Door panel reaction along closing direction (N)',
    )
    expect(layout.caption).toContain('Door panel travel along closing direction (mm)')
    await expectFits(`${size.width} en`)

    // Japanese keeps the same information with the localized phrase.
    await page.locator('.lang-button').click()
    await expect(page.locator('.plot .ytitle')).toHaveText('力 (N)', { timeout: 10000 })
    layout = await axisLayout(page)
    expect(layout.caption).toContain('閉じ方向のドアパネル反力 (N)')
    expect(layout.caption).toContain('閉じ方向のドアパネル移動量 (mm)')
    await expectFits(`${size.width} ja`)
    await page.locator('.lang-button').click()
    await expect(page.locator('.plot .ytitle')).toHaveText('Force (N)')
  }

  // A per-millimetre force basis carries its own unit in both the axis and the
  // full description; the plotted trace and the two-row export do not change.
  const trace = () =>
    page.evaluate(() => {
      const el = document.querySelector('.plot') as unknown as { data?: { y?: number[] }[] }
      return (el.data?.[0]?.y ?? []).map((value) => Number(value))
    })
  await expect.poll(trace).toEqual([0, -7])
  current = withUnit('N/mm')
  await page.unroute('**/results.json')
  await page.route('**/results.json', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'cache-control': 'no-store' },
      body: JSON.stringify(current),
    })
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  // Same URL: a hash-only goto would not reload the run, so reload explicitly.
  if (!page.url().endsWith('/#results/' + run.id)) await page.goto('/#results/' + run.id)
  else await page.reload()
  await expect(page.locator('.plot .ytitle')).toHaveText('Force (N/mm)')
  const perMm = await axisLayout(page)
  expect(perMm.caption).toContain('Door panel reaction along closing direction (N/mm)')
  await expectFits('N/mm')
  await expect.poll(trace).toEqual([0, -7])

  // The body step gets its own full description and still fits.
  await page.getByLabel('Curve step').selectOption('bodyseating')
  await expect(page.locator('.plot .ytitle')).toHaveText('Force (N/mm)')
  const body = await axisLayout(page)
  expect(body.caption).toContain('Body panel reaction along the seating direction (N/mm)')
  await expectFits('body step')

  // Reverse Y mirrors the displayed trace only; the description is unchanged.
  await page.getByLabel('Reverse Y sign').check()
  await expect.poll(trace).toEqual([-4, 3])
  const flipped = await axisLayout(page)
  expect(flipped.caption).toContain('Body panel reaction along the seating direction (N/mm)')
  await expectFits('reverse Y')

  // Legacy provenance: no step metadata. The full description names the raw
  // U2/RF2 components instead of borrowing another step's direction, and it
  // still fits the plot.
  const legacy = withUnit('N')
  legacy.steps = []
  legacy.closing = null
  legacy.body = null
  legacy.history = legacy.history.map(
    (row: { time: number; displacement: number; force: number }) => ({
      time: row.time,
      displacement: row.displacement,
      force: row.force,
    }),
  )
  current = legacy
  await page.unroute('**/results.json')
  await page.route('**/results.json', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'cache-control': 'no-store' },
      body: JSON.stringify(current),
    })
  })
  await page.reload()
  await expect(page.locator('.plot .ytitle')).toHaveText('Force (N)')
  const legacyLayout = await axisLayout(page)
  expect(legacyLayout.caption).toContain('Panel RF2 (N)')
  expect(legacyLayout.caption).toContain('Panel U2 (mm)')
  await expectFits('legacy provenance')

  mkdirSync(resolve('../../.local/evidence'), { recursive: true })
  test.info().attach('force-axis-measurements.json', {
    body: JSON.stringify(measurements, null, 2),
    contentType: 'application/json',
  })
  writeFileSync(
    resolve('../../.local/evidence/force-axis-measurements.json'),
    JSON.stringify(measurements, null, 2),
  )
})
