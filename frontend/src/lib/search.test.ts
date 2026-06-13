import { describe, expect, it } from 'vitest'
import { props } from '../test/fixtures'
import {
  areaResultLabel,
  areaUnitLabel,
  getAreaSearchRank,
  normalizeSearchText,
  toggleRequiredSelection,
} from './search'

describe('normalizeSearchText', () => {
  it('strips accents, lowercases, and collapses punctuation', () => {
    expect(normalizeSearchText('Metrobús')).toBe('metrobus')
    expect(normalizeSearchText('Álvaro Obregón!!')).toBe('alvaro obregon')
    expect(normalizeSearchText('  Roma   Norte  ')).toBe('roma norte')
  })
})

describe('labels', () => {
  it('labels area units', () => {
    expect(areaUnitLabel('postal_code')).toBe('Postal code')
    expect(areaUnitLabel('colonia')).toBe('Colonia')
  })

  it('builds a postal result label with alcaldia', () => {
    const label = areaResultLabel(props({ postal_code: '06700', alcaldia: 'Cuauhtémoc' }))
    expect(label).toBe('CP 06700 — Cuauhtémoc')
  })
})

describe('getAreaSearchRank', () => {
  it('ranks an exact postal-code match highest', () => {
    const rank = getAreaSearchRank(props({ postal_code: '06700' }), 'something', '06700')
    expect(rank).toBe(0)
  })

  it('ranks exact, prefix, token-prefix, and substring matches', () => {
    const p = props({ area_unit: 'colonia', area_name: 'Roma Norte', area_id: 'Roma Norte' })
    expect(getAreaSearchRank(p, 'roma norte', '')).toBe(1)
    expect(getAreaSearchRank(p, 'roma', '')).toBe(2)
    expect(getAreaSearchRank(p, 'nort', '')).toBe(3)
    expect(getAreaSearchRank(p, 'zzz', '')).toBeNull()
  })
})

describe('toggleRequiredSelection', () => {
  it('adds, removes, but keeps at least one selection', () => {
    expect(toggleRequiredSelection(['a', 'b'], 'a')).toEqual(['b'])
    expect(toggleRequiredSelection(['a'], 'a')).toEqual(['a'])
    expect(toggleRequiredSelection(['a'], 'b')).toEqual(['a', 'b'])
  })
})
