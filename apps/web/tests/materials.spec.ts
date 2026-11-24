import { expect, test, type Page } from './fixtures'
import { saveRevision } from './save'
import type { LibraryDetail, LibrarySummary, MaterialImportResult, Revision } from '../src/api'

async function create(
  request: import('@playwright/test').APIRequestContext,
  name: string,
) {
  return (await (
    await request.post('/api/projects', { data: { name, example: true } })
  ).json()) as Revision
}

async function importCards(
  request: import('@playwright/test').APIRequestContext,
  revision: Revision,
) {
  return (await (
    await request.post('/api/materials/import', { data: { revision: revision.id } })
  ).json()) as MaterialImportResult[]
}

async function library(
  request: import('@playwright/test').APIRequestContext,
): Promise<LibrarySummary[]> {
  return (await request.get('/api/materials')).json()
}

async function detail(
  request: import('@playwright/test').APIRequestContext,
  id: string,
): Promise<LibraryDetail> {
  return (await request.get('/api/materials/' + id)).json()
}

async function editLibraryCard(
  request: import('@playwright/test').APIRequestContext,
  id: string,
  patch: Record<string, unknown>,
) {
  const found = await detail(request, id)
  return (
    await request.put('/api/materials/' + id, {
      data: { card: { ...found.card, ...patch } },
    })
  ).json() as Promise<LibraryDetail>
}

async function openLibrary(page: Page) {
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByRole('button', { name: 'Materials' })
    .click()
}

function row(page: Page, name: string) {
  return page.locator('.material-list .material-row').filter({ hasText: name }).first()
}

test('the library validates, versions, archives and restores material cards', async ({
  page,
  request,
}) => {
  const revision = await create(request, 'Library UI')
  // The retired model-local import panel is replaced by the explicit API and the
  // CAE import panel; this test exercises the library editor.
  await request.post('/api/materials/import', { data: { revision: revision.id } })
  await page.goto('/#materials')
  await expect(row(page, 'Dense EPDM')).toBeVisible()
  await expect(row(page, 'Cellular EPDM')).toBeVisible()

  await row(page, 'Dense EPDM').click()
  const materialId = await row(page, 'Dense EPDM').getAttribute('data-material-id')
  expect(materialId).toBeTruthy()
  const density = page.getByLabel('Density (tonne/mm³)')
  await density.fill('0')
  await expect(page.getByRole('button', { name: 'Save material' })).toBeDisabled()

  await density.fill('1.15e-9')
  await page.getByLabel("Young's modulus (MPa)").fill('8.5')
  await page.getByRole('button', { name: 'Save material' }).click()
  await expect(page.getByTestId('version-history')).toContainText('v2')
  await expect(page.locator('.library-editor')).toContainText('Current v2')

  // The archived material disappears from the default list and returns on restore.
  await page.getByRole('button', { name: 'Archive' }).click()
  await expect
    .poll(async () => (await detail(request, materialId!)).archived)
    .toBe(true)
  await page.getByLabel('Include archived').check()
  const archivedRow = page.locator(`[data-material-id="${materialId}"]`)
  await expect(archivedRow).toBeVisible()
  await archivedRow.click()
  await page.getByRole('button', { name: 'Restore' }).click()
  await expect
    .poll(async () => (await detail(request, materialId!)).archived)
    .toBe(false)
  await page.getByLabel('Include archived').uncheck()
  await expect(row(page, 'Dense EPDM')).toBeVisible()
})

test('the comparison graph plots measured versions of the same library material', async ({
  page,
  request,
}) => {
  const revision = await create(request, 'Comparison')
  const imported = await importCards(request, revision)
  const foam = (await library(request)).find((entry) => entry.name === 'Cellular EPDM')!
  expect(foam).toBeTruthy()
  expect(imported.length).toBe(2)

  await page.goto('/#materials')
  await row(page, 'Cellular EPDM').click()
  await page.getByRole('button', { name: 'Duplicate' }).click()
  const copy = row(page, 'Cellular EPDM · copy')
  await expect(copy).toBeVisible()
  await page.getByLabel('Library material name').fill('Cellular EPDM copy')
  await page.getByRole('button', { name: 'Add row' }).click()
  await page.getByRole('button', { name: 'Save material' }).click()
  await expect(page.getByTestId('version-history')).toContainText('v2')
  // The renamed duplicate must be present before its comparison checkbox is
  // addressed.
  await expect(row(page, 'Cellular EPDM copy')).toBeVisible()

  await page.getByLabel('Compare Cellular EPDM current version').first().check()
  await page.getByLabel('Compare Cellular EPDM copy current version').check()
  const chart = page.getByTestId('compare-stress')
  await expect(chart).toBeVisible()
  await expect(chart).toContainText('Cellular EPDM')
  await expect(chart).toContainText('Cellular EPDM copy')
  await expect(page.getByTestId('compare-lateral')).toBeVisible()
})

test('paste review stays in the library and leaves the saved card unchanged', async ({
  page,
  request,
}) => {
  const revision = await create(request, 'Paste library')
  await importCards(request, revision)
  await page.goto('/#materials')
  await row(page, 'Cellular EPDM').click()
  await expect(page.getByRole('heading', { name: /Uniaxial test data/ })).toContainText(
    '5 samples',
  )

  await page.getByRole('button', { name: 'Paste table data' }).click()
  const textarea = page.getByLabel('Paste table data')
  await textarea.fill(
    [
      'stress,strain_axial,strain_lateral',
      '0.10,0.05,-0.02',
      '0.20,0.10,-0.04',
      '0.40,oops,-0.02',
    ].join('\n'),
  )
  await expect(page.getByTestId('paste-summary')).toContainText('2 rows accepted, 1 rejected')
  await expect(page.getByRole('button', { name: /Apply \d+ rows/ })).toBeDisabled()
  await page.getByRole('button', { name: 'Cancel' }).click()
  await expect(page.getByRole('heading', { name: /Uniaxial test data/ })).toContainText(
    '5 samples',
  )
})

test('workspace assigns a library material, adopts a newer version and reuses the mesh', async ({
  page,
  request,
}) => {
  const revision = await create(request, 'Library adoption')
  const imported = await importCards(request, revision)
  // Use this revision's own import; other tests may have same-named entries.
  let denseId = ''
  for (const item of imported) {
    const found = await detail(request, item.library_id)
    if (found.name === 'Dense EPDM') denseId = found.id
  }
  expect(denseId).toBeTruthy()
  const v2 = await editLibraryCard(request, denseId, { young: 8.5 })
  expect(v2.current_version).toBe(2)

  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Components' }).click()
  await page.locator('.region-list button', { hasText: 'Mounting foot' }).first().click()
  await page.getByTestId('assign-material').click()
  await page.getByLabel('Assign from the material library').selectOption(denseId)
  const assigned = page.getByTestId('library-newer')
  await expect(assigned).toHaveCount(0)
  await expect(page.locator('.property-body')).toContainText('Dense EPDM')

  await saveRevision(page)
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  let projects = (await (await request.get('/api/projects')).json()) as {
    id: string
    revision: string
  }[]
  let head = projects.find((entry) => entry.id === revision.project)!
  let saved = (await (await request.get('/api/revisions/' + head.revision)).json()) as Revision
  const face = saved.setup.faces.find((item) => item.name === 'Mounting foot')!
  const card = saved.setup.materials.find((item) => item.id === face.material)!
  expect(card.library_id).toBe(denseId)
  expect(card.library_version).toBe(2)
  expect(card.young).toBe(8.5)
  expect(saved.mesh_compat).toBe(revision.mesh_compat)

  // Material-only edit: mesh and fixture stay reusable, deck carries the value.
  await workflow.getByRole('button', { name: 'Mesh' }).click()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 60000 })
  await workflow.getByRole('button', { name: 'Mounting' }).click()
  await page.getByRole('button', { name: /Resolve .* mounting edges to nodes/ }).click()
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await workflow.locator('[data-stage="results"]').click()
  await page.getByRole('button', { name: 'Prepare input deck' }).click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', {
    timeout: 60000,
  })
  const deckHref = await page
    .getByRole('link', { name: 'Inspect input deck' })
    .getAttribute('href')
  const deck = await (await request.get(deckHref!)).text()
  expect(deck).toContain('8.5')

  // A newer library version appears in the workspace and can be adopted.
  await editLibraryCard(request, denseId, { young: 9.5 })
  // Reload so the workspace re-fetches the library current versions.
  await page.reload()
  await workflow.getByRole('button', { name: 'Components' }).click()
  await page.locator('.region-list button', { hasText: 'Mounting foot' }).first().click()
  await page.getByTestId('assign-material').click()
  await expect(page.locator('.property-body')).toContainText('Dense EPDM')
  await expect(page.getByTestId('library-newer')).toBeVisible()
  await page.getByRole('button', { name: 'Adopt v3' }).click()
  await saveRevision(page)
  await expect(page.locator('.crumb')).toContainText('Revision 03')
  projects = (await (await request.get('/api/projects')).json()) as {
    id: string
    revision: string
  }[]
  head = projects.find((entry) => entry.id === revision.project)!
  saved = (await (await request.get('/api/revisions/' + head.revision)).json()) as Revision
  const adopted = saved.setup.materials.find((item) => item.library_id === denseId)!
  expect(adopted.library_version).toBe(3)
  expect(adopted.young).toBe(9.5)
  expect(saved.mesh_compat).toBe(revision.mesh_compat)
})

test('a compressible neo-Hookean card is edited in both languages and versioned', async ({
  page,
  request,
}) => {
  const name = 'Synthetic neo-Hookean ' + Date.now()
  await page.goto('/#materials')
  await page.getByRole('button', { name: 'New material' }).click()
  // Wait for the created card to load into the editor before editing it.
  await expect(page.getByLabel('Library material name')).toHaveValue('New material')
  await expect(page.getByTestId('version-history')).toContainText('v1')
  await page.getByLabel('Library material name').fill(name)
  const model = page.getByLabel('Material model')
  await model.selectOption('neo_hookean')
  await expect(model).toHaveValue('neo_hookean')
  await expect(page.getByLabel(/C10/)).toHaveValue('0.5')
  await expect(page.getByLabel(/D1/)).toHaveValue('0.01')
  await page.getByLabel(/C10/).fill('0.75')
  await page.getByLabel(/C10/).press('Tab')
  await page.getByRole('button', { name: 'Save material' }).click()
  await expect(page.getByTestId('version-history')).toContainText('v2')
  await expect(row(page, name)).toContainText('neo-Hookean')

  const rowId = await row(page, name).getAttribute('data-material-id')
  const saved = await detail(request, rowId!)
  expect(saved.card.model).toBe('neo_hookean')
  expect(saved.card.c10).toBe(0.75)
  expect(saved.card.d1).toBe(0.01)
  // v1 remains the original linear card; the model change created v2.
  expect(saved.versions[0].card.model).toBe('linear_elastic')
  expect(saved.versions[1].card.model).toBe('neo_hookean')

  // The same fields and law are localized, and editing creates another version.
  await page.locator('.lang-button').click()
  await expect(page.getByLabel('材料モデル')).toBeVisible()
  await expect(row(page, name)).toContainText('圧縮性 neo-Hookean')
  await page.getByLabel(/C10/).fill('0.9')
  await page.getByLabel(/C10/).press('Tab')
  await page.getByRole('button', { name: '材料を保存' }).click()
  await expect(page.getByTestId('version-history')).toContainText('v3')
  const versions = (await detail(request, rowId!)).versions
  expect(versions[1].card.c10).toBe(0.75)
  expect(versions[2].card.c10).toBe(0.9)
  expect(versions[2].card.d1).toBe(0.01)
})

test('the material library is localized in Japanese', async ({ page }) => {
  await page.goto('/#materials')
  await page.getByRole('button', { name: /日本語/ }).click()
  await expect(page.getByRole('heading', { name: '材料ライブラリ' })).toBeVisible()
  await expect(page.getByRole('button', { name: '新材料' })).toBeVisible()
  await expect(page.getByLabel('材料を検索')).toBeVisible()
  await expect(page.getByText('共有材料ライブラリ')).toBeVisible()
})
