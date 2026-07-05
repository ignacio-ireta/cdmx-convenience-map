import { STORE_OPTIONS, TRANSIT_ACCESS_OPTIONS } from '../constants'
import type {
  AreaFeatureCollection,
  AreaProperties,
  FieldScoreMap,
  PreferenceScoreModel,
  StoreOption,
} from '../types'

export function percentile(values: number[], fraction: number) {
  const finiteValues = values.filter(Number.isFinite)
  if (!finiteValues.length) return 1
  const sorted = [...finiteValues].sort((a, b) => a - b)
  const index = Math.min(sorted.length - 1, Math.max(0, Math.floor((sorted.length - 1) * fraction)))
  return sorted[index] || 1
}

export function scoreCloserIsBetter(values: number[]) {
  const cap = percentile(values, 0.95)
  const scores = new Map<string, number>()
  return { cap, scores }
}

export function buildCloserScoreMap(
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
      Number.isFinite(value) && value >= 0 ? 100 * (1 - Math.min(value, safeCap) / safeCap) : 0
    scores.set(areaId, Math.max(0, Math.min(100, score)))
  }
  return { hasValues: true, scores }
}

export function buildScoreRecord<Key extends string>(
  data: AreaFeatureCollection,
  options: { key: Key; field: keyof AreaProperties }[],
): Record<Key, FieldScoreMap> {
  return Object.fromEntries(
    options.map((option) => [option.key, buildCloserScoreMap(data, option.field)]),
  ) as Record<Key, FieldScoreMap>
}

export function buildPreferenceScoreModel(
  data: AreaFeatureCollection,
  storeOptions: StoreOption[] = STORE_OPTIONS,
): PreferenceScoreModel {
  return {
    storeDistanceScores: buildScoreRecord(
      data,
      storeOptions.map((option) => ({
        key: option.key,
        field: option.distanceField as keyof AreaProperties,
      })),
    ),
    storeTimeScores: buildScoreRecord(
      data,
      storeOptions.map((option) => ({
        key: option.key,
        field: option.timeField as keyof AreaProperties,
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

export function averageSelectedScores<Key extends string>(
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
