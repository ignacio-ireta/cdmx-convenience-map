# Current State

Last integration pass: 2026-04-28.

## Architecture

This repo is a static CDMX convenience map. The browser app is Vite + React + TypeScript with Leaflet through React-Leaflet. Python is used only for offline fetching, normalization, and score generation. There is no runtime backend.

The app is GitHub Pages-compatible:

- Vite is configured with `base: './'` in `frontend/vite.config.ts`.
- Runtime data loads use `import.meta.env.BASE_URL`.
- Production output is `frontend/dist/`.
- The browser loads static JSON/GeoJSON assets only, plus external map tiles.

Current frontend stack:

- React `19.2.5`
- Vite `8.0.10`
- TypeScript `6.0.2`
- Leaflet `1.9.4`
- React-Leaflet `5.0.0`
- lucide-react `1.12.0`

## Data Flow

1. Fetch scripts cache raw inputs under `data/raw/` and normalized intermediates under `data/processed/`.
2. `scripts/build_scores.py --area-unit postal_code` and `scripts/build_scores.py --area-unit colonia` run the shared scoring pipeline.
3. Area polygons are projected to EPSG:32614 for meter distances.
4. Representative points are scored against workplace, Apimetro transit points, OSM/seed Costco/Walmart, OSM/seed gyms, and FGJ crime records.
5. Scores are normalized to `0..100`; distance metrics use a 95th-percentile cap to avoid flattening the map.
6. Enriched GeoJSON and metadata are written to `data/processed/` and copied to `frontend/public/data/`.
7. The frontend fetches the static public assets at runtime.

Active scripts:

- `scripts/fetch_postal_codes.py`: CDMX postal-code GeoJSON.
- `scripts/fetch_colonias.py`: Opendatasoft Mexico colonia polygons filtered to CDMX.
- `scripts/fetch_transit.py`: Apimetro data for Metro, Metrobús, RTP, Trolebús, and Corredor Concesionado.
- `scripts/fetch_supermarkets.py`: OSM Overpass Costco/Walmart query with seed fallback.
- `scripts/fetch_gyms.py`: OSM Overpass gym query with seed fallback.
- `scripts/fetch_crime.py`: FGJ victims CSV normalization.
- `scripts/build_scores.py`: generic scoring CLI for supported area units.
- `scripts/validate_processed.py`: generated GeoJSON validation.

Archived script:

- `scripts/archive/fetch_gtfs_transit.py`: legacy GTFS stop fetcher, no longer active.

## Frontend Entry Points

- `frontend/index.html`: Vite HTML entry.
- `frontend/src/main.tsx`: React mount point; imports Leaflet CSS, global CSS, and `App`.
- `frontend/src/App.tsx`: app state, static data loading, geography selection, metric controls, work postal-code override, map rendering, search, details, top-100 list, and data audit panel.
- `frontend/src/App.css`: app layout and component styles.
- `frontend/src/index.css`: global reset/body styles.

Static files are loaded in `frontend/src/App.tsx` with paths equivalent to:

```ts
fetch(`${import.meta.env.BASE_URL}data/scores_postal_code.geojson`)
fetch(`${import.meta.env.BASE_URL}data/scores_colonia.geojson`)
fetch(`${import.meta.env.BASE_URL}data/score_metadata_postal_code.json`)
fetch(`${import.meta.env.BASE_URL}data/score_metadata_colonia.json`)
fetch(`${import.meta.env.BASE_URL}data/score_metadata.json`)
```

## Generated Public Assets

Current public assets in `frontend/public/data/`:

- `scores_postal_code.geojson`: 3.7 MB, 1,215 features.
- `scores_colonia.geojson`: 5.1 MB, 1,837 features.
- `cdmx_postal_scores.geojson`: 3.7 MB legacy alias for postal-code data.
- `score_metadata_postal_code.json`: 3.2 KB.
- `score_metadata_colonia.json`: 3.1 KB.
- `score_metadata.json`: 3.1 KB combined metadata.

Current generated metadata reports:

- 10,849 Apimetro transit points.
- 1,308 core transit points.
- 9,541 surface transit points.
- 130 supermarket points.
- 553 gym points.
- 1 configured workplace, defaulting to postal code `11510`.
- 1,340,993 normalized crime records.
- 231,158 crime records in the current 12-month scoring window.
- Amenity travel-time source: `fallback_straight_line_estimate`.

## Scoring Fields

Both geography outputs use the generic area schema:

- `area_unit`
- `area_id`
- `area_name`
- `display_name`
- `alcaldia`
- `centroid_lat`
- `centroid_lon`

Postal-code outputs also keep backward-compatible fields:

- `d_cp`
- `postal_code`
- `postal_label`

Colonia outputs include:

- `colonia_name`

Distance fields:

- `dist_work_m`
- `dist_transit_m`
- `dist_core_transit_m`
- `dist_surface_transit_m`
- `dist_supermarket_m`
- `dist_costco_m`
- `dist_walmart_m`
- `dist_gym_m`

Travel-time fields:

- `time_work_driving_min`
- `time_work_walking_min`
- `time_work_biking_min`
- `time_supermarket_min`
- `time_costco_min`
- `time_walmart_min`
- `time_gym_min`

Score fields:

- `score_work`
- `score_work_driving`
- `score_work_walking`
- `score_work_biking`
- `score_transit`
- `score_supermarkets`
- `score_supermarkets_time`
- `score_gyms`
- `score_gyms_time`
- `score_safety`
- `score_combined_default`

Nearest-place fields:

- `nearest_work_name`
- `nearest_transit_name`
- `nearest_core_transit_name`
- `nearest_surface_transit_name`
- `nearest_supermarket_name`
- `nearest_costco_name`
- `nearest_walmart_name`
- `nearest_gym_name`
- `nearest_work_source`
- `nearest_transit_source`
- `nearest_core_transit_source`
- `nearest_surface_transit_source`
- `nearest_supermarket_source`
- `nearest_gym_source`

Crime fields:

- `crime_incidents_total`
- `crime_incidents_recent_12m`
- `crime_density_recent_12m_per_km2`
- `crime_top_category_recent_12m`
- `crime_source`

Default combined weights are:

- Work: `0.30`
- Transit: `0.25`
- Supermarkets: `0.18`
- Gyms: `0.12`
- Safety: `0.15`

The frontend exposes sliders as whole-number weights and normalizes by their runtime total.

## Verified Commands

These commands passed during the final integration pass:

```bash
cd frontend && npm run build
cd frontend && npm run lint
python3 -m py_compile scripts/*.py
.venv/bin/python scripts/build_scores.py --area-unit postal_code
.venv/bin/python scripts/build_scores.py --area-unit colonia
.venv/bin/python scripts/validate_processed.py
```

Additional checks performed:

- Validated required fields in `frontend/public/data/scores_postal_code.geojson`.
- Validated required fields in `frontend/public/data/scores_colonia.geojson`.
- Checked numeric distances/times are nonnegative when present.
- Checked score fields stay in `0..100`.
- Sampled 5 postal-code features and 5 colonia features.
- Checked generated public asset sizes.
- Checked `.gitignore` and repo status for accidental raw/generated bloat.
- Checked current browser console after reload; no fresh app errors were logged.

## Browser Smoke Test

The local app at `http://127.0.0.1:5174/` passed these checks:

- Postal-code layer rendered 1,215 Leaflet polygons.
- Colonia layer rendered 1,837 Leaflet polygons.
- Metric selector switched to Stores, Work, and Overall.
- Store time-based metric toggle displayed `Stores (Time)`.
- Work driving mode displayed `Work (Drive)`.
- Weight sliders accepted keyboard adjustment.
- Searching `06700` returned and opened `CP 06700`.
- Searching `roma` on the colonia layer returned and opened `Roma Norte I - Cuauhtémoc`.
- Top-list copy button was visible.
- Fresh browser console check after reload reported 0 app errors.

## Run Commands

Install Python dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Run the offline data pipeline:

```bash
.venv/bin/python scripts/fetch_postal_codes.py
.venv/bin/python scripts/fetch_colonias.py
.venv/bin/python scripts/fetch_transit.py
.venv/bin/python scripts/fetch_supermarkets.py
.venv/bin/python scripts/fetch_gyms.py
.venv/bin/python scripts/fetch_crime.py
.venv/bin/python scripts/build_scores.py --area-unit postal_code
.venv/bin/python scripts/build_scores.py --area-unit colonia
.venv/bin/python scripts/validate_processed.py
```

Run the frontend dev server:

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5174
```

Run frontend checks:

```bash
cd frontend
npm run build
npm run lint
```

## Repo Hygiene

Do not commit these local dependencies, raw downloads, or generated intermediates:

- `.venv/`
- `frontend/node_modules/`
- `frontend/dist/`
- `data/raw/correos-postales.json`
- `data/raw/colonias.geojson`
- `data/raw/apimetro_transit_stations.geojson`
- `data/raw/victimasFGJ_acumulado_2024_09.csv`
- `data/processed/crime_points.csv`
- `data/processed/*.csv`
- `data/processed/*.geojson`
- `data/processed/*.json`
- `data/archive/gtfs_legacy/`

These small source/config files are intentionally commit-worthy:

- `data/config/places.json`
- `data/raw/workplaces.csv`
- `data/seeds/*.csv`
- `data/archive/README.md`

These generated static app assets are intentionally public-facing and should be reviewed before commit:

- `frontend/public/data/scores_postal_code.geojson`
- `frontend/public/data/scores_colonia.geojson`
- `frontend/public/data/cdmx_postal_scores.geojson`
- `frontend/public/data/score_metadata_postal_code.json`
- `frontend/public/data/score_metadata_colonia.json`
- `frontend/public/data/score_metadata.json`

## Risks And Limitations

- GitHub Pages deployment still needs a publishing workflow or manual upload of `frontend/dist/`.
- Public GeoJSON files are moderately large for a static MVP; monitor size if more fields or layers are added.
- OSM Overpass data can be incomplete or temporarily unavailable; seed fallbacks are useful for demos but not exhaustive.
- Transit score is still proximity to Apimetro stops/stations, not true commute time.
- Work and amenity travel times currently use offline straight-line fallback estimates, not routed travel times.
- Safety scoring uses reported FGJ victim investigation records and area density, not population-adjusted risk, perception, or underreporting.
- The repo has not been committed yet, so `git status` shows the source project files as untracked while ignored generated files stay hidden.
