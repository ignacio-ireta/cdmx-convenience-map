import { describe, expect, it, vi } from 'vitest'
import { PARTS_INDEX_TYPE, loadAreaCollection, type GeoJsonPartsIndex } from './areaData'

const BASE_HREF = 'https://example.test/app/'
const INDEX_URL = '/app/data/monterrey/scores_colonia_index.json'

function feature(id: string) {
  return {
    type: 'Feature' as const,
    geometry: { type: 'Point' as const, coordinates: [0, 0] },
    properties: { area_id: id },
  }
}

function collection(ids: string[], name = 'part') {
  return { type: 'FeatureCollection', name, features: ids.map(feature) }
}

function partsIndex(parts: { path: string; ids: string[] }[]): GeoJsonPartsIndex {
  return {
    type: PARTS_INDEX_TYPE,
    version: 1,
    area_unit: 'colonia',
    feature_count: parts.reduce((sum, part) => sum + part.ids.length, 0),
    max_part_bytes: 9_000_000,
    parts: parts.map((part) => ({
      path: part.path,
      feature_count: part.ids.length,
      bytes: 1,
      sha256: 'x',
    })),
  }
}

// A fetch stub serving JSON bodies by absolute or page-relative URL.
function fakeFetch(bodies: Record<string, unknown>, status: Record<string, number> = {}) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const code = status[url] ?? (url in bodies ? 200 : 404)
    return new Response(JSON.stringify(bodies[url] ?? null), { status: code })
  }) as unknown as typeof fetch & ReturnType<typeof vi.fn>
}

const PART_1 = 'https://example.test/app/data/monterrey/scores_colonia.part-01.geojson'
const PART_2 = 'https://example.test/app/data/monterrey/scores_colonia.part-02.geojson'

describe('loadAreaCollection', () => {
  it('returns a single FeatureCollection as it is', async () => {
    const body = collection(['A', 'B'], 'scores_postal_code')
    const fetchImpl = fakeFetch({ '/app/data/oslo/scores_postal_code.geojson': body })
    await expect(
      loadAreaCollection('/app/data/oslo/scores_postal_code.geojson', fetchImpl, BASE_HREF),
    ).resolves.toEqual(body)
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('joins the parts of an index in index order, resolved beside the index', async () => {
    const index = partsIndex([
      { path: 'scores_colonia.part-01.geojson', ids: ['A', 'B'] },
      { path: 'scores_colonia.part-02.geojson', ids: ['C'] },
    ])
    const fetchImpl = fakeFetch({
      [INDEX_URL]: index,
      [PART_1]: collection(['A', 'B']),
      [PART_2]: collection(['C']),
    })
    const result = await loadAreaCollection(INDEX_URL, fetchImpl, BASE_HREF)
    expect(result.type).toBe('FeatureCollection')
    expect(result.features.map((item) => item.properties?.area_id)).toEqual(['A', 'B', 'C'])
    expect(fetchImpl.mock.calls.map(([url]) => String(url))).toEqual([INDEX_URL, PART_1, PART_2])
  })

  it('rejects a part path that leaves the index directory', async () => {
    const index = partsIndex([{ path: '../oslo/scores_postal_code.geojson', ids: ['A'] }])
    const fetchImpl = fakeFetch({ [INDEX_URL]: index })
    await expect(loadAreaCollection(INDEX_URL, fetchImpl, BASE_HREF)).rejects.toThrow(
      'outside its index directory',
    )
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('rejects a part whose feature count differs from the index', async () => {
    const index = partsIndex([
      { path: 'scores_colonia.part-01.geojson', ids: ['A', 'B'] },
      { path: 'scores_colonia.part-02.geojson', ids: ['C'] },
    ])
    const fetchImpl = fakeFetch({
      [INDEX_URL]: index,
      [PART_1]: collection(['A']),
      [PART_2]: collection(['C']),
    })
    await expect(loadAreaCollection(INDEX_URL, fetchImpl, BASE_HREF)).rejects.toThrow(
      'has 1 features, expected 2',
    )
  })

  it('rejects an index whose total does not match its parts', async () => {
    const index = { ...partsIndex([{ path: 'scores_colonia.part-01.geojson', ids: ['A'] }]) }
    index.feature_count = 5
    const fetchImpl = fakeFetch({ [INDEX_URL]: index, [PART_1]: collection(['A']) })
    await expect(loadAreaCollection(INDEX_URL, fetchImpl, BASE_HREF)).rejects.toThrow(
      'hold 1 features, expected 5',
    )
  })

  it('rejects a part that is not a FeatureCollection', async () => {
    const index = partsIndex([{ path: 'scores_colonia.part-01.geojson', ids: ['A'] }])
    const fetchImpl = fakeFetch({ [INDEX_URL]: index, [PART_1]: { type: 'Feature' } })
    await expect(loadAreaCollection(INDEX_URL, fetchImpl, BASE_HREF)).rejects.toThrow(
      'is not a FeatureCollection',
    )
  })

  it('reports a failed index or part request with its status', async () => {
    await expect(
      loadAreaCollection(INDEX_URL, fakeFetch({}, { [INDEX_URL]: 404 }), BASE_HREF),
    ).rejects.toThrow('GeoJSON request failed: 404')
    const index = partsIndex([{ path: 'scores_colonia.part-01.geojson', ids: ['A'] }])
    await expect(
      loadAreaCollection(INDEX_URL, fakeFetch({ [INDEX_URL]: index }), BASE_HREF),
    ).rejects.toThrow('GeoJSON request failed: 404')
  })

  it('rejects JSON that is neither a collection nor a parts index', async () => {
    const fetchImpl = fakeFetch({ [INDEX_URL]: { type: 'geojson_parts', version: 2, parts: [] } })
    await expect(loadAreaCollection(INDEX_URL, fetchImpl, BASE_HREF)).rejects.toThrow(
      'neither a FeatureCollection nor a parts index',
    )
  })
})
