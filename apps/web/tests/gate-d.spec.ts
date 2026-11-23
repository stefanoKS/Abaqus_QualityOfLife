/**
 * Gate D: the exported displayed curve distinguishes missing measurements from
 * measured zeros in real browser download bytes.
 *
 * The run is a manufactured test run. Only the results index transport is
 * modified for this UI test (some samples lose a component or carry a measured
 * zero); frames and solver artifacts are untouched. This is frontend evidence,
 * not solver evidence.
 */
import { randomUUID } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { expect, test } from './fixtures'
import { meshAndDeck } from './pipeline'
import type { Job, Revision } from '../src/api'

test('missing measurements are empty cells and measured zeros stay numeric', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Gate D holes', example: true } })
  ).json()
  const { deck } = await meshAndDeck(request, revision)
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name: 'Gate D holes',
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
  // Three deliberate cases inside the same aligned sample set.
  modified.history[2].u2 = null // missing component: magnitude cannot be formed
  modified.history[3].force = 0 // measured zero force: numeric zero
  modified.history[4].force = null // missing force: empty cell
  await page.route('**/results.json', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(modified) }),
  )

  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()

  const pending = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export displayed curve (2 rows)' }).click()
  const download = await pending
  const csv = readFileSync((await download.path())!, 'utf8').trim()
  const rows = csv.split(/\r?\n/).map((line) => line.split(','))
  expect(csv.startsWith('#')).toBe(false)
  expect(rows).toHaveLength(2)
  expect(rows[0].length).toBe(rows[1].length)
  expect(rows[0].length).toBe(modified.history.length)
  // Sample 2: missing U2 -> empty magnitude, but the force is still numeric.
  expect(rows[0][2]).toBe('')
  expect(Number.isFinite(Number(rows[1][2]))).toBeTruthy()
  // Sample 3: measured zero force is the number 0, not a hole.
  expect(rows[1][3]).toBe('0')
  // Sample 4: missing force is a hole.
  expect(rows[1][4]).toBe('')
  // Everything else is numeric or an explicit hole; no text leaks in.
  for (const row of rows) {
    for (const cell of row) {
      expect(cell === '' || Number.isFinite(Number(cell))).toBeTruthy()
    }
  }
})
