# Multi-City Plug-and-Play Roadmap

This project already has a good split between **offline scoring** (Python) and **static visualization** (React + Leaflet). To make it reusable for cities beyond CDMX (for example Stavanger), the key move is to convert CDMX assumptions into city profiles and adapters.

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
6. Run `scripts/run_city.py --city stavanger --area-unit <unit>`.
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
