import {
  FALLBACK_TRAVEL_TIME,
  TRAVEL_WORK_MODES,
  WORK_TIME_FIELDS,
  WORK_TIME_SCORE_FIELDS,
} from '../constants'
import type {
  AreaFeature,
  AreaFeatureCollection,
  AreaProperties,
  TravelWorkMode,
  WorkMode,
  WorkModel,
} from '../types'
import { percentile, scoreCloserIsBetter } from './score-math'
import { areaUnitLabel } from './search'

export function haversineMeters(fromLat: number, fromLon: number, toLat: number, toLon: number) {
  const earthRadiusMeters = 6371008.8
  const toRadians = Math.PI / 180
  const dLat = (toLat - fromLat) * toRadians
  const dLon = (toLon - fromLon) * toRadians
  const lat1 = fromLat * toRadians
  const lat2 = toLat * toRadians
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2
  return 2 * earthRadiusMeters * Math.asin(Math.sqrt(a))
}

export function estimateTravelMinutes(distanceMeters: number, mode: TravelWorkMode) {
  const speedKmh = FALLBACK_TRAVEL_TIME.speedsKmh[mode]
  const detourFactor = FALLBACK_TRAVEL_TIME.detourFactors[mode]
  if (!Number.isFinite(distanceMeters) || speedKmh <= 0) return Number.NaN
  return (distanceMeters * detourFactor) / ((speedKmh * 1000) / 60)
}

export function buildWorkModel(
  data: AreaFeatureCollection,
  workFeature: AreaFeature,
  routedTimes: Record<TravelWorkMode, Map<string, number>> | null = null,
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
  // Distance mode always stays straight-line (haversine), even on a routed model.
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
  const travelSources = Object.fromEntries(
    TRAVEL_WORK_MODES.map((mode) => [mode, new Map<string, string>()]),
  ) as Record<TravelWorkMode, Map<string, string>>

  for (const mode of TRAVEL_WORK_MODES) {
    const timeValues = data.features.map((feature) => {
      const areaId = feature.properties.area_id
      const routed = routedTimes?.[mode].get(areaId)
      let minutes: number
      let source: string
      if (typeof routed === 'number' && Number.isFinite(routed)) {
        // Genuine routed travel time from the matrix.
        minutes = routed
        source = 'valhalla_free_flow'
      } else {
        // No matrix, or an unreachable cell -> labeled straight-line estimate.
        minutes = estimateTravelMinutes(distances.get(areaId) ?? Number.NaN, mode)
        source = 'fallback_travel_time'
      }
      travelTimes[mode].set(areaId, minutes)
      travelSources[mode].set(areaId, source)
      return minutes
    })
    const timeCap = percentile(timeValues, 0.95)
    for (const [areaId, minutes] of travelTimes[mode]) {
      travelScores[mode].set(
        areaId,
        Number.isFinite(minutes) ? 100 * (1 - Math.min(minutes, timeCap) / timeCap) : 0,
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
    routed: routedTimes !== null,
    travelSources,
  }
}

export function getWorkDistance(properties: AreaProperties, workModel: WorkModel | null) {
  return workModel?.distances.get(properties.area_id) ?? properties.dist_work_m
}

export function getWorkTime(
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

export function getWorkScore(
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

export function getWorkName(properties: AreaProperties, workModel: WorkModel | null) {
  return workModel
    ? `Work ${areaUnitLabel(workModel.areaUnit).toLocaleLowerCase()} ${workModel.displayName}`
    : properties.nearest_work_name || 'Configured work location'
}

export function getWorkSource(
  properties: AreaProperties,
  workModel: WorkModel | null,
  workMode: WorkMode,
) {
  if (workMode !== 'distance') {
    // A custom workplace: routed when the matrix covered this area, else a labeled
    // estimate. No custom workplace: the precomputed per-feature source.
    return workModel
      ? (workModel.travelSources[workMode].get(properties.area_id) ?? 'fallback_travel_time')
      : properties.work_travel_time_source || properties.nearest_work_source
  }
  return workModel ? 'area_reference_point' : properties.nearest_work_source
}
