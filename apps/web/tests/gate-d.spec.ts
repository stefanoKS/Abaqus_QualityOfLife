/**
 * Gate D: the exported load CSV distinguishes missing measurements from
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

function parsed(csv: string) {
  const text = csv.replace(/^\uFEFF/, '').trim()
  return text.split(/\r?\n/).map((line) => line.split(','))
}

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
  modified.history[2].u2 = null // missing component: no measured stroke
  modified.history[3].force = 0 // measured zero force: numeric zero
  // A real gap in the force history, wide enough to contain a 1 mm grid point.
  for (let index = 4; index <= 6; index++) modified.history[index].force = null
  await page.route('**/results.json', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(modified) }),
  )

  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()

  const download = async () => {
    const pending = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Export load CSV (2 rows)' }).click()
    return parsed(readFileSync((await (await pending).path())!, 'utf8'))
  }

  // Original ordered samples preserve every acquisition row, including a row
  // whose stroke cannot be formed and a row with a missing force.
  await page.getByTestId('load-sampling').selectOption('original')
  const rows = await download()
  expect(rows).toHaveLength(2)
  expect(rows[0][0]).toBe('stroke(mm)')
  expect(rows[1][0]).toMatch(/^F \(N\/100mm\)$/)
  expect(rows[0].length).toBe(rows[1].length)
  expect(rows[0].length).toBe(modified.history.length + 1)
  // Column 0 is the label; sample 2 is column 3.
  expect(rows[0][3]).toBe('')
  expect(Number.isFinite(Number(rows[1][3]))).toBeTruthy()
  // Sample 3: measured zero force is the number 0, not a hole.
  expect(rows[1][4]).toBe('0')
  // Sample 4: missing force is a hole.
  expect(rows[1][5]).toBe('')
  for (const row of rows) {
    for (const cell of row.slice(1)) {
      expect(cell === '' || Number.isFinite(Number(cell))).toBeTruthy()
    }
  }

  // Uniform resampling drops the unplaceable row rather than inventing a stroke
  // for it, and a missing force at a measured station stays an empty cell.
  await page.getByTestId('load-sampling').selectOption('uniform')
  const uniform = await download()
  expect(uniform).toHaveLength(2)
  expect(uniform[0][0]).toBe('stroke(mm)')
  expect(uniform[0].slice(1).every((cell) => Number.isFinite(Number(cell)))).toBeTruthy()
  expect(uniform[1].some((cell) => cell === '')).toBeTruthy()
  expect(uniform[1][0]).toMatch(/^F \(N\/100mm\)$/)
})
