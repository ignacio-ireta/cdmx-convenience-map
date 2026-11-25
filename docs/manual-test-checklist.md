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

### Monterrey and Guadalajara (published routed)

Run the sequence in `docs/road-routing.md` (national tileset at
`data/processed/valhalla_mx`, then `run` postal code, `score` colonia and
`build-matrix` postal code with `--travel-router valhalla`, then
`validate --city <id>`, for each city). Confirm:

- `uv run cdmxmap validate --city monterrey` and `--city guadalajara` pass.
- `frontend/public/data/<id>/score_metadata_postal_code.json` has `feature_count`
  658 (Monterrey) / 401 (Guadalajara), and the colonia metadata 4,698 / 2,648.
- Its `road_routing` block shows `pyvalhalla 3.7.0`, `osm_md5`
  `7140e40aaf94d08ebc0551a8880f3d9e` and the `search_filter`, with only a handful
  of fallback rows per mode.
- `frontend/public/data/<id>/routing_matrix_postal_code_index.json` and three
  `routing_matrix_postal_code_<mode>_<hash>.bin` files exist (Monterrey 865,928 B
  each, Guadalajara 321,602 B each); there is no colonia matrix.
- `frontend/public/data/<id>/scores_colonia_index.json` lists 4 parts
  (Monterrey) / 2 parts (Guadalajara), each `scores_colonia.part-NN.geojson`
  under 9,000,000 bytes, and there is no single `scores_colonia.geojson` there
  (`validate --city` checks the parts against the processed file).
- Monterrey's metadata `crime` block has `mode: city_statistics`, 12 `units`,
  `scored_label` "robbery and violent crime", and the period 2025-11-01 to
  2026-10-31. Guadalajara's has `density_buffer_m: 250` and `latest_date`
  2025-08-31, and its features carry `crime_buffer_m: 250`.
- `data/processed/valhalla_mx/`, `data/raw/osm/`, `data/raw/gtfs/` and the
  per-city `routing_cache/` are NOT committed.

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
- The legend pointer and the locator inset both move to the selected area.
- The scale bar and the coordinate/zoom readout update when the map is zoomed.
- At 900px wide the top list sits below the map in two columns; at 390px it
  follows the map in one column.
- Each city (`?city=oslo`, `?city=bergen`, …) loads in its own colours with the
  same score ramp.
- Browser console has no app errors.

### Monterrey and Guadalajara

Open `?city=monterrey` and `?city=guadalajara` and verify, for each:

- The page loads in the city's colours (Monterrey: orange with a slate counter;
  Guadalajara: ochre with a cobalt counter) with the same score ramp.
- Postal-code layer shows `658 postal codes scored` (Monterrey) / `401 postal
  codes scored` (Guadalajara); the colonia layer shows `4698 colonias scored` /
  `2648 colonias scored`. The colonia layer is large (about 27 MB / 15 MB, fetched
  as the index plus 4 / 2 parts in parallel; check the network panel), so the
  first load is slower.
- Search `66220` (Monterrey) opens `CP 66220, San Pedro Garza García` with the
  muted label "Colonia del Valle, Jardines del Valle +6". Search `44100`
  (Guadalajara) opens `CP 44100, Guadalajara` with the label "Centro".
- Transit toggles list the city's systems (Monterrey: Metro, BRT, TransMetro,
  Rutas; Guadalajara: Mi Tren, Mi Macro, Alimentadoras, SITREN, Mi Transporte).
  Leaving one checked re-colours the Transit metric, and the area panel's row
  reads `Transit access (<system>)`, e.g. `Transit access (Metrorrey)`.
- Brand toggles list seven stores per city (Monterrey: H-E-B, Soriana,
  Walmart, Bodega Aurrerá, S-Mart, Sam's Club, Costco; Guadalajara: Bodega
  Aurrerá, Soriana, Walmart, Chedraui, Sam's Club, La Comer / City Market /
  Fresko, Costco).
- Data audit: Transit reads `Nuevo León open data · 9650 points` /
  `SETRAN GTFS · 14488 points`; Gyms reads `INEGI DENUE`; Work time and Amenity
  time read `Valhalla (free-flow) · … where unrouted`.
- Drive/Walk/Bike rows show the green `routed` badge. Setting another postal
  code as the workplace on the postal-code view keeps `routed` (the browser
  fetches `data/<id>/routing_matrix_postal_code_index.json`, not CDMX's
  `data/routing_matrix_postal_code_index.json`). On the colonia view a custom
  workplace shows the amber `estimate` badge.
- Monterrey safety panel: for CP 64000, Municipal rate reads
  `331.1 per 100k · robbery and violent crime (Monterrey)`, Total rate
  `1782.8 per 100k`, Statistics period `2025-11-01 to 2026-10-31`, Safety scope
  "All postal codes in Monterrey share this municipal rate", and Safety method
  "Ranked within the metro: lowest municipal rate = 100, highest = 0". The data
  audit Crime row ends `· 12 municipalities`. No incident count or density is
  shown.
- Guadalajara safety panel: Crime window reads `Sep 2024 – Aug 2025`; the
  Safety row and crime density say `(area + 250 m)` / `within the area + 250 m`;
  the records row is labelled `All IIEG records`.
- Switching back to Mexico City shows CDMX exactly as before (FGJ wording,
  `1215 postal codes scored`, and `estimate` badges on Drive/Walk/Bike, since
  CDMX's published build is straight-line).

## Static Deploy Checks

After `npm run build`, inspect `frontend/dist/`:

- Built JS/CSS assets are under `assets/`.
- Static data is copied under `data/`.
- No paths in built files assume `/data/...` at the domain root.
- The app works when served from a nested path, for example `/projects/cdmx-convenience-map/`.
