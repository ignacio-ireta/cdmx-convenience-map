# Travel-Time-To-Work Roadmap

> **Status update:** offline road routing is now implemented. See
> [`docs/road-routing.md`](road-routing.md) for the Valhalla architecture,
> setup, and the dynamic-workplace matrix. The straight-line method below is the
> default fallback used when no router is configured. (The pipeline is now the
> `cdmxmap` package/CLI; older `scripts/build_scores.py` references are historical.)

## Current Implementation (default / fallback)

Travel-time-to-work is generated offline by the `cdmxmap` pipeline (`cdmxmap run`
/ `cdmxmap score`); the browser only loads static GeoJSON.

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

## Replacing The Fallback — implemented

This is now done with **Valhalla** routing, run only during preprocessing, writing
static fields to GeoJSON. The shape closely follows the original plan, adapted to
the `src/cdmxmap/` package layout:

1. A routing abstraction lives under `src/cdmxmap/routing/` (a `Router` Protocol,
   the `ValhallaRouter` adapter, a `RoutingCache`, and the matrix codec/builder).
2. `score_areas(..., router=...)` routes work + amenity candidates per mode.
3. Results are cached by area unit/id, origin & destination coords, mode, engine,
   version, profile, and an inputs hash, under the ignored `data/processed/routing_cache/`.
4. For amenities only the straight-line candidate set is routed (candidate
   narrowing is retained), then the genuinely fastest routed destination is chosen.
5. On routing/snapping failure a row falls back to the straight-line estimate and
   is labeled `fallback_straight_line_estimate` per feature; routed rows are
   labeled `valhalla_free_flow`. Routed distance is stored separately (`*_routed_m`).
6. A single writer still renders the GeoJSON (`output/geojson.py`).

The dynamic-workplace area-to-area matrix is precomputed and served as a binary +
index (`cdmxmap build-matrix`); see [`docs/road-routing.md`](road-routing.md).

No API keys are used (Valhalla is local and free-flow). Hosted options
(OpenRouteService, GraphHopper) were rejected for needing keys/rate limits;
OSRM remains a documented drop-in alternative behind the `Router` Protocol.
