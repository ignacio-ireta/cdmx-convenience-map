import { describe, expect, it } from 'vitest'
import { CITY_CONFIGS, STORE_OPTIONS, TRANSIT_ACCESS_OPTIONS } from '../constants'
import { collection } from '../test/fixtures'
import {
  averageSelectedScores,
  buildCloserScoreMap,
  buildPreferenceScoreModel,
  percentile,
} from './score-math'

describe('percentile', () => {
  it('returns the value at the requested fraction', () => {
    expect(percentile([1, 2, 3, 4, 5], 0.95)).toBe(4)
    expect(percentile([10], 0.5)).toBe(10)
  })

  it('defaults to 1 for empty input', () => {
    expect(percentile([], 0.5)).toBe(1)
  })
})

describe('buildCloserScoreMap', () => {
  it('scores closer values higher (100 at zero, 0 at/above the cap)', () => {
    const data = collection([
      { area_id: 'a', dist_gym_m: 0 },
      { area_id: 'b', dist_gym_m: 250 },
      { area_id: 'c', dist_gym_m: 1000 },
      { area_id: 'far', dist_gym_m: 5000 },
    ])
    const map = buildCloserScoreMap(data, 'dist_gym_m')
    expect(map.hasValues).toBe(true)
    expect(map.scores.get('a')).toBe(100) // closest -> best
    expect(map.scores.get('b')).toBeCloseTo(75, 6) // 100 * (1 - 250/1000)
    expect(map.scores.get('c')).toBe(0) // at the cap -> worst
  })

  it('reports no values when the field is entirely missing', () => {
    const data = collection([{ area_id: 'a' }, { area_id: 'b' }])
    expect(buildCloserScoreMap(data, 'dist_gym_m').hasValues).toBe(false)
  })

  it('reports no values when every value is zero (a system with no stops)', () => {
    // The pipeline writes distance 0 for a declared system with no points; scoring
    // that would give every area 100.
    const data = collection([
      { area_id: 'a', dist_rtp_transit_m: 0 },
      { area_id: 'b', dist_rtp_transit_m: 0 },
      { area_id: 'c' },
    ])
    const map = buildCloserScoreMap(data, 'dist_rtp_transit_m')
    expect(map.hasValues).toBe(false)
    expect(map.scores.size).toBe(0)
  })

  it('still scores a field where only some values are zero', () => {
    const data = collection([
      { area_id: 'a', dist_gym_m: 0 },
      { area_id: 'b', dist_gym_m: 400 },
    ])
    const map = buildCloserScoreMap(data, 'dist_gym_m')
    expect(map.hasValues).toBe(true)
    expect(map.scores.get('a')).toBe(100)
  })
})

describe('buildPreferenceScoreModel', () => {
  const monterrey = CITY_CONFIGS.monterrey
  const data = collection([
    { area_id: 'a', dist_metro_transit_m: 0, dist_brt_transit_m: 900, dist_heb_m: 100 },
    { area_id: 'b', dist_metro_transit_m: 500, dist_brt_transit_m: 300, dist_heb_m: 300 },
    { area_id: 'c', dist_metro_transit_m: 1000, dist_brt_transit_m: 0, dist_heb_m: 900 },
  ])

  it('defaults to the CDMX store and transit options', () => {
    const model = buildPreferenceScoreModel(data)
    expect(Object.keys(model.storeDistanceScores)).toEqual(STORE_OPTIONS.map((o) => o.key))
    expect(Object.keys(model.transitAccessScores)).toEqual(TRANSIT_ACCESS_OPTIONS.map((o) => o.key))
  })

  it("builds one transit score map per city system from that city's options", () => {
    const model = buildPreferenceScoreModel(data, monterrey.stores, monterrey.transit)
    expect(Object.keys(model.transitAccessScores)).toEqual(['metro', 'brt', 'transmetro', 'rutas'])
    expect(Object.keys(model.storeDistanceScores)).toEqual(monterrey.stores.map((o) => o.key))

    const metro = model.transitAccessScores.metro
    expect(metro.hasValues).toBe(true)
    expect(metro.scores.get('a')).toBe(100)
    expect(metro.scores.get('c')).toBe(0)
    expect(model.transitAccessScores.brt.scores.get('c')).toBe(100)
    // No values in the data for these systems: not scored, so averaging skips them.
    expect(model.transitAccessScores.transmetro.hasValues).toBe(false)
    expect(model.transitAccessScores.rutas.hasValues).toBe(false)
    expect(model.storeDistanceScores.heb.scores.get('a')).toBeGreaterThan(
      model.storeDistanceScores.heb.scores.get('b') ?? 0,
    )

    // Area a: nearest to Metro (100), at/above the BRT cap (0).
    expect(model.transitAccessScores.brt.scores.get('a')).toBe(0)
    expect(averageSelectedScores('a', ['metro', 'brt'], model.transitAccessScores)).toBe(50)
    // Unscored systems drop out of the average instead of counting as 100.
    expect(
      averageSelectedScores('a', ['metro', 'brt', 'transmetro'], model.transitAccessScores),
    ).toBe(50)
  })
})

describe('averageSelectedScores', () => {
  it('averages only the score maps that have values', () => {
    const scoreMaps = {
      costco: { hasValues: true, scores: new Map([['a', 80]]) },
      walmart: { hasValues: true, scores: new Map([['a', 60]]) },
    }
    expect(averageSelectedScores('a', ['costco', 'walmart'], scoreMaps)).toBe(70)
    expect(averageSelectedScores('a', ['costco'], scoreMaps)).toBe(80)
  })

  it('returns undefined when no selected map has a value', () => {
    const scoreMaps = { costco: { hasValues: false, scores: new Map<string, number>() } }
    expect(averageSelectedScores('a', ['costco'], scoreMaps)).toBeUndefined()
  })
})
