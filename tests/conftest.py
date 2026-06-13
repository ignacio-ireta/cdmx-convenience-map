"""Shared pytest configuration.

The pipeline is the installed ``cdmxmap`` package (``uv sync``), so tests import
it directly. Fixtures below seed a tiny synthetic "city" (``tests/fixtures/
fixture_city/``) so the integration/e2e/golden tests run fully offline.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

FIXTURE_CITY = Path(__file__).parent / "fixtures" / "fixture_city"
FIXTURE_CSVS = ("transit_stops.csv", "supermarkets.csv", "gyms.csv", "crime_points.csv")


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
