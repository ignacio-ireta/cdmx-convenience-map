"""Integration + golden tests over the synthetic fixture city (standards §K).

Exercises the real scoring engine (areas -> points -> metrics -> crime ->
transit -> engine) end to end, offline, with no real data/.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from cdmxmap import validate as vmod
from cdmxmap.models import AREA_CONFIGS
from cdmxmap.scoring import score_areas
from cdmxmap.scoring.points import load_point_datasets

FIXTURE_CITY = Path(__file__).parents[1] / "fixtures" / "fixture_city"


def _score_fixture(places: dict) -> list[dict]:
    points = load_point_datasets(places, data_dir=FIXTURE_CITY)
    scored = score_areas(
        config=AREA_CONFIGS["colonia"],
        input_path=FIXTURE_CITY / "areas.geojson",
        point_datasets=points,
        places_config=places,
    )
    props = [f["properties"] for f in json.loads(scored.output.to_json())["features"]]
    props.sort(key=lambda p: p["area_id"])
    return props


@pytest.mark.integration
class TestFixtureScoring:
    def test_property_contract(self, fixture_places: dict) -> None:
        props = _score_fixture(fixture_places)
        assert [p["area_id"] for p in props] == ["C001", "C002", "C003"]
        for p in props:
            for field in vmod.GENERIC_FIELDS:
                assert p.get(field)
            for field in vmod.DISTANCE_FIELDS + vmod.TIME_FIELDS:
                assert p[field] >= 0
            for field in vmod.SCORE_FIELDS:
                assert 0 <= p[field] <= 100
            for field in vmod.TRANSIT_COMMUTE_FIELDS:
                assert field in p
        assert any(p["time_work_transit_min"] is not None for p in props)

    def test_known_values(self, fixture_places: dict) -> None:
        by_id = {p["area_id"]: p for p in _score_fixture(fixture_places)}
        # More recent crime -> worse safety; no crime -> best.
        assert by_id["C001"]["crime_incidents_recent_12m"] == 4
        assert by_id["C001"]["score_safety"] == 0.0
        assert by_id["C003"]["crime_incidents_recent_12m"] == 0
        assert by_id["C003"]["score_safety"] == 100.0
        # Farthest area from the workplace -> work score 0 (closer-is-better cap).
        assert by_id["C003"]["score_work"] == 0.0
        # Brand fields populate from the seeded supermarkets.
        assert by_id["C001"]["nearest_costco_name"] == "Costco Centro"


@pytest.mark.golden
def test_golden_properties(fixture_places: dict) -> None:
    props = _score_fixture(fixture_places)
    golden_path = FIXTURE_CITY / "expected_properties.json"
    if os.environ.get("UPDATE_GOLDEN"):
        golden_path.write_text(json.dumps(props, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    expected = json.loads(golden_path.read_text(encoding="utf-8"))
    assert props == expected
