"""Tests for the processed-output validator (scripts/validate_processed.py).

This pins the data contract (engineering standards §G): a feature must carry
every identity/distance/time/score/transit/crime field in valid ranges.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cdmxmap import validate as vp


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

    def test_routed_fields_optional_and_nullable(self, tmp_path: Path) -> None:
        props = make_props()
        props["dist_work_routed_m"] = 2500  # routed row
        props["dist_gym_routed_m"] = None  # fell back -> null is allowed
        props["work_travel_time_source"] = "valhalla_free_flow"
        path = write_collection(tmp_path / "routed.geojson", props)
        assert vp.validate_geojson(path) == 1

    def test_routed_distance_negative_fails(self, tmp_path: Path) -> None:
        props = make_props()
        props["dist_work_routed_m"] = -10
        path = write_collection(tmp_path / "bad_routed.geojson", props)
        with pytest.raises(AssertionError):
            vp.validate_geojson(path)

    def test_source_field_must_be_scalar_string(self, tmp_path: Path) -> None:
        props = make_props()
        props["work_travel_time_source"] = ["valhalla_free_flow"]  # array is invalid
        path = write_collection(tmp_path / "list_source.geojson", props)
        with pytest.raises(AssertionError):
            vp.validate_geojson(path)


def _stats_ctx():
    from dataclasses import replace

    from cdmxmap.citycontext import load_city_context

    return replace(load_city_context(), city_id="stats_city", crime_mode="city_statistics")


def make_stats_props() -> dict:
    props = make_props()
    for field in vp.CRIME_COUNT_FIELDS:
        del props[field]
    props.update({field: 10.0 for field in vp.CRIME_STATISTICS_NUMBER_FIELDS})
    props["crime_statistics_scope"] = "municipality"
    props["crime_statistics_area"] = "Monterrey"
    props["crime_statistics_period"] = "2025-11-01/2026-10-31"
    return props


class TestStatisticsMode:
    def test_valid_statistics_feature_passes(self, tmp_path: Path) -> None:
        path = write_collection(tmp_path / "stats.geojson", make_stats_props())
        assert vp.validate_geojson(path, ctx=_stats_ctx()) == 1

    def test_incident_mode_still_requires_incident_counts(self, tmp_path: Path) -> None:
        path = write_collection(tmp_path / "stats.geojson", make_stats_props())
        with pytest.raises(AssertionError):
            vp.validate_geojson(path)  # CDMX context: incident fields are required

    @pytest.mark.parametrize("field", vp.CRIME_STATISTICS_NUMBER_FIELDS)
    def test_negative_or_missing_statistic_fails(self, tmp_path: Path, field: str) -> None:
        for bad in (-1.0, None):
            props = make_stats_props()
            props[field] = bad
            path = write_collection(tmp_path / f"bad_{field}.geojson", props)
            with pytest.raises(AssertionError):
                vp.validate_geojson(path, ctx=_stats_ctx())

    @pytest.mark.parametrize("field", vp.CRIME_STATISTICS_TEXT_FIELDS)
    def test_empty_statistics_text_fails(self, tmp_path: Path, field: str) -> None:
        props = make_stats_props()
        props[field] = " "
        path = write_collection(tmp_path / f"empty_{field}.geojson", props)
        with pytest.raises(AssertionError, match=field):
            vp.validate_geojson(path, ctx=_stats_ctx())

    def test_incident_fields_are_rejected_in_statistics_mode(self, tmp_path: Path) -> None:
        props = make_stats_props()
        props["crime_incidents_total"] = 0  # a fake zero
        path = write_collection(tmp_path / "fake_zero.geojson", props)
        with pytest.raises(AssertionError, match="must not carry incident fields"):
            vp.validate_geojson(path, ctx=_stats_ctx())


class TestProfileTransitSystems:
    @staticmethod
    def _profile_ctx():
        from dataclasses import replace

        from cdmxmap.citycontext import TransitSystemSpec, load_city_context

        return replace(
            load_city_context(),
            city_id="profile_city",
            profile={"transit_systems": [{"code": "RAIL", "slug": "rail"}]},
            transit_systems=(TransitSystemSpec("RAIL", "rail", "core"),),
        )

    def test_declared_system_without_stops_fails(self, tmp_path: Path) -> None:
        props = make_props()
        props["nearest_rail_transit_name"] = ""
        path = write_collection(tmp_path / "empty_system.geojson", props)
        with pytest.raises(AssertionError, match="'rail' has no stops"):
            vp.validate_geojson(path, ctx=self._profile_ctx())

    def test_declared_system_with_a_stop_passes(self, tmp_path: Path) -> None:
        props = make_props()
        props["nearest_rail_transit_name"] = "Estación Central"
        path = write_collection(tmp_path / "rail.geojson", props)
        assert vp.validate_geojson(path, ctx=self._profile_ctx()) == 1

    def test_cdmx_context_skips_the_check(self, tmp_path: Path) -> None:
        # The CDMX fixture has no RTP/CC stops; CDMX must keep validating.
        props = make_props()
        props["nearest_rtp_transit_name"] = ""
        path = write_collection(tmp_path / "cdmx.geojson", props)
        assert vp.validate_geojson(path) == 1


class TestCrimeBuffer:
    """``crime_buffer_m`` is optional; when present it must be a real radius."""

    def test_absent_buffer_passes(self, tmp_path: Path) -> None:
        props = make_props()
        assert vp.CRIME_BUFFER_FIELD not in props
        assert vp.validate_geojson(write_collection(tmp_path / "plain.geojson", props)) == 1

    def test_positive_buffer_passes(self, tmp_path: Path) -> None:
        props = make_props()
        props[vp.CRIME_BUFFER_FIELD] = 250
        assert vp.validate_geojson(write_collection(tmp_path / "buffer.geojson", props)) == 1

    @pytest.mark.parametrize("bad", [0, -250, None, "250", float("inf")])
    def test_non_positive_or_non_numeric_buffer_fails(self, tmp_path: Path, bad: object) -> None:
        props = make_props()
        props[vp.CRIME_BUFFER_FIELD] = bad
        path = write_collection(tmp_path / "bad_buffer.geojson", props)
        with pytest.raises(AssertionError):
            vp.validate_geojson(path)

    def test_zero_buffer_message_names_the_field(self, tmp_path: Path) -> None:
        props = make_props()
        props[vp.CRIME_BUFFER_FIELD] = 0
        path = write_collection(tmp_path / "zero_buffer.geojson", props)
        with pytest.raises(AssertionError, match="crime_buffer_m must be > 0"):
            vp.validate_geojson(path)
