import { expect, type Page } from '@playwright/test'

/**
 * Gate 7 readiness hook for the workspace viewport.
 *
 * `data-readiness-settled` is published by Workspace once the readiness response
 * for the current revision has been applied; that response decides whether the
 * next-action banner is mounted, so the canvas height is not final before it.
 * `data-viewport-ready` is published by the renderer atomically with the camera
 * and host/fit dimensions only when the last fit used the current host size.
 *
 * The final poll requires those values (and the host rect) to stay unchanged for
 * 300 ms. That catches a ResizeObserver refit that is still queued when the
 * readiness flag first flips, without changing any camera assertion.
 */
export async function settleViewport(page: Page) {
  await expect(page.locator('.viewport-wrap[data-readiness-settled="true"]')).toBeVisible()
  await expect(page.locator('.seal-vtk-host')).toHaveAttribute('data-viewport-ready', 'true')
  const read = () =>
    page.evaluate(() => {
      const host = document.querySelector('.seal-vtk-host') as HTMLElement | null
      if (!host) return ''
      const rect = host.getBoundingClientRect()
      return [
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        host.dataset.hostSize,
        host.dataset.fitSize,
        host.dataset.camera,
      ].join('|')
    })
  await expect
    .poll(
      async () => {
        const before = await read()
        await page.waitForTimeout(300)
        return before === (await read())
      },
      { timeout: 20000 },
    )
    .toBe(true)
}
