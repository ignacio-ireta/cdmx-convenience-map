"""GeoJSON writer."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd


def write_geojson(output: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output.to_file(path, driver="GeoJSON")
    print(f"Wrote {path}")
