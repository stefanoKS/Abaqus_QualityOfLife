import { expect, type Page } from '@playwright/test'

/**
 * The ordinary workspace replaces the current model automatically, so tests no
 * longer click a manual "Save revision" button. Settle the automatic writer
 * instead: a just-committed field gets its short coalescing window, then the
 * visible state must be `saved`. The assertion fails loudly if persistence
 * reported an error, so a silent loss can never look like success.
 */
export async function saveRevision(page: Page) {
  await page.waitForTimeout(500)
  // Wait for the draft to be committed, not merely for a save that happened
  // before the edit: the visible state is saved only when nothing is dirty.
  await expect(
    page.locator('[data-testid="save-state"][data-state="saved"][data-dirty="false"]'),
  ).toHaveCount(1, { timeout: 25000 })
}
