// Low-level value coercion + display formatting helpers (pure, no app state).

export function stringFrom(value: unknown) {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return ''
}

export function optionalString(value: unknown) {
  const text = stringFrom(value)
  return text || undefined
}

export function numberFrom(value: unknown) {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const numeric = Number(value)
    return Number.isFinite(numeric) ? numeric : undefined
  }
  return undefined
}

export function colorForScore(score: number) {
  if (score >= 85) return '#166534'
  if (score >= 70) return '#2f9e44'
  if (score >= 55) return '#9ac43e'
  if (score >= 40) return '#f2c94c'
  if (score >= 25) return '#f2994a'
  return '#d94841'
}

export function verdict(score: number) {
  if (score >= 78) return 'Convenient'
  if (score >= 58) return 'Manageable'
  if (score >= 38) return 'Mixed'
  return 'Annoying'
}

export function formatMeters(value?: number) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'n/a'
  if (value >= 1000) return `${(value / 1000).toFixed(1)} km`
  return `${Math.round(value)} m`
}

export function formatMinutes(value?: number) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'n/a'
  if (value >= 60) {
    const hours = Math.floor(value / 60)
    const minutes = Math.round(value % 60)
    return `${hours} hr ${minutes} min`
  }
  return `${Math.round(value)} min`
}

export function formatDistanceAndTime(distance?: number, minutes?: number) {
  return `${formatMeters(distance)} / ${formatMinutes(minutes)}`
}

export function formatAmenityDetail(name?: string, distance?: number, minutes?: number) {
  const detail = formatDistanceAndTime(distance, minutes)
  return name ? `${name} · ${detail}` : detail
}

export function scoreText(value?: number) {
  const score = typeof value === 'number' && Number.isFinite(value) ? value : 0
  return `${Math.round(score * 10) / 10}`
}

export function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`
}

export function formatSource(source?: string) {
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

export function transitStopLabel(system?: string, name?: string, line?: string) {
  if (!name) return 'n/a'
  const prefix = [system, line].filter(Boolean).join(' ')
  return prefix ? `${prefix} ${name}` : name
}

export function formatTransitComplexity(value?: string) {
  if (value === 'same_line') return 'Same line'
  if (value === 'same_system_different_line') return 'Same system, different line'
  if (value === 'same_system_unknown_line') return 'Same system, line unknown'
  if (value === 'different_system') return 'Different systems'
  return value || 'n/a'
}
