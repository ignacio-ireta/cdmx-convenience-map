from __future__ import annotations

import argparse
import json
import urllib.request

from common import DATA_RAW, USER_AGENT, ensure_dirs


COLONIAS_GEOJSON_URL = (
    "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
    "georef-mexico-colonia/exports/geojson"
    "?lang=en&timezone=America%2FMexico_City"
)


def first_value(value: object) -> str:
    if isinstance(value, list):
        return str(value[0]).strip() if value else ""
    if value is None:
        return ""
    return str(value).strip()


def normalized_feature(feature: dict) -> dict:
    properties = feature.get("properties") or {}
    state_code = first_value(properties.get("sta_code"))
    municipality_code = first_value(properties.get("mun_code"))
    municipality_name = first_value(properties.get("mun_name"))
    colonia_code = first_value(properties.get("col_code"))
    colonia_name = first_value(properties.get("col_name"))
    area_id = "-".join(
        part for part in [state_code, municipality_code, colonia_code] if part
    )

    return {
        "type": "Feature",
        "geometry": feature.get("geometry"),
        "properties": {
            "area_unit": "colonia",
            "area_id": area_id or colonia_name,
            "area_name": colonia_name,
            "display_name": colonia_name,
            "alcaldia": municipality_name,
            "colonia_name": colonia_name,
            "col_code": colonia_code,
            "mun_code": municipality_code,
            "mun_name": municipality_name,
            "sta_code": state_code,
            "sta_name": first_value(properties.get("sta_name")),
            "year": first_value(properties.get("year")),
            "source": "opendatasoft_georef_mexico_colonia",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download and normalize CDMX colonia polygons from Opendatasoft."
    )
    parser.add_argument("--force", action="store_true", help="Redownload even if cached.")
    args = parser.parse_args()

    ensure_dirs()
    target = DATA_RAW / "colonias.geojson"
    if target.exists() and not args.force:
        print(f"Using cached {target}")
        return

    print(f"Downloading {COLONIAS_GEOJSON_URL}")
    request = urllib.request.Request(
        COLONIAS_GEOJSON_URL,
        headers={
            "Accept": "application/geo+json, application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = json.loads(response.read().decode("utf-8"))

    features = [
        normalized_feature(feature)
        for feature in payload.get("features", [])
        if feature.get("geometry")
    ]
    if not features:
        raise ValueError("No colonia polygons were downloaded")

    normalized = {
        "type": "FeatureCollection",
        "name": "cdmx_colonias",
        "source": COLONIAS_GEOJSON_URL,
        "features": features,
    }
    target.write_text(json.dumps(normalized, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {target}")
    print(f"Validated {len(features)} colonia features")


if __name__ == "__main__":
    main()
