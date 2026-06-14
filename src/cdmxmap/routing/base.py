"""Road-routing abstraction (engineering standards §F).

A thin ``Router`` Protocol so the scoring engine depends on an interface, not a
concrete engine. The production adapter is Valhalla (in-process via ``pyvalhalla``,
see ``valhalla.py``); tests inject a deterministic stub.

Road routing is **offline preprocessing only** — it never runs in the browser —
and the free-flow engines we use have no live-traffic model, so results are
labeled honestly (``valhalla_free_flow`` / ``osrm_free_flow``), never
"actual traffic commute time". Unreachable / failed cells are ``np.nan`` so the
caller can fall back to the straight-line estimate; a routed time is never 0
(0 minutes would read as "best possible" and corrupt the score).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

# Pipeline travel modes. Mirrors ``config.WORK_TRAVEL_MODES`` (asserted equal in
# tests) — kept here so the routing package has no import cycle with config.
ROUTING_MODES = ("driving", "walking", "biking")

# Honest source-name labels written into the output contract.
VALHALLA_FREE_FLOW_SOURCE = "valhalla_free_flow"
OSRM_FREE_FLOW_SOURCE = "osrm_free_flow"
FALLBACK_STRAIGHT_LINE_SOURCE = "fallback_straight_line_estimate"

# Engine-agnostic costing/profile names per pipeline mode (Valhalla uses these
# verbatim; an OSRM adapter would map them to car/foot/bicycle profiles).
DEFAULT_PROFILES = {
    "driving": "auto",
    "walking": "pedestrian",
    "biking": "bicycle",
}

# A (latitude, longitude) WGS84 point. Order matches the rest of the pipeline
# (e.g. ``points.workplace_coordinates`` returns ``(lat, lon)``).
LatLon = tuple[float, float]


@dataclass(frozen=True)
class RouteMatrix:
    """Result of a sources × targets routing query.

    ``minutes`` and ``meters`` are float arrays shaped ``(len(sources), len(targets))``.
    Unreachable / failed cells are ``np.nan`` (never ``0``).
    """

    minutes: np.ndarray
    meters: np.ndarray
    mode: str

    @property
    def shape(self) -> tuple[int, ...]:
        return self.minutes.shape


@runtime_checkable
class Router(Protocol):
    """A road router answering sources × targets travel-time/distance queries."""

    engine: str
    version: str
    source: str

    def profile(self, mode: str) -> str:
        """The engine-specific costing/profile name for a pipeline mode."""
        ...

    def matrix(
        self,
        sources: Sequence[LatLon],
        targets: Sequence[LatLon],
        mode: str,
    ) -> RouteMatrix:
        """Route every source to every target.

        ``sources``/``targets`` are ``(lat, lon)`` pairs. The returned arrays are
        shaped ``(len(sources), len(targets))`` with ``np.nan`` for unreachable
        pairs and snapping failures.
        """
        ...
