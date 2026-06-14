import { useEffect, useMemo, useState } from 'react'
import { Check, ClipboardCopy, Database, MapPinned, Search } from 'lucide-react'
import L, { type Layer, type PathOptions } from 'leaflet'
import { GeoJSON, MapContainer, TileLayer } from 'react-leaflet'
import type { Feature, Geometry } from 'geojson'
import './App.css'

import {
  AMENITY_MODES,
  CITY_CONFIGS,
  DATA_FOCUS_PADDING,
  LEGEND_STEPS,
  METRICS,
  SELECTED_AREA_FOCUS_PADDING,
  SELECTED_AREA_MAX_ZOOM,
  WORK_MODES,
} from './constants'
import type {
  AmenityMode,
  AreaDatasets,
  AreaFeature,
  AreaFocusRequest,
  AreaProperties,
  AreaUnit,
  MetricKey,
  RawAreaFeatureCollection,
  ScoreMetadata,
  SearchMatch,
  StorePreferenceKey,
  TransitAccessKey,
  WeightKey,
  WorkMode,
  WorkModel,
} from './types'
import {
  colorForScore,
  formatAmenityDetail,
  formatDistanceAndTime,
  formatMeters,
  formatMinutes,
  formatSource,
  formatTransitComplexity,
  scoreText,
  sourceBadge,
  transitStopLabel,
  verdict,
} from './lib/format'
import { normalizeAreaCollection, normalizePostalCode } from './lib/normalize'
import { fetchRoutedWorkTimes, loadMatrixIndex } from './lib/routingMatrix'
import {
  areaFullLabel,
  areaResultLabel,
  areaUnitLabel,
  getAreaSearchRank,
  normalizeSearchText,
  toggleRequiredSelection,
} from './lib/search'
import { buildPreferenceScoreModel } from './lib/score-math'
import {
  buildWorkModel,
  getWorkDistance,
  getWorkName,
  getWorkScore,
  getWorkSource,
  getWorkTime,
} from './lib/work'
import {
  getAmenitySource,
  getGymScore,
  getScore,
  getStoreDetailValue,
  getStoreNearestName,
  getStoreSource,
  getSupermarketScore,
  getTransitAccessDistance,
  getTransitAccessNearestName,
  getTransitAccessScore,
  getTransitAccessSource,
  hasTransitCommute,
  scoreModeSummary,
  selectedStoreLabel,
  selectedTransitLabel,
  weightSummary,
} from './lib/scoring'

function App() {
  const city =
    new URLSearchParams(window.location.search).get('city') === 'oslo'
      ? CITY_CONFIGS.oslo
      : CITY_CONFIGS.cdmx
  const [selectedAreaUnit, setSelectedAreaUnit] = useState<AreaUnit>('postal_code')
  const [datasets, setDatasets] = useState<AreaDatasets>({})
  const [metadata, setMetadata] = useState<ScoreMetadata | null>(null)
  const [selectedMetric, setSelectedMetric] = useState<MetricKey>('combined')
  const [workMode, setWorkMode] = useState<WorkMode>('distance')
  const [supermarketMode, setSupermarketMode] = useState<AmenityMode>('distance')
  const [gymMode, setGymMode] = useState<AmenityMode>('distance')
  const [selectedStores, setSelectedStores] = useState<StorePreferenceKey[]>(
    city.stores.map((option) => option.key),
  )
  const [selectedTransitAccess, setSelectedTransitAccess] = useState<TransitAccessKey[]>(
    city.transit.map((option) => option.key),
  )
  const [weights, setWeights] = useState<Record<WeightKey, number>>(city.weights)
  const [selected, setSelected] = useState<AreaFeature | null>(null)
  const [selectedFocus, setSelectedFocus] = useState<AreaFocusRequest | null>(null)
  const [query, setQuery] = useState('')
  const [workCodeDraft, setWorkCodeDraft] = useState('')
  const [workPostalCode, setWorkPostalCode] = useState('')
  const [workCodeError, setWorkCodeError] = useState('')
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'failed'>('idle')
  const [loadError, setLoadError] = useState('')
  const data = datasets[selectedAreaUnit] ?? null
  const postalData = datasets.postal_code ?? null
  const selectedGeography =
    city.geographies.find((geography) => geography.unit === selectedAreaUnit) ??
    city.geographies[0]
  const selectedWorkMode = WORK_MODES.find((mode) => mode.key === workMode) ?? WORK_MODES[0]

  useEffect(() => {
    const cached = datasets[selectedAreaUnit]
    if (cached) return

    let cancelled = false
    fetch(city.assets.scores[selectedAreaUnit])
      .then((response) => {
        if (!response.ok) {
          throw new Error(`GeoJSON request failed: ${response.status}`)
        }
        return response.json()
      })
      .then((payload: RawAreaFeatureCollection) => {
        if (cancelled) return
        const normalized = normalizeAreaCollection(payload, city.postalWidth)
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
  }, [city, datasets, selectedAreaUnit])

  useEffect(() => {
    fetch(city.assets.metadata[selectedAreaUnit])
      .then((response) => (response.ok ? response.json() : fetch(city.assets.scoreMetadata)))
      .then((payloadOrResponse: ScoreMetadata | Response | null) =>
        payloadOrResponse instanceof Response
          ? payloadOrResponse.ok
            ? payloadOrResponse.json()
            : null
          : payloadOrResponse,
      )
      .then((payload: ScoreMetadata | null) => setMetadata(payload))
      .catch(() => setMetadata(null))
  }, [city, selectedAreaUnit])

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

  // Immediate, synchronous straight-line model for a custom workplace.
  const haversineWorkModel = useMemo(() => {
    if (!data || !workFeature) return null
    if (
      !Number.isFinite(workFeature.properties.centroid_lat) ||
      !Number.isFinite(workFeature.properties.centroid_lon)
    ) {
      return null
    }
    return buildWorkModel(data, workFeature)
  }, [data, workFeature])

  // If a precomputed routed matrix covers the selected workplace, overlay real
  // routed times asynchronously. Absent matrix (or cross-unit workplace) keeps the
  // labeled straight-line estimate. See lib/routingMatrix.ts.
  const [routedWork, setRoutedWork] = useState<{ unit: AreaUnit; model: WorkModel } | null>(null)
  useEffect(() => {
    if (!data || !workFeature) return
    let cancelled = false
    void (async () => {
      const index = await loadMatrixIndex(selectedAreaUnit)
      if (cancelled || !index) return
      const routedTimes = await fetchRoutedWorkTimes(index, workFeature.properties.area_id)
      if (cancelled || !routedTimes) return
      setRoutedWork({
        unit: selectedAreaUnit,
        model: buildWorkModel(data, workFeature, routedTimes),
      })
    })()
    return () => {
      cancelled = true
    }
  }, [data, workFeature, selectedAreaUnit])

  // Use the routed model only when it matches the current view + workplace; a stale
  // routed model (different unit/workplace, or still loading) falls back to haversine.
  const workModel =
    routedWork &&
    workFeature &&
    routedWork.unit === selectedAreaUnit &&
    routedWork.model.areaId === workFeature.properties.area_id
      ? routedWork.model
      : haversineWorkModel

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
    const postalQuery = normalizePostalCode(trimmedSearchQuery, city.postalWidth)
    if (!normalizedQuery && !postalQuery) return []

    return data.features
      .map((feature) => {
        const rank = getAreaSearchRank(feature.properties, normalizedQuery, postalQuery)
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
  }, [city.postalWidth, data, trimmedSearchQuery])

  const searchResults = searchMatches.slice(0, 12)

  const topListCopyText = useMemo(() => {
    const metricLabel =
      METRICS.find((metric) => metric.key === selectedMetric)?.label ?? selectedMetric
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
    workModel?.areaId ?? 'sample-work'
  }-${selectedAreaUnit}-${workMode}-${supermarketMode}-${gymMode}-${selectedStores.join('.')}-${selectedTransitAccess.join('.')}`
  const mapInstanceKey = `${selectedAreaUnit}-${selectedFocus?.requestId ?? 'all'}`
  const mapBounds = useMemo(() => {
    const focusTarget = selectedFocus?.feature ?? data
    if (!focusTarget) return null

    const bounds = L.geoJSON(focusTarget).getBounds()
    return bounds.isValid() ? bounds : null
  }, [data, selectedFocus])
  const mapBoundsOptions = selectedFocus
    ? {
        animate: false,
        maxZoom: SELECTED_AREA_MAX_ZOOM,
        padding: SELECTED_AREA_FOCUS_PADDING,
      }
    : { animate: false, padding: DATA_FOCUS_PADDING }

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

  const onEachArea = (feature: Feature<Geometry, AreaProperties>, layer: Layer) => {
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
        layer.bindTooltip(`${areaFullLabel(feature.properties)} · ${scoreText(score)}`, {
          sticky: true,
        })
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
              <p className="eyebrow">{city.eyebrow}</p>
              <h1>Area convenience map</h1>
            </div>
          </div>
          <p className="status-line">
            {data
              ? `${data.features.length} ${selectedGeography.pluralLabel.toLocaleLowerCase()} scored`
              : `Loading ${selectedGeography.pluralLabel.toLocaleLowerCase()}`}
          </p>
        </header>

        <label className="city-picker">
          <span>City</span>
          <select
            value={city.id}
            onChange={(event) => {
              window.location.search = event.target.value === 'oslo' ? '?city=oslo' : ''
            }}
          >
            <option value="cdmx">CDMX</option>
            <option value="oslo">Oslo</option>
          </select>
        </label>

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
            {city.geographies.map((geography) => (
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
                maxLength={city.postalWidth}
                placeholder={city.postalPlaceholder}
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
                {city.stores.map((option) => (
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
                {city.transit.map((option) => (
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
                {city.safetySource}
                {city.id === 'cdmx'
                  ? ` · ${metadata?.crime?.records_recent_12m ?? 'n/a'} recent records`
                  : ''}
              </dd>
            </div>
          </dl>
        </section>

        <section className="panel-section">
          <div className="section-heading">
            <h2>Weights</h2>
            <span>Combined</span>
          </div>
          {(Object.keys(city.weights) as WeightKey[]).map((key) => (
            <label className="weight-row" key={key}>
              <span>{METRICS.find((metric) => metric.key === key)?.label}</span>
              <input
                type="range"
                min="0"
                max="60"
                step="1"
                value={weights[key]}
                onChange={(event) => updateWeight(key, Number(event.target.value))}
                onInput={(event) => updateWeight(key, Number(event.currentTarget.value))}
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
                      : formatMinutes(getWorkTime(selected.properties, workModel, workMode))
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
                  distance={getTransitAccessDistance(selected.properties, selectedTransitAccess)}
                  nearest={getTransitAccessNearestName(selected.properties, selectedTransitAccess)}
                  source={getTransitAccessSource(selected.properties, selectedTransitAccess)}
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
                  value={getStoreDetailValue(selected.properties, supermarketMode, selectedStores)}
                  nearest={getStoreNearestName(selected.properties, selectedStores)}
                  source={getStoreSource(selected.properties, supermarketMode, selectedStores)}
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
                    selected.properties.crime_top_category_recent_12m || 'No recent category'
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
                {city.transit.map((option) => (
                  <div key={option.key}>
                    <dt>{option.label}</dt>
                    <dd>
                      {formatMeters(
                        selected.properties[option.distanceField] as number | undefined,
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
                      <dd>{formatMeters(selected.properties.transit_origin_walk_m)}</dd>
                    </div>
                    <div>
                      <dt>Destination walk</dt>
                      <dd>{formatMeters(selected.properties.transit_destination_walk_m)}</dd>
                    </div>
                    <div>
                      <dt>Transfer penalty</dt>
                      <dd>{formatMinutes(selected.properties.transit_transfer_penalty_min)}</dd>
                    </div>
                    <div>
                      <dt>Route complexity</dt>
                      <dd>
                        {formatTransitComplexity(selected.properties.transit_route_complexity)}
                      </dd>
                    </div>
                    <div className="raw-note">
                      <dt>Transit source</dt>
                      <dd>{formatSource(selected.properties.transit_commute_source)}</dd>
                    </div>
                    <div className="raw-note">
                      <dt>Transit note</dt>
                      <dd>{selected.properties.transit_commute_notes || 'n/a'}</dd>
                    </div>
                  </>
                ) : null}
                <div>
                  <dt>Crime density</dt>
                  <dd>
                    {(selected.properties.crime_density_recent_12m_per_km2 ?? 0).toFixed(1)}
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
            className="leaflet-map"
            key={mapInstanceKey}
            maxZoom={16}
            minZoom={9}
            {...(mapBounds
              ? { bounds: mapBounds, boundsOptions: mapBoundsOptions }
              : { center: city.mapCenter, zoom: city.mapZoom })}
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <GeoJSON data={data} key={mapKey} onEachFeature={onEachArea} style={areaStyle} />
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
                  {copyStatus === 'copied' ? 'Copied' : copyStatus === 'failed' ? 'Failed' : 'Copy'}
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
    typeof score === 'number' && Number.isFinite(score) ? Math.max(0, Math.min(100, score)) : 0
  const badge = sourceBadge(source)

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
      <div className="metric-source">
        {badge ? <span className={`source-badge source-badge-${badge}`}>{badge}</span> : null}
        {formatSource(source)}
      </div>
    </div>
  )
}

export default App
