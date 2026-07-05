from __future__ import annotations

import pytest

from cdmxmap.citycontext import load_city_context
from cdmxmap.errors import ConfigError
from cdmxmap.scoring.points import load_workplaces


@pytest.mark.parametrize("city", ["oslo", "bergen", "trondheim", "stavanger"])
def test_norwegian_profile_is_runnable(city: str) -> None:
    ctx = load_city_context(city)

    assert set(ctx.area_configs) == {"postal_code"}
    assert ctx.weights["safety"] == 0
    assert ctx.metric_crs == "EPSG:25832"
    assert [brand.slug for brand in ctx.store_brands] == [
        "rema",
        "kiwi",
        "coop",
        "meny",
        "joker",
        "bunnpris",
    ]
    assert ctx.raw_dir.name == city
    assert ctx.data_dir.name == city


def test_incomplete_city_profile_fails_before_cli_execution(monkeypatch) -> None:
    incomplete = {
        "city_id": "incomplete",
        "crs_metric_epsg": 32632,
        "bbox": {"south": 1.0, "west": 1.0, "north": 2.0, "east": 2.0},
    }
    monkeypatch.setattr("cdmxmap.citycontext.load_city_profile", lambda city: incomplete)
    with pytest.raises(ConfigError, match="complete area_units"):
        load_city_context("incomplete")


def test_workplace_fallback_uses_the_city_raw_directory(tmp_path) -> None:
    city_raw = tmp_path / "oslo"
    city_raw.mkdir()
    (city_raw / "workplaces.csv").write_text(
        "name,latitude,longitude\nOslo reference,59.91,10.75\n",
        encoding="utf-8",
    )

    workplaces = load_workplaces({}, raw_dir=city_raw, metric_crs="EPSG:25832")

    assert workplaces.iloc[0]["name"] == "Oslo reference"
