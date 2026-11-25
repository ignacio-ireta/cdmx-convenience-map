"""Buffered incident density (``crime_source.density_buffer_m``, profile incident cities).

A tiny polygon with no incidents of its own should not read as perfectly safe when
its neighbor is busy: with a buffer, every incident field is computed over the area
plus ``density_buffer_m`` meters. CDMX and every profile without the key keep the
unbuffered polygon join byte-for-byte.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

from cdmxmap.citycontext import CityContext, load_city_context
from cdmxmap.errors import ConfigError
from cdmxmap.models import AREA_CONFIGS, ScoredAreaResult
from cdmxmap.scoring import score_areas
from cdmxmap.scoring.crime import (
    aggregate_crime,
    incident_crime_metadata,
    incident_density_buffer_m,
)
from cdmxmap.scoring.notes import CDMX_SAFETY_NOTE, safety_score_note
from cdmxmap.scoring.points import load_point_datasets
from cdmxmap.validate import validate_geojson

METRIC = "EPSG:32613"
FIXTURE_CITY = Path(__file__).parents[1] / "fixtures" / "fixture_city"
BUFFER_M = 250

# "hot" is 1 km²; "tiny" (0.01 km²) touches hot's east edge; "far" is 5 km away.
HOT = box(0, 0, 1000, 1000)
TINY = box(1000, 0, 1100, 100)
FAR = box(5000, 5000, 5100, 5100)


def _areas() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"area_id": ["hot", "tiny", "far"]}, geometry=[HOT, TINY, FAR], crs=METRIC
    )


def _crimes(rows: list[tuple[float, float, str, str]]) -> gpd.GeoDataFrame:
    """(x, y, date, category) rows -> the metric-CRS frame ``read_crimes`` returns."""
    frame = pd.DataFrame(rows, columns=["x", "y", "date", "category"])
    frame["date"] = pd.to_datetime(frame["date"])
    return gpd.GeoDataFrame(
        frame.drop(columns=["x", "y"]),
        geometry=[Point(x, y) for x, y in zip(frame["x"], frame["y"])],
        crs=METRIC,
    )


# Ten recent incidents inside hot, 50 m from tiny; one mid-hot; one stale one.
HOT_EDGE = [(950.0, 50.0, "2026-09-01", "Robo") for _ in range(10)]
BASE_ROWS = [
    *HOT_EDGE,
    (500.0, 500.0, "2026-10-01", "Lesiones"),
    (500.0, 500.0, "2024-01-01", "Robo"),  # outside every 12-month window
]


def _by_id(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.set_index("area_id")


class TestAggregateCrimeBuffer:
    def test_tiny_zero_count_polygon_borrows_its_hot_neighbor(self) -> None:
        crimes = _crimes(BASE_ROWS)
        plain = _by_id(aggregate_crime(_areas(), crimes)[0])
        buffered = _by_id(aggregate_crime(_areas(), crimes, buffer_m=BUFFER_M)[0])
        # Unbuffered: the tiny polygon has no incidents, so it would score as safest.
        assert plain.loc["tiny", "crime_incidents_recent_12m"] == 0
        assert plain.loc["tiny", "crime_density_recent_12m_per_km2"] == 0.0
        # Buffered: the ten hot-edge incidents lie within 250 m of it.
        assert buffered.loc["tiny", "crime_incidents_recent_12m"] == 10
        assert buffered.loc["tiny", "crime_incidents_total"] == 10
        assert buffered.loc["tiny", "crime_density_recent_12m_per_km2"] > 0
        assert buffered.loc["tiny", "crime_top_category_recent_12m"] == "Robo"
        # A far area with nothing nearby stays at zero (no invented incidents).
        assert buffered.loc["far", "crime_incidents_total"] == 0
        assert buffered.loc["far", "crime_top_category_recent_12m"] == ""

    def test_density_divides_by_the_buffered_area(self) -> None:
        buffered = _by_id(aggregate_crime(_areas(), _crimes(BASE_ROWS), buffer_m=BUFFER_M)[0])
        tiny_km2 = TINY.buffer(BUFFER_M).area / 1_000_000
        hot_km2 = HOT.buffer(BUFFER_M).area / 1_000_000
        assert 0.29 < tiny_km2 < 0.31  # 0.01 km² polygon + its 250 m ring
        assert buffered.loc["tiny", "crime_density_recent_12m_per_km2"] == pytest.approx(
            10 / tiny_km2
        )
        assert buffered.loc["hot", "crime_incidents_recent_12m"] == 11
        assert buffered.loc["hot", "crime_density_recent_12m_per_km2"] == pytest.approx(
            11 / hot_km2
        )

    def test_metadata_counts_unique_incidents_not_join_rows(self) -> None:
        crimes = _crimes(BASE_ROWS)
        frame, metadata = aggregate_crime(_areas(), crimes, buffer_m=BUFFER_M)
        per_area = _by_id(frame)
        # The ten hot-edge incidents count toward both hot and tiny (intended) ...
        assert per_area["crime_incidents_total"].sum() == 12 + 10
        assert per_area["crime_incidents_recent_12m"].sum() == 11 + 10
        # ... but the metadata reports each incident once.
        assert metadata["records_total"] == 12
        assert metadata["records_recent_12m"] == 11

    def test_unique_counts_survive_a_non_unique_input_index(self) -> None:
        crimes = _crimes(BASE_ROWS)
        crimes.index = [0] * len(crimes)  # e.g. a concatenated frame
        _, metadata = aggregate_crime(_areas(), crimes, buffer_m=BUFFER_M)
        assert (metadata["records_total"], metadata["records_recent_12m"]) == (12, 11)

    def test_window_anchors_on_the_latest_incident_inside_the_buffers(self) -> None:
        rows = [
            *BASE_ROWS,
            # In hot's and tiny's buffers but in no polygon: anchors only when buffered.
            (1200.0, 50.0, "2026-11-15", "Fraude"),
            # Outside every buffer, latest of all: never anchors the window.
            (20000.0, 20000.0, "2026-12-31", "Robo"),
        ]
        _, plain = aggregate_crime(_areas(), _crimes(rows))
        _, buffered = aggregate_crime(_areas(), _crimes(rows), buffer_m=BUFFER_M)
        assert plain["latest_date"] == "2026-10-01"
        assert buffered["latest_date"] == "2026-11-15"
        assert buffered["recent_start_date"] == "2025-11-15"
        assert buffered["records_total"] == 13  # the far-away incident is not counted

    def test_zero_buffer_is_the_historical_polygon_join(self) -> None:
        crimes = _crimes(BASE_ROWS)
        default_frame, default_meta = aggregate_crime(_areas(), crimes)
        zero_frame, zero_meta = aggregate_crime(_areas(), crimes, buffer_m=0)
        pd.testing.assert_frame_equal(default_frame, zero_frame)
        assert default_meta == zero_meta
        # Join rows, as before (the polygons here do not overlap).
        assert default_meta["records_total"] == 12

    def test_empty_crimes_with_a_buffer(self) -> None:
        frame, metadata = aggregate_crime(_areas(), _crimes([]), buffer_m=BUFFER_M)
        assert frame["crime_incidents_total"].tolist() == [0, 0, 0]
        assert metadata["records_total"] == 0 and metadata["latest_date"] is None


class TestBufferSetting:
    def test_guadalajara_declares_250_m(self) -> None:
        assert incident_density_buffer_m(load_city_context("guadalajara")) == BUFFER_M

    @pytest.mark.parametrize("city", ["morelia", "oslo", "monterrey"])
    def test_profiles_without_the_key_are_unbuffered(self, city: str) -> None:
        assert incident_density_buffer_m(load_city_context(city)) == 0

    def test_cdmx_is_never_buffered(self) -> None:
        cdmx = load_city_context("cdmx")
        injected = dataclasses.replace(
            cdmx, profile={**cdmx.profile, "crime_source": {"density_buffer_m": 500}}
        )
        assert incident_density_buffer_m(cdmx) == 0
        assert incident_density_buffer_m(injected) == 0
        assert incident_crime_metadata(injected, {"records_total": 0}) == {"records_total": 0}
        assert safety_score_note(injected) == CDMX_SAFETY_NOTE

    @pytest.mark.parametrize("value", [-1, 12.5, "250", True, float("nan")])
    def test_malformed_buffer_is_a_config_error(self, value: object) -> None:
        ctx = dataclasses.replace(
            load_city_context("guadalajara"),
            profile={"crime_source": {"source": "x", "density_buffer_m": value}},
        )
        with pytest.raises(ConfigError, match="density_buffer_m"):
            incident_density_buffer_m(ctx)

    def test_zero_buffer_adds_no_metadata_key(self) -> None:
        ctx = dataclasses.replace(
            load_city_context("guadalajara"),
            profile={"crime_source": {"source": "x", "density_buffer_m": 0}},
        )
        assert incident_density_buffer_m(ctx) == 0
        assert list(incident_crime_metadata(ctx, {"records_total": 0})) == [
            "records_total",
            "source",
            "source_label",
        ]


def _buffered_ctx(buffer_m: int | None) -> CityContext:
    """CDMX's fixture-city context as a profile incident city (optionally buffered)."""
    cdmx = load_city_context("cdmx")
    crime_source: dict = {"source": "iieg_jalisco_fge", "source_label": "IIEG test"}
    if buffer_m is not None:
        crime_source["density_buffer_m"] = buffer_m
    return dataclasses.replace(
        cdmx,
        city_id="fixture_buffered",
        profile={**cdmx.profile, "crime_source": crime_source},
    )


def _score(ctx: CityContext, places: dict) -> ScoredAreaResult:
    points = load_point_datasets(places, ctx=ctx, data_dir=FIXTURE_CITY)
    return score_areas(
        config=AREA_CONFIGS["colonia"],
        input_path=FIXTURE_CITY / "areas.geojson",
        point_datasets=points,
        places_config=places,
        ctx=ctx,
    )


def _properties(result: ScoredAreaResult) -> list[dict]:
    props = [f["properties"] for f in json.loads(result.output.to_json())["features"]]
    return sorted(props, key=lambda p: p["area_id"])


class TestEngineBuffer:
    def test_buffered_city_emits_buffer_field_metadata_and_note(
        self, fixture_places: dict, tmp_path: Path
    ) -> None:
        ctx = _buffered_ctx(BUFFER_M)
        result = _score(ctx, fixture_places)
        props = _properties(result)
        plain = {p["area_id"]: p for p in _properties(_score(_buffered_ctx(None), fixture_places))}
        for p in props:
            assert p["crime_buffer_m"] == BUFFER_M and isinstance(p["crime_buffer_m"], int)
            keys = list(p)
            density = keys.index("crime_density_recent_12m_per_km2")
            assert keys[density + 1] == "crime_buffer_m"
            # The buffered area contains the polygon, so the all-time count can only grow.
            assert p["crime_incidents_total"] >= plain[p["area_id"]]["crime_incidents_total"]
        crime = result.metadata["crime"]
        assert list(crime)[-3:] == ["source", "source_label", "density_buffer_m"]
        assert crime["density_buffer_m"] == BUFFER_M
        assert (
            "Safety score is lower-is-better incident density per km² over each area plus a "
            "250 m buffer, latest 12 months in the IIEG test data."
        ) in result.metadata["notes"]
        path = tmp_path / "scores.geojson"
        path.write_text(result.output.to_json(), encoding="utf-8")
        assert validate_geojson(path, ctx=ctx) == len(props)

    def test_unbuffered_profile_city_has_no_buffer_keys(self, fixture_places: dict) -> None:
        result = _score(_buffered_ctx(None), fixture_places)
        assert all("crime_buffer_m" not in p for p in _properties(result))
        assert "density_buffer_m" not in result.metadata["crime"]

    def test_cdmx_scoring_is_unbuffered(self, fixture_places: dict) -> None:
        result = _score(load_city_context("cdmx"), fixture_places)
        assert all("crime_buffer_m" not in p for p in _properties(result))
        assert list(result.metadata["crime"]) == [
            "records_total",
            "records_recent_12m",
            "latest_date",
            "recent_start_date",
        ]
