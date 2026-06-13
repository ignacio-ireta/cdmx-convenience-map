// Test fixtures for the pure-logic unit tests. Excluded from the app build.
import type { AreaFeature, AreaFeatureCollection, AreaProperties } from '../types'

export function props(partial: Partial<AreaProperties> = {}): AreaProperties {
  return {
    area_unit: 'postal_code',
    area_id: partial.area_id ?? '00000',
    area_name: partial.area_name ?? 'Area',
    display_name: partial.display_name ?? 'Area',
    ...partial,
  }
}

export function feature(partial: Partial<AreaProperties> = {}): AreaFeature {
  return {
    type: 'Feature',
    geometry: {
      type: 'Point',
      coordinates: [partial.centroid_lon ?? 0, partial.centroid_lat ?? 0],
    },
    properties: props(partial),
  }
}

export function collection(items: Partial<AreaProperties>[]): AreaFeatureCollection {
  return {
    type: 'FeatureCollection',
    features: items.map((item) => feature(item)),
  }
}
