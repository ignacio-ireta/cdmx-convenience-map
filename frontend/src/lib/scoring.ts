import {
  DEFAULT_WEIGHTS,
  METRICS,
  SCORE_FIELDS,
  TRANSIT_ACCESS_OPTIONS,
  WORK_MODES,
} from '../constants'
import type { StoreOption } from '../types'
import type {
  AmenityMode,
  AreaProperties,
  MetricKey,
  PreferenceScoreModel,
  StorePreferenceKey,
  TransitAccessKey,
  WeightKey,
  WorkMode,
  WorkModel,
} from '../types'
import { formatDistanceAndTime, formatMeters, formatPercent } from './format'
import { averageSelectedScores } from './score-math'
import { getWorkScore } from './work'

export function getScore(
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
      return getSupermarketScore(properties, supermarketMode, preferenceScoreModel, selectedStores)
    }
    if (metric === 'gyms') return getGymScore(properties, gymMode)
    if (metric === 'transit') {
      return getTransitAccessScore(properties, preferenceScoreModel, selectedTransitAccess)
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
          ? getSupermarketScore(properties, supermarketMode, preferenceScoreModel, selectedStores)
          : key === 'gyms'
            ? getGymScore(properties, gymMode)
            : key === 'transit'
              ? getTransitAccessScore(properties, preferenceScoreModel, selectedTransitAccess)
              : Number(properties[SCORE_FIELDS[key as WeightKey]]) || 0
    return sum + score * (weight / total)
  }, 0)
}

export function getSupermarketScore(
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

export function getTransitAccessScore(
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
    const option = TRANSIT_ACCESS_OPTIONS.find((item) => item.key === selectedTransitAccess[0])
    const score = option ? Number(properties[option.scoreField]) : Number.NaN
    if (Number.isFinite(score)) return score
  }
  return properties.score_transit ?? 0
}

export function getGymScore(properties: AreaProperties, gymMode: AmenityMode) {
  return gymMode === 'time'
    ? (properties.score_gyms_time ?? properties.score_gyms ?? 0)
    : (properties.score_gyms ?? 0)
}

export function getAmenitySource(
  properties: AreaProperties,
  mode: AmenityMode,
  distanceSource?: string,
) {
  return mode === 'time' ? properties.amenity_travel_time_source || distanceSource : distanceSource
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

export function selectedStoreLabel(
  storeOptions: StoreOption[],
  selectedStores: StorePreferenceKey[],
) {
  return selectedOptionLabels(storeOptions, selectedStores) || 'No stores'
}

export function selectedTransitLabel(selectedTransitAccess: TransitAccessKey[]) {
  return selectedOptionLabels(TRANSIT_ACCESS_OPTIONS, selectedTransitAccess) || 'No transit'
}

function getSingleStoreOption(storeOptions: StoreOption[], selectedStores: StorePreferenceKey[]) {
  if (selectedStores.length !== 1) return undefined
  return storeOptions.find((option) => option.key === selectedStores[0])
}

function getSingleTransitAccessOption(selectedTransitAccess: TransitAccessKey[]) {
  if (selectedTransitAccess.length !== 1) return undefined
  return TRANSIT_ACCESS_OPTIONS.find((option) => option.key === selectedTransitAccess[0])
}

export function getStoreDetailValue(
  properties: AreaProperties,
  supermarketMode: AmenityMode,
  storeOptions: StoreOption[],
  selectedStores: StorePreferenceKey[],
) {
  const option = getSingleStoreOption(storeOptions, selectedStores)
  if (!option) {
    return formatDistanceAndTime(properties.dist_supermarket_m, properties.time_supermarket_min)
  }
  return supermarketMode === 'time'
    ? formatDistanceAndTime(
        properties[option.distanceField] as number | undefined,
        properties[option.timeField] as number | undefined,
      )
    : formatMeters(properties[option.distanceField] as number | undefined)
}

export function getStoreNearestName(
  properties: AreaProperties,
  storeOptions: StoreOption[],
  selectedStores: StorePreferenceKey[],
) {
  const option = getSingleStoreOption(storeOptions, selectedStores)
  if (!option) return properties.nearest_supermarket_name
  return properties[option.nearestNameField] as string | undefined
}

export function getStoreSource(
  properties: AreaProperties,
  supermarketMode: AmenityMode,
  storeOptions: StoreOption[],
  selectedStores: StorePreferenceKey[],
) {
  const option = getSingleStoreOption(storeOptions, selectedStores)
  const distanceSource = option
    ? (properties[option.nearestSourceField] as string | undefined)
    : properties.nearest_supermarket_source
  return getAmenitySource(properties, supermarketMode, distanceSource)
}

export function getTransitAccessDistance(
  properties: AreaProperties,
  selectedTransitAccess: TransitAccessKey[],
) {
  const option = getSingleTransitAccessOption(selectedTransitAccess)
  return option
    ? (properties[option.distanceField] as number | undefined)
    : properties.dist_transit_m
}

export function getTransitAccessNearestName(
  properties: AreaProperties,
  selectedTransitAccess: TransitAccessKey[],
) {
  const option = getSingleTransitAccessOption(selectedTransitAccess)
  return option
    ? (properties[option.nearestNameField] as string | undefined)
    : properties.nearest_transit_name
}

export function getTransitAccessSource(
  properties: AreaProperties,
  selectedTransitAccess: TransitAccessKey[],
) {
  const option = getSingleTransitAccessOption(selectedTransitAccess)
  return option
    ? (properties[option.nearestSourceField] as string | undefined)
    : properties.nearest_transit_source
}

export function hasTransitCommute(properties: AreaProperties) {
  return (
    typeof properties.time_work_transit_min === 'number' ||
    typeof properties.score_work_transit === 'number' ||
    Boolean(properties.transit_commute_source)
  )
}

export function weightSummary(weights: Record<WeightKey, number>) {
  const total = Object.values(weights).reduce((sum, value) => sum + value, 0)
  return (Object.keys(DEFAULT_WEIGHTS) as WeightKey[])
    .map((key) => {
      const label = METRICS.find((metric) => metric.key === key)?.label ?? key
      const share = total > 0 ? weights[key] / total : 0
      return `${label} ${weights[key]} (${formatPercent(share)})`
    })
    .join('; ')
}

export function scoreModeSummary(
  selectedMetric: MetricKey,
  workMode: WorkMode,
  supermarketMode: AmenityMode,
  gymMode: AmenityMode,
  storeOptions: StoreOption[],
  selectedStores: StorePreferenceKey[],
  selectedTransitAccess: TransitAccessKey[],
) {
  if (selectedMetric === 'work') {
    const mode = WORK_MODES.find((item) => item.key === workMode)?.label ?? workMode
    return `Work scored by ${mode.toLocaleLowerCase()}`
  }
  if (selectedMetric === 'supermarkets') {
    return `Stores scored by ${supermarketMode}; brands ${selectedStoreLabel(storeOptions, selectedStores)}`
  }
  if (selectedMetric === 'gyms') {
    return `Gyms scored by ${gymMode}`
  }
  if (selectedMetric === 'transitCommute') {
    return 'Transit commute scored by offline stop-pair approximation'
  }
  if (selectedMetric === 'combined') {
    return `Combined score using work ${workMode}, transit ${selectedTransitLabel(selectedTransitAccess)}, stores ${supermarketMode} (${selectedStoreLabel(storeOptions, selectedStores)}), gyms ${gymMode}`
  }
  if (selectedMetric === 'transit') {
    return `Transit access scored by ${selectedTransitLabel(selectedTransitAccess)}`
  }
  return 'Single metric score'
}
