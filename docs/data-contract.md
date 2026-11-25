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

Profile cities read their own `data/cities/<city>/places.json` and write their
intermediate files under `data/raw/<city>/` and `data/processed/<city>/`.

### Monterrey and Guadalajara inputs

| Source | Provider | In scope | Out of scope / best-effort |
|---|---|---|---|
| **Postal codes** | open-mexico SEPOMEX state GeoJSON + INEGI municipalities (wscatgeo `mgem`) | polygons whose largest-overlap municipality is in `mx_area.municipalities`; label from INEGI colonia names | the SEPOMEX/Correos settlement catalog (terms forbid redistribution) |
| **Colonias** | INEGI DCAH 2025 | named colonias of the member municipalities | unnamed placeholders are dropped |
| **Transit** | Nuevo León open data (Monterrey); SETRAN Jalisco GTFS (Guadalajara) | stop and station points with line ids | **not schedule-aware**; no GTFS calendar is used |
| **Supermarkets** | OpenStreetMap via Overpass, classifier v2 | store families from `supermarket_classifier` | replies with OSM data older than 30 days are rejected |
| **Gyms** | INEGI DENUE | SCIAN 713943 / 713944 points in the profile states and bbox | — |
| **Crime (Monterrey)** | SESNSP municipal incidence | one 12-month aggregate per municipality | no per-area counts exist or are invented |
| **Crime (Guadalajara)** | IIEG Jalisco (Fiscalía) microdata | latest 12 months, **aggregated by area + buffer** | **raw victim rows are never emitted or logged** (§P) |

### Intermediate files (fetcher outputs)

`data/raw/<city>/postal_codes.geojson` (municipality mode): one feature per SEPOMEX
polygon, with `d_codigo` (5-digit string), `mun_code` (5-digit INEGI code, e.g.
`19039`), `municipio`, `colonias_label` (the first two colonia names by area plus
` +N` for the rest; may be empty), `colonias_count`, and
`source = "open_mexico_sepomex"`.

`data/raw/<city>/colonias.geojson`: `area_unit = "colonia"`, `area_id` (13-character
INEGI `cvegeo`, unique), `area_name` = `display_name` = `colonia_name`,
`municipio`, `mun_code`, `col_code`, `col_type`, `postal_code` (DCAH `cp`, else the
SEPOMEX polygon holding the colonia's representative point, else `""`), `year`,
and `source = "inegi_dcah_2025"`.

`data/processed/<city>/transit_stops.csv`: columns exactly
`id,name,system,line,hierarchy,latitude,longitude,source`. `system` is a
`transit_systems[].code` from the profile (upper case). Core systems have one row
per (station, line). Surface systems have one row per stop, and `line` holds the
stop's sorted route ids joined with `|` (for example `19|20|23`). A declared
system with no rows is a fetch error. `source` is `nl_stcm_metrorrey` or `nl_ima`
(Monterrey) and `setran_gtfs` (Guadalajara).

`data/processed/<city>/supermarkets.csv`: `name,brand,latitude,longitude,source`.
With classifier v2 `brand` is the family slug (for example `aurrera`), including
`pool_only` families, and a store toggle selects its rows by exact slug. A
non-`pool_only` family with no rows is a fetch error.

`data/processed/<city>/gyms.csv`: `name,latitude,longitude,source` with
`source = "inegi_denue"`.

`data/processed/<city>/crime_statistics.csv` (`crime_mode == "city_statistics"`):
columns exactly
`unit_key,unit_name,population,population_source,period_start,period_end,incidents_12m,scored_incidents_12m,top_category_12m,source`.
One row per municipality of `crime_statistics.state_codes` (51 for Nuevo León).
`unit_key` is the 5-digit INEGI code that areas carry as `mun_code`; `population`
is Censo 2020; the period is the last 12 published months (`YYYY-MM-DD`);
`incidents_12m` counts every fuero-común carpeta and `scored_incidents_12m` the
scored subset; `source = "sesnsp_municipal"`. The engine rejects missing columns,
repeated or empty keys, negative or non-integer counts, and malformed dates.

`data/processed/<city>/crime_points.csv` (Guadalajara): the columns CDMX's reader
accepts, `date,category,offense,borough,latitude,longitude,source`, with
`source = "iieg_jalisco_fge"`. It is a gitignored intermediate file; only per-area
aggregates reach the outputs.

## Outputs

Per area unit the pipeline writes two files (canonical location
`frontend/public/data/`, mirrored from `data/processed/`; profile cities use
`frontend/public/data/<city>/` and `data/processed/<city>/`):

- `scores_<area_unit>.geojson` — a GeoJSON `FeatureCollection`
- `score_metadata_<area_unit>.json` — counts, coverage, provenance, transit engine

`area_unit ∈ {postal_code, colonia}`. CDMX, Monterrey, and Guadalajara publish
both; a profile city gets the colonia unit by listing it in `city.json`
`area_units` (Monterrey and Guadalajara read `colonias.geojson` with id field
`area_id`). (`cdmx_postal_scores.geojson` and `score_metadata.json` are retained
legacy aliases.)

#### Public parts

An `area_units` entry with `public_part_max_bytes` (a positive integer; Monterrey
and Guadalajara set 9,000,000 on `colonia`) is published to the frontend in parts
rather than as one `scores_<area_unit>.geojson`, so that no public file reaches
the 10 MB pre-commit limit. `data/processed/` still holds the single file.

- `scores_<area_unit>.part-NN.geojson` (`NN` = `01`, `02`, …): each a complete
  `FeatureCollection` of at most `public_part_max_bytes` bytes. The parts are the
  fewest equal-count contiguous slices that fit, so their features in order are
  exactly the processed file's features.
- `scores_<area_unit>_index.json`:
  `{"type": "geojson_parts", "version": 1, "area_unit", "feature_count",
  "max_part_bytes", "parts": [{"path", "feature_count", "bytes", "sha256"}]}`.
  Part `path`s are bare file names beside the index.

The metadata then has `outputs.public` set to the index and adds
`outputs.public_parts`; other units keep the exact `outputs` keys. Publishing
in parts removes the unit's single public file and any parts left from a run
with more parts; turning the setting off removes the index and parts again.
`cdmxmap validate --city <id>` checks every part against the index (size,
SHA-256, feature count, budget), that area ids are unique across parts, and that
the joined features equal the processed file. The frontend (`lib/areaData.ts`)
accepts either form at the unit's scores URL. For an index it rejects a part path
that leaves the index's directory, a part that is not a `FeatureCollection` or
whose feature count differs from the index, and a total that differs from
`feature_count`; it does not check `bytes` or `sha256`, which are for the
validator.

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

Monterrey and Guadalajara features also carry `mun_code` and `municipio` (with
`alcaldia` set to the municipality, which the area header shows). Postal-code
features carry `d_codigo`, `colonias_label`, `colonias_count` and `postal_label`
(the colonia label, shown as a muted line); colonia features carry `col_code`,
`col_type`, `postal_code` (may be `""`), `year` and `source`.

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

**Per-system transit and per-brand store fields.** For each `transit_systems`
entry (slug `<s>`, e.g. `metro`, `rutas`, `mitren`): `dist_<s>_transit_m`,
`score_transit_<s>`, `nearest_<s>_transit_name`, `nearest_<s>_transit_source`; the
browser re-scores transit access from these when systems are toggled. For each
`store_brands` entry (slug `<b>`, e.g. `heb`, `la_comer`): `dist_<b>_m`,
`time_<b>_min`, `nearest_<b>_name`, `nearest_<b>_source`, plus `dist_<b>_routed_m`
on a routed build.

**Crime fields** depend on the city's `crime_mode`.

*`incident_points`* (CDMX, Guadalajara; aggregates ≥ 0): `crime_incidents_total`,
`crime_incidents_recent_12m`, `crime_density_recent_12m_per_km2`,
`crime_top_category_recent_12m`, `crime_source` (`fgj_cdmx_victimas` for CDMX;
otherwise the profile's `crime_source.source`, e.g. `iieg_jalisco_fge`). When the
profile sets `crime_source.density_buffer_m`, every count and the density are
taken over the area polygon buffered by that many meters, and each feature
carries `crime_buffer_m` (> 0; 250 for Guadalajara). An incident can then count
toward several neighbouring areas; the metadata record counts stay unique.

*`city_statistics`* (Monterrey): every area inherits the aggregates of its
statistics unit, joined on `crime_statistics.area_key_field` (default `mun_code`)
to `unit_key`:

| Field | Notes |
|---|---|
| `crime_statistics_scope` | `municipality` |
| `crime_statistics_area` | unit name, e.g. `San Pedro Garza García` |
| `crime_statistics_period` | `YYYY-MM-DD/YYYY-MM-DD` |
| `crime_scope_population` | integer, Censo 2020 |
| `crime_scope_incidents_12m` | all fuero-común carpetas in the unit |
| `crime_scope_scored_incidents_12m` | the scored subset |
| `crime_rate_per_100k_12m` | scored subset per 100k residents, 1 dp; the safety input |
| `crime_total_rate_per_100k_12m` | all carpetas per 100k residents, 1 dp; context only |
| `crime_top_category_recent_12m` | most frequent *tipo de delito* |
| `crime_source` | `sesnsp_municipal` |

`score_safety` is a linear min–max over the matched units' scored rates (lowest
100, highest 0, no percentile cap), so every area in a unit shares its score. An
area with no matching unit is a hard error, never a silent zero. The incident
fields (`crime_incidents_*`, `crime_density_*`) are **absent** in this mode.

### Validation invariants

`cdmxmap validate` asserts: type is `FeatureCollection` with ≥ 1 feature; every
feature has geometry and all identity fields; postal features have `postal_code`;
all distance/time/crime fields are finite `≥ 0`; all score fields are `0–100`;
the transit block keys all exist and `transit_commute_source` is non-empty; and
**at least one** feature has a non-null `time_work_transit_min`. When present, each
`*_routed_m` field is a number `≥ 0` or explicit `null`, and each `*_source`
field is a scalar string (a JSON array is rejected).

Crime checks follow the mode: incident cities need the incident counts `≥ 0`
(and `crime_buffer_m > 0` when present); statistics cities need the five numeric
statistics fields `≥ 0`, non-empty `crime_statistics_scope`/`_area`/`_period`,
and **no** incident fields. For a profile city (not CDMX), every declared transit
system must be the nearest stop of at least one feature (a non-empty
`nearest_<slug>_transit_name`), because an empty system would otherwise score 100
everywhere in the browser.

### Metadata `crime` block

Incident mode: `records_total`, `records_recent_12m`, `latest_date`,
`recent_start_date` (CDMX: exactly these keys). A profile incident city adds
`source` and `source_label`, and `density_buffer_m` when its density is buffered.

Statistics mode: `mode` (`city_statistics`), `scope`, `source`, `source_label`,
`scored_label`, `scored_definition` and `scored_offenses` (when the profile
declares them), `score_method` (`min_max_across_units`), `population_source`,
`period_start`, `period_end`, `recent_start_date` (= `period_start`),
`latest_date` (= `period_end`), `records_total` and `records_recent_12m` (both the
sum of `incidents_12m` over matched units), `units` (one entry per matched unit:
`key`, `name`, `population`, `incidents_12m`, `scored_incidents_12m`,
`rate_per_100k`, `total_rate_per_100k`, `areas`), `areas_matched`, and
`areas_unmatched` (always 0). `point_counts` gains `crime_statistics_units` (rows
in the CSV, e.g. 51) and `sources` gains `crime_statistics`.

### Road routing (optional)

When the pipeline runs with `--travel-router valhalla`, work and amenity travel
times come from an offline Valhalla road network (free-flow) instead of the
straight-line estimate. See `docs/road-routing.md` for the architecture decision,
setup, and the dynamic-workplace matrix. The `score_metadata` gains a
`road_routing` block (engine, version, source, profiles per mode, OSM source,
per-mode and per-amenity routed/fallback counts, and cache stats), and
`travel_time.source` and `amenity_travel_time.source` reflect the engine while
their `fallback_source` keeps the straight-line label. When `places.json`
declares them, the `road_routing` block also records `osm_md5`, `osm_date`, and
the Valhalla `search_filter` (Monterrey and Guadalajara:
`{"min_road_class": "residential"}`).

The dynamic-workplace area-to-area matrix is published as binary assets in
`frontend/public/data/`: `routing_matrix_<area_unit>_<mode>_<hash>.bin` (the N×N
travel-time matrix in **deciminutes** as little-endian `uint16`, sentinel `65535`
for unreachable, laid out **destination-major** so one workplace column is a
contiguous Range request) plus a `routing_matrix_<area_unit>_index.json` sidecar
(ordered `area_ids`, `n`, `dtype`, `scale`, `sentinel`, axis order, per-mode
filenames, and provenance: `engine`, `version`, `profiles`, `inputs_hash`,
`osm_source`, `osm_sha`, `osm_date`, and `search_filter` when one was used).
Profile cities publish them under `frontend/public/data/<city>/`; Monterrey and
Guadalajara ship the postal-code matrices only. The frontend feature-detects the
index of the selected city and unit and falls back to the labeled straight-line
estimate when it is absent.

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
