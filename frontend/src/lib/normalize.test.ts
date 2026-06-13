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
