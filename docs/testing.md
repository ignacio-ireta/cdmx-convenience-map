# Testing

Test strategy and how to run the suites (engineering standards §K/§L). Tests are
being introduced in Phases 4 (Python) and 6 (frontend); this doc is the contract
they fill in.

## Python

Tests live under `tests/` (outside the package), split by scope:

```
tests/
  unit/          # pure functions: metrics, normalize, config parse, nearest, error classifier
  integration/   # fixture points → score_areas → property contract; score → validate
  e2e/           # `cdmxmap run --city fixture` end to end
  golden/        # compare generated fixture output to committed expected files
  fixtures/      # tiny synthetic city: a few areas + a few points
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

### Golden files

Golden tests pin the output contract against accidental regressions. The fixture
city is small and fully synthetic (no network). To regenerate after an
**intentional** output change:

```bash
uv run cdmxmap score --city fixture --area-unit postal_code \
  --output tests/golden/expected/scores_postal_code.geojson
```

Review the diff carefully — a golden change means the data contract changed and
`score_metadata.extractor_version`, the frontend normalizer, and
`docs/data-contract.md` must move together.

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
