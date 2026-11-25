import type { LucideIcon } from 'lucide-react'
import type { Feature, FeatureCollection, Geometry } from 'geojson'

export type MetricKey =
  | 'combined'
  | 'work'
  | 'transit'
  | 'transitCommute'
  | 'supermarkets'
  | 'gyms'
  | 'safety'
export type WeightKey = Exclude<MetricKey, 'combined' | 'transitCommute'>

export type AreaUnit = 'postal_code' | 'colonia'
export type WorkMode = 'distance' | 'driving' | 'walking' | 'biking'
export type TravelWorkMode = Exclude<WorkMode, 'distance'>
export type AmenityMode = 'distance' | 'time'
export type StorePreferenceKey = string
// A transit system's profile slug (CDMX: metro, metrobus, rtp, trolebus,
// corredor; other cities declare their own in data/cities/<id>/city.json).
export type TransitAccessKey = string
// How a city scores safety: CDMX-style incident points aggregated per area, or
// one published rate per statistics unit (e.g. municipality) shared by its areas.
export type SafetyMode = 'incident_points' | 'city_statistics'

export type AreaProperties = {
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
  // Routed network distances (present only on a routed build; null where a row
  // fell back to the straight-line estimate). Additive — see docs/data-contract.md.
  dist_work_routed_m?: number
  dist_supermarket_routed_m?: number
  dist_costco_routed_m?: number
  dist_walmart_routed_m?: number
  dist_gym_routed_m?: number
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
  // Incident mode only, on cities whose profile declares crime_source.density_buffer_m:
  // the counts and density above cover the area grown by this many metres.
  crime_buffer_m?: number
  // Statistics-mode safety (crime_mode "city_statistics"): one rate per
  // statistics unit, shared by every area inside it.
  crime_statistics_scope?: string
  crime_statistics_area?: string
  crime_statistics_period?: string
  crime_scope_population?: number
  crime_scope_incidents_12m?: number
  crime_scope_scored_incidents_12m?: number
  crime_rate_per_100k_12m?: number
  crime_total_rate_per_100k_12m?: number
  municipio?: string
  mun_code?: string

  // Allow dynamic fields generated by the pipeline (e.g. per-city brand fields
  // like dist_rema_m, time_kiwi_min, etc.)
  [key: string]: unknown
}

export type RawAreaProperties = Record<string, unknown>
export type RawAreaFeatureCollection = FeatureCollection<Geometry, RawAreaProperties>
export type AreaFeature = Feature<Geometry, AreaProperties>
export type AreaFeatureCollection = FeatureCollection<Geometry, AreaProperties>

export type WorkModel = {
  areaId: string
  areaUnit: AreaUnit
  displayName: string
  distances: Map<string, number>
  scores: Map<string, number>
  travelTimes: Record<TravelWorkMode, Map<string, number>>
  travelScores: Record<TravelWorkMode, Map<string, number>>
  // True when travel times came from the precomputed routed matrix. ``travelSources``
  // is the per-area, per-mode honest label (valhalla_free_flow vs fallback_travel_time).
  routed: boolean
  travelSources: Record<TravelWorkMode, Map<string, string>>
}

export type MatrixIndex = {
  area_unit: AreaUnit
  n: number
  dtype: string
  scale: number
  sentinel: number
  axis0: string
  axis1: string
  layout: string
  unit: string
  area_ids: string[]
  modes: string[]
  mode_files: Record<string, string>
  engine: string
  version: string
  profiles: Record<string, string>
  inputs_hash: string
  osm_source?: string | null
  osm_sha?: string | null
  osm_date?: string | null
  generated_at: string
}
export type FieldScoreMap = {
  hasValues: boolean
  scores: Map<string, number>
}
export type PreferenceScoreModel = {
  storeDistanceScores: Record<StorePreferenceKey, FieldScoreMap>
  storeTimeScores: Record<StorePreferenceKey, FieldScoreMap>
  transitAccessScores: Record<TransitAccessKey, FieldScoreMap>
}
export type ScoreMetadata = {
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
    // Statistics mode only (absent from CDMX's block).
    mode?: string
    scope?: string
    source?: string
    source_label?: string
    scored_label?: string
    // Plain-language definition and the SESNSP offense names of the scored subset.
    scored_definition?: string
    scored_offenses?: string[]
    // How rates become scores, e.g. "min_max_across_units" (lowest rate = 100,
    // highest = 0, across the metro's statistics units).
    score_method?: string
    population_source?: string
    period_start?: string
    period_end?: string
    units?: CrimeStatisticsUnit[]
    areas_matched?: number
    areas_unmatched?: number
    // Incident mode: metres each area is grown by before counting incidents.
    density_buffer_m?: number
  }
  workplace?: {
    name?: string
    postal_code?: string
    source?: string
  }
  travel_time?: {
    source?: string
    fallback_source?: string
    modes?: string[]
    speeds_kmh?: Record<string, number>
    detour_factors?: Record<string, number>
  }
  road_routing?: {
    engine?: string
    version?: string
    source?: string
    modes?: string[]
    profiles?: Record<string, string>
    osm_source?: string | null
  } | null
  amenity_travel_time?: {
    source?: string
    // Present on routed builds: the estimate used for pairs the router missed.
    fallback_source?: string
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

export type CrimeStatisticsUnit = {
  key?: string
  name?: string
  population?: number
  incidents_12m?: number
  scored_incidents_12m?: number
  rate_per_100k?: number
  total_rate_per_100k?: number
  areas?: number
}

export type MetricConfig = {
  key: MetricKey
  label: string
  shortLabel: string
  icon: LucideIcon
}

export type GeographyConfig = {
  unit: AreaUnit
  label: string
  pluralLabel: string
  sourceLabel: string
}

export type AreaDatasets = Partial<Record<AreaUnit, AreaFeatureCollection>>
export type SearchMatch = {
  feature: AreaFeature
  rank: number
}
export type AreaFocusRequest = {
  feature: AreaFeature
  requestId: number
}

export type StoreOption = {
  key: StorePreferenceKey
  label: string
  distanceField: string
  timeField: string
  nearestNameField: string
  nearestSourceField: string
}

export type TransitAccessOption = {
  key: TransitAccessKey
  label: string
  shortLabel: string
  distanceField: keyof AreaProperties
  scoreField: keyof AreaProperties
  nearestNameField: keyof AreaProperties
  nearestSourceField: keyof AreaProperties
}
