"""GeoJSON writer with atomic replace (standards §J: never leave a half file)."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

import geopandas as gpd

logger = logging.getLogger(__name__)


def write_geojson(output: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # GDAL's GeoJSON driver embeds a layer "name" derived from the file's stem,
    # so the temp file must share the final basename (only the directory differs)
    # to keep the bytes identical. A sibling temp dir keeps it on one filesystem,
    # so os.replace stays atomic.
    tmp_dir = Path(tempfile.mkdtemp(dir=path.parent, prefix=".tmp-geojson-"))
    try:
        tmp_path = tmp_dir / path.name
        output.to_file(tmp_path, driver="GeoJSON")
        os.replace(tmp_path, path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    logger.info("Wrote %s", path)
