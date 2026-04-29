# GitHub Pages Deployment

## Assumptions

The app is a static Vite build. There is no runtime backend, and the browser only loads static assets that are produced ahead of time:

- `data/scores_postal_code.geojson`
- `data/scores_colonia.geojson`
- `data/score_metadata_postal_code.json`
- `data/score_metadata_colonia.json`
- `data/score_metadata.json`
- compiled JS/CSS/assets from Vite

Python scripts are only for offline preprocessing. They should be run before building when source data changes.

## Nested Path Compatibility

`frontend/vite.config.ts` sets:

```ts
base: './'
```

This makes the production build use relative asset URLs, so the same `dist/` output can be served from a nested GitHub Pages path such as:

```text
/projects/cdmx-convenience-map/
```

Runtime data fetches also use Vite's base URL:

```ts
fetch(`${import.meta.env.BASE_URL}data/scores_postal_code.geojson`)
fetch(`${import.meta.env.BASE_URL}data/scores_colonia.geojson`)
fetch(`${import.meta.env.BASE_URL}data/score_metadata_postal_code.json`)
fetch(`${import.meta.env.BASE_URL}data/score_metadata_colonia.json`)
fetch(`${import.meta.env.BASE_URL}data/score_metadata.json`)
```

With `base: './'`, those resolve relative to the deployed page instead of the domain root.

## Build

From the repository root:

```bash
cd frontend
npm install
npm run build
```

The static site output is written to:

```text
frontend/dist/
```

Deploy the contents of `frontend/dist/` as the GitHub Pages artifact or static site root.

## Data Assets

The production build copies everything under `frontend/public/` into `frontend/dist/`. The scored map data must exist before building:

```text
frontend/public/data/scores_postal_code.geojson
frontend/public/data/scores_colonia.geojson
frontend/public/data/score_metadata_postal_code.json
frontend/public/data/score_metadata_colonia.json
frontend/public/data/score_metadata.json
```

If processed data needs to be regenerated first, run the offline pipeline from the repo root:

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

## What Not To Commit

Do not commit local dependencies, raw data, or generated build output unless the repository intentionally switches to a committed-`dist` Pages workflow:

- `frontend/node_modules/`
- `frontend/dist/`
- `.venv/`
- `data/raw/*.csv`
- `data/raw/*.json`
- `data/raw/*.zip`
- `data/processed/*`

The current repo is set up for generated `dist/` output to stay ignored.
