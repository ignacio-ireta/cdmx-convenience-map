# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it is
published.

## [Unreleased]

### Added

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
