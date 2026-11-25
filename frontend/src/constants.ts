import {
  BriefcaseBusiness,
  Dumbbell,
  Layers,
  Route,
  ShieldCheck,
  ShoppingCart,
  TrainFront,
} from 'lucide-react'
import type * as L from 'leaflet'
import type {
  AmenityMode,
  AreaProperties,
  AreaUnit,
  GeographyConfig,
  MetricConfig,
  SafetyMode,
  StoreOption,
  TransitAccessOption,
  TravelWorkMode,
  WeightKey,
  WorkMode,
} from './types'

export const METRICS: MetricConfig[] = [
  { key: 'combined', label: 'Combined', shortLabel: 'Overall', icon: Layers },
  { key: 'work', label: 'Work', shortLabel: 'Work', icon: BriefcaseBusiness },
  {
    key: 'transit',
    label: 'Transit access',
    shortLabel: 'Access',
    icon: TrainFront,
  },
  {
    key: 'transitCommute',
    label: 'Transit commute',
    shortLabel: 'Commute',
    icon: Route,
  },
  {
    key: 'supermarkets',
    label: 'Supermarkets',
    shortLabel: 'Stores',
    icon: ShoppingCart,
  },
  { key: 'gyms', label: 'Gyms', shortLabel: 'Gyms', icon: Dumbbell },
  { key: 'safety', label: 'Safety', shortLabel: 'Safety', icon: ShieldCheck },
]

export const DEFAULT_WEIGHTS: Record<WeightKey, number> = {
  work: 30,
  transit: 25,
  supermarkets: 18,
  gyms: 12,
  safety: 15,
}

export const WORK_MODES: { key: WorkMode; label: string; shortLabel: string }[] = [
  { key: 'distance', label: 'Straight-line distance', shortLabel: 'Distance' },
  { key: 'driving', label: 'Driving time', shortLabel: 'Drive' },
  { key: 'walking', label: 'Walking time', shortLabel: 'Walk' },
  { key: 'biking', label: 'Biking time', shortLabel: 'Bike' },
]

export const AMENITY_MODES: { key: AmenityMode; label: string }[] = [
  { key: 'distance', label: 'Distance' },
  { key: 'time', label: 'Time' },
]

export const STORE_OPTIONS: StoreOption[] = [
  {
    key: 'costco',
    label: 'Costco',
    distanceField: 'dist_costco_m',
    timeField: 'time_costco_min',
    nearestNameField: 'nearest_costco_name',
    nearestSourceField: 'nearest_costco_source',
  },
  {
    key: 'walmart',
    label: 'Walmart',
    distanceField: 'dist_walmart_m',
    timeField: 'time_walmart_min',
    nearestNameField: 'nearest_walmart_name',
    nearestSourceField: 'nearest_walmart_source',
  },
]

export const TRANSIT_ACCESS_OPTIONS: TransitAccessOption[] = [
  {
    key: 'metro',
    label: 'Metro',
    shortLabel: 'Metro',
    distanceField: 'dist_metro_transit_m',
    scoreField: 'score_transit_metro',
    nearestNameField: 'nearest_metro_transit_name',
    nearestSourceField: 'nearest_metro_transit_source',
  },
  {
    key: 'metrobus',
    label: 'Metrobús',
    shortLabel: 'MB',
    distanceField: 'dist_metrobus_transit_m',
    scoreField: 'score_transit_metrobus',
    nearestNameField: 'nearest_metrobus_transit_name',
    nearestSourceField: 'nearest_metrobus_transit_source',
  },
  {
    key: 'rtp',
    label: 'RTP',
    shortLabel: 'RTP',
    distanceField: 'dist_rtp_transit_m',
    scoreField: 'score_transit_rtp',
    nearestNameField: 'nearest_rtp_transit_name',
    nearestSourceField: 'nearest_rtp_transit_source',
  },
  {
    key: 'trolebus',
    label: 'Trolebús',
    shortLabel: 'Trole',
    distanceField: 'dist_trolebus_transit_m',
    scoreField: 'score_transit_trolebus',
    nearestNameField: 'nearest_trolebus_transit_name',
    nearestSourceField: 'nearest_trolebus_transit_source',
  },
  {
    key: 'corredor',
    label: 'Corredor',
    shortLabel: 'CC',
    distanceField: 'dist_corredor_transit_m',
    scoreField: 'score_transit_corredor',
    nearestNameField: 'nearest_corredor_transit_name',
    nearestSourceField: 'nearest_corredor_transit_source',
  },
]

export const TRAVEL_WORK_MODES: TravelWorkMode[] = ['driving', 'walking', 'biking']

export const WORK_TIME_FIELDS: Record<TravelWorkMode, keyof AreaProperties> = {
  driving: 'time_work_driving_min',
  walking: 'time_work_walking_min',
  biking: 'time_work_biking_min',
}

export const WORK_TIME_SCORE_FIELDS: Record<TravelWorkMode, keyof AreaProperties> = {
  driving: 'score_work_driving',
  walking: 'score_work_walking',
  biking: 'score_work_biking',
}

export const FALLBACK_TRAVEL_TIME = {
  speedsKmh: {
    driving: 24,
    walking: 4.8,
    biking: 14,
  },
  detourFactors: {
    driving: 1.35,
    walking: 1.15,
    biking: 1.25,
  },
} satisfies {
  speedsKmh: Record<TravelWorkMode, number>
  detourFactors: Record<TravelWorkMode, number>
}

export const GEOGRAPHIES: GeographyConfig[] = [
  {
    unit: 'postal_code',
    label: 'Postal code',
    pluralLabel: 'Postal codes',
    sourceLabel: 'CDMX open data',
  },
  {
    unit: 'colonia',
    label: 'Colonia',
    pluralLabel: 'Colonias',
    sourceLabel: 'Opendatasoft / IECM',
  },
]

export const DATA_ASSETS = {
  scores: {
    postal_code: `${import.meta.env.BASE_URL}data/scores_postal_code.geojson`,
    colonia: `${import.meta.env.BASE_URL}data/scores_colonia.geojson`,
  } satisfies Record<AreaUnit, string>,
  metadata: {
    postal_code: `${import.meta.env.BASE_URL}data/score_metadata_postal_code.json`,
    colonia: `${import.meta.env.BASE_URL}data/score_metadata_colonia.json`,
  } satisfies Record<AreaUnit, string>,
  scoreMetadata: `${import.meta.env.BASE_URL}data/score_metadata.json`,
  // Dynamic-workplace routed matrix sidecars (feature-detected; absent on a
  // straight-line build, in which case the frontend uses the labeled estimate).
  matrixIndex: {
    postal_code: `${import.meta.env.BASE_URL}data/routing_matrix_postal_code_index.json`,
    colonia: `${import.meta.env.BASE_URL}data/routing_matrix_colonia_index.json`,
  } satisfies Record<AreaUnit, string>,
}

export const SCORE_FIELDS: Record<WeightKey, keyof AreaProperties> = {
  work: 'score_work',
  transit: 'score_transit',
  supermarkets: 'score_supermarkets',
  gyms: 'score_gyms',
  safety: 'score_safety',
}

// One entry per colour class of the shared score ramp, highest first. `from` is
// the class's inclusive lower bound and must agree with `colorForScore`
// (lib/format.ts); format.test.ts checks that they do.
export const LEGEND_STEPS = [
  { label: '85+', from: 85, color: '#166534' },
  { label: '70', from: 70, color: '#2f9e44' },
  { label: '55', from: 55, color: '#9ac43e' },
  { label: '40', from: 40, color: '#f2c94c' },
  { label: '25', from: 25, color: '#f2994a' },
  { label: '0', from: 0, color: '#d94841' },
]

export const SELECTED_AREA_MAX_ZOOM = 14
export const SELECTED_AREA_FOCUS_PADDING: L.PointExpression = [56, 56]
export const DATA_FOCUS_PADDING: L.PointExpression = [18, 18]
export const DEFAULT_MAP_CENTER: L.LatLngExpression = [19.4326, -99.1332]

export type CityAssets = {
  scores: Record<AreaUnit, string>
  metadata: Record<AreaUnit, string>
  scoreMetadata: string
  // Dynamic-workplace routing matrix index per unit. A unit without a published
  // matrix has no entry, so the app never requests it (no 404 in the console).
  matrixIndex: Partial<Record<AreaUnit, string>>
}

// Chrome colours for one city's map page. Applied as CSS custom properties on
// the app shell (see App.css); the score ramp stays shared so a colour means
// the same score in every city.
//
// `accent*` is the city's ink. `counter` is a second ink of the opposite
// temperature (warm against a cool city, cool against a warm one), used
// sparingly for markers and section numerals. Every ink used for text passes
// WCAG AA (4.5:1) on `panel`, `canvas` and `accentSoft`.
export type CityTheme = {
  accent: string
  accentStrong: string
  accentSoft: string
  counter: string
  canvas: string
  panel: string
  border: string
}

export type CityConfig = {
  id: string
  name: string
  theme: CityTheme
  eyebrow: string
  postalWidth: number
  postalPlaceholder: string
  postalPrefix: string
  mapCenter: L.LatLngExpression
  mapZoom: number
  weights: Record<WeightKey, number>
  geographies: GeographyConfig[]
  stores: StoreOption[]
  transit: TransitAccessOption[]
  assets: CityAssets
  transitSourceLabel: string
  safetySource: string
  scoresSafety: boolean
  // 'incident_points' (CDMX): per-area incident counts and density.
  // 'city_statistics': one municipal rate per 100k residents, shared by every
  // area in that municipality.
  safetyMode: SafetyMode
  // Label of the all-records row in incident mode (CDMX "All FGJ records").
  safetyRecordsLabel?: string
  // Incident mode: name the data window ("Sep 2024 – Aug 2025", from the
  // metadata crime block) instead of saying "recent". For a city whose newest
  // crime release lags the map by months; CDMX keeps its "recent" wording.
  safetyWindowLabel?: boolean
  // Provenance of the gym points in the audit and the copied report
  // (default: OpenStreetMap).
  gymsSourceLabel?: string
  // Show the area's `postal_label` (e.g. its colonias) under the area title.
  showPostalLabel?: boolean
}

// Every Norwegian city shares the same open-data provenance (Kartverket postal
// areas, OpenStreetMap transit + grocery brands) and does not score crime; only
// location, map framing, and static-asset paths differ. See data/cities/<id>/.
const NORWAY_WEIGHTS: Record<WeightKey, number> = {
  work: 35,
  transit: 30,
  supermarkets: 20,
  gyms: 15,
  safety: 0,
}

const NORWAY_GEOGRAPHIES: GeographyConfig[] = [
  {
    unit: 'postal_code',
    label: 'Postal code',
    pluralLabel: 'Postal codes',
    sourceLabel: 'Kartverket',
  },
]

const NORWAY_STORES: StoreOption[] = [
  {
    key: 'rema',
    label: 'Rema 1000',
    distanceField: 'dist_rema_m',
    timeField: 'time_rema_min',
    nearestNameField: 'nearest_rema_name',
    nearestSourceField: 'nearest_rema_source',
  },
  {
    key: 'kiwi',
    label: 'Kiwi',
    distanceField: 'dist_kiwi_m',
    timeField: 'time_kiwi_min',
    nearestNameField: 'nearest_kiwi_name',
    nearestSourceField: 'nearest_kiwi_source',
  },
  {
    key: 'coop',
    label: 'Coop/Extra',
    distanceField: 'dist_coop_m',
    timeField: 'time_coop_min',
    nearestNameField: 'nearest_coop_name',
    nearestSourceField: 'nearest_coop_source',
  },
  {
    key: 'meny',
    label: 'Meny',
    distanceField: 'dist_meny_m',
    timeField: 'time_meny_min',
    nearestNameField: 'nearest_meny_name',
    nearestSourceField: 'nearest_meny_source',
  },
  {
    key: 'joker',
    label: 'Joker',
    distanceField: 'dist_joker_m',
    timeField: 'time_joker_min',
    nearestNameField: 'nearest_joker_name',
    nearestSourceField: 'nearest_joker_source',
  },
  {
    key: 'bunnpris',
    label: 'Bunnpris',
    distanceField: 'dist_bunnpris_m',
    timeField: 'time_bunnpris_min',
    nearestNameField: 'nearest_bunnpris_name',
    nearestSourceField: 'nearest_bunnpris_source',
  },
]

// Morelia (Michoacán) shares the open-data provenance of the Norwegian cities —
// OpenStreetMap transit + grocery brands, no crime scoring — but keeps Mexican
// 5-digit "CP " postal codes (open-mexico SEPOMEX polygons) and local grocery
// chains. See data/cities/morelia/.
const MORELIA_STORES: StoreOption[] = [
  {
    key: 'aurrera',
    label: 'Bodega Aurrerá',
    distanceField: 'dist_aurrera_m',
    timeField: 'time_aurrera_min',
    nearestNameField: 'nearest_aurrera_name',
    nearestSourceField: 'nearest_aurrera_source',
  },
  {
    key: 'walmart',
    label: 'Walmart',
    distanceField: 'dist_walmart_m',
    timeField: 'time_walmart_min',
    nearestNameField: 'nearest_walmart_name',
    nearestSourceField: 'nearest_walmart_source',
  },
  {
    key: 'soriana',
    label: 'Soriana',
    distanceField: 'dist_soriana_m',
    timeField: 'time_soriana_min',
    nearestNameField: 'nearest_soriana_name',
    nearestSourceField: 'nearest_soriana_source',
  },
  {
    key: 'chedraui',
    label: 'Chedraui',
    distanceField: 'dist_chedraui_m',
    timeField: 'time_chedraui_min',
    nearestNameField: 'nearest_chedraui_name',
    nearestSourceField: 'nearest_chedraui_source',
  },
]

// One transit system declared in a city profile's `transit_systems`; the
// pipeline names its per-system fields after the slug.
function transitOption(slug: string, label: string, shortLabel: string): TransitAccessOption {
  return {
    key: slug,
    label,
    shortLabel,
    distanceField: `dist_${slug}_transit_m`,
    scoreField: `score_transit_${slug}`,
    nearestNameField: `nearest_${slug}_transit_name`,
    nearestSourceField: `nearest_${slug}_transit_source`,
  }
}

// One grocery family declared in a city profile's `store_brands`.
function storeOption(slug: string, label: string): StoreOption {
  return {
    key: slug,
    label,
    distanceField: `dist_${slug}_m`,
    timeField: `time_${slug}_min`,
    nearestNameField: `nearest_${slug}_name`,
    nearestSourceField: `nearest_${slug}_source`,
  }
}

/**
 * Static-asset paths for a city published under `data/<cityId>/`.
 *
 * With `colonia: true` the colonia unit gets its own scores and metadata files,
 * and a routing-matrix index only with `coloniaMatrix: true` (Monterrey and
 * Guadalajara publish the dynamic-workplace matrix for postal codes only). With
 * `coloniaParts: true` the colonia scores URL is the parts index
 * (`scores_colonia_index.json`) that lib/areaData.ts joins, for a layer too large
 * for one file (`public_part_max_bytes` in the city profile).
 * Otherwise the city has no colonia geography, and the colonia entries alias the
 * postal files so the shared AreaUnit-keyed lookups still resolve to a real asset.
 */
export function cityDataAssets(
  cityId: string,
  opts: { colonia?: boolean; coloniaMatrix?: boolean; coloniaParts?: boolean } = {},
): CityAssets {
  const base = `${import.meta.env.BASE_URL}data/${cityId}`
  const coloniaUnit = opts.colonia ? 'colonia' : 'postal_code'
  return {
    scores: {
      postal_code: `${base}/scores_postal_code.geojson`,
      colonia:
        opts.colonia && opts.coloniaParts
          ? `${base}/scores_colonia_index.json`
          : `${base}/scores_${coloniaUnit}.geojson`,
    },
    metadata: {
      postal_code: `${base}/score_metadata_postal_code.json`,
      colonia: `${base}/score_metadata_${coloniaUnit}.json`,
    },
    scoreMetadata: `${base}/score_metadata.json`,
    matrixIndex: {
      postal_code: `${base}/routing_matrix_postal_code_index.json`,
      ...(opts.colonia && !opts.coloniaMatrix
        ? {}
        : { colonia: `${base}/routing_matrix_${coloniaUnit}_index.json` }),
    },
  }
}

// Monterrey and Guadalajara share the INEGI geography: SEPOMEX postal-code
// polygons (open-mexico) assigned to INEGI municipalities, plus INEGI's 2025
// colonia boundaries (DCAH) as a second geography. See data/cities/<id>/.
const MX_METRO_GEOGRAPHIES: GeographyConfig[] = [
  {
    unit: 'postal_code',
    label: 'Postal code',
    pluralLabel: 'Postal codes',
    sourceLabel: 'SEPOMEX via open-mexico · INEGI municipios',
  },
  {
    unit: 'colonia',
    label: 'Colonia',
    pluralLabel: 'Colonias',
    sourceLabel: 'INEGI colonias 2025',
  },
]

function norwegianCity(opts: {
  id: string
  name: string
  mapCenter: L.LatLngExpression
  postalPlaceholder: string
  theme: CityTheme
  mapZoom?: number
}): CityConfig {
  return {
    id: opts.id,
    name: opts.name,
    theme: opts.theme,
    eyebrow: `${opts.name} apartment search`,
    postalWidth: 4,
    postalPlaceholder: opts.postalPlaceholder,
    postalPrefix: '',
    mapCenter: opts.mapCenter,
    mapZoom: opts.mapZoom ?? 11,
    weights: NORWAY_WEIGHTS,
    geographies: NORWAY_GEOGRAPHIES,
    stores: NORWAY_STORES,
    transit: [],
    assets: cityDataAssets(opts.id),
    transitSourceLabel: 'OpenStreetMap',
    safetySource: 'Not scored',
    scoresSafety: false,
    safetyMode: 'incident_points',
  }
}

export const CITY_CONFIGS: Record<string, CityConfig> = {
  cdmx: {
    id: 'cdmx',
    name: 'CDMX',
    // Rosa mexicano and jacaranda bloom.
    theme: {
      accent: '#b5126f',
      accentStrong: '#7d0c4d',
      accentSoft: '#fbe4f0',
      // Jacaranda blue-violet, the cool against the rosa.
      counter: '#3f4a9a',
      canvas: '#f6e9f1',
      panel: '#fcf4f9',
      border: '#e3c9d8',
    },
    eyebrow: 'CDMX apartment search',
    postalWidth: 5,
    postalPlaceholder: 'e.g. 06600',
    postalPrefix: 'CP ',
    mapCenter: DEFAULT_MAP_CENTER,
    mapZoom: 11,
    weights: DEFAULT_WEIGHTS,
    geographies: GEOGRAPHIES,
    stores: STORE_OPTIONS,
    transit: TRANSIT_ACCESS_OPTIONS,
    assets: DATA_ASSETS,
    transitSourceLabel: 'Apimetro',
    safetySource: 'FGJ CDMX',
    scoresSafety: true,
    safetyMode: 'incident_points',
    safetyRecordsLabel: 'All FGJ records',
  },
  oslo: norwegianCity({
    id: 'oslo',
    name: 'Oslo',
    mapCenter: [59.9139, 10.7522],
    postalPlaceholder: 'e.g. 0150',
    // Oslo-blue fjord indigo.
    theme: {
      accent: '#3a36a0',
      accentStrong: '#2a2859',
      accentSoft: '#e6e5fa',
      // Fired brick of the Rådhuset, the warm against the fjord.
      counter: '#9c4a2c',
      canvas: '#eae9f7',
      panel: '#f6f5fc',
      border: '#cfcde8',
    },
  }),
  bergen: norwegianCity({
    id: 'bergen',
    name: 'Bergen',
    mapCenter: [60.3913, 5.3221],
    postalPlaceholder: 'e.g. 5003',
    // Bryggen wharf red against rain-grey skies.
    theme: {
      accent: '#a8322b',
      accentStrong: '#7b211c',
      accentSoft: '#f8e1de',
      // Fjord slate, the cool against the wharf red.
      counter: '#2c5a73',
      canvas: '#e9edf0',
      panel: '#f5f7f8',
      border: '#cdd5da',
    },
  }),
  trondheim: norwegianCity({
    id: 'trondheim',
    name: 'Trondheim',
    mapCenter: [63.4305, 10.3951],
    postalPlaceholder: 'e.g. 7010',
    // Verdigris copper of Nidarosdomen's roof.
    theme: {
      accent: '#1c7358',
      accentStrong: '#114d3b',
      accentSoft: '#dcf2e9',
      // Bare copper, what the roof was before it turned.
      counter: '#96501c',
      canvas: '#e4f0ea',
      panel: '#f3f9f6',
      border: '#c2d9ce',
    },
  }),
  stavanger: norwegianCity({
    id: 'stavanger',
    name: 'Stavanger',
    mapCenter: [58.97, 5.7331],
    postalPlaceholder: 'e.g. 4006',
    // North Sea petrol.
    theme: {
      accent: '#0b6a86',
      accentStrong: '#074a5e',
      accentSoft: '#dbf0f6',
      // Flare orange against the petrol.
      counter: '#a04a1e',
      canvas: '#e2f0f4',
      panel: '#f2f9fb',
      border: '#bdd8e0',
    },
  }),
  drammen: norwegianCity({
    id: 'drammen',
    name: 'Drammen',
    mapCenter: [59.744, 10.2045],
    postalPlaceholder: 'e.g. 3015',
    // Drammenselva river steel-blue.
    theme: {
      accent: '#2f6190',
      accentStrong: '#1f4263',
      accentSoft: '#dfebf7',
      // Brick of the riverside mills.
      counter: '#96502a',
      canvas: '#e5edf5',
      panel: '#f4f7fb',
      border: '#c4d2e0',
    },
  }),
  morelia: {
    id: 'morelia',
    name: 'Morelia',
    // Cantera rosa, the pink stone of the historic centre.
    theme: {
      accent: '#a4493d',
      accentStrong: '#7a3229',
      accentSoft: '#f9e3dc',
      // Aqueduct-shadow teal, the cool against the pink stone.
      counter: '#2f6170',
      canvas: '#f5e4dd',
      panel: '#fcf3ef',
      border: '#e2c6bb',
    },
    eyebrow: 'Morelia apartment search',
    postalWidth: 5,
    postalPlaceholder: 'e.g. 58000',
    postalPrefix: 'CP ',
    mapCenter: [19.7024, -101.1946],
    mapZoom: 12,
    weights: { work: 35, transit: 30, supermarkets: 20, gyms: 15, safety: 0 },
    geographies: [
      {
        unit: 'postal_code',
        label: 'Postal code',
        pluralLabel: 'Postal codes',
        sourceLabel: 'SEPOMEX (Correos de México)',
      },
    ],
    stores: MORELIA_STORES,
    transit: [],
    assets: cityDataAssets('morelia'),
    transitSourceLabel: 'OpenStreetMap',
    safetySource: 'Not scored',
    scoresSafety: false,
    safetyMode: 'incident_points',
  },
  monterrey: {
    id: 'monterrey',
    name: 'Monterrey',
    // Faro del Comercio orange, the beacon over the Macroplaza.
    theme: {
      accent: '#a14e00',
      accentStrong: '#733000',
      accentSoft: '#fde8d8',
      // Cerro de la Silla slate, the cool against the beacon.
      counter: '#3d5266',
      canvas: '#f1ece6',
      panel: '#f9f6f2',
      border: '#dcd2c8',
    },
    eyebrow: 'Monterrey apartment search',
    postalWidth: 5,
    postalPlaceholder: 'e.g. 64000',
    postalPrefix: 'CP ',
    mapCenter: [25.6866, -100.3161],
    mapZoom: 11,
    weights: { work: 32, transit: 26, supermarkets: 20, gyms: 12, safety: 10 },
    geographies: MX_METRO_GEOGRAPHIES,
    // Order and labels follow data/cities/monterrey/city.json store_brands and
    // supermarket_classifier families.
    stores: [
      storeOption('heb', 'H-E-B'),
      storeOption('soriana', 'Soriana'),
      storeOption('walmart', 'Walmart'),
      storeOption('aurrera', 'Bodega Aurrerá'),
      storeOption('s_mart', 'S-Mart'),
      storeOption('sams', "Sam's Club"),
      storeOption('costco', 'Costco'),
    ],
    transit: [
      transitOption('metro', 'Metrorrey', 'Metro'),
      transitOption('brt', 'TransMetro BRT', 'BRT'),
      transitOption('transmetro', 'TransMetro', 'TransMetro'),
      transitOption('rutas', 'Rutas urbanas', 'Rutas'),
    ],
    assets: cityDataAssets('monterrey', { colonia: true, coloniaParts: true }),
    transitSourceLabel: 'Nuevo León open data',
    safetySource: 'SESNSP municipal rates',
    scoresSafety: true,
    safetyMode: 'city_statistics',
    gymsSourceLabel: 'INEGI DENUE',
    showPostalLabel: true,
  },
  guadalajara: {
    id: 'guadalajara',
    name: 'Guadalajara',
    // Ochre of the Catedral's tiled spires.
    theme: {
      accent: '#7c5f00',
      accentStrong: '#523f00',
      accentSoft: '#f7ecc9',
      // Talavera cobalt, the cool against the ochre.
      counter: '#1e4d9b',
      canvas: '#f4eddb',
      panel: '#fbf8ef',
      border: '#e2d6b4',
    },
    eyebrow: 'Guadalajara apartment search',
    postalWidth: 5,
    postalPlaceholder: 'e.g. 44100',
    postalPrefix: 'CP ',
    mapCenter: [20.6597, -103.3496],
    mapZoom: 11,
    weights: { work: 30, transit: 25, supermarkets: 18, gyms: 12, safety: 15 },
    geographies: MX_METRO_GEOGRAPHIES,
    // Order and labels follow data/cities/guadalajara/city.json store_brands and
    // supermarket_classifier families.
    stores: [
      storeOption('aurrera', 'Bodega Aurrerá'),
      storeOption('soriana', 'Soriana'),
      storeOption('walmart', 'Walmart'),
      storeOption('chedraui', 'Chedraui'),
      storeOption('sams', "Sam's Club"),
      storeOption('la_comer', 'La Comer / City Market / Fresko'),
      storeOption('costco', 'Costco'),
    ],
    transit: [
      transitOption('mitren', 'Mi Tren', 'Mi Tren'),
      transitOption('mimacro', 'Mi Macro', 'Mi Macro'),
      transitOption('alimentadora', 'Alimentadoras Mi Macro', 'Alimentadoras'),
      transitOption('sitren', 'Mi Transporte Tren Ligero', 'SITREN'),
      transitOption('mitransporte', 'Mi Transporte', 'Mi Transporte'),
    ],
    assets: cityDataAssets('guadalajara', { colonia: true, coloniaParts: true }),
    transitSourceLabel: 'SETRAN GTFS',
    safetySource: 'IIEG Jalisco (Fiscalía)',
    scoresSafety: true,
    safetyMode: 'incident_points',
    safetyRecordsLabel: 'All IIEG records',
    // The newest IIEG Región Centro release ends 2025-08-31.
    safetyWindowLabel: true,
    gymsSourceLabel: 'INEGI DENUE',
    showPostalLabel: true,
  },
}
