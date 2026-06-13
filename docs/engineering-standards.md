# Engineering Standards — CDMX Convenience Map

These are the engineering standards for **this** project: a **dual-stack** system
made of a Python geo data pipeline (`src/cdmxmap/`) that fetches open-data
sources for a city, scores every area unit (postal code / colonia) on
convenience metrics, and writes `scores_*.geojson` + `score_metadata_*.json`;
and a static **React + TypeScript + Leaflet (Vite)** frontend (`frontend/`) that
visualizes the result on GitHub Pages.

The lettered sections mirror a generic standards template so the two can be
compared, but every rule below is specific to this repository. Each section ends
with a **Status** line: `✅ compliant`, `🟡 in progress`, or `⬜ planned`, with a
pointer to where it lives. Day-to-day workflow is in
[`CONTRIBUTING.md`](../CONTRIBUTING.md).

---

## A. Product definition and scope

The pipeline ingests a **city profile** (`data/cities/<city>/city.json`) plus
shared config (`data/config/places.json`), fetches the city's open-data sources,
and produces one scored GeoJSON per **area unit** (`postal_code`, `colonia`)
along with a metadata/provenance file. The frontend renders these as an
interactive choropleth; no runtime backend exists.

- **Success criteria:** given a valid city profile, produce a scored GeoJSON for
  every requested area unit in which every feature carries the full property
  contract (§G) and at least one feature has a non-null transit-commute estimate,
  plus a run report (manifest + metadata).
- **Failure criteria:** an unavailable or malformed source (Overpass, Apimetro,
  CDMX/FGJ open data) is **skipped or degraded to a committed seed with a
  structured warning** — never a silent crash and never a partially written
  output file. A failed city run reports which source failed and why.

Out of scope today: live routing in the browser, non-CDMX live source adapters
(only OSM fetchers are city-aware), OCR/scanned inputs.

**Status:** ✅ scope realized; 🟡 structured per-run report formalized in §I/§J.

## B. Repository structure

```
cdmx-convenience-map/
  pyproject.toml  uv.lock  requirements.txt   # Python project (uv)
  .pre-commit-config.yaml  .env.example
  README.md  CHANGELOG.md  CONTRIBUTING.md  LICENSE
  src/cdmxmap/            # importable pipeline package (src-layout)
    cli.py config.py logging_config.py errors.py models.py
    sources/  scoring/  output/  pipeline/
  tests/{unit,integration,e2e,golden,fixtures}/
  frontend/              # React + TS + Leaflet + Vite app
  data/{cities,config,raw,seeds,archive,processed}/
  docs/                  # this file + architecture, data-contract, testing, …
  scripts/              # thin CLI shims + experiments/ + archive/
  .github/workflows/    # ci.yml, deploy.yml
```

Pipeline code is importable under `src/` (src-layout per the Python packaging
guidance); tests live outside the package; the frontend is self-contained under
`frontend/`. Experimental spikes stay in `scripts/experiments/` and legacy code
in `scripts/archive/`, explicitly fenced off from the quality gates.

**Status:** 🟡 `src/cdmxmap/` package created; pipeline moves in during Phase 2.

## C. Version control

- Git from day one; `master` protected and kept green.
- **Conventional Commits** with a project scope: `scoring`, `sources`,
  `transit`, `cli`, `frontend`, `data`, `docs`, `ci`, `chore`.
  - Good: `feat(scoring): add inverse-density gym score`,
    `fix(frontend): keep weight sliders from breaking the map`,
    `data(crime): refresh FGJ snapshot to 2024-09`.
  - Bad: `updates`, `final version`, `stuff`, `fix`.
- Feature branch per change; PR required; CI green before merge; review for
  non-trivial changes.
- `CHANGELOG.md` maintained under `[Unreleased]`; tags/releases used for stable
  versions.
- **Secrets never committed.** Generated data is gitignored. **Large fixtures:**
  the built score GeoJSON (6–9 MB) is intentionally versioned so GitHub Pages can
  serve it; this is a documented exception (see §Q) — raw inputs are not.

**Status:** ✅ conventions documented in CONTRIBUTING.md; ⬜ branch protection to
be enabled once CI lands (§N).

## D. Dependency and environment management

Dependencies are declared, isolated, reproducible, and separated by purpose.

- **Python** is managed by **uv** with `pyproject.toml` + committed `uv.lock`.
  - Runtime: `geopandas, numpy, pandas, pyogrio, pyproj, shapely, requests`
    (pinned for output determinism) + `typer, rich, pydantic`.
  - Dev group: `pytest, pytest-cov, ruff, mypy, pre-commit`.
  - Optional extra `transit`: `r5py` (schedule-aware routing; **needs Java 21+**).
  - Python pinned `>=3.11,<3.13` (numpy 1.26.x predates 3.13; raising the cap is a
    tracked follow-up). `requirements.txt` is generated from the lock for non-uv
    users.
- **Frontend** deps live in `frontend/package.json` with a committed
  `package-lock.json`; installed with `npm ci`.
- **OS / native deps:** the geospatial stack ships wheels (GDAL bundled in
  pyogrio), so no system GDAL is required on macOS/Linux; the optional `transit`
  extra needs a JDK. Documented in `docs/troubleshooting.md`.

Setup: `uv sync` (+ `uv sync --extra transit`), and `npm install` in `frontend/`.

**Status:** ✅ implemented in Phase 0.

## E. Configuration

Config is separated from code; environment-varying values are overridable.

| Item | Source |
|---|---|
| City profile (bbox, CRS, source URLs, amenity brands) | `data/cities/<city>/city.json` |
| Workplace, travel speeds/detour factors, amenity time settings | `data/config/places.json` |
| Input / output paths, area unit, transit router | CLI flags |
| Log level | `--log-level` / `CDMXMAP_LOG_LEVEL` |
| Resume / fail-fast / force-refetch | explicit flags |
| Frontend data asset paths & geographies | `DATA_ASSETS` / `GEOGRAPHIES` constants + Vite `base` |

City profiles and `places.json` are validated with **pydantic** models
(`src/cdmxmap/models.py`); a malformed profile fails fast with a `ConfigError`,
not a `KeyError` deep in scoring.

CLI shape:

```bash
cdmxmap run   --city cdmx --area-unit postal_code
cdmxmap fetch --city cdmx --force
cdmxmap score --area-unit colonia --transit-router approximate
cdmxmap validate
cdmxmap run   --city cdmx --resume --fail-fast --log-level debug
```

**Status:** 🟡 file config + argparse flags exist today; pydantic validation and
the unified `cdmxmap` CLI land in Phase 2, resume/fail-fast in Phase 3.

## F. Architecture and modularity

```
city profile + config
  → sources (fetch & normalize each open-data source)
  → typed intermediate model (areas + point datasets)
  → scoring engine (distance / density / travel-time / crime / transit)
  → output writer (GeoJSON + metadata + manifest)
  → run state / reporting
```

The senior move the original template calls out — *don't let each extractor
invent its own output* — maps directly: **no fetcher or scorer writes GeoJSON
itself.** Sources normalize to typed structures; the scoring engine consumes
them; a single writer renders the output contract. The intermediate model
already exists as frozen dataclasses and is preserved verbatim:

```python
AreaConfig(area_unit, area_id_field, …)
PointDatasets(transit, supermarkets, gyms, crime, workplaces, …)
NearestResult / AmenityRouteResult
ScoredAreaResult(...)   # one row of the output contract
```

Keeping fetch / score / render separable means a crime-aggregation bug can't be
a Markdown/GeoJSON-rendering bug, each block keeps source provenance (§S), and a
future JSON or vector-tile writer is an additive change.

**Status:** 🟡 separation exists logically inside `build_scores.py`; Phase 2
splits it into `sources/`, `scoring/`, `output/`, `pipeline/`.

## G. Input/output contracts

Per-source scope and the exact output schema are specified in
[`docs/data-contract.md`](data-contract.md). Summary:

| Source | In scope | Notes / out of scope |
|---|---|---|
| Postal codes (CDMX open data) | polygons, `d_cp` / postal_code | — |
| Colonias (Opendatasoft / IECM) | polygons, name, alcaldía | best-effort name normalization |
| Transit (Apimetro) | Metro, Metrobús, RTP, Trolebús, Corredor points | not schedule-aware unless `r5py` extra |
| Supermarkets (OSM Overpass) | Costco, Walmart points | brand list from city profile; seed fallback |
| Gyms (OSM Overpass) | fitness centres / gyms | unnamed OSM features stay "Unnamed gym" |
| Crime (FGJ victims CSV) | latest 12 months, aggregated by area | **aggregate-only**; raw rows never emitted/logged |

The output is a GeoJSON `FeatureCollection` whose every feature carries a
**stable property contract**: generic identity (`area_unit, area_id, area_name,
display_name`, `postal_code` for postal areas), 8 `dist_*_m` fields, 7 `time_*_min`
fields, 11 `score_*` fields (each `0–100`), the 15-field `transit_*` /
`*_transit_*` commute block, and 3 `crime_*` aggregates. Distances are `≥ 0`,
scores are clamped `0–100`, optional fields are explicit `null`. The authoritative
field list is enforced by `cdmxmap validate` (today `scripts/validate_processed.py`).

A sibling `score_metadata_<unit>.json` records counts, coverage, source
provenance, and the transit router engine. **Output is deterministic** for fixed
inputs and a fixed version, except embedded timestamps.

**Status:** ✅ contract exists & is validated; 🟡 documented in `data-contract.md`
(Phase 1) and provenance enriched in §S.

## H. Error handling

- **Domain exceptions** in `src/cdmxmap/errors.py`: `ConfigError`,
  `SourceUnavailableError`, `FetchError`, `ScoringError`, `ValidationError`
  (replacing today's broad `except Exception`).
- **Partial failure isolation:** one failed source does not kill a city run
  unless `--fail-fast`. OSM sources already degrade to committed seeds
  (`data/seeds/*.csv`); the same pattern is generalized and reported.
- Actionable messages; full stack traces only at `--log-level debug`.
- **Meaningful exit codes:** `0` success, `1` partial (some sources failed but an
  output was produced), `2` config/usage error, `3` no output produced.
- A per-run error report (`runs/<id>/errors.json`) lists each failed source/area
  with a machine-readable reason.

Target console summary:

```
SUCCESS  postal_code: 1215 areas scored
WARNING  supermarkets degraded to seed (Overpass timeout)
FAILED   crime: download 503 from datos.cdmx.gob.mx
```

**Status:** 🟡 seed fallback exists; typed exceptions, fail-fast, exit codes,
error report land in Phase 3.

## I. Logging and observability

- Replace ~55 `print()` calls with stdlib `logging` via
  `src/cdmxmap/logging_config.py`; **rich** progress bars for CLI UX.
- Levels: DEBUG (internals), INFO (pipeline milestones), WARNING (recoverable /
  degraded source), ERROR (failed source/run), CRITICAL (system failure).
- **Persistent observability** beats a pretty progress bar: each run writes
  `runs/<run_id>/{run.log, manifest.json, errors.json}`.
- **Privacy:** never log raw crime/victim rows or full PII coordinates at INFO;
  source URLs are fine, individual records are not (§P).

Expected lines:

```
INFO  run start run_id=20260613-… city=cdmx area_unit=postal_code
INFO  source transit ok stops=412
WARNING source supermarkets degraded reason=overpass_timeout fallback=seed
INFO  run done success_sources=5 degraded=1 failed=0 areas=1215 duration=00:02:11
```

**Status:** ⬜ Phase 3.

## J. Resumability and idempotency

A `runs/<id>/manifest.json` records, per source and per area unit, a `sha256`/
`mtime`, status (`pending|running|success|warning|failed|skipped|interrupted`),
and output path. From it the pipeline can:

- **resume after a crash** (`--resume`),
- **skip unchanged** successful sources, **reprocess changed** ones (by hash),
- write outputs **atomically** (temp file + `os.replace`) so a crash never leaves
  a half-written `scores_*.geojson`,
- guarantee **deterministic naming** so re-runs overwrite cleanly rather than
  accumulating garbage.

Running the same command twice produces the same outputs and no duplicates.

**Status:** ⬜ Phase 3 (atomic writes + manifest + `--resume`).

## K. Testing strategy

- **Unit:** score math (`metrics.py`), `normalize_postal_code`, path/output
  mapping, pydantic config parsing, `nearest`, error classification.
- **Integration:** fixture point datasets → `score_areas` → assert the property
  contract; `score` → `validate`.
- **E2e:** `cdmxmap run --city fixture` over a tiny 2–3 area fixture city →
  outputs + manifest + error report exist; exit code `0`.
- **Golden:** committed expected `scores.geojson` / metadata for the fixture city;
  guards against accidental output-format regressions. Regeneration documented.
- **Property/fuzz (later):** weird filenames, empty/`NaN` columns, huge tables,
  Spanish/accented names, broken ZIP/GeoJSON, mixed CRS.
- **Frontend:** Vitest unit tests for the pure scoring/normalize/search helpers
  and component smoke tests (mocked fetch).

**Status:** 🟡 Frontend Vitest (46 tests over the extracted logic) and Python
pytest (26 tests: common helpers, the validator's data-contract invariants,
scoring-math property tests) have landed. Integration / e2e / golden suites
remain (they depend on the Phase 2 fixture city).

## L. Testing documentation

[`docs/testing.md`](testing.md) explains how to run all tests, only unit /
integration / e2e (`uv run pytest tests/unit`, `-m "not slow"`), how fixtures are
organized, **how to regenerate golden files**, what external deps are needed
(JDK for `transit`), what runs in CI, and what is intentionally skipped locally
(network fetchers, r5py).

**Status:** ✅ `docs/testing.md` written; expanded as the suites grow.

## M. Code quality gates

| Gate | Python | Frontend |
|---|---|---|
| Format | `ruff format --check .` | `prettier --check .` |
| Lint | `ruff check .` | `eslint .` |
| Types | `mypy` (`src/cdmxmap`) | `tsc -b` (strict) |
| Tests | `pytest --cov=cdmxmap` | `vitest` |
| Deps/security | `pip-audit` / Dependabot | `npm audit` / Dependabot |
| Pre-commit | ruff + hygiene + prettier | — |

All gates run locally (`CONTRIBUTING.md`) and in CI (§N). The frontend uses **full
TypeScript `strict`** (enabled in Phase 5).

**Status:** ✅ both stacks gated — Python `ruff`/`mypy`/`pytest`, frontend
`eslint`/`tsc` (strict)/`prettier`/`vitest` — and enforced in CI. Dependency
scanning (pip-audit/Dependabot) remains to be wired.

## N. CI/CD

`.github/workflows/ci.yml` runs on PR and push to `master`:

- **frontend job:** `npm ci` → `lint` → `typecheck` → `test` → `build`.
- **python job (matrix 3.11, 3.12):** `uv sync` → `ruff check` →
  `ruff format --check` → `mypy` → `pytest --cov` → upload coverage.

`deploy.yml` (build → GitHub Pages → website embed sync) stays, but deploy is
gated on CI being green. **CI-first**: there is no PyPI/Docker publish target;
the only "CD" is the static Pages deploy + embed sync.

**Status:** ✅ `ci.yml` runs both stacks on PR + push to `master`; `deploy.yml`
is gated on the same frontend checks. Enabling branch protection (require the CI
checks) is a one-time GitHub settings step.

## O. Documentation

| Doc | Purpose |
|---|---|
| `README.md` | what it is, install, quickstart |
| `docs/engineering-standards.md` | this file |
| `docs/architecture.md` | components & data flow |
| `docs/data-contract.md` | per-source scope + output schema (§G) |
| `docs/testing.md` | how tests work |
| `docs/troubleshooting.md` | common failures & native deps |
| `CHANGELOG.md` / `CONTRIBUTING.md` / `.env.example` | releases / workflow / config |

The existing roadmap docs (`multi-city-roadmap.md`, `transit-*`, `travel-time-*`,
`r5py-*`, `website-embed-sync.md`, `current-state.md`, `data-pipeline.md`) are
kept and cross-linked from `architecture.md`.

**Status:** ✅ standards, data-contract, architecture, testing, and
troubleshooting docs present, plus `CHANGELOG.md`, `CONTRIBUTING.md`, and
`.env.example`.

## P. Security and privacy

This tool processes open data, but crime records are sensitive.

- **Local-first, non-networked by default at runtime**: the frontend ships only
  pre-aggregated GeoJSON; no extracted content is ever sent to an external model.
- **Crime data:** outputs are **aggregate-only** (counts + density per area);
  raw victim rows are never written to outputs or logged.
- **Secrets:** none committed (verified). `WEBSITE_REPO_DEPLOY_KEY` lives only in
  GitHub Actions secrets; `.env` is gitignored, `.env.example` documents config.
- **Untrusted files** (downloaded GeoJSON/ZIP/CSV) parsed defensively; password-
  protected / corrupt inputs fail safely with a `FetchError`.
- Dependencies scanned (`pip-audit`, `npm audit`, Dependabot).

**Status:** ✅ no secrets committed, aggregate-only crime; 🟡 logging-redaction
enforced in Phase 3, dependency scanning in Phase 7.

## Q. Performance and scalability

Concrete scalability statement (not "it's scalable"):

> The pipeline scores ~1,215 postal codes and ~1,837 colonias per CDMX run using
> vectorized GeoPandas operations over typed point datasets, per-source failure
> isolation, hash-based skip-unchanged, atomic output writes, and bounded
> retries on network sources (Overpass: 2 attempts, 3 s backoff). It scales to
> additional cities by adding a city profile, not by changing code.

- Avoid loading huge inputs unnecessarily; reproject once to the city metric CRS.
- Network sources have bounded retries/timeouts; r5py routing is opt-in.
- **Large committed GeoJSON** (6–9 MB) is an explicit trade-off: it keeps Pages a
  pure static deploy. Follow-ups if it grows: Git LFS or build-time-only
  generation. The trade-off is logged here rather than left implicit.

**Status:** ✅ vectorized + bounded retries; 🟡 skip-unchanged/atomic writes in
Phase 3; large-file policy documented.

## R. Graceful interruption

On `Ctrl+C`, `src/cdmxmap/pipeline/runner.py` installs a SIGINT handler that:
stops accepting new sources, lets the current source finish or aborts it safely,
marks the in-progress entry `interrupted` in the manifest, avoids half-written
final outputs, writes an interruption summary, and exits non-zero. The next run
continues with `--resume`.

```
Interrupted by user.
Sources: 5 done, 1 interrupted, 0 pending
Resume with: cdmxmap run --city cdmx --resume
```

**Status:** ⬜ Phase 3.

## S. Traceability

Six kinds of traceability, all backed by the manifest + metadata sidecar:

| Type | How |
|---|---|
| Source → output | which source/URL/SHA produced which area fields |
| Step | which pipeline steps ran (`fetch, score, transit, write`) |
| Dependency | which library/router version processed the run |
| Error | which source/area failed, where, why (`errors.json`) |
| Content | each property block tagged with its source (e.g. `transit_commute_source`) |
| Run | which command/config produced this run (`manifest.json`) |

`score_metadata_<unit>.json` already records counts, coverage, source provenance,
and the transit engine; Phase 3 adds source SHAs, pipeline steps, and per-area
warnings so any output field is traceable to its origin — valuable for answering
"where did this area's score come from?".

**Status:** 🟡 metadata partially implemented in `build_metadata()`; full
provenance in Phase 3.

---

### Compliance snapshot

| Area | A | B | C | D | E | F | G | H | I | J | K | L | M | N | O | P | Q | R | S |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Status | ✅ | 🟡 | ✅ | ✅ | 🟡 | 🟡 | ✅ | 🟡 | ⬜ | ⬜ | 🟡 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⬜ | 🟡 |

✅ done · 🟡 in progress · ⬜ planned. The phased roadmap to full compliance is
tracked in the project plan; this table is updated as phases land.
