# CDMX Postal-Code Convenience Map

Working prototype for evaluating where to start an apartment search in Mexico City by area convenience. The current map unit is postal code; the frontend and scoring schema are prepared for additional area units such as colonia. The frontend is a static React + Leaflet choropleth; Python scripts precompute straight-line distance scores into enriched GeoJSON.

## Quick Start

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

.venv/bin/python scripts/fetch_postal_codes.py
.venv/bin/python scripts/fetch_colonias.py
.venv/bin/python scripts/fetch_transit.py
.venv/bin/python scripts/fetch_supermarkets.py
.venv/bin/python scripts/fetch_gyms.py
.venv/bin/python scripts/fetch_crime.py
.venv/bin/python scripts/build_scores.py --area-unit postal_code
.venv/bin/python scripts/build_scores.py --area-unit colonia
.venv/bin/python scripts/validate_processed.py

cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5174
```

Open [http://127.0.0.1:5174](http://127.0.0.1:5174).


### City profile aware fetchers

You can now run the OSM amenity fetchers with a city profile:

```bash
.venv/bin/python scripts/fetch_supermarkets.py --city cdmx
.venv/bin/python scripts/fetch_gyms.py --city cdmx
```

A new orchestration helper is available:

```bash
.venv/bin/python scripts/run_city.py --city cdmx --area-unit postal_code
```

City profiles live in `data/cities/<city_id>/city.json` (for example `cdmx` and `stavanger`).

## What Is Included

- CDMX postal-code polygons colored by selected convenience score.
- CDMX colonia polygons as a second geography layer.
- Geography selector for postal code and colonia.
- Metric selector for combined, work, transit, supermarkets, gyms, and safety.
- Area detail panel with raw distances, nearest known point, and score breakdown.
- Editable work postal code; the browser recalculates work distance and combined score from that postal code's representative point.
- Work score mode selector for straight-line distance, driving time, walking time, and biking time.
- Store and gym score mode selectors for distance-based or offline time-estimated scoring.
- Weight sliders that recompute the combined score in the browser.
- Data-audit panel with source counts for postal codes, Apimetro transit points, OSM stores, OSM gyms, and FGJ crime records.
- Offline scoring pipeline with replaceable raw data sources.

## Data Notes

- Postal-code polygons come from CDMX open data: [Códigos Postales de la Ciudad de México](https://datos.cdmx.gob.mx/dataset/codigos-postales).
- Colonia polygons come from Opendatasoft's [Colonias de CDMX - Mexico](https://public.opendatasoft.com/explore/dataset/georef-mexico-colonia/export/) dataset, sourced from IECM cartography.
- Transit points come from [Apimetro](https://apimetro.dev/docs) GeoJSON for Metro, Metrobús, RTP, Trolebús, and Corredor Concesionado. The previous raw CDMX GTFS stop pipeline is archived under `scripts/archive`.
- Costco/Walmart and gym POIs come from OpenStreetMap through the [Overpass API](https://overpass-api.de/api/interpreter).
- Crime data comes from CDMX open data: [Víctimas en Carpetas de Investigación FGJ](https://datos.cdmx.gob.mx/dataset/victimas-en-carpetas-de-investigacion-fgj/resource/d543a7b1-f8cb-439f-8a5c-e56c5479eeb5).
- `data/seeds/*.csv` are fallback demo files only. If the nearest gym says `Unnamed gym`, that is an unnamed OSM feature, not generated sample data.
- Workplace distance defaults to `data/config/places.json`; the checked-in default is postal code `11510`, and the app can override it with any CDMX postal code at runtime.
- Work travel times are generated offline. The current implementation uses fallback straight-line estimates, documented in `docs/travel-time-roadmap.md`.
- Amenity travel times are generated offline with nearest-candidate narrowing; the current implementation uses fallback walking-time estimates, not live routing.
- Safety score is lower-is-better recent crime density. It uses the latest 12 months available in the FGJ CSV, not the current calendar date.

## Multi-City Evolution

If you want this project to become plug-and-play for other cities (for example Stavanger), see `docs/multi-city-roadmap.md`.

Recommended first implementation step: introduce `--city` profile-driven configuration in the data pipeline while preserving the current CDMX outputs as a compatibility baseline.
