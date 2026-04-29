import { useEffect, useMemo, useState } from 'react'
import {
  BriefcaseBusiness,
  Check,
  ClipboardCopy,
  Database,
  Dumbbell,
  Layers,
  MapPinned,
  Route,
  Search,
  ShieldCheck,
  ShoppingCart,
  TrainFront,
} from 'lucide-react'
import L, { type LatLngExpression, type Layer, type PathOptions } from 'leaflet'
import { GeoJSON, MapContainer, TileLayer, useMap } from 'react-leaflet'
import type { Feature, FeatureCollection, Geometry } from 'geojson'
import './App.css'

type MetricKey =
  | 'combined'
  | 'work'
  | 'transit'
  | 'transitCommute'
  | 'supermarkets'
  | 'gyms'
  | 'safety'
type WeightKey = Exclude<MetricKey, 'combined' | 'transitCommute'>

type AreaUnit = 'postal_code' | 'colonia'
type WorkMode = 'distance' | 'driving' | 'walking' | 'biking'
type TravelWorkMode = Exclude<WorkMode, 'distance'>
type AmenityMode = 'distance' | 'time'
type StorePreferenceKey = 'costco' | 'walmart'
type TransitAccessKey = 'metro' | 'metrobus' | 'rtp' | 'trolebus' | 'corredor'

type AreaProperties = {
  area_unit: AreaUnit
  area_id: string
  area_name: string
  display_name: string
  alcaldia?: string
  d_cp?: string
  postal_code?: string
  postal_label?: string
  colonia_name?: string
  centroid_lat?: number
  centroid_lon?: number
  dist_work_m?: number
  dist_transit_m?: number
  dist_core_transit_m?: number
  dist_surface_transit_m?: number
  dist_metro_transit_m?: number
  dist_metrobus_transit_m?: number
  dist_rtp_transit_m?: number
  dist_trolebus_transit_m?: number
  dist_corredor_transit_m?: number
  dist_supermarket_m?: number
  dist_costco_m?: number
  dist_walmart_m?: number
  dist_gym_m?: number
  time_work_driving_min?: number
  time_work_walking_min?: number
  time_work_biking_min?: number
  time_supermarket_min?: number
  time_costco_min?: number
  time_walmart_min?: number
  time_gym_min?: number
  time_work_transit_min?: number
  time_work_transit_p75_min?: number
  transfers_work_transit?: number
  walk_to_origin_stop_m?: number
  destination_walk_m?: number
  transit_commute_source?: string
  transit_origin_stop_name?: string
  transit_origin_system?: string
  transit_origin_line?: string
  transit_origin_walk_m?: number
  transit_destination_stop_name?: string
  transit_destination_system?: string
  transit_destination_line?: string
  transit_destination_walk_m?: number
  transit_transfer_penalty_min?: number
  transit_route_complexity?: string
  transit_commute_notes?: string
  score_work?: number
  score_work_driving?: number
  score_work_walking?: number
  score_work_biking?: number
  score_work_transit?: number
  score_transit?: number
  score_transit_metro?: number
  score_transit_metrobus?: number
  score_transit_rtp?: number
  score_transit_trolebus?: number
  score_transit_corredor?: number
  score_supermarkets?: number
  score_supermarkets_time?: number
  score_gyms?: number
  score_gyms_time?: number
  score_safety?: number
  score_combined_default?: number
  nearest_work_name?: string
  nearest_transit_name?: string
  nearest_core_transit_name?: string
  nearest_surface_transit_name?: string
  nearest_metro_transit_name?: string
  nearest_metrobus_transit_name?: string
  nearest_rtp_transit_name?: string
  nearest_trolebus_transit_name?: string
  nearest_corredor_transit_name?: string
  nearest_supermarket_name?: string
  nearest_costco_name?: string
  nearest_walmart_name?: string
  nearest_gym_name?: string
  nearest_work_source?: string
  work_travel_time_source?: string
  nearest_transit_source?: string
  nearest_core_transit_source?: string
  nearest_surface_transit_source?: string
  nearest_metro_transit_source?: string
  nearest_metrobus_transit_source?: string
  nearest_rtp_transit_source?: string
  nearest_trolebus_transit_source?: string
  nearest_corredor_transit_source?: string
  nearest_supermarket_source?: string
  nearest_costco_source?: string
  nearest_walmart_source?: string
  nearest_gym_source?: string
  amenity_travel_time_source?: string
  transit_route_summary?: string
  crime_incidents_total?: number
  crime_incidents_recent_12m?: number
  crime_density_recent_12m_per_km2?: number
  crime_top_category_recent_12m?: string
  crime_source?: string
}

type RawAreaProperties = Record<string, unknown>
type RawAreaFeatureCollection = FeatureCollection<Geometry, RawAreaProperties>
type AreaFeature = Feature<Geometry, AreaProperties>
type AreaFeatureCollection = FeatureCollection<Geometry, AreaProperties>
type WorkModel = {
  areaId: string
  areaUnit: AreaUnit
  displayName: string
  distances: Map<string, number>
  scores: Map<string, number>
  travelTimes: Record<TravelWorkMode, Map<string, number>>
  travelScores: Record<TravelWorkMode, Map<string, number>>
}
type FieldScoreMap = {
  hasValues: boolean
  scores: Map<string, number>
}
type PreferenceScoreModel = {
  storeDistanceScores: Record<StorePreferenceKey, FieldScoreMap>
  storeTimeScores: Record<StorePreferenceKey, FieldScoreMap>
  transitAccessScores: Record<TransitAccessKey, FieldScoreMap>
}
type ScoreMetadata = {
  feature_count?: number
  point_counts?: {
    transit_stops?: number
    transit_core_points?: number
    transit_surface_points?: number
    transit_system_points?: Partial<Record<TransitAccessKey, number>>
    supermarkets?: number
    gyms?: number
    workplaces?: number
    crime_records?: number
  }
  crime?: {
    records_total?: number
    records_recent_12m?: number
    latest_date?: string
    recent_start_date?: string
  }
  workplace?: {
    name?: string
    postal_code?: string
    source?: string
  }
  travel_time?: {
    source?: string
    modes?: string[]
    speeds_kmh?: Record<string, number>
    detour_factors?: Record<string, number>
  }
  amenity_travel_time?: {
    source?: string
    mode?: string
    candidate_count?: number
    candidate_pairs?: Record<string, number>
    estimated_pairs?: Record<string, number>
  }
  transit_commute?: {
    source?: string
    transit_commute_source?: string
    generated_at?: string
    candidate_stop_count?: number
    walking_speed_kmh?: number
    speeds_kmh?: Record<string, number>
    penalties_min?: Record<string, number>
    max_walk_m?: Record<string, number>
    estimated_areas?: number
    failed_areas?: number
    known_limitations?: string[]
  }
  transit_commute_source?: string
  source_urls?: Record<string, string>
}

type MetricConfig = {
  key: MetricKey
  label: string
  shortLabel: string
  icon: typeof Layers
}

type GeographyConfig = {
  unit: AreaUnit
  label: string
  pluralLabel: string
  sourceLabel: string
}

type AreaDatasets = Partial<Record<AreaUnit, AreaFeatureCollection>>
type SearchMatch = {
  feature: AreaFeature
  rank: number
}
type AreaFocusRequest = {
  feature: AreaFeature
  requestId: number
}

const METRICS: MetricConfig[] = [
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

const DEFAULT_WEIGHTS: Record<WeightKey, number> = {
  work: 30,
  transit: 25,
  supermarkets: 18,
  gyms: 12,
  safety: 15,
}

const WORK_MODES: { key: WorkMode; label: string; shortLabel: string }[] = [
  { key: 'distance', label: 'Straight-line distance', shortLabel: 'Distance' },
  { key: 'driving', label: 'Driving time', shortLabel: 'Drive' },
  { key: 'walking', label: 'Walking time', shortLabel: 'Walk' },
  { key: 'biking', label: 'Biking time', shortLabel: 'Bike' },
]

const AMENITY_MODES: { key: AmenityMode; label: string }[] = [
  { key: 'distance', label: 'Distance' },
  { key: 'time', label: 'Time' },
]

type StoreOption = {
  key: StorePreferenceKey
  label: string
  distanceField: keyof AreaProperties
  timeField: keyof AreaProperties
  nearestNameField: keyof AreaProperties
  nearestSourceField: keyof AreaProperties
}

type TransitAccessOption = {
  key: TransitAccessKey
  label: string
  shortLabel: string
  distanceField: keyof AreaProperties
  scoreField: keyof AreaProperties
  nearestNameField: keyof AreaProperties
  nearestSourceField: keyof AreaProperties
}

const STORE_OPTIONS: StoreOption[] = [
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

const TRANSIT_ACCESS_OPTIONS: TransitAccessOption[] = [
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

const TRAVEL_WORK_MODES: TravelWorkMode[] = ['driving', 'walking', 'biking']

const WORK_TIME_FIELDS: Record<TravelWorkMode, keyof AreaProperties> = {
  driving: 'time_work_driving_min',
  walking: 'time_work_walking_min',
  biking: 'time_work_biking_min',
}

const WORK_TIME_SCORE_FIELDS: Record<TravelWorkMode, keyof AreaProperties> = {
  driving: 'score_work_driving',
  walking: 'score_work_walking',
  biking: 'score_work_biking',
}

const FALLBACK_TRAVEL_TIME = {
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

const GEOGRAPHIES: GeographyConfig[] = [
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

const DATA_ASSETS = {
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

const SCORE_FIELDS: Record<WeightKey, keyof AreaProperties> = {
  work: 'score_work',
  transit: 'score_transit',
  supermarkets: 'score_supermarkets',
  gyms: 'score_gyms',
  safety: 'score_safety',
}

const LEGEND_STEPS = [
  { label: '85+', color: '#166534' },
  { label: '70', color: '#2f9e44' },
  { label: '55', color: '#9ac43e' },
  { label: '40', color: '#f2c94c' },
  { label: '25', color: '#f2994a' },
  { label: '0', color: '#d94841' },
]

const SELECTED_AREA_ZOOM = 14

function stringFrom(value: unknown) {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return ''
}

function optionalString(value: unknown) {
  const text = stringFrom(value)
  return text || undefined
}

function numberFrom(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const numeric = Number(value)
    return Number.isFinite(numeric) ? numeric : undefined
  }
  return undefined
}

function normalizeAreaProperties(raw: RawAreaProperties): AreaProperties {
  const rawUnit = stringFrom(raw.area_unit)
  const areaUnit: AreaUnit = rawUnit === 'colonia' ? 'colonia' : 'postal_code'
  const postalCode =
    normalizePostalCode(stringFrom(raw.postal_code)) ||
    normalizePostalCode(stringFrom(raw.d_cp)) ||
    normalizePostalCode(stringFrom(raw.d_codigo))
  const coloniaName =
    optionalString(raw.colonia_name) ||
    (areaUnit === 'colonia' ? optionalString(raw.area_name) : undefined)
  const postalLabel = optionalString(raw.postal_label)
  const rawAreaId = optionalString(raw.area_id)
  const areaId =
    rawAreaId ||
    (areaUnit === 'postal_code' ? postalCode : coloniaName) ||
    postalCode ||
    coloniaName ||
    'unknown'
  const areaName =
    optionalString(raw.area_name) ||
    (areaUnit === 'postal_code' ? postalLabel || postalCode : coloniaName) ||
    areaId
  const displayName =
    optionalString(raw.display_name) ||
    (areaUnit === 'postal_code' ? `CP ${areaId}` : areaName)

  return {
    ...(raw as Partial<AreaProperties>),
    area_unit: areaUnit,
    area_id: areaId,
    area_name: areaName,
    display_name: displayName,
    alcaldia: optionalString(raw.alcaldia),
    d_cp: optionalString(raw.d_cp),
    postal_code: postalCode || undefined,
    postal_label: postalLabel,
    colonia_name: coloniaName,
    centroid_lat: numberFrom(raw.centroid_lat),
    centroid_lon: numberFrom(raw.centroid_lon),
    dist_work_m: numberFrom(raw.dist_work_m),
    dist_transit_m: numberFrom(raw.dist_transit_m),
    dist_core_transit_m: numberFrom(raw.dist_core_transit_m),
    dist_surface_transit_m: numberFrom(raw.dist_surface_transit_m),
    dist_metro_transit_m: numberFrom(raw.dist_metro_transit_m),
    dist_metrobus_transit_m: numberFrom(raw.dist_metrobus_transit_m),
    dist_rtp_transit_m: numberFrom(raw.dist_rtp_transit_m),
    dist_trolebus_transit_m: numberFrom(raw.dist_trolebus_transit_m),
    dist_corredor_transit_m: numberFrom(raw.dist_corredor_transit_m),
    dist_supermarket_m: numberFrom(raw.dist_supermarket_m),
    dist_costco_m: numberFrom(raw.dist_costco_m),
    dist_walmart_m: numberFrom(raw.dist_walmart_m),
    dist_gym_m: numberFrom(raw.dist_gym_m),
    time_work_driving_min: numberFrom(raw.time_work_driving_min),
    time_work_walking_min: numberFrom(raw.time_work_walking_min),
    time_work_biking_min: numberFrom(raw.time_work_biking_min),
    time_supermarket_min: numberFrom(raw.time_supermarket_min),
    time_costco_min: numberFrom(raw.time_costco_min),
    time_walmart_min: numberFrom(raw.time_walmart_min),
    time_gym_min: numberFrom(raw.time_gym_min),
    time_work_transit_min: numberFrom(raw.time_work_transit_min),
    time_work_transit_p75_min: numberFrom(raw.time_work_transit_p75_min),
    transfers_work_transit: numberFrom(raw.transfers_work_transit),
    walk_to_origin_stop_m: numberFrom(raw.walk_to_origin_stop_m),
    destination_walk_m: numberFrom(raw.destination_walk_m),
    transit_commute_source: optionalString(raw.transit_commute_source),
    transit_origin_stop_name: optionalString(raw.transit_origin_stop_name),
    transit_origin_system: optionalString(raw.transit_origin_system),
    transit_origin_line: optionalString(raw.transit_origin_line),
    transit_origin_walk_m: numberFrom(raw.transit_origin_walk_m),
    transit_destination_stop_name: optionalString(
      raw.transit_destination_stop_name,
    ),
    transit_destination_system: optionalString(
      raw.transit_destination_system,
    ),
    transit_destination_line: optionalString(raw.transit_destination_line),
    transit_destination_walk_m: numberFrom(raw.transit_destination_walk_m),
    transit_transfer_penalty_min: numberFrom(raw.transit_transfer_penalty_min),
    transit_route_complexity: optionalString(raw.transit_route_complexity),
    transit_commute_notes: optionalString(raw.transit_commute_notes),
    score_work: numberFrom(raw.score_work),
    score_work_driving: numberFrom(raw.score_work_driving),
    score_work_walking: numberFrom(raw.score_work_walking),
    score_work_biking: numberFrom(raw.score_work_biking),
    score_work_transit: numberFrom(raw.score_work_transit),
    score_transit: numberFrom(raw.score_transit),
    score_transit_metro: numberFrom(raw.score_transit_metro),
    score_transit_metrobus: numberFrom(raw.score_transit_metrobus),
    score_transit_rtp: numberFrom(raw.score_transit_rtp),
    score_transit_trolebus: numberFrom(raw.score_transit_trolebus),
    score_transit_corredor: numberFrom(raw.score_transit_corredor),
    score_supermarkets: numberFrom(raw.score_supermarkets),
    score_supermarkets_time: numberFrom(raw.score_supermarkets_time),
    score_gyms: numberFrom(raw.score_gyms),
    score_gyms_time: numberFrom(raw.score_gyms_time),
    score_safety: numberFrom(raw.score_safety),
    score_combined_default: numberFrom(raw.score_combined_default),
    nearest_work_name: optionalString(raw.nearest_work_name),
    nearest_transit_name: optionalString(raw.nearest_transit_name),
    nearest_core_transit_name: optionalString(raw.nearest_core_transit_name),
    nearest_surface_transit_name: optionalString(raw.nearest_surface_transit_name),
    nearest_metro_transit_name: optionalString(raw.nearest_metro_transit_name),
    nearest_metrobus_transit_name: optionalString(
      raw.nearest_metrobus_transit_name,
    ),
    nearest_rtp_transit_name: optionalString(raw.nearest_rtp_transit_name),
    nearest_trolebus_transit_name: optionalString(
      raw.nearest_trolebus_transit_name,
    ),
    nearest_corredor_transit_name: optionalString(
      raw.nearest_corredor_transit_name,
    ),
    nearest_supermarket_name: optionalString(raw.nearest_supermarket_name),
    nearest_costco_name: optionalString(raw.nearest_costco_name),
    nearest_walmart_name: optionalString(raw.nearest_walmart_name),
    nearest_gym_name: optionalString(raw.nearest_gym_name),
    nearest_work_source: optionalString(raw.nearest_work_source),
    work_travel_time_source: optionalString(raw.work_travel_time_source),
    nearest_transit_source: optionalString(raw.nearest_transit_source),
    nearest_core_transit_source: optionalString(raw.nearest_core_transit_source),
    nearest_surface_transit_source: optionalString(raw.nearest_surface_transit_source),
    nearest_metro_transit_source: optionalString(raw.nearest_metro_transit_source),
    nearest_metrobus_transit_source: optionalString(
      raw.nearest_metrobus_transit_source,
    ),
    nearest_rtp_transit_source: optionalString(raw.nearest_rtp_transit_source),
    nearest_trolebus_transit_source: optionalString(
      raw.nearest_trolebus_transit_source,
    ),
    nearest_corredor_transit_source: optionalString(
      raw.nearest_corredor_transit_source,
    ),
    nearest_supermarket_source: optionalString(raw.nearest_supermarket_source),
    nearest_costco_source: optionalString(raw.nearest_costco_source),
    nearest_walmart_source: optionalString(raw.nearest_walmart_source),
    nearest_gym_source: optionalString(raw.nearest_gym_source),
    amenity_travel_time_source: optionalString(raw.amenity_travel_time_source),
    transit_route_summary: optionalString(raw.transit_route_summary),
    crime_incidents_total: numberFrom(raw.crime_incidents_total),
    crime_incidents_recent_12m: numberFrom(raw.crime_incidents_recent_12m),
    crime_density_recent_12m_per_km2: numberFrom(
      raw.crime_density_recent_12m_per_km2,
    ),
    crime_top_category_recent_12m: optionalString(
      raw.crime_top_category_recent_12m,
    ),
    crime_source: optionalString(raw.crime_source),
  }
}

function normalizeAreaCollection(
  payload: RawAreaFeatureCollection,
): AreaFeatureCollection {
  return {
    ...payload,
    features: payload.features.map((feature) => ({
      ...feature,
      properties: normalizeAreaProperties(feature.properties ?? {}),
    })),
  }
}

function areaUnitLabel(unit: AreaUnit) {
  return unit === 'postal_code' ? 'Postal code' : 'Colonia'
}

function areaShortLabel(properties: AreaProperties) {
  return properties.area_unit === 'postal_code'
    ? `CP ${properties.postal_code ?? properties.area_id}`
    : properties.display_name
}

function areaFullLabel(properties: AreaProperties) {
  const base = areaShortLabel(properties)
  return properties.alcaldia ? `${base}, ${properties.alcaldia}` : base
}

function areaResultLabel(properties: AreaProperties) {
  const primary =
    properties.area_unit === 'postal_code'
      ? `CP ${properties.postal_code ?? properties.area_id}`
      : properties.colonia_name || properties.area_name || properties.display_name
  return properties.alcaldia
    ? `${primary} \u2014 ${properties.alcaldia}`
    : primary
}

function normalizeSearchText(value: string) {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLocaleLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\s+/g, ' ')
}

function areaSearchFields(properties: AreaProperties) {
  return [
    properties.area_id,
    properties.area_name,
    properties.display_name,
    properties.postal_code,
    properties.d_cp,
    properties.postal_label,
    properties.colonia_name,
    properties.alcaldia,
  ]
    .filter((value): value is string => Boolean(value))
}

function areaSearchText(properties: AreaProperties) {
  return areaSearchFields(properties).map(normalizeSearchText).join(' ')
}

function getAreaSearchRank(
  properties: AreaProperties,
  normalizedQuery: string,
  postalQuery: string,
) {
  const fields = areaSearchFields(properties).map(normalizeSearchText)
  const haystack = areaSearchText(properties)

  if (
    postalQuery &&
    properties.area_unit === 'postal_code' &&
    properties.postal_code === postalQuery
  ) {
    return 0
  }

  if (!normalizedQuery) return null
  if (fields.some((field) => field === normalizedQuery)) return 1
  if (fields.some((field) => field.startsWith(normalizedQuery))) return 2
  if (
    fields.some((field) =>
      field.split(' ').some((token) => token.startsWith(normalizedQuery)),
    )
  ) {
    return 3
  }
  if (haystack.includes(normalizedQuery)) return 4
  return null
}

function toggleRequiredSelection<Key extends string>(
  current: Key[],
  key: Key,
): Key[] {
  if (current.includes(key)) {
    return current.length === 1 ? current : current.filter((item) => item !== key)
  }
  return [...current, key]
}

function getScore(
  properties: AreaProperties,
  metric: MetricKey,
  weights: Record<WeightKey, number>,
  workModel: WorkModel | null,
  workMode: WorkMode,
  supermarketMode: AmenityMode,
  gymMode: AmenityMode,
  preferenceScoreModel: PreferenceScoreModel | null,
  selectedStores: StorePreferenceKey[],
  selectedTransitAccess: TransitAccessKey[],
) {
  if (metric !== 'combined') {
    if (metric === 'work') return getWorkScore(properties, workModel, workMode)
    if (metric === 'transitCommute') return properties.score_work_transit ?? 0
    if (metric === 'supermarkets') {
      return getSupermarketScore(
        properties,
        supermarketMode,
        preferenceScoreModel,
        selectedStores,
      )
    }
    if (metric === 'gyms') return getGymScore(properties, gymMode)
    if (metric === 'transit') {
      return getTransitAccessScore(
        properties,
        preferenceScoreModel,
        selectedTransitAccess,
      )
    }
    return Number(properties[SCORE_FIELDS[metric]]) || 0
  }

  const total = Object.values(weights).reduce((sum, value) => sum + value, 0)
  if (total <= 0) {
    return properties.score_combined_default || 0
  }

  return Object.entries(weights).reduce((sum, [key, weight]) => {
    const score =
      key === 'work'
        ? getWorkScore(properties, workModel, workMode)
        : key === 'supermarkets'
          ? getSupermarketScore(
              properties,
              supermarketMode,
              preferenceScoreModel,
              selectedStores,
            )
          : key === 'gyms'
            ? getGymScore(properties, gymMode)
            : key === 'transit'
              ? getTransitAccessScore(
                  properties,
                  preferenceScoreModel,
                  selectedTransitAccess,
                )
              : Number(properties[SCORE_FIELDS[key as WeightKey]]) || 0
    return sum + score * (weight / total)
  }, 0)
}

function normalizePostalCode(value: string) {
  const digits = value.replace(/\D/g, '')
  return digits ? digits.padStart(5, '0').slice(0, 5) : ''
}

function haversineMeters(
  fromLat: number,
  fromLon: number,
  toLat: number,
  toLon: number,
) {
  const earthRadiusMeters = 6371008.8
  const toRadians = Math.PI / 180
  const dLat = (toLat - fromLat) * toRadians
  const dLon = (toLon - fromLon) * toRadians
  const lat1 = fromLat * toRadians
  const lat2 = toLat * toRadians
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2
  return 2 * earthRadiusMeters * Math.asin(Math.sqrt(a))
}

function percentile(values: number[], fraction: number) {
  const finiteValues = values.filter(Number.isFinite)
  if (!finiteValues.length) return 1
  const sorted = [...finiteValues].sort((a, b) => a - b)
  const index = Math.min(
    sorted.length - 1,
    Math.max(0, Math.floor((sorted.length - 1) * fraction)),
  )
  return sorted[index] || 1
}

function scoreCloserIsBetter(values: number[]) {
  const cap = percentile(values, 0.95)
  const scores = new Map<string, number>()
  return { cap, scores }
}

function buildCloserScoreMap(
  data: AreaFeatureCollection,
  field: keyof AreaProperties,
): FieldScoreMap {
  const entries = data.features.map((feature) => ({
    areaId: feature.properties.area_id,
    value: Number(feature.properties[field]),
  }))
  const values = entries
    .map((entry) => entry.value)
    .filter((value) => Number.isFinite(value) && value >= 0)
  if (!values.length) {
    return { hasValues: false, scores: new Map() }
  }

  const cap = percentile(values, 0.95)
  const safeCap = cap > 0 ? cap : Math.max(...values, 1)
  const scores = new Map<string, number>()
  for (const { areaId, value } of entries) {
    const score =
      Number.isFinite(value) && value >= 0
        ? 100 * (1 - Math.min(value, safeCap) / safeCap)
        : 0
    scores.set(areaId, Math.max(0, Math.min(100, score)))
  }
  return { hasValues: true, scores }
}

function buildScoreRecord<Key extends string>(
  data: AreaFeatureCollection,
  options: { key: Key; field: keyof AreaProperties }[],
): Record<Key, FieldScoreMap> {
  return Object.fromEntries(
    options.map((option) => [
      option.key,
      buildCloserScoreMap(data, option.field),
    ]),
  ) as Record<Key, FieldScoreMap>
}

function buildPreferenceScoreModel(data: AreaFeatureCollection): PreferenceScoreModel {
  return {
    storeDistanceScores: buildScoreRecord(
      data,
      STORE_OPTIONS.map((option) => ({
        key: option.key,
        field: option.distanceField,
      })),
    ),
    storeTimeScores: buildScoreRecord(
      data,
      STORE_OPTIONS.map((option) => ({
        key: option.key,
        field: option.timeField,
      })),
    ),
    transitAccessScores: buildScoreRecord(
      data,
      TRANSIT_ACCESS_OPTIONS.map((option) => ({
        key: option.key,
        field: option.distanceField,
      })),
    ),
  }
}

function averageSelectedScores<Key extends string>(
  areaId: string,
  selectedKeys: Key[],
  scoreMaps: Record<Key, FieldScoreMap>,
) {
  const scores = selectedKeys
    .map((key) => {
      const scoreMap = scoreMaps[key]
      return scoreMap?.hasValues ? scoreMap.scores.get(areaId) : undefined
    })
    .filter((value): value is number => typeof value === 'number')
  if (!scores.length) return undefined
  return scores.reduce((sum, value) => sum + value, 0) / scores.length
}

function estimateTravelMinutes(distanceMeters: number, mode: TravelWorkMode) {
  const speedKmh = FALLBACK_TRAVEL_TIME.speedsKmh[mode]
  const detourFactor = FALLBACK_TRAVEL_TIME.detourFactors[mode]
  if (!Number.isFinite(distanceMeters) || speedKmh <= 0) return Number.NaN
  return (distanceMeters * detourFactor) / ((speedKmh * 1000) / 60)
}

function buildWorkModel(
  data: AreaFeatureCollection,
  workFeature: AreaFeature,
): WorkModel {
  const distances = new Map<string, number>()
  const workLat = workFeature.properties.centroid_lat
  const workLon = workFeature.properties.centroid_lon
  const distanceValues = data.features.map((feature) => {
    const areaLat = feature.properties.centroid_lat
    const areaLon = feature.properties.centroid_lon
    const distance = haversineMeters(
      areaLat ?? Number.NaN,
      areaLon ?? Number.NaN,
      workLat ?? Number.NaN,
      workLon ?? Number.NaN,
    )
    distances.set(feature.properties.area_id, distance)
    return distance
  })
  const { cap } = scoreCloserIsBetter(distanceValues)
  const scores = new Map<string, number>()
  for (const [areaId, distance] of distances) {
    scores.set(areaId, 100 * (1 - Math.min(distance, cap) / cap))
  }
  const travelTimes = Object.fromEntries(
    TRAVEL_WORK_MODES.map((mode) => [mode, new Map<string, number>()]),
  ) as Record<TravelWorkMode, Map<string, number>>
  const travelScores = Object.fromEntries(
    TRAVEL_WORK_MODES.map((mode) => [mode, new Map<string, number>()]),
  ) as Record<TravelWorkMode, Map<string, number>>

  for (const mode of TRAVEL_WORK_MODES) {
    const timeValues = data.features.map((feature) => {
      const distance = distances.get(feature.properties.area_id) ?? Number.NaN
      const minutes = estimateTravelMinutes(distance, mode)
      travelTimes[mode].set(feature.properties.area_id, minutes)
      return minutes
    })
    const timeCap = percentile(timeValues, 0.95)
    for (const [areaId, minutes] of travelTimes[mode]) {
      travelScores[mode].set(
        areaId,
        Number.isFinite(minutes)
          ? 100 * (1 - Math.min(minutes, timeCap) / timeCap)
          : 0,
      )
    }
  }
  return {
    areaId: workFeature.properties.area_id,
    areaUnit: workFeature.properties.area_unit,
    displayName: workFeature.properties.display_name,
    distances,
    scores,
    travelTimes,
    travelScores,
  }
}

function getWorkDistance(
  properties: AreaProperties,
  workModel: WorkModel | null,
) {
  return workModel?.distances.get(properties.area_id) ?? properties.dist_work_m
}

function getWorkTime(
  properties: AreaProperties,
  workModel: WorkModel | null,
  workMode: WorkMode,
) {
  if (workMode === 'distance') return undefined
  return (
    workModel?.travelTimes[workMode].get(properties.area_id) ??
    (properties[WORK_TIME_FIELDS[workMode]] as number | undefined)
  )
}

function getWorkScore(
  properties: AreaProperties,
  workModel: WorkModel | null,
  workMode: WorkMode,
) {
  if (workMode === 'distance') {
    return workModel?.scores.get(properties.area_id) ?? properties.score_work ?? 0
  }
  return (
    workModel?.travelScores[workMode].get(properties.area_id) ??
    (properties[WORK_TIME_SCORE_FIELDS[workMode]] as number | undefined) ??
    properties.score_work ??
    0
  )
}

function getWorkName(properties: AreaProperties, workModel: WorkModel | null) {
  return workModel
    ? `Work ${areaUnitLabel(workModel.areaUnit).toLocaleLowerCase()} ${workModel.displayName}`
    : properties.nearest_work_name || 'Configured work location'
}

function getWorkSource(
  properties: AreaProperties,
  workModel: WorkModel | null,
  workMode: WorkMode,
) {
  if (workMode !== 'distance') {
    return workModel
      ? 'fallback_travel_time'
      : properties.work_travel_time_source || properties.nearest_work_source
  }
  return workModel ? 'area_reference_point' : properties.nearest_work_source
}

function getSupermarketScore(
  properties: AreaProperties,
  supermarketMode: AmenityMode,
  preferenceScoreModel: PreferenceScoreModel | null,
  selectedStores: StorePreferenceKey[],
) {
  const selectedScore = preferenceScoreModel
    ? averageSelectedScores(
        properties.area_id,
        selectedStores,
        supermarketMode === 'time'
          ? preferenceScoreModel.storeTimeScores
          : preferenceScoreModel.storeDistanceScores,
      )
    : undefined
  if (typeof selectedScore === 'number') return selectedScore

  return supermarketMode === 'time'
    ? (properties.score_supermarkets_time ?? properties.score_supermarkets ?? 0)
    : (properties.score_supermarkets ?? 0)
}

function getTransitAccessScore(
  properties: AreaProperties,
  preferenceScoreModel: PreferenceScoreModel | null,
  selectedTransitAccess: TransitAccessKey[],
) {
  const selectedScore = preferenceScoreModel
    ? averageSelectedScores(
        properties.area_id,
        selectedTransitAccess,
        preferenceScoreModel.transitAccessScores,
      )
    : undefined
  if (typeof selectedScore === 'number') return selectedScore
  if (selectedTransitAccess.length === 1) {
    const option = TRANSIT_ACCESS_OPTIONS.find(
      (item) => item.key === selectedTransitAccess[0],
    )
    const score = option ? Number(properties[option.scoreField]) : Number.NaN
    if (Number.isFinite(score)) return score
  }
  return properties.score_transit ?? 0
}

function getGymScore(properties: AreaProperties, gymMode: AmenityMode) {
  return gymMode === 'time'
    ? (properties.score_gyms_time ?? properties.score_gyms ?? 0)
    : (properties.score_gyms ?? 0)
}

function getAmenitySource(
  properties: AreaProperties,
  mode: AmenityMode,
  distanceSource?: string,
) {
  return mode === 'time'
    ? properties.amenity_travel_time_source || distanceSource
    : distanceSource
}

function selectedOptionLabels<Key extends string>(
  options: { key: Key; label: string }[],
  selectedKeys: Key[],
) {
  return options
    .filter((option) => selectedKeys.includes(option.key))
    .map((option) => option.label)
    .join(', ')
}

function selectedStoreLabel(selectedStores: StorePreferenceKey[]) {
  return selectedOptionLabels(STORE_OPTIONS, selectedStores) || 'No stores'
}

function selectedTransitLabel(selectedTransitAccess: TransitAccessKey[]) {
  return (
    selectedOptionLabels(TRANSIT_ACCESS_OPTIONS, selectedTransitAccess) ||
    'No transit'
  )
}

function getSingleStoreOption(selectedStores: StorePreferenceKey[]) {
  if (selectedStores.length !== 1) return undefined
  return STORE_OPTIONS.find((option) => option.key === selectedStores[0])
}

function getSingleTransitAccessOption(selectedTransitAccess: TransitAccessKey[]) {
  if (selectedTransitAccess.length !== 1) return undefined
  return TRANSIT_ACCESS_OPTIONS.find(
    (option) => option.key === selectedTransitAccess[0],
  )
}

function getStoreDetailValue(
  properties: AreaProperties,
  supermarketMode: AmenityMode,
  selectedStores: StorePreferenceKey[],
) {
  const option = getSingleStoreOption(selectedStores)
  if (!option) {
    return formatDistanceAndTime(
      properties.dist_supermarket_m,
      properties.time_supermarket_min,
    )
  }
  return supermarketMode === 'time'
    ? formatDistanceAndTime(
        properties[option.distanceField] as number | undefined,
        properties[option.timeField] as number | undefined,
      )
    : formatMeters(properties[option.distanceField] as number | undefined)
}

function getStoreNearestName(
  properties: AreaProperties,
  selectedStores: StorePreferenceKey[],
) {
  const option = getSingleStoreOption(selectedStores)
  if (!option) return properties.nearest_supermarket_name
  return properties[option.nearestNameField] as string | undefined
}

function getStoreSource(
  properties: AreaProperties,
  supermarketMode: AmenityMode,
  selectedStores: StorePreferenceKey[],
) {
  const option = getSingleStoreOption(selectedStores)
  const distanceSource = option
    ? (properties[option.nearestSourceField] as string | undefined)
    : properties.nearest_supermarket_source
  return getAmenitySource(properties, supermarketMode, distanceSource)
}

function getTransitAccessDistance(
  properties: AreaProperties,
  selectedTransitAccess: TransitAccessKey[],
) {
  const option = getSingleTransitAccessOption(selectedTransitAccess)
  return option
    ? (properties[option.distanceField] as number | undefined)
    : properties.dist_transit_m
}

function getTransitAccessNearestName(
  properties: AreaProperties,
  selectedTransitAccess: TransitAccessKey[],
) {
  const option = getSingleTransitAccessOption(selectedTransitAccess)
  return option
    ? (properties[option.nearestNameField] as string | undefined)
    : properties.nearest_transit_name
}

function getTransitAccessSource(
  properties: AreaProperties,
  selectedTransitAccess: TransitAccessKey[],
) {
  const option = getSingleTransitAccessOption(selectedTransitAccess)
  return option
    ? (properties[option.nearestSourceField] as string | undefined)
    : properties.nearest_transit_source
}

function hasTransitCommute(properties: AreaProperties) {
  return (
    typeof properties.time_work_transit_min === 'number' ||
    typeof properties.score_work_transit === 'number' ||
    Boolean(properties.transit_commute_source)
  )
}

function colorForScore(score: number) {
  if (score >= 85) return '#166534'
  if (score >= 70) return '#2f9e44'
  if (score >= 55) return '#9ac43e'
  if (score >= 40) return '#f2c94c'
  if (score >= 25) return '#f2994a'
  return '#d94841'
}

function verdict(score: number) {
  if (score >= 78) return 'Convenient'
  if (score >= 58) return 'Manageable'
  if (score >= 38) return 'Mixed'
  return 'Annoying'
}

function formatMeters(value?: number) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'n/a'
  if (value >= 1000) return `${(value / 1000).toFixed(1)} km`
  return `${Math.round(value)} m`
}

function formatMinutes(value?: number) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'n/a'
  if (value >= 60) {
    const hours = Math.floor(value / 60)
    const minutes = Math.round(value % 60)
    return `${hours} hr ${minutes} min`
  }
  return `${Math.round(value)} min`
}

function formatDistanceAndTime(distance?: number, minutes?: number) {
  return `${formatMeters(distance)} / ${formatMinutes(minutes)}`
}

function formatAmenityDetail(name?: string, distance?: number, minutes?: number) {
  const detail = formatDistanceAndTime(distance, minutes)
  return name ? `${name} · ${detail}` : detail
}

function scoreText(value?: number) {
  const score = typeof value === 'number' && Number.isFinite(value) ? value : 0
  return `${Math.round(score * 10) / 10}`
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`
}

function weightSummary(weights: Record<WeightKey, number>) {
  const total = Object.values(weights).reduce((sum, value) => sum + value, 0)
  return (Object.keys(DEFAULT_WEIGHTS) as WeightKey[])
    .map((key) => {
      const label = METRICS.find((metric) => metric.key === key)?.label ?? key
      const share = total > 0 ? weights[key] / total : 0
      return `${label} ${weights[key]} (${formatPercent(share)})`
    })
    .join('; ')
}

function scoreModeSummary(
  selectedMetric: MetricKey,
  workMode: WorkMode,
  supermarketMode: AmenityMode,
  gymMode: AmenityMode,
  selectedStores: StorePreferenceKey[],
  selectedTransitAccess: TransitAccessKey[],
) {
  if (selectedMetric === 'work') {
    const mode =
      WORK_MODES.find((item) => item.key === workMode)?.label ?? workMode
    return `Work scored by ${mode.toLocaleLowerCase()}`
  }
  if (selectedMetric === 'supermarkets') {
    return `Stores scored by ${supermarketMode}; brands ${selectedStoreLabel(selectedStores)}`
  }
  if (selectedMetric === 'gyms') {
    return `Gyms scored by ${gymMode}`
  }
  if (selectedMetric === 'transitCommute') {
    return 'Transit commute scored by offline Apimetro stop-pair approximation'
  }
  if (selectedMetric === 'combined') {
    return `Combined score using work ${workMode}, transit ${selectedTransitLabel(selectedTransitAccess)}, stores ${supermarketMode} (${selectedStoreLabel(selectedStores)}), gyms ${gymMode}`
  }
  if (selectedMetric === 'transit') {
    return `Transit access scored by ${selectedTransitLabel(selectedTransitAccess)}`
  }
  return 'Single metric score'
}

function formatSource(source?: string) {
  if (!source) return 'unknown'
  if (source === 'openstreetmap') return 'OSM Overpass'
  if (source === 'cdmx_gtfs') return 'CDMX GTFS'
  if (source === 'apimetro') return 'Apimetro'
  if (source === 'area_reference_point') return 'Area reference point'
  if (source === 'postal_code_centroid') return 'Postal-code centroid'
  if (source === 'sample_config') return 'sample config'
  if (source === 'places_config') return 'places config'
  if (source === 'fallback_straight_line_estimate') return 'fallback estimate'
  if (source === 'fallback_travel_time') return 'fallback estimate'
  if (source === 'offline_transit_router') return 'offline transit router'
  if (source === 'apimetro_stop_pair_approximation') {
    return 'Approximation from Apimetro stops; not schedule-aware'
  }
  if (source === 'r5py_gtfs_schedule') return 'r5py GTFS schedule'
  if (source === 'transit_commute_failed') return 'Transit commute failed'
  if (source === 'transit_commute_not_configured') return 'Transit commute not configured'
  if (source === 'no_transit_stops_available') return 'No transit stops available'
  if (source === 'no_valid_transit_stop_coordinates') {
    return 'No valid transit stop coordinates'
  }
  if (source === 'fgj_cdmx_victimas') return 'FGJ CDMX'
  if (source === 'seed') return 'seed fallback'
  return source
}

function transitStopLabel(system?: string, name?: string, line?: string) {
  if (!name) return 'n/a'
  const prefix = [system, line].filter(Boolean).join(' ')
  return prefix ? `${prefix} ${name}` : name
}

function formatTransitComplexity(value?: string) {
  if (value === 'same_line') return 'Same line'
  if (value === 'same_system_different_line') return 'Same system, different line'
  if (value === 'same_system_unknown_line') return 'Same system, line unknown'
  if (value === 'different_system') return 'Different systems'
  return value || 'n/a'
}

function areaFocusCenter(feature: AreaFeature): LatLngExpression | null {
  const lat = feature.properties.centroid_lat
  const lon = feature.properties.centroid_lon
  if (
    typeof lat === 'number' &&
    Number.isFinite(lat) &&
    typeof lon === 'number' &&
    Number.isFinite(lon)
  ) {
    return [lat, lon]
  }

  const bounds = L.geoJSON(feature).getBounds()
  return bounds.isValid() ? bounds.getCenter() : null
}

function FitToData({ data }: { data: AreaFeatureCollection }) {
  const map = useMap()

  useEffect(() => {
    const bounds = L.geoJSON(data).getBounds()
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [18, 18] })
    }
  }, [data, map])

  return null
}

function ZoomToSelected({
  focusRequest,
}: {
  focusRequest: AreaFocusRequest | null
}) {
  const map = useMap()

  useEffect(() => {
    if (!focusRequest) return
    const center = areaFocusCenter(focusRequest.feature)
    if (!center) return

    const animationFrame = window.requestAnimationFrame(() => {
      map.invalidateSize({ pan: false })
      map.setView(center, SELECTED_AREA_ZOOM)
    })

    return () => window.cancelAnimationFrame(animationFrame)
  }, [focusRequest, map])

  return null
}

function App() {
  const [selectedAreaUnit, setSelectedAreaUnit] =
    useState<AreaUnit>('postal_code')
  const [datasets, setDatasets] = useState<AreaDatasets>({})
  const [metadata, setMetadata] = useState<ScoreMetadata | null>(null)
  const [selectedMetric, setSelectedMetric] = useState<MetricKey>('combined')
  const [workMode, setWorkMode] = useState<WorkMode>('distance')
  const [supermarketMode, setSupermarketMode] =
    useState<AmenityMode>('distance')
  const [gymMode, setGymMode] = useState<AmenityMode>('distance')
  const [selectedStores, setSelectedStores] = useState<StorePreferenceKey[]>([
    'costco',
    'walmart',
  ])
  const [selectedTransitAccess, setSelectedTransitAccess] = useState<
    TransitAccessKey[]
  >(['metro', 'metrobus', 'rtp', 'trolebus', 'corredor'])
  const [weights, setWeights] =
    useState<Record<WeightKey, number>>(DEFAULT_WEIGHTS)
  const [selected, setSelected] = useState<AreaFeature | null>(null)
  const [selectedFocus, setSelectedFocus] = useState<AreaFocusRequest | null>(
    null,
  )
  const [query, setQuery] = useState('')
  const [workCodeDraft, setWorkCodeDraft] = useState('')
  const [workPostalCode, setWorkPostalCode] = useState('')
  const [workCodeError, setWorkCodeError] = useState('')
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>(
    'idle',
  )
  const [loadError, setLoadError] = useState('')
  const data = datasets[selectedAreaUnit] ?? null
  const postalData = datasets.postal_code ?? null
  const selectedGeography =
    GEOGRAPHIES.find((geography) => geography.unit === selectedAreaUnit) ??
    GEOGRAPHIES[0]
  const selectedWorkMode =
    WORK_MODES.find((mode) => mode.key === workMode) ?? WORK_MODES[0]

  useEffect(() => {
    const cached = datasets[selectedAreaUnit]
    if (cached) return

    let cancelled = false
    fetch(DATA_ASSETS.scores[selectedAreaUnit])
      .then((response) => {
        if (!response.ok) {
          throw new Error(`GeoJSON request failed: ${response.status}`)
        }
        return response.json()
      })
      .then((payload: RawAreaFeatureCollection) => {
        if (cancelled) return
        const normalized = normalizeAreaCollection(payload)
        setDatasets((current) => ({
          ...current,
          [selectedAreaUnit]: normalized,
        }))
        setSelected(normalized.features[0] ?? null)
      })
      .catch((error: Error) => {
        if (!cancelled) setLoadError(error.message)
      })

    return () => {
      cancelled = true
    }
  }, [datasets, selectedAreaUnit])

  useEffect(() => {
    fetch(DATA_ASSETS.metadata[selectedAreaUnit])
      .then((response) =>
        response.ok ? response.json() : fetch(DATA_ASSETS.scoreMetadata),
      )
      .then((payloadOrResponse: ScoreMetadata | Response | null) =>
        payloadOrResponse instanceof Response
          ? payloadOrResponse.ok
            ? payloadOrResponse.json()
            : null
          : payloadOrResponse,
      )
      .then((payload: ScoreMetadata | null) => setMetadata(payload))
      .catch(() => setMetadata(null))
  }, [selectedAreaUnit])

  const workFeature = useMemo(() => {
    if (!postalData || !workPostalCode) return null
    return (
      postalData.features.find(
        (feature) =>
          feature.properties.area_unit === 'postal_code' &&
          feature.properties.postal_code === workPostalCode,
      ) ?? null
    )
  }, [postalData, workPostalCode])

  const workModel = useMemo(() => {
    if (!data || !workFeature) return null
    if (
      !Number.isFinite(workFeature.properties.centroid_lat) ||
      !Number.isFinite(workFeature.properties.centroid_lon)
    ) {
      return null
    }
    return buildWorkModel(data, workFeature)
  }, [data, workFeature])

  const preferenceScoreModel = useMemo(() => {
    return data ? buildPreferenceScoreModel(data) : null
  }, [data])

  const selectedScore = selected
    ? getScore(
        selected.properties,
        selectedMetric,
        weights,
        workModel,
        workMode,
        supermarketMode,
        gymMode,
        preferenceScoreModel,
        selectedStores,
        selectedTransitAccess,
      )
    : 0

  const sortedTopAreas = useMemo(() => {
    if (!data) return []
    return [...data.features]
      .sort(
        (a, b) =>
          getScore(
            b.properties,
            selectedMetric,
            weights,
            workModel,
            workMode,
            supermarketMode,
            gymMode,
            preferenceScoreModel,
            selectedStores,
            selectedTransitAccess,
          ) -
          getScore(
            a.properties,
            selectedMetric,
            weights,
            workModel,
            workMode,
            supermarketMode,
            gymMode,
            preferenceScoreModel,
            selectedStores,
            selectedTransitAccess,
          ),
      )
      .slice(0, 100)
  }, [
    data,
    selectedMetric,
    weights,
    workModel,
    workMode,
    supermarketMode,
    gymMode,
    preferenceScoreModel,
    selectedStores,
    selectedTransitAccess,
  ])

  const trimmedSearchQuery = query.trim()
  const searchMatches = useMemo<SearchMatch[]>(() => {
    if (!data || !trimmedSearchQuery) return []
    const normalizedQuery = normalizeSearchText(trimmedSearchQuery)
    const postalQuery = normalizePostalCode(trimmedSearchQuery)
    if (!normalizedQuery && !postalQuery) return []

    return data.features
      .map((feature) => {
        const rank = getAreaSearchRank(
          feature.properties,
          normalizedQuery,
          postalQuery,
        )
        return rank == null ? null : { feature, rank }
      })
      .filter((match): match is SearchMatch => Boolean(match))
      .sort((a, b) => {
        if (a.rank !== b.rank) return a.rank - b.rank
        return areaResultLabel(a.feature.properties).localeCompare(
          areaResultLabel(b.feature.properties),
          'es-MX',
        )
      })
  }, [data, trimmedSearchQuery])

  const searchResults = searchMatches.slice(0, 12)

  const topListCopyText = useMemo(() => {
    const metricLabel =
      METRICS.find((metric) => metric.key === selectedMetric)?.label ??
      selectedMetric
    const workplaceLabel =
      workModel?.displayName ||
      (metadata?.workplace?.postal_code
        ? `CP ${metadata.workplace.postal_code}`
        : metadata?.workplace?.name) ||
      'configured workplace'
    const rows = sortedTopAreas.map((feature, index) => {
      const score = scoreText(
        getScore(
          feature.properties,
          selectedMetric,
          weights,
          workModel,
          workMode,
          supermarketMode,
          gymMode,
          preferenceScoreModel,
          selectedStores,
          selectedTransitAccess,
        ),
      )
      return `${index + 1}\t${areaFullLabel(feature.properties)}\t${areaUnitLabel(feature.properties.area_unit)}\t${score}`
    })
    const lines = [
      'CDMX convenience map experiment',
      '',
      'Summary',
      `Geography: ${selectedGeography.label}`,
      `Metric: ${metricLabel}`,
      `Score mode: ${scoreModeSummary(
        selectedMetric,
        workMode,
        supermarketMode,
        gymMode,
        selectedStores,
        selectedTransitAccess,
      )}`,
      `Work location: ${workplaceLabel}`,
      `Weights: ${weightSummary(weights)}`,
      `Store brands: ${selectedStoreLabel(selectedStores)}`,
      `Transit access methods: ${selectedTransitLabel(selectedTransitAccess)}`,
      `Search query: ${trimmedSearchQuery || 'all areas'}`,
      `Copied results: top ${rows.length} of ${data?.features.length ?? rows.length} ${selectedGeography.pluralLabel.toLocaleLowerCase()}`,
      `Transit data: Apimetro (${metadata?.point_counts?.transit_stops ?? 'n/a'} points)`,
      `Stores: ${metadata?.point_counts?.supermarkets ?? 'n/a'} OSM/seed points; mode ${supermarketMode}`,
      `Gyms: ${metadata?.point_counts?.gyms ?? 'n/a'} OSM/seed points; mode ${gymMode}`,
      `Amenity travel time: ${formatSource(metadata?.amenity_travel_time?.source)}`,
      `Work travel time: ${formatSource(metadata?.travel_time?.source)}`,
      `Crime window: ${metadata?.crime?.recent_start_date ?? 'n/a'} to ${metadata?.crime?.latest_date ?? 'n/a'}`,
      '',
      'Rank\tArea\tType\tScore',
      ...rows,
    ]
    return lines.join('\n')
  }, [
    data,
    gymMode,
    metadata,
    preferenceScoreModel,
    selectedGeography.label,
    selectedGeography.pluralLabel,
    selectedMetric,
    selectedStores,
    selectedTransitAccess,
    sortedTopAreas,
    supermarketMode,
    trimmedSearchQuery,
    weights,
    workModel,
    workMode,
  ])

  const mapKey = `${selectedMetric}-${Object.values(weights).join('-')}-${
    selected?.properties.area_id ?? 'none'
  }-${workModel?.areaId ?? 'sample-work'}-${selectedAreaUnit}-${workMode}-${supermarketMode}-${gymMode}-${selectedStores.join('.')}-${selectedTransitAccess.join('.')}`

  const areaStyle = (feature?: Feature<Geometry, AreaProperties>) => {
    const properties = feature?.properties
    const isSelected = properties?.area_id === selected?.properties.area_id
    const score = properties
      ? getScore(
          properties,
          selectedMetric,
          weights,
          workModel,
          workMode,
          supermarketMode,
          gymMode,
          preferenceScoreModel,
          selectedStores,
          selectedTransitAccess,
        )
      : 0
    return {
      color: isSelected ? '#101418' : '#ffffff',
      fillColor: colorForScore(score),
      fillOpacity: isSelected ? 0.92 : 0.78,
      opacity: 0.96,
      weight: isSelected ? 2.2 : 0.7,
    } satisfies PathOptions
  }

  const onEachArea = (
    feature: Feature<Geometry, AreaProperties>,
    layer: Layer,
  ) => {
    const score = getScore(
      feature.properties,
      selectedMetric,
      weights,
      workModel,
      workMode,
      supermarketMode,
      gymMode,
      preferenceScoreModel,
      selectedStores,
      selectedTransitAccess,
    )
    layer.on({
      click: () => focusAreaFeature(feature),
      mouseover: () => {
        layer.bindTooltip(
          `${areaFullLabel(feature.properties)} · ${scoreText(score)}`,
          { sticky: true },
        )
      },
    })
  }

  function focusAreaFeature(feature: AreaFeature) {
    setSelected(feature)
    setSelectedFocus((current) => ({
      feature,
      requestId: (current?.requestId ?? 0) + 1,
    }))
  }

  function selectAreaFeature(feature: AreaFeature) {
    focusAreaFeature(feature)
    setQuery(
      feature.properties.area_unit === 'postal_code'
        ? (feature.properties.postal_code ?? feature.properties.area_id)
        : feature.properties.colonia_name ||
            feature.properties.area_name ||
            feature.properties.display_name,
    )
  }

  function handleSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (searchResults[0]) selectAreaFeature(searchResults[0].feature)
  }

  function updateWeight(key: WeightKey, value: number) {
    setWeights((current) => ({ ...current, [key]: value }))
  }

  function toggleStorePreference(key: StorePreferenceKey) {
    setSelectedStores((current) => toggleRequiredSelection(current, key))
  }

  function toggleTransitPreference(key: TransitAccessKey) {
    setSelectedTransitAccess((current) => toggleRequiredSelection(current, key))
  }

  function selectAreaUnit(areaUnit: AreaUnit) {
    setSelectedAreaUnit(areaUnit)
    setLoadError('')
    setQuery('')
    setSelectedFocus(null)
    setSelected(datasets[areaUnit]?.features[0] ?? null)
  }

  function applyWorkPostalCode(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!postalData) {
      setWorkCodeError('Postal-code layer is still loading')
      return
    }
    const normalized = normalizePostalCode(workCodeDraft)
    const match = postalData.features.find(
      (feature) =>
        feature.properties.area_unit === 'postal_code' &&
        feature.properties.postal_code === normalized,
    )
    if (!match) {
      setWorkCodeError(`Postal code ${normalized || workCodeDraft} was not found`)
      return
    }
    setWorkPostalCode(normalized)
    setWorkCodeDraft(normalized)
    setWorkCodeError('')
  }

  function useSelectedForWork() {
    if (!selected) return
    const postalCode = selected.properties.postal_code
    if (!postalCode) {
      setWorkCodeError('Selected area does not have a postal code')
      return
    }
    setWorkPostalCode(postalCode)
    setWorkCodeDraft(postalCode)
    setWorkCodeError('')
  }

  function clearWorkPostalCode() {
    setWorkPostalCode('')
    setWorkCodeDraft('')
    setWorkCodeError('')
  }

  async function copyTopList() {
    try {
      try {
        if (!navigator.clipboard?.writeText) {
          throw new Error('Clipboard API unavailable')
        }
        await navigator.clipboard.writeText(topListCopyText)
      } catch {
        const textarea = document.createElement('textarea')
        textarea.value = topListCopyText
        textarea.style.position = 'fixed'
        textarea.style.left = '-9999px'
        textarea.style.top = '0'
        document.body.appendChild(textarea)
        textarea.focus()
        textarea.select()
        const copied = document.execCommand('copy')
        textarea.remove()
        if (!copied) {
          throw new Error('Fallback copy failed')
        }
      }
      setCopyStatus('copied')
      window.setTimeout(() => setCopyStatus('idle'), 1600)
    } catch {
      setCopyStatus('failed')
      window.setTimeout(() => setCopyStatus('idle'), 2200)
    }
  }

  return (
    <main className="app-shell">
      <aside className="control-panel" aria-label="Map controls">
        <header className="app-header">
          <div className="title-row">
            <MapPinned aria-hidden="true" />
            <div>
              <p className="eyebrow">CDMX apartment search</p>
              <h1>Area convenience map</h1>
            </div>
          </div>
          <p className="status-line">
            {data
              ? `${data.features.length} ${selectedGeography.pluralLabel.toLocaleLowerCase()} scored`
              : `Loading ${selectedGeography.pluralLabel.toLocaleLowerCase()}`}
          </p>
        </header>

        <form className="search-form" onSubmit={handleSearch}>
          <Search aria-hidden="true" />
          <input
            aria-label="Search postal codes, colonias, or alcaldias"
            type="search"
            placeholder="Find postal code or area"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </form>
        {trimmedSearchQuery ? (
          <div className="search-results" aria-label="Area search results">
            {searchResults.length ? (
              <>
                <div className="search-results-meta">
                  {searchMatches.length === searchResults.length
                    ? `${searchMatches.length} matches`
                    : `Showing ${searchResults.length} of ${searchMatches.length}`}
                </div>
                <div className="search-result-list">
                  {searchResults.map(({ feature }) => (
                    <button
                      key={`${feature.properties.area_unit}-${feature.properties.area_id}`}
                      onClick={() => selectAreaFeature(feature)}
                      type="button"
                    >
                      <span>
                        <strong>{areaResultLabel(feature.properties)}</strong>
                        <small>{areaUnitLabel(feature.properties.area_unit)}</small>
                      </span>
                      <em>
                        {scoreText(
                          getScore(
                            feature.properties,
                            selectedMetric,
                            weights,
                            workModel,
                            workMode,
                            supermarketMode,
                            gymMode,
                            preferenceScoreModel,
                            selectedStores,
                            selectedTransitAccess,
                          ),
                        )}
                      </em>
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <p className="search-empty">
                No matches for "{trimmedSearchQuery}" in{' '}
                {selectedGeography.pluralLabel.toLocaleLowerCase()}.
              </p>
            )}
          </div>
        ) : null}

        <section className="panel-section">
          <h2>Geography</h2>
          <div className="geography-grid">
            {GEOGRAPHIES.map((geography) => (
              <button
                className={selectedAreaUnit === geography.unit ? 'active' : ''}
                key={geography.unit}
                onClick={() => selectAreaUnit(geography.unit)}
                type="button"
              >
                {geography.label}
              </button>
            ))}
          </div>
        </section>

        <section className="panel-section work-location-panel">
          <div className="section-heading">
            <h2>Work location</h2>
            <span>
              {workModel
                ? workModel.displayName
                : metadata?.workplace?.postal_code
                  ? `CP ${metadata.workplace.postal_code}`
                  : 'configured'}
            </span>
          </div>
          <form className="work-location-form" onSubmit={applyWorkPostalCode}>
            <label htmlFor="work-postal-code">Work postal code</label>
            <div>
              <input
                id="work-postal-code"
                inputMode="numeric"
                maxLength={5}
                placeholder="e.g. 06600"
                value={workCodeDraft}
                onChange={(event) => setWorkCodeDraft(event.target.value)}
              />
              <button type="submit">Apply</button>
            </div>
          </form>
          <div className="work-actions">
            <button onClick={useSelectedForWork} type="button">
              Use selected CP
            </button>
            <button onClick={clearWorkPostalCode} type="button">
              Reset default
            </button>
          </div>
          <div className="work-mode-grid" aria-label="Work score mode">
            {WORK_MODES.map((mode) => (
              <button
                className={workMode === mode.key ? 'active' : ''}
                key={mode.key}
                onClick={() => setWorkMode(mode.key)}
                type="button"
              >
                {mode.shortLabel}
              </button>
            ))}
          </div>
          <p className={workCodeError ? 'form-note error' : 'form-note'}>
            {workCodeError ||
              (workModel
                ? 'Work score is recalculated from that area reference point.'
                : `Work score uses ${metadata?.workplace?.name ?? 'the configured workplace'}.`)}
          </p>
        </section>

        <section className="panel-section">
          <h2>Metric</h2>
          <div className="metric-grid">
            {METRICS.map((metric) => {
              const Icon = metric.icon
              return (
                <button
                  className={selectedMetric === metric.key ? 'active' : ''}
                  key={metric.key}
                  onClick={() => setSelectedMetric(metric.key)}
                  type="button"
                >
                  <Icon aria-hidden="true" />
                  <span>{metric.shortLabel}</span>
                </button>
              )
            })}
          </div>
          <div className="amenity-mode-panel">
            <div className="amenity-mode-row">
              <span>Stores</span>
              <div className="amenity-mode-buttons">
                {AMENITY_MODES.map((mode) => (
                  <button
                    className={supermarketMode === mode.key ? 'active' : ''}
                    key={`stores-${mode.key}`}
                    onClick={() => setSupermarketMode(mode.key)}
                    type="button"
                  >
                    {mode.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="amenity-mode-row preference-row">
              <span>Brands</span>
              <div className="option-checkboxes store-options">
                {STORE_OPTIONS.map((option) => (
                  <label className="option-checkbox" key={option.key}>
                    <input
                      checked={selectedStores.includes(option.key)}
                      onChange={() => toggleStorePreference(option.key)}
                      type="checkbox"
                    />
                    <span>{option.label}</span>
                  </label>
                ))}
              </div>
            </div>
            <div className="amenity-mode-row preference-row">
              <span>Transit</span>
              <div className="option-checkboxes transit-options">
                {TRANSIT_ACCESS_OPTIONS.map((option) => (
                  <label className="option-checkbox" key={option.key}>
                    <input
                      checked={selectedTransitAccess.includes(option.key)}
                      onChange={() => toggleTransitPreference(option.key)}
                      type="checkbox"
                    />
                    <span>{option.shortLabel}</span>
                  </label>
                ))}
              </div>
            </div>
            <div className="amenity-mode-row">
              <span>Gyms</span>
              <div className="amenity-mode-buttons">
                {AMENITY_MODES.map((mode) => (
                  <button
                    className={gymMode === mode.key ? 'active' : ''}
                    key={`gyms-${mode.key}`}
                    onClick={() => setGymMode(mode.key)}
                    type="button"
                  >
                    {mode.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="panel-section data-audit-panel">
          <div className="section-heading">
            <h2>Data audit</h2>
            <Database aria-hidden="true" />
          </div>
          <dl>
            <div>
              <dt>{selectedGeography.pluralLabel}</dt>
              <dd>
                {selectedGeography.sourceLabel} · {data?.features.length ?? 0} areas
              </dd>
            </div>
            <div>
              <dt>Transit</dt>
              <dd>
                Apimetro · {metadata?.point_counts?.transit_stops ?? 'n/a'} points
                {metadata?.point_counts?.transit_core_points != null &&
                metadata?.point_counts?.transit_surface_points != null
                  ? ` (${metadata.point_counts.transit_core_points} core, ${metadata.point_counts.transit_surface_points} surface)`
                  : ''}
              </dd>
            </div>
            <div>
              <dt>Transit commute</dt>
              <dd>
                {metadata?.transit_commute?.estimated_areas ?? 'n/a'} estimated ·{' '}
                {metadata?.transit_commute?.candidate_stop_count ?? 'n/a'} candidates
              </dd>
            </div>
            <div>
              <dt>Stores</dt>
              <dd>OSM Overpass · {metadata?.point_counts?.supermarkets ?? 'n/a'} points</dd>
            </div>
            <div>
              <dt>Amenity time</dt>
              <dd>
                {formatSource(metadata?.amenity_travel_time?.source)} ·{' '}
                {metadata?.amenity_travel_time?.candidate_count ?? 'n/a'} candidates
              </dd>
            </div>
            <div>
              <dt>Work time</dt>
              <dd>
                {formatSource(metadata?.travel_time?.source)} ·{' '}
                {metadata?.workplace?.postal_code
                  ? `CP ${metadata.workplace.postal_code}`
                  : 'configured workplace'}
              </dd>
            </div>
            <div>
              <dt>Gyms</dt>
              <dd>OSM Overpass · {metadata?.point_counts?.gyms ?? 'n/a'} points</dd>
            </div>
            <div>
              <dt>Crime</dt>
              <dd>
                FGJ CDMX · {metadata?.crime?.records_recent_12m ?? 'n/a'} recent
                records
              </dd>
            </div>
          </dl>
        </section>

        <section className="panel-section">
          <div className="section-heading">
            <h2>Weights</h2>
            <span>Combined</span>
          </div>
          {(Object.keys(DEFAULT_WEIGHTS) as WeightKey[]).map((key) => (
            <label className="weight-row" key={key}>
              <span>{METRICS.find((metric) => metric.key === key)?.label}</span>
              <input
                type="range"
                min="0"
                max="60"
                step="1"
                value={weights[key]}
                onChange={(event) => updateWeight(key, Number(event.target.value))}
                onInput={(event) =>
                  updateWeight(key, Number(event.currentTarget.value))
                }
              />
              <strong>{weights[key]}</strong>
            </label>
          ))}
        </section>

        <section className="panel-section details-panel">
          <div className="section-heading">
            <h2>Area</h2>
            <span>{selected ? verdict(selectedScore) : 'No selection'}</span>
          </div>
          {selected ? (
            <>
              <div className="score-header">
                <div>
                  <p className="area-title">{areaFullLabel(selected.properties)}</p>
                  <p className="muted">
                    {areaUnitLabel(selected.properties.area_unit)} ·{' '}
                    {METRICS.find((metric) => metric.key === selectedMetric)?.label}
                  </p>
                </div>
                <strong>{scoreText(selectedScore)}</strong>
              </div>

              <div className="breakdown">
                <MetricRow
                  label={`Work (${selectedWorkMode.shortLabel})`}
                  score={getWorkScore(selected.properties, workModel, workMode)}
                  distance={
                    workMode === 'distance'
                      ? getWorkDistance(selected.properties, workModel)
                      : undefined
                  }
                  value={
                    workMode === 'distance'
                      ? undefined
                      : formatMinutes(
                          getWorkTime(selected.properties, workModel, workMode),
                        )
                  }
                  nearest={getWorkName(selected.properties, workModel)}
                  source={getWorkSource(selected.properties, workModel, workMode)}
                />
                <MetricRow
                  label={`Transit access (${selectedTransitLabel(selectedTransitAccess)})`}
                  score={getTransitAccessScore(
                    selected.properties,
                    preferenceScoreModel,
                    selectedTransitAccess,
                  )}
                  distance={getTransitAccessDistance(
                    selected.properties,
                    selectedTransitAccess,
                  )}
                  nearest={getTransitAccessNearestName(
                    selected.properties,
                    selectedTransitAccess,
                  )}
                  source={getTransitAccessSource(
                    selected.properties,
                    selectedTransitAccess,
                  )}
                />
                {hasTransitCommute(selected.properties) ? (
                  <MetricRow
                    label="Transit commute"
                    score={selected.properties.score_work_transit}
                    value={formatMinutes(selected.properties.time_work_transit_min)}
                    nearest={selected.properties.transit_route_summary}
                    source={selected.properties.transit_commute_source}
                  />
                ) : null}
                <MetricRow
                  label={`Stores (${selectedStoreLabel(selectedStores)})`}
                  score={getSupermarketScore(
                    selected.properties,
                    supermarketMode,
                    preferenceScoreModel,
                    selectedStores,
                  )}
                  value={getStoreDetailValue(
                    selected.properties,
                    supermarketMode,
                    selectedStores,
                  )}
                  nearest={getStoreNearestName(
                    selected.properties,
                    selectedStores,
                  )}
                  source={getStoreSource(
                    selected.properties,
                    supermarketMode,
                    selectedStores,
                  )}
                />
                <MetricRow
                  label={`Gyms (${gymMode === 'time' ? 'Time' : 'Distance'})`}
                  score={getGymScore(selected.properties, gymMode)}
                  value={formatDistanceAndTime(
                    selected.properties.dist_gym_m,
                    selected.properties.time_gym_min,
                  )}
                  nearest={selected.properties.nearest_gym_name}
                  source={getAmenitySource(
                    selected.properties,
                    gymMode,
                    selected.properties.nearest_gym_source,
                  )}
                />
                <MetricRow
                  label="Safety"
                  score={selected.properties.score_safety}
                  value={`${selected.properties.crime_incidents_recent_12m ?? 0} recent incidents`}
                  nearest={
                    selected.properties.crime_top_category_recent_12m ||
                    'No recent category'
                  }
                  source={selected.properties.crime_source}
                />
              </div>

              <dl className="raw-distances">
                <div>
                  <dt>Costco</dt>
                  <dd>
                    {formatAmenityDetail(
                      selected.properties.nearest_costco_name,
                      selected.properties.dist_costco_m,
                      selected.properties.time_costco_min,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Walmart</dt>
                  <dd>
                    {formatAmenityDetail(
                      selected.properties.nearest_walmart_name,
                      selected.properties.dist_walmart_m,
                      selected.properties.time_walmart_min,
                    )}
                  </dd>
                </div>
                <div>
                  <dt>Core transit</dt>
                  <dd>{formatMeters(selected.properties.dist_core_transit_m)}</dd>
                </div>
                <div>
                  <dt>Surface transit</dt>
                  <dd>{formatMeters(selected.properties.dist_surface_transit_m)}</dd>
                </div>
                {TRANSIT_ACCESS_OPTIONS.map((option) => (
                  <div key={option.key}>
                    <dt>{option.label}</dt>
                    <dd>
                      {formatMeters(
                        selected.properties[
                          option.distanceField
                        ] as number | undefined,
                      )}
                    </dd>
                  </div>
                ))}
                {hasTransitCommute(selected.properties) ? (
                  <>
                    <div>
                      <dt>Transit origin</dt>
                      <dd>
                        {transitStopLabel(
                          selected.properties.transit_origin_system,
                          selected.properties.transit_origin_stop_name,
                          selected.properties.transit_origin_line,
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>Transit destination</dt>
                      <dd>
                        {transitStopLabel(
                          selected.properties.transit_destination_system,
                          selected.properties.transit_destination_stop_name,
                          selected.properties.transit_destination_line,
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>Walk to origin stop</dt>
                      <dd>
                        {formatMeters(selected.properties.transit_origin_walk_m)}
                      </dd>
                    </div>
                    <div>
                      <dt>Destination walk</dt>
                      <dd>
                        {formatMeters(
                          selected.properties.transit_destination_walk_m,
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>Transfer penalty</dt>
                      <dd>
                        {formatMinutes(
                          selected.properties.transit_transfer_penalty_min,
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>Route complexity</dt>
                      <dd>
                        {formatTransitComplexity(
                          selected.properties.transit_route_complexity,
                        )}
                      </dd>
                    </div>
                    <div className="raw-note">
                      <dt>Transit source</dt>
                      <dd>
                        {formatSource(selected.properties.transit_commute_source)}
                      </dd>
                    </div>
                    <div className="raw-note">
                      <dt>Transit note</dt>
                      <dd>
                        {selected.properties.transit_commute_notes || 'n/a'}
                      </dd>
                    </div>
                  </>
                ) : null}
                <div>
                  <dt>Crime density</dt>
                  <dd>
                    {(
                      selected.properties.crime_density_recent_12m_per_km2 ?? 0
                    ).toFixed(1)}
                    /km2
                  </dd>
                </div>
                <div>
                  <dt>Drive to work</dt>
                  <dd>{formatMinutes(selected.properties.time_work_driving_min)}</dd>
                </div>
                <div>
                  <dt>Walk to work</dt>
                  <dd>{formatMinutes(selected.properties.time_work_walking_min)}</dd>
                </div>
                <div>
                  <dt>Bike to work</dt>
                  <dd>{formatMinutes(selected.properties.time_work_biking_min)}</dd>
                </div>
                <div>
                  <dt>All FGJ records</dt>
                  <dd>{selected.properties.crime_incidents_total ?? 0}</dd>
                </div>
              </dl>
            </>
          ) : (
            <p className="muted">Area details</p>
          )}
        </section>
      </aside>

      <section className="map-area" aria-label="Area map">
        {loadError ? (
          <div className="map-message">{loadError}</div>
        ) : data ? (
          <MapContainer
            center={[19.4326, -99.1332]}
            className="leaflet-map"
            maxZoom={16}
            minZoom={9}
            zoom={11}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <FitToData data={data} />
            <ZoomToSelected focusRequest={selectedFocus} />
            <GeoJSON
              data={data}
              key={mapKey}
              onEachFeature={onEachArea}
              style={areaStyle}
            />
          </MapContainer>
        ) : (
          <div className="map-message">
            Loading scored {selectedGeography.pluralLabel.toLocaleLowerCase()}
          </div>
        )}

        <div className="map-overlay">
          <div className="legend">
            {LEGEND_STEPS.map((step) => (
              <span key={step.label}>
                <i style={{ backgroundColor: step.color }} />
                {step.label}
              </span>
            ))}
          </div>
          <div className="top-list">
            <div className="top-list-header">
              <div>
                <strong>Top {selectedGeography.pluralLabel.toLocaleLowerCase()}</strong>
                <span>{sortedTopAreas.length} results</span>
              </div>
              <button
                className={copyStatus === 'copied' ? 'copied' : ''}
                onClick={copyTopList}
                title="Copy current top area results"
                type="button"
              >
                {copyStatus === 'copied' ? (
                  <Check aria-hidden="true" />
                ) : (
                  <ClipboardCopy aria-hidden="true" />
                )}
                <span>
                  {copyStatus === 'copied'
                    ? 'Copied'
                    : copyStatus === 'failed'
                      ? 'Failed'
                      : 'Copy'}
                </span>
              </button>
            </div>
            <div className="top-list-results">
              {sortedTopAreas.map((feature, index) => (
                <button
                  key={`${feature.properties.area_unit}-${feature.properties.area_id}`}
                  onClick={() => focusAreaFeature(feature)}
                  type="button"
                >
                  <span className="rank">{index + 1}</span>
                  <span>{areaFullLabel(feature.properties)}</span>
                  <em>
                    {scoreText(
                      getScore(
                        feature.properties,
                        selectedMetric,
                        weights,
                        workModel,
                        workMode,
                        supermarketMode,
                        gymMode,
                        preferenceScoreModel,
                        selectedStores,
                        selectedTransitAccess,
                      ),
                    )}
                  </em>
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>
    </main>
  )
}

function MetricRow({
  distance,
  label,
  nearest,
  score,
  source,
  value,
}: {
  distance?: number
  label: string
  nearest?: string
  score?: number
  source?: string
  value?: string
}) {
  const boundedScore =
    typeof score === 'number' && Number.isFinite(score)
      ? Math.max(0, Math.min(100, score))
      : 0

  return (
    <div className="metric-row">
      <div className="metric-row-top">
        <span>{label}</span>
        <strong>{scoreText(boundedScore)}</strong>
      </div>
      <div className="score-bar" aria-hidden="true">
        <i style={{ width: `${boundedScore}%` }} />
      </div>
      <div className="metric-row-bottom">
        <span>{value ?? formatMeters(distance ?? Number.NaN)}</span>
        <span>{nearest || 'n/a'}</span>
      </div>
      <div className="metric-source">{formatSource(source)}</div>
    </div>
  )
}

export default App
