import { expect, test } from './fixtures'
import {
  elementDisplayValues,
  misesFrom,
  stressCells,
  type FieldFrame,
} from '../src/features/run/fields'

/**
 * Gate E: instance-qualified cells, max-IP display policy, label-aware Mises
 * and missing-vs-measured-zero. These are the pure functions the Results view
 * uses for colouring and probing.
 */
test('duplicate element labels across instances stay separate', () => {
  const frame = {
    fields: {
      Mises: {
        values: [
          { instance: 'WS-1', element: 1, integration_point: 1, data: [0.2] },
          { instance: 'WS-1', element: 1, integration_point: 2, data: [0.5] },
          { instance: 'PANEL-1', element: 1, integration_point: 1, data: [0.9] },
        ],
      },
    },
  } as FieldFrame
  const cells = stressCells(frame, 'mises')
  expect([...cells.keys()].sort()).toEqual(['PANEL-1:1', 'WS-1:1'])
  expect(cells.get('WS-1:1')!.samples.map((sample) => sample.value)).toEqual([0.2, 0.5])
  expect(cells.get('PANEL-1:1')!.samples[0].value).toBe(0.9)
  // The declared display policy is the maximum integration-point value.
  expect(elementDisplayValues(cells, 'mises')).toEqual({
    'WS-1': { 1: 0.5 },
    'PANEL-1': { 1: 0.9 },
  })
})

test('Mises derives from present labels and missing components are not zero', () => {
  expect(misesFrom(['S11', 'S22', 'S33', 'S12'], [1, 0, 0, 0])).toBeCloseTo(1, 12)
  expect(misesFrom(['S11', 'S22', 'S12'], [1, 0, 0])).toBeCloseTo(1, 12)
  expect(misesFrom(['S11', 'S22', 'S12'], [-1, 1, 0])).toBeCloseTo(Math.sqrt(3), 12)
  expect(misesFrom(['S12'], [0])).toBeNull()
  expect(misesFrom([], [])).toBeNull()

  const frame = {
    fields: {
      S: {
        components: ['S11', 'S22', 'S12'],
        values: [
          { instance: 'WS-1', element: 7, integration_point: 1, data: [1, 0, 0] },
          { instance: 'WS-1', element: 7, integration_point: 2, data: [0, 0, 0] },
          { instance: 'WS-1', element: 8, integration_point: 1, data: [2, 2, 0] },
        ],
      },
    },
  } as FieldFrame
  const cells = stressCells(frame, 'mises')
  expect(cells.get('WS-1:7')!.samples.map((sample) => sample.value)).toEqual([1, 0])
  expect(cells.get('WS-1:8')!.samples[0].value).toBeCloseTo(2, 12)
})

test('component colour uses magnitude while the probe keeps the signed sample', () => {
  const frame = {
    fields: {
      S: {
        components: ['S11', 'S22', 'S12'],
        values: [
          { instance: 'WS-1', element: 3, integration_point: 1, data: [-1.2, 0, 0] },
          { instance: 'WS-1', element: 3, integration_point: 2, data: [0.4, 0, 0] },
        ],
      },
    },
  } as FieldFrame
  const cells = stressCells(frame, 'S11')
  expect(cells.get('WS-1:3')!.samples.map((sample) => sample.value)).toEqual([-1.2, 0.4])
  expect(elementDisplayValues(cells, 'S11')).toEqual({ 'WS-1': { 3: 1.2 } })
})

test('a missing field entry does not fabricate a cell', () => {
  const frame = {
    fields: {
      S: {
        components: ['S11', 'S22'],
        values: [
          { instance: 'WS-1', data: [1, 0] },
          { element: 4, data: [1, 0] },
          { instance: 'WS-1', element: 5, data: [1] },
        ],
      },
    },
  } as FieldFrame
  const cells = stressCells(frame, 'S11')
  expect(cells.size).toBe(1)
  expect(cells.get('WS-1:5')!.samples[0].value).toBe(1)
})
