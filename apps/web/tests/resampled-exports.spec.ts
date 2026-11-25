/**
 * Resampled two-row exports against retained licensed result packages.
 *
 * These tests open the immutable `.aqresult` files read-only into a disposable
 * test-data root and download real browser bytes. They are opt-in by path so CI
 * stays free of proprietary packages; the same numeric targets are exercised by
 * the manufactured cases in curve/gate-d/force-axis.
 *
 *   SEAL_LICENSED_AQRESULT=...9efc065a....aqresult
 *   SEAL_GENKOU_AQRESULT=...GENKOU-reference.aqresult
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test, type Page } from './fixtures'
import type { Job } from '../src/api'

const LICENSED =
  process.env.SEAL_LICENSED_AQRESULT ??
  resolve(process.cwd(), '../../.local/gate-c/results/Door-pressure-licensed-Door-pressure-licensed-20261125-221400-9efc065a.aqresult')
const GENKOU =
  process.env.SEAL_GENKOU_AQRESULT ??
  resolve(process.cwd(), '../../.local/evidence/door-panel-pressure/GENKOU-reference.aqresult')

type Rows = string[][]

function rows(text: string): Rows {
  return text
    .replace(/^\uFEFF/, '')
    .trim()
    .split(/\r?\n/)
    .map((line) => line.split(','))
}

function pairs(table: Rows): { xs: number[]; ys: (number | null)[] } {
  return {
    xs: table[0].slice(1).map(Number),
    ys: table[1].slice(1).map((value) => (value === '' ? null : Number(value))),
  }
}

function valueAt(table: Rows, x: number): number | null {
  const { xs, ys } = pairs(table)
  const index = xs.findIndex((candidate) => Math.abs(candidate - x) <= 1e-9)
  return index < 0 ? null : ys[index]
}

function occurrences(table: Rows, x: number): number {
  return pairs(table).xs.filter((candidate) => Math.abs(candidate - x) <= 1e-9).length
}

async function openResult(
  request: import('@playwright/test').APIRequestContext,
  path: string,
): Promise<Job> {
  const response = await request.post('/api/files/result/open', { data: { path } })
  expect(response.ok(), await response.text()).toBeTruthy()
  return (await response.json()) as Job
}

async function openRun(page: Page, request: import('@playwright/test').APIRequestContext, path: string) {
  const job = await openResult(request, path)
  await page.goto('/#results/' + job.id)
  await expect(page.getByTestId('run-complete')).toBeVisible({ timeout: 90000 })
  await expect(page.getByTestId('pressure-chart')).toBeVisible({ timeout: 60000 })
  return job
}

async function seek(page: Page, index: number) {
  const slider = page.locator('.playback-slider')
  const maximum = await slider.evaluate((element) => Number((element as HTMLInputElement).max))
  const target = Math.min(index, maximum)
  await slider.evaluate((element, value) => {
    const input = element as HTMLInputElement
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(
      input,
      String(value),
    )
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  }, target)
  return target
}

async function loadCsv(page: Page) {
  const pending = page.waitForEvent('download')
  await page.getByTestId('export-curve').click()
  const download = await pending
  const text = readFileSync((await download.path())!, 'utf8')
  return { table: rows(text), name: download.suggestedFilename(), text }
}

async function pressureCsv(page: Page) {
  const pending = page.waitForEvent('download')
  await page.getByTestId('export-pressure').click()
  const download = await pending
  const text = readFileSync((await download.path())!, 'utf8')
  return { table: rows(text), name: download.suggestedFilename(), text }
}

test.describe('licensed 9efc065a package', () => {
  test.skip(!existsSync(LICENSED), 'SEAL_LICENSED_AQRESULT is absent')

  test('load export matches the 1 mm and 0.65 mm reference values', async ({
    page,
    request,
  }) => {
    const job = await openRun(page, request, LICENSED)
    const loaded = await loadCsv(page)
    expect(loaded.name).toContain(job.id.slice(0, 8))
    expect(loaded.name).toContain('-closing-')
    expect(loaded.name).toContain('-dx1mm')
    expect(loaded.table[0]).toEqual(['stroke(mm)', '0', '1', '2', '2.5'])
    expect(loaded.table[1][0]).toBe('F (N/100mm)')
    expect(Number(loaded.table[1][1])).toBe(0)
    expect(Number(loaded.table[1][2])).toBe(0)
    expect(Number(loaded.table[1][3])).toBeCloseTo(8.26096907258, 9)
    expect(Number(loaded.table[1][4])).toBeCloseTo(51.3679385185, 9)

    await page.getByTestId('stroke-interval').fill('0.65')
    const custom = await loadCsv(page)
    expect(custom.name).toContain('dx0.65mm')
    expect(valueAt(custom.table, 1.95)).toBeCloseTo(5.613570174, 9)
    // The endpoint 2.5 mm is appended once after the 1.95 mm grid point.
    expect(occurrences(custom.table, 2.5)).toBe(1)
  })

  test('door pressure export matches the 1.3 mm interpolation targets', async ({
    page,
    request,
  }) => {    const job = await openRun(page, request, LICENSED)
    const index = await (
      await request.get('/api/jobs/' + job.id + '/artifacts/results.json')
    ).json()
    const last = await seek(page, index.frames.length - 1)
    await expect
      .poll(async () =>
        Number(await page.getByTestId('vtk-viewport').getAttribute('data-frame-time')),
      )
      .toBeCloseTo(index.frames[last].time, 6)

    const exported = await pressureCsv(page)
    expect(exported.name).toContain(job.id.slice(0, 8))
    expect(exported.name).toContain('frame-' + String(last).padStart(5, '0'))
    expect(exported.name).toContain('dx1.3mm')
    expect(exported.table[0][0]).toBe('door station(mm)')
    expect(exported.table[1][0]).toBe('CPRESS (kPa)')
    expect(valueAt(exported.table, 11.7)).toBeCloseTo(67.179839313, 3)
    expect(valueAt(exported.table, 13)).toBeCloseTo(125.8664876223, 3)
    expect(valueAt(exported.table, 14.3)).toBeCloseTo(52.4925112724, 3)
    expect(valueAt(exported.table, 24)).toBe(0)
    // The measured endpoint appears once, not as a duplicate grid point.
    expect(occurrences(exported.table, 24)).toBe(1)

    // A second, independent interval is honoured: 2.0 mm hits the measured
    // 12.0 mm station exactly (57.2002381086 kPa) and still ends once at 24.0.
    await page.getByTestId('station-interval').fill('2')
    const coarse = await pressureCsv(page)
    expect(coarse.name).toContain('dx2mm')
    expect(valueAt(coarse.table, 12)).toBeCloseTo(57.2002381086, 3)
    expect(occurrences(coarse.table, 24)).toBe(1)
    await page.getByTestId('station-interval').fill('1.3')

    // Original profile nodes retain the measured peak exactly.
    await page.getByTestId('pressure-sampling').selectOption('original')
    const nodes = await pressureCsv(page)
    const { xs, ys } = pairs(nodes.table)
    const measured = ys.filter((value): value is number => value !== null)
    expect(Math.max(...measured)).toBeCloseTo(165.36930203437805, 6)
    expect(xs[ys.indexOf(Math.max(...measured))]).toBeCloseTo(13.5, 9)
    expect(nodes.name).toContain('-nodes')
  })

  async function licensedIndex(
    page: Page,
    request: import('@playwright/test').APIRequestContext,
  ) {
    const job = await openRun(page, request, LICENSED)
    const index = await (
      await request.get('/api/jobs/' + job.id + '/artifacts/results.json')
    ).json()
    return { job, index, lastFile: index.frames[index.frames.length - 1].file as string }
  }

  async function routeFrame(
    page: Page,
    file: string,
    modify: (frame: Record<string, any>) => void,
  ) {
    await page.route('**/' + file, async (route) => {
      const response = await route.fetch()
      const frame = await response.json()
      modify(frame)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(frame),
      })
    })
  }

  test('all-zero, missing and ambiguous pressure arrays keep explicit cells', async ({
    page,
    request,
  }) => {
    const { index, lastFile } = await licensedIndex(page, request)
    const profileId = index.door_pressure.profiles[0].id as string
    await routeFrame(page, lastFile, (frame) => {
      const profile = frame.door_pressure.profiles[profileId]
      profile.pressure_kpa = profile.pressure_kpa.map(() => 0)
      profile.pressure_mpa = profile.pressure_mpa.map(() => 0)
    })
    await seek(page, index.frames.length - 1)
    await expect
      .poll(async () =>
        Number(await page.getByTestId('vtk-viewport').getAttribute('data-frame-time')),
      )
      .toBeCloseTo(index.frames[index.frames.length - 1].time, 6)
    const zero = await pressureCsv(page)
    const zeroPairs = pairs(zero.table)
    expect(zeroPairs.ys.every((value) => value === 0)).toBe(true)

    // A fresh route supplies a real gap and an ambiguity marker. The measured
    // grid point at 13.0 mm survives; 11.7 mm lies between two nulls.
    await page.unroute('**/' + lastFile)
    await routeFrame(page, lastFile, (frame) => {
      const profile = frame.door_pressure.profiles[profileId]
      profile.pressure_kpa[23] = null
      profile.pressure_kpa[24] = null
      profile.pressure_kpa[25] = null
      profile.ambiguous = [[226, 'pressure', 'conflicting_contact_observations']]
    })
    await page.reload()
    await seek(page, index.frames.length - 1)
    await expect(page.getByTestId('pressure-ambiguous')).toBeVisible({ timeout: 30000 })
    const gap = await pressureCsv(page)
    expect(valueAt(gap.table, 11.7)).toBeNull()
    expect(valueAt(gap.table, 13)).toBeCloseTo(125.8664876223, 3)
  })

  test('a mismatched pressure array disables the download with a reason', async ({
    page,
    request,
  }) => {
    const { index, lastFile } = await licensedIndex(page, request)
    const profileId = index.door_pressure.profiles[0].id as string
    await routeFrame(page, lastFile, (frame) => {
      const profile = frame.door_pressure.profiles[profileId]
      profile.pressure_kpa = profile.pressure_kpa.slice(0, 10)
    })
    await seek(page, index.frames.length - 1)
    await expect(page.getByTestId('pressure-export-issue')).toBeVisible({ timeout: 30000 })
    await expect(page.getByTestId('export-pressure')).toBeDisabled()
    await expect(page.getByTestId('pressure-export-issue')).toContainText('does not match')
  })

  test('an in-flight frame fetch never changes the exported frame', async ({
    page,
    request,
  }) => {
    const { index, lastFile } = await licensedIndex(page, request)
    await page.route('**/' + lastFile, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1500))
      await route.continue()
    })
    await seek(page, index.frames.length - 1)
    // The last frame is still loading: the visibly displayed frame is frame 0.
    const during = await pressureCsv(page)
    expect(during.name).toContain('frame-00000')
    await expect
      .poll(async () =>
        Number(await page.getByTestId('vtk-viewport').getAttribute('data-frame-time')),
      )
      .toBeCloseTo(index.frames[index.frames.length - 1].time, 6)
    const after = await pressureCsv(page)
    expect(after.name).toContain(
      'frame-' + String(index.frames.length - 1).padStart(5, '0'),
    )
    expect(after.text).not.toBe(during.text)
  })
})

test.describe('GENKOU reference package', () => {
  test.skip(!existsSync(GENKOU), 'SEAL_GENKOU_AQRESULT is absent')

  test('selected roof profile matches the 1.3 mm and endpoint targets', async ({
    page,
    request,
  }) => {
    const job = await openRun(page, request, GENKOU)
    const index = await (
      await request.get('/api/jobs/' + job.id + '/artifacts/results.json')
    ).json()
    const last = await seek(page, index.frames.length - 1)
    await expect
      .poll(async () =>
        Number(await page.getByTestId('vtk-viewport').getAttribute('data-frame-time')),
      )
      .toBeCloseTo(index.frames[last].time, 6)

    // A non-axis-aligned, nonuniform profile in the selected Step-2 frame.
    await page.getByTestId('pressure-profile').selectOption('UPPER_ROOFBARA-1:8')
    await expect(page.getByTestId('pressure-chart')).toHaveAttribute(
      'data-profile',
      'UPPER_ROOFBARA-1:8',
    )
    await expect(page.getByTestId('pressure-chart')).toHaveAttribute('data-patches', /[2-9]/)

    const exported = await pressureCsv(page)
    expect(exported.name).toContain('UPPER_ROOFBARA-1')
    expect(valueAt(exported.table, 35.1)).toBeCloseTo(17.0842183789, 3)
    expect(valueAt(exported.table, 45.5)).toBe(0)
    expect(valueAt(exported.table, 55.9)).toBeCloseTo(14.0379243522, 3)
    expect(occurrences(exported.table, 73.5880868374)).toBe(1)
    expect(valueAt(exported.table, 73.5880868374)).toBe(0)

    // Original nodes keep the measured 45.509 kPa peak near 56.405592 mm and
    // show that the mesh is not uniformly spaced.
    await page.getByTestId('pressure-sampling').selectOption('original')
    const nodes = await pressureCsv(page)
    const { xs, ys } = pairs(nodes.table)
    const measured = ys.filter((value): value is number => value !== null)
    const peak = Math.max(...measured)
    expect(peak).toBeCloseTo(45.50908878445625, 5)
    expect(xs[ys.indexOf(peak)]).toBeCloseTo(56.405592461919184, 6)
    const deltas = xs.slice(1).map((x, position) => x - xs[position])
    expect(Math.max(...deltas) - Math.min(...deltas)).toBeGreaterThan(1e-6)

    // Switching profile changes the chart and the export identity together.
    await page.getByTestId('pressure-profile').selectOption('UPPER_ROOF-1:7')
    await expect(page.getByTestId('pressure-chart')).toHaveAttribute(
      'data-profile',
      'UPPER_ROOF-1:7',
    )
    await page.getByTestId('pressure-sampling').selectOption('uniform')
    const other = await pressureCsv(page)
    expect(other.name).toContain('UPPER_ROOF-1')
    expect(other.name).not.toContain('UPPER_ROOFBARA-1')
  })
})

test('capture representative downloaded CSVs as local evidence', async ({ page, request }) => {
  test.skip(!existsSync(LICENSED), 'SEAL_LICENSED_AQRESULT is absent')
  const directory = process.env.SEAL_CAPTURE_DIR
  test.skip(!directory, 'SEAL_CAPTURE_DIR is not set')
  mkdirSync(directory!, { recursive: true })
  const job = await openRun(page, request, LICENSED)
  const index = await (
    await request.get('/api/jobs/' + job.id + '/artifacts/results.json')
  ).json()
  await seek(page, index.frames.length - 1)
  const load = await loadCsv(page)
  writeFileSync(resolve(directory!, load.name), load.text, 'utf8')
  await page.getByTestId('stroke-interval').fill('0.65')
  const custom = await loadCsv(page)
  writeFileSync(resolve(directory!, custom.name), custom.text, 'utf8')
  const pressure = await pressureCsv(page)
  writeFileSync(resolve(directory!, pressure.name), pressure.text, 'utf8')
  await page.getByTestId('pressure-sampling').selectOption('original')
  const nodes = await pressureCsv(page)
  writeFileSync(resolve(directory!, nodes.name), nodes.text, 'utf8')
  writeFileSync(
    resolve(directory!, 'evidence.json'),
    JSON.stringify(
      {
        job: job.id,
        load: load.name,
        custom_load: custom.name,
        pressure: pressure.name,
        pressure_nodes: nodes.name,
        load_bytes: Buffer.byteLength(load.text, 'utf8'),
        pressure_bytes: Buffer.byteLength(pressure.text, 'utf8'),
      },
      null,
      2,
    ),
  )
  if (existsSync(GENKOU)) {
    const genkou = await openRun(page, request, GENKOU)
    const genkouIndex = await (
      await request.get('/api/jobs/' + genkou.id + '/artifacts/results.json')
    ).json()
    await seek(page, genkouIndex.frames.length - 1)
    await page.getByTestId('pressure-profile').selectOption('UPPER_ROOFBARA-1:8')
    const roof = await pressureCsv(page)
    writeFileSync(resolve(directory!, roof.name), roof.text, 'utf8')
    await page.getByTestId('pressure-sampling').selectOption('original')
    const roofNodes = await pressureCsv(page)
    writeFileSync(resolve(directory!, roofNodes.name), roofNodes.text, 'utf8')
  }
})

