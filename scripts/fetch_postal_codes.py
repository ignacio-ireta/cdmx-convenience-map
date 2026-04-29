from __future__ import annotations

import argparse
import json

from common import DATA_RAW, download


POSTAL_GEOJSON_URL = (
    "https://datos.cdmx.gob.mx/dataset/7abff432-81a0-4956-8691-0865e2722423/"
    "resource/95482697-af9d-440a-a65b-4d289e5fcd5c/download/correos-postales.json"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download CDMX postal-code GeoJSON.")
    parser.add_argument("--force", action="store_true", help="Redownload even if cached.")
    args = parser.parse_args()

    target = DATA_RAW / "correos-postales.json"
    download(POSTAL_GEOJSON_URL, target, force=args.force)

    with target.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("type") != "FeatureCollection" or not payload.get("features"):
        raise ValueError(f"{target} is not a populated GeoJSON FeatureCollection")
    print(f"Validated {len(payload['features'])} postal-code features")


if __name__ == "__main__":
    main()

