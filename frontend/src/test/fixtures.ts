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

// A Monterrey-style postal code scored in crime_mode "city_statistics": the
// safety fields describe its municipality, not the area itself.
export function statisticsProps(partial: Partial<AreaProperties> = {}): AreaProperties {
  return props({
    area_id: '64000',
    postal_code: '64000',
    display_name: 'CP 64000',
    alcaldia: 'Monterrey',
    postal_label: 'Centro, Obrera +6',
    mun_code: '19039',
    score_safety: 61.2,
    crime_statistics_scope: 'municipality',
    crime_statistics_area: 'Monterrey',
    crime_statistics_period: '2025-10-01/2026-09-30',
    crime_scope_population: 1142994,
    crime_scope_incidents_12m: 41250,
    crime_scope_scored_incidents_12m: 18734,
    crime_rate_per_100k_12m: 1639.0,
    crime_total_rate_per_100k_12m: 3609.0,
    crime_top_category_recent_12m: 'Robo',
    crime_source: 'sesnsp_municipal',
    ...partial,
  })
}

// A Guadalajara-style postal code scored in incident mode over the area grown by
// crime_source.density_buffer_m (crime_buffer_m on the feature).
export function bufferedIncidentProps(partial: Partial<AreaProperties> = {}): AreaProperties {
  return props({
    area_id: '44100',
    postal_code: '44100',
    display_name: 'CP 44100',
    alcaldia: 'Guadalajara',
    score_safety: 42.5,
    crime_incidents_total: 4821,
    crime_incidents_recent_12m: 339,
    crime_density_recent_12m_per_km2: 151.26,
    crime_top_category_recent_12m: 'Robo a negocio',
    crime_source: 'iieg_jalisco_fge',
    crime_buffer_m: 250,
    ...partial,
  })
}
