import { describe, expect, it } from 'vitest'
import {
  colorForScore,
  formatCoordinates,
  formatDistanceAndTime,
  formatMeters,
  formatMinutes,
  formatPercent,
  formatSource,
  formatTransitComplexity,
  isEstimateSource,
  isRoutedSource,
  numberFrom,
  optionalString,
  scoreFigure,
  scoreText,
  sourceBadge,
  stringFrom,
  transitStopLabel,
  verdict,
} from './format'
import { LEGEND_STEPS } from '../constants'

describe('value coercion', () => {
  it('trims strings and stringifies finite numbers', () => {
    expect(stringFrom('  hi ')).toBe('hi')
    expect(stringFrom(42)).toBe('42')
    expect(stringFrom(Number.NaN)).toBe('')
    expect(stringFrom(null)).toBe('')
  })

  it('returns undefined for empty optional strings', () => {
    expect(optionalString('  ')).toBeUndefined()
    expect(optionalString('x')).toBe('x')
  })

  it('parses numbers from numeric strings only', () => {
    expect(numberFrom(3.5)).toBe(3.5)
    expect(numberFrom('3.5')).toBe(3.5)
    expect(numberFrom('abc')).toBeUndefined()
    expect(numberFrom(undefined)).toBeUndefined()
  })
})

describe('formatters', () => {
  it('formats meters with km rollover', () => {
    expect(formatMeters(500)).toBe('500 m')
    expect(formatMeters(1500)).toBe('1.5 km')
    expect(formatMeters(undefined)).toBe('n/a')
    expect(formatMeters(Number.NaN)).toBe('n/a')
  })

  it('formats minutes with hour rollover', () => {
    expect(formatMinutes(30)).toBe('30 min')
    expect(formatMinutes(90)).toBe('1 hr 30 min')
    expect(formatMinutes(undefined)).toBe('n/a')
  })

  it('combines distance and time', () => {
    expect(formatDistanceAndTime(500, 30)).toBe('500 m / 30 min')
  })

  it('rounds score text to one decimal and defaults to 0', () => {
    expect(scoreText(85.67)).toBe('85.7')
    expect(scoreText(undefined)).toBe('0')
  })

  it('formats percentages', () => {
    expect(formatPercent(0.25)).toBe('25%')
  })
})

describe('classifiers', () => {
  it('maps scores to legend colors', () => {
    expect(colorForScore(90)).toBe('#166534')
    expect(colorForScore(72)).toBe('#2f9e44')
    expect(colorForScore(0)).toBe('#d94841')
  })

  it('maps scores to verdicts', () => {
    expect(verdict(80)).toBe('Convenient')
    expect(verdict(60)).toBe('Manageable')
    expect(verdict(10)).toBe('Annoying')
  })

  it('translates known source codes and passes through unknown ones', () => {
    expect(formatSource('apimetro')).toBe('Apimetro')
    expect(formatSource('osm_stop_pair_approximation')).toBe(
      'Approximation from OpenStreetMap transit stops; not schedule-aware',
    )
    expect(formatSource('seed')).toBe('seed fallback')
    expect(formatSource('valhalla_free_flow')).toBe('Valhalla (free-flow)')
    expect(formatSource(undefined)).toBe('unknown')
    expect(formatSource('something-new')).toBe('something-new')
  })

  it('classifies sources as routed, estimate, or neither for the UI badge', () => {
    expect(isRoutedSource('valhalla_free_flow')).toBe(true)
    expect(isRoutedSource('r5py_gtfs_schedule')).toBe(true)
    expect(isRoutedSource('fallback_travel_time')).toBe(false)
    expect(isEstimateSource('fallback_straight_line_estimate')).toBe(true)
    expect(isEstimateSource('apimetro_stop_pair_approximation')).toBe(true)
    expect(isEstimateSource('osm_stop_pair_approximation')).toBe(true)
    expect(isEstimateSource('valhalla_free_flow')).toBe(false)
    expect(sourceBadge('valhalla_free_flow')).toBe('routed')
    expect(sourceBadge('fallback_travel_time')).toBe('estimate')
    expect(sourceBadge('fgj_cdmx_victimas')).toBeNull()
  })

  it('labels transit stops and complexity', () => {
    expect(transitStopLabel('Metro', 'Pino Suárez', 'L2')).toBe('Metro L2 Pino Suárez')
    expect(transitStopLabel(undefined, undefined)).toBe('n/a')
    expect(formatTransitComplexity('same_line')).toBe('Same line')
    expect(formatTransitComplexity('different_system')).toBe('Different systems')
  })
})

describe('map furniture figures', () => {
  it('keeps one decimal so score columns align', () => {
    expect(scoreFigure(95)).toBe('95.0')
    expect(scoreFigure(93.64)).toBe('93.6')
    expect(scoreFigure(Number.NaN)).toBe('0.0')
    expect(scoreFigure(undefined)).toBe('0.0')
  })

  it('prints coordinates with hemisphere letters', () => {
    expect(formatCoordinates(59.9139, 10.7522)).toBe('59.9139° N 10.7522° E')
    expect(formatCoordinates(19.4326, -99.1332, 2)).toBe('19.43° N 99.13° W')
    expect(formatCoordinates(-33.9, 18.4, 1)).toBe('33.9° S 18.4° E')
    expect(formatCoordinates(Number.NaN, 0)).toBe('n/a')
  })

  it('draws the legend from the same class breaks the map is coloured with', () => {
    const ascending = [...LEGEND_STEPS].reverse()
    expect(ascending[0].from).toBe(0)
    ascending.forEach((step, index) => {
      expect(colorForScore(step.from)).toBe(step.color)
      const upper = ascending[index + 1]?.from ?? 100
      expect(upper).toBeGreaterThan(step.from)
      expect(colorForScore(upper - 0.01)).toBe(step.color)
    })
  })
})
