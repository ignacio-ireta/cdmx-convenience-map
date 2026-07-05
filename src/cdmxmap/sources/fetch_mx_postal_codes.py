from __future__ import annotations

import argparse
import os
import urllib.request
from pathlib import Path

import geopandas as gpd

from .io import DATA_RAW, USER_AGENT, city_bbox, city_data_dir, load_city_profile


def _state_source_url(profile: dict, city: str) -> str:
    url = (profile.get("sources") or {}).get("postal_codes")
    if not url:
        raise ValueError(
            f"City profile '{city}' must declare sources.postal_codes "
            "(the state GeoJSON URL of postal-code polygons)"
        )
    return str(url)


def _postal_range(profile: dict, city: str) -> tuple[int, int]:
    """Inclusive ``[min, max]`` postal-code range that defines the municipality."""
    values = profile.get("postal_code_range")
    if not values or len(values) != 2:
        raise ValueError(
            f"City profile '{city}' must declare postal_code_range [min, max] "
            "to select its municipality from the state file"
        )
    low, high = int(values[0]), int(values[1])
    return (low, high) if low <= high else (high, low)


def _cached_state_file(url: str) -> Path:
    """Cache the state-wide GeoJSON once under a shared (gitignored) raw path.

    The whole state is downloaded, then every municipality trims it locally, so a
    corrupt or interrupted response can never poison later runs: the body is
    written to a temp path and only promoted after it parses.
    """
    filename = f"mx_{os.path.basename(url)}"
    target = DATA_RAW / filename
    if target.exists() and target.stat().st_size > 0:
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = response.read()

    tmp_path = target.with_suffix(target.suffix + ".tmp")
    tmp_path.write_bytes(payload)
    try:
        gpd.read_file(tmp_path)  # fails loudly on an error/HTML/truncated body
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    os.replace(tmp_path, target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Mexican postal-code area polygons for one municipality."
    )
    parser.add_argument("--city", required=True)
    args = parser.parse_args()

    profile = load_city_profile(args.city)
    url = _state_source_url(profile, args.city)
    low, high = _postal_range(profile, args.city)
    raw_dir = city_data_dir(DATA_RAW, args.city)
    raw_dir.mkdir(parents=True, exist_ok=True)

    areas = gpd.read_file(_cached_state_file(url)).to_crs("EPSG:4326")
    bbox = city_bbox(args.city)
    areas = areas.cx[bbox["west"] : bbox["east"], bbox["south"] : bbox["north"]].copy()
    codes = areas["d_codigo"].astype(int)
    areas = areas[(codes >= low) & (codes <= high)].copy()
    if areas.empty:
        raise ValueError(
            f"State file returned no postal-code areas for {args.city} "
            f"in range {low}-{high} within its bbox"
        )
    target = raw_dir / "postal_codes.geojson"
    areas.to_file(target, driver="GeoJSON")
    print(f"Wrote {len(areas)} {args.city} postal-code areas ({low}-{high}) to {target}")


if __name__ == "__main__":
    main()
