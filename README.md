# Multi-City Convenience Map — Norway & Mexico

**Where should an apartment search start?** This project scores every postal area of a city on commute, transit, groceries, and gyms, and draws the result as an interactive map. It covers nine cities: **five Norwegian ones — Oslo, Bergen, Stavanger, Trondheim, and Drammen —** and four Mexican ones: Mexico City, Monterrey, Guadalajara, and Morelia.

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
| **Monterrey** | [map](https://ignacio-ireta.github.io/projects/cdmx-map/?city=monterrey) | 658 postal codes · 4,698 colonias | SEPOMEX (open-mexico) · INEGI · Nuevo León open data · OpenStreetMap · SESNSP |
| **Guadalajara** | [map](https://ignacio-ireta.github.io/projects/cdmx-map/?city=guadalajara) | 401 postal codes · 2,648 colonias | SEPOMEX (open-mexico) · INEGI · SETRAN Jalisco GTFS · OpenStreetMap · IIEG Jalisco |
| **Morelia** | [map](https://ignacio-ireta.github.io/projects/cdmx-map/?city=morelia) | 154 postal codes | SEPOMEX (open-mexico) · OpenStreetMap |

Area counts are from each city's published `score_metadata_*.json` (generated 2026-07-05; Monterrey and Guadalajara 2026-11-25).

## What it demonstrates

- **One pipeline, nine cities.** A city is a profile (`data/cities/<id>/city.json`), not a fork. Adding a Norwegian city means setting its Kartverket `municipality_code`, bounding box, and reference workplace; a Mexican metro area lists its INEGI state and municipality codes (`mx_area`).
- **Norwegian open geodata handled properly.** The national postal-area dataset is fetched once from the Geonorge WFS, validated before it is cached, and trimmed per municipality; distances are computed in EPSG:25832 (ETRS89 / UTM 32N). Grocery scoring knows the local chains (Rema 1000, Kiwi, Coop, Meny, Joker, Bunnpris).
- **Mexican open data from many publishers.** Monterrey and Guadalajara combine SEPOMEX postal polygons (open-mexico), INEGI municipalities, colonias (DCAH 2025) and business directory (DENUE), state transit data (Nuevo León's GeoPackages, SETRAN Jalisco's GTFS), OpenStreetMap stores, and two different crime sources (SESNSP municipal rates, IIEG Jalisco incident points). Each download is validated before it is cached, and each value carries its source label.
- **Explainable scores.** Each area shows its raw distances, nearest places, and score breakdown; a data-audit panel shows source counts. Weights are sliders, not constants.
- **Honest travel times.** Monterrey and Guadalajara are published with offline Valhalla road routing (free-flow, no traffic) for work and amenity times, plus a routed area-to-area matrix so any postal code can be the workplace. The other cities use straight-line and stop-pair estimates. Every value is labeled routed or estimate, with a per-feature fallback; a schedule-aware r5py transit overlay is opt-in.
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
`data/cities/<city_id>/city.json` — the Mexican cities `cdmx`, `monterrey`,
`guadalajara`, and `morelia`, plus the Norwegian cities `oslo`, `bergen`,
`trondheim`, `stavanger`, and `drammen`; every fetcher a profile lists is
city-aware. Build another city's map with, for example,
`uv run cdmxmap run --city bergen --area-unit postal_code`. Monterrey and
Guadalajara are published with road routing; their build sequence is in
[`docs/road-routing.md`](docs/road-routing.md). The pipeline lives in
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

- A city switcher (or `?city=<id>` in the URL) across the nine city profiles.
- Postal-area polygons colored by the selected convenience score, for every city.
- Colonia polygons as a second geography layer for CDMX, Monterrey, and Guadalajara.
- Geography selector for postal code and colonia (CDMX, Monterrey, Guadalajara).
- Metric selector for combined, work, transit, supermarkets, gyms, and safety.
- Area detail panel with raw distances, nearest known point, and score breakdown. In Monterrey and Guadalajara the area header also shows the postal area's colonia names and its municipality.
- Editable work postal code; the browser recalculates work distance and combined score from that postal code's representative point. On the Monterrey and Guadalajara postal-code maps, drive, walk, and bike times to a custom workplace come from the precomputed routed matrix.
- Work score mode selector for straight-line distance, driving time, walking time, and biking time.
- Store and gym score mode selectors for distance-based or offline time-estimated scoring.
- Store-brand toggles per city, and transit-system toggles (for example Metrorrey, TransMetro BRT, TransMetro, and Rutas urbanas in Monterrey) that re-score transit access in the browser.
- A safety panel that matches the city's crime source: incident counts and density (CDMX, Guadalajara, with Guadalajara's data window named) or a municipal rate per 100k residents shared by every area in the municipality (Monterrey).
- Weight sliders that recompute the combined score in the browser.
- Data-audit panel with each city's source counts: areas, transit points, stores, gyms, and crime records or municipalities.
- Offline scoring pipeline with replaceable raw data sources.

## Data Notes

### Norway

- Postal-area polygons (postnummerområder) come from Kartverket through the [Geonorge WFS](https://kartkatalog.geonorge.no/metadata/postnummeromrader/462a5297-33ef-438a-82a5-07fff5799be3). The service returns the whole country, so the pipeline downloads it once to a shared cache and each city trims it by municipality code.
- Transit stops, supermarkets, and gyms come from OpenStreetMap through the [Overpass API](https://overpass-api.de/api/interpreter). Stops are grouped into rail (core) and bus (surface). Oslo, for example, is scored against 5,039 stops, 440 supermarkets, and 119 gyms.
- The transit commute is an OpenStreetMap stop-pair approximation, not a timetable query.
- There is no safety component for Norwegian cities: its weight is 0 because no comparable open crime dataset is used.
- The default workplace is a configured reference point per city (Oslo S for Oslo) in `data/cities/<id>/places.json`.

### Mexico City

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

### Monterrey and Guadalajara

Both maps cover a metro area as defined in SEDATU/CONAPO/INEGI *Metrópolis de México 2020*: Monterrey is the 12 central municipalities of the Zona Metropolitana de Monterrey (658 postal codes, 4,698 colonias), and Guadalajara is all 7 municipalities of the Zona Metropolitana de Guadalajara (401 postal codes, 2,648 colonias).

- **Postal codes.** SEPOMEX polygons from the open-mexico state GeoJSON (the same source as Morelia). Each polygon is assigned to the INEGI municipality it overlaps most; the municipal polygons and their Censo 2020 population come from INEGI's Marco Geoestadístico (wscatgeo `mgem` service). The label under a postal code, for example "Colonia del Valle, Jardines del Valle +6" for CP 66220, lists INEGI colonia names. The SEPOMEX/Correos settlement catalog is not used because its terms forbid redistribution.
- **Colonias.** INEGI *Delimitación de colonias y otros asentamientos humanos* (DCAH) 2025. Unnamed placeholder polygons are dropped: 411 in Monterrey and 91 in Guadalajara.
- **Transit, Monterrey.** Nuevo León open data ([catalogodatos.nl.gob.mx](https://catalogodatos.nl.gob.mx)): the STC Metrorrey GeoPackage (3T2026) and the IMA GeoPackage (Q3 2026). Metrorrey has 41 station-lines (Line 1: 19, Line 2: 13, Line 3: 9). TransMetro BRT has 57 stations (Ecovía 40, Av. México 17), named after the nearest OpenStreetMap station because the official names do not match their coordinates. TransMetro has 1,382 stops, and Rutas urbanas has 8,170 IMA stops with their route numbers. Metrorrey Lines 4 and 6 are not yet in service and will be added when they open (target February 2027).
- **Transit, Guadalajara.** The SETRAN Jalisco GTFS feed ([Mobility Database `mdb-3632`](https://mobilitydatabase.org/feeds/gtfs/mdb-3632), version of 2026-11-17): Mi Tren 56 station-lines (L1 20, L2 10, L3 18, L4 8), Mi Macro 84 (L5 9, L6 27, L7 48), Alimentadoras 1,806 stops, Mi Transporte Tren Ligero 675, and Mi Transporte 11,867.
- Each transit system is a toggle in the map. Stops carry their line ids (several routes are joined with `|`), so the stop-pair commute estimate can tell a same-line trip from a transfer, and rail and BRT stations are always among its candidate stops. It is still not schedule-aware; see [`docs/transit-commute.md`](docs/transit-commute.md).
- **Supermarkets.** OpenStreetMap through Overpass, sorted into store families by a deterministic classifier: it reads `brand:wikidata`, then `brand`, then `name`, and never `operator` (Walmart de México operates several of the chains). Toggles in Monterrey: H-E-B, Soriana, Walmart, Bodega Aurrerá, S-Mart, Sam's Club, and Costco (368 classified points). In Guadalajara: Bodega Aurrerá, Soriana, Walmart, Chedraui, Sam's Club, La Comer / City Market / Fresko, and Costco (173 points). Smaller chains count toward the overall supermarket score without a toggle. An Overpass reply whose OSM data is more than 30 days old is rejected, because some mirrors lag by months.
- **Gyms.** INEGI DENUE (May 2026 release, fitness centres with SCIAN codes 713943 and 713944): 1,483 in Monterrey and 1,414 in Guadalajara. OpenStreetMap has about 90 in each.
- **Safety, Monterrey.** SESNSP municipal crime incidence (fuero común; the 2015–2025 file and the 2026 RNID file) for 2025-11-01 to 2026-10-31, per 100k residents (Censo 2020). The scored subset, "robbery and violent crime", is all robbery, intentional homicide and feminicide (including attempts), intentional injury, kidnapping, extortion, and rape. The 12 municipalities are ranked within the metro, lowest rate 100 and highest 0, and every postal code or colonia in a municipality shares that score. This is municipal context, not neighbourhood safety. The safety weight is 10%.
- **Safety, Guadalajara.** IIEG Jalisco's Región Centro microdata from the state Fiscalía: geocoded incidents of 16 high-impact crime types, January 2017 to August 2025. The score uses September 2024 to August 2025, counted over each area plus a 250 m buffer so that a tiny colonia with no records does not read as perfectly safe. IIEG has published no newer release. Only per-area aggregates are written.
- Safety scores are relative within a city. Do not compare them across cities: the Nuevo León and Jalisco Fiscalías record crime very differently.
- **Travel times.** Work and amenity times are offline Valhalla free-flow road routes (no traffic) on one national Mexico tileset built from Geofabrik's Mexico extract, with a straight-line fallback labeled per feature. Routed driving times come out at about 0.45× the straight-line estimate the other cities use, so routed and unrouted cities are not comparable. A routed postal-code matrix lets any postal code be the workplace. Colonias have routed times to the default workplace but no matrix (Monterrey's would be about 132 MB), so a custom workplace on the colonia view uses the labeled estimate. See [`docs/road-routing.md`](docs/road-routing.md).
- **Default workplaces.** Monterrey: CP 66260 (Valle Oriente, San Pedro Garza García). Guadalajara: CP 45116 (Andares / Puerta de Hierro, Zapopan). Both are set in `data/cities/<id>/places.json`.
- **Licences and attribution.**
  - INEGI (municipalities, DCAH colonias, DENUE): Términos de Libre Uso de la Información del INEGI; credit "Fuente: INEGI".
  - open-mexico postal polygons: MIT, derived from SEPOMEX.
  - Gobierno de Nuevo León open data (STC Metrorrey, IMA): CC-BY.
  - SESNSP incidence: datos abiertos, CC-BY 4.0 on datos.gob.mx.
  - IIEG Jalisco: published as "datos abiertos … de libre uso"; no explicit licence was found.
  - SETRAN Jalisco GTFS: **no licence is stated** (the feed has no `feed_info.txt`, and the Mobility Database page names none). Confirm with SETRAN before redistributing the derived stop points.
  - OpenStreetMap: ODbL, © OpenStreetMap contributors.
- **Known limitations.**
  - The IIEG crime data ends in August 2025.
  - The GTFS service calendar ends 2026-12-31. Only stops and lines are used, so the map is unaffected, but the feed should be refreshed.
  - Per-capita crime rates use Censo 2020 population, which overstates rates in fast-growing municipalities.
  - The colonia layers are large: about 27.5 MB for Monterrey and 15.5 MB for Guadalajara (about 3.1 MB and 1.9 MB gzipped). They are published as parts under 9 MB each (4 and 2 parts) plus a `scores_colonia_index.json`, because the repository's pre-commit check caps added files at 10 MB; the app downloads the parts in parallel and joins them.

## Adding a City

The pipeline is `--city` profile-driven. Alongside CDMX it ships five
Norwegian cities — **Oslo**, **Bergen**, **Trondheim**, **Stavanger**, and
**Drammen** — and three more Mexican cities: **Morelia** (postal-code polygons
from the open-mexico SEPOMEX dataset, OpenStreetMap transit/grocery/gym, no crime
scoring), and the metro areas of **Monterrey** and **Guadalajara** (postal codes
and INEGI colonias, state transit open data, DENUE gyms, crime scoring, and road
routing). Each is built from `data/cities/<id>/{city.json,places.json}` and
viewable in the frontend via the city switcher or `?city=<id>`. Adding another
Norwegian city is mostly a profile (set its `municipality_code`). A Mexican
metro area lists its INEGI state and member municipalities in `mx_area` and
reuses the INEGI/SEPOMEX, store, and DENUE fetchers and the national SESNSP
municipal crime statistics; it needs a transit fetcher only when its open data
is neither GTFS nor OpenStreetMap. Other countries additionally need an
area/transit fetcher. See `docs/multi-city-roadmap.md` for the full contract.
