import { expect, test } from './fixtures'
import { meshAndDeck } from './pipeline'
import {
  makeScene,
  type Scene,
  type ViewMesh,
  type ViewportProps,
} from '../src/viewportModel'
import type { Revision } from '../src/api'

/**
 * The assembled-position scene model. These tests exercise the real
 * `makeScene` used by the viewport: no fabricated geometry and no browser
 * rendering assumptions beyond the public surface contract.
 */
const MESH: ViewMesh = {
  nodes: [
    { id: 1, xyz: [0, 0, 0] },
    { id: 2, xyz: [10, 0, 0] },
    { id: 3, xyz: [10, 2, 0] },
    { id: 4, xyz: [0, 2, 0] },
    { id: 5, xyz: [0, 10, 0] },
    { id: 6, xyz: [10, 10, 0] },
    { id: 7, xyz: [0, -2, 0] },
    { id: 8, xyz: [10, -2, 0] },
  ],
  elements: [
    { id: 11, type: 'CPS4R', nodes: [1, 2, 3, 4], entity: 'seal-region', component: 'seal' },
    { id: 21, type: 'R2D2', nodes: [5, 6], entity: 'door-profile', component: 'door' },
    { id: 22, type: 'R2D2', nodes: [7, 8], entity: 'body-profile', component: 'body' },
  ],
}

function scene(
  mesh: ViewMesh,
  rigidInstances?: ViewportProps['rigidInstances'],
  panelOffset = 0,
): Scene {
  return makeScene({
    dimension: '2D',
    display: null,
    mode: 'element',
    selection: null,
    onSelect: () => {},
    mesh,
    rigidInstances,
    panelOffset,
  })
}

function surface(built: Scene, instance: string) {
  return built.surfaces.find((item) => item.instance === instance)!
}

test('each rigid profile keeps its own instance, offset and picking identity', () => {
  const built = scene(
    MESH,
    [
      { component: 'door', instance: 'PANEL-1', offset: 2 },
      { component: 'body', instance: 'BODY-1', offset: -3 },
    ],
    // A stale shared door offset must not leak into the body.
    99,
  )
  expect(built.surfaces.map((item) => item.instance)).toEqual([
    'WS-1',
    'PANEL-1',
    'BODY-1',
  ])
  const panel = surface(built, 'PANEL-1')
  const body = surface(built, 'BODY-1')
  const ws = surface(built, 'WS-1')
  expect(panel.points.map((point) => point[1])).toEqual([12, 12])
  expect(body.points.map((point) => point[1])).toEqual([-5, -5])
  expect(ws.points.map((point) => point[1])).toEqual([0, 0, 2, 2])
  // FE identity is still the original element inside its own instance.
  expect(panel.elements!.map((element) => element.id)).toEqual([21])
  expect(body.elements!.map((element) => element.id)).toEqual([22])
  expect(panel.instance).toBe('PANEL-1')
  expect(body.instance).toBe('BODY-1')
})

test('a door-only mesh keeps the legacy single panel offset', () => {
  const doorOnly: ViewMesh = {
    ...MESH,
    elements: MESH.elements.filter((element) => element.id !== 22),
  }
  const built = scene(doorOnly, undefined, 4)
  expect(built.surfaces.map((item) => item.instance)).toEqual(['WS-1', 'PANEL-1'])
  expect(surface(built, 'PANEL-1').points.map((point) => point[1])).toEqual([14, 14])
  // The seal is never shifted by a panel offset.
  expect(surface(built, 'WS-1').points.map((point) => point[1])).toEqual([0, 0, 2, 2])
})

test('Motion and Review show the measured assembly in both languages', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', {
      data: { name: 'Assembly diagnostics', example: true },
    })
  ).json()
  await meshAndDeck(request, revision)
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Motion' }).click()
  const panel = page.getByTestId('assembly-diagnostics')
  await expect(panel).toHaveAttribute('data-state', 'measured')
  const door = page.getByTestId('assembly-door')
  await expect(door).toContainText('1.8')
  await expect(door).toContainText('downward')
  await expect(door).toContainText('Yes')
  // Travel past the gap is reported, never presented as guaranteed contact.
  await expect(page.getByTestId('assembly-contact-caveat')).toBeVisible()

  // The same measured numbers are localized, including the direction word.
  await page.locator('.lang-button').click()
  await expect(panel.getByRole('heading', { name: '組立初期位置' })).toBeVisible()
  await expect(door).toContainText('下方向')
  await expect(door).toContainText('上側')

  await page.locator('.lang-button').click()
  await workflow.getByRole('button', { name: 'Review / Run' }).click()
  await expect(page.getByTestId('assembly-diagnostics')).toHaveAttribute(
    'data-state',
    'measured',
  )
})
