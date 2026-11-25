import { describe, expect, it } from 'vitest'
import type { RawAreaFeatureCollection } from '../types'
import { normalizeAreaCollection, normalizeAreaProperties, normalizePostalCode } from './normalize'

describe('normalizePostalCode', () => {
  it('pads to five digits and strips non-digits', () => {
    expect(normalizePostalCode('6700')).toBe('06700')
    expect(normalizePostalCode('CP 06700')).toBe('06700')
    expect(normalizePostalCode('')).toBe('')
  })

  it('truncates overly long inputs to five digits', () => {
    expect(normalizePostalCode('123456')).toBe('12345')
  })
})

describe('normalizeAreaProperties', () => {
  it('derives postal identity from d_cp when area fields are sparse', () => {
    const result = normalizeAreaProperties({ area_unit: 'postal_code', d_cp: '6700' })
    expect(result.area_unit).toBe('postal_code')
    expect(result.postal_code).toBe('06700')
    expect(result.area_id).toBe('06700')
    expect(result.display_name).toBe('CP 06700')
  })

  it('defaults unknown area units to postal_code', () => {
    expect(normalizeAreaProperties({}).area_unit).toBe('postal_code')
  })

  it('uses the area name as the colonia identity', () => {
    const result = normalizeAreaProperties({ area_unit: 'colonia', area_name: 'Roma Norte' })
    expect(result.area_unit).toBe('colonia')
    expect(result.colonia_name).toBe('Roma Norte')
    expect(result.area_id).toBe('Roma Norte')
  })

  it('coerces numeric fields and drops non-numeric ones', () => {
    const result = normalizeAreaProperties({
      area_unit: 'postal_code',
      dist_work_m: '1200',
      score_work: 'x',
    })
    expect(result.dist_work_m).toBe(1200)
    expect(result.score_work).toBeUndefined()
  })
})

describe('Mexican metro area properties', () => {
  it('uses municipio as the municipality when alcaldia is absent', () => {
    expect(normalizeAreaProperties({ d_codigo: '64000', municipio: 'Monterrey' }).alcaldia).toBe(
      'Monterrey',
    )
    expect(
      normalizeAreaProperties({ d_codigo: '64000', alcaldia: 'Guadalupe', municipio: 'Monterrey' })
        .alcaldia,
    ).toBe('Guadalupe')
    expect(normalizeAreaProperties({ d_codigo: '06700' }).alcaldia).toBeUndefined()
  })

  it('keeps the postal label and coerces the statistics-mode safety fields', () => {
    const result = normalizeAreaProperties({
      area_unit: 'postal_code',
      area_id: '64000',
      d_codigo: '64000',
      postal_label: 'Centro, Obrera +6',
      crime_statistics_scope: 'municipality',
      crime_statistics_area: 'Monterrey',
      crime_statistics_period: '2025-10-01/2026-09-30',
      crime_scope_population: '1142994',
      crime_scope_incidents_12m: 41250,
      crime_scope_scored_incidents_12m: 18734,
      crime_rate_per_100k_12m: 1639,
      crime_total_rate_per_100k_12m: 'n/a',
    })
    expect(result.postal_label).toBe('Centro, Obrera +6')
    expect(result.crime_statistics_area).toBe('Monterrey')
    expect(result.crime_statistics_period).toBe('2025-10-01/2026-09-30')
    expect(result.crime_scope_population).toBe(1142994)
    expect(result.crime_rate_per_100k_12m).toBe(1639)
    expect(result.crime_total_rate_per_100k_12m).toBeUndefined()
    // No incident-mode fields are invented for a statistics-mode area.
    expect(result.crime_incidents_recent_12m).toBeUndefined()
    expect(result.crime_density_recent_12m_per_km2).toBeUndefined()
    expect(result.crime_buffer_m).toBeUndefined()
  })

  it('coerces the incident-mode crime buffer', () => {
    expect(normalizeAreaProperties({ area_id: '44100', crime_buffer_m: 250 }).crime_buffer_m).toBe(
      250,
    )
    expect(
      normalizeAreaProperties({ area_id: '44100', crime_buffer_m: '250' }).crime_buffer_m,
    ).toBe(250)
    expect(normalizeAreaProperties({ area_id: '06700' }).crime_buffer_m).toBeUndefined()
  })
})

describe('normalizeAreaCollection', () => {
  it('normalizes every feature and tolerates missing properties', () => {
    const raw: RawAreaFeatureCollection = {
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', geometry: null, properties: { area_unit: 'postal_code', d_cp: '6700' } },
        { type: 'Feature', geometry: null, properties: null as never },
      ],
    }
    const result = normalizeAreaCollection(raw)
    expect(result.features).toHaveLength(2)
    expect(result.features[0].properties.postal_code).toBe('06700')
    expect(result.features[1].properties.area_unit).toBe('postal_code')
  })
})
