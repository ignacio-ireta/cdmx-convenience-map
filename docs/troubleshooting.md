# Troubleshooting

Common failures and their fixes (engineering standards §O). The pipeline is
local-first; most issues are environment or upstream-source problems.

## Setup / environment

**`uv sync` fails resolving the geospatial stack.** Ensure `uv >= 0.5` and that
you're on macOS or Linux x86_64/arm64 where `pyogrio`/`shapely`/`pyproj` ship
wheels. The wheels bundle GDAL/GEOS/PROJ, so **system GDAL is not required**. The
project pins Python `>=3.11,<3.13`; uv will fetch a managed interpreter.

**`import pyproj`/`geopandas` errors at runtime.** You're likely outside the
venv. Use `uv run …` (or activate `.venv`). Don't mix a system `pip install` with
the uv-managed environment.

**Transit (r5py) routing unavailable.** The `transit` extra is optional and needs
a **Java 21+** runtime on `PATH`. Install it (`uv sync --extra transit`) and a
JDK; otherwise the pipeline falls back to the Apimetro approximation engine and
sets `transit_commute_source` accordingly.

**Road routing (`--travel-router valhalla`) errors.** Install the optional extra
(`uv sync --extra routing`, pulls the `pyvalhalla` wheel — no Docker/Java needed)
and build a tileset (`cdmxmap build-tiles --pbf <osm.pbf>`). A missing extra or
tileset raises an actionable `ConfigError`, not a crash; without `--travel-router`
the pipeline uses the straight-line estimate (`fallback_straight_line_estimate`).
If `cdmxmap build-tiles` can't find `valhalla_build_*`, the wheel's binaries
aren't on `PATH`/in the package — reinstall the extra. See `docs/road-routing.md`.

## Pipeline runs

**A source fails (Overpass timeout, 5xx from datos.cdmx.gob.mx).** By default the
run continues: OSM sources (supermarkets, gyms) degrade to the committed seeds in
`data/seeds/`, and the failure is recorded in `runs/<id>/errors.json` with a
reason. Use `--fail-fast` to stop instead. Re-run later or `--force` to refetch.

**`cdmxmap validate` reports a missing field.** The generated GeoJSON doesn't
match the data contract — usually a scoring change that dropped or renamed a
property. Compare against `docs/data-contract.md` and the golden fixtures.

**"No features have non-null transit commute estimates".** The transit source or
workplace coordinates are missing, so no commute could be computed. Check that
`fetch_transit` succeeded and `places.json` has a resolvable workplace.

**Crash left a partial output.** Shouldn't happen — outputs are written
atomically (temp + rename). If you interrupted a run, resume with `--resume`; the
manifest marks the in-progress source `interrupted`.

## Frontend

**Map loads but tiles/data are missing when embedded.** Vite must build with a
relative `base` (`./`); absolute `/data/...` paths break under the nested
`projects/cdmx-map/` embed path. See `docs/github-pages.md`.

**`npm run build` fails on types.** Run `npm run typecheck` for the full error;
the app uses strict TypeScript. `npm run lint` and `npm run format` catch the
rest.

## Data hygiene

- Raw downloads (`data/raw/`) and processed outputs (`data/processed/`, `runs/`)
  are gitignored and recreated by the pipeline; only small seed/config files are
  versioned.
- Crime data is aggregate-only by design; if you need raw records for debugging,
  keep them local and never commit or log them (standards §P).
