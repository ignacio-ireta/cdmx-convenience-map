# Architecture

The CDMX Convenience Map is a **dual-stack, offline-compute + static-serve**
system. Heavy geospatial work happens once, ahead of time, in Python; the browser
only renders pre-computed GeoJSON. There is no runtime backend.

```
                 ┌──────────────────────── Python pipeline (src/cdmxmap) ───────────────────────┐
 city.json  ──▶  │  sources/        scoring/            output/           pipeline.py           │
 places.json     │  fetch+normalize → engine over    → geojson +        → run orchestration,   │
 open data  ──▶  │  each source       typed model       metadata           resume, run manifest │
                 │  (Overpass,        (distance,                                                 │
                 │   Apimetro,         density,                                                  │
                 │   CDMX, FGJ)        crime, transit)                                           │
                 └──────────────────────────────────────────────┬──────────────────────────────┘
                                                                 ▼
                  frontend/public/data/[<city>/]scores_<unit>.geojson + score_metadata_*.json
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
  bounded retries and committed-seed fallback for OSM sources. A city profile's
  `fetchers` list picks the modules. The Mexican metro fetchers
  (`fetch_mx_postal_codes`, `fetch_mx_colonias`, `fetch_nl_transit`,
  `fetch_gtfs_transit`, `fetch_denue_gyms`, `fetch_sesnsp_crime_statistics`,
  `fetch_iieg_crime`) share `mx_common`: validated, atomic downloads into the
  gitignored raw cache, and state-wide INEGI and SEPOMEX layers cached once and
  trimmed per city. See `data-pipeline.md`.
- **`scoring/`** — `areas` (load/normalize geometries), `points` (nearest /
  candidate routing), `metrics` (distance & inverse-density scores, travel-time
  estimates), `crime` (two modes: per-area incident density, optionally over a
  buffer, or per-municipality rates in `city_statistics` mode), `transit`
  (stop-pair approximation + optional r5py overlay, with the commute models in
  `transit_commute/`), `notes` (per-city metadata wording; CDMX keeps its exact
  strings), and `engine.score_areas()` which assembles the contract.
- **`routing/`** — opt-in offline road routing for work/amenity travel times: a
  `Router` Protocol, the `ValhallaRouter` adapter (in-process `pyvalhalla`), a
  keyed `RoutingCache`, and the area-to-area matrix codec/builder. Off by default
  (straight-line fallback); separate from schedule-aware transit. See
  `docs/road-routing.md`.
- **`output/`** — `geojson` (atomic writes), `metadata`, and `parts` (publishes a
  unit with `public_part_max_bytes` as ordered part files plus an index, so no
  public file reaches the 10 MB pre-commit limit; see `data-contract.md`).
- **`pipeline.py`** — `run_pipeline` orchestrates a city run: per-source failure
  isolation (one failed source does not stop the rest unless `--fail-fast`),
  `--resume` (skip sources whose output already exists), clean handling of
  Ctrl-C, and meaningful exit codes.
- **`manifest.py`** — the run manifest written to `runs/<run_id>/`: per-source
  and per-area status, source SHA-256, output paths, timings, plus `errors.json`.
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

Each city is a `CityConfig` in `constants.ts`: theme, map view, default weights,
geographies, store and transit toggles, asset paths (`cityDataAssets`), source
labels, and `safetyMode` (`incident_points` or `city_statistics`). App code
reads these instead of branching on the city id (the only CDMX special case is
that its URL has no `?city=`). `lib/safety.ts` formats the two
safety modes, `lib/routingMatrix.ts` loads the selected city's matrix index, and
`lib/areaData.ts` loads a unit's scores from one GeoJSON file or from a parts
index and its parts (Monterrey and Guadalajara colonias).

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
`road-routing.md`, `r5py-prototype-results.md`, `true-transit-routing-spike.md`.
