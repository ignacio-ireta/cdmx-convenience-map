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

`build-tiles` shells out to the `pyvalhalla`-bundled `valhalla_build_config`,
`valhalla_build_tiles`, and `valhalla_build_extract`. The OSM PBF, the tileset
(`data/processed/valhalla/`), and the per-cell cache (`data/processed/routing_cache/`)
are all gitignored.

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

**Storage** (≈ doubles the committed payload, accepted): postal 1,215²×2×3 ≈
8.8 MB, colonia 1,837²×2×3 ≈ 20.2 MB, total ≈ 29 MB. A browser column fetch is
≈ N×2 bytes (~3.7 KB). The published assets live under `frontend/public/data/`
and are committed only after a routed build is run.

**Limitations**: the matrix is per area unit, so routed dynamic-workplace times
apply when the chosen workplace and the viewed areas share a unit (a postal-code
workplace + postal view). Other combinations fall back to the labeled estimate.

## Honesty contract

- `valhalla_free_flow` for genuinely routed rows; `fallback_straight_line_estimate`
  (work) / `fallback_travel_time` (dynamic workplace) for rows that fall back.
- Routed distance is stored separately (`*_routed_m`), `null` on fallback rows.
- `score_work` / `score_combined_default` stay distance-based for a stable
  headline; only per-mode `score_work_<mode>` reflect routed times.
- Transit routing (r5py/GTFS) is entirely separate and schedule-aware; road
  routing never touches it.
