from __future__ import annotations

import argparse
import urllib.parse
import urllib.request

import geopandas as gpd

from .io import DATA_RAW, USER_AGENT, city_bbox, city_data_dir

WFS_URL = "https://wfs.geonorge.no/skwms1/wfs.postnummeromrader"


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch official Oslo postal-code areas.")
    parser.add_argument("--city", required=True)
    args = parser.parse_args()
    if args.city != "oslo":
        raise ValueError("This fetcher only supports the Oslo profile")

    params = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": "app:Postnummerområde",
        }
    )
    request = urllib.request.Request(f"{WFS_URL}?{params}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = response.read()

    raw_dir = city_data_dir(DATA_RAW, args.city)
    raw_dir.mkdir(parents=True, exist_ok=True)
    gml_path = raw_dir / "postnummeromrader.gml"
    gml_path.write_bytes(payload)
    areas = gpd.read_file(gml_path).to_crs("EPSG:4326")
    bbox = city_bbox(args.city)
    areas = areas.cx[bbox["west"] : bbox["east"], bbox["south"] : bbox["north"]].copy()
    areas = areas[areas["kommune"].astype(str).str.zfill(4).eq("0301")].copy()
    if areas.empty:
        raise ValueError("Kartverket returned no Oslo postal-code areas")
    target = raw_dir / "postal_codes.geojson"
    areas.to_file(target, driver="GeoJSON")
    print(f"Wrote {len(areas)} official Oslo postal-code areas to {target}")


if __name__ == "__main__":
    main()
