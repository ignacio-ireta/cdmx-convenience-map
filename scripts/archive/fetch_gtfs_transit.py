from __future__ import annotations

import argparse
import csv
import zipfile

from common import CDMX_BBOX, DATA_PROCESSED, DATA_RAW, download, write_csv


GTFS_URL = (
    "https://datos.cdmx.gob.mx/dataset/75538d96-3ade-4bc5-ae7d-d85595e4522d/"
    "resource/32ed1b6b-41cd-49b3-b7f0-b57acb0eb819/download/gtfs.zip"
)


def in_cdmx_bbox(lat: float, lon: float) -> bool:
    return (
        CDMX_BBOX["south"] <= lat <= CDMX_BBOX["north"]
        and CDMX_BBOX["west"] <= lon <= CDMX_BBOX["east"]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Download CDMX GTFS and extract stops.")
    parser.add_argument("--force", action="store_true", help="Redownload even if cached.")
    args = parser.parse_args()

    zip_path = DATA_RAW / "gtfs.zip"
    download(GTFS_URL, zip_path, force=args.force, timeout=180)

    rows: list[dict] = []
    with zipfile.ZipFile(zip_path) as archive:
        with archive.open("stops.txt") as stops_file:
            decoded = (line.decode("utf-8-sig") for line in stops_file)
            reader = csv.DictReader(decoded)
            for raw in reader:
                try:
                    lat = float(raw["stop_lat"])
                    lon = float(raw["stop_lon"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not in_cdmx_bbox(lat, lon):
                    continue
                rows.append(
                    {
                        "id": raw.get("stop_id", ""),
                        "name": raw.get("stop_name", "") or raw.get("stop_id", ""),
                        "latitude": lat,
                        "longitude": lon,
                        "source": "cdmx_gtfs",
                    }
                )

    if not rows:
        raise ValueError("No GTFS stops were extracted from stops.txt")
    write_csv(
        DATA_PROCESSED / "transit_stops.csv",
        rows,
        ["id", "name", "latitude", "longitude", "source"],
    )
    print(f"Extracted {len(rows)} transit stops")


if __name__ == "__main__":
    main()

