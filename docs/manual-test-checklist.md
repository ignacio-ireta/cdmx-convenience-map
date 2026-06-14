# Manual Test Checklist

Use this before deploying or after changing scoring/data files. The automated
gates (lint, type-check, unit tests, build) now run in CI
(`.github/workflows/ci.yml`) and in the deploy quality gate; the checks below are
the data-regeneration steps CI cannot run (they need network sources) plus the
browser smoke test.

## Automated gates (also run in CI)

```bash
# Python
uv run ruff check . && uv run ruff format --check src scripts tests
uv run mypy && uv run pytest

# Frontend
cd frontend && npm run lint && npm run typecheck && npm run test && npm run build
```

## Data regeneration (run locally; needs network sources)

```bash
uv run cdmxmap run --city cdmx --area-unit postal_code
uv run cdmxmap score --area-unit colonia
uv run cdmxmap validate
```

Confirm:

- `frontend/public/data/scores_postal_code.geojson` exists.
- `frontend/public/data/scores_colonia.geojson` exists.
- `frontend/public/data/score_metadata.json` exists.
- `.gitignore` still excludes `.venv/`, `frontend/node_modules/`, `frontend/dist/`, raw crime CSVs, and `data/processed/`.

## Road routing regeneration (optional; needs the `routing` extra + tiles)

```bash
uv sync --extra routing
uv run cdmxmap build-tiles --pbf data/raw/osm/mexico-city.osm.pbf
uv run cdmxmap run --area-unit postal_code --travel-router valhalla
uv run cdmxmap run --area-unit colonia   --travel-router valhalla
uv run cdmxmap build-matrix --area-unit postal_code --travel-router valhalla
uv run cdmxmap build-matrix --area-unit colonia   --travel-router valhalla
uv run cdmxmap validate
```

Confirm:

- `score_metadata_*.json` has a `road_routing` block with non-zero routed counts.
- A spot-checked feature has `work_travel_time_source: valhalla_free_flow` and a
  `dist_work_routed_m` value; fallback rows show `fallback_straight_line_estimate`.
- `frontend/public/data/routing_matrix_*_index.json` + `*.bin` exist; the PBF,
  `data/processed/valhalla/`, and `data/processed/routing_cache/` are NOT committed.

## Browser Checks

Start local dev:

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5174
```

Then verify:

- Postal-code layer loads and shows `1215 postal codes scored`.
- Colonia selector loads and shows `1837 colonias scored`.
- Metric buttons update the legend for Overall, Work, Transit, Stores, Gyms, and Safety.
- Stores/Gyms can switch between Distance and Time when time fields are present.
- Work can switch between Distance, Drive, Walk, and Bike.
- On a routed build, Drive/Walk/Bike metric rows show a green `routed` badge
  (`Valhalla (free-flow)`); a custom workplace shows `routed` where the matrix
  covers it and an amber `estimate` badge otherwise.
- Weight sliders update the combined ranking/coloring without breaking the map.
- Search `06700` finds and opens `CP 06700`.
- Search `roma` on the colonia layer finds and opens Roma results.
- Details panel shows distances, time estimates, nearest amenities, safety fields, and score breakdown.
- Top-100 list scrolls and the Copy button is visible.
- Browser console has no app errors.

## Static Deploy Checks

After `npm run build`, inspect `frontend/dist/`:

- Built JS/CSS assets are under `assets/`.
- Static data is copied under `data/`.
- No paths in built files assume `/data/...` at the domain root.
- The app works when served from a nested path, for example `/projects/cdmx-convenience-map/`.
