# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it is
published.

## [Unreleased]

### Added

- Two Mexican metro areas, **Monterrey** (Nuevo León) and **Guadalajara**
  (Jalisco), viewable via the city switcher or `?city=monterrey` /
  `?city=guadalajara`. Both have postal-code and colonia geographies, crime
  scoring, per-system transit toggles, and published road routing; they are the
  first cities whose published maps are routed.
  - **Monterrey**: the 12 central municipalities of the Zona Metropolitana de
    Monterrey 2020 (SEDATU/CONAPO/INEGI *Metrópolis de México 2020*), 658 postal
    codes and 4,698 named colonias. Transit from Nuevo León open data (CC-BY):
    Metrorrey (41 station-lines on Lines 1–3), TransMetro BRT (57 stations:
    Ecovía 40, Av. México 17, named from OSM stations), TransMetro (1,382 stops)
    and Rutas urbanas (8,170 IMA stops with route numbers). Store toggles H-E-B,
    Soriana, Walmart, Bodega Aurrerá, S-Mart, Sam's Club and Costco (368
    classified points); 1,483 DENUE gyms. Safety uses the new `city_statistics`
    crime mode: SESNSP municipal incidence (fuero común) for 2025-11-01 to
    2026-10-31, "robbery and violent crime" per 100k residents (Censo 2020),
    ranked min–max across the 12 municipalities, weight 10%. Default workplace
    CP 66260 (Valle Oriente, San Pedro Garza García).
  - **Guadalajara**: all 7 municipalities of the Zona Metropolitana de
    Guadalajara 2020, 401 postal codes and 2,648 named colonias. Transit from the
    SETRAN Jalisco GTFS feed (Mobility Database `mdb-3632`, version of
    2026-11-17): Mi Tren (56 station-lines, L1–L4), Mi Macro (84, L5–L7),
    Alimentadoras (1,806), Mi Transporte Tren Ligero (675) and Mi Transporte
    (11,867). Store toggles Bodega Aurrerá, Soriana, Walmart, Chedraui, Sam's
    Club, La Comer / City Market / Fresko and Costco (173 points); 1,414 DENUE
    gyms. Safety is incident density from IIEG Jalisco's Región Centro Fiscalía
    microdata (16 high-impact crime types, 2017-01 to 2025-08), latest 12 months,
    counted over each area plus a 250 m buffer; aggregates only. Default
    workplace CP 45116 (Andares / Puerta de Hierro, Zapopan).
  - Shared infrastructure:
    - `sources/mx_common.py`: atomic, validated downloads; state-wide caches of
      the open-mexico SEPOMEX polygons, INEGI municipalities with Censo 2020
      population (wscatgeo `mgem`) and INEGI DCAH 2025 colonias; largest-overlap
      assignment, Spanish title case and the unnamed-colonia filter.
    - `fetch_mx_postal_codes` gains a municipality mode (profile `mx_area`):
      SEPOMEX polygons are assigned to INEGI municipalities by largest overlap
      and labelled with INEGI colonia names (`colonias_label`, e.g. "Colonia del
      Valle, Jardines del Valle +6"), not the SEPOMEX catalog, whose terms forbid
      redistribution. Morelia's range mode is unchanged.
    - `fetch_mx_colonias`: INEGI DCAH 2025 colonias of the member
      municipalities, unnamed placeholders dropped (411 in Monterrey, 91 in
      Guadalajara).
    - `fetch_nl_transit` (Nuevo León CKAN GeoPackages) and `fetch_gtfs_transit`
      (a profile-driven GTFS reader with ordered route rules). Stops carry line
      ids; a stop served by several routes lists them joined with `|`.
    - `fetch_supermarkets` classifier v2 (profile `supermarket_classifier`):
      `brand:wikidata` > `brand` > `name`, never `operator`; accent-insensitive
      tokens matched at word boundaries, with per-family excludes; same-family
      points within 150 m merged; `pool_only` families count toward the overall
      supermarket score without a toggle. Live Overpass replies whose OSM data is
      more than 30 days old are rejected.
    - `fetch_denue_gyms`: gyms from INEGI DENUE (May 2026 release, SCIAN 713943
      and 713944); OSM has only about 90 per metro.
    - `fetch_sesnsp_crime_statistics` (writes `crime_statistics.csv`, one row
      per municipality of the state) and `fetch_iieg_crime` (writes
      `crime_points.csv`; prints counts only, never a row).
    - Engine: the `city_statistics` crime mode (per-feature
      `crime_statistics_*`, `crime_scope_*`, `crime_rate_per_100k_12m` and
      `crime_total_rate_per_100k_12m`, no per-area incident counts, a hard error
      for an area with no matching unit, and a `units` list in the metadata
      `crime` block); `crime_source.density_buffer_m` for incident-mode profile
      cities (per-feature `crime_buffer_m`); opt-in transit-commute keys
      `has_line_data`, `system_speeds_kmh`, `priority_candidate_systems` and
      `priority_candidate_stop_count`, with `|`-joined lines counting as the same
      line when they share a route; opt-in `road_routing.search_filter`,
      `osm_md5` and `osm_date`.
    - Road routing for both cities from one national Mexico tileset (Geofabrik
      `mexico-261124.osm.pbf`) with `search_filter: {"min_road_class":
      "residential"}`: Valhalla free-flow work and amenity times for both
      geographies, and dynamic-workplace postal-code matrices (Monterrey 3 ×
      865,928 B, Guadalajara 3 × 321,602 B). Colonias have no matrix (Monterrey's
      would be 3 × 44 MB).
    - Validation: statistics-mode features must carry the statistics fields and
      must not carry incident counts; every transit system a profile city
      declares must be the nearest stop of at least one feature.
    - Frontend: two `CityConfig` entries with their own themes (Monterrey: Faro
      del Comercio orange with a Cerro de la Silla slate counter; Guadalajara:
      Catedral tower-tile ochre with a Talavera cobalt counter; WCAG AA asserted
      in a unit test), transit-system toggles for any city that declares them,
      the postal-area label and municipality in the area header, a
      statistics-mode safety panel (`lib/safety.ts`), a named crime window for
      Guadalajara, and INEGI DENUE as the gym source label.
    - Parts publishing (`output/parts.py`): an area unit with
      `public_part_max_bytes` in its profile entry is published to the frontend
      as `scores_<unit>.part-NN.geojson` FeatureCollections, each within that
      budget, listed in order (with byte size, SHA-256 and feature count) by
      `scores_<unit>_index.json`; the processed copy stays one file. Both
      colonia layers use 9,000,000 bytes (Monterrey 4 parts, Guadalajara 2),
      under the 10 MB pre-commit large-file limit. `cdmxmap validate --city`
      checks the parts against the index and the processed file;
      `lib/areaData.ts` fetches the parts in parallel and joins them; a test
      keeps every file under `frontend/public/data/` within the pre-commit
      limit, which CI does not otherwise run.
    - Tests: CDMX goldens for the metadata, postal-code properties and property
      order (`tests/integration/test_cdmx_goldens.py`), a statistics-mode
      fixture city (`tests/fixtures/fixture_city_stats/`), and offline unit
      tests for each new fetcher (network mocked).
- Per-city colour themes for the map page chrome (side panel, cards, buttons,
  accents), replacing the shared beige and teal: rosa mexicano for CDMX, cantera
  rosa for Morelia, fjord indigo for Oslo, Bryggen red for Bergen, verdigris
  green for Trondheim, North Sea petrol for Stavanger, and river steel-blue for
  Drammen. Each theme is a `theme` block on the city's `CityConfig`, applied as
  CSS custom properties; the score colour ramp stays shared across cities.
- Two more cities: **Drammen** (Norway) and **Morelia** (Michoacán, Mexico), each
  a full Oslo-equivalent map viewable via the city switcher or `?city=<id>`.
  - **Drammen** reuses the Norway-generic path end to end: a
    `data/cities/drammen/{city.json,places.json}` profile (Kartverket kommune
    `3301`, 46 postal areas, OSM transit + grocery brands, no crime scoring) and a
    `norwegianCity()` frontend entry — no new code.
  - **Morelia** is the first profile-driven **Mexican** city (CDMX stays on its
    in-code constants). Its 154 postal-code polygons (CP `58000`–`58399`) come
    from the national [open-mexico](https://github.com/open-mexico/mexico-geojson)
    SEPOMEX GeoJSON via a new `fetch_mx_postal_codes` fetcher (state file cached
    once and written atomically, then trimmed by `postal_code_range` + bbox,
    mirroring `fetch_no_postal_codes`). Transit, groceries (Bodega Aurrerá,
    Walmart, Soriana, Chedraui), and gyms come from OpenStreetMap; safety is not
    scored. A dedicated frontend `CityConfig` carries its Mexican `CP ` postal
    formatting and local grocery brands.
  - The Oslo/Norway OSM transit fetcher is generalized to a country-neutral
    `fetch_osm_transit`; `fetch_no_transit` remains as a thin backward-compatible
    alias so the Norwegian profiles are byte-unchanged, and Morelia reuses the
    generic module.
- Three more Norwegian cities alongside Oslo — **Bergen**, **Trondheim**, and
  **Stavanger** — each a full Oslo-equivalent map:
  - Complete `data/cities/<id>/city.json` + `places.json` profiles (Kartverket
    postal areas by kommune number, OSM transit + grocery brands, no crime
    scoring). Stavanger's earlier skeleton profile is promoted to a full one.
  - The Oslo-only postal/transit fetchers are generalized into Norway-generic,
    profile-driven `fetch_no_postal_codes` / `fetch_no_transit` (a new
    `municipality_code` profile field selects the kommune); Oslo now uses them
    too. The national postal GML is cached per city between runs.
  - Generated static assets under `frontend/public/data/<id>/` (Bergen 145,
    Trondheim 77, Stavanger 59 postal areas), each validated against the data
    contract.
  - Frontend: a `norwegianCity()` config factory + `CityConfig` type replace the
    duplicated Oslo block; the city switcher and `?city=` selection are
    generalized to every registered city (CDMX, Oslo, Bergen, Trondheim,
    Stavanger).
  - The transit-commute provenance is now fully config-driven — per-feature
    `transit_commute_source` + `transit_commute_notes`, and the metadata
    `engine` / limitations / notes — via `transit_commute.source`,
    `stop_source_label`, and `engine_label`. The Norwegian cities emit
    `osm_stop_pair_approximation` / "OpenStreetMap" natively (Oslo included, so it
    is now reproducible from code rather than a post-hoc rename); CDMX output is
    byte-unchanged.
  - `fetch_no_postal_codes` caches the ~26 MB national Kartverket GML once at a
    shared path and writes it atomically (parse-validated), so all four Norwegian
    cities share one download and a corrupt/interrupted fetch cannot poison re-runs.
- Offline road routing (opt-in) replacing the straight-line travel-time
  placeholder for work and amenity (supermarket/Costco/Walmart/gym) times:
  - New `src/cdmxmap/routing/` package — a `Router` Protocol, an in-process
    **Valhalla** adapter (`pyvalhalla`, no Docker/Java), a keyed `RoutingCache`,
    and the area-to-area matrix codec/builder. OSRM documented as a drop-in
    alternative; decision recorded in `docs/road-routing.md`.
  - `score_areas(router=...)` routes work + amenity candidates with per-row
    straight-line fallback; routed distance stored separately (`*_routed_m`); per
    feature scalar source labels (`valhalla_free_flow` vs
    `fallback_straight_line_estimate`). Default (no router) output is unchanged.
  - CLI: `--travel-router none|valhalla` on `score`/`run`, plus `build-matrix` and
    `build-tiles`. Optional `routing` dependency extra (`pyvalhalla`).
  - Dynamic workplace: precomputed area-to-area routed matrix served as a
    destination-major `uint16` binary + JSON index; the frontend Range-fetches one
    column and distinguishes routed vs estimate with a UI badge, falling back to a
    labeled estimate when the matrix is absent.
  - Metadata gains a `road_routing` block (engine/version, profiles, OSM source,
    routed/fallback counts, cache stats); contract updated in
    `docs/data-contract.md`; `docs/travel-time-roadmap.md` marked implemented.
- Config validation: `src/cdmxmap/schema.py` pydantic models validate `city.json`
  and `places.json` on load, failing fast with a `ConfigError`.
- Test suites completed: integration + golden + e2e over a synthetic fixture city
  (`tests/fixtures/fixture_city/`), runnable fully offline. `load_point_datasets`,
  `build_area`, and `run_pipeline` gained optional `data_dir`/`public_dir`/
  `places_config` parameters (defaults unchanged) so tests can drive a fixture
  build. **All 19 engineering-standards sections are now compliant.**
- `pyproject.toml` + `uv.lock`: Python project migrated to `uv` with runtime,
  dev, and optional `transit` dependency groups; Python pinned to `>=3.11,<3.13`.
- Quality-gate configuration: `ruff`, `mypy`, and `pytest` settings in
  `pyproject.toml`; Prettier for the frontend; `.pre-commit-config.yaml`.
- Documentation: `docs/engineering-standards.md` (project-specific A–S),
  `docs/data-contract.md`, `docs/architecture.md`, `docs/testing.md`,
  `docs/troubleshooting.md`; plus `CONTRIBUTING.md`, `.env.example`, this changelog.
- Frontend logic modules extracted from `App.tsx` (`types`, `constants`,
  `lib/{format,normalize,search,score-math,work,scoring}`).
- Tests: Vitest suite (46 tests) for the frontend logic; pytest suite (26 tests)
  for the pipeline helpers, the output-validator data contract, and scoring math.
- CI: `.github/workflows/ci.yml` runs lint/type-check/test/build for both stacks
  (Python matrix 3.11/3.12) on PRs and pushes to `master`.
- Pipeline resilience: domain exceptions (`errors.py`); structured logging
  (`logging_config.py`, `--log-level` / `CDMXMAP_LOG_LEVEL`); per-run artifacts
  under `runs/<run_id>/` (`run.log`, `manifest.json`, `errors.json`); atomic
  GeoJSON/metadata writes; per-source failure isolation with `--fail-fast`;
  `--resume` (skip already-fetched sources); meaningful exit codes; and `Ctrl+C`
  interruption that marks the in-progress entry and prints a resume hint.
- Pipeline refactored into the importable `src/cdmxmap/` package
  (`sources/`, `scoring/{areas,points,metrics,crime,transit,engine}`, `output/`,
  `pipeline`, `models`, `config`) with a unified **`cdmxmap` CLI**
  (`fetch`/`score`/`validate`/`run`). Verified byte-identical to the previous
  output on real CDMX data.

### Changed

- The transit and safety notes in the score metadata are generated from each
  profile city's own systems and crime source (for example "Transit score is 70%
  nearest Metrorrey / TransMetro BRT and 30% nearest TransMetro / Rutas
  urbanas."), and a city without safety scoring says "Safety is not scored.",
  instead of every city carrying CDMX's Metro/FGJ wording. CDMX keeps its exact
  strings. Morelia and the Norwegian cities pick this up the next time they are
  regenerated; their committed assets were not regenerated.
- The frontend loads the routing matrix of the selected city: `loadMatrixIndex`
  takes the index URL (cached per URL) and resolves the binaries next to it. It
  previously always loaded CDMX's index. `cityDataAssets(id, { colonia: true })`
  gives a city real colonia paths, the transit-toggle helpers take the city's
  own options (CDMX's by default), and the search box is labelled "Search
  areas". CDMX renders as before.
- On a routed build the metadata's `amenity_travel_time.source` names the
  router (`valhalla_free_flow`) and keeps the straight-line label as
  `fallback_source`, as `travel_time` already did.
- The transit-commute metadata records `has_line_data`, `priority_candidates`
  and `speeds_kmh.systems` when a city sets them; default metadata is unchanged.
- Frontend restyled as "a cartographer's sheet: each city in its own ink",
  following the portfolio's design language. Scoring, data contracts and
  `?city=` URLs are unchanged.
  - Sidebar: the nested white cards are gone. Sections are separated by hairline
    rules with numbered monospaced labels; option groups are single segmented
    controls; the data audit and raw distances are ruled spec lists; "Use
    selected area", "Reset default" and "Copy" are links, leaving "Apply" as the
    one primary button.
  - Type: a serif for the title, city and area names, the sans for reading, and
    a monospace with tabular figures for labels, counts, scores and units. Score
    columns print one fixed decimal (`scoreFigure`) so they align; the copied
    report and tooltips keep the compact `scoreText`.
  - Map furniture: a metric Leaflet scale bar, a neatline frame, a pointer/centre
    coordinate and zoom readout, and a legend drawn to scale (each class as wide
    as its score range, ticks at the class breaks, a pointer at the selected
    area's score). The top list is a numbered index with the map colour beside
    each score; below 1180px it follows the map instead of covering it.
  - A locator inset in the title block draws the city's scored areas as a mesh
    and marks the selected area (`lib/locator.ts`).
  - The OpenStreetMap base layer is desaturated on the city's paper colour so
    the score ramp is the only saturated colour on the map. The ramp itself is
    unchanged.
  - Each `CityTheme` gains a `counter` ink of the opposite temperature to its
    accent (for example brick against Oslo's indigo, jacaranda against CDMX's
    rosa), used for markers and section numerals. All text inks pass WCAG AA on
    their surfaces.
  - Hover and selection transitions on areas, score gauges and the legend
    pointer, disabled under `prefers-reduced-motion`.

- The standalone `scripts/build_scores.py`, `run_city.py`,
  `validate_processed.py`, `common.py`, the `fetch_*` scripts, and the
  `transit_commute` package moved into `src/cdmxmap/`; use the `cdmxmap` CLI.

- Frontend gains `typecheck`, `format`, and `test` npm scripts; full TypeScript
  `strict` mode enabled.
- `deploy.yml` now runs the frontend quality gate (lint/type-check/test) before
  building, so a broken build is never published.
- README quickstart switched to `uv`; manual test checklist updated.

### Fixed

- `fetch_supermarkets.infer_brand` broke ties between equal-length brand
  tokens in set order, so the inferred brand depended on `PYTHONHASHSEED`. Ties
  now break alphabetically (sort key `(-len(token), token)`); results that did
  not tie are unchanged.
- `retry_overpass` waited only 3 s between attempts. It now backs off 30 s per
  attempt (longer when Overpass sends `Retry-After`), fails at once on a client
  error other than HTTP 429, and treats a 200 reply whose `remark` reports an
  Overpass runtime error (a partial result) as a failure. Rotation across
  Overpass mirrors, with the 30-day staleness check, is opt-in and used only by
  the Monterrey and Guadalajara fetchers.
- `build-matrix` now passes the city's metric CRS to the representative-point
  helper, so a matrix's points match the scored output outside UTM 14N, and
  records `osm_sha`/`osm_date` in the matrix index when `places.json` declares
  them (they were always null).

[Unreleased]: https://github.com/ignacio-ireta/cdmx-convenience-map/commits/master
