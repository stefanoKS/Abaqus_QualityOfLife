import { test as base, expect } from '@playwright/test'

/**
 * Measurement and functional tests select English explicitly instead of relying
 * on the (now Japanese) default, so their accessible-label assertions stay
 * stable. The init script runs before application code on every page in the
 * context, including pages opened later in the same test.
 */
export const test = base.extend({
  context: async ({ context }, use) => {
    await context.addInitScript(() => {
      try {
        window.localStorage.setItem('abaqus-qol.language', 'en')
      } catch {
        // A blocked storage API leaves the Japanese default; individual tests fail loudly.
      }
    })
    await use(context)
  },
})

export { expect }
export type { Page, Locator } from '@playwright/test'
