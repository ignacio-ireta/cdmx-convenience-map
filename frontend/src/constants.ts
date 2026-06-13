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
