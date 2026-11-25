import { describe, expect, it } from 'vitest'
import { DEFAULT_WEIGHTS } from '../constants'
import type { WeightKey } from '../types'
import { props } from '../test/fixtures'
import {
  getGymScore,
  getScore,
  getTransitAccessDistance,
  getTransitAccessNearestName,
  getTransitAccessScore,
  getTransitAccessSource,
  hasTransitCommute,
  scoreModeSummary,
  selectedStoreLabel,
  selectedTransitLabel,
  weightSummary,
} from './scoring'
import { CITY_CONFIGS, STORE_OPTIONS } from '../constants'
import { collection } from '../test/fixtures'
import { buildPreferenceScoreModel } from './score-math'

const NO_WEIGHT: Record<WeightKey, number> = {
  work: 0,
  transit: 0,
  supermarkets: 0,
  gyms: 0,
  safety: 0,
}

describe('getGymScore', () => {
  it('reads the distance or time score and falls back appropriately', () => {
    expect(getGymScore(props({ score_gyms: 50 }), 'distance')).toBe(50)
    expect(getGymScore(props({ score_gyms_time: 70, score_gyms: 50 }), 'time')).toBe(70)
    expect(getGymScore(props({ score_gyms: 50 }), 'time')).toBe(50)
    expect(getGymScore(props({}), 'distance')).toBe(0)
  })
})

describe('getScore', () => {
  it('returns the precomputed field for a single non-combined metric', () => {
    const score = getScore(
      props({ score_safety: 42 }),
      'safety',
      DEFAULT_WEIGHTS,
      null,
      'distance',
      'distance',
      'distance',
      null,
      [],
      [],
    )
    expect(score).toBe(42)
  })

  it('falls back to the default combined score when all weights are zero', () => {
    const score = getScore(
      props({ score_combined_default: 55 }),
      'combined',
      NO_WEIGHT,
      null,
      'distance',
      'distance',
      'distance',
      null,
      [],
      [],
    )
    expect(score).toBe(55)
  })

  it('computes a weighted average across metrics', () => {
    // work 100 * 0.5 + transit 50 * 0.5 = 75
    const score = getScore(
      props({ score_work: 100, score_transit: 50 }),
      'combined',
      { work: 50, transit: 50, supermarkets: 0, gyms: 0, safety: 0 },
      null,
      'distance',
      'distance',
      'distance',
      null,
      [],
      [],
    )
    expect(score).toBeCloseTo(75, 6)
  })
})

describe('label + summary helpers', () => {
  it('labels selected stores and transit access', () => {
    expect(selectedStoreLabel(STORE_OPTIONS, ['costco'])).toBe('Costco')
    expect(selectedStoreLabel(STORE_OPTIONS, [])).toBe('No stores')
    expect(selectedTransitLabel(['metro', 'metrobus'])).toBe('Metro, Metrobús')
    expect(selectedTransitLabel([])).toBe('No transit')
  })

  it('detects transit commute availability', () => {
    expect(hasTransitCommute(props({ time_work_transit_min: 30 }))).toBe(true)
    expect(hasTransitCommute(props({ transit_commute_source: 'apimetro' }))).toBe(true)
    expect(hasTransitCommute(props({}))).toBe(false)
  })

  it('summarizes weights and score modes', () => {
    expect(weightSummary({ work: 50, transit: 50, supermarkets: 0, gyms: 0, safety: 0 })).toContain(
      'Work 50 (50%)',
    )
    expect(scoreModeSummary('gyms', 'distance', 'distance', 'time', STORE_OPTIONS, [], [])).toBe(
      'Gyms scored by time',
    )
  })
})

describe('city transit options', () => {
  const guadalajara = CITY_CONFIGS.guadalajara
  const area = props({
    area_id: 'g1',
    dist_transit_m: 120,
    nearest_transit_name: 'Parada 1',
    nearest_transit_source: 'setran_gtfs',
    score_transit: 64,
    dist_mitren_transit_m: 850,
    score_transit_mitren: 72,
    nearest_mitren_transit_name: 'Juárez',
    nearest_mitren_transit_source: 'setran_gtfs',
    dist_mimacro_transit_m: 400,
    score_transit_mimacro: 81,
    nearest_mimacro_transit_name: 'Normal',
    nearest_mimacro_transit_source: 'setran_gtfs',
  })

  it('labels the selected systems from the city options (CDMX stays the default)', () => {
    expect(selectedTransitLabel(['mitren', 'mimacro'], guadalajara.transit)).toBe(
      'Mi Tren, Mi Macro',
    )
    expect(selectedTransitLabel(['metro', 'brt'], CITY_CONFIGS.monterrey.transit)).toBe(
      'Metrorrey, TransMetro BRT',
    )
    // A Guadalajara key means nothing against the CDMX defaults.
    expect(selectedTransitLabel(['mitren'])).toBe('No transit')
    expect(selectedTransitLabel(['metro'])).toBe('Metro')
  })

  it("reads a single selected system's distance, nearest stop and source", () => {
    expect(getTransitAccessDistance(area, ['mitren'], guadalajara.transit)).toBe(850)
    expect(getTransitAccessNearestName(area, ['mimacro'], guadalajara.transit)).toBe('Normal')
    expect(getTransitAccessSource(area, ['mitren'], guadalajara.transit)).toBe('setran_gtfs')
    // Several systems selected: the all-systems nearest stop.
    expect(getTransitAccessDistance(area, ['mitren', 'mimacro'], guadalajara.transit)).toBe(120)
    expect(getTransitAccessNearestName(area, ['mitren', 'mimacro'], guadalajara.transit)).toBe(
      'Parada 1',
    )
    // With the CDMX defaults an unknown key falls back to the all-systems fields.
    expect(getTransitAccessDistance(area, ['mitren'])).toBe(120)
  })

  it("falls back to the single selected system's server score from the city options", () => {
    expect(getTransitAccessScore(area, null, ['mimacro'], guadalajara.transit)).toBe(81)
    expect(getTransitAccessScore(area, null, ['mimacro'])).toBe(64)
    expect(getTransitAccessScore(area, null, ['mitren', 'mimacro'], guadalajara.transit)).toBe(64)
  })

  it("averages the selected systems' client scores in the combined score", () => {
    const data = collection([
      { area_id: 'g1', dist_mitren_transit_m: 0, dist_mimacro_transit_m: 900 },
      { area_id: 'g2', dist_mitren_transit_m: 600, dist_mimacro_transit_m: 300 },
      { area_id: 'g3', dist_mitren_transit_m: 900, dist_mimacro_transit_m: 0 },
    ])
    const model = buildPreferenceScoreModel(data, guadalajara.stores, guadalajara.transit)
    const transitOnly = { work: 0, transit: 100, supermarkets: 0, gyms: 0, safety: 0 }
    const score = getScore(
      props({ area_id: 'g1', score_transit: 5 }),
      'combined',
      transitOnly,
      null,
      'distance',
      'distance',
      'distance',
      model,
      [],
      ['mitren'],
      guadalajara.transit,
    )
    expect(score).toBe(100)
    // A model built from the CDMX defaults has no Guadalajara systems: server score.
    const cdmxModel = buildPreferenceScoreModel(data)
    expect(
      getScore(
        props({ area_id: 'g1', score_transit: 5 }),
        'transit',
        transitOnly,
        null,
        'distance',
        'distance',
        'distance',
        cdmxModel,
        [],
        ['mitren'],
      ),
    ).toBe(5)
  })

  it('summarizes the score mode with city labels', () => {
    expect(
      scoreModeSummary(
        'transit',
        'distance',
        'distance',
        'distance',
        guadalajara.stores,
        [],
        ['mitren'],
        guadalajara.transit,
      ),
    ).toBe('Transit access scored by Mi Tren')
    expect(
      scoreModeSummary(
        'combined',
        'driving',
        'time',
        'distance',
        guadalajara.stores,
        ['aurrera'],
        ['mitren', 'mimacro'],
        guadalajara.transit,
      ),
    ).toBe(
      'Combined score using work driving, transit Mi Tren, Mi Macro, stores time (Bodega Aurrerá), gyms distance',
    )
  })
})
