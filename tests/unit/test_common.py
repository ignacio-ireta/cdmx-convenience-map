"""Unit tests for shared IO/config helpers (cdmxmap.sources.io)."""

from __future__ import annotations

import pytest

from cdmxmap.sources import io as common


class TestElementCenter:
    def test_direct_lat_lon(self) -> None:
        assert common.element_center({"lat": 19.4, "lon": -99.1}) == (19.4, -99.1)

    def test_nested_center(self) -> None:
        assert common.element_center({"center": {"lat": 1, "lon": 2}}) == (1.0, 2.0)

    def test_missing_returns_none(self) -> None:
        assert common.element_center({}) is None
        assert common.element_center({"center": {"lat": 1}}) is None


class TestCityProfile:
    def test_loads_cdmx_profile(self) -> None:
        profile = common.load_city_profile("cdmx")
        assert profile["city_id"] == "cdmx"
        assert "bbox" in profile

    def test_missing_city_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            common.load_city_profile("atlantis")

    def test_city_bbox_returns_floats(self) -> None:
        bbox = common.city_bbox("cdmx")
        assert set(bbox) == {"south", "west", "north", "east"}
        assert all(isinstance(value, float) for value in bbox.values())
        assert bbox["south"] < bbox["north"]
        assert bbox["west"] < bbox["east"]
