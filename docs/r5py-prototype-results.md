# r5py Prototype Results

Last run: 2026-04-29.

## Result

r5py now runs locally with the real CDMX GTFS feed and a BBBike Mexico City OSM PBF. It builds a transport network, computes schedule-aware transit travel-time matrices, writes cached CSVs, and `scripts/build_scores.py --transit-router r5py` overlays successful r5py rows while preserving the existing Apimetro approximation as fallback.

This is a real schedule-aware routing result, but coverage is below the 90% QA target:

| Area unit | Origins | r5py routed | Fallback / failed | Coverage | Runtime |
| --- | ---: | ---: | ---: | ---: | ---: |
| postal_code | 1,215 | 823 | 392 | 67.7% | 229.7 sec |
| colonia | 1,837 | 1,429 | 408 | 77.8% | 410.9 sec |

Recommendation: keep r5py opt-in for now. Do not make it the default until coverage is closer to 90-95% and stop/itinerary metadata is improved.

## Inputs

GTFS:

- Path: `data/raw/gtfs/cdmx_gtfs.zip`
- SHA1: `0ab3dea28a81bd58a83b0d2b21dcfa344b211a6e`

OSM:

- Path: `data/raw/osm/mexico-city.osm.pbf`
- Source: `https://download.bbbike.org/osm/bbbike/MexicoCity/MexicoCity.osm.pbf`
- Size: 19 MB
- SHA1: `03da50a72e27b9b26d9a2b83da742be2c8eeaab1`

Routing environment:

- Python: `.venv-routing/`
- r5py: `1.1.3`
- Java: `/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home`
- No Java heap override was needed.

## GTFS Sanitization

The CDMX GTFS ZIP needed a small r5py/R5 compatibility pass. The original ZIP remains untouched. The experiment script writes a sanitized copy to:

```text
data/processed/r5py/cdmx_gtfs_r5py_sanitized.zip
```

Fixes applied to the sanitized copy:

| File | Field / issue | Rows fixed |
| --- | --- | ---: |
| `agency.txt` | added missing route agency `SEMOVI` | 1 |
| `trips.txt` | normalized `direction_id` blanks / `0.0` / `1.0` to integers | 1,205 |
| `frequencies.txt` | normalized `exact_times` blanks / `0.0` to integers | 1,584 |

Without this sanitizer, R5 fails before network build with GTFS number parsing and agency referential-integrity errors.

## Commands

OSM download:

```bash
mkdir -p data/raw/osm
curl -L --fail -o data/raw/osm/mexico-city.osm.pbf "https://download.bbbike.org/osm/bbbike/MexicoCity/MexicoCity.osm.pbf"
```

r5py runs:

```bash
JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home .venv-routing/bin/python scripts/experiments/compute_r5py_travel_times.py --area-unit postal_code --service-date 2026-05-05
JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home .venv-routing/bin/python scripts/experiments/compute_r5py_travel_times.py --area-unit colonia --service-date 2026-05-05
```

Production rebuild:

```bash
.venv/bin/python scripts/build_scores.py --area-unit postal_code --transit-router r5py
.venv/bin/python scripts/build_scores.py --area-unit colonia --transit-router r5py
```

Validation:

```bash
.venv/bin/python scripts/validate_processed.py
cd frontend && npm run build && npm run lint
```

## Output Files

Generated r5py cache files:

| File | Size |
| --- | ---: |
| `data/processed/transit_commute_r5py_postal_code.csv` | 56 KB |
| `data/processed/transit_commute_r5py_colonia.csv` | 128 KB |
| `data/processed/transit_commute_r5py_postal_code.metadata.json` | 4 KB |
| `data/processed/transit_commute_r5py_colonia.metadata.json` | 4 KB |

Generated public app assets after r5py rebuild:

| File | Size |
| --- | ---: |
| `frontend/public/data/scores_postal_code.geojson` | 4.9 MB |
| `frontend/public/data/scores_colonia.geojson` | 6.8 MB |
| `frontend/public/data/cdmx_postal_scores.geojson` | 4.9 MB |
| `frontend/public/data/score_metadata_postal_code.json` | 8 KB |
| `frontend/public/data/score_metadata_colonia.json` | 8 KB |
| `frontend/public/data/score_metadata.json` | 8 KB |

## Coverage Details

The r5py matrix returned fewer rows than total origins:

| Area unit | Matrix rows | Successful median times | Total origins |
| --- | ---: | ---: | ---: |
| postal_code | 882 | 823 | 1,215 |
| colonia | 1,533 | 1,429 | 1,837 |

r5py emitted warnings that some origin points could not be snapped to the street network. Failed areas include outer CDMX areas where representative points are near Apimetro stops but r5py could not produce a schedule-aware route from the OSM/GTFS network. This suggests the remaining gap is likely a combination of:

- representative points that do not snap cleanly to routable OSM streets,
- limits of the BBBike Mexico City extract near the CDMX edges,
- GTFS reachability or service-pattern gaps for the chosen Tuesday service date,
- the current single-destination, 08:00-10:00 departure-window setup.

Increasing the route search cap from 180 to 300 minutes improved postal-code coverage from 506/1,215 to 823/1,215. It did not fix missing matrix rows, so the remaining issue is not only max trip duration.

## Comparison With Apimetro Approximation

The existing Apimetro approximation remains useful because it covers every area deterministically and provides origin/destination stop context. Its weakness is that it is not schedule-aware: it uses nearest-stop pairs, straight-line walking, simple mode speeds, and fixed transfer penalties.

r5py is schedule-aware and uses GTFS service patterns, but in this run it covers only:

- 67.7% of postal codes,
- 77.8% of colonias.

Production `--transit-router r5py` therefore uses hybrid output:

| Area unit | r5py rows | Apimetro fallback rows |
| --- | ---: | ---: |
| postal_code | 823 | 392 |
| colonia | 1,429 | 408 |

The frontend still displays Apimetro nearest-stop names for r5py rows. Those stop names are context only; the current r5py CSV does not yet include itinerary legs or actual boarded/alighted stops.

## Sample Rows

Fastest postal-code r5py sample:

| Area | Transit time | Transit score | Source | Origin stop context | Destination stop context |
| --- | ---: | ---: | --- | --- | --- |
| CP 11510 | 0 min | 100.0 | `r5py_gtfs_schedule` | Av. Horacio y Luis Vives | Av. Horacio y Luis Vives |
| CP 11530 | 9 min | 95.5 | `r5py_gtfs_schedule` | Av. Horacio y Socrates | Av. Horacio y Luis Vives |
| CP 11600 | 10 min | 95.0 | `r5py_gtfs_schedule` | Periférico - Ejército Nacional | Av. Horacio y Luis Vives |
| CP 11500 | 13 min | 93.5 | `r5py_gtfs_schedule` | Miguel de Cervantes S. y Presa Pabellón | Av. Horacio y Luis Vives |
| CP 11650 | 14 min | 93.0 | `r5py_gtfs_schedule` | Sierra Santa Rosa - Muinura | Av. Horacio y Luis Vives |

Fastest colonia r5py sample:

| Area | Transit time | Transit score | Source | Origin stop context | Destination stop context |
| --- | ---: | ---: | --- | --- | --- |
| Los Morales (Polanco) | 3 min | 98.5 | `r5py_gtfs_schedule` | Av. Horacio y Juan Vazquez | Av. Horacio y Luis Vives |
| Del Bosque (Polanco) | 4 min | 98.0 | `r5py_gtfs_schedule` | Blvd. Manuel Avila C. y Priv. de Horacio | Av. Horacio y Luis Vives |
| Morales Seccion Alameda (Polanco) | 7 min | 96.5 | `r5py_gtfs_schedule` | Av. Horacio y Socrates | Av. Horacio y Luis Vives |
| Morales Seccion Palmas (Polanco) | 10 min | 95.0 | `r5py_gtfs_schedule` | Av. Homero y Socrates | Av. Horacio y Luis Vives |
| Palmitas (Polanco) | 13 min | 93.5 | `r5py_gtfs_schedule` | Blvd. Manuel Avila C. y Monte Elbruz | Av. Horacio y Luis Vives |

Notes on samples:

- `transit_commute_source = r5py_gtfs_schedule` means the travel time came from the r5py matrix.
- Origin/destination stop names are still Apimetro context, not r5py itinerary legs.
- Failed r5py areas retain `apimetro_stop_pair_approximation` values in production GeoJSON.

## Integration Status

Implemented and verified:

- `scripts/experiments/compute_r5py_travel_times.py` runs with r5py 1.1.3.
- The script supports both `TravelTimeMatrixComputer` and `TravelTimeMatrix`.
- The script sanitizes GTFS into an ignored processed ZIP for R5 compatibility.
- Matrix computation is batched per area unit instead of one origin at a time.
- `scripts/build_scores.py --transit-router r5py` preserves postal-code leading zeroes when loading cached r5py CSVs.
- r5py rows overlay successful schedule-aware results.
- Apimetro approximation remains the fallback.
- Default `build_scores.py` behavior remains Apimetro unless `--transit-router r5py` is passed.

Checks passed:

```bash
python3 -m py_compile scripts/*.py scripts/experiments/*.py
.venv/bin/python scripts/validate_processed.py
cd frontend && npm run build
cd frontend && npm run lint
```

## Recommendation

Keep `apimetro_approximation` as the default production path for now.

r5py should not become the default until coverage improves. The next most useful work is:

1. Try a broader OSM extract, such as Geofabrik Mexico clipped to a generous CDMX buffer.
2. Pre-snap representative points to nearby routable street vertices before passing them to r5py.
3. Add itinerary or stop-leg extraction if r5py/R5 exposes enough detail, or evaluate OpenTripPlanner for richer route summaries.
4. Revisit `score_work_transit`: the current score curve reaches zero after 90 minutes, while many valid schedule-aware r5py trips are longer.
5. Keep tracking source counts in metadata so the frontend can clearly distinguish r5py rows from Apimetro fallback rows.
