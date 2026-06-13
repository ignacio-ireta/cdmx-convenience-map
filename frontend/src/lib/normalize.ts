import type {
  AreaFeatureCollection,
  AreaProperties,
  AreaUnit,
  RawAreaFeatureCollection,
  RawAreaProperties,
} from '../types'
import { numberFrom, optionalString, stringFrom } from './format'

export function normalizePostalCode(value: string) {
  const digits = value.replace(/\D/g, '')
  return digits ? digits.padStart(5, '0').slice(0, 5) : ''
}

export function normalizeAreaProperties(raw: RawAreaProperties): AreaProperties {
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
    optionalString(raw.display_name) || (areaUnit === 'postal_code' ? `CP ${areaId}` : areaName)

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
    transit_destination_stop_name: optionalString(raw.transit_destination_stop_name),
    transit_destination_system: optionalString(raw.transit_destination_system),
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
    nearest_metrobus_transit_name: optionalString(raw.nearest_metrobus_transit_name),
    nearest_rtp_transit_name: optionalString(raw.nearest_rtp_transit_name),
    nearest_trolebus_transit_name: optionalString(raw.nearest_trolebus_transit_name),
    nearest_corredor_transit_name: optionalString(raw.nearest_corredor_transit_name),
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
    nearest_metrobus_transit_source: optionalString(raw.nearest_metrobus_transit_source),
    nearest_rtp_transit_source: optionalString(raw.nearest_rtp_transit_source),
    nearest_trolebus_transit_source: optionalString(raw.nearest_trolebus_transit_source),
    nearest_corredor_transit_source: optionalString(raw.nearest_corredor_transit_source),
    nearest_supermarket_source: optionalString(raw.nearest_supermarket_source),
    nearest_costco_source: optionalString(raw.nearest_costco_source),
    nearest_walmart_source: optionalString(raw.nearest_walmart_source),
    nearest_gym_source: optionalString(raw.nearest_gym_source),
    amenity_travel_time_source: optionalString(raw.amenity_travel_time_source),
    transit_route_summary: optionalString(raw.transit_route_summary),
    crime_incidents_total: numberFrom(raw.crime_incidents_total),
    crime_incidents_recent_12m: numberFrom(raw.crime_incidents_recent_12m),
    crime_density_recent_12m_per_km2: numberFrom(raw.crime_density_recent_12m_per_km2),
    crime_top_category_recent_12m: optionalString(raw.crime_top_category_recent_12m),
    crime_source: optionalString(raw.crime_source),
  }
}

export function normalizeAreaCollection(payload: RawAreaFeatureCollection): AreaFeatureCollection {
  return {
    ...payload,
    features: payload.features.map((feature) => ({
      ...feature,
      properties: normalizeAreaProperties(feature.properties ?? {}),
    })),
  }
}
