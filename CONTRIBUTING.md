# Contributing

Thanks for working on the CDMX Convenience Map. This guide covers the day-to-day
workflow. For the full rationale behind every rule, see
[`docs/engineering-standards.md`](docs/engineering-standards.md).

The project is **dual-stack**:

- a Python geo data pipeline under `src/cdmxmap/` (fetch open data → score areas →
  write GeoJSON + metadata), and
- a static React + TypeScript + Leaflet frontend under `frontend/`.

## Setup

Python (managed by [uv](https://docs.astral.sh/uv/)):

```bash
uv sync                 # creates .venv, installs runtime + dev deps
uv sync --extra transit # optional: schedule-aware r5py routing (needs Java 21+)
```

Frontend:

```bash
cd frontend
npm install
```

## Day-to-day commands

```bash
# Python
uv run ruff check .            # lint
uv run ruff format --check .   # formatting gate (use `ruff format .` to fix)
uv run mypy                    # type-check src/cdmxmap
uv run pytest                  # tests (add --cov=cdmxmap for coverage)

# Frontend (run inside frontend/)
npm run lint
npm run typecheck
npm run format                 # use `npm run format:write` to fix
npm run build
npm run test                   # once Vitest is wired (Phase 6)
```

A `pre-commit` configuration runs the fast gates automatically:

```bash
uv run pre-commit install
```

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/) with a project
scope. Common scopes: `scoring`, `sources`, `transit`, `cli`, `frontend`,
`data`, `docs`, `ci`, `chore`.

Good:

```
feat(scoring): add inverse-density gym score
fix(frontend): keep weight sliders from breaking the map
data(crime): refresh FGJ snapshot to 2024-09
docs(cli): document --resume and --fail-fast
```

Avoid: `updates`, `final version`, `stuff`, `fix`.

## Branches & pull requests

- `master` is protected and should stay green. Branch for every change.
- Open a PR; CI (`.github/workflows/ci.yml`) must pass before merge.
- Keep PRs small and focused — ideally one logical change.
- Update `CHANGELOG.md` under `[Unreleased]` for any user-visible change.

## Tests

See [`docs/testing.md`](docs/testing.md) for the full strategy (unit /
integration / e2e / golden) and how to update golden files. Add or update tests
with behavior changes; never mark a task done with failing tests.

## Data & secrets

- Never commit secrets. Runtime config lives in `data/config/places.json` and
  `data/cities/<city>/city.json`; see `.env.example` for environment overrides.
- Large downloaded inputs (`data/raw/`) and generated outputs (`data/processed/`,
  `runs/`) are gitignored. Only small seed/config files are versioned.
- Crime data is sensitive: outputs are aggregate-only and raw victim rows are
  never logged. See standards §P.
