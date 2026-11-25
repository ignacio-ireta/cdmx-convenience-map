"""Parts publishing end to end (build_area), and the committed public data.

``public_part_max_bytes`` on an area unit publishes the frontend copy as parts
plus an index while the processed output stays one file (output/parts.py). The
committed-data tests guard what CI cannot otherwise see: the repository's
pre-commit large-file limit is not run in CI.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path

import pytest

from cdmxmap.citycontext import CityContext, load_city_context
from cdmxmap.errors import ConfigError
from cdmxmap.pipeline import build_area
from cdmxmap.schema import validate_city_profile
from cdmxmap.sources.io import load_city_profile
from cdmxmap.validate import validate_geojson, validate_public_parts

ROOT = Path(__file__).parents[2]
STATS_CITY = ROOT / "tests" / "fixtures" / "fixture_city_stats"
STATS_CSVS = ("transit_stops.csv", "supermarkets.csv", "gyms.csv", "crime_statistics.csv")
PUBLIC_DATA = ROOT / "frontend" / "public" / "data"
PARTS_CITIES = ("monterrey", "guadalajara")


def _ctx(monkeypatch: pytest.MonkeyPatch, max_bytes: int | None) -> CityContext:
    data = json.loads((STATS_CITY / "city.json").read_text(encoding="utf-8"))
    profile = copy.deepcopy(validate_city_profile(data, city="fixture_stats"))
    if max_bytes is not None:
        profile["area_units"][0]["public_part_max_bytes"] = max_bytes
    monkeypatch.setattr("cdmxmap.citycontext.load_city_profile", lambda city: profile)
    return load_city_context("fixture_stats")


def _build(ctx: CityContext, data_dir: Path, public_dir: Path) -> Path:
    places = json.loads((STATS_CITY / "places.json").read_text(encoding="utf-8"))
    return build_area(
        "postal_code",
        ctx=ctx,
        input_path=STATS_CITY / "areas.geojson",
        places_config=places,
        data_dir=data_dir,
        public_dir=public_dir,
        skip_legacy=True,
    )


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    dest = tmp_path / "processed"
    dest.mkdir()
    for name in STATS_CSVS:
        shutil.copyfile(STATS_CITY / name, dest / name)
    return dest


def test_build_area_publishes_parts_and_back(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, tmp_path: Path
) -> None:
    public = tmp_path / "public"
    single = _build(_ctx(monkeypatch, None), data_dir, public)
    single_bytes = single.read_bytes()
    assert sorted(p.name for p in public.glob("scores_postal_code*")) == [
        "scores_postal_code.geojson"
    ]

    # Five fixture areas in parts of about two features each.
    budget = len(single_bytes) * 2 // 5
    out = _build(_ctx(monkeypatch, budget), data_dir, public)

    assert out.read_bytes() == single_bytes  # the processed file is unchanged
    assert validate_geojson(out, ctx=load_city_context("fixture_stats")) == 5
    index_path = public / "scores_postal_code_index.json"
    assert validate_public_parts(index_path, max_bytes=budget, processed_path=out) == 5
    index = json.loads(index_path.read_text(encoding="utf-8"))
    part_names = [part["path"] for part in index["parts"]]
    assert len(part_names) >= 2
    assert sorted(p.name for p in public.glob("scores_postal_code*")) == sorted(
        ["scores_postal_code_index.json", *part_names]
    )
    meta = json.loads((public / "score_metadata_postal_code.json").read_text(encoding="utf-8"))
    assert meta["outputs"]["public"].endswith("scores_postal_code_index.json")
    assert [Path(path).name for path in meta["outputs"]["public_parts"]] == part_names

    # Turning the setting off restores the single file and removes the parts.
    _build(_ctx(monkeypatch, None), data_dir, public)
    assert sorted(p.name for p in public.glob("scores_postal_code*")) == [
        "scores_postal_code.geojson"
    ]
    meta = json.loads((public / "score_metadata_postal_code.json").read_text(encoding="utf-8"))
    assert "public_parts" not in meta["outputs"]


def test_parts_need_a_separate_public_directory(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path
) -> None:
    with pytest.raises(ConfigError, match="public directory apart"):
        _build(_ctx(monkeypatch, 1_000_000), data_dir, data_dir)


def _pre_commit_max_bytes() -> int:
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    match = re.search(r"--maxkb=(\d+)", config)
    assert match, "check-added-large-files --maxkb not found in .pre-commit-config.yaml"
    return int(match.group(1)) * 1024


def test_every_published_data_file_fits_the_pre_commit_limit() -> None:
    limit = _pre_commit_max_bytes()
    too_large = {
        str(path.relative_to(ROOT)): path.stat().st_size
        for path in PUBLIC_DATA.rglob("*")
        if path.is_file() and path.stat().st_size > limit
    }
    assert too_large == {}


@pytest.mark.parametrize("city", PARTS_CITIES)
def test_committed_colonia_parts_match_their_index(city: str) -> None:
    unit = next(
        entry for entry in load_city_profile(city)["area_units"] if entry["area_unit"] == "colonia"
    )
    max_bytes = unit["public_part_max_bytes"]
    assert max_bytes <= _pre_commit_max_bytes()
    city_dir = PUBLIC_DATA / city
    count = validate_public_parts(city_dir / "scores_colonia_index.json", max_bytes=max_bytes)
    assert not (city_dir / "scores_colonia.geojson").exists()
    metadata = json.loads((city_dir / "score_metadata_colonia.json").read_text(encoding="utf-8"))
    assert metadata["feature_count"] == count
    assert metadata["outputs"]["public"].endswith(f"{city}/scores_colonia_index.json")
