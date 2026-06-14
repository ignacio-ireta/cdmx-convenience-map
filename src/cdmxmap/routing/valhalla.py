"""Valhalla road-routing adapter (in-process via the ``pyvalhalla`` wheel).

Valhalla was chosen over OSRM because one tile build serves driving, walking, and
biking (no per-profile graphs), it is pip-installable with prebuilt binaries (no
Docker/Java — works even on a Docker-less machine), and its ``sources_to_targets``
matrix action is the batch primitive the pipeline needs. See
``docs/road-routing.md`` for the full decision.

Free-flow only: results are labeled ``valhalla_free_flow`` and must never be
presented as live-traffic commute times.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from cdmxmap.errors import ConfigError
from cdmxmap.routing.base import (
    DEFAULT_PROFILES,
    VALHALLA_FREE_FLOW_SOURCE,
    LatLon,
    RouteMatrix,
)

# Valhalla matrix payloads count locations per request; keep chunks well under the
# (configurable) service limit. Sources are chunked; targets ride along per chunk.
DEFAULT_CHUNK_SIZE = 64


def _require_valhalla():
    """Import the pyvalhalla bindings lazily, with an actionable error."""
    try:
        import valhalla
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ConfigError(
            "Valhalla routing requires the optional 'routing' extra. Install it with "
            "`uv sync --extra routing` (pulls the pyvalhalla wheel), then build tiles "
            "(see docs/road-routing.md)."
        ) from exc
    return valhalla


def _valhalla_config(*, tile_dir: Path | None = None, tile_extract: Path | None = None) -> dict:
    """Build a sanitized Valhalla config dict pointing at a tile dir or tar extract.

    Bypasses pyvalhalla's ``get_config`` (broken in 3.7.0: it strict-resolves both
    paths and then KeyErrors on a missing ``logging`` key). We deep-copy the
    bundled default config, strip ``Optional`` sentinels, and set the tile source.
    """
    import copy

    from valhalla.valhalla_build_config import Optional
    from valhalla.valhalla_build_config import config as default_config

    def sanitize(node: dict) -> dict:
        for key in list(node):
            value = node[key]
            if isinstance(value, Optional):
                del node[key]
            elif isinstance(value, dict):
                sanitize(value)
        return node

    config = sanitize(copy.deepcopy(default_config))
    mjolnir = config.setdefault("mjolnir", {})
    mjolnir["tile_dir"] = str(tile_dir.resolve()) if tile_dir is not None else ""
    mjolnir["tile_extract"] = str(tile_extract.resolve()) if tile_extract is not None else ""
    mjolnir.setdefault("logging", {"type": ""})
    # Raise matrix limits so a large sources×targets chunk is accepted. Valhalla
    # caps `max_matrix_location_pairs` (default 2500) and `max_matrix_distance`.
    limits = config.setdefault("service_limits", {})
    for costing in DEFAULT_PROFILES.values():
        costing_limits = limits.setdefault(costing, {})
        costing_limits["max_matrix_location_pairs"] = 10_000_000
        costing_limits["max_matrix_distance"] = 5_000_000
    return config


def _load_actor(config_path: Path | None, tiles_dir: Path):
    """Build a Valhalla Actor from a config file or a built tileset/tar."""
    valhalla = _require_valhalla()

    if config_path is not None and config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        tile_extract = tiles_dir / "valhalla_tiles.tar"
        has_tiles = tiles_dir.exists() and any(tiles_dir.iterdir())
        if tile_extract.exists():
            config = _valhalla_config(tile_extract=tile_extract)
        elif has_tiles:
            config = _valhalla_config(tile_dir=tiles_dir)
        else:
            raise ConfigError(
                f"Valhalla tiles not found at {tiles_dir}. Build them from an OSM PBF "
                "first (see docs/road-routing.md: `cdmxmap build-tiles --pbf <osm.pbf>`)."
            )
    return valhalla.Actor(config)


class ValhallaRouter:
    """A ``Router`` backed by an in-process Valhalla ``Actor``."""

    engine = "valhalla"
    source = VALHALLA_FREE_FLOW_SOURCE

    def __init__(
        self,
        tiles_dir: str | Path = "data/processed/valhalla",
        *,
        config_path: str | Path | None = None,
        version: str | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        self.tiles_dir = Path(tiles_dir)
        self.chunk_size = max(1, chunk_size)
        self.version = version or _detect_version()
        self._actor = _load_actor(
            Path(config_path) if config_path is not None else None, self.tiles_dir
        )

    def profile(self, mode: str) -> str:
        try:
            return DEFAULT_PROFILES[mode]
        except KeyError as exc:
            raise ConfigError(f"Unsupported routing mode: {mode!r}") from exc

    def matrix(
        self, sources: Sequence[LatLon], targets: Sequence[LatLon], mode: str
    ) -> RouteMatrix:
        costing = self.profile(mode)
        target_locations = [{"lat": lat, "lon": lon} for lat, lon in targets]
        minutes = np.full((len(sources), len(targets)), np.nan)
        meters = np.full((len(sources), len(targets)), np.nan)

        for start in range(0, len(sources), self.chunk_size):
            chunk = sources[start : start + self.chunk_size]
            request = {
                "sources": [{"lat": lat, "lon": lon} for lat, lon in chunk],
                "targets": target_locations,
                "costing": costing,
            }
            raw = self._actor.matrix(json.dumps(request))
            data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
            for row in data.get("sources_to_targets", []):
                for cell in row:
                    i = start + int(cell["from_index"])
                    j = int(cell["to_index"])
                    seconds = cell.get("time")
                    kilometers = cell.get("distance")
                    if seconds is not None:
                        minutes[i, j] = float(seconds) / 60.0
                    if kilometers is not None:
                        meters[i, j] = float(kilometers) * 1000.0
        return RouteMatrix(minutes=minutes, meters=meters, mode=mode)


def _detect_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    for dist in ("pyvalhalla", "pyvalhalla-weekly", "valhalla"):
        try:
            return f"pyvalhalla {version(dist)}"
        except PackageNotFoundError:
            continue
    return "pyvalhalla unknown"


def _find_binary(name: str) -> str:
    """Locate a Valhalla build binary on PATH or inside the pyvalhalla package."""
    import importlib.util
    import shutil

    found = shutil.which(name)
    if found:
        return found
    spec = importlib.util.find_spec("valhalla")
    locations = list(spec.submodule_search_locations or []) if spec is not None else []
    for base in locations:
        for sub in ("bin", "."):
            candidate = Path(base) / sub / name
            if candidate.exists():
                return str(candidate)
    raise ConfigError(
        f"Valhalla build binary {name!r} not found. Install the 'routing' extra "
        "(`uv sync --extra routing`); see docs/road-routing.md for manual tile builds."
    )


def build_tiles(pbf_path: str | Path, tiles_dir: str | Path) -> Path:
    """Build a Valhalla tileset from an OSM PBF (one-time offline setup).

    Writes a routing config whose tile dir is ``tiles_dir`` itself, then runs the
    bundled ``valhalla_build_tiles`` binary. The graph tiles land directly in
    ``tiles_dir`` so ``ValhallaRouter`` reads them via the same config. Heavy;
    outputs are gitignored.
    """
    import subprocess

    pbf = Path(pbf_path)
    tiles = Path(tiles_dir)
    if not pbf.exists():
        raise ConfigError(f"OSM PBF not found: {pbf}")
    tiles.mkdir(parents=True, exist_ok=True)
    _require_valhalla()

    config = _valhalla_config(tile_dir=tiles)
    config_path = tiles / "valhalla.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    subprocess.run(  # noqa: S603
        [_find_binary("valhalla_build_tiles"), "-c", str(config_path), str(pbf)], check=True
    )
    return tiles
