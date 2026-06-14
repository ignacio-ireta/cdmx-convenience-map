from __future__ import annotations

import pytest

from cdmxmap.citycontext import load_city_context
from cdmxmap.errors import ConfigError
from cdmxmap.scoring.points import load_workplaces


def test_oslo_profile_is_runnable() -> None:
    ctx = load_city_context("oslo")

    assert set(ctx.area_configs) == {"postal_code"}
    assert ctx.weights["safety"] == 0
    assert ctx.raw_dir.name == "oslo"
    assert ctx.data_dir.name == "oslo"


def test_incomplete_city_profile_fails_before_cli_execution() -> None:
    with pytest.raises(ConfigError, match="complete area_units"):
        load_city_context("stavanger")


def test_workplace_fallback_uses_the_city_raw_directory(tmp_path) -> None:
    city_raw = tmp_path / "oslo"
    city_raw.mkdir()
    (city_raw / "workplaces.csv").write_text(
        "name,latitude,longitude\nOslo reference,59.91,10.75\n",
        encoding="utf-8",
    )

    workplaces = load_workplaces({}, raw_dir=city_raw, metric_crs="EPSG:25832")

    assert workplaces.iloc[0]["name"] == "Oslo reference"
