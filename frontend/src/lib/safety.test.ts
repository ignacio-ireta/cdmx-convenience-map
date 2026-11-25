import { describe, expect, it } from 'vitest'
import { bufferedIncidentProps, props, statisticsProps } from '../test/fixtures'
import {
  DEFAULT_SCORED_LABEL,
  UNDATED_INCIDENT_WINDOW,
  crimeBufferLabel,
  formatCount,
  formatCrimeDensity,
  formatCrimeRecordsTotal,
  formatCrimeWindow,
  formatRatePer100k,
  formatSafetyStatistic,
  formatStatisticsIncidents,
  formatStatisticsPeriod,
  incidentWindowLabel,
  safetyAuditSuffix,
  safetyMethodNote,
  safetyMetricDetail,
  safetyReportLines,
  safetyScopeNote,
  scoredCrimesDefinition,
  statisticsAreaName,
} from './safety'

// Guadalajara's IIEG window as the engine writes it (latest date minus 12 months).
const GDL_CRIME = {
  records_total: 483269,
  records_recent_12m: 36631,
  recent_start_date: '2024-08-31',
  latest_date: '2025-08-31',
  density_buffer_m: 250,
}
const GDL_WINDOW = 'Sep 2024 – Aug 2025'

// Monterrey's statistics block after the min-max change, with the profile's definition.
const MTY_CRIME = {
  mode: 'city_statistics',
  scope: 'municipality',
  scored_label: 'robbery and violent crime',
  scored_definition:
    'All robbery, intentional homicide and feminicide (including attempts), intentional injury, kidnapping, extortion and rape',
  scored_offenses: ['Robo', 'Homicidio doloso', 'Lesiones dolosas'],
  score_method: 'min_max_across_units',
}

describe('statistics-mode formatting', () => {
  it('formats a rate per 100k with one decimal, n/a when missing', () => {
    expect(formatRatePer100k(1639)).toBe('1639.0 per 100k')
    expect(formatRatePer100k(12.345)).toBe('12.3 per 100k')
    expect(formatRatePer100k(0)).toBe('0.0 per 100k')
    expect(formatRatePer100k(undefined)).toBe('n/a')
    expect(formatRatePer100k(Number.NaN)).toBe('n/a')
  })

  it('formats counts with thousands separators', () => {
    expect(formatCount(1142994)).toBe('1,142,994')
    expect(formatCount(0)).toBe('0')
    expect(formatCount(undefined)).toBe('n/a')
  })

  it('formats the statistics period', () => {
    expect(formatStatisticsPeriod('2025-10-01/2026-09-30')).toBe('2025-10-01 to 2026-09-30')
    expect(formatStatisticsPeriod('2026')).toBe('2026')
    expect(formatStatisticsPeriod(undefined)).toBe('n/a')
  })

  it('names the municipality from the statistics unit, then the area municipality', () => {
    expect(statisticsAreaName(statisticsProps())).toBe('Monterrey')
    expect(statisticsAreaName(statisticsProps({ crime_statistics_area: undefined }))).toBe(
      'Monterrey',
    )
    expect(
      statisticsAreaName(
        statisticsProps({ crime_statistics_area: undefined, alcaldia: undefined }),
      ),
    ).toBeUndefined()
  })

  it('reads "{rate} per 100k · {scored_label} ({municipio})"', () => {
    expect(formatSafetyStatistic(statisticsProps(), 'street crime')).toBe(
      '1639.0 per 100k · street crime (Monterrey)',
    )
    expect(
      formatSafetyStatistic(
        statisticsProps({
          crime_statistics_area: 'San Pedro Garza García',
          crime_rate_per_100k_12m: 402.04,
        }),
        'street crime',
      ),
    ).toBe('402.0 per 100k · street crime (San Pedro Garza García)')
    expect(formatSafetyStatistic(statisticsProps())).toBe(
      `1639.0 per 100k · ${DEFAULT_SCORED_LABEL} (Monterrey)`,
    )
  })

  it('says every area of the municipality shares the rate', () => {
    expect(safetyScopeNote(statisticsProps(), 'Postal codes')).toBe(
      'All postal codes in Monterrey share this municipal rate',
    )
    expect(safetyScopeNote(statisticsProps({ area_unit: 'colonia' }), 'Colonias')).toBe(
      'All colonias in Monterrey share this municipal rate',
    )
    expect(
      safetyScopeNote(
        statisticsProps({ crime_statistics_area: undefined, alcaldia: undefined }),
        'Postal codes',
      ),
    ).toBe('Every area in the same statistics unit shares this municipal rate')
  })

  it('reports scored and total municipal incidents', () => {
    expect(formatStatisticsIncidents(statisticsProps(), 'street crime')).toBe(
      '18,734 street crime · 41,250 total',
    )
    expect(formatStatisticsIncidents(props({}), 'street crime')).toBe(
      'n/a street crime · n/a total',
    )
  })
})

describe('safetyMetricDetail', () => {
  it('keeps the CDMX incident-mode strings', () => {
    expect(
      safetyMetricDetail(
        props({
          crime_incidents_recent_12m: 214,
          crime_top_category_recent_12m: 'Robo a transeúnte',
        }),
        'incident_points',
      ),
    ).toEqual({ value: '214 recent incidents', nearest: 'Robo a transeúnte' })
    expect(safetyMetricDetail(props({}), 'incident_points')).toEqual({
      value: '0 recent incidents',
      nearest: 'No recent category',
    })
  })

  it('shows the municipal rate in statistics mode, without fake incident counts', () => {
    const detail = safetyMetricDetail(statisticsProps(), 'city_statistics', 'street crime')
    expect(detail).toEqual({ value: '1639.0 per 100k', nearest: 'street crime (Monterrey)' })
    expect(
      safetyMetricDetail(
        statisticsProps({ crime_rate_per_100k_12m: undefined }),
        'city_statistics',
        'street crime',
      ).value,
    ).toBe('n/a')
  })
})

describe('safetyAuditSuffix', () => {
  it('keeps the CDMX recent-records suffix', () => {
    expect(safetyAuditSuffix('incident_points', { records_recent_12m: 231158 })).toBe(
      ' · 231158 recent records',
    )
    expect(safetyAuditSuffix('incident_points', undefined)).toBe(' · n/a recent records')
  })

  it('counts the matched municipalities in statistics mode', () => {
    expect(
      safetyAuditSuffix('city_statistics', {
        scope: 'municipality',
        units: [{ key: '19039' }, { key: '19019' }],
      }),
    ).toBe(' · 2 municipalities')
    expect(safetyAuditSuffix('city_statistics', undefined)).toBe(' · n/a municipalities')
  })
})

describe('crime window labels', () => {
  it('names the 12 whole months of a window that starts on a month end', () => {
    expect(formatCrimeWindow('2024-08-31', '2025-08-31')).toBe(GDL_WINDOW)
    expect(formatCrimeWindow('2024-12-31', '2025-12-31')).toBe('Jan 2025 – Dec 2025')
    expect(formatCrimeWindow('2023-02-28', '2024-02-29')).toBe('Mar 2023 – Feb 2024')
  })

  it('keeps the start month when the window starts inside it', () => {
    expect(formatCrimeWindow('2025-11-01', '2026-10-31')).toBe('Nov 2025 – Oct 2026')
    expect(formatCrimeWindow('2024-08-15', '2025-08-15')).toBe('Aug 2024 – Aug 2025')
    // 2024 is a leap year, so Feb 28 is not that month's last day.
    expect(formatCrimeWindow('2024-02-28', '2025-02-28')).toBe('Feb 2024 – Feb 2025')
  })

  it('returns undefined for missing or malformed dates', () => {
    expect(formatCrimeWindow(undefined, '2025-08-31')).toBeUndefined()
    expect(formatCrimeWindow('2024-08-31', undefined)).toBeUndefined()
    expect(formatCrimeWindow('2024-13-01', '2025-08-31')).toBeUndefined()
    expect(formatCrimeWindow('2023-02-29', '2025-08-31')).toBeUndefined()
    expect(formatCrimeWindow('Aug 2024', '2025-08-31')).toBeUndefined()
  })

  it('reads the window from the metadata, never "recent" when it is missing', () => {
    expect(incidentWindowLabel(GDL_CRIME)).toBe(GDL_WINDOW)
    expect(incidentWindowLabel(undefined)).toBe(UNDATED_INCIDENT_WINDOW)
    expect(incidentWindowLabel({ latest_date: '2025-08-31' })).toBe(UNDATED_INCIDENT_WINDOW)
    expect(UNDATED_INCIDENT_WINDOW).not.toMatch(/recent/)
  })

  it('labels a positive crime buffer only', () => {
    expect(crimeBufferLabel(bufferedIncidentProps())).toBe('250 m')
    expect(crimeBufferLabel(bufferedIncidentProps({ crime_buffer_m: 1000 }))).toBe('1,000 m')
    expect(crimeBufferLabel(bufferedIncidentProps({ crime_buffer_m: 0 }))).toBeUndefined()
    expect(crimeBufferLabel(bufferedIncidentProps({ crime_buffer_m: undefined }))).toBeUndefined()
    expect(crimeBufferLabel(props({}))).toBeUndefined()
  })
})

describe('incident mode with a named window (safetyWindowLabel)', () => {
  it('counts within the buffered area over the named window', () => {
    expect(
      safetyMetricDetail(bufferedIncidentProps(), 'incident_points', undefined, GDL_WINDOW),
    ).toEqual({
      value: '339 incidents within the area + 250 m · Sep 2024 – Aug 2025',
      nearest: 'Robo a negocio',
    })
  })

  it('drops the buffer phrase without crime_buffer_m and keeps counts honest', () => {
    const unbuffered = bufferedIncidentProps({ crime_buffer_m: undefined })
    expect(safetyMetricDetail(unbuffered, 'incident_points', undefined, GDL_WINDOW).value).toBe(
      '339 incidents · Sep 2024 – Aug 2025',
    )
    expect(
      safetyMetricDetail(
        bufferedIncidentProps({ crime_incidents_recent_12m: 1 }),
        'incident_points',
        undefined,
        GDL_WINDOW,
      ).value,
    ).toBe('1 incident within the area + 250 m · Sep 2024 – Aug 2025')
    expect(
      safetyMetricDetail(
        bufferedIncidentProps({
          crime_incidents_recent_12m: undefined,
          crime_top_category_recent_12m: undefined,
        }),
        'incident_points',
        undefined,
        GDL_WINDOW,
      ),
    ).toEqual({
      value: 'n/a incidents within the area + 250 m · Sep 2024 – Aug 2025',
      nearest: 'No top category',
    })
  })

  it('never says "recent" once a window is named', () => {
    const detail = safetyMetricDetail(
      bufferedIncidentProps({ crime_top_category_recent_12m: undefined }),
      'incident_points',
      undefined,
      UNDATED_INCIDENT_WINDOW,
    )
    expect(`${detail.value} ${detail.nearest}`).not.toMatch(/recent/)
    expect(safetyAuditSuffix('incident_points', GDL_CRIME, GDL_WINDOW)).not.toMatch(/recent/)
  })

  it('labels density and the all-records count with the buffer', () => {
    expect(formatCrimeDensity(bufferedIncidentProps(), GDL_WINDOW)).toBe('151.3/km² (area + 250 m)')
    expect(
      formatCrimeDensity(bufferedIncidentProps({ crime_buffer_m: undefined }), GDL_WINDOW),
    ).toBe('151.3/km²')
    expect(
      formatCrimeDensity(
        bufferedIncidentProps({ crime_density_recent_12m_per_km2: undefined }),
        GDL_WINDOW,
      ),
    ).toBe('n/a')
    expect(formatCrimeRecordsTotal(bufferedIncidentProps(), GDL_WINDOW)).toBe(
      '4,821 (area + 250 m)',
    )
    expect(
      formatCrimeRecordsTotal(
        bufferedIncidentProps({ crime_incidents_total: undefined }),
        GDL_WINDOW,
      ),
    ).toBe('n/a (area + 250 m)')
  })

  it('names the window and the buffer in the audit row', () => {
    expect(safetyAuditSuffix('incident_points', GDL_CRIME, GDL_WINDOW)).toBe(
      ' · 36,631 records · Sep 2024 – Aug 2025 · counted within each area + 250 m',
    )
    expect(
      safetyAuditSuffix(
        'incident_points',
        { ...GDL_CRIME, density_buffer_m: undefined },
        GDL_WINDOW,
      ),
    ).toBe(' · 36,631 records · Sep 2024 – Aug 2025')
    expect(safetyAuditSuffix('incident_points', undefined, UNDATED_INCIDENT_WINDOW)).toBe(
      ' · n/a records · latest 12 months of data',
    )
  })
})

describe('CDMX incident strings stay verbatim without a named window', () => {
  it('ignores crime_buffer_m and keeps "recent" and "/km2"', () => {
    const area = bufferedIncidentProps({ crime_top_category_recent_12m: undefined })
    expect(safetyMetricDetail(area, 'incident_points')).toEqual({
      value: '339 recent incidents',
      nearest: 'No recent category',
    })
    expect(formatCrimeDensity(area)).toBe('151.3/km2')
    expect(formatCrimeDensity(props({}))).toBe('0.0/km2')
    expect(formatCrimeRecordsTotal(area)).toBe('4821')
    expect(formatCrimeRecordsTotal(props({}))).toBe('0')
    expect(safetyAuditSuffix('incident_points', GDL_CRIME)).toBe(' · 36631 recent records')
  })
})

describe('statistics mode definition and method', () => {
  it('shows the scored definition, else the offense list', () => {
    expect(scoredCrimesDefinition(MTY_CRIME)).toBe(MTY_CRIME.scored_definition)
    expect(scoredCrimesDefinition({ ...MTY_CRIME, scored_definition: '  ' })).toBe(
      'Robo, Homicidio doloso, Lesiones dolosas',
    )
    expect(scoredCrimesDefinition({ scored_offenses: [] })).toBeUndefined()
    expect(scoredCrimesDefinition(undefined)).toBeUndefined()
  })

  it('describes min-max ranking within the metro, and nothing it does not know', () => {
    expect(safetyMethodNote(MTY_CRIME)).toBe(
      'Ranked within the metro: lowest municipal rate = 100, highest = 0',
    )
    expect(safetyMethodNote({ ...MTY_CRIME, scope: 'state' })).toBe(
      'Ranked within the metro: lowest state rate = 100, highest = 0',
    )
    expect(safetyMethodNote({ ...MTY_CRIME, score_method: 'p95_inverse' })).toBeUndefined()
    expect(safetyMethodNote({ scope: 'municipality' })).toBeUndefined()
    expect(safetyMethodNote(undefined)).toBeUndefined()
  })

  it('adds report lines in statistics mode only', () => {
    expect(safetyReportLines('city_statistics', MTY_CRIME)).toEqual([
      `Scored crimes: ${MTY_CRIME.scored_definition}`,
      'Safety method: Ranked within the metro: lowest municipal rate = 100, highest = 0',
    ])
    expect(safetyReportLines('city_statistics', { scope: 'municipality' })).toEqual([])
    expect(safetyReportLines('incident_points', MTY_CRIME)).toEqual([])
  })

  it('carries the longer scored label into the statistics strings', () => {
    const label = MTY_CRIME.scored_label
    const sanPedro = statisticsProps({
      crime_statistics_area: 'San Pedro Garza García',
      crime_rate_per_100k_12m: 209.6,
      crime_scope_scored_incidents_12m: 3785,
      crime_scope_incidents_12m: 20377,
    })
    expect(safetyMetricDetail(sanPedro, 'city_statistics', label)).toEqual({
      value: '209.6 per 100k',
      nearest: 'robbery and violent crime (San Pedro Garza García)',
    })
    expect(formatSafetyStatistic(sanPedro, label)).toBe(
      '209.6 per 100k · robbery and violent crime (San Pedro Garza García)',
    )
    expect(formatStatisticsIncidents(sanPedro, label)).toBe(
      '3,785 robbery and violent crime · 20,377 total',
    )
  })

  it('ignores a named window in statistics mode', () => {
    expect(safetyMetricDetail(statisticsProps(), 'city_statistics', 'x', GDL_WINDOW).value).toBe(
      '1639.0 per 100k',
    )
    expect(
      safetyAuditSuffix('city_statistics', { scope: 'municipality', units: [] }, GDL_WINDOW),
    ).toBe(' · 0 municipalities')
  })
})
