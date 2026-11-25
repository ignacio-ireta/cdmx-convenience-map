// Loads one area unit's scored GeoJSON. A unit is published either as a single
// FeatureCollection or, when it is too large for one file (Monterrey and
// Guadalajara colonias), as ordered FeatureCollection parts listed by a small
// JSON index (`scores_<unit>_index.json`, written by src/cdmxmap/output/parts.py).
// The parts are fetched in parallel and their features joined in index order,
// which reproduces the single processed file exactly. See docs/data-contract.md.

import type { RawAreaFeatureCollection } from '../types'
import { resolveMatrixAssetUrl } from './routingMatrix'

export const PARTS_INDEX_TYPE = 'geojson_parts'

export type GeoJsonPart = {
  path: string
  feature_count: number
  bytes: number
  sha256: string
}

export type GeoJsonPartsIndex = {
  type: typeof PARTS_INDEX_TYPE
  version: number
  area_unit: string
  feature_count: number
  max_part_bytes: number
  parts: GeoJsonPart[]
}

function isFeatureCollection(value: unknown): value is RawAreaFeatureCollection {
  if (!value || typeof value !== 'object') return false
  const payload = value as { type?: unknown; features?: unknown }
  return payload.type === 'FeatureCollection' && Array.isArray(payload.features)
}

function isPartsIndex(value: unknown): value is GeoJsonPartsIndex {
  if (!value || typeof value !== 'object') return false
  const index = value as Partial<GeoJsonPartsIndex>
  return (
    index.type === PARTS_INDEX_TYPE &&
    index.version === 1 &&
    typeof index.feature_count === 'number' &&
    Array.isArray(index.parts) &&
    index.parts.length > 0 &&
    index.parts.every(
      (part) => typeof part?.path === 'string' && typeof part?.feature_count === 'number',
    )
  )
}

async function fetchJson(url: string, fetchImpl: typeof fetch): Promise<unknown> {
  const response = await fetchImpl(url)
  if (!response.ok) {
    throw new Error(
      `GeoJSON request failed: ${response.status}. Reload the page to get the latest map data.`,
    )
  }
  return response.json()
}

/**
 * The FeatureCollection at `url`, or the parts an index at `url` lists, joined.
 *
 * Part paths resolve relative to the index's own URL and must stay in its
 * directory. A part that is not a FeatureCollection, or whose feature count
 * differs from the index, rejects the whole load rather than showing a map with
 * areas missing.
 */
export async function loadAreaCollection(
  url: string,
  fetchImpl: typeof fetch = fetch,
  baseHref?: string,
): Promise<RawAreaFeatureCollection> {
  const payload = await fetchJson(url, fetchImpl)
  if (isFeatureCollection(payload)) return payload
  if (!isPartsIndex(payload)) {
    throw new Error('Area data is neither a FeatureCollection nor a parts index')
  }

  const partUrls = payload.parts.map((part) => {
    const partUrl = resolveMatrixAssetUrl(url, part.path, baseHref)
    if (!partUrl) throw new Error(`Area data part is outside its index directory: ${part.path}`)
    return partUrl
  })
  const parts = await Promise.all(partUrls.map((partUrl) => fetchJson(partUrl, fetchImpl)))

  const features = parts.flatMap((part, position) => {
    const expected = payload.parts[position]
    if (!isFeatureCollection(part)) {
      throw new Error(`Area data part ${expected.path} is not a FeatureCollection`)
    }
    if (part.features.length !== expected.feature_count) {
      throw new Error(
        `Area data part ${expected.path} has ${part.features.length} features, expected ${expected.feature_count}`,
      )
    }
    return part.features
  })
  if (features.length !== payload.feature_count) {
    throw new Error(
      `Area data parts hold ${features.length} features, expected ${payload.feature_count}`,
    )
  }
  return { type: 'FeatureCollection', features }
}
