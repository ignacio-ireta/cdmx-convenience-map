from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ZIP_PATH = ROOT / "data" / "archive" / "gtfs_legacy" / "gtfs.zip"
DEFAULT_DOWNLOAD_PATH = ROOT / "data" / "raw" / "gtfs" / "cdmx_gtfs.zip"
DEFAULT_GTFS_URL = (
    "https://datos.cdmx.gob.mx/dataset/75538d96-3ade-4bc5-ae7d-d85595e4522d/"
    "resource/32ed1b6b-41cd-49b3-b7f0-b57acb0eb819/download/gtfs-2.zip"
)

REQUIRED_FILES = [
    "agency.txt",
    "stops.txt",
    "routes.txt",
    "trips.txt",
    "stop_times.txt",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the CDMX static GTFS ZIP for routing experiments."
    )
    parser.add_argument(
        "zip_path",
        nargs="?",
        type=Path,
        default=DEFAULT_ZIP_PATH,
        help=f"GTFS ZIP to inspect. Defaults to {DEFAULT_ZIP_PATH}.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the configured GTFS URL before validation.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_GTFS_URL,
        help="GTFS ZIP URL to use with --download.",
    )
    parser.add_argument(
        "--download-to",
        type=Path,
        default=DEFAULT_DOWNLOAD_PATH,
        help=f"Download target used with --download. Defaults to {DEFAULT_DOWNLOAD_PATH}.",
    )
    parser.add_argument(
        "--as-of",
        type=_parse_iso_date,
        default=dt.date.today(),
        help="Date used for freshness checks, in YYYY-MM-DD format.",
    )
    return parser.parse_args()


def _parse_iso_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected YYYY-MM-DD") from exc


def download_gtfs(url: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "cdmx-transit-routing-spike/0.1"},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        target.write_bytes(response.read())
    return target


def read_rows(archive: zipfile.ZipFile, name: str) -> tuple[list[str], list[dict[str, str]]]:
    with archive.open(name) as handle:
        text = io.TextIOWrapper(handle, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
        return list(reader.fieldnames or []), list(reader)


def parse_gtfs_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    cleaned = value.strip()
    if len(cleaned) != 8 or not cleaned.isdigit():
        return None
    return dt.datetime.strptime(cleaned, "%Y%m%d").date()


def date_coverage(
    names: set[str],
    rows_by_file: dict[str, list[dict[str, str]]],
) -> dict[str, Any]:
    dates: list[dt.date] = []
    if "calendar.txt" in names:
        for row in rows_by_file["calendar.txt"]:
            for key in ("start_date", "end_date"):
                parsed = parse_gtfs_date(row.get(key))
                if parsed:
                    dates.append(parsed)
    if "calendar_dates.txt" in names:
        for row in rows_by_file["calendar_dates.txt"]:
            parsed = parse_gtfs_date(row.get("date"))
            if parsed:
                dates.append(parsed)

    if not dates:
        return {"start": None, "end": None}
    return {"start": min(dates).isoformat(), "end": max(dates).isoformat()}


def validate(path: Path, as_of: dt.date) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        text_files = sorted(name for name in names if name.endswith(".txt"))
        rows_by_file: dict[str, list[dict[str, str]]] = {}
        file_summaries: dict[str, dict[str, Any]] = {}

        for name in text_files:
            header, rows = read_rows(archive, name)
            rows_by_file[name] = rows
            file_summaries[name] = {"rows": len(rows), "columns": header}

        missing_required = [name for name in REQUIRED_FILES if name not in names]
        has_service_calendar = "calendar.txt" in names or "calendar_dates.txt" in names
        coverage = date_coverage(names, rows_by_file)
        coverage_end = (
            dt.date.fromisoformat(coverage["end"]) if coverage.get("end") else None
        )

        route_type_counts = Counter(
            row.get("route_type", "") for row in rows_by_file.get("routes.txt", [])
        )
        route_agency_counts = Counter(
            row.get("agency_id", "") for row in rows_by_file.get("routes.txt", [])
        )
        agencies = [
            row.get("agency_name") or row.get("agency_id") or ""
            for row in rows_by_file.get("agency.txt", [])
        ]

    return {
        "zip_path": str(path),
        "zip_size_bytes": path.stat().st_size,
        "missing_required_files": missing_required,
        "has_calendar_or_calendar_dates": has_service_calendar,
        "has_frequencies": "frequencies.txt" in names,
        "files": file_summaries,
        "date_coverage": coverage,
        "as_of": as_of.isoformat(),
        "covers_as_of_date": bool(
            coverage_end is not None and coverage_end >= as_of
        ),
        "agencies": agencies,
        "route_type_counts": dict(sorted(route_type_counts.items())),
        "route_agency_counts": dict(route_agency_counts.most_common()),
    }


def main() -> None:
    args = parse_args()
    zip_path = args.zip_path
    if args.download:
        zip_path = download_gtfs(args.url, args.download_to)
    report = validate(zip_path, args.as_of)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
