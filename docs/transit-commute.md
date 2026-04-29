# Transit Commute Approximation

## What Was Implemented

The score pipeline now adds a first offline estimate of public-transport commute time from each scored area to the configured workplace.

The browser still loads only static GeoJSON from `frontend/public/data`. There are no runtime routing calls, API keys, backend services, or Docker requirements.

Generated files include the new fields for both area units:

- `frontend/public/data/scores_postal_code.geojson`
- `frontend/public/data/scores_colonia.geojson`

The current transit proximity score remains separate as `score_transit`.

## Transit Data Audit

`scripts/fetch_transit.py` fetches Apimetro point GeoJSON from:

```text
https://apimetro.dev/movilidad/mapas/geojsonEstacion?sistema=METRO,MB,RTP,TROLE,CC&existe=true
```

The cached raw file inspected for this implementation is `data/raw/apimetro_transit_stations.geojson`.

Raw Apimetro properties available in the cached GeoJSON:

- `sistema`
- `nombre`
- `alcaldia_municipio`
- `jerarquia_transporte`
- `tipo`
- `tipo_entidad`
- `es_cetram`
- `nombre_cetram`
- point coordinates

Processed output from `scripts/fetch_transit.py` is `data/processed/transit_stops.csv` with:

- `id`
- `name`
- `system`
- `line`
- `hierarchy`
- `latitude`
- `longitude`
- `source`

Important limitation: the cached Apimetro GeoJSON does not include route/line identifiers, stop sequence, route geometry, schedules, headways, or directionality. The processed `line` column exists for future compatibility, but current values are blank.

Current processed stop counts:

- `METRO`: 195
- `MB`: 373
- `RTP`: 4912
- `TROLE`: 740
- `CC`: 4629

## Why This Is Not True Transit Routing

This is not schedule-aware routing. It does not know:

- which route serves each stop
- stop order
- train or bus frequency
- waiting time
- service calendars
- transfers through stations or terminals
- direction of travel
- street network walking paths
- disruptions or reliability

The estimate is useful as a robust commute-oriented approximation, not as a trip planner.

## Approximation Logic

For each area:

1. Use the area representative point as origin.
2. Find the nearest configured number of origin transit stops.
3. Find the nearest configured number of destination-side transit stops around the workplace.
4. Score every origin/destination stop pair.
5. Keep the pair with the lowest estimated total time.

Formula:

```text
origin walk time
+ straight-line stop-to-stop in-vehicle time
+ destination walk time
+ transfer/complexity penalty
+ excess-walk penalty when a stop is beyond configured max walk distance
```

Default assumptions:

- walking speed: `4.8 km/h`
- Metro speed: `28 km/h`
- Metrobús speed: `18 km/h`
- RTP and Corredor Concesionado speed: `14 km/h`
- Trolebús speed: `14 km/h`
- default transit speed: `16 km/h`
- same-line penalty: `2 min`
- same-system different/unknown-line penalty: `8 min`
- different-system penalty: `12 min`
- max origin walk distance before penalty: `1200 m`
- max destination walk distance before penalty: `1200 m`
- candidate stops per side: `5`

Because current Apimetro line fields are blank, same-system pairs are treated as `same_system_unknown_line`, not as confident same-line rides.

## Scoring

`score_work_transit` is derived from `time_work_transit_min` with a fixed monotonic scale:

- short trips are near `100`
- `30 min` is good
- `45 min` is acceptable
- `60 min` is weak
- `90+ min` is near `0`

The scoring function lives in `scripts/transit_commute/approximate.py` as `score_transit_commute_minutes`.

## Fields Added To GeoJSON

- `time_work_transit_min`
- `score_work_transit`
- `transit_commute_source`
- `transit_origin_stop_name`
- `transit_origin_system`
- `transit_origin_line`
- `transit_origin_walk_m`
- `transit_destination_stop_name`
- `transit_destination_system`
- `transit_destination_line`
- `transit_destination_walk_m`
- `transit_transfer_penalty_min`
- `transit_route_complexity`
- `transit_commute_notes`

Compatibility aliases are also written:

- `transfers_work_transit`
- `walk_to_origin_stop_m`
- `destination_walk_m`
- `transit_route_summary`

The source value for successful estimates is:

```text
apimetro_stop_pair_approximation
```

## Metadata

Per-area-unit metadata files now include:

- `generated_at`
- `transit_commute_source`
- `transit_commute.source`
- `transit_commute.candidate_stop_count`
- `transit_commute.speeds_kmh`
- `transit_commute.penalties_min`
- `transit_commute.max_walk_m`
- `transit_commute.estimated_areas`
- `transit_commute.failed_areas`
- `transit_commute.known_limitations`

## Manual Validation

Regenerate and validate:

```bash
.venv/bin/python scripts/build_scores.py --area-unit postal_code
.venv/bin/python scripts/build_scores.py --area-unit colonia
.venv/bin/python scripts/validate_processed.py
cd frontend && npm run build
```

Sample values:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path

for path in [
    Path("frontend/public/data/scores_postal_code.geojson"),
    Path("frontend/public/data/scores_colonia.geojson"),
]:
    payload = json.loads(path.read_text())
    print(path)
    for feature in payload["features"][:5]:
        props = feature["properties"]
        print(
            props["display_name"],
            props["time_work_transit_min"],
            props["score_work_transit"],
            props["transit_origin_stop_name"],
            props["transit_destination_stop_name"],
            props["transit_commute_source"],
            props["transit_commute_notes"],
            sep=" | ",
        )
PY
```

Sanity checks to perform:

- Areas close to the workplace should generally have shorter estimates.
- Areas with a very long walk to origin or destination stops should show lower scores and notes about walk penalties.
- The selected origin and destination stops should look geographically plausible on a map.
- `Transit access` and `Transit commute` should differ in the frontend when a nearby stop is not useful for the workplace direction.

## Known Limitations

- Stop-to-stop time is based on straight-line distance, not track or road geometry.
- Walking is straight-line distance, not sidewalk routing.
- Current Apimetro data has stop names and systems but no usable route/line membership.
- Transfer penalties are fixed assumptions.
- Destination-side stops are selected by proximity to the workplace, not by actual route access.
- The estimate is for one configured workplace only.
- It is not schedule-aware and should not be presented as a trip-planning result.

## Future Path To True Routing

The next serious version should replace this approximation behind the same static fields. The frontend should continue reading precomputed GeoJSON only.

Recommended path:

1. Validate a current CDMX GTFS feed for freshness and modal coverage.
2. Download or prepare an OSM extract for the CDMX routing region.
3. Use r5py/R5 or OpenTripPlanner offline during preprocessing.
4. Calculate a travel-time matrix from all area representative points to the workplace for a selected service date and departure window.
5. Cache results by area unit, area ID, workplace coordinate, service date, departure window, feed version, and router version.
6. Emit the same GeoJSON fields, replacing `transit_commute_source` with the true router source.

