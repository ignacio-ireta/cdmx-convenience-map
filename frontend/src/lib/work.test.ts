import { describe, expect, it } from 'vitest'
import { collection, feature, props } from '../test/fixtures'
import type { TravelWorkMode } from '../types'
import {
  buildWorkModel,
  estimateTravelMinutes,
  getWorkScore,
  getWorkSource,
  getWorkTime,
  haversineMeters,
} from './work'

describe('haversineMeters', () => {
  it('is zero for identical points', () => {
    expect(haversineMeters(19.4326, -99.1332, 19.4326, -99.1332)).toBe(0)
  })

  it('is positive and symmetric for distinct points', () => {
    const ab = haversineMeters(19.4326, -99.1332, 19.5, -99.0)
    const ba = haversineMeters(19.5, -99.0, 19.4326, -99.1332)
    expect(ab).toBeGreaterThan(0)
    expect(ab).toBeCloseTo(ba, 6)
  })
})

describe('estimateTravelMinutes', () => {
  it('applies the mode speed and detour factor', () => {
    // 1000 m walking: (1000 * 1.15) / ((4.8 * 1000) / 60) = 14.375 min
    expect(estimateTravelMinutes(1000, 'walking')).toBeCloseTo(14.375, 5)
  })

  it('returns NaN for non-finite distances', () => {
    expect(Number.isNaN(estimateTravelMinutes(Number.NaN, 'driving'))).toBe(true)
  })
})

describe('buildWorkModel', () => {
  const data = collection([
    { area_id: 'work', centroid_lat: 19.43, centroid_lon: -99.13 },
    { area_id: 'near', centroid_lat: 19.44, centroid_lon: -99.14 },
    { area_id: 'far', centroid_lat: 19.6, centroid_lon: -99.3 },
  ])
  const workFeature = feature({ area_id: 'work', centroid_lat: 19.43, centroid_lon: -99.13 })
  const model = buildWorkModel(data, workFeature)

  it('measures zero distance and a perfect score for the work area itself', () => {
    expect(model.distances.get('work')).toBe(0)
    expect(model.scores.get('work')).toBe(100)
  })

  it('keeps every work score within 0..100', () => {
    for (const score of model.scores.values()) {
      expect(score).toBeGreaterThanOrEqual(0)
      expect(score).toBeLessThanOrEqual(100)
    }
  })

  it('exposes per-mode travel times and scores', () => {
    expect(model.travelTimes.driving.get('near')).toBeGreaterThan(0)
    expect(model.travelScores.walking.has('far')).toBe(true)
  })

  it('getWorkScore reads the model in distance mode', () => {
    expect(getWorkScore(props({ area_id: 'work' }), model, 'distance')).toBe(100)
  })

  it('labels travel-mode sources as fallback estimates without a matrix', () => {
    expect(getWorkSource(props({ area_id: 'near' }), model, 'driving')).toBe('fallback_travel_time')
  })
})

describe('buildWorkModel with a routed matrix', () => {
  const data = collection([
    { area_id: 'work', centroid_lat: 19.43, centroid_lon: -99.13 },
    { area_id: 'near', centroid_lat: 19.44, centroid_lon: -99.14 },
    { area_id: 'far', centroid_lat: 19.6, centroid_lon: -99.3 },
  ])
  const workFeature = feature({ area_id: 'work', centroid_lat: 19.43, centroid_lon: -99.13 })
  // 'near' has a genuine routed time; 'far' is unreachable (NaN) -> estimate fallback.
  const routedTimes = Object.fromEntries(
    (['driving', 'walking', 'biking'] as TravelWorkMode[]).map((mode) => [
      mode,
      new Map<string, number>([
        ['work', 0],
        ['near', 7.5],
        ['far', Number.NaN],
      ]),
    ]),
  ) as Record<TravelWorkMode, Map<string, number>>
  const model = buildWorkModel(data, workFeature, routedTimes)

  it('uses the routed time and labels it as routed', () => {
    expect(model.routed).toBe(true)
    expect(model.travelTimes.driving.get('near')).toBe(7.5)
    expect(getWorkSource(props({ area_id: 'near' }), model, 'driving')).toBe('valhalla_free_flow')
  })

  it('falls back to a labeled estimate for an unreachable area', () => {
    const farTime = getWorkTime(props({ area_id: 'far' }), model, 'driving')
    expect(Number.isFinite(farTime as number)).toBe(true) // estimate, not NaN/0
    expect(getWorkSource(props({ area_id: 'far' }), model, 'driving')).toBe('fallback_travel_time')
  })

  it('keeps distance mode straight-line even on a routed model', () => {
    expect(getWorkSource(props({ area_id: 'near' }), model, 'distance')).toBe(
      'area_reference_point',
    )
  })
})
