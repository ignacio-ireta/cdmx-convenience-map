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


def _score_fixture(places: dict, *, router=None, routing_cache=None) -> list[dict]:
    points = load_point_datasets(places, data_dir=FIXTURE_CITY)
    scored = score_areas(
        config=AREA_CONFIGS["colonia"],
        input_path=FIXTURE_CITY / "areas.geojson",
        point_datasets=points,
        places_config=places,
        router=router,
        routing_cache=routing_cache,
    )
    props = [f["properties"] for f in json.loads(scored.output.to_json())["features"]]
    props.sort(key=lambda p: p["area_id"])
    return props


def _score_fixture_meta(places: dict, *, router=None, routing_cache=None) -> dict:
    points = load_point_datasets(places, data_dir=FIXTURE_CITY)
    return score_areas(
        config=AREA_CONFIGS["colonia"],
        input_path=FIXTURE_CITY / "areas.geojson",
        point_datasets=points,
        places_config=places,
        router=router,
        routing_cache=routing_cache,
    ).metadata


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


@pytest.mark.integration
class TestRoutedScoring:
    """Routing is opt-in; these drive score_areas with the deterministic StubRouter."""

    def test_routed_times_differ_from_fallback(self, fixture_places: dict, stub_router) -> None:
        fallback = {p["area_id"]: p for p in _score_fixture(fixture_places)}
        routed = {p["area_id"]: p for p in _score_fixture(fixture_places, router=stub_router)}
        # The stub uses different speeds/detours, so routed work times must move.
        moved = any(
            routed[a]["time_work_driving_min"] != fallback[a]["time_work_driving_min"]
            for a in routed
        )
        assert moved

    def test_routed_rows_are_labeled_and_have_routed_distance(
        self, fixture_places: dict, stub_router
    ) -> None:
        props = _score_fixture(fixture_places, router=stub_router)
        for p in props:
            assert p["work_travel_time_source"] == "valhalla_free_flow"
            assert p["amenity_travel_time_source"] == "valhalla_free_flow"
            # Routed distance fields are present, non-negative, and additive.
            assert p["dist_work_routed_m"] is not None and p["dist_work_routed_m"] >= 0
            assert p["dist_gym_routed_m"] is not None and p["dist_gym_routed_m"] >= 0
            # Straight-line fields are retained unchanged in name/shape.
            assert p["dist_work_m"] >= 0

    def test_routed_fields_absent_without_router(self, fixture_places: dict) -> None:
        # Gate: the additive routed fields must not appear on the fallback path,
        # which is exactly what keeps the existing golden byte-identical.
        props = _score_fixture(fixture_places)
        for p in props:
            assert "dist_work_routed_m" not in p
            assert "dist_gym_routed_m" not in p
            assert p["work_travel_time_source"] == "fallback_straight_line_estimate"

    def test_per_row_fallback_when_unreachable(
        self, fixture_places: dict, make_stub_router
    ) -> None:
        router = make_stub_router(unreachable=lambda origin, target: True)
        props = _score_fixture(fixture_places, router=router)
        fallback = {p["area_id"]: p for p in _score_fixture(fixture_places)}
        for p in props:
            # Unreachable -> honest fallback label, null routed distance, and the
            # time equals the straight-line estimate (never 0).
            assert p["work_travel_time_source"] == "fallback_straight_line_estimate"
            assert p["dist_work_routed_m"] is None
            assert p["time_work_driving_min"] == fallback[p["area_id"]]["time_work_driving_min"]

    def test_metadata_records_routing_provenance(self, fixture_places: dict, stub_router) -> None:
        meta = _score_fixture_meta(fixture_places, router=stub_router)
        block = meta["road_routing"]
        assert block["engine"] == "stub"
        assert block["source"] == "valhalla_free_flow"
        assert set(block["modes"]) == {"driving", "walking", "biking"}
        assert block["work"]["routed_count"]["driving"] == meta["feature_count"]

    def test_cache_round_trips(self, fixture_places: dict, stub_router, tmp_path) -> None:
        from cdmxmap.routing.cache import RoutingCache

        cache = RoutingCache(path=tmp_path / "routes.json")
        first = _score_fixture(fixture_places, router=stub_router, routing_cache=cache)
        assert cache.stats()["misses"] > 0
        cache.save()
        reloaded = RoutingCache(path=tmp_path / "routes.json")
        second = _score_fixture(fixture_places, router=stub_router, routing_cache=reloaded)
        assert first == second  # cached run reproduces the routed output
        assert reloaded.stats()["hits"] > 0


@pytest.mark.golden
def test_routed_golden_properties(fixture_places: dict, stub_router) -> None:
    props = _score_fixture(fixture_places, router=stub_router)
    golden_path = FIXTURE_CITY / "expected_properties_routed.json"
    if os.environ.get("UPDATE_GOLDEN"):
        golden_path.write_text(json.dumps(props, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    expected = json.loads(golden_path.read_text(encoding="utf-8"))
    assert props == expected
