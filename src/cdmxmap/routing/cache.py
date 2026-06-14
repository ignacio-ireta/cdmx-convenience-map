"""File-backed routing cache with stable keys (engineering standards §J/§Q).

Routing a representative point to a destination is deterministic for a fixed
engine + OSM extract, so results are cached and reused across runs. The cache
key includes everything that can change a routed value — area unit/id, origin and
destination coordinates, mode, engine, version, profile, and an inputs hash
(OSM/engine provenance) — so a stale value is never silently reused after the
network or engine changes.

This caches the modest work + amenity candidate routes. The bulk area-to-area
matrix is invalidated wholesale via the OSM/engine hash recorded in its sidecar
(see ``matrix_codec``), not cached cell-by-cell.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

# Coordinates are rounded before hashing so float noise can't fragment the cache.
_COORD_PRECISION = 6


@dataclass(frozen=True)
class RouteCacheKey:
    """Everything that can change a single routed result."""

    area_unit: str
    area_id: str
    origin: tuple[float, float]
    destination: tuple[float, float]
    mode: str
    engine: str
    version: str
    profile: str
    inputs_hash: str

    def digest(self) -> str:
        origin = [round(self.origin[0], _COORD_PRECISION), round(self.origin[1], _COORD_PRECISION)]
        destination = [
            round(self.destination[0], _COORD_PRECISION),
            round(self.destination[1], _COORD_PRECISION),
        ]
        payload = {
            "area_unit": self.area_unit,
            "area_id": self.area_id,
            "origin": origin,
            "destination": destination,
            "mode": self.mode,
            "engine": self.engine,
            "version": self.version,
            "profile": self.profile,
            "inputs_hash": self.inputs_hash,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class RoutingCache:
    """A JSON-file cache of ``digest -> {minutes, meters}`` with hit/miss stats.

    Disabled instances (``enabled=False``) act as a no-op so callers don't need a
    branch. Call :meth:`save` once after a build to persist new entries atomically.
    """

    def __init__(self, path: Path | None = None, *, enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled and path is not None
        self._store: dict[str, list[float]] = {}
        self.hits = 0
        self.misses = 0
        if self.enabled and path is not None and path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                self._store = {key: list(value) for key, value in raw.get("routes", {}).items()}
            except (json.JSONDecodeError, OSError, ValueError):
                # A corrupt cache is non-fatal: start fresh rather than crash a build.
                self._store = {}

    def get(self, key: RouteCacheKey) -> tuple[float, float] | None:
        if not self.enabled:
            return None
        value = self._store.get(key.digest())
        if value is None:
            self.misses += 1
            return None
        self.hits += 1
        return float(value[0]), float(value[1])

    def set(self, key: RouteCacheKey, minutes: float, meters: float) -> None:
        if not self.enabled:
            return
        self._store[key.digest()] = [float(minutes), float(meters)]

    def save(self) -> None:
        if not self.enabled or self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f"{self.path.name}.tmp")
        tmp_path.write_text(
            json.dumps({"routes": self._store}, separators=(",", ":")), encoding="utf-8"
        )
        tmp_path.replace(self.path)

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "entries": len(self._store)}
