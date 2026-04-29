# Transit Routing Roadmap

## Recommendation

The preferred next routing engine is `r5py`/R5.

Why it fits this project:

- It is Python-friendly.
- It works naturally with GeoPandas-style origin and destination tables.
- It is designed for public-transport travel-time matrices.
- It can use OpenStreetMap extracts plus GTFS feeds.
- It can run during preprocessing and emit static GeoJSON for GitHub Pages.

Relevant docs:

- r5py travel-time matrices: https://r5py.readthedocs.io/stable/user-guide/user-manual/travel-time-matrices.html
- OpenTripPlanner: https://www.opentripplanner.org/

OpenTripPlanner is the main alternative if the project wants an API-server-style router for local preprocessing or a richer itinerary object model.

## Why Not A Browser Router

The app is deployed as static GitHub Pages content. Runtime transit routing from the browser would add one or more of:

- live API calls
- secret key handling
- latency and quota failures
- non-reproducible scores
- a backend dependency

The correct architecture is still offline preprocessing plus static generated GeoJSON.

## Required Inputs

A real transit router needs more than Apimetro stop points:

- OSM street network extract for walking access and egress
- GTFS `stops.txt`
- GTFS `routes.txt`
- GTFS `trips.txt`
- GTFS `stop_times.txt`
- GTFS `calendar.txt` or `calendar_dates.txt`
- a service date covered by the feed
- a departure time or time window
- configured workplace coordinates
- area representative points

CDMX GTFS exists, but feed freshness and modal coverage must be validated before relying on it. In particular, confirm coverage for Metro, Metrobús, RTP, Trolebús, and concessioned corridors before replacing the approximation.

## r5py/R5 Implementation Shape

1. Add ignored local inputs under `data/raw` or `data/intermediate`, such as:
   - `cdmx.osm.pbf`
   - one or more GTFS ZIP files
2. Validate GTFS files before routing.
3. Build a transport network once per feed/network version.
4. Create one origin point per scored area.
5. Create one destination point for the configured workplace.
6. Compute a transit travel-time matrix for a chosen weekday commute window.
7. Use a robust statistic, such as median or 75th percentile across the window.
8. Cache travel times and route diagnostics.
9. Join results into `scores_postal_code.geojson` and `scores_colonia.geojson`.
10. Keep `score_transit` as transit access and update `score_work_transit` as schedule-aware commute.

Suggested cache key:

```text
r5py:{router_version}:{osm_hash}:{gtfs_hash}:{area_unit}:{area_id}:{workplace_hash}:{service_date}:{departure_window}
```

Suggested metadata:

```json
{
  "transit_commute": {
    "source": "r5py",
    "service_date": "YYYY-MM-DD",
    "departure_window": "08:00-10:00",
    "statistic": "median",
    "routed_areas": 0,
    "failed_areas": 0,
    "osm_extract": "cdmx.osm.pbf",
    "gtfs_feeds": ["feed.zip"]
  }
}
```

## OpenTripPlanner Alternative

OpenTripPlanner is appropriate if the project wants a local service that returns itinerary details, including legs, transfer points, walk segments, and route names.

Tradeoffs:

- Strong itinerary model.
- Natural GTFS plus OSM architecture.
- More operational setup than a Python matrix workflow.
- Usually shaped as a server process, even when used only during preprocessing.

This is a good option if future UI work needs detailed route summaries beyond a single travel-time score.

## Validation Before Replacing The Approximation

Data validation:

- GTFS required files exist and parse.
- Stop coordinates are in or near CDMX.
- Routes have trips.
- Trips have ordered stop times.
- Service calendars cover the selected date.
- Agencies and modes cover the expected public-transport systems.

Routing validation:

- At least 95% of areas return a finite route, unless coverage gaps are documented.
- No negative or zero-time long-distance routes.
- Manual spot checks for known commutes.
- Compare nearby areas for directional sanity, without expecting perfect monotonicity.
- Flag outliers over a maximum expected commute threshold.

Product validation:

- Frontend still builds as static assets.
- `Transit access` remains a proximity score.
- `Transit commute` clearly indicates router source, service date, and departure window.
- Missing routes degrade to null fields and a populated source/failure note.

## Recommended Next Task

Add a small GTFS validation command before integrating a router. It should read candidate CDMX feeds, report agencies, route types, service date coverage, stop counts, route counts, trip counts, and whether each configured mode appears covered.

