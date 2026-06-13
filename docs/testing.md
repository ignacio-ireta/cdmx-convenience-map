# Testing

Test strategy and how to run the suites (engineering standards §K/§L).

## Python

Tests live under `tests/` (outside the package), split by scope:

```
tests/
  unit/          # pure functions: metrics, normalize, config parse, schema, errors, manifest
  integration/   # fixture points → score_areas → property contract (+ golden compare)
  e2e/           # build_area + run_pipeline + `cdmxmap` CLI over the fixture city
  fixtures/
    fixture_city/  # tiny synthetic city (areas.geojson + point CSVs + places.json
                   # + expected_properties.json golden)
```

Run:

```bash
uv run pytest                      # everything
uv run pytest tests/unit           # only unit
uv run pytest tests/integration    # only integration
uv run pytest -m "not slow"        # skip slow tests
uv run pytest -m e2e               # only end-to-end CLI runs
uv run pytest --cov=cdmxmap        # with coverage
```

Markers (`pyproject.toml`): `slow`, `integration`, `e2e`, `golden`.

### Fixture city & golden file

`tests/fixtures/fixture_city/` is a tiny, fully synthetic city (3 areas + a few
transit/supermarket/gym/crime points + `places.json`) that exercises the whole
scoring path offline — including crime-driven safety variation and transit-commute
estimates. The integration/e2e tests build over it via the `data_dir` /
`public_dir` / `places_config` parameters that `load_point_datasets`, `build_area`,
and `run_pipeline` accept (they default to the real pipeline locations, so
production output is unchanged).

`expected_properties.json` is the **golden**: the sorted feature properties the
fixture run must reproduce (deterministic — `generated_at` lives only in the
metadata, never in the GeoJSON). To regenerate after an **intentional** output
change:

```bash
UPDATE_GOLDEN=1 uv run pytest tests/integration -m golden
```

Review the diff carefully — a golden change means the data contract changed, so
`docs/data-contract.md` and the frontend normalizer must move with it.

## Frontend

Vitest + Testing Library + jsdom (added in Phase 6):

```bash
cd frontend
npm run test            # watch/run
npm run test -- --run   # single run (CI mode)
```

Covered first (highest value, lowest effort): the pure helpers extracted in Phase
5 — `lib/scoring`, `lib/work`, `lib/normalize`, `lib/search`. Then component
smoke tests (ControlsPanel, Legend, DetailsPanel) with `fetch` mocked.

## External dependencies & local skips

- Network fetchers (Overpass/Apimetro/CDMX/FGJ) are **not** exercised in unit/CI
  tests; they are integration-only and skipped without network.
- `r5py` schedule-aware routing needs a JDK and is skipped unless the `transit`
  extra is installed (`@pytest.mark.skipif`).

## What runs in CI

`.github/workflows/ci.yml` runs `ruff`, `mypy`, and `pytest --cov` (Python matrix
3.11/3.12) and `eslint` + `tsc` + `vitest` + `build` (frontend). Network/r5py
tests are excluded from CI.
