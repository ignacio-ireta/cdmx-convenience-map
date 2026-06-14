"""Unit tests for the routing abstraction: codec, cache, and Router protocol."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from cdmxmap.config import WORK_TRAVEL_MODES
from cdmxmap.errors import ConfigError
from cdmxmap.routing import get_road_router
from cdmxmap.routing.base import ROUTING_MODES, RouteMatrix, Router
from cdmxmap.routing.cache import RouteCacheKey, RoutingCache
from cdmxmap.routing.matrix_codec import (
    MATRIX_SCALE,
    MATRIX_SENTINEL,
    build_matrix_index,
    decode_matrix,
    encode_matrix,
    extract_column,
)


def test_routing_modes_match_config() -> None:
    # base.py duplicates the mode triple to avoid an import cycle; keep them equal.
    assert ROUTING_MODES == WORK_TRAVEL_MODES


class TestRouterFactory:
    def test_none_returns_no_router(self) -> None:
        assert get_road_router(None) is None
        assert get_road_router("none") is None
        assert get_road_router("") is None

    def test_unknown_engine_raises(self) -> None:
        with pytest.raises(ConfigError):
            get_road_router("graphhopper")

    def test_valhalla_without_extra_or_tiles_raises_actionable_error(self) -> None:
        # Whether pyvalhalla is absent (ImportError) or present without tiles, the
        # factory must raise an actionable ConfigError, never a cryptic crash.
        with pytest.raises(ConfigError):
            get_road_router("valhalla", tiles_dir="/nonexistent/valhalla/tiles")


def test_stub_router_satisfies_protocol(stub_router) -> None:
    assert isinstance(stub_router, Router)
    result = stub_router.matrix([(19.43, -99.13)], [(19.44, -99.14)], "driving")
    assert isinstance(result, RouteMatrix)
    assert result.shape == (1, 1)
    assert np.isfinite(result.minutes[0, 0])
    assert result.minutes[0, 0] > 0


def test_stub_router_unreachable_is_nan(make_stub_router) -> None:
    router = make_stub_router(unreachable=lambda origin, target: True)
    result = router.matrix([(19.43, -99.13)], [(19.44, -99.14)], "walking")
    assert np.isnan(result.minutes[0, 0])


class TestMatrixCodec:
    def test_round_trip_preserves_values(self) -> None:
        minutes = np.array([[0.0, 12.3, 45.6], [7.1, 0.0, 99.9]])
        data = encode_matrix(minutes)
        decoded = decode_matrix(data, 2, 3)
        np.testing.assert_allclose(decoded, minutes, atol=1.0 / MATRIX_SCALE)

    def test_destination_major_column_extraction(self) -> None:
        # Pin the axis convention: a destination column = one contiguous block.
        minutes = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])  # [origin, destination]
        data = encode_matrix(minutes)
        # Column for destination 1 must be origins -> dest1 = [2, 4, 6].
        column = extract_column(data, n_origins=3, destination_index=1)
        np.testing.assert_allclose(column, [2.0, 4.0, 6.0], atol=1.0 / MATRIX_SCALE)
        column0 = extract_column(data, n_origins=3, destination_index=0)
        np.testing.assert_allclose(column0, [1.0, 3.0, 5.0], atol=1.0 / MATRIX_SCALE)

    def test_unreachable_and_overflow_become_nan(self) -> None:
        minutes = np.array([[np.nan, np.inf], [-5.0, 1e9]])
        decoded = decode_matrix(encode_matrix(minutes), 2, 2)
        assert np.isnan(decoded).all()

    def test_sentinel_constant_round_trips_to_nan(self) -> None:
        raw = (np.array([[MATRIX_SENTINEL]], dtype="<u2")).tobytes(order="F")
        assert np.isnan(decode_matrix(raw, 1, 1)[0, 0])

    def test_decode_rejects_wrong_length(self) -> None:
        with pytest.raises(ValueError):
            decode_matrix(b"\x00\x01\x02", 2, 2)

    def test_build_index_records_axis_and_provenance(self) -> None:
        index = build_matrix_index(
            area_unit="postal_code",
            area_ids=["a", "b"],
            mode_files={"driving": "m_driving.bin"},
            engine="valhalla",
            version="3.4",
            profiles={"driving": "auto"},
            inputs_hash="abc",
            osm_source="https://example/x.pbf",
            osm_sha="deadbeef",
            osm_date="2026-06-13",
            generated_at="2026-06-13T00:00:00+00:00",
        )
        assert index["n"] == 2
        assert index["axis0"] == "origin" and index["axis1"] == "destination"
        assert index["layout"] == "destination_major"
        assert index["dtype"] == "<u2"
        assert index["mode_files"]["driving"] == "m_driving.bin"


class TestRoutingCache:
    def _key(self, **overrides) -> RouteCacheKey:
        base = dict(
            area_unit="postal_code",
            area_id="11510",
            origin=(19.43, -99.13),
            destination=(19.40, -99.17),
            mode="driving",
            engine="valhalla",
            version="3.4.0",
            profile="auto",
            inputs_hash="hash-1",
        )
        base.update(overrides)
        return RouteCacheKey(**base)

    def test_digest_is_stable_and_sensitive(self) -> None:
        assert self._key().digest() == self._key().digest()
        assert self._key().digest() != self._key(mode="walking").digest()
        assert self._key().digest() != self._key(inputs_hash="hash-2").digest()
        # Coordinate noise below the rounding precision must not change the key.
        assert self._key().digest() == self._key(origin=(19.4300000004, -99.13)).digest()

    def test_disabled_cache_is_noop(self) -> None:
        cache = RoutingCache(path=None, enabled=False)
        cache.set(self._key(), 10.0, 5000.0)
        assert cache.get(self._key()) is None
        assert cache.stats()["entries"] == 0

    def test_hit_miss_and_persistence(self, tmp_path: Path) -> None:
        path = tmp_path / "routes.json"
        cache = RoutingCache(path=path)
        assert cache.get(self._key()) is None  # miss
        cache.set(self._key(), 12.5, 6200.0)
        got = cache.get(self._key())
        assert got == (12.5, 6200.0)  # hit
        assert cache.stats() == {"hits": 1, "misses": 1, "entries": 1}
        cache.save()

        reloaded = RoutingCache(path=path)
        assert reloaded.get(self._key()) == (12.5, 6200.0)

    def test_corrupt_cache_starts_fresh(self, tmp_path: Path) -> None:
        path = tmp_path / "routes.json"
        path.write_text("{not valid json", encoding="utf-8")
        cache = RoutingCache(path=path)
        assert cache.stats()["entries"] == 0


FIXTURE_AREAS = Path(__file__).parents[1] / "fixtures" / "fixture_city" / "areas.geojson"


class TestMatrixBuild:
    def test_build_writes_binary_and_index_with_correct_axis(self, stub_router, tmp_path) -> None:
        from cdmxmap.models import AREA_CONFIGS
        from cdmxmap.routing.matrix_build import build_area_matrix
        from cdmxmap.routing.matrix_codec import extract_column
        from cdmxmap.scoring.areas import area_representative_latlon

        out, pub = tmp_path / "processed", tmp_path / "public"
        summary = build_area_matrix(
            config=AREA_CONFIGS["colonia"],
            input_path=FIXTURE_AREAS,
            router=stub_router,
            modes=("driving", "walking"),
            output_dir=out,
            public_dir=pub,
        )
        assert summary["n"] == 3 and not summary["skipped"]

        index = json.loads((out / "routing_matrix_colonia_index.json").read_text())
        assert index["n"] == 3
        assert index["axis0"] == "origin" and index["axis1"] == "destination"
        assert (pub / "routing_matrix_colonia_index.json").exists()

        # End-to-end axis check: the on-disk destination column must equal a direct
        # origins -> that-destination route.
        _, latlon = area_representative_latlon(FIXTURE_AREAS, AREA_CONFIGS["colonia"])
        expected = stub_router.matrix(latlon, latlon, "driving").minutes
        data = (pub / index["mode_files"]["driving"]).read_bytes()
        for dest in range(3):
            column = extract_column(data, 3, dest)
            np.testing.assert_allclose(column, expected[:, dest], atol=0.1)

    def test_rebuild_skips_when_current(self, stub_router, tmp_path) -> None:
        from cdmxmap.models import AREA_CONFIGS
        from cdmxmap.routing.matrix_build import build_area_matrix

        kwargs = dict(
            config=AREA_CONFIGS["colonia"],
            input_path=FIXTURE_AREAS,
            router=stub_router,
            modes=("driving",),
            output_dir=tmp_path / "processed",
            public_dir=tmp_path / "public",
        )
        assert not build_area_matrix(**kwargs)["skipped"]
        assert build_area_matrix(**kwargs)["skipped"]
        assert not build_area_matrix(**kwargs, force=True)["skipped"]
