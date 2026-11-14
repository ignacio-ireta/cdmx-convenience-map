// Locator inset: the city's scored areas drawn as one small SVG mesh, so the
// sidebar can show where the selected area sits once the main map has zoomed in.
// Pure geometry, no app state.

import type { Geometry, Position } from 'geojson'
import type { AreaFeatureCollection } from '../types'

export type Locator = {
  width: number
  height: number
  /** Every area outline as a single SVG path. */
  mesh: string
  project: (lon: number, lat: number) => [number, number]
  /** One geometry's outline in the same coordinate space. */
  outline: (geometry: Geometry) => string
}

// Path coordinates snap to a quarter of an SVG unit. At inset size that is well
// below a device pixel, and it collapses most vertices of a detailed boundary.
const GRID = 4

function ringsOf(geometry: Geometry): Position[][] {
  if (geometry.type === 'Polygon') return geometry.coordinates
  if (geometry.type === 'MultiPolygon') return geometry.coordinates.flat()
  return []
}

function snap(value: number) {
  return Math.round(value * GRID) / GRID
}

/**
 * Fit the collection into a `box` x `box` square, keeping its aspect ratio.
 *
 * Uses an equirectangular projection scaled by the cosine of the mid latitude:
 * accurate to well under a pixel at city extent, which is all an inset needs.
 * Returns null when the collection has no polygon extent to draw.
 */
export function buildLocator(
  collection: AreaFeatureCollection,
  box = 132,
  pad = 3,
): Locator | null {
  let minLon = Infinity
  let maxLon = -Infinity
  let minLat = Infinity
  let maxLat = -Infinity
  for (const feature of collection.features) {
    if (!feature.geometry) continue
    for (const ring of ringsOf(feature.geometry)) {
      for (const [lon, lat] of ring) {
        if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue
        if (lon < minLon) minLon = lon
        if (lon > maxLon) maxLon = lon
        if (lat < minLat) minLat = lat
        if (lat > maxLat) maxLat = lat
      }
    }
  }
  if (!(maxLon > minLon) || !(maxLat > minLat)) return null

  const lonScale = Math.cos((((minLat + maxLat) / 2) * Math.PI) / 180)
  const spanX = (maxLon - minLon) * lonScale
  const spanY = maxLat - minLat
  const scale = (box - 2 * pad) / Math.max(spanX, spanY)
  const width = snap(spanX * scale + 2 * pad)
  const height = snap(spanY * scale + 2 * pad)

  const project = (lon: number, lat: number): [number, number] => [
    snap(pad + (lon - minLon) * lonScale * scale),
    snap(pad + (maxLat - lat) * scale),
  ]

  const ringPath = (ring: Position[]) => {
    const points: string[] = []
    let lastX = Number.NaN
    let lastY = Number.NaN
    for (const [lon, lat] of ring) {
      const [x, y] = project(lon, lat)
      if (x === lastX && y === lastY) continue
      points.push(`${x} ${y}`)
      lastX = x
      lastY = y
    }
    // A closed ring repeats its first point; drop it so `Z` does the closing.
    if (points.length > 1 && points[0] === points[points.length - 1]) points.pop()
    return points.length < 3 ? '' : `M${points.join('L')}Z`
  }

  const outline = (geometry: Geometry) => ringsOf(geometry).map(ringPath).join('')

  return {
    width,
    height,
    mesh: collection.features
      .map((feature) => (feature.geometry ? outline(feature.geometry) : ''))
      .join(''),
    project,
    outline,
  }
}
