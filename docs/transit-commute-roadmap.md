# Transit Commute Roadmap

## Current State

The current transit score is a proximity score, not a commute-time score.

`scripts/fetch_transit.py` fetches Apimetro station/stop points from:

```text
https://apimetro.dev/movilidad/mapas/geojsonEstacion?sistema=METRO,MB,RTP,TROLE,CC&existe=true
```

It writes normalized points to `data/processed/transit_stops.csv` with `id`, `name`, `system`, `line`, `hierarchy`, `latitude`, `longitude`, and `source`.

`scripts/build_scores.py` then:

1. Splits Apimetro points into core transit and surface transit.
2. Finds nearest straight-line distance from each area's representative point to:
   - any transit point
   - nearest core point: `METRO`, `MB`, `TROLE`
   - nearest surface point: `RTP`, `CC`
3. Scores each distance with the same closer-is-better 95th-percentile cap.
4. Computes `score_transit` as:

```text
0.70 * nearest core transit score + 0.30 * nearest surface transit score
```

Current fields:

- `dist_transit_m`
- `dist_core_transit_m`
- `dist_surface_transit_m`
- `score_transit`
- `nearest_transit_name`
- `nearest_core_transit_name`
- `nearest_surface_transit_name`
- `nearest_transit_source`
- `nearest_core_transit_source`
- `nearest_surface_transit_source`

## Limitation

Nearest station/stop distance is not commute time.

It does not account for:

- whether the nearby stop goes toward the workplace
- route frequency or service windows
- transfers
- waiting time
- in-vehicle time
- walking from the destination stop to the workplace
- station access geometry
- directionality and one-way route patterns
- route disruption or unreliability

The current score is still useful as a quick "am I near transit?" signal, but it should stay separate from true commute scoring.

## Future Data Contract

Future static GeoJSON properties should add:

```text
time_work_transit_min
transfers_work_transit
walk_to_origin_stop_m
destination_walk_m
score_work_transit
transit_route_summary
```

Recommended optional companion fields:

```text
transit_commute_source
transit_commute_service_date
transit_origin_stop_name
transit_destination_stop_name
transit_wait_time_min
transit_in_vehicle_min
transit_walk_time_min
```

`score_work_transit` should be a 0-100 closer-is-better score over `time_work_transit_min`, clipped at the 95th percentile like the other metrics. Missing or unroutable areas should have null values in the raw commute fields and score `0`, with a metadata count of failed routes.

Frontend placeholder support already accepts and conditionally displays the required fields when present. Existing `score_transit` remains untouched.

## Required Data

A real transit commute estimate needs schedule-aware or headway-aware data, not just stop points.

Minimum inputs:

- area representative points from the existing scoring pipeline
- configured workplace coordinate from `data/config/places.json`
- transit stops with stable IDs and coordinates
- transit routes, trips, stop sequences, service calendars, and stop times
- walking connection rules between area points and nearby stops
- walking connection rules from destination stops to the workplace
- a chosen service date and departure time window

Preferred transit input:

- a current CDMX GTFS bundle covering Metro, Metrobús, RTP, Trolebús, Corredor Concesionado, and other relevant modes
- if GTFS coverage is incomplete, mode-specific feeds or curated stop/route tables must be merged and validated before routing

Apimetro is useful for current station/stop geometries and mode labels, but by itself it is not enough for reliable schedule-aware commute time because the current pipeline only uses its point GeoJSON.

## Architecture

Keep the app static:

1. Fetch or load transit schedule/network data offline.
2. Build or start a routing engine locally during preprocessing.
3. Route each area representative point to the configured workplace.
4. Cache route results by area unit, area ID, workplace, service date, departure window, and routing engine version.
5. Write enriched static GeoJSON.
6. Let the browser render only static fields.

Suggested cache key shape:

```text
{engine}:{engine_version}:{area_unit}:{area_id}:{workplace_hash}:{service_date}:{departure_window}
```

Suggested metadata:

```json
{
  "transit_commute": {
    "source": "otp",
    "service_date": "YYYY-MM-DD",
    "departure_window": "08:00-10:00",
    "routed_areas": 1215,
    "failed_areas": 0,
    "cache_hits": 0,
    "cache_misses": 1215
  }
}
```

## Engine Options

### Recommended: OpenTripPlanner

OpenTripPlanner is the best first implementation target for this project.

Why:

- built for GTFS plus walking access/egress
- supports transit itineraries, transfers, waiting, walking, and time windows
- can run locally during preprocessing
- outputs enough itinerary detail for `transit_route_summary`
- keeps all routing out of the browser

Shape:

1. Put GTFS ZIP files under ignored raw/intermediate data paths.
2. Build an OTP graph locally.
3. Run one-to-one routes from each area representative point to the workplace for a configured departure window.
4. Pick a robust statistic, such as median or 75th percentile over the window.
5. Cache route results.
6. Write static GeoJSON fields.

### Alternative: Valhalla Multimodal

Valhalla can support multimodal routing, but setup is heavier. It may be a good later option if the project also wants consistent driving, biking, walking, and transit routing from one engine.

Risk: transit support depends on correctly prepared transit tiles and may be more operationally complex than OTP for a first transit-only pass.

### Alternative: Custom Graph Approximation

A custom graph can be useful for a rough prototype:

- walking edges from area points to nearby stops
- route edges along known stop sequences
- transfer edges between nearby stops
- rough wait penalties by mode

This is faster to hack but easy to make misleading. It should only be used if schedule data is unavailable and the output is clearly labeled as approximate.

### Not Recommended For V1: Live Browser Transit APIs

Do not use browser-side routing APIs. They break static deployment, complicate secrets, and make the map slower and less reproducible.

## Implementation Steps

1. Restore or add a GTFS fetch/load script, separate from the current Apimetro stop fetcher.
2. Validate required GTFS files:
   - `stops.txt`
   - `routes.txt`
   - `trips.txt`
   - `stop_times.txt`
   - `calendar.txt` or `calendar_dates.txt`
3. Choose a representative service date and departure window.
4. Build the router input graph.
5. Add `scripts/build_transit_commute.py` or a clearly separated module called by `build_scores.py`.
6. Route each area to the configured workplace.
7. Cache raw itinerary results.
8. Collapse itineraries into the data contract fields.
9. Join results into `scores_postal_code.geojson` and `scores_colonia.geojson`.
10. Validate ranges and null handling.
11. Keep existing `score_transit` as a proximity layer.

## Validation Strategy

Use three levels of validation:

1. Data validation:
   - GTFS files exist and parse
   - stops have coordinates inside or near CDMX
   - routes have trips
   - trips have ordered stop times
   - service calendar has active service on the selected date
2. Route validation:
   - spot-check known commutes manually
   - compare nearby areas for monotonic sanity, without expecting perfect ordering
   - flag impossible values such as negative times, huge transfer counts, or zero-minute nonzero-distance trips
3. Product validation:
   - compare `score_transit` proximity against `score_work_transit`
   - identify areas near transit but still bad for the chosen workplace
   - confirm unroutable areas degrade gracefully instead of disappearing

## Known Risks

- CDMX transit data coverage may be incomplete or inconsistent across modes.
- Frequencies and calendars may not reflect real operations.
- GTFS quality can vary by agency and update cycle.
- Routing a representative point may miss local barriers around large polygons.
- Commute estimates are highly sensitive to departure time.
- Transit scoring to one workplace is not a general transit-access score.
- A router can produce precise-looking but wrong numbers if the feed is stale.

## Recommendation

Use OpenTripPlanner first, but only after a current, complete GTFS bundle is available and validated locally. Until then, keep the existing Apimetro proximity score as the production transit layer and avoid shipping a half-working transit router.

