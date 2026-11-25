# Multi-City Plug-and-Play Roadmap

This project already has a good split between **offline scoring** (Python) and **static visualization** (React + Leaflet). To make it reusable for cities beyond CDMX (for example Stavanger), the key move is to convert CDMX assumptions into city profiles and adapters.

> **Implementation status.** Much of this roadmap has shipped. The pipeline is
> `--city` profile-driven (`data/cities/<id>/{city.json,places.json}`) and now
> ships nine cities: four Mexican — **CDMX**, **Monterrey**, **Guadalajara**,
> and **Morelia** — and five Norwegian — **Oslo**, **Bergen**, **Trondheim**,
> **Stavanger**, and **Drammen** — built with
> `uv run cdmxmap run --city <id> --area-unit postal_code`.
> Where sections below propose a `scripts/`-based layout (e.g. `scripts/run_city.py`,
> `scripts/adapters/<city_id>/`), the realized design is the importable
> `src/cdmxmap/` package and the `cdmxmap` CLI; the Norwegian area adapter lives at
> `src/cdmxmap/sources/fetch_no_postal_codes.py`, the Mexican one at
> `fetch_mx_postal_codes.py`, and the shared OSM transit adapter at
> `fetch_osm_transit.py`. Treat the rest of this document as the original design
> sketch, not current file paths.

### Status by city

| City | Area units | Transit source | Safety | Travel times |
|---|---|---|---|---|
| CDMX | postal code, colonia | Apimetro (in-code constants) | FGJ incident density | straight-line (routing opt-in) |
| Monterrey | postal code, colonia | Nuevo León open data (`fetch_nl_transit`) | SESNSP municipal rate (`city_statistics`) | Valhalla free-flow, published |
| Guadalajara | postal code, colonia | SETRAN Jalisco GTFS (`fetch_gtfs_transit`) | IIEG incident density, 250 m buffer | Valhalla free-flow, published |
| Morelia | postal code | OpenStreetMap (`fetch_osm_transit`) | not scored | straight-line |
| Oslo, Bergen, Trondheim, Stavanger, Drammen | postal code | OpenStreetMap (`fetch_no_transit`) | not scored | straight-line |

Monterrey and Guadalajara realize most of the adapter idea in sections 2–5 and 7:

- **Area adapters by administrative unit.** A profile's `mx_area` block names the
  INEGI state and member municipalities. `fetch_mx_postal_codes` (municipality
  mode) assigns SEPOMEX polygons to municipalities by largest overlap, and
  `fetch_mx_colonias` adds INEGI DCAH 2025 colonias as a second area unit
  (`area_units` in `city.json`). Shared plumbing is in
  `src/cdmxmap/sources/mx_common.py`.
- **Transit adapters** write the same `transit_stops.csv` from very different
  sources (CKAN GeoPackages, GTFS), with the systems declared in the profile's
  `transit_systems` (`code`, `slug`, `group`, `label`). The frontend reads its
  toggles from the city's `CityConfig`, so there is no city-specific branch.
- **Amenity adapters**: `supermarket_classifier` (store families matched in
  Python) and `gyms_source` (`fetch_denue_gyms`, INEGI DENUE).
- **Safety adapters**: `crime_mode` selects `incident_points` (CDMX, Guadalajara
  via `fetch_iieg_crime`) or `city_statistics` (Monterrey via
  `fetch_sesnsp_crime_statistics`). SESNSP covers every Mexican municipality, so
  the statistics mode is available to any Mexican city.
- **Quality gates**: `cdmxmap validate --city <id>` checks the mode-specific
  crime fields and that every declared transit system has stops; the transit
  and classifier-v2 store fetchers fail loudly when a declared system or store
  family comes back empty.

Not done: the per-city `manifest.json` of section 6 (the frontend still keeps
its city list in `frontend/src/constants.ts`), and a license field in the
provenance metadata of section 7. Metrorrey Lines 4 and 6 are to be added to
Monterrey when they carry passengers (target February 2027).

## 1) Introduce a city profile contract

Create one profile per city under `data/cities/<city_id>/city.json` with:

- `city_id`: stable id (`cdmx`, `stavanger`)
- `display_name`: human name
- `country_code`: ISO 3166-1 alpha-2
- `timezone`
- `crs_metric_epsg`: local projected CRS used for meter calculations
- `bbox`: south/west/north/east
- `area_units`: list of supported geographies (`postal_code`, `neighborhood`, etc.)
- `default_weights`
- `data_sources`: URLs/API details by metric (work centers, transit, groceries, gyms, safety)
- `field_mapping`: normalization map from external columns to the internal schema

### Example Stavanger profile sketch

```json
{
  "city_id": "stavanger",
  "display_name": "Stavanger",
  "country_code": "NO",
  "timezone": "Europe/Oslo",
  "crs_metric_epsg": 32632,
  "bbox": { "south": 58.82, "west": 5.55, "north": 59.07, "east": 5.95 },
  "area_units": ["grunnkrets", "postal_code"],
  "default_weights": {
    "work": 0.30,
    "transit": 0.25,
    "supermarkets": 0.18,
    "gyms": 0.12,
    "safety": 0.15
  }
}
```

## 2) Add a normalized intermediate schema (city-agnostic)

Keep all scoring logic city-neutral by enforcing canonical intermediate tables:

- `areas.geojson`: polygons + canonical ids
- `transit_points.csv`
- `amenities_supermarkets.csv`
- `amenities_gyms.csv`
- `crime_events.csv`
- `workplaces.csv`

Each fetcher becomes a **city adapter** that outputs this schema, regardless of original data shape.

## 3) Refactor scripts into adapter + core pipeline

Current fetch scripts are source-specific. Evolve to:

- `scripts/core/build_scores.py`: unchanged scoring engine logic, fed canonical files
- `scripts/core/validate_processed.py`: schema + quality checks
- `scripts/adapters/<city_id>/fetch_*.py`: fetch + normalize to canonical files
- `scripts/run_city.py --city cdmx --area-unit postal_code`: orchestration entrypoint

This keeps complex geometry/scoring code centralized while allowing city-specific fetching differences.

## 4) Replace hardcoded constants with runtime config

Move constants from `scripts/common.py` (bbox, user-agent name, default files) into profile-aware accessors:

- `load_city_profile(city_id)`
- `get_city_paths(city_id)`
- `get_city_bbox(city_id)`

Then pass `--city` through all CLIs. This is the biggest unlock for reuse.

## 5) Make area-unit plugins explicit

Different countries use different statistical units. Add area-unit plugin definitions:

- `area_unit_id`
- `required_fields`
- `id_builder` / `display_name_builder`
- optional compatibility aliases (e.g., `postal_code`, `d_cp`)

This avoids coupling frontend labels and backend geometry logic to CDMX terminology.

## 6) Frontend: city-aware static asset loading

Serve generated assets under:

- `frontend/public/data/<city_id>/scores_<area_unit>.geojson`
- `frontend/public/data/<city_id>/metadata_<area_unit>.json`
- `frontend/public/data/<city_id>/manifest.json`

`manifest.json` should declare available area units and metric toggles. `App.tsx` can then:

1. read selected city from URL (`?city=stavanger`) or dropdown,
2. fetch that city's manifest,
3. load listed assets only.

No city-specific frontend branches needed.

## 7) Define quality gates per adapter

Add validation rules that all cities must satisfy before publishing:

- geometry valid and non-empty
- required canonical columns present
- score fields in `0..100`
- source counts above configurable minimums
- provenance metadata captured (`source_name`, `download_date`, `license`)

## 8) Stavanger onboarding checklist

1. Create `data/cities/stavanger/city.json`.
2. Implement area fetcher for one unit (postal code or grunnkrets).
3. Add transit adapter (e.g., GTFS/NeTEx-derived stop points).
4. Add supermarket/gym OSM adapter with localized brand list.
5. Add safety proxy dataset if official crime microdata is unavailable.
6. Run `uv run cdmxmap run --city stavanger --area-unit postal_code`.
7. Validate and publish static assets.
8. Open frontend with `?city=stavanger`.

## 9) Suggested implementation phases

- **Phase 1 (low risk):** city profile files + orchestrator CLI + folder structure.
- **Phase 2:** migrate existing CDMX pipeline to new adapter contract without changing outputs.
- **Phase 3:** add first non-CDMX city (Stavanger) with one area unit.
- **Phase 4:** add per-city UI switcher and manifest-driven loading.

## 10) Why this works

- Core scoring remains one code path.
- New cities only require adapter work + profile configuration.
- Frontend deployment stays static and cheap (GitHub Pages compatible).
- You can incrementally improve data quality city by city without rewriting the app.
