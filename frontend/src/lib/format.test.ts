import { describe, expect, it } from 'vitest'
import {
  colorForScore,
  formatDistanceAndTime,
  formatMeters,
  formatMinutes,
  formatPercent,
  formatSource,
  formatTransitComplexity,
  numberFrom,
  optionalString,
  scoreText,
  stringFrom,
  transitStopLabel,
  verdict,
} from './format'

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
    expect(formatSource('seed')).toBe('seed fallback')
    expect(formatSource(undefined)).toBe('unknown')
    expect(formatSource('something-new')).toBe('something-new')
  })

  it('labels transit stops and complexity', () => {
    expect(transitStopLabel('Metro', 'Pino Suárez', 'L2')).toBe('Metro L2 Pino Suárez')
    expect(transitStopLabel(undefined, undefined)).toBe('n/a')
    expect(formatTransitComplexity('same_line')).toBe('Same line')
    expect(formatTransitComplexity('different_system')).toBe('Different systems')
  })
})
