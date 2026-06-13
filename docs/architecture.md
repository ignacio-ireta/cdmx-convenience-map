# Architecture

The CDMX Convenience Map is a **dual-stack, offline-compute + static-serve**
system. Heavy geospatial work happens once, ahead of time, in Python; the browser
only renders pre-computed GeoJSON. There is no runtime backend.

```
                 ┌──────────────────────── Python pipeline (src/cdmxmap) ───────────────────────┐
 city.json  ──▶  │  sources/        scoring/            output/           pipeline/             │
 places.json     │  fetch+normalize → engine over    → geojson +        → runner / state /     │
 open data  ──▶  │  each source       typed model       metadata +         manifest / progress  │
                 │  (Overpass,        (distance,         manifest                                │
                 │   Apimetro,         density,                                                  │
                 │   CDMX, FGJ)        crime, transit)                                           │
                 └──────────────────────────────────────────────┬──────────────────────────────┘
                                                                 ▼
                              frontend/public/data/scores_<unit>.geojson + score_metadata_*.json
                                                                 ▼
                 ┌──────────────────────── React + TS + Leaflet (Vite) ────────────────────────┐
                 │  fetch+normalize → in-browser re-scoring (weights, work loc, modes) → map    │
                 └──────────────────────────────────────────────────────────────────────────────┘
                                                                 ▼
                                  GitHub Pages  ──(embed sync)──▶  personal website
```

## Pipeline (Python)

Data flow: **city profile + config → sources → typed intermediate model →
scoring engine → output writer → run report**. The key design rule (standards
§F): fetch, score, and render are separable; nothing but the writer emits
GeoJSON.

- **`sources/`** — one module per open-data source (postal codes, colonias,
  transit, supermarkets, gyms, crime) plus shared `http`/`overpass` clients with
  bounded retries and committed-seed fallback for OSM sources.
- **`scoring/`** — `areas` (load/normalize geometries), `points` (nearest /
  candidate routing), `metrics` (distance & inverse-density scores, travel-time
  estimates), `crime` (spatial aggregation), `transit/` (Apimetro approximation +
  optional r5py overlay), and `engine.score_areas()` which assembles the contract.
- **`output/`** — `geojson` (atomic writes), `metadata`, `manifest`.
- **`pipeline/`** — `runner` orchestrates a city run with per-source isolation;
  `state` tracks the manifest (hashing, skip-unchanged, resume); `progress`
  renders rich progress.
- **`cli.py / config.py / models.py / errors.py / logging_config.py`** — entry
  point, config loading, pydantic models (the intermediate model + validated
  config), domain exceptions, logging setup.

The intermediate model is a set of frozen dataclasses (`AreaConfig`,
`PointDatasets`, `NearestResult`, `AmenityRouteResult`, `ScoredAreaResult`).

## Frontend

A single-page React 19 + TypeScript app using Leaflet (`react-leaflet`). It
fetches the score GeoJSON + metadata, normalizes raw properties to a typed
`AreaProperties`, and **re-scores in the browser** as the user changes weights,
work location, travel mode, and store/transit preferences — so interaction needs
no server. After Phase 5 the monolithic `App.tsx` is decomposed into
`types`/`constants`, `lib/*` pure helpers, `hooks/*`, and `components/*`.

Vite builds with a relative `base` (`./`) so the bundle works from a nested path,
which is what lets it be embedded under `projects/cdmx-map/` on the personal site.

## Deployment

`.github/workflows/deploy.yml` builds the frontend, publishes to GitHub Pages,
and (when `WEBSITE_REPO_DEPLOY_KEY` is configured) syncs the built app into the
personal website repo via `scripts/sync_website_embed.sh`. CI (`ci.yml`) gates
this. See `docs/github-pages.md` and `docs/website-embed-sync.md`.

## Related design docs

`current-state.md`, `data-pipeline.md`, `multi-city-roadmap.md`,
`transit-commute.md`, `transit-routing-roadmap.md`, `travel-time-roadmap.md`,
`r5py-prototype-results.md`, `true-transit-routing-spike.md`.
