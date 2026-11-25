"""Integration + golden tests for the ``city_statistics`` crime mode (spec §4.2).

The synthetic ``tests/fixtures/fixture_city_stats/`` profile mirrors a Monterrey-like
city: postal areas carry a ``mun_code``, safety comes from per-municipality
aggregates in ``crime_statistics.csv``, and its places.json turns on every opt-in
transit-commute option (line data, ``|`` multi-route stops, per-system speeds,
priority candidates). Regenerate the goldens (and read the diff) with::

    UPDATE_GOLDEN=1 uv run pytest tests/integration/test_city_statistics.py -m golden
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from cdmxmap.citycontext import CityContext, load_city_context
from cdmxmap.errors import ScoringError
from cdmxmap.models import AREA_CONFIGS, ScoredAreaResult
from cdmxmap.pipeline import build_area
from cdmxmap.routing.cache import RoutingCache
from cdmxmap.schema import validate_city_profile
from cdmxmap.scoring import score_areas
from cdmxmap.scoring.notes import CDMX_SAFETY_NOTE, CDMX_TRANSIT_NOTE
from cdmxmap.scoring.points import load_point_datasets
from cdmxmap.validate import CRIME_COUNT_FIELDS, validate_geojson

FIXTURES = Path(__file__).parents[1] / "fixtures"
STATS_CITY = FIXTURES / "fixture_city_stats"
CDMX_FIXTURE_CITY = FIXTURES / "fixture_city"
STATS_CSVS = ("transit_stops.csv", "supermarkets.csv", "gyms.csv", "crime_statistics.csv")
STATISTICS_FIELDS = (
    "crime_statistics_scope",
    "crime_statistics_area",
    "crime_statistics_period",
    "crime_scope_population",
    "crime_scope_incidents_12m",
    "crime_scope_scored_incidents_12m",
    "crime_rate_per_100k_12m",
    "crime_total_rate_per_100k_12m",
)


@pytest.fixture
def stats_profile() -> dict:
    data = json.loads((STATS_CITY / "city.json").read_text(encoding="utf-8"))
    return validate_city_profile(data, city="fixture_stats")


@pytest.fixture
def stats_places() -> dict:
    return json.loads((STATS_CITY / "places.json").read_text(encoding="utf-8"))


@pytest.fixture
def stats_ctx(monkeypatch: pytest.MonkeyPatch, stats_profile: dict) -> CityContext:
    """The synthetic profile resolved through the real profile-context path."""
    monkeypatch.setattr("cdmxmap.citycontext.load_city_profile", lambda city: stats_profile)
    return load_city_context("fixture_stats")


@pytest.fixture
def stats_data_dir(tmp_path: Path) -> Path:
    dest = tmp_path / "processed"
    dest.mkdir()
    for name in STATS_CSVS:
        shutil.copyfile(STATS_CITY / name, dest / name)
    return dest


def _score(
    ctx: CityContext,
    places: dict,
    *,
    data_dir: Path = STATS_CITY,
    router: Any = None,
    routing_cache: RoutingCache | None = None,
) -> ScoredAreaResult:
    points = load_point_datasets(places, ctx=ctx, data_dir=data_dir)
    return score_areas(
        config=ctx.area_configs["postal_code"],
        input_path=STATS_CITY / "areas.geojson",
        point_datasets=points,
        places_config=places,
        ctx=ctx,
        router=router,
        routing_cache=routing_cache,
    )


def _properties(result: ScoredAreaResult) -> list[dict]:
    props = [f["properties"] for f in json.loads(result.output.to_json())["features"]]
    props.sort(key=lambda p: p["area_id"])
    return props


def _strip_generated_at(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_generated_at(v) for k, v in value.items() if k != "generated_at"}
    if isinstance(value, list | tuple):
        return [_strip_generated_at(item) for item in value]
    return value


def _read_or_update(path: Path, text: str) -> str:
    if os.environ.get("UPDATE_GOLDEN"):
        path.write_text(text, encoding="utf-8")
    return path.read_text(encoding="utf-8")


@pytest.mark.integration
class TestStatisticsScoring:
    def test_context_resolves_statistics_mode(self, stats_ctx: CityContext) -> None:
        assert stats_ctx.crime_mode == "city_statistics"
        # The profile declares "Bus"; codes are upper-cased to match the data.
        assert [spec.code for spec in stats_ctx.transit_systems] == ["METRO", "BRT", "BUS"]

    def test_statistics_fields_replace_incident_fields(
        self, stats_ctx: CityContext, stats_places: dict
    ) -> None:
        props = _properties(_score(stats_ctx, stats_places))
        assert [p["area_id"] for p in props] == ["90001", "90002", "90003", "90004", "90005"]
        for p in props:
            for field in CRIME_COUNT_FIELDS:
                assert field not in p, "no per-area incident counts in statistics mode"
            for field in STATISTICS_FIELDS:
                assert field in p
            assert p["crime_statistics_scope"] == "municipality"
            assert p["crime_statistics_period"] == "2025-11-01/2026-10-31"
            assert p["crime_source"] == "sesnsp_municipal"
        by_id = {p["area_id"]: p for p in props}
        centro = by_id["90001"]
        assert centro["crime_statistics_area"] == "Municipio Centro"
        assert centro["crime_scope_population"] == 500000
        assert centro["crime_scope_incidents_12m"] == 9000
        assert centro["crime_scope_scored_incidents_12m"] == 1500
        assert centro["crime_rate_per_100k_12m"] == 300.0
        assert centro["crime_total_rate_per_100k_12m"] == 1800.0
        assert centro["crime_top_category_recent_12m"] == "Violencia familiar"
        assert by_id["90004"]["crime_total_rate_per_100k_12m"] == 1083.3

    def test_safety_scores_the_municipal_scored_rate(
        self, stats_ctx: CityContext, stats_places: dict
    ) -> None:
        by_id = {p["area_id"]: p for p in _properties(_score(stats_ctx, stats_places))}
        # Min-max over the matched units' rates (112.5 .. 300 per 100k): the highest
        # rate scores 0, the lowest 100, linearly. Same municipality -> same score.
        assert by_id["90001"]["score_safety"] == by_id["90002"]["score_safety"] == 0.0  # 300
        assert by_id["90003"]["score_safety"] == 80.0  # 150: 100 * 150 / 187.5
        assert by_id["90004"]["score_safety"] == 66.7  # 175: 100 * 125 / 187.5
        assert by_id["90005"]["score_safety"] == 100.0  # 112.5, the lowest rate

    def test_metadata_lists_matched_units_only(
        self, stats_ctx: CityContext, stats_places: dict
    ) -> None:
        crime = _score(stats_ctx, stats_places).metadata["crime"]
        assert list(crime) == [
            "mode",
            "scope",
            "source",
            "source_label",
            "scored_label",
            "scored_definition",
            "scored_offenses",
            "score_method",
            "population_source",
            "period_start",
            "period_end",
            "recent_start_date",
            "latest_date",
            "records_total",
            "records_recent_12m",
            "units",
            "areas_matched",
            "areas_unmatched",
        ]
        assert [unit["key"] for unit in crime["units"]] == ["99001", "99002", "99003", "99004"]
        assert [unit["areas"] for unit in crime["units"]] == [2, 1, 1, 1]
        # 99005 has no area, so its 400 incidents are not counted.
        assert crime["records_total"] == crime["records_recent_12m"] == 13400
        assert crime["recent_start_date"] == crime["period_start"] == "2025-11-01"
        assert crime["latest_date"] == crime["period_end"] == "2026-10-31"
        assert (crime["areas_matched"], crime["areas_unmatched"]) == (5, 0)
        assert crime["score_method"] == "min_max_across_units"
        # Copied from the profile so the UI can show what the scored rate counts.
        assert crime["scored_label"] == "robbery and violent crime"
        assert crime["scored_definition"] == "Synthetic robbery and violent-crime subset"
        assert crime["scored_offenses"] == ["Robo", "Lesiones dolosas"]

    def test_generated_notes(self, stats_ctx: CityContext, stats_places: dict) -> None:
        notes = _score(stats_ctx, stats_places).metadata["notes"]
        assert "Transit score is 70% nearest Fixture Metro / Fixture BRT and 30% nearest " in (
            " ".join(notes)
        )
        assert (
            "Safety score ranks the municipalities within the metro by robbery and violent "
            "crime per 100k residents (Synthetic municipal crime statistics): the lowest rate "
            "scores 100 and the highest 0, linearly; every area in a municipality shares its "
            "municipality's score."
        ) in notes
        assert CDMX_TRANSIT_NOTE not in notes and CDMX_SAFETY_NOTE not in notes

    def test_unmatched_area_is_a_hard_error(
        self, stats_ctx: CityContext, stats_places: dict, stats_data_dir: Path
    ) -> None:
        csv_path = stats_data_dir / "crime_statistics.csv"
        lines = csv_path.read_text(encoding="utf-8").splitlines()
        csv_path.write_text(
            "\n".join(line for line in lines if not line.startswith("99004")) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(ScoringError, match="no crime_statistics unit.*90005"):
            _score(stats_ctx, stats_places, data_dir=stats_data_dir)

    def test_missing_join_field_is_a_hard_error(
        self, stats_ctx: CityContext, stats_places: dict
    ) -> None:
        profile = {
            **stats_ctx.profile,
            "crime_statistics": {**stats_ctx.profile["crime_statistics"], "area_key_field": "x"},
        }
        ctx = dataclasses.replace(stats_ctx, profile=profile)
        with pytest.raises(ScoringError, match="join field 'x'"):
            _score(ctx, stats_places)

    def test_missing_statistics_file_raises(
        self, stats_ctx: CityContext, stats_places: dict, stats_data_dir: Path
    ) -> None:
        (stats_data_dir / "crime_statistics.csv").unlink()
        with pytest.raises(FileNotFoundError, match="crime_statistics.csv"):
            load_point_datasets(stats_places, ctx=stats_ctx, data_dir=stats_data_dir)

    def test_build_area_writes_valid_statistics_output(
        self,
        stats_ctx: CityContext,
        stats_places: dict,
        stats_data_dir: Path,
        tmp_path: Path,
    ) -> None:
        out = build_area(
            "postal_code",
            ctx=stats_ctx,
            input_path=STATS_CITY / "areas.geojson",
            places_config=stats_places,
            data_dir=stats_data_dir,
            public_dir=tmp_path / "public",
            skip_legacy=True,
        )
        assert validate_geojson(out, ctx=stats_ctx) == 5
        meta = json.loads((stats_data_dir / "score_metadata_postal_code.json").read_text())
        assert meta["crime"]["mode"] == "city_statistics"
        assert meta["sources"]["crime_statistics"].endswith("crime_statistics.csv")
        assert meta["point_counts"]["crime_statistics_units"] == 5
        assert meta["point_counts"]["crime_records"] == 0
        assert meta["point_counts"]["transit_system_points"] == {"metro": 5, "brt": 2, "rutas": 7}

    def test_routed_metadata_records_routing_provenance(
        self, stats_ctx: CityContext, stats_places: dict, stub_router
    ) -> None:
        block = _score(stats_ctx, stats_places, router=stub_router).metadata["road_routing"]
        assert block["search_filter"] == {"min_road_class": "residential"}
        assert block["osm_md5"] == "00000000000000000000000000000000"
        assert block["osm_date"] == "2026-11-24"

    def test_routed_amenity_metadata_names_the_router(
        self, stats_ctx: CityContext, stats_places: dict, stub_router
    ) -> None:
        metadata = _score(stats_ctx, stats_places, router=stub_router).metadata
        block = metadata["amenity_travel_time"]
        # Mirrors travel_time: the router's source, with the straight-line fallback named.
        assert list(block)[:3] == ["source", "fallback_source", "mode"]
        assert block["source"] == metadata["travel_time"]["source"] == "valhalla_free_flow"
        assert block["fallback_source"] == "fallback_straight_line_estimate"

    def test_unrouted_amenity_metadata_has_no_fallback_key(
        self, stats_ctx: CityContext, stats_places: dict
    ) -> None:
        block = _score(stats_ctx, stats_places).metadata["amenity_travel_time"]
        assert block["source"] == "fallback_straight_line_estimate"
        assert "fallback_source" not in block

    def test_search_filter_is_part_of_the_route_cache_key(
        self, stats_ctx: CityContext, stats_places: dict, stub_router, tmp_path: Path
    ) -> None:
        cache = RoutingCache(path=tmp_path / "routes.json")
        _score(stats_ctx, stats_places, router=stub_router, routing_cache=cache)
        first = cache.stats()
        _score(stats_ctx, stats_places, router=stub_router, routing_cache=cache)
        repeat = cache.stats()
        assert repeat["misses"] == first["misses"] and repeat["hits"] > 0
        unfiltered = {
            **stats_places,
            "road_routing": {
                k: v for k, v in stats_places["road_routing"].items() if k != "search_filter"
            },
        }
        _score(stats_ctx, unfiltered, router=stub_router, routing_cache=cache)
        # Dropping the filter changes inputs_hash, so nothing is served from cache.
        assert cache.stats()["misses"] == 2 * first["misses"]
        assert cache.stats()["entries"] == 2 * first["entries"]


@pytest.mark.golden
def test_statistics_golden_properties(stats_ctx: CityContext, stats_places: dict) -> None:
    props = _properties(_score(stats_ctx, stats_places))
    serialized = json.dumps(props, indent=2, sort_keys=True) + "\n"
    expected = json.loads(_read_or_update(STATS_CITY / "expected_properties.json", serialized))
    assert props == expected


@pytest.mark.golden
def test_statistics_golden_metadata(stats_ctx: CityContext, stats_places: dict) -> None:
    metadata = _strip_generated_at(_score(stats_ctx, stats_places).metadata)
    serialized = json.dumps(metadata, indent=2) + "\n"
    expected_text = _read_or_update(STATS_CITY / "expected_metadata.json", serialized)
    assert json.loads(serialized) == json.loads(expected_text)
    assert serialized == expected_text  # values and key order


@pytest.mark.golden
def test_statistics_golden_property_order(stats_ctx: CityContext, stats_places: dict) -> None:
    props = _properties(_score(stats_ctx, stats_places))
    orders = {tuple(p) for p in props}
    assert len(orders) == 1
    serialized = json.dumps(list(next(iter(orders))), indent=2) + "\n"
    expected = json.loads(_read_or_update(STATS_CITY / "expected_property_order.json", serialized))
    assert list(next(iter(orders))) == expected


@pytest.mark.integration
class TestExistingCitiesUnchanged:
    """CDMX and incident-mode cities never pick up statistics-mode keys."""

    def test_cdmx_context_emits_no_statistics_keys(self, fixture_places: dict) -> None:
        ctx = load_city_context("cdmx")
        points = load_point_datasets(fixture_places, ctx=ctx, data_dir=CDMX_FIXTURE_CITY)
        assert points.crime_statistics is None
        result = score_areas(
            config=AREA_CONFIGS["colonia"],
            input_path=CDMX_FIXTURE_CITY / "areas.geojson",
            point_datasets=points,
            places_config=fixture_places,
            ctx=ctx,
        )
        for p in _properties(result):
            assert not [field for field in STATISTICS_FIELDS if field in p]
            assert "crime_buffer_m" not in p
            assert p["crime_source"] == "fgj_cdmx_victimas"
        assert "fallback_source" not in result.metadata["amenity_travel_time"]
        assert list(result.metadata["crime"]) == [
            "records_total",
            "records_recent_12m",
            "latest_date",
            "recent_start_date",
        ]
        assert CDMX_TRANSIT_NOTE in result.metadata["notes"]
        assert CDMX_SAFETY_NOTE in result.metadata["notes"]
        assert "systems" not in result.metadata["transit_commute"]["speeds_kmh"]

    def test_cdmx_routed_metadata_has_no_new_routing_keys(
        self, fixture_places: dict, stub_router
    ) -> None:
        ctx = load_city_context("cdmx")
        points = load_point_datasets(fixture_places, ctx=ctx, data_dir=CDMX_FIXTURE_CITY)
        block = score_areas(
            config=AREA_CONFIGS["colonia"],
            input_path=CDMX_FIXTURE_CITY / "areas.geojson",
            point_datasets=points,
            places_config=fixture_places,
            ctx=ctx,
            router=stub_router,
        ).metadata["road_routing"]
        assert not {"search_filter", "osm_md5", "osm_date"} & set(block)

    def test_profile_incident_city_uses_its_declared_crime_source(
        self, fixture_places: dict
    ) -> None:
        cdmx = load_city_context("cdmx")
        ctx = dataclasses.replace(
            cdmx,
            city_id="fixture_incident",
            profile={
                **cdmx.profile,
                "crime_source": {"source": "iieg_jalisco_fge", "source_label": "IIEG test"},
            },
        )
        points = load_point_datasets(fixture_places, ctx=ctx, data_dir=CDMX_FIXTURE_CITY)
        result = score_areas(
            config=AREA_CONFIGS["colonia"],
            input_path=CDMX_FIXTURE_CITY / "areas.geojson",
            point_datasets=points,
            places_config=fixture_places,
            ctx=ctx,
        )
        props = _properties(result)
        assert {p["crime_source"] for p in props} == {"iieg_jalisco_fge"}
        assert all(field in p for p in props for field in CRIME_COUNT_FIELDS)
        crime = result.metadata["crime"]
        assert crime["source"] == "iieg_jalisco_fge"
        assert crime["source_label"] == "IIEG test"
        assert crime["records_recent_12m"] == 5
        assert (
            "Safety score is lower-is-better incident density per km² over the latest 12 "
            "months in the IIEG test data."
        ) in result.metadata["notes"]
