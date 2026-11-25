import { afterEach, describe, expect, it, vi } from 'vitest'
import { CITY_CONFIGS, DATA_ASSETS } from '../constants'
import type { MatrixIndex } from '../types'
import { fetchRoutedWorkTimes, loadMatrixIndex, resolveMatrixAssetUrl } from './routingMatrix'

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

describe('resolveMatrixAssetUrl', () => {
  const page = 'https://example.org/convenience-map/?city=monterrey'

  it("resolves a city's binaries next to that city's index", () => {
    expect(
      resolveMatrixAssetUrl(
        './data/monterrey/routing_matrix_postal_code_index.json',
        'routing_matrix_postal_code_driving_0123456789ab.bin',
        page,
      ),
    ).toBe(
      'https://example.org/convenience-map/data/monterrey/routing_matrix_postal_code_driving_0123456789ab.bin',
    )
  })

  it("keeps CDMX's binaries under the flat data/ directory", () => {
    expect(resolveMatrixAssetUrl('./data/routing_matrix_colonia_index.json', 'm.bin', page)).toBe(
      'https://example.org/convenience-map/data/m.bin',
    )
    expect(
      resolveMatrixAssetUrl('/data/routing_matrix_postal_code_index.json', 'm.bin', page),
    ).toBe('https://example.org/data/m.bin')
  })

  it("refuses names that leave the index's directory", () => {
    const index = './data/monterrey/routing_matrix_postal_code_index.json'
    expect(resolveMatrixAssetUrl(index, '../cdmx/m.bin', page)).toBeNull()
    expect(resolveMatrixAssetUrl(index, '/m.bin', page)).toBeNull()
    expect(resolveMatrixAssetUrl(index, 'https://elsewhere.example/m.bin', page)).toBeNull()
  })
})

describe('loadMatrixIndex', () => {
  function stubIndexFetch(payload: unknown, ok = true) {
    const fetchSpy = vi.fn(async (url: string) => {
      void url
      return { ok, json: async () => payload }
    })
    vi.stubGlobal('fetch', fetchSpy)
    return fetchSpy
  }

  it("fetches the city's own index URL and caches it by URL", async () => {
    const url = CITY_CONFIGS.monterrey.assets.matrixIndex.postal_code
    const fetchSpy = stubIndexFetch(makeIndex({ inputs_hash: 'mty' }))
    const first = await loadMatrixIndex(url)
    const second = await loadMatrixIndex(url)
    expect(first?.inputs_hash).toBe('mty')
    expect(second).toBe(first)
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    expect(fetchSpy).toHaveBeenCalledWith(url)
  })

  it('keeps cities apart: same unit, different URL, different index', async () => {
    const fetchSpy = stubIndexFetch(makeIndex({ inputs_hash: 'gdl' }))
    const gdl = await loadMatrixIndex(CITY_CONFIGS.guadalajara.assets.matrixIndex.postal_code)
    expect(gdl?.inputs_hash).toBe('gdl')
    expect(fetchSpy).toHaveBeenCalledWith(
      `${import.meta.env.BASE_URL}data/guadalajara/routing_matrix_postal_code_index.json`,
    )
  })

  it('returns null (and caches the miss) when the index is absent or malformed', async () => {
    const fetchSpy = stubIndexFetch(null, false)
    const url = `${import.meta.env.BASE_URL}data/absent/routing_matrix_postal_code_index.json`
    expect(await loadMatrixIndex(url)).toBeNull()
    expect(await loadMatrixIndex(url)).toBeNull()
    expect(fetchSpy).toHaveBeenCalledTimes(1)

    stubIndexFetch({ area_ids: 'not-a-list' })
    expect(
      await loadMatrixIndex(
        `${import.meta.env.BASE_URL}data/bad/routing_matrix_colonia_index.json`,
      ),
    ).toBeNull()
  })
})

describe('fetchRoutedWorkTimes with a city index', () => {
  it("Range-fetches the binaries from the city's directory", async () => {
    const fetchSpy = vi.fn(async (url: string) => {
      void url
      return { status: 206, arrayBuffer: async () => bytesFromDeci([0, 25]) }
    })
    vi.stubGlobal('fetch', fetchSpy)
    const indexUrl = CITY_CONFIGS.guadalajara.assets.matrixIndex.postal_code
    const result = await fetchRoutedWorkTimes(makeIndex({ inputs_hash: 'h-gdl' }), 'A', indexUrl)
    expect(result!.walking.get('B')).toBeCloseTo(2.5, 5)
    const urls = fetchSpy.mock.calls.map(([url]) => url)
    expect(urls).toHaveLength(3)
    for (const url of urls) {
      expect(url).toMatch(/\/data\/guadalajara\/[dwb]\.bin$/)
    }
  })

  it("defaults to CDMX's flat data/ directory for the index's unit", async () => {
    const fetchSpy = vi.fn(async (url: string) => {
      void url
      return { status: 206, arrayBuffer: async () => bytesFromDeci([0, 25]) }
    })
    vi.stubGlobal('fetch', fetchSpy)
    await fetchRoutedWorkTimes(makeIndex({ inputs_hash: 'h-cdmx-default' }), 'A')
    const expected = resolveMatrixAssetUrl(DATA_ASSETS.matrixIndex.postal_code, 'd.bin')
    expect(fetchSpy.mock.calls[0][0]).toBe(expected)
    expect(expected).toMatch(/\/data\/d\.bin$/)
  })
})
