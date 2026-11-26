/**
 * Gate 5: a measured-history-only result opens the curve without inventing field
 * frames or an invalid playback control (`1 / 0`, `max=-1`, enabled Play).
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from './fixtures'
import type { Job } from '../src/api'

const here = fileURLToPath(new URL('.', import.meta.url))
const root = resolve(here, '../../..')
const python = process.env.SEAL_TEST_PYTHON || join(root, '.venv', 'Scripts', 'python.exe')
let folder = ''

test.beforeAll(() => {
  folder = mkdtempSync(join(tmpdir(), 'aqol-history-only-'))
  execFileSync(python, [
    join(root, 'scripts', 'manufactured_result_fixtures.py'),
    '--folder',
    folder,
  ])
})

test('history-only result shows the CLD curve with field controls disabled', async ({
  page,
  request,
}) => {
  const response = await request.post('/api/files/result/open', {
    data: { path: join(folder, 'history-only.aqresult') },
  })
  expect(response.ok()).toBeTruthy()
  const job = (await response.json()) as Job
  await page.goto('/#results/' + job.id)

  await expect(page.getByTestId('partial-history-only')).toBeVisible({ timeout: 30000 })
  await expect(page.getByTestId('no-field-frames')).toBeVisible()
  await expect(page.getByTestId('playback')).toHaveCount(0)
  await expect(page.locator('.playback-slider')).toHaveCount(0)
  await expect(page.getByTestId('frame-count')).toHaveCount(0)
  await expect(page.getByLabel('Field')).toBeDisabled()
  await expect(page.getByLabel('Probe mode')).toBeDisabled()

  // The measured history still plots and keeps its exports.
  await expect(page.getByTestId('force-caption')).toBeVisible()
  await expect(page.locator('.js-plotly-plot')).toHaveCount(1)
  await expect(page.getByTestId('selected-step')).toContainText('Closing')
  await expect(page.getByTestId('export-curve')).toBeEnabled()
  await expect(page.getByTestId('pressure-unavailable')).toBeVisible()

  // No field frame means no pressure/arrow section is fabricated.
  await expect(page.getByTestId('pressure-chart')).toHaveCount(0)
  await expect(page.locator('.seal-vtk-host')).not.toHaveAttribute('data-pressure-node', /\d/)
})
