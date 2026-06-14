"""Offline road-routing: a ``Router`` abstraction + a Valhalla adapter.

Replaces the straight-line travel-time placeholder with real street-network
routing during preprocessing. Routing is opt-in; when no router is supplied the
pipeline keeps its deterministic straight-line fallback (honest source label
``fallback_straight_line_estimate``). See ``docs/road-routing.md``.
"""

from __future__ import annotations

from pathlib import Path

from cdmxmap.errors import ConfigError
from cdmxmap.routing.base import (
    DEFAULT_PROFILES,
    FALLBACK_STRAIGHT_LINE_SOURCE,
    OSRM_FREE_FLOW_SOURCE,
    ROUTING_MODES,
    VALHALLA_FREE_FLOW_SOURCE,
    LatLon,
    RouteMatrix,
    Router,
)
from cdmxmap.routing.cache import RouteCacheKey, RoutingCache

__all__ = [
    "DEFAULT_PROFILES",
    "FALLBACK_STRAIGHT_LINE_SOURCE",
    "OSRM_FREE_FLOW_SOURCE",
    "ROUTING_MODES",
    "VALHALLA_FREE_FLOW_SOURCE",
    "LatLon",
    "RouteCacheKey",
    "RouteMatrix",
    "Router",
    "RoutingCache",
    "get_road_router",
]


def get_road_router(
    engine: str | None,
    *,
    tiles_dir: str | Path | None = None,
    version: str | None = None,
    config_path: str | Path | None = None,
) -> Router | None:
    """Construct a road router by engine name; ``None``/``"none"`` -> no router.

    pyvalhalla is imported lazily so the default (fallback) path never needs the
    optional 'routing' extra. An unknown engine raises an actionable ``ConfigError``.
    """
    if engine in (None, "", "none"):
        return None
    if engine == "valhalla":
        from cdmxmap.routing.valhalla import ValhallaRouter

        kwargs: dict = {}
        if tiles_dir:
            kwargs["tiles_dir"] = tiles_dir
        if version:
            kwargs["version"] = version
        if config_path:
            kwargs["config_path"] = config_path
        return ValhallaRouter(**kwargs)
    raise ConfigError(f"Unknown road routing engine: {engine!r} (expected 'none' or 'valhalla')")
