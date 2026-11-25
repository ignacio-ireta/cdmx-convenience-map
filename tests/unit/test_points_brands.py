"""Store-brand toggles select their supermarket rows (scoring/points.py)."""

from __future__ import annotations

from pathlib import Path

from cdmxmap.citycontext import load_city_context
from cdmxmap.scoring.points import load_point_datasets

PLACES = {"workplace": {"name": "Work", "latitude": 20.70, "longitude": -103.40}}


def _write(path: Path, header: str, rows: list[str]) -> None:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


def _datasets(tmp_path: Path, city: str, brands: list[str]):
    _write(
        tmp_path / "transit_stops.csv",
        "id,name,system,line,hierarchy,latitude,longitude,source",
        ["s1,Stop,MITREN,L1,station,20.70,-103.40,test"],
    )
    _write(
        tmp_path / "supermarkets.csv",
        "name,brand,latitude,longitude,source",
        [f"Store {i},{brand},20.7{i},-103.4{i},test" for i, brand in enumerate(brands)],
    )
    _write(tmp_path / "gyms.csv", "name,latitude,longitude,source", ["Gym,20.70,-103.40,test"])
    return load_point_datasets(PLACES, ctx=load_city_context(city), data_dir=tmp_path)


def test_classifier_profile_matches_family_slugs_exactly(tmp_path: Path) -> None:
    # "chedraui" must not pick up a pool family whose slug merely contains it.
    datasets = _datasets(tmp_path, "guadalajara", ["chedraui", "chedraui_supercito", "sams"])
    assert datasets.supermarkets_by_brand["chedraui"]["brand"].tolist() == ["chedraui"]
    assert datasets.supermarkets_by_brand["sams"]["brand"].tolist() == ["sams"]
    assert len(datasets.supermarkets) == 3  # pool rows still count for "any supermarket"


def test_legacy_profile_keeps_substring_matching(tmp_path: Path) -> None:
    # Morelia's legacy brand column holds inferred names ("Aurrerá"); its match tokens
    # are substrings, exactly as before the classifier existed.
    datasets = _datasets(tmp_path, "morelia", ["Aurrerá", "Walmart", "Soriana"])
    assert datasets.supermarkets_by_brand["aurrera"]["brand"].tolist() == ["Aurrerá"]
    assert datasets.supermarkets_by_brand["walmart"]["brand"].tolist() == ["Walmart"]
