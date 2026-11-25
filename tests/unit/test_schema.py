"""Tests for pydantic config validation (cdmxmap.schema)."""

from __future__ import annotations

import pytest

from cdmxmap.config import load_places_config, road_routing_config
from cdmxmap.errors import ConfigError
from cdmxmap.schema import validate_city_profile, validate_places_config
from cdmxmap.sources.io import DATA_CITIES, load_city_profile

COMMITTED_CITIES = sorted(path.name for path in DATA_CITIES.iterdir() if path.is_dir())

VALID_CITY = {
    "city_id": "test",
    "bbox": {"south": 19.0, "west": -99.4, "north": 19.6, "east": -98.9},
}


class TestCityProfile:
    @pytest.mark.parametrize(
        "city",
        [
            "cdmx",
            "oslo",
            "bergen",
            "trondheim",
            "stavanger",
            "drammen",
            "morelia",
            "monterrey",
            "guadalajara",
        ],
    )
    def test_committed_profiles_validate(self, city: str) -> None:
        # The real loaders run validation; every shipped profile must pass.
        assert load_city_profile(city)["city_id"] == city

    def test_every_city_directory_is_covered(self) -> None:
        assert {"monterrey", "guadalajara"} <= set(COMMITTED_CITIES)
        for city in COMMITTED_CITIES:
            assert load_city_profile(city)["city_id"] == city

    def test_rejects_unknown_crime_mode(self) -> None:
        with pytest.raises(ConfigError, match="crime_mode"):
            validate_city_profile({**VALID_CITY, "crime_mode": "vibes"})

    def test_accepts_both_crime_modes(self) -> None:
        for mode in ("incident_points", "city_statistics"):
            assert validate_city_profile({**VALID_CITY, "crime_mode": mode})["crime_mode"] == mode

    @pytest.mark.parametrize(
        "systems",
        [
            [{"code": "METRO", "slug": "metro", "group": "rail"}],  # unknown group
            [{"code": "METRO", "slug": "Metro Line"}],  # slug is not a field-name slug
            [{"code": "", "slug": "metro"}],
            [{"code": "METRO", "slug": "a"}, {"code": "metro", "slug": "b"}],  # dup code
            [{"code": "A", "slug": "metro"}, {"code": "B", "slug": "metro"}],  # dup slug
        ],
    )
    def test_rejects_malformed_transit_systems(self, systems: list[dict]) -> None:
        with pytest.raises(ConfigError):
            validate_city_profile({**VALID_CITY, "transit_systems": systems})

    @pytest.mark.parametrize("buffer_m", [0, 250])
    def test_accepts_a_whole_meter_density_buffer(self, buffer_m: int) -> None:
        data = {**VALID_CITY, "crime_source": {"density_buffer_m": buffer_m}}
        assert validate_city_profile(data)["crime_source"]["density_buffer_m"] == buffer_m

    @pytest.mark.parametrize("buffer_m", [-1, 12.5, "250", True])
    def test_rejects_a_malformed_density_buffer(self, buffer_m: object) -> None:
        with pytest.raises(ConfigError, match="density_buffer_m"):
            validate_city_profile({**VALID_CITY, "crime_source": {"density_buffer_m": buffer_m}})

    def test_accepts_scored_definition_and_offenses(self) -> None:
        block = {"scored_definition": "Robbery", "scored_offenses": ["Robo", "Extorsión"]}
        data = {**VALID_CITY, "crime_statistics": block}
        assert validate_city_profile(data)["crime_statistics"] is block

    @pytest.mark.parametrize("offenses", ["Robo", ["Robo", 3]])
    def test_rejects_malformed_scored_offenses(self, offenses: object) -> None:
        with pytest.raises(ConfigError, match="scored_offenses"):
            validate_city_profile({**VALID_CITY, "crime_statistics": {"scored_offenses": offenses}})

    def test_new_city_crime_blocks(self) -> None:
        monterrey = load_city_profile("monterrey")["crime_statistics"]
        assert monterrey["scored_label"] == "robbery and violent crime"
        assert monterrey["scored_definition"] and monterrey["scored_offenses"]
        assert load_city_profile("guadalajara")["crime_source"]["density_buffer_m"] == 250

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

    @pytest.mark.parametrize("city", COMMITTED_CITIES)
    def test_every_city_places_validates(self, city: str) -> None:
        # load_places_config validates; CDMX falls back to data/config/places.json.
        assert isinstance(load_places_config(city), dict)

    def test_rejects_non_positive_system_speed(self) -> None:
        with pytest.raises(ConfigError):
            validate_places_config({"transit_commute": {"system_speeds_kmh": {"BUS": 0}}})

    def test_rejects_non_boolean_line_flag(self) -> None:
        with pytest.raises(ConfigError):
            validate_places_config({"transit_commute": {"has_line_data": "sometimes"}})

    def test_rejects_non_object_search_filter(self) -> None:
        with pytest.raises(ConfigError):
            validate_places_config({"road_routing": {"search_filter": "residential"}})

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

    def test_new_keys_default_to_none(self) -> None:
        config = road_routing_config({})
        assert config["search_filter"] is None
        assert config["osm_md5"] is None
        assert config["osm_date"] is None
        assert self._cfg(search_filter={})["search_filter"] is None

    @pytest.mark.parametrize("city", ["monterrey", "guadalajara"])
    def test_mexican_cities_declare_snapping_and_osm_provenance(self, city: str) -> None:
        config = road_routing_config(load_places_config(city))
        assert config["search_filter"] == {"min_road_class": "residential"}
        assert config["osm_md5"] == "7140e40aaf94d08ebc0551a8880f3d9e"
        assert config["osm_date"] == "2026-11-24"
        assert config["tiles_dir"] == "data/processed/valhalla_mx"

    def test_unknown_modes_filtered_then_defaulted(self) -> None:
        assert self._cfg(modes=["driving", "flying"])["modes"] == ("driving",)
        assert self._cfg(modes=["flying"])["modes"] == ("driving", "walking", "biking")
