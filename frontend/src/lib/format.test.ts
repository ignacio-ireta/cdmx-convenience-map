import { readFileSync, readdirSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import type { ScoreMetadata } from '../types'
import {
  colorForScore,
  formatCoordinates,
  formatDistanceAndTime,
  formatMeters,
  formatMinutes,
  formatPercent,
  formatSource,
  formatSourceWithFallback,
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

  it('labels the Monterrey and Guadalajara sources', () => {
    expect(formatSource('nl_stcm_metrorrey')).toBe('STC Metrorrey (NL open data)')
    expect(formatSource('nl_ima')).toBe('IMA Nuevo León')
    expect(formatSource('setran_gtfs')).toBe('SETRAN Jalisco GTFS')
    expect(formatSource('inegi_denue')).toBe('INEGI DENUE')
    expect(formatSource('iieg_jalisco_fge')).toBe('IIEG Jalisco (FGE)')
    expect(formatSource('sesnsp_municipal')).toBe('SESNSP municipal')
    expect(formatSource('inegi_dcah_2025')).toBe('INEGI colonias 2025')
    expect(formatSource('open_mexico_sepomex')).toBe('SEPOMEX (open-mexico)')
    expect(formatSource('nl_open_data_stop_pair_approximation')).toBe(
      'Approximation from Nuevo León open-data stops; not schedule-aware',
    )
    expect(formatSource('setran_gtfs_stop_pair_approximation')).toBe(
      'Approximation from SETRAN GTFS stops; not schedule-aware',
    )
    // Still FGJ for CDMX, and the approximations keep their estimate badge.
    expect(formatSource('fgj_cdmx_victimas')).toBe('FGJ CDMX')
    expect(sourceBadge('nl_open_data_stop_pair_approximation')).toBe('estimate')
    expect(sourceBadge('setran_gtfs_stop_pair_approximation')).toBe('estimate')
    expect(sourceBadge('sesnsp_municipal')).toBeNull()
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
    expect(
      transitStopLabel('MITRANSPORTE', 'Blvrd. Puerta De Hierro', 'C54|C71|C120|T17|T17-1'),
    ).toBe('MITRANSPORTE (C54, C71, C120 +2) Blvrd. Puerta De Hierro')
    expect(transitStopLabel('BUS', 'Av. Juárez', '42|85')).toBe('BUS (42, 85) Av. Juárez')
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

describe('formatSourceWithFallback', () => {
  it('mentions the fallback on a routed build', () => {
    expect(formatSourceWithFallback('valhalla_free_flow', 'fallback_straight_line_estimate')).toBe(
      'Valhalla (free-flow) · fallback estimate where unrouted',
    )
  })

  it('adds nothing when the fallback is absent or the source itself', () => {
    expect(formatSourceWithFallback('valhalla_free_flow')).toBe('Valhalla (free-flow)')
    expect(
      formatSourceWithFallback(
        'fallback_straight_line_estimate',
        'fallback_straight_line_estimate',
      ),
    ).toBe('fallback estimate')
    expect(formatSourceWithFallback(undefined, undefined)).toBe('unknown')
  })

  // The audit rows and copied report of the existing cities read these committed
  // files; their Amenity/Work time labels must not change.
  it('leaves every existing city audit label as formatSource', () => {
    const dataDir = new URL('../../public/data/', import.meta.url)
    const existing = ['', 'morelia/', 'oslo/', 'bergen/', 'trondheim/', 'stavanger/', 'drammen/']
    let checked = 0
    for (const dir of existing) {
      const url = new URL(dir, dataDir)
      for (const name of readdirSync(url).filter((file) => /^score_metadata.*\.json$/.test(file))) {
        const metadata = JSON.parse(readFileSync(new URL(name, url), 'utf8')) as ScoreMetadata
        for (const block of [metadata.travel_time, metadata.amenity_travel_time]) {
          expect(formatSourceWithFallback(block?.source, block?.fallback_source), dir + name).toBe(
            formatSource(block?.source),
          )
        }
        checked += 1
      }
    }
    expect(checked).toBeGreaterThanOrEqual(existing.length)
  })
})
