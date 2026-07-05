from __future__ import annotations

import argparse
import os
import urllib.parse
import urllib.request

import geopandas as gpd

from .io import DATA_RAW, USER_AGENT, city_bbox, city_data_dir, load_city_profile

WFS_URL = "https://wfs.geonorge.no/skwms1/wfs.postnummeromrader"
# The Kartverket WFS only serves the whole national dataset, so cache it once at a
# country-shared path (not per city). Every Norwegian city trims it locally, so
# oslo/bergen/trondheim/stavanger share a single ~26 MB download. Gitignored.
NATIONAL_GML = DATA_RAW / "no_postnummeromrader.gml"


def _municipality_code(city: str) -> str:
    """Return the zero-padded Kartverket kommune number for the city profile."""
    profile = load_city_profile(city)
    code = profile.get("municipality_code")
    if not code:
        raise ValueError(
            f"City profile '{city}' must declare municipality_code (Kartverket kommune number)"
        )
    return str(code).zfill(4)


def _load_national_areas() -> gpd.GeoDataFrame:
    """Load the national postal-area dataset, downloading it once if not cached.

    The download is written to a temp path and only promoted to the cache after it
    parses, so an interrupted or error (HTTP-200 exception page) response can never
    poison later runs.
    """
    if NATIONAL_GML.exists() and NATIONAL_GML.stat().st_size > 0:
        return gpd.read_file(NATIONAL_GML)

    NATIONAL_GML.parent.mkdir(parents=True, exist_ok=True)
    params = urllib.parse.urlencode(
        {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": "app:Postnummerområde",
        }
    )
    request = urllib.request.Request(f"{WFS_URL}?{params}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = response.read()

    tmp_path = NATIONAL_GML.with_suffix(".gml.tmp")
    tmp_path.write_bytes(payload)
    try:
        areas = gpd.read_file(tmp_path)  # fails loudly on an error/HTML/truncated body
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    os.replace(tmp_path, NATIONAL_GML)
    return areas


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch official Norwegian postal-code areas for one municipality."
    )
    parser.add_argument("--city", required=True)
    args = parser.parse_args()

    kommune_code = _municipality_code(args.city)
    raw_dir = city_data_dir(DATA_RAW, args.city)
    raw_dir.mkdir(parents=True, exist_ok=True)

    areas = _load_national_areas().to_crs("EPSG:4326")
    bbox = city_bbox(args.city)
    areas = areas.cx[bbox["west"] : bbox["east"], bbox["south"] : bbox["north"]].copy()
    areas = areas[areas["kommune"].astype(str).str.zfill(4).eq(kommune_code)].copy()
    if areas.empty:
        raise ValueError(
            f"Kartverket returned no postal-code areas for {args.city} (kommune {kommune_code})"
        )
    target = raw_dir / "postal_codes.geojson"
    areas.to_file(target, driver="GeoJSON")
    print(f"Wrote {len(areas)} official {args.city} postal-code areas to {target}")


if __name__ == "__main__":
    main()
