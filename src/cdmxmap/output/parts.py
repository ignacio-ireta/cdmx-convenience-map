"""Publish one scored GeoJSON as ordered part files plus a JSON index.

A colonia layer with thousands of features is larger than the repository's
10 MB pre-commit file limit (``check-added-large-files``), mostly because GeoJSON
repeats every property name in every feature. An area unit whose profile entry
sets ``public_part_max_bytes`` is therefore published to the frontend as
``<stem>.part-NN.geojson`` files, each a complete FeatureCollection no larger
than that budget, listed in order by ``<stem>_index.json``. The processed copy
under ``data/processed/`` stays a single file, and the parts' features in index
order are exactly its features.

Units without the setting keep the single public file, unchanged.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np

logger = logging.getLogger(__name__)

PARTS_INDEX_TYPE = "geojson_parts"
PARTS_INDEX_VERSION = 1
# Two digits keep the names sortable; 99 parts of even 1 MB is far past any layer here.
MAX_PARTS = 99


@dataclass(frozen=True)
class PublishedParts:
    index_path: Path
    part_paths: list[Path]


def parts_index_name(stem: str) -> str:
    return f"{stem}_index.json"


def part_name(stem: str, number: int) -> str:
    return f"{stem}.part-{number:02d}.geojson"


def _part_pattern(stem: str) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(stem)}\.part-\d{{2}}\.geojson")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def remove_geojson_parts(
    public_dir: Path, stem: str, *, keep: frozenset[str] = frozenset()
) -> None:
    """Delete ``stem``'s part files and index in ``public_dir``, except names in ``keep``."""
    pattern = _part_pattern(stem)
    index_name = parts_index_name(stem)
    if not public_dir.is_dir():
        return
    for path in public_dir.iterdir():
        if path.name in keep:
            continue
        if pattern.fullmatch(path.name) or path.name == index_name:
            path.unlink()
            logger.info("Removed stale %s", path)


def _write_candidate(
    output: gpd.GeoDataFrame, tmp_dir: Path, stem: str, count: int, max_bytes: int
) -> list[tuple[Path, int]] | None:
    """Write ``output`` as ``count`` contiguous parts; None if any part is over budget."""
    written: list[tuple[Path, int]] = []
    for number, positions in enumerate(np.array_split(np.arange(len(output)), count), start=1):
        path = tmp_dir / part_name(stem, number)
        # GDAL embeds the file stem as the layer "name", so each part is written
        # under its final basename (only the directory differs), as write_geojson does.
        output.iloc[positions].to_file(path, driver="GeoJSON")
        if path.stat().st_size > max_bytes:
            return None
        written.append((path, len(positions)))
    return written


def write_geojson_parts(
    output: gpd.GeoDataFrame,
    public_dir: Path,
    *,
    stem: str,
    area_unit: str,
    max_bytes: int,
    size_hint: int | None = None,
) -> PublishedParts:
    """Publish ``output`` as the fewest equal-count parts that each fit ``max_bytes``.

    ``size_hint`` (the single-file size, when already known) sets the first part
    count to try. The parts and index are staged in a temp dir beside the final
    files, moved into place parts first and index last, and then any part left by
    an earlier publish with more parts, and the single ``<stem>.geojson`` copy,
    are removed so the public directory holds exactly one form of the layer.
    """
    if max_bytes <= 0:
        raise ValueError(f"public_part_max_bytes must be positive, got {max_bytes}")
    if len(output) == 0:
        raise ValueError(f"Cannot publish {stem} as parts: it has no features")
    public_dir.mkdir(parents=True, exist_ok=True)
    count = max(1, math.ceil(size_hint / max_bytes)) if size_hint else 1

    tmp_dir = Path(tempfile.mkdtemp(dir=public_dir, prefix=".tmp-geojson-parts-"))
    try:
        while True:
            if count > min(len(output), MAX_PARTS):
                raise ValueError(
                    f"Cannot publish {stem} in parts of at most {max_bytes} bytes "
                    f"(tried up to {count - 1} parts)"
                )
            written = _write_candidate(output, tmp_dir, stem, count, max_bytes)
            if written is not None:
                break
            for leftover in tmp_dir.iterdir():
                leftover.unlink()
            count += 1

        index = {
            "type": PARTS_INDEX_TYPE,
            "version": PARTS_INDEX_VERSION,
            "area_unit": area_unit,
            "feature_count": int(len(output)),
            "max_part_bytes": int(max_bytes),
            "parts": [
                {
                    "path": path.name,
                    "feature_count": int(features),
                    "bytes": int(path.stat().st_size),
                    "sha256": _sha256(path),
                }
                for path, features in written
            ],
        }
        index_tmp = tmp_dir / parts_index_name(stem)
        index_tmp.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

        part_paths: list[Path] = []
        for path, _features in written:
            final = public_dir / path.name
            os.replace(path, final)
            part_paths.append(final)
        index_path = public_dir / index_tmp.name
        os.replace(index_tmp, index_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    remove_geojson_parts(
        public_dir, stem, keep=frozenset({index_path.name, *(path.name for path in part_paths)})
    )
    single = public_dir / f"{stem}.geojson"
    if single.exists():
        single.unlink()
        logger.info("Removed single-file copy %s (now published in parts)", single)
    logger.info("Wrote %s with %d parts under %d bytes", index_path, len(part_paths), max_bytes)
    return PublishedParts(index_path=index_path, part_paths=part_paths)
