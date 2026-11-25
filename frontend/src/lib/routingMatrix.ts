// Loads the precomputed area-to-area routed travel-time matrix for the
// dynamic-workplace feature. The matrix is published as a destination-major binary
// (deciminutes, little-endian uint16, sentinel = unreachable) with a JSON index
// sidecar; for a chosen workplace we Range-fetch just that destination column.
// Everything degrades gracefully: a missing/!ok asset returns null and the caller
// falls back to the labeled straight-line estimate. See docs/road-routing.md.
//
// Each city publishes its own index under data/<city>/ (CDMX: flat data/), so the
// index is addressed by URL and its binaries resolve relative to that URL.

import { DATA_ASSETS, TRAVEL_WORK_MODES } from '../constants'
import type { MatrixIndex, TravelWorkMode } from '../types'

const indexCache = new Map<string, MatrixIndex | null>()
const columnCache = new Map<string, Map<string, number>>()

// What fetch() resolves a relative URL against in the page (the document base
// URL); tests in the node environment have no document.
function defaultBaseHref() {
  return globalThis.document?.baseURI ?? globalThis.location?.href ?? 'http://localhost/'
}

function isMatrixIndex(value: unknown): value is MatrixIndex {
  if (!value || typeof value !== 'object') return false
  const index = value as Partial<MatrixIndex>
  return (
    typeof index.n === 'number' &&
    Array.isArray(index.area_ids) &&
    typeof index.mode_files === 'object' &&
    index.mode_files !== null
  )
}

/**
 * Absolute URL of a matrix binary named in an index, resolved relative to the
 * index's own URL. Returns null for a name that would leave the index's
 * directory (another origin, an absolute path or `../`), since the index is data.
 */
export function resolveMatrixAssetUrl(
  indexUrl: string,
  filename: string,
  baseHref: string = defaultBaseHref(),
): string | null {
  try {
    const indexHref = new URL(indexUrl, baseHref)
    const directory = new URL('.', indexHref).href
    const resolved = new URL(filename, indexHref).href
    return resolved.startsWith(directory) ? resolved : null
  } catch {
    return null
  }
}

/** The matrix index at `indexUrl` (e.g. `city.assets.matrixIndex[unit]`), cached by URL. */
export async function loadMatrixIndex(indexUrl: string): Promise<MatrixIndex | null> {
  if (indexCache.has(indexUrl)) return indexCache.get(indexUrl) ?? null
  let index: MatrixIndex | null = null
  try {
    const response = await fetch(indexUrl)
    if (response.ok) {
      const payload: unknown = await response.json()
      index = isMatrixIndex(payload) ? payload : null
    }
  } catch {
    index = null
  }
  indexCache.set(indexUrl, index)
  return index
}

async function fetchColumnBytes(
  url: string,
  n: number,
  columnIndex: number,
): Promise<DataView | null> {
  const columnBytes = n * 2
  const start = columnIndex * columnBytes
  const end = start + columnBytes - 1
  let buffer: ArrayBuffer
  try {
    const response = await fetch(url, { headers: { Range: `bytes=${start}-${end}` } })
    if (response.status !== 200 && response.status !== 206) return null
    buffer = await response.arrayBuffer()
  } catch {
    return null
  }
  // A 206 returns exactly the column; some CDNs ignore Range and return 200 (the
  // full N*N matrix) — slice the column out in that case.
  if (buffer.byteLength === columnBytes) return new DataView(buffer)
  if (buffer.byteLength === n * columnBytes) return new DataView(buffer, start, columnBytes)
  return null
}

/**
 * Routed travel times (minutes) from every area to ``destinationAreaId`` per mode,
 * keyed by origin area_id. NaN marks an unreachable cell (caller falls back).
 * Returns null when no matrix covers this destination (e.g. cross-unit workplace).
 *
 * ``indexUrl`` is where ``index`` was loaded from; its binaries sit next to it.
 * It defaults to CDMX's index for the unit.
 */
export async function fetchRoutedWorkTimes(
  index: MatrixIndex,
  destinationAreaId: string,
  indexUrl: string = DATA_ASSETS.matrixIndex[index.area_unit],
): Promise<Record<TravelWorkMode, Map<string, number>> | null> {
  const destinationIndex = index.area_ids.indexOf(destinationAreaId)
  if (destinationIndex < 0) return null

  const result = {} as Record<TravelWorkMode, Map<string, number>>
  for (const mode of TRAVEL_WORK_MODES) {
    const filename = index.mode_files[mode]
    if (!filename) return null
    const url = resolveMatrixAssetUrl(indexUrl, filename)
    if (!url) return null
    const cacheKey = `${url}:${index.inputs_hash}:${destinationAreaId}`
    const cached = columnCache.get(cacheKey)
    if (cached) {
      result[mode] = cached
      continue
    }
    const view = await fetchColumnBytes(url, index.n, destinationIndex)
    if (view === null) return null
    const minutes = new Map<string, number>()
    for (let i = 0; i < index.n; i += 1) {
      const raw = view.getUint16(i * 2, true)
      minutes.set(index.area_ids[i], raw === index.sentinel ? Number.NaN : raw / index.scale)
    }
    columnCache.set(cacheKey, minutes)
    result[mode] = minutes
  }
  return result
}
