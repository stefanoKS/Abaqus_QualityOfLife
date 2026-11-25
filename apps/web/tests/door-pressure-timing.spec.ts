/**
 * Gate F: playback cadence with pressure arrows on and off, on the same build
 * and result. Opt-in via SEAL_DOOR_JOB.
 */
import { writeFileSync } from 'node:fs'
import { expect, test } from './fixtures'

const JOB = process.env.SEAL_DOOR_JOB
const EVIDENCE = process.env.SEAL_DOOR_EVIDENCE || process.cwd()

async function measure(page: import('./fixtures').Page) {
  await page.locator('.playback-slider').evaluate((element) => {
    const input = element as HTMLInputElement
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(input, '0')
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await page.evaluate(() => {
    const target = document.querySelector('[data-testid="frame-count"]')!
    const viewport = document.querySelector('.seal-vtk-host') as HTMLElement
    const samples: { t: number; text: string; camera: string }[] = []
    ;(window as unknown as { __samples: typeof samples }).__samples = samples
    new MutationObserver(() => {
      samples.push({
        t: performance.now(),
        text: target.textContent ?? '',
        camera: viewport.dataset.camera ?? '',
      })
    }).observe(target, { childList: true, subtree: true, characterData: true })
  })
  const play = page.locator('.play-toggle')
  await play.click()
  await expect
    .poll(
      async () =>
        page.evaluate(
          () =>
            (window as unknown as { __samples: unknown[] }).__samples?.length ?? 0,
        ),
      { timeout: 20000 },
    )
    .toBeGreaterThanOrEqual(20)
  await play.click()
  const samples = await page.evaluate(
    () => (window as unknown as { __samples: { t: number; camera: string }[] }).__samples,
  )
  const intervals = samples.slice(1).map((sample, index) => sample.t - samples[index].t)
  const sorted = [...intervals].sort((a, b) => a - b)
  return {
    frames: samples.length,
    median_ms: sorted[Math.floor(sorted.length / 2)] ?? 0,
    p95_ms: sorted[Math.floor(sorted.length * 0.95)] ?? 0,
    worst_ms: sorted[sorted.length - 1] ?? 0,
    cameras: [...new Set(samples.map((sample) => sample.camera))].length,
  }
}

test('pressure arrows do not change playback cadence or camera', async ({ page }) => {
  test.skip(!JOB, 'SEAL_DOOR_JOB is not set')
  await page.goto('/#results/' + JOB)
  await expect(page.getByTestId('run-complete')).toBeVisible({ timeout: 60000 })
  await expect(page.getByTestId('pressure-chart')).toBeVisible({ timeout: 30000 })
  const toggle = page.getByTestId('pressure-arrows-toggle')
  await expect(toggle).toBeChecked()
  const withArrows = await measure(page)
  await toggle.uncheck()
  await expect(page.locator('.seal-vtk-host')).toHaveAttribute('data-pressure-arrows', '0')
  const withoutArrows = await measure(page)
  await toggle.check()
  const report = { job: JOB, with_arrows: withArrows, without_arrows: withoutArrows }
  writeFileSync(EVIDENCE + '/gate-f-timing.json', JSON.stringify(report, null, 2))
  expect(withArrows.cameras).toBe(1)
  expect(withoutArrows.cameras).toBe(1)
  expect(withArrows.frames).toBeGreaterThanOrEqual(20)
  expect(withoutArrows.frames).toBeGreaterThanOrEqual(20)
})
