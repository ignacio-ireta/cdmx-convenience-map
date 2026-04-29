# Requires: .venv-routing/ (Python 3.11+) and JAVA_HOME set to OpenJDK 21
# Run: JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home .venv-routing/bin/python scripts/experiments/compute_r5py_travel_times.py
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DATA_CONFIG = ROOT / "data" / "config"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_PROCESSED_R5PY = DATA_PROCESSED / "r5py"
DEFAULT_GTFS_ZIP = ROOT / "data" / "raw" / "gtfs" / "cdmx_gtfs.zip"
DEFAULT_OSM_PBF = ROOT / "data" / "raw" / "osm" / "mexico-city.osm.pbf"
DEFAULT_SERVICE_DATE = "2026-05-05"
DEFAULT_DEPARTURE_TIME = "08:00"
DEFAULT_DEPARTURE_WINDOW_MINUTES = 120
DEFAULT_MAX_TIME_MINUTES = 300
WGS84_CRS = "EPSG:4326"
R5PY_SOURCE = "r5py_gtfs_schedule"
OSM_SOURCE_URL = "https://download.bbbike.org/osm/bbbike/MexicoCity/MexicoCity.osm.pbf"

GTFS_BLANK_NUMERIC_DEFAULTS = {
    # R5 is stricter than many GTFS consumers and rejects blank numeric fields
    # even when GTFS treats them as optional. Keep the original ZIP untouched and
    # route against a small sanitized copy.
    "frequencies.txt": {
        "exact_times": "0",
    },
    "trips.txt": {
        "direction_id": "0",
    },
}

GTFS_INTEGER_FIELDS = {
    "frequencies.txt": {"exact_times"},
    "trips.txt": {"direction_id"},
}

OUTPUT_COLUMNS = [
    "area_id",
    "area_name",
    "time_work_transit_min",
    "time_work_transit_p75_min",
    "routed_successfully",
    "transit_commute_source",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute schedule-aware transit commute times with r5py."
    )
    parser.add_argument(
        "--area-unit",
        choices=["postal_code", "colonia"],
        default="postal_code",
        help="Processed area unit to route from.",
    )
    parser.add_argument(
        "--service-date",
        type=parse_iso_date,
        default=parse_iso_date(DEFAULT_SERVICE_DATE),
        help=f"GTFS service date to route on. Defaults to {DEFAULT_SERVICE_DATE}.",
    )
    parser.add_argument(
        "--departure-time",
        type=parse_hhmm_time,
        default=parse_hhmm_time(DEFAULT_DEPARTURE_TIME),
        help=f"Start of the commute departure window. Defaults to {DEFAULT_DEPARTURE_TIME}.",
    )
    parser.add_argument(
        "--departure-window-minutes",
        type=positive_int,
        default=DEFAULT_DEPARTURE_WINDOW_MINUTES,
        help=(
            "Minutes after --departure-time to sample departures over. "
            f"Defaults to {DEFAULT_DEPARTURE_WINDOW_MINUTES}."
        ),
    )
    parser.add_argument(
        "--max-time-minutes",
        type=positive_int,
        default=DEFAULT_MAX_TIME_MINUTES,
        help=f"Maximum routed trip duration. Defaults to {DEFAULT_MAX_TIME_MINUTES}.",
    )
    parser.add_argument(
        "--gtfs-zip",
        type=Path,
        default=DEFAULT_GTFS_ZIP,
        help=f"Path to the CDMX GTFS ZIP. Defaults to {DEFAULT_GTFS_ZIP}.",
    )
    parser.add_argument(
        "--osm-pbf",
        type=Path,
        default=DEFAULT_OSM_PBF,
        help=f"Path to the Mexico City OSM PBF. Defaults to {DEFAULT_OSM_PBF}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional CSV output path.",
    )
    return parser.parse_args()


def parse_iso_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected YYYY-MM-DD") from exc


def parse_hhmm_time(value: str) -> dt.time:
    try:
        return dt.datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected HH:MM") from exc


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Expected a positive integer")
    return parsed


def sha1(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def sanitized_gtfs_path(gtfs_zip: Path) -> Path:
    return DATA_PROCESSED_R5PY / f"{gtfs_zip.stem}_r5py_sanitized.zip"


def read_zip_csv(source: zipfile.ZipFile, filename: str) -> list[dict[str, str]]:
    with source.open(filename) as handle:
        reader = csv.DictReader(line.decode("utf-8-sig") for line in handle)
        return [dict(row) for row in reader]


def missing_route_agencies(source: zipfile.ZipFile) -> list[str]:
    agency_ids = {
        row.get("agency_id", "").strip()
        for row in read_zip_csv(source, "agency.txt")
        if row.get("agency_id", "").strip()
    }
    route_agency_ids = {
        row.get("agency_id", "").strip()
        for row in read_zip_csv(source, "routes.txt")
        if row.get("agency_id", "").strip()
    }
    return sorted(route_agency_ids - agency_ids)


def append_missing_agencies(text: str, agency_ids: list[str]) -> tuple[str, int]:
    if not agency_ids:
        return text, 0
    input_buffer = io.StringIO(text)
    reader = csv.DictReader(input_buffer)
    if not reader.fieldnames:
        return text, 0

    output_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        output_buffer,
        fieldnames=reader.fieldnames,
        lineterminator="\n",
    )
    writer.writeheader()
    for row in reader:
        writer.writerow(row)
    for agency_id in agency_ids:
        row = {field: "" for field in reader.fieldnames}
        row.update(
            {
                "agency_id": agency_id,
                "agency_name": agency_id,
                "agency_url": "https://semovi.cdmx.gob.mx/",
                "agency_timezone": "America/Mexico_City",
                "agency_lang": "ES",
            }
        )
        writer.writerow(row)
    return output_buffer.getvalue(), len(agency_ids)


def normalize_gtfs_numeric_value(
    value: object,
    *,
    blank_default: str,
    integer: bool,
) -> tuple[str, bool]:
    text = str(value or "").strip()
    if not text:
        return blank_default, True
    if integer:
        try:
            numeric = float(text)
        except ValueError:
            return text, False
        if math.isfinite(numeric) and numeric.is_integer():
            normalized = str(int(numeric))
            return normalized, normalized != text
    return text, False


def sanitize_gtfs_for_r5py(gtfs_zip: Path) -> tuple[Path, dict[str, Any]]:
    output_path = sanitized_gtfs_path(gtfs_zip)
    source_sha1 = sha1(gtfs_zip)
    DATA_PROCESSED_R5PY.mkdir(parents=True, exist_ok=True)
    replacements: dict[str, dict[str, int]] = {}
    with zipfile.ZipFile(gtfs_zip) as source, zipfile.ZipFile(
        output_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        missing_agencies = missing_route_agencies(source)
        for item in source.infolist():
            if item.filename == "agency.txt":
                text = source.read(item.filename).decode("utf-8-sig")
                text, agency_count = append_missing_agencies(text, missing_agencies)
                if agency_count:
                    replacements[item.filename] = {
                        "missing_route_agencies_added": agency_count
                    }
                target.writestr(item, text)
                continue

            defaults = GTFS_BLANK_NUMERIC_DEFAULTS.get(item.filename)
            if not defaults:
                target.writestr(item, source.read(item.filename))
                continue

            text = source.read(item.filename).decode("utf-8-sig")
            input_buffer = io.StringIO(text)
            reader = csv.DictReader(input_buffer)
            if not reader.fieldnames:
                target.writestr(item, text)
                continue

            output_buffer = io.StringIO(newline="")
            writer = csv.DictWriter(
                output_buffer,
                fieldnames=reader.fieldnames,
                lineterminator="\n",
            )
            writer.writeheader()
            file_replacements: dict[str, int] = {}
            integer_fields = GTFS_INTEGER_FIELDS.get(item.filename, set())
            for row in reader:
                for field, replacement in defaults.items():
                    if field not in row:
                        continue
                    normalized, changed = normalize_gtfs_numeric_value(
                        row[field],
                        blank_default=replacement,
                        integer=field in integer_fields,
                    )
                    if changed:
                        row[field] = normalized
                        file_replacements[field] = file_replacements.get(field, 0) + 1
                writer.writerow(row)
            replacements[item.filename] = file_replacements
            target.writestr(item, output_buffer.getvalue())

    return output_path, {
        "sanitized": True,
        "input_zip": relative(gtfs_zip),
        "input_sha1": source_sha1,
        "blank_numeric_fields_fixed": replacements,
    }


def load_origins(area_unit: str) -> gpd.GeoDataFrame:
    path = DATA_PROCESSED / f"scores_{area_unit}.geojson"
    if not path.exists():
        raise FileNotFoundError(f"Missing processed score GeoJSON: {path}")

    areas = gpd.read_file(path)
    required = {"area_id", "area_name", "centroid_lat", "centroid_lon"}
    missing = sorted(required - set(areas.columns))
    if missing:
        raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")

    origins = areas[["area_id", "area_name", "centroid_lat", "centroid_lon"]].copy()
    origins["id"] = origins["area_id"].fillna("").astype(str)
    origins["area_name"] = origins["area_name"].fillna(origins["id"]).astype(str)
    origins["centroid_lat"] = pd.to_numeric(origins["centroid_lat"], errors="coerce")
    origins["centroid_lon"] = pd.to_numeric(origins["centroid_lon"], errors="coerce")
    origins = origins.dropna(subset=["id", "centroid_lat", "centroid_lon"])

    gdf = gpd.GeoDataFrame(
        origins,
        geometry=gpd.points_from_xy(origins["centroid_lon"], origins["centroid_lat"]),
        crs=WGS84_CRS,
    )
    if gdf.empty:
        raise ValueError(f"{path} did not contain any routable origins")
    return gdf[["id", "area_id", "area_name", "geometry"]]


def load_destination() -> gpd.GeoDataFrame:
    path = DATA_CONFIG / "places.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing places config: {path}")
    places = json.loads(path.read_text(encoding="utf-8"))
    workplace = places.get("workplace", {})
    latitude = workplace.get("latitude")
    longitude = workplace.get("longitude")
    if latitude is None or longitude is None:
        raise ValueError(f"{path} does not define workplace.latitude and longitude")

    df = pd.DataFrame(
        [
            {
                "id": "workplace",
                "name": str(workplace.get("name") or "Configured workplace"),
                "latitude": float(latitude),
                "longitude": float(longitude),
            }
        ]
    )
    return gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
        crs=WGS84_CRS,
    )[["id", "name", "geometry"]]


def failure_rows(origins: gpd.GeoDataFrame) -> list[dict[str, Any]]:
    return [
        {
            "area_id": origin.area_id,
            "area_name": origin.area_name,
            "time_work_transit_min": None,
            "time_work_transit_p75_min": None,
            "routed_successfully": False,
            "transit_commute_source": R5PY_SOURCE,
        }
        for origin in origins.itertuples(index=False)
    ]


def import_r5py() -> tuple[Any, Any, Any]:
    import r5py
    from r5py import TransportMode, TransportNetwork

    travel_time_matrix = getattr(
        r5py,
        "TravelTimeMatrixComputer",
        getattr(r5py, "TravelTimeMatrix", None),
    )
    if travel_time_matrix is None:
        raise ImportError("This r5py install exposes neither TravelTimeMatrixComputer nor TravelTimeMatrix")
    return r5py, TransportMode, TransportNetwork


def compute_matrix(
    *,
    travel_time_matrix: Any,
    transport_mode: Any,
    network: Any,
    origins: gpd.GeoDataFrame,
    destination: gpd.GeoDataFrame,
    departure: dt.datetime,
    departure_window_minutes: int,
    max_time_minutes: int,
) -> pd.DataFrame:
    matrix = travel_time_matrix(
        network,
        origins=origins,
        destinations=destination,
        departure=departure,
        departure_time_window=dt.timedelta(minutes=departure_window_minutes),
        percentiles=[50, 75],
        transport_modes=[transport_mode.TRANSIT],
        access_modes=[transport_mode.WALK],
        egress_modes=[transport_mode.WALK],
        max_time=dt.timedelta(minutes=max_time_minutes),
        max_time_walking=dt.timedelta(minutes=max_time_minutes),
        speed_walking=4.8,
        snap_to_network=True,
    )
    if hasattr(matrix, "compute_travel_times"):
        matrix = matrix.compute_travel_times()
    elif hasattr(matrix, "compute"):
        matrix = matrix.compute()

    return pd.DataFrame(matrix)


def matrix_times_by_origin(
    frame: pd.DataFrame,
    *,
    max_time_minutes: int,
) -> dict[str, tuple[float | None, float | None]]:
    if frame.empty:
        return {}

    origin_column = next(
        (column for column in ["from_id", "origin_id", "id"] if column in frame.columns),
        None,
    )
    if origin_column is None:
        raise ValueError(
            "r5py matrix output did not include an origin id column. "
            f"Columns: {', '.join(frame.columns)}"
        )

    median_column = (
        "travel_time_p50" if "travel_time_p50" in frame.columns else "travel_time"
    )
    if median_column not in frame.columns:
        raise ValueError(
            "r5py matrix output did not include a travel time column. "
            f"Columns: {', '.join(frame.columns)}"
        )

    result: dict[str, tuple[float | None, float | None]] = {}
    for row in frame.itertuples(index=False):
        row_dict = row._asdict()
        origin_id = str(row_dict.get(origin_column) or "")
        median = value_or_none(row_dict.get(median_column))
        p75 = value_or_none(row_dict.get("travel_time_p75"))
        # Keep long-but-finite trips. r5py may return trips above max_time when
        # the departure window contributes additional waiting time; only discard
        # sentinel-like values that are clearly not real commute minutes.
        if median is not None and median >= 10_000:
            median = None
        if p75 is not None and p75 >= 10_000:
            p75 = None
        if median is not None:
            result[origin_id] = (median, p75)
    return result


def value_or_none(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return round(numeric, 1)


def write_outputs(
    *,
    rows: list[dict[str, Any]],
    output_path: Path,
    metadata_path: Path,
    metadata: dict[str, Any],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=OUTPUT_COLUMNS).to_csv(output_path, index=False)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def print_summary(rows: list[dict[str, Any]]) -> None:
    frame = pd.DataFrame(rows)
    routed = frame[frame["routed_successfully"] == True]  # noqa: E712
    failed = len(frame) - len(routed)
    median_time = value_or_none(routed["time_work_transit_min"].median()) if not routed.empty else None
    mean_time = value_or_none(routed["time_work_transit_min"].mean()) if not routed.empty else None
    print(f"Total origins: {len(frame)}")
    print(f"Successfully routed: {len(routed)}")
    print(f"Failed: {failed}")
    print(f"Median time: {median_time if median_time is not None else 'n/a'}")
    print(f"Mean time: {mean_time if mean_time is not None else 'n/a'}")


def main() -> None:
    started_at = time.monotonic()
    args = parse_args()
    output_path = args.output or DATA_PROCESSED / f"transit_commute_r5py_{args.area_unit}.csv"
    metadata_path = output_path.with_suffix(".metadata.json")

    origins = load_origins(args.area_unit)
    destination = load_destination()
    departure = dt.datetime.combine(args.service_date, args.departure_time)
    global_error: str | None = None
    global_traceback: str | None = None
    r5py_version: str | None = None
    routing_gtfs_zip = args.gtfs_zip
    gtfs_sanitizer_info: dict[str, Any] = {"sanitized": False}
    rows: list[dict[str, Any]]

    try:
        if not args.gtfs_zip.exists():
            raise FileNotFoundError(f"Missing GTFS ZIP: {args.gtfs_zip}")
        if not args.osm_pbf.exists():
            raise FileNotFoundError(f"Missing OSM PBF: {args.osm_pbf}")
        routing_gtfs_zip, gtfs_sanitizer_info = sanitize_gtfs_for_r5py(args.gtfs_zip)

        r5py, transport_mode, transport_network = import_r5py()
        r5py_version = getattr(r5py, "__version__", None)
        travel_time_matrix = getattr(
            r5py,
            "TravelTimeMatrixComputer",
            getattr(r5py, "TravelTimeMatrix"),
        )

        print(f"Building r5py transport network from {args.osm_pbf} and {routing_gtfs_zip}")
        network = transport_network(args.osm_pbf, [routing_gtfs_zip])
        print("Transport network built. Routing origins...")

        matrix = compute_matrix(
            travel_time_matrix=travel_time_matrix,
            transport_mode=transport_mode,
            network=network,
            origins=origins[["id", "geometry"]],
            destination=destination[["id", "geometry"]],
            departure=departure,
            departure_window_minutes=args.departure_window_minutes,
            max_time_minutes=args.max_time_minutes,
        )
        print(f"r5py matrix returned {len(matrix)} origin/destination rows")
        times_by_origin = matrix_times_by_origin(
            matrix,
            max_time_minutes=args.max_time_minutes,
        )

        rows = []
        for origin_record in origins.itertuples(index=False):
            median, p75 = times_by_origin.get(origin_record.id, (None, None))
            routed = median is not None
            rows.append(
                {
                    "area_id": origin_record.area_id,
                    "area_name": origin_record.area_name,
                    "time_work_transit_min": median,
                    "time_work_transit_p75_min": p75,
                    "routed_successfully": routed,
                    "transit_commute_source": R5PY_SOURCE,
                }
            )

    except Exception as exc:  # noqa: BLE001 - write all-failed output for diagnosability.
        global_error = f"{type(exc).__name__}: {exc}"
        global_traceback = traceback.format_exc()
        print(f"ERROR: r5py routing setup failed: {global_error}")
        rows = failure_rows(origins)

    routed_count = sum(1 for row in rows if row["routed_successfully"])
    failed_count = len(rows) - routed_count
    routed_times = [
        row["time_work_transit_min"]
        for row in rows
        if row["routed_successfully"] and row["time_work_transit_min"] is not None
    ]
    elapsed_seconds = round(time.monotonic() - started_at, 1)
    metadata = {
        "engine": "r5py",
        "source": R5PY_SOURCE,
        "area_unit": args.area_unit,
        "service_date": args.service_date.isoformat(),
        "departure_time": args.departure_time.strftime("%H:%M"),
        "departure_window_minutes": args.departure_window_minutes,
        "max_time_minutes": args.max_time_minutes,
        "gtfs_zip": relative(routing_gtfs_zip),
        "gtfs_sha1": sha1(routing_gtfs_zip),
        "gtfs_sanitizer": gtfs_sanitizer_info,
        "osm_pbf": relative(args.osm_pbf),
        "osm_source": OSM_SOURCE_URL,
        "osm_sha1": sha1(args.osm_pbf),
        "java_home": os.environ.get("JAVA_HOME"),
        "r5py_version": r5py_version,
        "total_origins": len(rows),
        "routed_count": routed_count,
        "failed_count": failed_count,
        "coverage_percent": round((routed_count / len(rows)) * 100, 1) if rows else 0.0,
        "median_time_min": value_or_none(pd.Series(routed_times).median()) if routed_times else None,
        "mean_time_min": value_or_none(pd.Series(routed_times).mean()) if routed_times else None,
        "runtime_seconds": elapsed_seconds,
        "global_error": global_error,
        "global_traceback": global_traceback,
        "output_csv": relative(output_path),
    }

    write_outputs(
        rows=rows,
        output_path=output_path,
        metadata_path=metadata_path,
        metadata=metadata,
    )
    print(f"Wrote {output_path}")
    print(f"Wrote {metadata_path}")
    print_summary(rows)
    if global_error:
        print(f"Global r5py error: {global_error}")


if __name__ == "__main__":
    main()
