"""Tests for pydantic config validation (cdmxmap.schema)."""

from __future__ import annotations

import pytest

from cdmxmap.config import load_places_config, road_routing_config
from cdmxmap.errors import ConfigError
from cdmxmap.schema import validate_city_profile, validate_places_config
from cdmxmap.sources.io import load_city_profile

VALID_CITY = {
    "city_id": "test",
    "bbox": {"south": 19.0, "west": -99.4, "north": 19.6, "east": -98.9},
}


class TestCityProfile:
    def test_committed_profiles_validate(self) -> None:
        # The real loaders run validation; both shipped profiles must pass.
        assert load_city_profile("cdmx")["city_id"] == "cdmx"
        assert load_city_profile("stavanger")["city_id"] == "stavanger"

    def test_returns_original_dict_unchanged(self) -> None:
        data = {**VALID_CITY, "notes": "extra keys are allowed"}
        assert validate_city_profile(data) is data

    def test_missing_city_id_raises(self) -> None:
        with pytest.raises(ConfigError):
            validate_city_profile({"bbox": VALID_CITY["bbox"]})

    def test_bbox_ordering_is_enforced(self) -> None:
        with pytest.raises(ConfigError):
            validate_city_profile(
                {"city_id": "x", "bbox": {"south": 20, "west": 1, "north": 5, "east": 2}}
            )
        with pytest.raises(ConfigError):
            validate_city_profile(
                {"city_id": "x", "bbox": {"south": 1, "west": 9, "north": 5, "east": 2}}
            )


class TestPlacesConfig:
    def test_committed_places_validates(self) -> None:
        assert isinstance(load_places_config(), dict)

    def test_rejects_non_numeric_workplace_latitude(self) -> None:
        with pytest.raises(ConfigError):
            validate_places_config({"workplace": {"latitude": "not-a-number", "longitude": -99.2}})

    def test_allows_partial_and_extra_keys(self) -> None:
        data = {"workplace": {"name": "Office"}, "travel_time": {"notes": "ok"}}
        assert validate_places_config(data) is data

    def test_committed_places_has_road_routing_block(self) -> None:
        assert "road_routing" in load_places_config()

    def test_rejects_non_integer_candidate_count(self) -> None:
        with pytest.raises(ConfigError):
            validate_places_config({"road_routing": {"candidate_count": "lots"}})


class TestRoadRoutingConfig:
    @staticmethod
    def _cfg(**road_routing) -> dict:
        return road_routing_config({"road_routing": road_routing})

    def test_defaults_when_absent(self) -> None:
        config = road_routing_config({})
        assert config["engine"] == "none"
        assert config["modes"] == ("driving", "walking", "biking")
        assert config["candidate_count"] == 5

    def test_engine_is_normalized(self) -> None:
        assert self._cfg(engine=" Valhalla ")["engine"] == "valhalla"

    def test_candidate_count_is_clamped(self) -> None:
        assert self._cfg(candidate_count=99)["candidate_count"] == 10
        assert self._cfg(candidate_count=-1)["candidate_count"] == 1
        assert self._cfg(candidate_count=0)["candidate_count"] == 5  # 0 -> default

    def test_unknown_modes_filtered_then_defaulted(self) -> None:
        assert self._cfg(modes=["driving", "flying"])["modes"] == ("driving",)
        assert self._cfg(modes=["flying"])["modes"] == ("driving", "walking", "biking")
