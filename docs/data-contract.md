# Data Contract

The authoritative input/output contract for the pipeline (engineering standards
§G). "Extract a city to a scored map" sounds simple but is full of ambiguity;
this document pins down what each source contributes and the exact shape of the
output so downstream consumers (the frontend, future writers, LLM ingestion) can
rely on it. The output property list is enforced by `cdmxmap validate`
(`scripts/validate_processed.py`).

## Inputs (per source)

| Source | Provider | In scope (v0.1) | Out of scope / best-effort |
|---|---|---|---|
| **Postal codes** | CDMX open data — Códigos Postales | polygons; `d_cp` / `postal_code`; alcaldía | — |
| **Colonias** | Opendatasoft / IECM cartography | polygons; colonia name; alcaldía | name normalization is best-effort |
| **Transit** | Apimetro GeoJSON | points for Metro, Metrobús, RTP, Trolebús, Corredor Concesionado | **not schedule-aware** unless the `transit` (r5py) extra is enabled |
| **Supermarkets** | OpenStreetMap via Overpass | Costco & Walmart points (brand list from `city.json`) | other brands; degrades to `data/seeds/supermarkets_seed.csv` |
| **Gyms** | OpenStreetMap via Overpass | `leisure=fitness_centre`, `amenity=gym` | unnamed OSM features remain "Unnamed gym"; degrades to seed |
| **Crime** | CDMX FGJ — Víctimas en Carpetas de Investigación | latest 12 months, **aggregated by area** | **raw victim rows are never emitted or logged** (§P) |

Workplace reference, travel speeds, detour factors, and amenity time settings come
from `data/config/places.json`. The city bounding box, metric CRS, amenity
brands, and source URLs come from `data/cities/<city>/city.json`.

## Outputs

Per area unit the pipeline writes two files (canonical location
`frontend/public/data/`, mirrored from `data/processed/`):

- `scores_<area_unit>.geojson` — a GeoJSON `FeatureCollection`
- `score_metadata_<area_unit>.json` — counts, coverage, provenance, transit engine

`area_unit ∈ {postal_code, colonia}`. (`cdmx_postal_scores.geojson` and
`score_metadata.json` are retained legacy aliases.)

### Feature property contract

Every feature has a non-null geometry and the following properties. Distances are
meters `≥ 0`; times are minutes `≥ 0`; scores are `0–100`; commute/optional
fields may be explicit `null`.

**Identity**

| Field | Notes |
|---|---|
| `area_unit` | `postal_code` \| `colonia` |
| `area_id` | unique within the file |
| `area_name`, `display_name` | human labels |
| `postal_code` | required when `area_unit == postal_code` |

**Distances (`*_m`, ≥ 0):** `dist_work_m`, `dist_transit_m`,
`dist_core_transit_m`, `dist_surface_transit_m`, `dist_supermarket_m`,
`dist_costco_m`, `dist_walmart_m`, `dist_gym_m`.

**Travel times (`*_min`, ≥ 0):** `time_work_driving_min`, `time_work_walking_min`,
`time_work_biking_min`, `time_supermarket_min`, `time_costco_min`,
`time_walmart_min`, `time_gym_min`. These are straight-line estimates by default
and real routed times where road routing ran (see *Road routing* below); a row
that fails to route falls back to the estimate, so the field is always populated.

**Routed distances (`*_routed_m`, ≥ 0, optional — present only when road routing
ran):** `dist_work_routed_m`, `dist_supermarket_routed_m`, `dist_costco_routed_m`,
`dist_walmart_routed_m`, `dist_gym_routed_m`. The routed network distance of the
chosen destination, stored separately from the straight-line `dist_*_m`. A row
that fell back to the straight-line estimate emits explicit `null` here. These are
**additive**: absent entirely on the default straight-line build.

**Per-feature source labels (scalar strings, never arrays):**
`work_travel_time_source` and `amenity_travel_time_source` are `valhalla_free_flow`
(or another engine label) on rows that routed and `fallback_straight_line_estimate`
on rows that fell back. Free-flow routing is never labeled as live-traffic commute.

**Scores (0–100):** `score_work`, `score_work_driving`, `score_work_walking`,
`score_work_biking`, `score_transit`, `score_supermarkets`,
`score_supermarkets_time`, `score_gyms`, `score_gyms_time`, `score_safety`,
`score_combined_default`.

**Transit commute block** (nullable; `transit_commute_source` always present):
`time_work_transit_min`, `time_work_transit_p75_min`, `score_work_transit`,
`transit_commute_source`, `transit_origin_stop_name`, `transit_origin_system`,
`transit_origin_line`, `transit_origin_walk_m`, `transit_destination_stop_name`,
`transit_destination_system`, `transit_destination_line`,
`transit_destination_walk_m`, `transit_transfer_penalty_min`,
`transit_route_complexity`, `transit_commute_notes`.

**Crime aggregates (≥ 0):** `crime_incidents_total`,
`crime_incidents_recent_12m`, `crime_density_recent_12m_per_km2`.

### Validation invariants

`cdmxmap validate` asserts: type is `FeatureCollection` with ≥ 1 feature; every
feature has geometry and all identity fields; postal features have `postal_code`;
all distance/time/crime fields are finite `≥ 0`; all score fields are `0–100`;
the transit block keys all exist and `transit_commute_source` is non-empty; and
**at least one** feature has a non-null `time_work_transit_min`. When present, each
`*_routed_m` field is a number `≥ 0` or explicit `null`, and each `*_source`
field is a scalar string (a JSON array is rejected).

### Road routing (optional)

When the pipeline runs with `--travel-router valhalla`, work and amenity travel
times come from an offline Valhalla road network (free-flow) instead of the
straight-line estimate. See `docs/road-routing.md` for the architecture decision,
setup, and the dynamic-workplace matrix. The `score_metadata` gains a
`road_routing` block (engine, version, source, profiles per mode, OSM source,
per-mode and per-amenity routed/fallback counts, and cache stats), and
`travel_time.source` reflects the engine while `travel_time.fallback_source`
keeps the straight-line label.

The dynamic-workplace area-to-area matrix is published as binary assets in
`frontend/public/data/`: `routing_matrix_<area_unit>_<mode>_<hash>.bin` (the N×N
travel-time matrix in **deciminutes** as little-endian `uint16`, sentinel `65535`
for unreachable, laid out **destination-major** so one workplace column is a
contiguous Range request) plus a `routing_matrix_<area_unit>_index.json` sidecar
(ordered `area_ids`, `n`, `dtype`, `scale`, `sentinel`, axis order, per-mode
filenames, and provenance). The frontend feature-detects the index and falls back
to the labeled straight-line estimate when it is absent.

### Determinism

For fixed inputs and a fixed pipeline version the outputs are byte-stable except
for embedded timestamps (which can be disabled for golden comparisons). Changing
a pinned geospatial dependency may change floating-point output and is therefore
treated as a breaking change.

## Versioning

This contract is versioned with the package (`cdmxmap.__version__`). Additive
fields are a minor change; renaming/removing a field or changing its range is a
breaking change and must update `score_metadata`'s `extractor_version`, the
frontend normalizer, and the golden fixtures together.
