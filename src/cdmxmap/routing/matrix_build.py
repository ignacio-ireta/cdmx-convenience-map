"""Build the dynamic-workplace area-to-area routed travel-time matrix.

For each area unit and mode, route every representative point to every other and
serialize the N×N matrix to the destination-major binary the frontend reads via
HTTP Range (see ``matrix_codec`` and ``docs/road-routing.md``). Outputs go to the
gitignored processed dir and are copied to ``frontend/public/data`` (committed,
served on Pages). A hash in the filename + sidecar busts stale CDN caches and
lets an unchanged rebuild skip work.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from cdmxmap.models import AreaConfig
from cdmxmap.routing.base import Router
from cdmxmap.routing.matrix_codec import build_matrix_index, encode_matrix
from cdmxmap.scoring.areas import area_representative_latlon

logger = logging.getLogger(__name__)


def _content_hash(inputs_hash: str, area_ids: list[str]) -> str:
    payload = "|".join([inputs_hash, str(len(area_ids)), *area_ids])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def build_area_matrix(
    *,
    config: AreaConfig,
    input_path: Path,
    router: Router,
    modes: tuple[str, ...],
    output_dir: Path,
    public_dir: Path,
    osm_source: str | None = None,
    osm_sha: str | None = None,
    osm_date: str | None = None,
    force: bool = False,
) -> dict:
    """Route the full N×N matrix per mode and write binary + index for one area unit.

    Returns a summary dict (counts, sizes, paths). When an up-to-date matrix already
    exists (same content hash) the build is skipped unless ``force``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)

    area_ids, latlon = area_representative_latlon(input_path, config)
    n = len(area_ids)
    inputs_hash = "|".join([router.engine, router.version, str(osm_source or "")])
    content_hash = _content_hash(inputs_hash, area_ids)
    index_path = output_dir / f"routing_matrix_{config.area_unit}_index.json"

    if not force and _is_current(index_path, content_hash, modes, output_dir, public_dir):
        logger.info("matrix %s up-to-date (hash %s); skipping", config.area_unit, content_hash)
        return {"area_unit": config.area_unit, "skipped": True, "n": n}

    mode_files: dict[str, str] = {}
    sizes: dict[str, int] = {}
    for mode in modes:
        logger.info("routing %s matrix mode=%s n=%d (%d cells)", config.area_unit, mode, n, n * n)
        result = router.matrix(latlon, latlon, mode)
        payload = encode_matrix(result.minutes)
        filename = f"routing_matrix_{config.area_unit}_{mode}_{content_hash}.bin"
        (output_dir / filename).write_bytes(payload)
        shutil.copyfile(output_dir / filename, public_dir / filename)
        mode_files[mode] = filename
        sizes[mode] = len(payload)

    index = build_matrix_index(
        area_unit=config.area_unit,
        area_ids=area_ids,
        mode_files=mode_files,
        engine=router.engine,
        version=router.version,
        profiles={mode: router.profile(mode) for mode in modes},
        inputs_hash=content_hash,
        osm_source=osm_source,
        osm_sha=osm_sha,
        osm_date=osm_date,
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
    )
    index_text = json.dumps(index, indent=2)
    index_path.write_text(index_text, encoding="utf-8")
    (public_dir / index_path.name).write_text(index_text, encoding="utf-8")

    logger.info(
        "wrote matrix %s (%d modes, %d bytes total)",
        config.area_unit,
        len(modes),
        sum(sizes.values()),
    )
    return {
        "area_unit": config.area_unit,
        "skipped": False,
        "n": n,
        "modes": list(modes),
        "bytes": sizes,
        "content_hash": content_hash,
        "index": str(index_path),
    }


def _is_current(
    index_path: Path,
    content_hash: str,
    modes: tuple[str, ...],
    output_dir: Path,
    public_dir: Path,
) -> bool:
    if not index_path.exists():
        return False
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if index.get("inputs_hash") != content_hash:
        return False
    for mode in modes:
        filename = index.get("mode_files", {}).get(mode)
        if not filename:
            return False
        if not (output_dir / filename).exists() or not (public_dir / filename).exists():
            return False
    return True
