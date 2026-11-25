# Offline Road Routing

Replaces the straight-line travel-time placeholder for **work** and **amenity**
(supermarket / Costco / Walmart / gym) times with real street-network routing,
computed entirely offline during preprocessing and baked into the static GeoJSON.
No routing happens in the browser; GitHub Pages stays a pure static deploy.

Routing is **opt-in**. With no router configured the pipeline keeps its
deterministic straight-line fallback (`fallback_straight_line_estimate`), and the
generated output is byte-identical to before.

## Architecture decision: Valhalla via `pyvalhalla`

We evaluated OSRM and Valhalla (the travel-time roadmap also lists ORS/GraphHopper,
both rejected: hosted, API-key, rate-limited — incompatible with an offline,
key-free, static pipeline).

**Chosen: Valhalla, in-process via the `pyvalhalla` pip wheel.**

| Criterion | Valhalla (`pyvalhalla`) | OSRM |
|---|---|---|
| Profiles | One tile build serves `auto`/`pedestrian`/`bicycle` | One graph **per profile** (3 builds + 3 servers) |
| Setup | `uv sync --extra routing` (prebuilt binaries) — no Docker/Java | Docker (or C++ build) + per-profile preprocessing |
| Reproducibility | In-process `Actor` against a local tileset; no server lifecycle | HTTP server(s) to manage |
| Batch matrix | `sources_to_targets` action | `/table` (faster at very large N) |

For this repo Valhalla wins on profile coverage (one build for three modes), setup
burden (pip-installable, runs on a Docker-less machine), and reproducibility
(no server). OSRM's faster `/table` matters mainly at full-matrix scale; our
per-area-unit matrices are small enough that it isn't decisive. **OSRM remains a
drop-in alternative behind the `Router` Protocol** (`src/cdmxmap/routing/base.py`)
if a future need arises — it is documented, not built.

**Why not a bespoke contraction-hierarchies engine** (cf. Dibbelt, Strasser &
Wagner, *Customizable Contraction Hierarchies*, arXiv:1402.0402): a mature engine
already meets the need with far less risk. Valhalla internally uses hierarchical
graph techniques; hand-rolling a CCH engine is unjustified here.

Free-flow only: Valhalla has no live-traffic model, so results are labeled
`valhalla_free_flow` and are **never** presented as "actual traffic commute time".

## Components

- `src/cdmxmap/routing/base.py` — `Router` Protocol + `RouteMatrix`.
- `src/cdmxmap/routing/valhalla.py` — `ValhallaRouter` (in-process Actor, chunked
  `sources_to_targets`, mode→costing, unreachable→NaN) + `build_tiles()`.
- `src/cdmxmap/routing/cache.py` — `RoutingCache` (stable keys: area unit/id,
  origin/destination coords, mode, engine, version, profile, inputs hash).
- `src/cdmxmap/routing/matrix_codec.py` / `matrix_build.py` — the area-to-area
  matrix binary codec and builder.
- Scoring integration: `score_areas(..., router=...)` routes work + amenity
  candidates with per-row straight-line fallback (`src/cdmxmap/scoring/`).

## Setup & build (one-time, offline)

Requires network to fetch the OSM extract once; the build itself is offline.
The sequence below is for CDMX, whose published maps are not routed. Monterrey
and Guadalajara have their own sequence below.

```bash
uv sync --extra routing
mkdir -p data/raw/osm
curl -L --fail -o data/raw/osm/mexico-city.osm.pbf \
  "https://download.bbbike.org/osm/bbbike/MexicoCity/MexicoCity.osm.pbf"
uv run cdmxmap build-tiles --pbf data/raw/osm/mexico-city.osm.pbf
# Routed work + amenity times baked into the GeoJSON:
uv run cdmxmap run --area-unit postal_code --travel-router valhalla
uv run cdmxmap run --area-unit colonia   --travel-router valhalla
# Dynamic-workplace area-to-area matrix (binary + index):
uv run cdmxmap build-matrix --area-unit postal_code --travel-router valhalla
uv run cdmxmap build-matrix --area-unit colonia   --travel-router valhalla
uv run cdmxmap validate
(cd frontend && npm run build)
```

`build-tiles` writes a routing config to `<tiles-dir>/valhalla.json` and runs the
`pyvalhalla`-bundled `valhalla_build_tiles`; the graph tiles land directly in
`--tiles-dir` (default `data/processed/valhalla/`). The OSM PBF, the tileset, and
the per-cell cache (`data/processed/routing_cache/`, or
`data/processed/<city>/routing_cache/` for a profile city) are all gitignored.

## Monterrey and Guadalajara (published routed maps)

Monterrey and Guadalajara are the first cities whose published maps are routed:
work and amenity times for both geographies are Valhalla free-flow routes, and
the postal-code unit ships a dynamic-workplace matrix. The other cities remain
straight-line.

**One national tileset.** BBBike has no Monterrey or Guadalajara extract, so both
cities route on a single tileset built from Geofabrik's national Mexico file
(`mexico-261124.osm.pbf`, md5 `7140e40aaf94d08ebc0551a8880f3d9e`, OSM data of
2026-11-24) at `data/processed/valhalla_mx/`. The build took 79 s, wrote 3,467
tiles (about 2 GB), and peaked at about 25 GB of RAM. Do not build two PBFs into
the same tiles directory. Both cities' `places.json` point at the same tileset:

```json
"road_routing": {
  "engine": "valhalla",
  "tiles_dir": "data/processed/valhalla_mx",
  "modes": ["driving", "walking", "biking"],
  "osm_source": "https://download.geofabrik.de/north-america/mexico/mexico-261124.osm.pbf",
  "osm_md5": "7140e40aaf94d08ebc0551a8880f3d9e",
  "osm_date": "2026-11-24",
  "search_filter": { "min_road_class": "residential" }
}
```

**`search_filter`.** Without it, representative points in forest and mountain
postal codes snap to tracks and service roads, and some driving times ran to
hundreds of minutes. The filter is sent on every Valhalla source and target and
is part of the routing-cache key and the matrix content hash, but only when
declared, so CDMX requests and hashes are unchanged. `osm_md5` and `osm_date` are
recorded in the metadata and in the matrix index (`osm_sha`, `osm_date`).

**Build sequence** (from the repo root; `tiles_dir` is relative to it).
`pyvalhalla` 3.7.0 ships a CPython 3.12 abi3 wheel, so the `routing` extra needs
the Python 3.12 environment.

```bash
uv sync --extra routing
mkdir -p data/raw/osm
curl -L --fail -o data/raw/osm/mexico-261124.osm.pbf \
  "https://download.geofabrik.de/north-america/mexico/mexico-261124.osm.pbf"
md5 -q data/raw/osm/mexico-261124.osm.pbf   # macOS; md5sum on Linux. Expect 7140e40a…
uv run --extra routing cdmxmap build-tiles \
  --pbf data/raw/osm/mexico-261124.osm.pbf --tiles-dir data/processed/valhalla_mx
for city in monterrey guadalajara; do
  uv run --extra routing cdmxmap run --city "$city" --area-unit postal_code --travel-router valhalla
  uv run --extra routing cdmxmap score --city "$city" --area-unit colonia --travel-router valhalla
  uv run --extra routing cdmxmap build-matrix --city "$city" --area-unit postal_code --travel-router valhalla
  uv run cdmxmap validate --city "$city"
done
```

`build-tiles` has no `--city` option, so always pass `--tiles-dir`. If Geofabrik
no longer serves the dated file, use a newer one and update `osm_source`,
`osm_md5`, and `osm_date` in both `places.json` files.

Measured run times (single-threaded): Monterrey about 2.5 min (postal codes), 18
min (colonias), and 25 min (matrix); Guadalajara about 2, 12, and 8 min.

**Published matrices**: `frontend/public/data/<city>/routing_matrix_postal_code_{driving,walking,biking}_<hash>.bin`
plus `routing_matrix_postal_code_index.json`. Monterrey: 3 × 865,928 B (658
postal codes); Guadalajara: 3 × 321,602 B (401). There is no colonia matrix:
4,698² × 2 B × 3 modes would be about 132 MB for Monterrey (42 MB for
Guadalajara), too much to commit. Colonia views therefore use the labeled
estimate for a custom workplace, while their times to the default workplace and
to amenities are routed.

**Comparability.** Routed free-flow driving times come out at about 0.45× the
straight-line estimate (median 0.42 in Monterrey and 0.44 in Guadalajara, over
postal codes more than 500 m from the workplace). Routed and unrouted cities are
therefore not comparable, and the per-feature source labels and UI badges must
stay visible.

## Dynamic-workplace matrix

The frontend lets a user pick any area as their workplace. Real routing can't run
in the browser, so we precompute the full **area-to-area** routed matrix offline
and ship it as a binary the browser reads one column at a time over HTTP Range.

Per `(area_unit, mode)`:

- `routing_matrix_<area_unit>_<mode>_<hash>.bin` — N×N travel time in
  **deciminutes** (minutes×10) as little-endian `uint16`, sentinel `65535` for
  unreachable, **destination-major** (a chosen workplace = one contiguous column).
- `routing_matrix_<area_unit>_index.json` — `area_ids` (order), `n`, `dtype`,
  `scale`, `sentinel`, axis order, per-mode filenames, engine/profile/OSM
  provenance. The `<hash>` busts stale CDN caches; the frontend reads the index
  first and follows it to the binaries.

The frontend (`frontend/src/lib/routingMatrix.ts`) feature-detects the index: when
it is absent (the default straight-line build) it silently uses the labeled
estimate, so the repo isn't forced to carry the matrix until the build is run.

**Storage** (≈ doubles the committed payload, accepted): for CDMX, postal
1,215²×2×3 ≈ 8.8 MB, colonia 1,837²×2×3 ≈ 20.2 MB, total ≈ 29 MB. A browser
column fetch is ≈ N×2 bytes (~3.7 KB). The published assets live under
`frontend/public/data/` (`frontend/public/data/<city>/` for profile cities) and
are committed only after a routed build is run; today only Monterrey and
Guadalajara have them (see above).

The frontend (`frontend/src/lib/routingMatrix.ts`) loads the index of the
selected city and unit (`city.assets.matrixIndex[unit]`, cached per URL) and
resolves the binaries relative to that index, so each city reads its own files.

**Limitations**: the matrix is per area unit, so routed dynamic-workplace times
apply when the chosen workplace and the viewed areas share a unit (a postal-code
workplace + postal view). Other combinations, and units without a matrix (the
Monterrey and Guadalajara colonia views), fall back to the labeled estimate.

## Honesty contract

- `valhalla_free_flow` for genuinely routed rows; `fallback_straight_line_estimate`
  (work) / `fallback_travel_time` (dynamic workplace) for rows that fall back.
- Routed distance is stored separately (`*_routed_m`), `null` on fallback rows.
- `score_work` / `score_combined_default` stay distance-based for a stable
  headline; only per-mode `score_work_<mode>` reflect routed times.
- Transit routing (r5py/GTFS) is entirely separate and schedule-aware; road
  routing never touches it.
