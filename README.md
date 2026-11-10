# Multi-City Convenience Map — Norway & Mexico

**Where should an apartment search start?** This project scores every postal area of a city on commute, transit, groceries, and gyms, and draws the result as an interactive map. It covers **five Norwegian cities — Oslo, Bergen, Stavanger, Trondheim, and Drammen —** and two Mexican ones, Mexico City and Morelia.

A typed Python pipeline does the geospatial work offline and writes enriched GeoJSON. A static React + Leaflet frontend renders it and re-scores in the browser as you change weights, workplace, or travel mode. There is no backend.

> The repository and package keep the name `cdmx-convenience-map` / `cdmxmap` because the project began with Mexico City (CDMX). The pipeline has been city-agnostic since the Oslo release.

## Live maps

| City | Open | Areas scored | Area and point data |
|---|---|---:|---|
| **Oslo** | [map](https://ignacio-ireta.github.io/projects/cdmx-map/?city=oslo) | 505 postal areas | Kartverket postnummerområder (Geonorge WFS) · OpenStreetMap |
| **Bergen** | [map](https://ignacio-ireta.github.io/projects/cdmx-map/?city=bergen) | 145 postal areas | Kartverket · OpenStreetMap |
| **Trondheim** | [map](https://ignacio-ireta.github.io/projects/cdmx-map/?city=trondheim) | 77 postal areas | Kartverket · OpenStreetMap |
| **Stavanger** | [map](https://ignacio-ireta.github.io/projects/cdmx-map/?city=stavanger) | 59 postal areas | Kartverket · OpenStreetMap |
| **Drammen** | [map](https://ignacio-ireta.github.io/projects/cdmx-map/?city=drammen) | 46 postal areas | Kartverket · OpenStreetMap |
| **Mexico City** | [map](https://ignacio-ireta.github.io/projects/cdmx-map/) | 1,215 postal codes · 1,837 colonias | CDMX open data · Apimetro · OpenStreetMap · FGJ crime records |
| **Morelia** | [map](https://ignacio-ireta.github.io/projects/cdmx-map/?city=morelia) | 154 postal codes | SEPOMEX (open-mexico) · OpenStreetMap |

Area counts are from the published `score_metadata_postal_code.json` of each city (generated 2026-07-05).

## What it demonstrates

- **One pipeline, seven cities.** A city is a profile (`data/cities/<id>/city.json`), not a fork. Adding a Norwegian city means setting its Kartverket `municipality_code`, bounding box, and reference workplace.
- **Norwegian open geodata handled properly.** The national postal-area dataset is fetched once from the Geonorge WFS, validated before it is cached, and trimmed per municipality; distances are computed in EPSG:25832 (ETRS89 / UTM 32N). Grocery scoring knows the local chains (Rema 1000, Kiwi, Coop, Meny, Joker, Bunnpris).
- **Explainable scores.** Each area shows its raw distances, nearest places, and score breakdown; a data-audit panel shows source counts. Weights are sliders, not constants.
- **Honest travel times.** The published maps use straight-line and stop-pair estimates, labeled as such. Offline road routing with Valhalla (`--travel-router valhalla`) and a schedule-aware r5py transit overlay are opt-in, with a per-feature fallback, and their output is labeled by source.
- **Engineering discipline.** `uv` with pinned geospatial dependencies, `ruff`, `mypy`, unit, integration, and end-to-end tests, a written [data contract](docs/data-contract.md), resumable runs with a manifest, atomic writes, and CI on Python 3.11 and 3.12 plus the frontend.

```
city profile + open data ──▶ sources/ ──▶ scoring/ ──▶ output/ (GeoJSON + metadata + manifest)
                                                            │
                                React + TypeScript + Leaflet ◀┘  re-scores in the browser, static hosting
```

Details: [`docs/architecture.md`](docs/architecture.md).

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
`data/cities/<city_id>/city.json` — the Mexican cities `cdmx` and `morelia`, plus
the Norwegian cities `oslo`, `bergen`, `trondheim`, `stavanger`, and `drammen`;
every fetcher a profile lists is city-aware. Build another city's map with, for
example, `uv run cdmxmap run --city bergen --area-unit postal_code`. The pipeline lives in
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

- A city switcher (or `?city=<id>` in the URL) across the seven city profiles.
- Postal-area polygons colored by the selected convenience score, for every city.
- CDMX colonia polygons as a second geography layer.
- Geography selector for postal code and colonia (CDMX).
- Metric selector for combined, work, transit, supermarkets, gyms, and safety.
- Area detail panel with raw distances, nearest known point, and score breakdown.
- Editable work postal code; the browser recalculates work distance and combined score from that postal code's representative point.
- Work score mode selector for straight-line distance, driving time, walking time, and biking time.
- Store and gym score mode selectors for distance-based or offline time-estimated scoring.
- Weight sliders that recompute the combined score in the browser.
- Data-audit panel with source counts for postal codes, Apimetro transit points, OSM stores, OSM gyms, and FGJ crime records.
- Offline scoring pipeline with replaceable raw data sources.

## Data Notes

### Norway

- Postal-area polygons (postnummerområder) come from Kartverket through the [Geonorge WFS](https://kartkatalog.geonorge.no/metadata/postnummeromrader/462a5297-33ef-438a-82a5-07fff5799be3). The service returns the whole country, so the pipeline downloads it once to a shared cache and each city trims it by municipality code.
- Transit stops, supermarkets, and gyms come from OpenStreetMap through the [Overpass API](https://overpass-api.de/api/interpreter). Stops are grouped into rail (core) and bus (surface). Oslo, for example, is scored against 5,039 stops, 440 supermarkets, and 119 gyms.
- The transit commute is an OpenStreetMap stop-pair approximation, not a timetable query.
- There is no safety component for Norwegian cities: its weight is 0 because no comparable open crime dataset is used.
- The default workplace is a configured reference point per city (Oslo S for Oslo) in `data/cities/<id>/places.json`.

### Mexico

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

## Adding a City

The pipeline is `--city` profile-driven. Alongside CDMX it ships five
Norwegian cities — **Oslo**, **Bergen**, **Trondheim**, **Stavanger**, and
**Drammen** — and a second Mexican city, **Morelia** (postal-code polygons from
the open-mexico SEPOMEX dataset, OpenStreetMap transit/grocery/gym, no crime
scoring), each built from `data/cities/<id>/{city.json,places.json}` and viewable
in the frontend via the city switcher or `?city=<id>`. Adding another Norwegian
city is mostly a profile (set its `municipality_code`); a new Mexican city needs
its `postal_code_range` and the shared OSM fetchers; other countries additionally
need an area/transit fetcher. See `docs/multi-city-roadmap.md` for the full contract.
