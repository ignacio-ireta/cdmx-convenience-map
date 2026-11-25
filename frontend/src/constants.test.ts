import { existsSync, readFileSync, statSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import {
  CITY_CONFIGS,
  DATA_ASSETS,
  GEOGRAPHIES,
  STORE_OPTIONS,
  TRANSIT_ACCESS_OPTIONS,
  cityDataAssets,
  type CityTheme,
} from './constants'
import { contrastRatio, relativeLuminance, rgbDistance } from './test/contrast'

const BASE = import.meta.env.BASE_URL
const TEXT_INKS: (keyof CityTheme)[] = ['accent', 'accentStrong', 'counter']
const TEXT_GROUNDS: (keyof CityTheme)[] = ['panel', 'canvas', 'accentSoft']
const NEW_MX_CITIES = ['monterrey', 'guadalajara'] as const

type CityProfile = {
  area_units?: (string | { area_unit: string; public_part_max_bytes?: number })[]
  default_weights: Record<string, number>
  transit_systems: { code: string; slug: string; group: string; label: string }[]
  store_brands: { slug: string }[]
  supermarket_classifier: { families: { slug: string; label: string }[] }
  crime_mode: string
}

// The committed backend profile is the contract the frontend config mirrors.
function cityProfile(cityId: string): CityProfile {
  const url = new URL(`../../data/cities/${cityId}/city.json`, import.meta.url)
  return JSON.parse(readFileSync(url, 'utf8')) as CityProfile
}

// Disk path under frontend/public/ of an asset URL (`${BASE}data/...`).
function publicFile(assetUrl: string): URL {
  expect(assetUrl.startsWith(BASE), assetUrl).toBe(true)
  return new URL(`../public/${assetUrl.slice(BASE.length)}`, import.meta.url)
}

// The repository's pre-commit check-added-large-files limit, in bytes.
function preCommitMaxBytes(): number {
  const config = readFileSync(new URL('../../.pre-commit-config.yaml', import.meta.url), 'utf8')
  const match = /--maxkb=(\d+)/.exec(config)
  expect(match, 'check-added-large-files --maxkb').not.toBeNull()
  return Number(match?.[1]) * 1024
}

describe('contrast helper', () => {
  it('matches the WCAG reference values', () => {
    expect(relativeLuminance('#000000')).toBe(0)
    expect(relativeLuminance('#ffffff')).toBeCloseTo(1, 10)
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 10)
    expect(contrastRatio('#ffffff', '#000000')).toBeCloseTo(21, 10)
    // #767676 is the classic lightest grey that still passes AA on white.
    expect(contrastRatio('#767676', '#ffffff')).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio('#777777', '#ffffff')).toBeLessThan(4.5)
  })
})

describe('city themes', () => {
  it.each(Object.keys(CITY_CONFIGS))('%s: every text ink passes WCAG AA', (cityId) => {
    const theme = CITY_CONFIGS[cityId].theme
    for (const ink of TEXT_INKS) {
      for (const ground of TEXT_GROUNDS) {
        const ratio = contrastRatio(theme[ink], theme[ground])
        expect(
          ratio,
          `${cityId} ${ink} ${theme[ink]} on ${ground} ${theme[ground]}`,
        ).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it.each(NEW_MX_CITIES)('%s has its own accent, distinct from every other city', (cityId) => {
    const accent = CITY_CONFIGS[cityId].theme.accent
    for (const other of Object.values(CITY_CONFIGS)) {
      if (other.id === cityId) continue
      expect(accent).not.toBe(other.theme.accent)
      expect(rgbDistance(accent, other.theme.accent), `${cityId} vs ${other.id}`).toBeGreaterThan(
        35,
      )
    }
  })

  it('keeps the existing accents unchanged', () => {
    expect(
      Object.fromEntries(
        ['cdmx', 'oslo', 'bergen', 'trondheim', 'stavanger', 'drammen', 'morelia'].map((id) => [
          id,
          CITY_CONFIGS[id].theme.accent,
        ]),
      ),
    ).toEqual({
      cdmx: '#b5126f',
      oslo: '#3a36a0',
      bergen: '#a8322b',
      trondheim: '#1c7358',
      stavanger: '#0b6a86',
      drammen: '#2f6190',
      morelia: '#a4493d',
    })
  })
})

describe('cityDataAssets', () => {
  it('maps the colonia unit to its own files when the city declares it', () => {
    const assets = cityDataAssets('monterrey', { colonia: true })
    expect(assets.scores).toEqual({
      postal_code: `${BASE}data/monterrey/scores_postal_code.geojson`,
      colonia: `${BASE}data/monterrey/scores_colonia.geojson`,
    })
    expect(assets.metadata).toEqual({
      postal_code: `${BASE}data/monterrey/score_metadata_postal_code.json`,
      colonia: `${BASE}data/monterrey/score_metadata_colonia.json`,
    })
    // No colonia matrix is published, so no colonia index is declared (never fetched).
    expect(assets.matrixIndex).toEqual({
      postal_code: `${BASE}data/monterrey/routing_matrix_postal_code_index.json`,
    })
    expect(assets.scoreMetadata).toBe(`${BASE}data/monterrey/score_metadata.json`)
  })

  it('declares a colonia matrix index only when the city publishes one', () => {
    const assets = cityDataAssets('monterrey', { colonia: true, coloniaMatrix: true })
    expect(assets.matrixIndex).toEqual({
      postal_code: `${BASE}data/monterrey/routing_matrix_postal_code_index.json`,
      colonia: `${BASE}data/monterrey/routing_matrix_colonia_index.json`,
    })
  })

  it('aliases colonia to the postal files for a postal-only city (unchanged default)', () => {
    const assets = cityDataAssets('oslo')
    expect(assets.scores.colonia).toBe(`${BASE}data/oslo/scores_postal_code.geojson`)
    expect(assets.metadata.colonia).toBe(`${BASE}data/oslo/score_metadata_postal_code.json`)
    expect(assets.matrixIndex.colonia).toBe(
      `${BASE}data/oslo/routing_matrix_postal_code_index.json`,
    )
    expect(CITY_CONFIGS.oslo.assets).toEqual(assets)
    expect(CITY_CONFIGS.morelia.assets).toEqual(cityDataAssets('morelia'))
  })

  it('points the colonia scores at the parts index with coloniaParts', () => {
    const assets = cityDataAssets('monterrey', { colonia: true, coloniaParts: true })
    expect(assets.scores).toEqual({
      postal_code: `${BASE}data/monterrey/scores_postal_code.geojson`,
      colonia: `${BASE}data/monterrey/scores_colonia_index.json`,
    })
    expect(assets.metadata.colonia).toBe(`${BASE}data/monterrey/score_metadata_colonia.json`)
    // Without a colonia geography the flag changes nothing.
    expect(cityDataAssets('oslo', { coloniaParts: true })).toEqual(cityDataAssets('oslo'))
  })

  it('wires both new cities to real colonia assets and CDMX to its flat paths', () => {
    expect(CITY_CONFIGS.monterrey.assets).toEqual(
      cityDataAssets('monterrey', { colonia: true, coloniaParts: true }),
    )
    expect(CITY_CONFIGS.guadalajara.assets).toEqual(
      cityDataAssets('guadalajara', { colonia: true, coloniaParts: true }),
    )
    expect(CITY_CONFIGS.cdmx.assets).toBe(DATA_ASSETS)
  })

  it.each(NEW_MX_CITIES)('%s publishes colonia parts exactly as its profile declares', (cityId) => {
    const colonia = cityProfile(cityId).area_units?.find(
      (entry) => typeof entry === 'object' && entry.area_unit === 'colonia',
    )
    const declared = typeof colonia === 'object' && Boolean(colonia.public_part_max_bytes)
    expect(declared).toBe(true)
    expect(CITY_CONFIGS[cityId].assets.scores.colonia.endsWith('_index.json')).toBe(declared)
  })
})

describe('published score assets', () => {
  const limit = preCommitMaxBytes()

  it.each(Object.keys(CITY_CONFIGS))('%s: every scores and metadata URL is a file', (cityId) => {
    const { assets } = CITY_CONFIGS[cityId]
    for (const url of [...Object.values(assets.scores), ...Object.values(assets.metadata)]) {
      expect(existsSync(publicFile(url)), url).toBe(true)
    }
  })

  it.each(Object.keys(CITY_CONFIGS))(
    '%s: a parts index lists files that exist, match it and fit the limit',
    (cityId) => {
      for (const url of Object.values(CITY_CONFIGS[cityId].assets.scores)) {
        if (!url.endsWith('_index.json')) {
          expect(statSync(publicFile(url)).size, url).toBeLessThanOrEqual(limit)
          continue
        }
        const index = JSON.parse(readFileSync(publicFile(url), 'utf8')) as {
          feature_count: number
          parts: { path: string; bytes: number; feature_count: number }[]
        }
        expect(index.parts.length).toBeGreaterThan(1)
        const directory = url.slice(0, url.lastIndexOf('/') + 1)
        for (const part of index.parts) {
          expect(part.path).not.toContain('/')
          const size = statSync(publicFile(directory + part.path)).size
          expect(size, part.path).toBe(part.bytes)
          expect(size, part.path).toBeLessThanOrEqual(limit)
        }
        expect(index.parts.reduce((sum, part) => sum + part.feature_count, 0)).toBe(
          index.feature_count,
        )
      }
    },
  )
})

describe('CDMX config', () => {
  it('keeps its options, labels and incident-mode safety', () => {
    const cdmx = CITY_CONFIGS.cdmx
    expect(cdmx.transit).toBe(TRANSIT_ACCESS_OPTIONS)
    expect(cdmx.stores).toBe(STORE_OPTIONS)
    expect(cdmx.geographies).toBe(GEOGRAPHIES)
    expect(cdmx.safetyMode).toBe('incident_points')
    expect(cdmx.safetySource).toBe('FGJ CDMX')
    expect(cdmx.safetyRecordsLabel).toBe('All FGJ records')
    expect(cdmx.gymsSourceLabel).toBeUndefined()
    expect(cdmx.showPostalLabel).toBeUndefined()
  })

  it('does not show postal labels for the cities that predate them', () => {
    for (const id of ['cdmx', 'oslo', 'bergen', 'trondheim', 'stavanger', 'drammen', 'morelia']) {
      expect(CITY_CONFIGS[id].showPostalLabel, id).toBeFalsy()
    }
  })
})

describe.each(NEW_MX_CITIES)('%s config mirrors data/cities/<id>/city.json', (cityId) => {
  const city = CITY_CONFIGS[cityId]
  const profile = cityProfile(cityId)

  it('uses the profile weights x100', () => {
    expect(city.weights).toEqual(
      Object.fromEntries(
        Object.entries(profile.default_weights).map(([key, value]) => [
          key,
          Math.round(value * 100),
        ]),
      ),
    )
    expect(Object.values(city.weights).reduce((sum, value) => sum + value, 0)).toBe(100)
  })

  it('declares one transit option per profile system, keyed and labelled by it', () => {
    expect(city.transit.map((option) => [option.key, option.label])).toEqual(
      profile.transit_systems.map((system) => [system.slug, system.label]),
    )
    for (const option of city.transit) {
      expect(option.shortLabel.length).toBeGreaterThan(0)
      expect(option.distanceField).toBe(`dist_${option.key}_transit_m`)
      expect(option.scoreField).toBe(`score_transit_${option.key}`)
      expect(option.nearestNameField).toBe(`nearest_${option.key}_transit_name`)
      expect(option.nearestSourceField).toBe(`nearest_${option.key}_transit_source`)
    }
  })

  it('lists stores in store_brands order with the classifier family labels', () => {
    const labels = new Map(
      profile.supermarket_classifier.families.map((family) => [family.slug, family.label]),
    )
    expect(city.stores.map((option) => [option.key, option.label])).toEqual(
      profile.store_brands.map((brand) => [brand.slug, labels.get(brand.slug)]),
    )
    for (const option of city.stores) {
      expect(option.distanceField).toBe(`dist_${option.key}_m`)
      expect(option.timeField).toBe(`time_${option.key}_min`)
      expect(option.nearestNameField).toBe(`nearest_${option.key}_name`)
      expect(option.nearestSourceField).toBe(`nearest_${option.key}_source`)
    }
  })

  it('scores safety in the profile crime mode', () => {
    expect(city.scoresSafety).toBe(true)
    expect(city.safetyMode).toBe(profile.crime_mode)
  })

  it('offers postal codes and INEGI colonias', () => {
    expect(city.geographies.map((geography) => [geography.unit, geography.sourceLabel])).toEqual([
      ['postal_code', 'SEPOMEX via open-mexico · INEGI municipios'],
      ['colonia', 'INEGI colonias 2025'],
    ])
    expect(city.postalWidth).toBe(5)
    expect(city.postalPrefix).toBe('CP ')
    expect(city.eyebrow).toBe(`${city.name} apartment search`)
    expect(city.mapZoom).toBe(11)
    expect(city.showPostalLabel).toBe(true)
    expect(city.gymsSourceLabel).toBe('INEGI DENUE')
  })
})

describe('new city specifics', () => {
  it('frames and labels Monterrey', () => {
    const city = CITY_CONFIGS.monterrey
    expect(city.mapCenter).toEqual([25.6866, -100.3161])
    expect(city.postalPlaceholder).toBe('e.g. 64000')
    expect(city.transitSourceLabel).toBe('Nuevo León open data')
    expect(city.safetySource).toBe('SESNSP municipal rates')
    expect(city.safetyMode).toBe('city_statistics')
  })

  it('frames and labels Guadalajara', () => {
    const city = CITY_CONFIGS.guadalajara
    expect(city.mapCenter).toEqual([20.6597, -103.3496])
    expect(city.postalPlaceholder).toBe('e.g. 44100')
    expect(city.transitSourceLabel).toBe('SETRAN GTFS')
    expect(city.safetySource).toBe('IIEG Jalisco (Fiscalía)')
    expect(city.safetyMode).toBe('incident_points')
    expect(city.safetyRecordsLabel).toBe('All IIEG records')
  })

  it('names the crime window for Guadalajara only', () => {
    // IIEG's newest Región Centro release ends 2025-08-31; every other city keeps
    // its wording (CDMX "recent", Monterrey statistics, Norway/Morelia unscored).
    for (const [id, city] of Object.entries(CITY_CONFIGS)) {
      expect(Boolean(city.safetyWindowLabel), id).toBe(id === 'guadalajara')
    }
  })
})
