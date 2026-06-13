import { describe, expect, it } from 'vitest'
import { collection } from '../test/fixtures'
import { averageSelectedScores, buildCloserScoreMap, percentile } from './score-math'

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
