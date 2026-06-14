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


def _load_actor(config_path: Path | None, tiles_dir: Path):
    """Import pyvalhalla lazily and build an Actor, with actionable errors."""
    try:
        from valhalla import Actor, get_config
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ConfigError(
            "Valhalla routing requires the optional 'routing' extra. Install it with "
            "`uv sync --extra routing` (pulls the pyvalhalla wheel), then build tiles "
            "(see docs/road-routing.md)."
        ) from exc

    if config_path is not None and config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        tile_extract = tiles_dir / "valhalla_tiles.tar"
        if tile_extract.exists():
            config = get_config(tile_extract=str(tile_extract))
        elif tiles_dir.exists():
            config = get_config(tile_dir=str(tiles_dir))
        else:
            raise ConfigError(
                f"Valhalla tiles not found at {tiles_dir}. Build them from an OSM PBF "
                "first (see docs/road-routing.md: `cdmxmap routing build-tiles`)."
            )
        # Raise matrix limits so a full area-to-area chunk is accepted.
        limits = config.setdefault("service_limits", {})
        for costing in DEFAULT_PROFILES.values():
            costing_limits = limits.setdefault(costing, {})
            costing_limits["max_matrix_locations"] = 100000
            costing_limits["max_matrix_distance"] = 5000000
    return Actor(config)


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
    """Build a Valhalla tileset + tar extract from an OSM PBF (one-time setup).

    Shells out to the pyvalhalla-bundled ``valhalla_build_config`` /
    ``valhalla_build_tiles`` / ``valhalla_build_extract`` binaries. Heavy and run
    offline; outputs are gitignored. See docs/road-routing.md.
    """
    import subprocess

    pbf = Path(pbf_path)
    tiles = Path(tiles_dir)
    if not pbf.exists():
        raise ConfigError(f"OSM PBF not found: {pbf}")
    tiles.mkdir(parents=True, exist_ok=True)
    config_path = tiles / "valhalla.json"
    tile_dir = tiles / "valhalla_tiles"
    tile_extract = tiles / "valhalla_tiles.tar"

    config_json = subprocess.run(  # noqa: S603
        [
            _find_binary("valhalla_build_config"),
            "--mjolnir-tile-dir",
            str(tile_dir),
            "--mjolnir-tile-extract",
            str(tile_extract),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    config_path.write_text(config_json, encoding="utf-8")

    subprocess.run(  # noqa: S603
        [_find_binary("valhalla_build_tiles"), "-c", str(config_path), str(pbf)], check=True
    )
    subprocess.run(  # noqa: S603
        [_find_binary("valhalla_build_extract"), "-c", str(config_path), "-v"], check=True
    )
    return tiles
