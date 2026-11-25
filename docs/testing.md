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
    fixture_city/        # tiny synthetic city (areas.geojson + point CSVs + places.json
                         # + expected_properties.json golden, plus the CDMX goldens
                         # expected_metadata / expected_postal_properties /
                         # expected_property_order.json)
    fixture_city_stats/  # synthetic city_statistics city (areas with mun_code +
                         # crime_statistics.csv) and its goldens
    mx_amenities/, mx_crime/  # small Overpass / index-page samples for the
                         # Mexican fetcher tests
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

`tests/integration/test_cdmx_goldens.py` pins the rest of what CDMX publishes:
the full metadata dict (minus `generated_at`) by value and key order, the
postal-code unit's properties, and the property order of every output. Multi-city
engine work must leave it unchanged. `tests/integration/test_city_statistics.py`
does the same for the `city_statistics` crime mode over `fixture_city_stats/`.
`tests/integration/test_public_parts.py` covers parts publishing through
`build_area` and checks the committed data: every file under
`frontend/public/data/` must fit the pre-commit `check-added-large-files` limit
(read from `.pre-commit-config.yaml`; CI does not run pre-commit), and each
committed parts index must match its parts. `frontend/src/constants.test.ts`
checks from the frontend side that every city's score and metadata URL is a
file and that each parts index matches its parts.

The Mexican fetchers (`mx_common`, the INEGI/SEPOMEX geography, Nuevo León and
GTFS transit, the supermarket classifier, DENUE gyms, SESNSP and IIEG crime) are
unit-tested offline: the download helper is monkeypatched and inputs come from
small fixtures built in the test or kept under `tests/fixtures/`.

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
