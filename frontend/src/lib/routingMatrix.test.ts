import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MatrixIndex } from '../types'
import { fetchRoutedWorkTimes } from './routingMatrix'

function makeIndex(overrides: Partial<MatrixIndex> = {}): MatrixIndex {
  return {
    area_unit: 'postal_code',
    n: 2,
    dtype: '<u2',
    scale: 10,
    sentinel: 65535,
    axis0: 'origin',
    axis1: 'destination',
    layout: 'destination_major',
    unit: 'minutes',
    area_ids: ['A', 'B'],
    modes: ['driving', 'walking', 'biking'],
    mode_files: { driving: 'd.bin', walking: 'w.bin', biking: 'b.bin' },
    engine: 'valhalla',
    version: 'test',
    profiles: {},
    inputs_hash: 'hash',
    generated_at: 't',
    ...overrides,
  }
}

function bytesFromDeci(values: number[]): ArrayBuffer {
  const buffer = new ArrayBuffer(values.length * 2)
  const view = new DataView(buffer)
  values.forEach((value, index) => view.setUint16(index * 2, value, true))
  return buffer
}

function stubFetch(status: number, buffer: ArrayBuffer) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ status, arrayBuffer: async () => buffer })),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fetchRoutedWorkTimes', () => {
  it('decodes a 206 destination column into minutes per origin area', async () => {
    // Column for destination 0 = [origin A -> dest0, origin B -> dest0] in deciminutes.
    stubFetch(206, bytesFromDeci([0, 25]))
    const result = await fetchRoutedWorkTimes(makeIndex({ inputs_hash: 'h-206' }), 'A')
    expect(result).not.toBeNull()
    expect(result!.driving.get('A')).toBe(0)
    expect(result!.driving.get('B')).toBeCloseTo(2.5, 5)
  })

  it('maps the sentinel value to NaN (caller falls back)', async () => {
    stubFetch(206, bytesFromDeci([15, 65535]))
    const result = await fetchRoutedWorkTimes(makeIndex({ inputs_hash: 'h-sentinel' }), 'A')
    expect(result!.driving.get('A')).toBeCloseTo(1.5, 5)
    expect(Number.isNaN(result!.driving.get('B') as number)).toBe(true)
  })

  it('slices the column out when a CDN returns 200 with the full matrix', async () => {
    // Full 2x2 destination-major: dest0 col [0, 25], dest1 col [40, 40].
    stubFetch(200, bytesFromDeci([0, 25, 40, 40]))
    const result = await fetchRoutedWorkTimes(makeIndex({ inputs_hash: 'h-200' }), 'A')
    expect(result!.driving.get('A')).toBe(0)
    expect(result!.driving.get('B')).toBeCloseTo(2.5, 5)
  })

  it('returns null when the workplace is not in this unit matrix', async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    const result = await fetchRoutedWorkTimes(makeIndex({ inputs_hash: 'h-missing' }), 'ZZZ')
    expect(result).toBeNull()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('returns null on a failed request (graceful fallback)', async () => {
    stubFetch(404, new ArrayBuffer(0))
    const result = await fetchRoutedWorkTimes(makeIndex({ inputs_hash: 'h-404' }), 'A')
    expect(result).toBeNull()
  })
})
