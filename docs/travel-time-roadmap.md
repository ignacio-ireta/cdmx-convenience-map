# Travel-Time-To-Work Roadmap

## Current Implementation

Travel-time-to-work is generated offline in `scripts/build_scores.py`; the browser only loads static GeoJSON.

The default workplace lives in `data/config/places.json`:

- Name: `Default Workplace - CP 11510`
- Postal code: `11510`
- Coordinates: representative point from the CDMX postal-code polygon
- Source: `places_config`

The current routing source is `fallback_straight_line_estimate`. For every scored area, the pipeline:

1. Uses the area's representative point.
2. Computes straight-line distance to the configured workplace.
3. Estimates travel time with a mode-specific detour factor and speed.
4. Writes travel-time fields into the static GeoJSON.

Generated fields:

- `time_work_driving_min`
- `time_work_walking_min`
- `time_work_biking_min`
- `score_work_driving`
- `score_work_walking`
- `score_work_biking`
- `work_travel_time_source`

The legacy `dist_work_m` and `score_work` fields are preserved. In the frontend, `Distance` keeps the existing work-distance behavior; `Drive`, `Walk`, and `Bike` use the new travel-time fields when present.

Amenity travel times use the same offline-only principle. For supermarkets, Costco, Walmart, and gyms, the pipeline first keeps only the nearest configured candidate POIs by straight-line distance, currently `5`, then estimates travel time for those candidate pairs. This avoids the expensive and unnecessary all-areas-to-all-POIs matrix.

Generated amenity fields:

- `time_supermarket_min`
- `time_costco_min`
- `time_walmart_min`
- `time_gym_min`
- `nearest_costco_name`
- `nearest_walmart_name`
- `score_supermarkets_time`
- `score_gyms_time`
- `amenity_travel_time_source`

## Limitations

The fallback is intentionally crude. It does not know street networks, hills, traffic, one-way streets, transfers, safety, or actual route geometry. Because the fallback is a linear conversion from straight-line distance, mode-specific scores will generally rank areas similarly until a real routing source is plugged in. The displayed minutes are useful as rough placeholders, not commute promises.

No routing calls happen in the browser. This keeps GitHub Pages deployment static and avoids exposing API keys.

## Replacing The Fallback

The replacement should still run only during preprocessing and write static fields to GeoJSON.

Recommended shape:

1. Add a routing adapter under `scripts/`, for example `scripts/routing.py`.
2. Give it a function such as `get_work_travel_times(area_points, workplace, modes)`.
3. Cache results by `area_unit`, `area_id`, mode, source, and workplace coordinate under `data/processed/routing_cache/` or another ignored path.
4. For amenities, cache by `area_unit`, `area_id`, POI identifier/name, mode, source, and destination coordinate. Only candidate pairs should be routed or cached.
5. On routing failures, return nulls for failed rows or fall back to the current straight-line estimate.
6. Keep `scripts/build_scores.py` as the single writer of final GeoJSON fields.

Candidate routing sources:

- OSRM: good for local/offline driving, walking, and biking if profiles are prepared.
- Valhalla: strong multimodal routing, heavier local setup.
- OpenRouteService: easy hosted API, but requires an API key and strict caching/rate-limit handling.
- GraphHopper: hosted or local option, similar key/caching considerations.

Do not put API keys in the repo or browser. Use environment variables during preprocessing, and cache the resulting travel times into generated static assets.
