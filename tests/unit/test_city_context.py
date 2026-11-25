from __future__ import annotations

import pytest

from cdmxmap.citycontext import load_city_context
from cdmxmap.errors import ConfigError
from cdmxmap.scoring.points import load_workplaces


@pytest.mark.parametrize("city", ["oslo", "bergen", "trondheim", "stavanger", "drammen"])
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


def test_morelia_profile_is_runnable() -> None:
    ctx = load_city_context("morelia")

    assert set(ctx.area_configs) == {"postal_code"}
    assert ctx.area_configs["postal_code"].postal_width == 5
    assert ctx.area_configs["postal_code"].display_prefix == "CP "
    assert ctx.weights["safety"] == 0
    assert ctx.metric_crs == "EPSG:32614"
    assert [brand.slug for brand in ctx.store_brands] == [
        "aurrera",
        "walmart",
        "soriana",
        "chedraui",
    ]
    assert ctx.raw_dir.name == "morelia"
    assert ctx.data_dir.name == "morelia"


def test_morelia_transit_and_crime_context_is_unchanged() -> None:
    ctx = load_city_context("morelia")

    assert [(s.code, s.slug, s.group, s.label) for s in ctx.transit_systems] == [
        ("RAIL", "rail", "core", ""),
        ("BUS", "bus", "surface", ""),
    ]
    assert ctx.crime_mode == "incident_points"


def test_monterrey_profile_is_runnable() -> None:
    ctx = load_city_context("monterrey")

    assert set(ctx.area_configs) == {"postal_code", "colonia"}
    postal = ctx.area_configs["postal_code"]
    assert postal.postal_width == 5
    assert postal.display_prefix == "CP "
    assert postal.id_fields == ["d_codigo"]
    assert postal.name_fields == ["colonias_label"]
    assert postal.default_input_path == ctx.raw_dir / "postal_codes.geojson"
    colonia = ctx.area_configs["colonia"]
    assert colonia.postal_width is None
    assert colonia.id_fields == ["area_id"]
    assert colonia.default_input_path == ctx.raw_dir / "colonias.geojson"
    assert ctx.metric_crs == "EPSG:32614"
    assert ctx.weights["safety"] == pytest.approx(0.10)
    assert [(s.code, s.slug, s.group, s.label) for s in ctx.transit_systems] == [
        ("METRO", "metro", "core", "Metrorrey"),
        ("BRT", "brt", "core", "TransMetro BRT"),
        ("TRANSMETRO", "transmetro", "surface", "TransMetro"),
        ("BUS", "rutas", "surface", "Rutas urbanas"),
    ]
    assert ctx.core_codes == {"METRO", "BRT"}
    assert [brand.slug for brand in ctx.store_brands] == [
        "heb",
        "soriana",
        "walmart",
        "aurrera",
        "s_mart",
        "sams",
        "costco",
    ]
    assert ctx.crime_mode == "city_statistics"
    assert ctx.raw_dir.name == "monterrey"
    assert ctx.data_dir.name == "monterrey"


def test_guadalajara_profile_is_runnable() -> None:
    ctx = load_city_context("guadalajara")

    assert set(ctx.area_configs) == {"postal_code", "colonia"}
    assert ctx.area_configs["postal_code"].postal_width == 5
    assert ctx.area_configs["colonia"].postal_width is None
    assert ctx.metric_crs == "EPSG:32613"
    assert ctx.weights["safety"] == pytest.approx(0.15)
    assert [(s.code, s.slug, s.group, s.label) for s in ctx.transit_systems] == [
        ("MITREN", "mitren", "core", "Mi Tren"),
        ("MIMACRO", "mimacro", "core", "Mi Macro"),
        ("ALIMENTADORA", "alimentadora", "surface", "Alimentadoras Mi Macro"),
        ("SITREN", "sitren", "surface", "Mi Transporte Tren Ligero"),
        ("MITRANSPORTE", "mitransporte", "surface", "Mi Transporte"),
    ]
    assert [brand.slug for brand in ctx.store_brands] == [
        "aurrera",
        "soriana",
        "walmart",
        "chedraui",
        "sams",
        "la_comer",
        "costco",
    ]
    assert ctx.crime_mode == "incident_points"
    assert ctx.raw_dir.name == "guadalajara"
    assert ctx.data_dir.name == "guadalajara"


def test_profile_transit_codes_are_upper_cased(monkeypatch) -> None:
    profile = {
        "city_id": "lowercase",
        "crs_metric_epsg": 32614,
        "bbox": {"south": 1.0, "west": 1.0, "north": 2.0, "east": 2.0},
        "area_units": [{"area_unit": "postal_code", "default_input": "x.geojson"}],
        "transit_systems": [{"code": " metro ", "slug": "metro", "group": "core"}],
        "crime_mode": None,
    }
    monkeypatch.setattr("cdmxmap.citycontext.load_city_profile", lambda city: profile)
    ctx = load_city_context("lowercase")

    assert ctx.transit_slugs == {"METRO": "metro"}
    assert ctx.transit_systems[0].label == ""
    assert ctx.crime_mode == "incident_points"  # null falls back to the default


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
