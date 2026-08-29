# Portfolio Resume Bullet Bank — Multi-City Convenience Map

## Positioning

A profile-driven geospatial decision-support platform that turns heterogeneous open data into comparable neighborhood convenience scores. The project combines a Python data pipeline with a static React/Leaflet interface and now supports seven city profiles: CDMX, Morelia, Oslo, Bergen, Trondheim, Stavanger, and Drammen.

## Recommended Norway-facing pair

- Built a profile-driven Python geospatial pipeline that integrates administrative boundaries, transit, amenities, routing, and safety data into auditable neighborhood convenience scores across seven Mexican and Norwegian cities.
- Developed a static React/Leaflet decision-support interface with city, geography, metric, travel-mode, and weight controls, enabling users to compare areas without a live backend or paid routing dependency.

## Role-targeted variants

### Data / ML engineering

- Packaged a reproducible geospatial scoring workflow as a typed Python CLI, separating source ingestion, feature construction, validation, and enriched GeoJSON generation.
- Designed replaceable data-source adapters and city profiles so the same scoring pipeline could expand from CDMX to Morelia and five Norwegian cities without city-specific application forks.
- Combined distance, travel-time, amenity, transit, and recent crime-density signals into transparent component scores with user-adjustable weights and visible source counts.

### Backend / platform engineering

- Implemented a city-aware pipeline for fetching, validating, and publishing open geospatial data from municipal portals, OpenStreetMap, transit APIs, and offline routing infrastructure.
- Added optional Valhalla road routing with straight-line fallback, preserving deterministic static outputs when routing data or individual routes are unavailable.
- Established Python and frontend quality gates covering linting, static typing, automated tests, validation, and production builds.

### Frontend / product engineering

- Built an interactive React/Leaflet choropleth with postal-code and neighborhood views, metric selection, travel-mode controls, editable destinations, and client-side score recomputation.
- Made model inputs and limitations inspectable through score breakdowns, nearest-place details, provenance metadata, and a data-audit panel rather than presenting a single opaque ranking.
- Delivered the application as a static site with precomputed GeoJSON, reducing operational complexity while keeping exploration responsive and portable.

### Data / AI consulting

- Translated an ambiguous apartment-search question into an auditable decision model spanning commute, transit, amenities, fitness access, and safety.
- Designed the product around explainable tradeoffs: users can inspect component evidence, change priorities, and compare how travel assumptions alter the ranking.
- Evolved a Mexico City prototype into a reusable multi-city platform, demonstrating how explicit data contracts and city profiles reduce the cost of geographic expansion.

## Compact application summary

Built an open-data geospatial decision-support platform that converts heterogeneous city data into explainable, user-adjustable neighborhood rankings. The system combines a typed Python pipeline, offline routing support, validated static artifacts, and a React/Leaflet interface across Mexico and five Norwegian cities.

## Evidence anchors

Use these repository artifacts when preparing an interview walkthrough:

- `README.md` — supported cities, user-facing capabilities, data sources, and quality gates.
- `src/cdmxmap/` — importable Python package and CLI pipeline.
- `data/cities/` — city-profile expansion pattern.
- `docs/data-contract.md` — published artifact and scoring schema.
- `docs/road-routing.md` — Valhalla integration and fallback behavior.
- `frontend/` — React/Leaflet implementation and static build.

## Claim boundary

- The seven-city count and five Norwegian cities are current repository facts as of 2026-08-29; recount profiles before using the number later.
- Describe the output as **decision support** or **convenience scoring**, not an objective measure of neighborhood quality.
- Do not imply live traffic: Valhalla routes use offline free-flow travel times.
- Do not claim causal safety prediction; the safety component uses recent reported-crime density from the available source data.
- Keep source attribution visible. Open data does not mean provenance-free data.
