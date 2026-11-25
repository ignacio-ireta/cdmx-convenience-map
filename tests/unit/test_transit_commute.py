"""Tests for the stop-pair transit-commute approximation's opt-in options (spec §4.5).

Every option defaults to the historical behavior, so CDMX output is unchanged;
the CDMX goldens pin that end to end and ``TestDefaults`` pins it here.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from cdmxmap.transit_commute import (
    TransitCommuteConfig,
    estimate_transit_commute_to_work,
    transit_commute_metadata,
)
from cdmxmap.transit_commute.approximate import _lines_match, _system_speed_kmh

FIXTURE_CITY = Path(__file__).parents[1] / "fixtures" / "fixture_city"
METRIC_CRS = "EPSG:32614"
HISTORICAL_METADATA_KEYS = [
    "source",
    "candidate_stop_count",
    "walking_speed_kmh",
    "speeds_kmh",
    "penalties_min",
    "max_walk_m",
]
HISTORICAL_SPEED_KEYS = ["metro", "metrobus", "bus", "trolleybus", "default_transit"]


def _stops(rows: list[tuple[str, str, str, float, float]]) -> gpd.GeoDataFrame:
    """``(name, system, line, lat, lon)`` rows as a WGS84 stop GeoDataFrame."""
    frame = pd.DataFrame(rows, columns=["name", "system", "line", "latitude", "longitude"])
    return gpd.GeoDataFrame(
        frame,
        geometry=gpd.points_from_xy(frame["longitude"], frame["latitude"]),
        crs="EPSG:4326",
    )


def _one_area(lat: float, lon: float, half: float = 0.0005) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"area_unit": ["postal_code"], "area_id": ["A1"]},
        geometry=[box(lon - half, lat - half, lon + half, lat + half)],
        crs="EPSG:4326",
    )


def _estimate(
    areas: gpd.GeoDataFrame,
    stops: gpd.GeoDataFrame,
    workplace: tuple[float, float],
    config: TransitCommuteConfig | dict | None,
) -> pd.DataFrame:
    return estimate_transit_commute_to_work(
        areas, stops, workplace[0], workplace[1], config, metric_crs=METRIC_CRS
    )


class TestConfigParsing:
    def test_new_fields_default_to_historical_behavior(self) -> None:
        config = TransitCommuteConfig.from_mapping({"source": "x"})
        assert config.system_speeds_kmh == {}
        assert config.has_line_data is False
        assert config.priority_candidate_systems == ()
        assert config.priority_candidate_stop_count == 0
        assert config.priority_candidates_enabled is False

    def test_new_fields_are_parsed_not_floated(self) -> None:
        config = TransitCommuteConfig.from_mapping(
            {
                "has_line_data": True,
                "system_speeds_kmh": {"metro": 28, " BRT ": "18"},
                "priority_candidate_systems": ["metro", "BRT", "metro"],
                "priority_candidate_stop_count": 99,
            }
        )
        assert config.has_line_data is True
        assert config.system_speeds_kmh == {"METRO": 28.0, "BRT": 18.0}
        assert config.priority_candidate_systems == ("METRO", "BRT")
        assert config.priority_candidate_stop_count == 25  # clamped
        assert config.priority_candidates_enabled is True

    def test_string_flag_is_parsed(self) -> None:
        assert TransitCommuteConfig.from_mapping({"has_line_data": "false"}).has_line_data is False
        assert TransitCommuteConfig.from_mapping({"has_line_data": "true"}).has_line_data is True

    def test_non_positive_speed_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            TransitCommuteConfig.from_mapping({"system_speeds_kmh": {"BUS": 0}})

    def test_committed_profile_settings_parse(self) -> None:
        from cdmxmap.config import load_places_config, transit_commute_config

        monterrey = transit_commute_config(load_places_config("monterrey"))
        assert monterrey.has_line_data is True
        assert monterrey.system_speeds_kmh["METRO"] == 28.0
        assert monterrey.priority_candidate_systems == ("METRO", "BRT")
        assert monterrey.priority_candidate_stop_count == 3
        guadalajara = transit_commute_config(load_places_config("guadalajara"))
        assert guadalajara.priority_candidate_systems == ("MITREN", "MIMACRO")
        assert guadalajara.system_speeds_kmh["MITREN"] == 30.0


class TestDefaults:
    def test_default_metadata_keeps_its_historical_shape(self) -> None:
        metadata = TransitCommuteConfig().to_metadata()
        assert list(metadata) == HISTORICAL_METADATA_KEYS
        assert list(metadata["speeds_kmh"]) == HISTORICAL_SPEED_KEYS
        limitations = transit_commute_metadata(None)["known_limitations"]
        assert "the current Apimetro cache does not include line/order fields" in limitations[1]

    def test_empty_options_reproduce_the_default_estimate(self) -> None:
        areas = gpd.read_file(FIXTURE_CITY / "areas.geojson")
        frame = pd.read_csv(FIXTURE_CITY / "transit_stops.csv")
        stops = gpd.GeoDataFrame(
            frame,
            geometry=gpd.points_from_xy(frame["longitude"], frame["latitude"]),
            crs="EPSG:4326",
        )
        workplace = (19.41, -99.14)
        baseline = _estimate(areas, stops, workplace, None)
        explicit = _estimate(
            areas,
            stops,
            workplace,
            {
                "system_speeds_kmh": {},
                "has_line_data": False,
                "priority_candidate_systems": ["METRO"],
                "priority_candidate_stop_count": 0,  # systems listed but disabled
            },
        )
        pd.testing.assert_frame_equal(baseline, explicit)
        # The fixture exercises all three historical complexities.
        assert set(baseline["transit_route_complexity"]) <= {
            "same_line",
            "same_system_different_line",
            "different_system",
        }


class TestLineMatching:
    @pytest.mark.parametrize(
        ("origin", "destination", "expected"),
        [
            ("L1", "l1", True),  # historical: case-insensitive equality
            ("L1", "L2", False),
            ("", "L1", False),
            ("L1", "", False),
            ("107|214", "214|300", True),  # share route 214
            ("107|214", "300", False),
            (" 214 | 107", "107", True),
            ("107|214", "1072", False),
            ("|", "|", False),
        ],
    )
    def test_lines_match(self, origin: str, destination: str, expected: bool) -> None:
        assert _lines_match(origin, destination) is expected

    def test_multi_route_stops_count_as_same_line_when_they_share_a_route(self) -> None:
        areas = _one_area(25.6700, -100.3100)
        workplace = (25.6500, -100.3300)

        def complexity(destination_line: str) -> str:
            stops = _stops(
                [
                    ("Origen", "BUS", "107|214", 25.6700, -100.3100),
                    ("Destino", "BUS", destination_line, 25.6501, -100.3301),
                ]
            )
            row = _estimate(areas, stops, workplace, None).iloc[0]
            return str(row["transit_route_complexity"])

        assert complexity("214|300") == "same_line"
        assert complexity("300") == "same_system_different_line"


class TestSystemSpeeds:
    def test_configured_speed_is_checked_first(self) -> None:
        config = TransitCommuteConfig.from_mapping({"system_speeds_kmh": {"METRO": 40}})
        assert _system_speed_kmh("METRO", config) == 40.0
        assert _system_speed_kmh("MB", config) == config.metrobus_speed_kmh
        assert _system_speed_kmh("ECOVIA", config) == config.default_transit_speed_kmh

    def test_speed_changes_the_estimate(self) -> None:
        areas = _one_area(25.6700, -100.3100)
        stops = _stops(
            [
                ("Origen", "TREN", "1", 25.6700, -100.3100),
                ("Destino", "TREN", "1", 25.6300, -100.3500),
            ]
        )
        workplace = (25.6300, -100.3500)
        default = _estimate(areas, stops, workplace, None).iloc[0]["time_work_transit_min"]
        fast = _estimate(areas, stops, workplace, {"system_speeds_kmh": {"TREN": 48}}).iloc[0][
            "time_work_transit_min"
        ]
        assert fast < default  # 48 km/h beats the 16 km/h default

    def test_metadata_lists_system_speeds_only_when_set(self) -> None:
        config = TransitCommuteConfig.from_mapping({"system_speeds_kmh": {"METRO": 30}})
        speeds = config.to_metadata()["speeds_kmh"]
        assert list(speeds) == [*HISTORICAL_SPEED_KEYS, "systems"]
        assert speeds["systems"] == {"METRO": 30.0}


class TestPriorityCandidates:
    """Dense bus stops crowd a slightly farther metro out of the nearest-N pool."""

    AREA = (25.6700, -100.3100)
    WORKPLACE = (25.6300, -100.3500)

    def _stops(self) -> gpd.GeoDataFrame:
        return _stops(
            [
                ("Bus cerca", "BUS", "R1", 25.6701, -100.3101),
                ("Bus oficina", "BUS", "R9", 25.6301, -100.3501),
                ("Metro barrio", "METRO", "1", 25.6720, -100.3120),
                ("Metro oficina", "METRO", "1", 25.6320, -100.3520),
            ]
        )

    def _row(self, extra: dict) -> pd.Series:
        config = {"candidate_stop_count": 1, "system_speeds_kmh": {"METRO": 35}, **extra}
        return _estimate(_one_area(*self.AREA), self._stops(), self.WORKPLACE, config).iloc[0]

    def test_without_priority_only_the_nearest_stops_are_considered(self) -> None:
        row = self._row({})
        assert row["transit_origin_stop_name"] == "Bus cerca"
        assert row["transit_route_complexity"] == "same_system_different_line"

    def test_priority_system_stops_join_the_candidates(self) -> None:
        row = self._row(
            {"priority_candidate_systems": ["METRO"], "priority_candidate_stop_count": 1}
        )
        assert row["transit_origin_stop_name"] == "Metro barrio"
        assert row["transit_destination_stop_name"] == "Metro oficina"
        assert row["transit_route_complexity"] == "same_line"
        assert row["time_work_transit_min"] < self._row({})["time_work_transit_min"]

    def test_unknown_priority_system_is_a_no_op(self) -> None:
        base = self._row({})
        other = self._row(
            {"priority_candidate_systems": ["NOPE"], "priority_candidate_stop_count": 3}
        )
        pd.testing.assert_series_equal(base, other)

    def test_metadata_records_priority_candidates(self) -> None:
        config = TransitCommuteConfig.from_mapping(
            {"priority_candidate_systems": ["METRO"], "priority_candidate_stop_count": 2}
        )
        assert config.to_metadata()["priority_candidates"] == {
            "systems": ["METRO"],
            "stop_count": 2,
        }


class TestLineDataLimitation:
    def test_has_line_data_replaces_the_missing_line_limitation(self) -> None:
        limitations = transit_commute_metadata(
            {"stop_source_label": "Nuevo León open data", "has_line_data": True}
        )["known_limitations"]
        assert limitations[1] == (
            "Line ids come from Nuevo León open data; stops served by several routes list "
            "them joined by '|', and a pair counts as same-line when they share any route."
        )
        assert not any("does not include line/order fields" in item for item in limitations)


class TestStopNamePrefix:
    """Label-prefixed stop names ("Metrorrey L1 · Cuauhtémoc") lose the label only when
    the stop cache declares line data; CDMX's "<CODE> · <stop>" rule is unchanged."""

    STOPS = [
        ("Metrorrey L1 · Cuauhtémoc", "METRO", "L1", 19.4300, -99.1300),
        ("METRO · Polanco", "METRO", "L1", 19.4400, -99.1300),
    ]

    def _names(self, config: dict | None) -> tuple[str, str]:
        frame = _estimate(
            _one_area(19.4300, -99.1300), _stops(self.STOPS), (19.4400, -99.1300), config
        )
        row = frame.iloc[0]
        return row["transit_origin_stop_name"], row["transit_destination_stop_name"]

    def test_default_strips_only_the_code_prefix(self) -> None:
        assert self._names(None) == ("Metrorrey L1 · Cuauhtémoc", "Polanco")

    def test_line_data_cache_strips_the_label_prefix(self) -> None:
        assert self._names({"has_line_data": True}) == ("Cuauhtémoc", "Polanco")
