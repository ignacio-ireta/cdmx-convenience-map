// Safety display helpers for the two crime modes a city can declare:
// - 'incident_points' (CDMX, Guadalajara): per-area incident counts and density.
// - 'city_statistics' (Monterrey): one published rate per 100k residents for each
//   statistics unit (a municipality), shared by every area inside it.
// Pure functions, no app state. The incident-mode strings are CDMX's, verbatim,
// unless the caller passes `incidentWindow` (a city with `safetyWindowLabel`):
// then "recent" becomes the named data window, and an area grown by
// `crime_buffer_m` before counting says so.

import type { AreaProperties, SafetyMode, ScoreMetadata } from '../types'

export const DEFAULT_SCORED_LABEL = 'scored crime'

function finiteNumber(value?: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

export function formatRatePer100k(rate?: number) {
  const value = finiteNumber(rate)
  return value === undefined ? 'n/a' : `${value.toFixed(1)} per 100k`
}

export function formatCount(value?: number) {
  const count = finiteNumber(value)
  return count === undefined ? 'n/a' : Math.round(count).toLocaleString('en-US')
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// Stands in for the window while metadata loads or lacks its dates: still true
// (the engine counts the latest 12 months in the data), and never "recent".
export const UNDATED_INCIDENT_WINDOW = 'latest 12 months of data'

function parseIsoDate(value?: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? '')
  if (!match) return undefined
  const [year, month, day] = match.slice(1).map(Number)
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate()
  if (month < 1 || month > 12 || day < 1 || day > lastDay) return undefined
  return { year, month, day, lastDay }
}

/**
 * "Sep 2024 – Aug 2025" for an incident window from `recent_start_date` to
 * `latest_date`. The engine's window is the latest date minus 12 months, both
 * ends inclusive, so a start on a month's last day adds only that boundary day:
 * the label then starts at the next month, naming the 12 months it covers.
 * Undefined when either date is missing or malformed.
 */
export function formatCrimeWindow(start?: string, end?: string) {
  const from = parseIsoDate(start)
  const to = parseIsoDate(end)
  if (!from || !to) return undefined
  let { year, month } = from
  if (from.day === from.lastDay) {
    month += 1
    if (month > 12) {
      month = 1
      year += 1
    }
  }
  return `${MONTHS[month - 1]} ${year} – ${MONTHS[to.month - 1]} ${to.year}`
}

/** The named window for a `safetyWindowLabel` city's incident counts. */
export function incidentWindowLabel(crime?: ScoreMetadata['crime']) {
  return formatCrimeWindow(crime?.recent_start_date, crime?.latest_date) ?? UNDATED_INCIDENT_WINDOW
}

function positiveMeters(value?: number) {
  const meters = finiteNumber(value)
  return meters !== undefined && meters > 0 ? `${formatCount(meters)} m` : undefined
}

/** "250 m" when the area was grown by `crime_buffer_m` before counting incidents. */
export function crimeBufferLabel(properties: AreaProperties) {
  return positiveMeters(properties.crime_buffer_m)
}

/** "2025-10-01/2026-09-30" -> "2025-10-01 to 2026-09-30". */
export function formatStatisticsPeriod(period?: string) {
  if (!period) return 'n/a'
  const [start, end] = period.split('/')
  return start && end ? `${start} to ${end}` : period
}

/** The statistics unit (municipality) an area's rate comes from. */
export function statisticsAreaName(properties: AreaProperties) {
  return properties.crime_statistics_area || properties.alcaldia || undefined
}

function scopeRateLabel(properties: AreaProperties) {
  const scope = properties.crime_statistics_scope || 'municipality'
  return scope === 'municipality' ? 'municipal rate' : `${scope} rate`
}

/** "{rate} per 100k · {scored_label} ({municipio})". */
export function formatSafetyStatistic(
  properties: AreaProperties,
  scoredLabel: string = DEFAULT_SCORED_LABEL,
) {
  const rate = formatRatePer100k(properties.crime_rate_per_100k_12m)
  const area = statisticsAreaName(properties)
  return area ? `${rate} · ${scoredLabel} (${area})` : `${rate} · ${scoredLabel}`
}

/** "All postal codes in {municipio} share this municipal rate". */
export function safetyScopeNote(properties: AreaProperties, pluralAreaLabel: string) {
  const area = statisticsAreaName(properties)
  const rateLabel = scopeRateLabel(properties)
  return area
    ? `All ${pluralAreaLabel.toLocaleLowerCase()} in ${area} share this ${rateLabel}`
    : `Every area in the same statistics unit shares this ${rateLabel}`
}

/** "{scored} {scored_label} · {all} total" incidents over the statistics period. */
export function formatStatisticsIncidents(
  properties: AreaProperties,
  scoredLabel: string = DEFAULT_SCORED_LABEL,
) {
  return `${formatCount(properties.crime_scope_scored_incidents_12m)} ${scoredLabel} · ${formatCount(
    properties.crime_scope_incidents_12m,
  )} total`
}

/**
 * The two bottom lines of the Safety breakdown row. Incident mode reads
 * "{n} recent incidents" (CDMX), or with `incidentWindow`
 * "{n} incidents within the area + {R} m · {window}".
 */
export function safetyMetricDetail(
  properties: AreaProperties,
  mode: SafetyMode,
  scoredLabel: string = DEFAULT_SCORED_LABEL,
  incidentWindow?: string,
): { value: string; nearest: string } {
  if (mode === 'city_statistics') {
    const area = statisticsAreaName(properties)
    return {
      value: formatRatePer100k(properties.crime_rate_per_100k_12m),
      nearest: area ? `${scoredLabel} (${area})` : scoredLabel,
    }
  }
  if (incidentWindow === undefined) {
    return {
      value: `${properties.crime_incidents_recent_12m ?? 0} recent incidents`,
      nearest: properties.crime_top_category_recent_12m || 'No recent category',
    }
  }
  const count = finiteNumber(properties.crime_incidents_recent_12m)
  const noun = count === 1 ? 'incident' : 'incidents'
  const buffer = crimeBufferLabel(properties)
  const scope = buffer ? ` within the area + ${buffer}` : ''
  return {
    value: `${formatCount(count)} ${noun}${scope} · ${incidentWindow}`,
    nearest: properties.crime_top_category_recent_12m || 'No top category',
  }
}

/**
 * The details-list density: CDMX's "{d}/km2" (missing reads 0.0), or with
 * `incidentWindow` "{d}/km² (area + {R} m)" and n/a when missing.
 */
export function formatCrimeDensity(properties: AreaProperties, incidentWindow?: string) {
  if (incidentWindow === undefined) {
    return `${(properties.crime_density_recent_12m_per_km2 ?? 0).toFixed(1)}/km2`
  }
  const density = finiteNumber(properties.crime_density_recent_12m_per_km2)
  if (density === undefined) return 'n/a'
  const buffer = crimeBufferLabel(properties)
  return buffer ? `${density.toFixed(1)}/km² (area + ${buffer})` : `${density.toFixed(1)}/km²`
}

/**
 * The details-list all-records count: CDMX's bare number (missing reads 0), or
 * with `incidentWindow` a grouped count, "(area + {R} m)" when buffered.
 */
export function formatCrimeRecordsTotal(properties: AreaProperties, incidentWindow?: string) {
  if (incidentWindow === undefined) return String(properties.crime_incidents_total ?? 0)
  const total = formatCount(properties.crime_incidents_total)
  const buffer = crimeBufferLabel(properties)
  return buffer ? `${total} (area + ${buffer})` : total
}

/** Suffix of the data-audit Crime row, after the city's safety source label. */
export function safetyAuditSuffix(
  mode: SafetyMode,
  crime?: ScoreMetadata['crime'],
  incidentWindow?: string,
) {
  if (mode === 'city_statistics') {
    const units = crime?.units?.length ?? 'n/a'
    const plural = (crime?.scope ?? 'municipality') === 'municipality' ? 'municipalities' : 'units'
    return ` · ${units} ${plural}`
  }
  if (incidentWindow === undefined) {
    return ` · ${crime?.records_recent_12m ?? 'n/a'} recent records`
  }
  const buffer = positiveMeters(crime?.density_buffer_m)
  const counted = buffer ? ` · counted within each area + ${buffer}` : ''
  return ` · ${formatCount(crime?.records_recent_12m)} records · ${incidentWindow}${counted}`
}

/** What the statistics-mode score counts: the definition, else the offense list. */
export function scoredCrimesDefinition(crime?: ScoreMetadata['crime']) {
  const definition = crime?.scored_definition?.trim()
  if (definition) return definition
  const offenses = (crime?.scored_offenses ?? []).filter(
    (offense) => typeof offense === 'string' && offense.trim(),
  )
  return offenses.length ? offenses.join(', ') : undefined
}

/** How rates became scores, for the methods this UI can describe; else undefined. */
export function safetyMethodNote(crime?: ScoreMetadata['crime']) {
  if (crime?.score_method !== 'min_max_across_units') return undefined
  const scope = crime.scope ?? 'municipality'
  const rate = scope === 'municipality' ? 'municipal rate' : `${scope} rate`
  return `Ranked within the metro: lowest ${rate} = 100, highest = 0`
}

/**
 * Extra copied-report lines in statistics mode: what the score counts and how
 * rates became scores, each only when the metadata states it. None in incident
 * mode, so CDMX's report is unchanged.
 */
export function safetyReportLines(mode: SafetyMode, crime?: ScoreMetadata['crime']) {
  if (mode !== 'city_statistics') return []
  const scoredCrimes = scoredCrimesDefinition(crime)
  const method = safetyMethodNote(crime)
  return [
    ...(scoredCrimes ? [`Scored crimes: ${scoredCrimes}`] : []),
    ...(method ? [`Safety method: ${method}`] : []),
  ]
}
