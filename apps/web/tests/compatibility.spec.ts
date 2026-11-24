import { expect, test } from './fixtures'

/**
 * A tab and the API must agree on the browser release and API generation. An
 * incompatible pair shows one recovery action and cannot create a project.
 */
test('a stale tab is explained and project creation is disabled until reload', async ({
  page,
}) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({
      json: {
        product: 'Abaqus QOL',
        status: 'ready',
        api: 3,
        release: 'ffffffffffff',
        frontend: 'index-OTHER.js',
      },
    }),
  )
  await page.goto('/#dashboard')
  const banner = page.getByTestId('compat-banner')
  await expect(banner).toBeVisible()
  await expect(banner).toContainText('different browser build')
  await expect(page.getByRole('button', { name: 'New project' })).toBeDisabled()

  // The recovery action is a reload; clearing the mismatch restores writes.
  await page.unroute('**/api/health')
  await page.reload()
  await expect(page.getByTestId('compat-banner')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'New project' })).toBeEnabled()
})

test('an API generation mismatch offers restart, not a misleading reload', async ({ page }) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({
      json: {
        product: 'Abaqus QOL',
        status: 'ready',
        api: 2,
        release: 'legacy',
        frontend: 'index-OTHER.js',
      },
    }),
  )
  await page.goto('/#dashboard')
  const banner = page.getByTestId('compat-banner')
  await expect(banner).toBeVisible()
  await expect(banner).toContainText('different generations')
  await expect(banner.getByRole('button', { name: 'Reload' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'New project' })).toBeDisabled()

  // The API refuses a write from an identified stale tab even if a UI is bypassed.
  const refused = await page.request.post('/api/projects', {
    data: { name: 'Bypass', example: false },
    headers: { 'X-Abaqus-QOL-Client': 'index-OTHER.js', 'X-Abaqus-QOL-Api': '3' },
  })
  expect(refused.status()).toBe(409)
})

test('a mismatched client cannot prepare or submit from Review', async ({ page, request }) => {
  const revision = await (await request.post('/api/projects', {
    data: { name: 'Incompatible review', example: true },
  })).json()
  await page.route('**/api/health', (route) => route.fulfill({
    json: { product: 'Abaqus QOL', status: 'ready', api: 2, release: 'legacy', frontend: 'index-OTHER.js' },
  }))
  await page.goto('/#workspace/' + revision.id)
  await page.locator('[data-stage="motion"]').click()
  const actions = page.getByTestId('action-group')
  await expect(actions.getByRole('button', { name: 'Prepare input deck' })).toBeDisabled()
  await expect(actions.getByRole('button', { name: 'Submit Abaqus analysis' })).toBeDisabled()
  await expect(actions).toContainText('disabled')
})

test('a lost create response is retried with the same request identity', async ({
  page,
  request,
}) => {
  let dropped = false
  await page.route('**/api/project-groups', async (route) => {
    if (dropped) {
      await route.continue()
      return
    }
    dropped = true
    // Commit the creation on the server, then lose the response.
    await route.fetch()
    await route.abort('failed')
  })

  await page.goto('/#dashboard')
  await page.getByRole('button', { name: 'New project' }).click()
  await page.getByLabel('Project name').fill('Atomic project')
  await page.getByLabel('Model name').fill('Door A')
  await page.getByRole('button', { name: 'Create project' }).click()
  // The lost response produces an error toast, not a second project.
  await expect(page.locator('.toast')).toBeVisible()

  await page.getByRole('button', { name: 'Create project' }).click()
  await expect(page).toHaveURL(/#workspace\//)
  await expect(page.locator('.crumb-model')).toContainText('Door A')

  // Scope to this action's group: other tests share the disposable server data.
  const groups = await (await request.get('/api/groups')).json()
  const mine = groups.filter((group: { name: string }) => group.name === 'Atomic project')
  expect(mine).toHaveLength(1)
  expect(mine[0].models).toHaveLength(1)
  expect(mine[0].models[0].name).toBe('Door A')
})
