"""Tests for the processed-output validator (scripts/validate_processed.py).

This pins the data contract (engineering standards §G): a feature must carry
every identity/distance/time/score/transit/crime field in valid ranges.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import validate_processed as vp


def make_props() -> dict:
    props: dict = {field: "x" for field in vp.GENERIC_FIELDS}
    props["area_unit"] = "postal_code"
    props["postal_code"] = "06700"
    props.update({field: 100.0 for field in vp.DISTANCE_FIELDS})
    props.update({field: 5.0 for field in vp.TIME_FIELDS})
    props.update({field: 50.0 for field in vp.SCORE_FIELDS})
    props.update({field: None for field in vp.TRANSIT_COMMUTE_FIELDS})
    props["transit_commute_source"] = "apimetro"
    props["time_work_transit_min"] = 30.0
    props.update({field: 0 for field in vp.CRIME_COUNT_FIELDS})
    return props


def write_collection(path: Path, props: dict) -> Path:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0, 0]},
                "properties": props,
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestAssertNumber:
    def test_accepts_in_range(self) -> None:
        vp.assert_number(50, minimum=0, maximum=100)

    def test_rejects_below_minimum(self) -> None:
        with pytest.raises(AssertionError):
            vp.assert_number(-1, minimum=0)

    def test_rejects_non_finite(self) -> None:
        with pytest.raises(AssertionError):
            vp.assert_number(float("nan"), minimum=0)

    def test_optional_number_allows_none(self) -> None:
        assert vp.assert_optional_number(None, minimum=0) is False
        assert vp.assert_optional_number(5, minimum=0) is True


class TestValidateGeojson:
    def test_valid_collection_passes(self, tmp_path: Path) -> None:
        path = write_collection(tmp_path / "scores.geojson", make_props())
        assert vp.validate_geojson(path) == 1

    def test_score_out_of_range_fails(self, tmp_path: Path) -> None:
        props = make_props()
        props["score_safety"] = 150.0
        path = write_collection(tmp_path / "bad_score.geojson", props)
        with pytest.raises(AssertionError):
            vp.validate_geojson(path)

    def test_missing_identity_field_fails(self, tmp_path: Path) -> None:
        props = make_props()
        props["area_name"] = ""
        path = write_collection(tmp_path / "missing.geojson", props)
        with pytest.raises(AssertionError):
            vp.validate_geojson(path)

    def test_requires_a_transit_estimate(self, tmp_path: Path) -> None:
        props = make_props()
        props["time_work_transit_min"] = None
        path = write_collection(tmp_path / "no_transit.geojson", props)
        with pytest.raises(AssertionError):
            vp.validate_geojson(path)
