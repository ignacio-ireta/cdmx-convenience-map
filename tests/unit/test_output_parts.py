"""Parts publishing of large public GeoJSON layers (output/parts.py, validate.py)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import box

from cdmxmap.errors import ConfigError
from cdmxmap.models import build_area_configs
from cdmxmap.output import write_geojson
from cdmxmap.output.parts import (
    PARTS_INDEX_TYPE,
    part_name,
    parts_index_name,
    remove_geojson_parts,
    write_geojson_parts,
)
from cdmxmap.schema import validate_city_profile
from cdmxmap.validate import validate_public_parts

STEM = "scores_colonia"


def _areas(count: int = 40) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "area_unit": ["colonia"] * count,
            "area_id": [f"A{i:03d}" for i in range(count)],
            "area_name": [f"Colonia número {i} " + "x" * (i % 7) * 30 for i in range(count)],
            "score_total": [round(i * 2.5 % 100, 3) for i in range(count)],
        },
        geometry=[box(-100 + i * 0.01, 25, -100 + i * 0.01 + 0.009, 25.009) for i in range(count)],
        crs="EPSG:4326",
    )


def _single(tmp_path: Path, areas: gpd.GeoDataFrame) -> Path:
    path = tmp_path / "processed" / f"{STEM}.geojson"
    write_geojson(areas, path)
    return path


def _publish(public: Path, areas: gpd.GeoDataFrame, max_bytes: int, **kwargs):
    return write_geojson_parts(
        areas, public, stem=STEM, area_unit="colonia", max_bytes=max_bytes, **kwargs
    )


def test_parts_fit_the_budget_and_rejoin_to_the_single_file(tmp_path: Path) -> None:
    areas = _areas()
    single = _single(tmp_path, areas)
    budget = single.stat().st_size // 3
    published = _publish(tmp_path / "public", areas, budget)

    assert len(published.part_paths) >= 3
    assert all(path.stat().st_size <= budget for path in published.part_paths)
    joined = [
        feature
        for path in published.part_paths
        for feature in json.loads(path.read_text(encoding="utf-8"))["features"]
    ]
    assert joined == json.loads(single.read_text(encoding="utf-8"))["features"]
    assert validate_public_parts(published.index_path, processed_path=single) == len(areas)


def test_index_records_each_part(tmp_path: Path) -> None:
    areas = _areas()
    published = _publish(tmp_path / "public", areas, 6_000)
    index = json.loads(published.index_path.read_text(encoding="utf-8"))

    assert published.index_path.name == parts_index_name(STEM) == "scores_colonia_index.json"
    assert index["type"] == PARTS_INDEX_TYPE
    assert index["version"] == 1
    assert index["area_unit"] == "colonia"
    assert index["feature_count"] == len(areas)
    assert index["max_part_bytes"] == 6_000
    assert [part["path"] for part in index["parts"]] == [
        part_name(STEM, number) for number in range(1, len(index["parts"]) + 1)
    ]
    for part, path in zip(index["parts"], published.part_paths, strict=True):
        data = path.read_bytes()
        assert part["bytes"] == len(data)
        assert part["sha256"] == hashlib.sha256(data).hexdigest()
        assert part["feature_count"] == len(json.loads(data)["features"])
    assert sum(part["feature_count"] for part in index["parts"]) == len(areas)


def test_a_layer_under_budget_is_one_part(tmp_path: Path) -> None:
    areas = _areas(5)
    published = _publish(tmp_path / "public", areas, 10_000_000)
    assert [path.name for path in published.part_paths] == ["scores_colonia.part-01.geojson"]


def test_size_hint_only_sets_the_first_attempt(tmp_path: Path) -> None:
    areas = _areas()
    single = _single(tmp_path, areas)
    budget = single.stat().st_size // 3
    plain = _publish(tmp_path / "a", areas, budget)
    hinted = _publish(tmp_path / "b", areas, budget, size_hint=single.stat().st_size)
    assert [p.read_bytes() for p in plain.part_paths] == [p.read_bytes() for p in hinted.part_paths]


def test_publishing_is_deterministic(tmp_path: Path) -> None:
    areas = _areas()
    first = _publish(tmp_path / "a", areas, 6_000)
    second = _publish(tmp_path / "b", areas, 6_000)
    assert first.index_path.read_bytes() == second.index_path.read_bytes()
    assert [p.read_bytes() for p in first.part_paths] == [p.read_bytes() for p in second.part_paths]


def test_stale_parts_and_the_single_copy_are_removed(tmp_path: Path) -> None:
    public = tmp_path / "public"
    public.mkdir()
    stale = [part_name(STEM, 7), part_name(STEM, 12), f"{STEM}.geojson"]
    unrelated = ["scores_postal_code.geojson", "scores_colonia.part-1.geojson", "notes.txt"]
    for name in stale + unrelated:
        (public / name).write_text("{}", encoding="utf-8")

    published = _publish(public, _areas(), 6_000)

    names = sorted(path.name for path in public.iterdir())
    expected = sorted(
        [published.index_path.name, *(p.name for p in published.part_paths), *unrelated]
    )
    assert names == expected  # no temp dir left behind either


def test_remove_geojson_parts_leaves_other_layers(tmp_path: Path) -> None:
    public = tmp_path / "public"
    published = _publish(public, _areas(), 6_000)
    (public / "scores_postal_code.part-01.geojson").write_text("{}", encoding="utf-8")
    (public / f"{STEM}.geojson").write_text("{}", encoding="utf-8")

    remove_geojson_parts(public, STEM)

    assert not published.index_path.exists()
    assert not any(path.exists() for path in published.part_paths)
    assert sorted(p.name for p in public.iterdir()) == [
        "scores_colonia.geojson",
        "scores_postal_code.part-01.geojson",
    ]


@pytest.mark.parametrize("max_bytes", [0, -1])
def test_non_positive_budget_is_rejected(tmp_path: Path, max_bytes: int) -> None:
    with pytest.raises(ValueError, match="must be positive"):
        _publish(tmp_path / "public", _areas(), max_bytes)


def test_empty_layer_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no features"):
        _publish(tmp_path / "public", _areas().iloc[0:0], 6_000)


def test_a_feature_larger_than_the_budget_fails_and_leaves_no_files(tmp_path: Path) -> None:
    public = tmp_path / "public"
    with pytest.raises(ValueError, match="at most 100 bytes"):
        _publish(public, _areas(4), 100)
    assert list(public.iterdir()) == []


class TestValidatePublicParts:
    @pytest.fixture
    def published(self, tmp_path: Path):
        areas = _areas()
        single = _single(tmp_path, areas)
        return _publish(tmp_path / "public", areas, 6_000), single

    def _rewrite_index(self, index_path: Path, edit) -> None:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        edit(index)
        index_path.write_text(json.dumps(index), encoding="utf-8")

    def test_tampered_part_fails_the_checksum(self, published) -> None:
        parts, _single_path = published
        path = parts.part_paths[0]
        data = path.read_bytes()
        path.write_bytes(data.replace(b"A000", b"B000"))
        with pytest.raises(AssertionError, match="SHA-256"):
            validate_public_parts(parts.index_path)

    def test_a_part_over_the_caller_limit_fails(self, published) -> None:
        parts, _single_path = published
        with pytest.raises(AssertionError, match="over the 1000-byte part limit"):
            validate_public_parts(parts.index_path, max_bytes=1_000)

    def test_a_part_path_outside_the_directory_fails(self, published) -> None:
        parts, _single_path = published

        def escape(index: dict) -> None:
            index["parts"][0]["path"] = "../scores_colonia.part-01.geojson"

        self._rewrite_index(parts.index_path, escape)
        with pytest.raises(AssertionError, match="bare file name"):
            validate_public_parts(parts.index_path)

    def test_a_reordered_index_fails_against_the_processed_file(self, published) -> None:
        parts, single = published
        self._rewrite_index(parts.index_path, lambda index: index["parts"].reverse())
        validate_public_parts(parts.index_path)  # still self-consistent on its own
        with pytest.raises(AssertionError, match="differ from"):
            validate_public_parts(parts.index_path, processed_path=single)

    def test_a_wrong_total_fails(self, published) -> None:
        parts, _single_path = published
        self._rewrite_index(parts.index_path, lambda index: index.update(feature_count=1))
        with pytest.raises(AssertionError, match="index says 1"):
            validate_public_parts(parts.index_path)

    def test_a_non_index_file_fails(self, tmp_path: Path) -> None:
        path = tmp_path / "x_index.json"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
        with pytest.raises(AssertionError, match="parts index"):
            validate_public_parts(path)


class TestProfileSetting:
    def _profile(self, value: object) -> dict:
        return {
            "city_id": "x",
            "bbox": {"south": 0, "west": 0, "north": 1, "east": 1},
            "area_units": [
                {
                    "area_unit": "colonia",
                    "default_input": "c.geojson",
                    "public_part_max_bytes": value,
                }
            ],
        }

    def test_parsed_into_the_area_config(self, tmp_path: Path) -> None:
        profile = validate_city_profile(self._profile(9_000_000))
        configs = build_area_configs(profile, tmp_path)
        assert configs["colonia"].public_part_max_bytes == 9_000_000

    def test_absent_means_single_file(self, tmp_path: Path) -> None:
        profile = self._profile(1)
        del profile["area_units"][0]["public_part_max_bytes"]
        assert build_area_configs(profile, tmp_path)["colonia"].public_part_max_bytes is None

    @pytest.mark.parametrize("value", [0, -5, "9000000", 9.5, True])
    def test_must_be_a_positive_integer(self, value: object) -> None:
        with pytest.raises(ConfigError):
            validate_city_profile(self._profile(value))
