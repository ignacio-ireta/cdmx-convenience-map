# CDMX Postal-Code Convenience Map

Working prototype for evaluating where to start an apartment search in Mexico City by area convenience. The current map unit is postal code; the frontend and scoring schema are prepared for additional area units such as colonia. The frontend is a static React + Leaflet choropleth; Python scripts precompute straight-line distance scores into enriched GeoJSON.

## Quick Start

The Python pipeline is managed with [uv](https://docs.astral.sh/uv/); the
frontend with npm.

```bash
# 1. Python environment (creates .venv, installs the pinned geospatial stack)
uv sync

# 2. Fetch sources, score every area unit, validate the output (cdmxmap CLI)
uv run cdmxmap run --city cdmx --area-unit postal_code
uv run cdmxmap score --area-unit colonia
uv run cdmxmap validate

# 3. Frontend
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5174
```

Open [http://127.0.0.1:5174](http://127.0.0.1:5174).

`cdmxmap run` orchestrates the per-source fetchers (postal codes, colonias,
transit, supermarkets, gyms, crime) and then builds scores; pass `--skip-fetch`
to rebuild scores from already-downloaded data, or use `cdmxmap fetch` /
`cdmxmap score` individually. City profiles live in
`data/cities/<city_id>/city.json` (`cdmx` plus the Norwegian cities `oslo`,
`bergen`, `trondheim`, and `stavanger`); every fetcher a profile lists is
city-aware. Build another city's map with, for example,
`uv run cdmxmap run --city bergen --area-unit postal_code`. The pipeline lives in
the importable `src/cdmxmap/` package; `python -m cdmxmap` is equivalent to the
`cdmxmap` command.

## Development

- **Contributing & workflow:** [`CONTRIBUTING.md`](CONTRIBUTING.md)
- **Engineering standards (A–S):** [`docs/engineering-standards.md`](docs/engineering-standards.md)
- **Architecture:** [`docs/architecture.md`](docs/architecture.md)
- **Data contract:** [`docs/data-contract.md`](docs/data-contract.md)
- **Testing:** [`docs/testing.md`](docs/testing.md) · **Troubleshooting:** [`docs/troubleshooting.md`](docs/troubleshooting.md)

```bash
uv run ruff check . && uv run mypy && uv run pytest   # Python gates
cd frontend && npm run lint && npm run typecheck && npm run build   # frontend gates
```

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
- Work and amenity travel times are generated offline. The default is a straight-line estimate; passing `--travel-router valhalla` uses real **offline road routing** (Valhalla, free-flow) baked into the static GeoJSON, with a per-feature straight-line fallback. Routed values are labeled `valhalla_free_flow`. See `docs/road-routing.md` (setup: `uv sync --extra routing`, then `cdmxmap build-tiles`).
- Amenity travel times use straight-line nearest-candidate narrowing, then route those candidates and pick the genuinely fastest destination when routing is enabled.
- Safety score is lower-is-better recent crime density. It uses the latest 12 months available in the FGJ CSV, not the current calendar date.

## Multi-City Evolution

The pipeline is already `--city` profile-driven. Alongside CDMX it ships four
Norwegian cities — **Oslo**, **Bergen**, **Trondheim**, and **Stavanger** — each
built from `data/cities/<id>/{city.json,places.json}` and viewable in the frontend
via the city switcher or `?city=<id>`. Adding another Norwegian city is mostly a
profile (set its `municipality_code`); other countries additionally need an
area/transit fetcher. See `docs/multi-city-roadmap.md` for the full contract.
