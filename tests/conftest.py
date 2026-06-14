"""Shared pytest configuration.

The pipeline is the installed ``cdmxmap`` package (``uv sync``), so tests import
it directly. Fixtures below seed a tiny synthetic "city" (``tests/fixtures/
fixture_city/``) so the integration/e2e/golden tests run fully offline.
"""

from __future__ import annotations

import json
import math
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
import pytest

from cdmxmap.routing.base import (
    DEFAULT_PROFILES,
    VALHALLA_FREE_FLOW_SOURCE,
    LatLon,
    RouteMatrix,
)

FIXTURE_CITY = Path(__file__).parent / "fixtures" / "fixture_city"
FIXTURE_CSVS = ("transit_stops.csv", "supermarkets.csv", "gyms.csv", "crime_points.csv")


def _haversine_m(a: LatLon, b: LatLon) -> float:
    earth_radius_m = 6371008.8
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    d_lat, d_lon = lat2 - lat1, lon2 - lon1
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    return 2 * earth_radius_m * math.asin(math.sqrt(h))


class StubRouter:
    """A deterministic in-memory router standing in for the Valhalla adapter.

    Routed times come from haversine distance × a detour factor ÷ a mode speed —
    intentionally different constants from the production straight-line fallback,
    so routed values are distinguishable in tests. It reports the real
    ``valhalla_free_flow`` source so golden/label tests exercise the production
    path; an optional ``unreachable`` predicate forces ``np.nan`` cells to test
    the per-row fallback.
    """

    engine = "stub"
    version = "0.0-test"
    source = VALHALLA_FREE_FLOW_SOURCE

    def __init__(
        self,
        *,
        detour: float = 1.6,
        speeds_kmh: dict[str, float] | None = None,
        unreachable: Callable[[LatLon, LatLon], bool] | None = None,
    ) -> None:
        self.detour = detour
        self.speeds_kmh = speeds_kmh or {"driving": 30.0, "walking": 5.0, "biking": 16.0}
        self._unreachable = unreachable

    def profile(self, mode: str) -> str:
        return DEFAULT_PROFILES[mode]

    def matrix(
        self, sources: Sequence[LatLon], targets: Sequence[LatLon], mode: str
    ) -> RouteMatrix:
        speed = self.speeds_kmh[mode]
        meters_per_minute = speed * 1000 / 60
        minutes = np.full((len(sources), len(targets)), np.nan)
        meters = np.full((len(sources), len(targets)), np.nan)
        for i, origin in enumerate(sources):
            for j, target in enumerate(targets):
                if self._unreachable is not None and self._unreachable(origin, target):
                    continue
                distance = _haversine_m(origin, target) * self.detour
                meters[i, j] = distance
                minutes[i, j] = distance / meters_per_minute
        return RouteMatrix(minutes=minutes, meters=meters, mode=mode)


@pytest.fixture
def stub_router() -> StubRouter:
    return StubRouter()


@pytest.fixture
def make_stub_router() -> Callable[..., StubRouter]:
    return lambda **kwargs: StubRouter(**kwargs)


@pytest.fixture
def fixture_places() -> dict:
    return json.loads((FIXTURE_CITY / "places.json").read_text(encoding="utf-8"))


@pytest.fixture
def fixture_data_dir(tmp_path: Path) -> Path:
    """A writable tmp dir seeded with the fixture point CSVs (mimics data/processed)."""
    dest = tmp_path / "processed"
    dest.mkdir()
    for name in FIXTURE_CSVS:
        shutil.copyfile(FIXTURE_CITY / name, dest / name)
    return dest
