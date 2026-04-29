# Data Pipeline

## Inputs

- `data/raw/correos-postales.json`: CDMX postal-code GeoJSON from [Códigos Postales de la Ciudad de México](https://datos.cdmx.gob.mx/dataset/codigos-postales).
- `data/raw/colonias.geojson`: normalized CDMX colonia GeoJSON from Opendatasoft's [Colonias de CDMX - Mexico](https://public.opendatasoft.com/explore/dataset/georef-mexico-colonia/export/) dataset.
- `data/processed/transit_stops.csv`: deduped station/stop points from [Apimetro](https://apimetro.dev/docs) `geojsonEstacion` for `METRO,MB,RTP,TROLE,CC`.
- `data/processed/supermarkets.csv`: Costco/Walmart points fetched from OpenStreetMap through [Overpass API](https://overpass-api.de/api/interpreter). The script filters to store-like OSM records, excluding banks/pharmacies/restaurants that merely mention Walmart.
- `data/processed/gyms.csv`: OSM `leisure=fitness_centre` and legacy `amenity=gym` points fetched through Overpass.
- `data/processed/crime_points.csv`: geocoded FGJ victim investigation records from [Víctimas en Carpetas de Investigación FGJ](https://datos.cdmx.gob.mx/dataset/victimas-en-carpetas-de-investigacion-fgj/resource/d543a7b1-f8cb-439f-8a5c-e56c5479eeb5). The current direct CSV is `victimasFGJ_acumulado_2024_09.csv`.
- `data/config/places.json`: primary workplace and travel-time config. The checked-in default workplace is postal code `11510`.
- `data/raw/workplaces.csv`: legacy fallback workplace CSV with `name`, `latitude`, and `longitude`.
- `data/seeds/*.csv`: deterministic fallback files only; use them for demos when Overpass is down or slow, not as the preferred data source.

## Build

Run the scripts from the repository root:

```bash
.venv/bin/python scripts/fetch_postal_codes.py
.venv/bin/python scripts/fetch_colonias.py
.venv/bin/python scripts/fetch_transit.py
.venv/bin/python scripts/fetch_supermarkets.py
.venv/bin/python scripts/fetch_gyms.py
.venv/bin/python scripts/fetch_crime.py
.venv/bin/python scripts/build_scores.py --area-unit postal_code
.venv/bin/python scripts/build_scores.py --area-unit colonia
```

Add `--seed-only` to either POI script if you need an offline deterministic demo. The scripts also fall back to seed CSVs if Overpass is slow or returns too few rows.

## Output

`scripts/build_scores.py` writes:

- `data/processed/scores_postal_code.geojson`
- `data/processed/scores_colonia.geojson`
- `data/processed/cdmx_postal_scores.geojson`
- `data/processed/score_metadata_postal_code.json`
- `data/processed/score_metadata_colonia.json`
- `data/processed/score_metadata.json`
- `frontend/public/data/scores_postal_code.geojson`
- `frontend/public/data/scores_colonia.geojson`
- `frontend/public/data/cdmx_postal_scores.geojson`
- `frontend/public/data/score_metadata_postal_code.json`
- `frontend/public/data/score_metadata_colonia.json`
- `frontend/public/data/score_metadata.json`

The frontend fetches `frontend/public/data/scores_postal_code.geojson` or `frontend/public/data/scores_colonia.geojson` based on the selected geography, plus the matching `score_metadata_*` file for the audit panel. The `cdmx_postal_scores.geojson` and `score_metadata.json` files are legacy aliases kept for v1 compatibility, so no backend is required.

The scoring CLI is area-unit aware:

```bash
.venv/bin/python scripts/build_scores.py --area-unit postal_code
```

Build colonia scores after fetching the normalized colonia source:

```bash
.venv/bin/python scripts/fetch_colonias.py
.venv/bin/python scripts/build_scores.py --area-unit colonia
```

## Scoring

Distances are representative-point-to-point straight-line distances in meters after projecting CDMX geometries to EPSG:32614. Representative points are used instead of naive centroids so the scoring point sits inside each polygon. The legacy `centroid_lat` and `centroid_lon` property names are retained for frontend compatibility. Scores are normalized to 0-100 with closer values scoring higher, clipped at each metric's 95th percentile to reduce outlier impact.

Default combined weights:

- Work: 30
- Transit: 25
- Supermarkets: 18
- Gyms: 12
- Safety: 15

The transit score is now a composite to reduce noise from dense surface-stop networks: 70% nearest core transit point (`METRO`, `MB`, `TROLE`) and 30% nearest surface transit point (`RTP`, `CC`). The safety score is computed from FGJ crime density, not distance. `scripts/build_scores.py` spatially joins geocoded FGJ victim records into postal-code polygons, finds the latest date present in the file, keeps the latest 12 months from that date, and scores lower incidents per square kilometer as better. This keeps the score reproducible if the source is updated later.

Transit commute time is not implemented yet. The current Apimetro score measures proximity to stops, not travel time to work. See `docs/transit-commute-roadmap.md` for the planned static preprocessing data contract and routing options.

## Current Generated Data

The current checked app asset was built with:

- 1,215 CDMX postal-code polygons.
- 1,837 CDMX colonia polygons.
- 10,849 deduped Apimetro transit points: 1,308 core points and 9,541 surface points.
- 130 OSM Costco/Walmart store-like points.
- 553 OSM gym/fitness points.
- 1,340,993 geocoded FGJ victim records normalized from the CSV.
- 231,158 FGJ records in the latest available 12-month scoring window, from 2023-09-30 through 2024-09-30.
- 1 sample workplace config row.

Each scored area feature includes `nearest_*_source` and `crime_source` fields so the detail panel can show whether the data came from `Apimetro`, `OSM Overpass`, `FGJ CDMX`, `sample config`, or a `seed fallback`.

Each feature also includes generic area fields for future area units:

- `area_unit`
- `area_id`
- `area_name`
- `display_name`
- `alcaldia`

Postal-code-specific fields such as `postal_code`, `d_cp`, and `postal_label` are still retained for compatibility.

Work travel-time fields are generated offline and stored in the same GeoJSON:

- `time_work_driving_min`
- `time_work_walking_min`
- `time_work_biking_min`
- `score_work_driving`
- `score_work_walking`
- `score_work_biking`
- `work_travel_time_source`

The current source is `fallback_straight_line_estimate`, described in `docs/travel-time-roadmap.md`.

Amenity travel-time fields are also generated offline. The pipeline first narrows each area to the nearest configured candidate POIs by straight-line distance, then routes or estimates only those candidate pairs. The current config uses the nearest `5` candidates and fallback walking-time estimates:

- `time_supermarket_min`
- `time_costco_min`
- `time_walmart_min`
- `time_gym_min`
- `nearest_costco_name`
- `nearest_walmart_name`
- `score_supermarkets_time`
- `score_gyms_time`
- `amenity_travel_time_source`

Existing distance fields and distance-based `score_supermarkets` / `score_gyms` are preserved for compatibility.

## Apimetro

[Apimetro](https://apimetro.dev/) is now the active transit source. It is an open-source CDMX mobility API at [galigaribaldi/Apimetro](https://github.com/galigaribaldi/Apimetro) with JSON and GeoJSON endpoints for stations, lines, and polygons.

Useful endpoints from the project docs:

- `GET https://apimetro.dev/movilidad/mapas/geojsonEstacion?sistema=TODOS`
- `GET https://apimetro.dev/movilidad/mapas/geojsonLinea?sistema=METRO,MB`
- `GET https://apimetro.dev/movilidad/mapas/geojsonPoligono?entidad=CDMX&nivel=alcaldia`

The old CDMX GTFS stop fetcher is archived at `scripts/archive/fetch_gtfs_transit.py`. Local generated GTFS files, if present, belong under `data/archive/gtfs_legacy/` and are not used by the active scoring pipeline.
