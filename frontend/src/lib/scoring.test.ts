import { describe, expect, it } from 'vitest'
import { DEFAULT_WEIGHTS } from '../constants'
import type { WeightKey } from '../types'
import { props } from '../test/fixtures'
import {
  getGymScore,
  getScore,
  hasTransitCommute,
  scoreModeSummary,
  selectedStoreLabel,
  selectedTransitLabel,
  weightSummary,
} from './scoring'
import { STORE_OPTIONS } from '../constants'

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
