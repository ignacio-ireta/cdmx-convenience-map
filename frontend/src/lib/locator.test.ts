import { describe, expect, it } from 'vitest'
import type { Geometry } from 'geojson'
import type { AreaFeatureCollection } from '../types'
import { props } from '../test/fixtures'
import { buildLocator } from './locator'

function areas(geometries: Geometry[]): AreaFeatureCollection {
  return {
    type: 'FeatureCollection',
    features: geometries.map((geometry, index) => ({
      type: 'Feature',
      geometry,
      properties: props({ area_id: String(index) }),
    })),
  }
}

function square(lon: number, lat: number, size: number): Geometry {
  return {
    type: 'Polygon',
    coordinates: [
      [
        [lon, lat],
        [lon + size, lat],
        [lon + size, lat + size],
        [lon, lat + size],
        [lon, lat],
      ],
    ],
  }
}

describe('buildLocator', () => {
  it('fits the long side to the box and puts north at the top', () => {
    // Two unit squares side by side on the equator: twice as wide as tall.
    const locator = buildLocator(areas([square(0, 0, 1), square(1, 0, 1)]), 100, 0)
    expect(locator).not.toBeNull()
    expect(locator!.width).toBeCloseTo(100, 0)
    expect(locator!.height).toBeCloseTo(50, 0)
    expect(locator!.project(0, 1)).toEqual([0, 0])
    expect(locator!.project(2, 0)[0]).toBeCloseTo(100, 0)
    expect(locator!.project(2, 0)[1]).toBeCloseTo(50, 0)
  })

  it('narrows longitude by the cosine of the latitude', () => {
    // At 60 degrees north a degree of longitude is half a degree of latitude.
    const locator = buildLocator(areas([square(10, 59.5, 1)]), 100, 0)
    expect(locator!.height).toBe(100)
    expect(locator!.width).toBeCloseTo(50, 0)
  })

  it('writes each ring once, closed with Z', () => {
    const locator = buildLocator(areas([square(0, 0, 1)]), 10, 0)
    expect(locator!.mesh).toBe('M0 10L10 10L10 0L0 0Z')
    expect(locator!.outline(square(0, 0, 1))).toBe(locator!.mesh)
  })

  it('draws every polygon of a multipolygon and skips degenerate rings', () => {
    const multi: Geometry = {
      type: 'MultiPolygon',
      coordinates: [
        (square(0, 0, 1) as { coordinates: number[][][] }).coordinates,
        (square(1, 1, 1) as { coordinates: number[][][] }).coordinates,
        // Smaller than the snapping grid: collapses to a point and is dropped.
        (square(0.5, 0.5, 1e-6) as { coordinates: number[][][] }).coordinates,
      ],
    }
    const locator = buildLocator(areas([multi]), 10, 0)
    expect(locator!.mesh.match(/M/g)).toHaveLength(2)
  })

  it('returns null when there is nothing with an extent', () => {
    expect(buildLocator(areas([]))).toBeNull()
    expect(buildLocator(areas([{ type: 'Point', coordinates: [1, 1] }]))).toBeNull()
  })
})
