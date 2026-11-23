/**
 * Gate 3a: deterministic scene geometry for stress-free rigid panels.
 *
 * The y=4 -> y=2 reproducer: a PANEL-1 rigid edge with measured U2 = -2 mm must
 * move in every field, while a colour contour still depends on scalar
 * availability. No browser or solver is involved.
 */
import { expect, test } from '@playwright/test'
import { makeScene, ramp, type ViewportProps } from '../src/viewportModel'
import { pickAt } from '../src/viewportPicking'

function props(overrides: Partial<ViewportProps> = {}): ViewportProps {
  return {
    dimension: '2D',
    display: null,
    mode: 'node',
    selection: null,
    onSelect: () => undefined,
    results: {
      instances: [
        {
          name: 'WS-1',
          nodes: [
            [1, 0, 0, 0],
            [2, 2, 0, 0],
            [3, 2, 4, 0],
            [4, 0, 4, 0],
          ],
          elements: [
            { label: 1, type: 'CPS4R', connectivity: [1, 2, 3, 4], region: 'foot' },
          ],
        },
        {
          name: 'PANEL-1',
          nodes: [
            [1, 0, 4, 0],
            [2, 4, 4, 0],
          ],
          elements: [{ label: 2, type: 'R2D2', connectivity: [1, 2], region: 'panel' }],
        },
      ],
      frame: {
        time: 1,
        displacements: {
          'WS-1': [
            [1, 0, 0, 0],
            [2, 0, 0, 0],
            [3, 0, 0, 0],
            [4, 0, 0, 0],
          ],
          'PANEL-1': [
            [1, 0, -2, 0],
            [2, 0, -2, 0],
          ],
        },
      },
      bounds: [0, 4, 0, 4, 0, 0],
    },
    deformed: true,
    deformationScale: 1,
    resultComponent: 'magnitude',
    resultRange: 0.5,
    resultMin: 0,
    elementValues: { 'WS-1': { 1: 0.1 } },
    ...overrides,
  }
}

function surface(scene: ReturnType<typeof makeScene>, instance: string, kind: string) {
  return scene.surfaces.find((item) => item.instance === instance && item.kind === kind)!
}

test('a stress-free rigid panel moves in Mises and U while contouring stays separate', () => {
  // Mises present for WS-1 only; PANEL-1 has valid nodal U but no stress.
  const scene = makeScene(props())
  const edge = surface(scene, 'PANEL-1', 'edge')
  expect(edge.points.map((point) => point[1])).toEqual([2, 2])
  expect(edge.contour).toBe(false)
  // The deformable seal carries the contour.
  const face = surface(scene, 'WS-1', 'face')
  expect(face.contour).toBe(true)
  expect(face.points.map((point) => point[1])).toEqual([0, 0, 4, 4])

  // Node markers use the same measured U; the old code left them behind.
  const markers = makeScene(props({ nodeMarkers: true })).surfaces.find(
    (item) => item.instance === 'PANEL-1' && item.kind === 'points',
  )!
  expect(markers.points.map((point) => point[1])).toEqual([2, 2])
  // Instance-qualified labels survive even with duplicate local node labels.
  expect(markers.nodeIds).toEqual([1, 2])
  expect(face.nodeIds).toEqual([1, 2, 3, 4])
})

test('deformation off and scale 2 use the same base coordinates and measured U', () => {
  const off = makeScene(props({ deformed: false }))
  expect(surface(off, 'PANEL-1', 'edge').points.map((point) => point[1])).toEqual([4, 4])
  const twice = makeScene(props({ deformationScale: 2 }))
  expect(surface(twice, 'PANEL-1', 'edge').points.map((point) => point[1])).toEqual([0, 0])
  expect(surface(twice, 'WS-1', 'face').points.map((point) => point[1])).toEqual([0, 0, 4, 4])
})

test('a node without measured U stays at its base position instead of moving', () => {
  const scene = makeScene(
    props({
      results: {
        ...props().results!,
        frame: {
          time: 1,
          displacements: {
            'WS-1': props().results!.frame!.displacements['WS-1'],
            'PANEL-1': [[1, 0, -2, 0]],
          },
        },
      },
    }),
  )
  const edge = surface(scene, 'PANEL-1', 'edge')
  expect(edge.points.map((point) => point[1])).toEqual([2, 4])
})

test('true zero stress is measured zero; absent stress is neutral and unavailable', () => {
  const zero = makeScene(props({ elementValues: { 'WS-1': { 1: 0 } } }))
  const measured = surface(zero, 'WS-1', 'face')
  expect(measured.contour).toBe(true)
  expect(measured.magnitudes).toEqual([0, 0, 0, 0])
  const absent = makeScene(props({ elementValues: {} }))
  const neutral = surface(absent, 'WS-1', 'face')
  expect(neutral.contour).toBe(false)
  expect(neutral.color).toBe('#a3a9ae')
  // The rigid panel keeps a legible neutral stroke in the same view.
  expect(surface(absent, 'PANEL-1', 'edge').color).toBe('#a3a9ae')
})

test('picking resolves the instance-qualified node at the deformed position', () => {
  const scene = makeScene(props())
  const projected = scene.surfaces.map((item) => ({
    surface: item,
    points: item.points,
  }))
  // PANEL-1 node 1 sits at (0, 2) after U2 = -2; WS-1 also has a node 1 at (0, 0).
  const hit = pickAt(projected, 'node', 0, 2)
  expect(hit).toMatchObject({ kind: 'node', instance: 'PANEL-1', label: 1 })
  expect(hit?.id).toBe('PANEL-1:1')
})

test('one saturated palette is shared by the legend and the actor colours', () => {
  expect(ramp).toEqual([
    [23, 69, 230],
    [0, 185, 242],
    [8, 184, 79],
    [255, 212, 0],
    [227, 38, 33],
  ])
})
