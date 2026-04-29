# True Transit Routing Spike

## Goal

Evaluate whether the current Apimetro stop-pair commute approximation can later be replaced or supplemented by true schedule-aware public-transit routing. This spike does not change production scoring and does not remove the current approximation.

## Existing State

Active scoring uses Apimetro station/stop points and straight-line stop-pair heuristics in `scripts/transit_commute/approximate.py`.

Existing GTFS-related code:

- `scripts/archive/fetch_gtfs_transit.py`: archived downloader that fetches the CDMX GTFS ZIP and extracts `stops.txt` into `data/processed/transit_stops.csv`.
- `scripts/transit_commute/future_gtfs.py`: placeholder that explicitly raises `NotImplementedError`.
- `data/archive/README.md`: documents that the original GTFS stop-distance metric was archived because it was noisy.

The current app can safely keep the Apimetro approximation as a fallback while a real router is prototyped offline.

## Available GTFS Source

Official source:

- Dataset page: https://datos.cdmx.gob.mx/dataset/gtfs
- CKAN resource id: `32ed1b6b-41cd-49b3-b7f0-b57acb0eb819`
- Current observed download URL from Transitland import:
  `https://datos.cdmx.gob.mx/dataset/75538d96-3ade-4bc5-ae7d-d85595e4522d/resource/32ed1b6b-41cd-49b3-b7f0-b57acb0eb819/download/gtfs-2.zip`

The official portal describes coverage for Corredores Concesionados, Metro, Metrobus, RTP, Tren Ligero, Ferrocarril Suburbano, Cablebus, Trolebus, and Pumabus. The page reports "Ultima Actualizacion: 24 de febrero 2026".

Transitland cross-check:

- Feed version: https://www.transit.land/feeds/f-9g3-semovi/versions/0ab3dea28a81bd58a83b0d2b21dcfa344b211a6e
- SHA1: `0ab3dea28a81bd58a83b0d2b21dcfa344b211a6e`
- Imported/added by Transitland: 2026-03-24
- Service range: 2024-12-01 to 2026-12-31

The local cache `data/archive/gtfs_legacy/gtfs.zip` has the same SHA1 as the Transitland version, so the checked local ZIP appears to be the current feed version.

Automatic download should be feasible. The existing archive script already uses the CKAN resource URL shape with `scripts/common.download()`. The URL should be updated to `gtfs-2.zip`, or better, the fetcher should query CKAN/package metadata for the current resource URL instead of hard-coding the filename. The local shell environment for this spike could not resolve external DNS, so direct `curl`/`pip` checks failed locally; web verification and local ZIP validation were used instead.

## GTFS Structure Validation

Validated local ZIP:

```text
data/archive/gtfs_legacy/gtfs.zip
size: 2.3 MiB
sha1: 0ab3dea28a81bd58a83b0d2b21dcfa344b211a6e
```

Required structure:

| File | Status | Rows |
| --- | --- | ---: |
| `agency.txt` | present | 10 |
| `stops.txt` | present | 11,362 |
| `routes.txt` | present | 301 |
| `trips.txt` | present | 1,205 |
| `stop_times.txt` | present | 42,789 |
| `calendar.txt` | present | 13 |
| `calendar_dates.txt` | missing, acceptable because `calendar.txt` is present | 0 |
| `frequencies.txt` | present | 1,584 |
| `shapes.txt` | present | 127,135 |

Agencies in the feed:

- Tren El Insurgente
- Pumabus
- Corredores Concesionados
- Sistema de Transporte Colectivo Metro
- Metrobus
- Servicio de Tren Ligero
- Ferrocarriles Suburbanos
- Trolebus
- Red de Transporte de Pasajeros
- Cablebus

Route counts by `agency_id`:

| Agency id | Routes |
| --- | ---: |
| `CC` | 137 |
| `RTP` | 114 |
| `PUMABUS` | 12 |
| `METRO` | 12 |
| `TROLE` | 11 |
| `MB` | 8 |
| `CBB` | 3 |
| `SEMOVI` | 1 |
| `INTERURBANO` | 1 |
| `TL` | 1 |
| `SUB` | 1 |

Route counts by GTFS `route_type`:

| route_type | Routes |
| --- | ---: |
| `0` | 1 |
| `1` | 13 |
| `2` | 1 |
| `3` | 282 |
| `6` | 3 |
| `11` | 1 |

## Feed Freshness

The feed service coverage is:

```text
2024-12-01 through 2026-12-31
```

This is current enough for an offline commute scoring model in late April 2026. The selected service date for scoring should be a weekday within this range, for example `2026-05-05`, and metadata must record the service date and departure window.

Limitations:

- This is static GTFS, not real-time routing.
- It does not represent disruptions, crowding, reliability, or station access restrictions.
- Feed content should be revalidated before every score regeneration.

## OSM PBF Source

r5py and OpenTripPlanner both need an OpenStreetMap PBF for street access and egress.

Practical options:

- BBBike MexicoCity extract: https://download.bbbike.org/osm/bbbike/MexicoCity/
  - Smaller city extract, reported around 18 MB PBF.
  - Best first prototype input.
- Geofabrik Mexico extract: https://download.geofabrik.de/north-america/mexico.html
  - Larger national extract, reported around 595 MB PBF.
  - More stable provider, but should be clipped before repeated local experiments.

Do not commit PBF or GTFS downloads. The repo `.gitignore` already excludes `data/raw/*.zip`, `data/raw/gtfs/`, and `data/archive/**`.

## r5py Evaluation

Sources:

- r5py installation: https://r5py.readthedocs.io/latest/user-guide/installation/installation.html
- r5py data requirements: https://r5py.readthedocs.io/stable/user-guide/user-manual/data-requirements.html
- r5py quickstart: https://r5py.readthedocs.io/latest/user-guide/user-manual/quickstart.html
- PyPI package: https://pypi.org/project/r5py/

r5py is a good architectural fit:

- It is Python-native and works with GeoPandas inputs.
- It computes travel-time matrices, which is exactly the scoring need.
- It can build a transport network from an OSM `.pbf` plus one or more GTFS ZIPs.
- It can run during preprocessing and emit static GeoJSON, preserving GitHub Pages deployment.

Current project environment blockers:

- Project venv is Python 3.9.6.
- Current r5py 1.1.3 requires Python `>=3.10`.
- `r5py` and `jpype` are not installed.
- `java -version` reports no Java runtime installed.
- r5py docs require a JDK 21+ when installed via pip. Conda/mamba can install OpenJDK as a dependency.
- Local DNS/network is unavailable in this sandbox, so `pip index versions r5py` and direct CDMX `curl` checks could not run.

Conclusion: r5py is viable after environment setup, but it is not immediately runnable in the current venv. The lowest-friction path is a dedicated Python 3.11 or 3.12 environment installed with `mamba`/`conda-forge` so r5py and OpenJDK 21 are managed together.

Recommended setup:

```bash
conda create --name cdmx-routing --channel conda-forge python=3.11 r5py geopandas pandas numpy shapely pyproj requests
conda activate cdmx-routing
java -version
```

If staying on pip:

```bash
python3.11 -m venv .venv-routing
.venv-routing/bin/python -m pip install -U pip
.venv-routing/bin/python -m pip install -r requirements.txt r5py
# Install JDK 21 separately, then verify:
java -version
```

## OpenTripPlanner Evaluation

Sources:

- OTP overview: https://www.opentripplanner.org/
- OTP basic tutorial: https://docs.opentripplanner.org/en/v2.6.0/Basic-Tutorial/
- OTP configuration: https://docs.opentripplanner.org/en/v2.2.0/Configuration/

OpenTripPlanner is a solid fallback, especially if detailed route itineraries become product requirements. It builds graphs from GTFS and OSM, saves `graph.obj`, and serves trip planning APIs from a local Java process.

Requirements and implications:

- OTP2 requires Java 21+.
- It is distributed as a runnable shaded JAR.
- The input directory can contain one or more GTFS ZIPs and an OSM PBF.
- GTFS ZIP names must end in `.zip` and contain `gtfs` unless configured explicitly.
- Typical workflow is graph build, graph save, then server load.
- It provides detailed itineraries and transfer legs, but requires orchestration around a Java server/API even if only used during preprocessing.

OTP is more appropriate than r5py if:

- The frontend needs real route summaries, legs, transfer points, and route names.
- We want a route-planner API for manual QA.
- r5py cannot handle the CDMX feed or produces insufficient diagnostics.

OTP is less appropriate for the first scoring integration because the app only needs area-to-workplace travel-time matrices and static output fields.

## Recommended Engine

Recommended first implementation engine: r5py.

Reasoning:

- The product need is a batch travel-time matrix, not interactive trip planning.
- The existing scoring pipeline is Python and GeoPandas-based.
- r5py can produce one row per origin/destination pair and join cleanly into current score outputs.
- It avoids running and querying a local web service during preprocessing.

Fallback: OpenTripPlanner.

Use OTP if r5py fails to build a network from the CDMX GTFS plus OSM PBF, if route diagnostics are too opaque, or if detailed route summaries become necessary.

## Exact Implementation Steps

1. Keep the current Apimetro approximation unchanged.
2. Add a GTFS fetch/validate command that either:
   - queries the CKAN dataset/resource metadata for the current download URL, or
   - uses the observed current `gtfs-2.zip` URL with a documented update process.
3. Download GTFS to an ignored path such as `data/raw/gtfs/cdmx_gtfs.zip`.
4. Run `scripts/experiments/validate_cdmx_gtfs.py` and fail fast if:
   - required GTFS files are missing,
   - neither `calendar.txt` nor `calendar_dates.txt` exists,
   - the configured service date is outside feed coverage,
   - row counts are unexpectedly zero.
5. Download the BBBike MexicoCity OSM PBF to an ignored path such as `data/raw/osm/mexico-city.osm.pbf`.
6. Create a dedicated Python 3.11+ routing environment with r5py and JDK 21.
7. Build an r5py `TransportNetwork` from the OSM PBF and GTFS ZIP.
8. Build origin GeoDataFrames from the existing area representative points for both `postal_code` and `colonia`.
9. Build a destination GeoDataFrame from the configured workplace coordinates.
10. Compute transit/walk matrices for a weekday commute window, for example 08:00 to 10:00 every 15 minutes.
11. Store a robust statistic per origin, preferably median and p75 travel time.
12. Cache outputs under an ignored or reproducible path, for example `data/processed/transit_commute_r5py_{area_unit}.csv`.
13. Add a non-default build flag such as `--transit-router r5py` so production scoring does not switch accidentally.
14. Join routed minutes into the existing fields:
   - `time_work_transit_min`
   - `score_work_transit`
   - `transit_commute_source`
   - `transit_commute_notes`
15. Keep route-detail fields nullable unless a later engine returns reliable details.
16. Fall back to `apimetro_stop_pair_approximation` for null routes until coverage and QA thresholds are met.
17. Add metadata:
   - router engine/version,
   - GTFS URL and SHA1,
   - OSM source and date/hash,
   - service date,
   - departure window,
   - statistic,
   - routed and failed area counts.
18. Validate at least:
   - 95% finite route coverage,
   - no impossible zero/negative long-distance routes,
   - manual spot checks for known CDMX commutes,
   - stable frontend build.

## Prototype Added

This spike adds an experiment-only validator:

```bash
.venv/bin/python scripts/experiments/validate_cdmx_gtfs.py --as-of 2026-04-29
```

To download first in a network-enabled environment:

```bash
.venv/bin/python scripts/experiments/validate_cdmx_gtfs.py --download --as-of 2026-04-29
```

This script writes only when `--download` is passed and does not integrate with production scoring.

## Prototype Results

The r5py prototype path has been implemented behind a non-default `build_scores.py` flag:

```bash
.venv/bin/python scripts/build_scores.py --area-unit postal_code --transit-router r5py
.venv/bin/python scripts/build_scores.py --area-unit colonia --transit-router r5py
```

The default production path remains the Apimetro approximation.

This local run did not produce schedule-aware travel times because the shell environment could not resolve the external download hosts for the GTFS and OSM inputs. The GTFS ZIP was available from `data/archive/gtfs_legacy/gtfs.zip` and validates successfully, but `data/raw/osm/mexico-city.osm.pbf` remained missing. As a result, both r5py runs wrote all-failed diagnostic CSVs:

| Area unit | Origins | r5py routed | Failed | Coverage |
| --- | ---: | ---: | ---: | ---: |
| postal_code | 1,215 | 0 | 1,215 | 0.0% |
| colonia | 1,837 | 0 | 1,837 | 0.0% |

The global prototype error was:

```text
FileNotFoundError: Missing OSM PBF: data/raw/osm/mexico-city.osm.pbf
```

The data was rebuilt with the default Apimetro router after the failed r5py run. Validation, frontend build, and frontend lint passed. Detailed results and next steps are in `docs/r5py-prototype-results.md`.

## Risks

- GTFS freshness may regress or the download filename may change again.
- Static GTFS can disagree with real operations.
- CDMX route/headway modeling may be approximate, especially for frequency-based bus services.
- `frequencies.txt` support must be verified in whichever router is used.
- OSM pedestrian connectivity around stations can cause route failures.
- Station entrances, paid-area transfers, and large terminal transfer paths may be simplified.
- r5py requires Python and Java environment changes.
- OTP requires Java service orchestration and API querying.
- Travel-time matrix runs may be slow for colonia-scale origins over multiple departure times.
- The frontend must communicate router source/date/window so scores do not look live.

## Estimated Complexity

Documentation and validation:

- Done in this spike.

r5py prototype:

- Medium, about 1-2 engineering days after Java/Python environment setup.
- Main uncertainty is network build/runtime behavior with the CDMX feed and OSM extract.

Production integration behind a non-default flag:

- Medium, about 2-4 engineering days after prototype success.
- Includes caching, metadata, failure handling, scoring joins, and validation.

Replacing or supplementing the current approximation by default:

- Medium-high, about 1 additional week after production integration.
- Requires QA thresholds, manual route checks, frontend copy/metadata updates, and comparison against the current approximation.

OTP fallback prototype:

- Medium-high, about 2-4 engineering days.
- More moving parts than r5py, but better itinerary detail if needed.

## Decision

GTFS is usable for a true-routing prototype. It has the required structure, covers the current 2026 service period, and includes the modes the app cares about.

r5py is the preferred first engine, but the project needs a Python 3.10+ environment and JDK 21 before it can run.

OpenTripPlanner is the correct fallback if r5py fails or if detailed route itineraries become a product requirement. It is not the first recommendation for score generation because it adds a local Java server/API workflow.

## Recommended Next Prompt

```text
Implement the r5py prototype path from docs/true-transit-routing-spike.md. Create a Python 3.11+/JDK 21 routing environment, fetch the current CDMX GTFS ZIP and a Mexico City OSM PBF into ignored data/raw paths, validate the GTFS, build an r5py transport network, compute weekday 08:00-10:00 transit+walk travel-time matrices from postal_code and colonia representative points to the configured workplace, cache the results as CSV, and report coverage/runtime. Do not change the default production scoring path; keep the Apimetro approximation as fallback.
```
