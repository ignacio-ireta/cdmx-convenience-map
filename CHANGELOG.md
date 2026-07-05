# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it is
published.

## [Unreleased]

### Added

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

- The standalone `scripts/build_scores.py`, `run_city.py`,
  `validate_processed.py`, `common.py`, the `fetch_*` scripts, and the
  `transit_commute` package moved into `src/cdmxmap/`; use the `cdmxmap` CLI.

- Frontend gains `typecheck`, `format`, and `test` npm scripts; full TypeScript
  `strict` mode enabled.
- `deploy.yml` now runs the frontend quality gate (lint/type-check/test) before
  building, so a broken build is never published.
- README quickstart switched to `uv`; manual test checklist updated.

[Unreleased]: https://github.com/ignacio-ireta/cdmx-convenience-map/commits/master
