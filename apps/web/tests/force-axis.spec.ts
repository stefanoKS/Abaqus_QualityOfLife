/**
 * Gate C: the actual plot trace, the selected-step readout and the exported
 * second CSV row follow the selected step's own projection direction.
 *
 * A manufactured test run supplies the transport; the results index is cloned
 * only in the browser route so both steps carry distinct directions and force
 * samples. This is frontend evidence, not solver evidence.
 */
import { randomUUID } from 'node:crypto'
import { readFileSync } from 'node:fs'
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
