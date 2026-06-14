"""Offline road-routing: a ``Router`` abstraction + a Valhalla adapter.

Replaces the straight-line travel-time placeholder with real street-network
routing during preprocessing. Routing is opt-in; when no router is supplied the
pipeline keeps its deterministic straight-line fallback (honest source label
``fallback_straight_line_estimate``). See ``docs/road-routing.md``.
"""

from __future__ import annotations

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
]
