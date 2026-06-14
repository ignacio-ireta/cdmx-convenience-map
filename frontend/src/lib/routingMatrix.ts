// Loads the precomputed area-to-area routed travel-time matrix for the
// dynamic-workplace feature. The matrix is published as a destination-major binary
// (deciminutes, little-endian uint16, sentinel = unreachable) with a JSON index
// sidecar; for a chosen workplace we Range-fetch just that destination column.
// Everything degrades gracefully: a missing/!ok asset returns null and the caller
// falls back to the labeled straight-line estimate. See docs/road-routing.md.

import { DATA_ASSETS, matrixAssetUrl } from '../constants'
import type { AreaUnit, MatrixIndex, TravelWorkMode } from '../types'
import { TRAVEL_WORK_MODES } from '../constants'

const indexCache = new Map<AreaUnit, MatrixIndex | null>()
const columnCache = new Map<string, Map<string, number>>()

export async function loadMatrixIndex(areaUnit: AreaUnit): Promise<MatrixIndex | null> {
  if (indexCache.has(areaUnit)) return indexCache.get(areaUnit) ?? null
  let index: MatrixIndex | null = null
  try {
    const response = await fetch(DATA_ASSETS.matrixIndex[areaUnit])
    if (response.ok) index = (await response.json()) as MatrixIndex
  } catch {
    index = null
  }
  indexCache.set(areaUnit, index)
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
 */
export async function fetchRoutedWorkTimes(
  index: MatrixIndex,
  destinationAreaId: string,
): Promise<Record<TravelWorkMode, Map<string, number>> | null> {
  const destinationIndex = index.area_ids.indexOf(destinationAreaId)
  if (destinationIndex < 0) return null

  const result = {} as Record<TravelWorkMode, Map<string, number>>
  for (const mode of TRAVEL_WORK_MODES) {
    const filename = index.mode_files[mode]
    if (!filename) return null
    const cacheKey = `${index.area_unit}:${mode}:${destinationAreaId}:${index.inputs_hash}`
    const cached = columnCache.get(cacheKey)
    if (cached) {
      result[mode] = cached
      continue
    }
    const view = await fetchColumnBytes(matrixAssetUrl(filename), index.n, destinationIndex)
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
