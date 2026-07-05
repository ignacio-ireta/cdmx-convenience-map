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

/** URL for a matrix binary, resolved against the Pages base path. */
export function matrixAssetUrl(filename: string) {
  return `${import.meta.env.BASE_URL}data/${filename}`
}

export const SCORE_FIELDS: Record<WeightKey, keyof AreaProperties> = {
  work: 'score_work',
  transit: 'score_transit',
  supermarkets: 'score_supermarkets',
  gyms: 'score_gyms',
  safety: 'score_safety',
}

export const LEGEND_STEPS = [
  { label: '85+', color: '#166534' },
  { label: '70', color: '#2f9e44' },
  { label: '55', color: '#9ac43e' },
  { label: '40', color: '#f2c94c' },
  { label: '25', color: '#f2994a' },
  { label: '0', color: '#d94841' },
]

export const SELECTED_AREA_MAX_ZOOM = 14
export const SELECTED_AREA_FOCUS_PADDING: L.PointExpression = [56, 56]
export const DATA_FOCUS_PADDING: L.PointExpression = [18, 18]
export const DEFAULT_MAP_CENTER: L.LatLngExpression = [19.4326, -99.1332]

export const CITY_CONFIGS = {
  cdmx: {
    id: 'cdmx',
    name: 'CDMX',
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
  },
  oslo: {
    id: 'oslo',
    name: 'Oslo',
    eyebrow: 'Oslo apartment search',
    postalWidth: 4,
    postalPlaceholder: 'e.g. 0150',
    postalPrefix: '',
    mapCenter: [59.9139, 10.7522] as L.LatLngExpression,
    mapZoom: 11,
    weights: {
      work: 35,
      transit: 30,
      supermarkets: 20,
      gyms: 15,
      safety: 0,
    } satisfies Record<WeightKey, number>,
    geographies: [
      {
        unit: 'postal_code',
        label: 'Postal code',
        pluralLabel: 'Postal codes',
        sourceLabel: 'Kartverket',
      },
    ] satisfies GeographyConfig[],
    stores: [
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
    ] satisfies StoreOption[],
    transit: [] satisfies TransitAccessOption[],
    assets: {
      scores: {
        postal_code: `${import.meta.env.BASE_URL}data/oslo/scores_postal_code.geojson`,
        colonia: `${import.meta.env.BASE_URL}data/oslo/scores_postal_code.geojson`,
      },
      metadata: {
        postal_code: `${import.meta.env.BASE_URL}data/oslo/score_metadata_postal_code.json`,
        colonia: `${import.meta.env.BASE_URL}data/oslo/score_metadata_postal_code.json`,
      },
      scoreMetadata: `${import.meta.env.BASE_URL}data/oslo/score_metadata.json`,
      matrixIndex: {
        postal_code: `${import.meta.env.BASE_URL}data/oslo/routing_matrix_postal_code_index.json`,
        colonia: `${import.meta.env.BASE_URL}data/oslo/routing_matrix_postal_code_index.json`,
      },
    },
    transitSourceLabel: 'OpenStreetMap',
    safetySource: 'Not scored',
    scoresSafety: false,
  },
} as const
