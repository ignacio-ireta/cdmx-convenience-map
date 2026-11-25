"""Offline tests for the Mexican transit fetchers (workstream C).

Everything is synthetic and built in ``tmp_path``: tiny multi-layer GeoPackages that
mimic the Nuevo León STC Metrorrey / IMA files and a tiny GTFS zip that mimics the
SETRAN Jalisco feed. Network seams (CKAN, downloads, Overpass) are replaced; an
autouse guard fails any test that would reach the network.
"""

from __future__ import annotations

import copy
import csv
import io
import json
import re
import shutil
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from cdmxmap.errors import ConfigError, FetchError, SourceUnavailableError
from cdmxmap.sources import fetch_gtfs_transit as gt
from cdmxmap.sources import fetch_nl_transit as nl
from cdmxmap.sources import io as source_io
from cdmxmap.sources import mx_common
from cdmxmap.sources.io import load_city_profile

REAL_STREAM_DOWNLOAD = mx_common.stream_download
STCM_URL = (
    "https://catalogodatos.nl.gob.mx/dataset/x/resource/a/download/"
    "recorridosparadas_stcm_3t2026.gpkg"
)
STCM_OLD_URL = (
    "https://catalogodatos.nl.gob.mx/dataset/x/resource/b/download/"
    "recorridosparadas_stcm_4t2025.gpkg"
)
IMA_URL = (
    "https://catalogodatos.nl.gob.mx/dataset/y/resource/c/download/"
    "q3_2026_recorridos_paradas_conjunto.gpkg"
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unit tests must not touch the network")

    monkeypatch.setattr(mx_common, "stream_download", blocked)
    monkeypatch.setattr(nl, "ckan_action", blocked)
    monkeypatch.setattr(nl, "retry_overpass", blocked)
    monkeypatch.setattr(source_io, "post_overpass", blocked)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def test_join_lines_sorts_naturally_dedupes_and_strips() -> None:
    assert gt.join_lines(["12", "1 ", "1", "", "2", "T01 "]) == "1|2|12|T01"
    assert gt.join_lines(["a|b"]) == "a/b"
    assert gt.join_lines([]) == ""


def test_finalize_rows_sorts_and_assigns_unique_ids() -> None:
    systems = gt.profile_systems(
        {
            "transit_systems": [
                {"code": "metro", "slug": "metro", "group": "core", "label": "M"},
                {"code": "BUS", "slug": "bus", "group": "surface"},
            ]
        }
    )
    rows = [
        {"system": "BUS", "line": "2", "name": "b", "latitude": 1.0, "longitude": 1.0},
        {"system": "BUS", "line": "10", "name": "a", "latitude": 1.0, "longitude": 1.0},
        {
            "system": "METRO",
            "line": "L1",
            "name": "x",
            "latitude": 1.1234567,
            "longitude": 2,
            "_key": "dup",
        },
        {
            "system": "METRO",
            "line": "L1",
            "name": "y",
            "latitude": 1.0,
            "longitude": 2,
            "_key": "dup",
        },
    ]
    final = gt.finalize_rows(rows, systems)
    assert [row["id"] for row in final] == ["METRO-dup", "METRO-dup-2", "BUS-1", "BUS-2"]
    assert [row["line"] for row in final] == ["L1", "L1", "2", "10"]
    assert final[0]["latitude"] == 1.123457
    assert list(final[0]) == list(gt.TRANSIT_STOP_FIELDS)
    with pytest.raises(FetchError, match="undeclared"):
        gt.finalize_rows([{"system": "TREN", "latitude": 0, "longitude": 0}], systems)


def test_check_declared_systems_fails_on_empty_system() -> None:
    with pytest.raises(FetchError, match="TREN"):
        gt.check_declared_systems([{"system": "BUS"}], ["BUS", "TREN"])
    gt.check_declared_systems([{"system": "BUS"}], ["BUS"])


def test_run_cli_exits_non_zero_with_one_error_line(capsys: pytest.CaptureFixture[str]) -> None:
    def boom() -> None:
        raise FetchError("Declared transit systems with 0 rows: TREN")

    with pytest.raises(SystemExit) as excinfo:
        gt.run_cli(boom)
    assert excinfo.value.code == 1
    assert capsys.readouterr().err.strip() == "error: Declared transit systems with 0 rows: TREN"


def test_committed_profiles_parse() -> None:
    gdl = load_city_profile("guadalajara")
    rules = gt.parse_rules(gdl["transit_source"], gt.profile_systems(gdl))
    assert [rule.system for rule in rules][:5] == [
        "MITREN",
        "MIMACRO",
        "MIMACRO",
        "MIMACRO",
        "MIMACRO",
    ]
    assert rules[4].corridor_only and rules[4].offcorridor_system == "ALIMENTADORA"
    mty = load_city_profile("monterrey")
    nl._require_systems(gt.profile_systems(mty))
    assert mty["transit_source"]["type"] == "nl_open_data"


# ---------------------------------------------------------------------------
# Nuevo León (STC Metrorrey + IMA GeoPackages)
# ---------------------------------------------------------------------------

UTM14 = "EPSG:32614"
X0, Y0 = 370_000.0, 2_840_000.0  # central Monterrey in UTM 14N

BRT_A = (25.70500, -100.15810)  # Ecovía P1 (OSM: Terminal Valle Soleado nearby)
BRT_B = (25.70555, -100.16470)  # Ecovía P2 (no OSM station nearby)
BRT_C = (25.65550, -100.18240)  # Av. México corridor P3 (OSM: México nearby)
TM_D = (25.67000, -100.30000)  # shared by two feeder routes
TM_E = (25.68000, -100.31000)
TM_F = (25.69000, -100.32000)  # only in the older month
TM_NULL = (25.67500, -100.30500)  # all-null placeholder row (no RUTA/LINEA/NOM_VIAL)

# (MES, RUTA, LINEA, NO_PARADA, NOM_VIAL, (lat, lon)) rows appended to the TransMetro layer
StcmStop = tuple[str, str | None, str | None, str | None, str | None, tuple[float, float]]


def _write_gpkg(path: Path, layers: dict[str, gpd.GeoDataFrame]) -> Path:
    for name, frame in layers.items():
        frame.to_file(path, layer=name, driver="GPKG")
    return path


def _wgs(lat: float, lon: float) -> Point:
    return Point(lon, lat)


def make_stcm_gpkg(path: Path, extra_stops: Sequence[StcmStop] = ()) -> Path:
    metro = gpd.GeoDataFrame(
        {
            "id": ["a", "b", "c", "d"],
            "Name": [
                "Estación Cuahuctémoc Línea 1 METRO",
                "Estación Cuahuctémoc Línea 2 METRO",
                "Estación General I. Zaragoza L2 METRO",
                "Estación Talleres Linea 1 METRORREY",
            ],
        },
        geometry=[
            _wgs(25.6860, -100.3169),
            _wgs(25.6862, -100.3167),
            _wgs(25.6677, -100.3102),
            _wgs(25.7594, -100.3684),
        ],
        crs="EPSG:4326",
    )
    base: list[StcmStop] = [
        ("AGOSTO", "GARCIA - MONTERREY - GUADALUPE", "BRT", "P1", "TERMINAL LINCON", BRT_A),
        ("AGOSTO", "GARCIA - MONTERREY - GUADALUPE", "BRT", "P2", "ASTROS", BRT_B),
        ("AGOSTO", " exposición - pablo livas ", "2", "P3", "MEXICO", BRT_C),
        ("AGOSTO", "SENDERO - APODACA", "2", "P1", "AV. PINO SUAREZ Y JERÓNIMO TREVIÑO", TM_D),
        ("AGOSTO", "ALAMEDA - PRADERAS ", "1", "P4", "OTRO NOMBRE", TM_D),
        ("AGOSTO", "SENDERO - APODACA", "2", "P2", None, TM_E),
        ("JULIO", "RUTA VIEJA", "1", "P1", "VIEJA", TM_F),
        # Like the 5 all-null rows of the real Q3-2026 layer: a point on no route.
        ("AGOSTO", None, None, None, None, TM_NULL),
    ]
    rows = [*base, *extra_stops]
    stops = gpd.GeoDataFrame(
        {
            "PERIODO": ["2026"] * len(rows),
            "MES": [row[0] for row in rows],
            "RUTA": [row[1] for row in rows],
            "ESTACION_ENLACE": [None] * len(rows),
            "LINEA": [row[2] for row in rows],
            "NO_PARADA": [row[3] for row in rows],
            "NOM_VIAL": [row[4] for row in rows],
        },
        geometry=[_wgs(*row[5]) for row in rows],
        crs="EPSG:4326",
    )
    routes = gpd.GeoDataFrame(
        {"PERIODO": ["2026"], "MES": ["AGOSTO"], "RUTA": ["SENDERO - APODACA"]},
        geometry=[LineString([(-100.30, 25.67), (-100.31, 25.68)])],
        crs="EPSG:4326",
    )
    return _write_gpkg(
        path,
        {
            "paradasrutastransmetro_3T2026": stops,
            "recorridosrutastransmetro_3T2026": routes,
            "estacioneslineasdemetro_3T2026": metro,
        },
    )


def _lat_lon(x: float, y: float) -> tuple[float, float]:
    point = gpd.GeoSeries([Point(x, y)], crs=UTM14).to_crs("EPSG:4326").iloc[0]
    return point.y, point.x


def make_ima_gpkg(path: Path) -> Path:
    routes = gpd.GeoDataFrame(
        {
            "periodo": [2026, 2026, 2026],
            "mes": ["Agosto", "Agosto", "Julio"],
            "ID_servicio": ["R001-AAA01", "R012-BBB02", "R099-OLD01"],
            "nombre_ruta": ["Ruta 1", "Ruta 12", "Ruta 99"],
        },
        geometry=[
            LineString([(X0, Y0), (X0 + 1000, Y0)]),
            LineString([(X0 + 500, Y0 - 500), (X0 + 500, Y0 + 500)]),
            LineString([(X0, Y0 + 5), (X0 + 1000, Y0 + 5)]),
        ],
        crs=UTM14,
    )
    good_lat, good_lon = _lat_lon(X0 + 300, Y0 + 3)
    stops = [
        # (mes, id, x, y, declared lat, declared lon)
        ("Agosto", "MTY-0001", X0 + 500, Y0 + 10, None, None),  # near routes 1 and 12
        ("Agosto", "MTY-0002", X0 + 100, Y0 + 20, 25.80, -100.30),  # Lat/Lon ~13 km off
        ("Agosto", "MTY-0003", X0 + 9000, Y0 + 9000, good_lat, good_lon),  # bad duplicate
        ("Agosto", "MTY-0003", X0 + 300, Y0 + 3, good_lat, good_lon),  # agreeing duplicate
        ("Agosto", "MTY-0004", X0 + 3000, Y0 + 3000, None, None),  # no route nearby
        ("Agosto", None, X0 + 200, Y0 + 2, None, None),  # attribute-less row
        ("Julio", "MTY-0009", X0 + 100, Y0 + 2, None, None),  # older month
    ]
    frame = gpd.GeoDataFrame(
        {
            "periodo": [2026] * len(stops),
            "mes": [row[0] for row in stops],
            "ID_parada": [row[1] for row in stops],
            "NomVial": ["Av Constitucion OTE PTE"] * len(stops),
            "Cruce": ["Pasando Zaragoza"] * len(stops),
            "Latitud": [row[4] for row in stops],
            "Longitud": [row[5] for row in stops],
            "Municipio": ["Monterrey"] * len(stops),
        },
        geometry=[Point(row[2], row[3]) for row in stops],
        crs=UTM14,
    )
    return _write_gpkg(
        path, {"q3_2026_paradas_conjunto": frame, "q3_2026_recorridos_conjunto": routes}
    )


def nl_profile(**overrides: Any) -> dict:
    profile = copy.deepcopy(load_city_profile("monterrey"))
    profile.update(overrides)
    return profile


OSM_PAYLOAD = {
    "elements": [
        {
            "type": "way",
            "id": 1,
            "center": {"lat": BRT_A[0] + 0.0003, "lon": BRT_A[1]},
            "tags": {
                "public_transport": "station",
                "network": "Ecovía",
                "name": "Ecovía - Terminal Valle Soleado",
            },
        },
        {
            "type": "way",
            "id": 2,
            "center": {"lat": BRT_C[0], "lon": BRT_C[1] + 0.0005},
            "tags": {"public_transport": "station", "network": "Transmetro", "name": "México"},
        },
        {"type": "node", "id": 3, "lat": 25.0, "lon": -100.0, "tags": {"name": "no pt tag"}},
        {
            "type": "node",
            "id": 4,
            "lat": BRT_B[0],
            "lon": BRT_B[1],
            "tags": {"public_transport": "station", "network": "Metrorrey", "name": "Metro X"},
        },
    ]
}


def test_resource_period_reads_year_and_quarter_from_url() -> None:
    stcm = re.compile(r"recorridosparadas_stcm_(\d)t(\d{4})\.gpkg$", re.IGNORECASE)
    ima = re.compile(r"q(\d)_(\d{4})_recorridos_paradas_conjunto\.gpkg$", re.IGNORECASE)
    assert nl.resource_period(STCM_URL, stcm) == (2026, 3)
    assert nl.resource_period(STCM_OLD_URL + "?x=1", stcm) == (2025, 4)
    assert nl.resource_period(IMA_URL, ima) == (2026, 3)
    assert nl.resource_period("https://x/q5_2026_recorridos_paradas_conjunto.gpkg", ima) is None
    assert nl.resource_period("https://x/other.csv", ima) is None


def test_resolve_latest_resource_uses_urls_and_search(monkeypatch: pytest.MonkeyPatch) -> None:
    pattern = re.compile(r"recorridosparadas_stcm_(\d)t(\d{4})\.gpkg$")
    calls: list[str] = []

    def fake_ckan(api: str, action: str, params: dict, **_: object) -> dict:
        calls.append(action)
        if action == "package_show":
            return {
                "name": "pkg-2025-2026",
                "resources": [
                    {"name": "2026_T4_recorridosparadas_stcm.gpkg", "url": STCM_OLD_URL},
                    {"name": "2026_T3_recorridosparadas_stcm.gpkg", "url": STCM_URL},
                    {"name": "dictionary", "url": "https://x/diccionario.csv"},
                ],
            }
        return {"results": [{"name": "unrelated", "resources": [{"url": "https://x/a.csv"}]}]}

    monkeypatch.setattr(nl, "ckan_action", fake_ckan)
    choice = nl.resolve_latest_resource("https://api", "pkg-2025-2026", pattern, "paradas")
    assert (choice.year, choice.quarter, choice.basename) == (
        2026,
        3,
        "recorridosparadas_stcm_3t2026.gpkg",
    )
    assert calls == ["package_show", "package_search"]

    newer = STCM_URL.replace("3t2026", "1t2027")

    def show_fails(api: str, action: str, params: dict, **_: object) -> dict:
        if action == "package_show":
            raise SourceUnavailableError("404")
        return {"results": [{"name": "pkg-2026-2027", "resources": [{"url": newer}]}]}

    monkeypatch.setattr(nl, "ckan_action", show_fails)
    choice = nl.resolve_latest_resource("https://api", "pkg-2025-2026", pattern, "paradas")
    assert (choice.year, choice.quarter, choice.package) == (2027, 1, "pkg-2026-2027")

    def all_fail(*_: object, **__: object) -> dict:
        raise SourceUnavailableError("down")

    monkeypatch.setattr(nl, "ckan_action", all_fail)
    with pytest.raises(SourceUnavailableError):
        nl.resolve_latest_resource("https://api", "pkg", pattern, "paradas")


def test_latest_month_rows_handles_case_and_accents() -> None:
    frame = gpd.GeoDataFrame(
        {"MES": ["JULIO", "SEPTIEMBRE", "agosto", "Septiembre"]},
        geometry=[Point(0, 0)] * 4,
        crs="EPSG:4326",
    )
    subset, month = nl.latest_month_rows(frame, "mes")
    assert month == "SEPTIEMBRE" and len(subset) == 2
    with pytest.raises(FetchError):
        nl.latest_month_rows(frame.assign(MES="??"), "MES")


def test_build_nl_rows_classifies_every_system(tmp_path: Path) -> None:
    stcm = make_stcm_gpkg(tmp_path / "recorridosparadas_stcm_3t2026.gpkg")
    ima = make_ima_gpkg(tmp_path / "q3_2026_recorridos_paradas_conjunto.gpkg")
    profile = nl_profile()
    systems = gt.profile_systems(profile)
    unfiltered = nl.parse_osm_stations(OSM_PAYLOAD)
    assert [s.name for s in unfiltered] == ["Metro X", "México", "Terminal Valle Soleado"]
    assert [s.name for s in nl.parse_osm_stations(OSM_PAYLOAD, "ecov[ií]a")] == [
        "Terminal Valle Soleado"
    ]
    osm = nl.parse_osm_stations(OSM_PAYLOAD, profile["transit_source"]["osm_brt_network"])
    rows = nl.build_nl_rows(
        stcm,
        ima,
        profile["transit_source"],
        systems,
        metric_crs=UTM14,
        osm_lookup=lambda points: osm,
    )
    final = gt.finalize_rows(rows, systems)
    by_system: dict[str, list[dict]] = {}
    for row in final:
        by_system.setdefault(row["system"], []).append(row)

    metro = {(row["line"], row["name"]) for row in by_system["METRO"]}
    assert metro == {
        ("L1", "Metrorrey L1 · Cuauhtémoc"),
        ("L1", "Metrorrey L1 · Talleres"),
        ("L2", "Metrorrey L2 · Cuauhtémoc"),
        ("L2", "Metrorrey L2 · General I. Zaragoza"),
    }
    assert {row["id"] for row in by_system["METRO"]} >= {"METRO-L1-Cuauhtemoc"}
    assert all(row["hierarchy"] == "station" for row in by_system["METRO"])

    brt = {(row["line"], row["name"], row["latitude"]) for row in by_system["BRT"]}
    assert brt == {
        ("ECOVIA", "TransMetro BRT Ecovía · Terminal Valle Soleado", BRT_A[0]),
        ("ECOVIA", "TransMetro BRT Ecovía · stop 2", BRT_B[0]),
        ("AV_MEXICO", "TransMetro BRT Av. México · México", BRT_C[0]),
    }

    transmetro = {(row["latitude"], row["longitude"]): row for row in by_system["TRANSMETRO"]}
    assert set(transmetro) == {TM_D, TM_E}  # the July-only stop is gone
    assert transmetro[TM_D]["line"] == "ALAMEDA - PRADERAS|SENDERO - APODACA"
    assert transmetro[TM_D]["name"] == "TransMetro · Otro Nombre"
    assert transmetro[TM_E]["name"] == "TransMetro · Parada"
    assert {row["source"] for row in by_system["TRANSMETRO"] + by_system["BRT"]} == {
        "nl_stcm_metrorrey"
    }

    bus = {row["id"]: row for row in by_system["BUS"]}
    assert set(bus) == {"BUS-MTY-0001", "BUS-MTY-0002", "BUS-MTY-0003", "BUS-MTY-0004"}
    assert bus["BUS-MTY-0001"]["line"] == "1|12"
    assert bus["BUS-MTY-0002"]["line"] == "1"
    assert bus["BUS-MTY-0004"]["line"] == ""
    # Coordinates come from the geometry, not the (wrong) Latitud/Longitud columns.
    lat2, lon2 = _lat_lon(X0 + 100, Y0 + 20)
    assert bus["BUS-MTY-0002"]["latitude"] == pytest.approx(lat2, abs=1e-6)
    assert bus["BUS-MTY-0002"]["longitude"] == pytest.approx(lon2, abs=1e-6)
    # Of the two MTY-0003 rows the one agreeing with its declared position is kept.
    lat3, lon3 = _lat_lon(X0 + 300, Y0 + 3)
    assert bus["BUS-MTY-0003"]["latitude"] == pytest.approx(lat3, abs=1e-6)
    assert bus["BUS-MTY-0003"]["line"] == "1"
    assert (
        bus["BUS-MTY-0001"]["name"] == "Rutas urbanas · Av Constitucion OTE PTE, Pasando Zaragoza"
    )
    assert {row["source"] for row in bus.values()} == {"nl_ima"}


def test_brt_names_fall_back_when_overpass_fails(tmp_path: Path) -> None:
    stcm = make_stcm_gpkg(tmp_path / "recorridosparadas_stcm_3t2026.gpkg")
    ima = make_ima_gpkg(tmp_path / "q3_2026_recorridos_paradas_conjunto.gpkg")
    profile = nl_profile()
    rows = nl.build_nl_rows(
        stcm,
        ima,
        profile["transit_source"],
        gt.profile_systems(profile),
        metric_crs=UTM14,
        osm_lookup=lambda points: None,
    )
    names = sorted(row["name"] for row in rows if row["system"] == "BRT")
    assert names == [
        "TransMetro BRT Av. México · stop 3",
        "TransMetro BRT Ecovía · stop 1",
        "TransMetro BRT Ecovía · stop 2",
    ]


def test_split_transmetro_drops_route_less_placeholder_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stcm = make_stcm_gpkg(
        tmp_path / "recorridosparadas_stcm_3t2026.gpkg",
        # an empty-RUTA row that *is* BRT (LINEA) is a real station and stays
        extra_stops=[("AGOSTO", "", "BRT", "P9", None, (25.70600, -100.17000))],
    )
    layer = nl.read_layer(
        stcm, nl_profile()["transit_source"]["layer_patterns"]["transmetro_stops"]
    )
    split = nl.split_transmetro(layer, nl_profile()["transit_source"]["brt_routes"])
    assert "TRANSMETRO: dropped 1 AGOSTO stop rows without a RUTA" in capsys.readouterr().out
    other = set(zip(split.other["lat"], split.other["lon"]))
    assert TM_NULL not in other
    assert other == {TM_D, TM_E}
    assert (split.other["ruta"] != "").all()
    assert (25.706, -100.17) in set(zip(split.brt["lat"], split.brt["lon"]))
    assert set(split.brt["brt_line"]) == {"ECOVIA", "AV_MEXICO", "BRT"}


def test_strip_estacion() -> None:
    assert nl.strip_estacion("Estacion Exposición") == "Exposición"
    assert nl.strip_estacion("ESTACIÓN  Hospital") == "Hospital"
    assert nl.strip_estacion(" Av. Pino Suarez ") == "Av. Pino Suarez"
    assert nl.strip_estacion("Estación") == "Estación"  # nothing would be left


# Feeder stops next to the synthetic BRT stops (offsets in degrees of latitude;
# 0.0001 deg ~ 11 m).
NEAR_A = (BRT_A[0] - 0.0002, BRT_A[1])  # ~22 m: loses to the OSM station
NEAR_B = (BRT_B[0] + 0.0003, BRT_B[1])  # ~33 m
FAR_B = (BRT_B[0] + 0.0005, BRT_B[1])  # ~56 m: in range, but farther than NEAR_B
NEAR_C = (BRT_C[0] + 0.0009, BRT_C[1])  # ~100 m: outside the 75 m radius
FEEDERS: list[StcmStop] = [
    ("AGOSTO", "SENDERO - APODACA", "2", "P7", "ESTACION OTRA", NEAR_A),
    ("AGOSTO", "SENDERO - APODACA", "2", "P8", "ESTACION ASTROS", NEAR_B),
    ("AGOSTO", "ALAMEDA - PRADERAS", "1", "P9", "AV. SEGUNDA", FAR_B),
    ("AGOSTO", "ALAMEDA - PRADERAS", "1", "P10", "ESTACIÓN LEJOS", NEAR_C),
]


@pytest.mark.parametrize(
    ("osm_available", "expected"),
    [
        (
            True,
            {
                "TransMetro BRT Ecovía · Terminal Valle Soleado",  # OSM beats the feeder
                "TransMetro BRT Ecovía · Astros",  # no OSM station: nearest feeder
                "TransMetro BRT Av. México · México",
            },
        ),
        (
            False,  # Overpass failed: feeders still name what they can
            {
                "TransMetro BRT Ecovía · Otra",
                "TransMetro BRT Ecovía · Astros",
                "TransMetro BRT Av. México · stop 3",  # the only feeder is ~100 m away
            },
        ),
    ],
)
def test_brt_names_borrow_the_nearest_feeder_stop_name(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    osm_available: bool,
    expected: set[str],
) -> None:
    stcm = make_stcm_gpkg(tmp_path / "recorridosparadas_stcm_3t2026.gpkg", FEEDERS)
    ima = make_ima_gpkg(tmp_path / "q3_2026_recorridos_paradas_conjunto.gpkg")
    profile = nl_profile()
    osm = nl.parse_osm_stations(OSM_PAYLOAD, profile["transit_source"]["osm_brt_network"])
    rows = nl.build_nl_rows(
        stcm,
        ima,
        profile["transit_source"],
        gt.profile_systems(profile),
        metric_crs=UTM14,
        osm_lookup=lambda points: osm if osm_available else None,
    )
    assert {row["name"] for row in rows if row["system"] == "BRT"} == expected
    out = capsys.readouterr().out
    if osm_available:
        assert (
            "BRT names for 3 stops: 2 from OSM stations within 200 m, 0 from METRO and "
            "1 from TRANSMETRO stops within 75 m, 0 generic"
        ) in out
    else:
        assert (
            "BRT names for 3 stops: 0 from OSM stations within 200 m, 0 from METRO and "
            "2 from TRANSMETRO stops within 75 m, 1 generic"
        ) in out
    # The feeder stops themselves are unchanged TRANSMETRO rows.
    feeder_names = {row["name"] for row in rows if row["system"] == "TRANSMETRO"}
    assert {"TransMetro · Estacion Astros", "TransMetro · Estación Lejos"} <= feeder_names
    assert all("_station" not in row for row in gt.finalize_rows(rows, gt.profile_systems(profile)))


def test_brt_rows_neighbour_precedence_radius_and_counts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    brt = pd.DataFrame(
        {
            "brt_line": ["ECOVIA", "ECOVIA", "AV_MEXICO"],
            "lat": [25.70000, 25.71000, 25.72000],
            "lon": [-100.20000, -100.20000, -100.20000],
            "stop_no": ["P1", "P2", "P3"],
        }
    )
    neighbours = [
        nl.NamedStop(nl.METRO, "Metro Uno", 25.70030, -100.20000),  # ~33 m
        nl.NamedStop(nl.TRANSMETRO, "Feeder Uno", 25.70050, -100.20000),  # ~56 m
        nl.NamedStop(nl.TRANSMETRO, "Feeder Dos", 25.71040, -100.20000),  # ~44 m
        nl.NamedStop(nl.METRO, "Metro Lejos", 25.72080, -100.20000),  # ~89 m
    ]
    rows = nl.brt_rows(
        brt,
        label="BRT",
        line_labels={"ECOVIA": "Ecovía"},
        osm_stations=None,
        radius_m=200,
        neighbours=neighbours,
    )
    assert [row["name"] for row in rows] == [
        "BRT AV_MEXICO · stop 3",
        "BRT Ecovía · Metro Uno",
        "BRT Ecovía · Feeder Dos",
    ]
    assert (
        "BRT names for 3 stops: 0 from OSM stations within 200 m, 1 from METRO and "
        "1 from TRANSMETRO stops within 75 m, 1 generic"
    ) in capsys.readouterr().out
    # without neighbours the old generic naming is untouched
    plain = nl.brt_rows(brt, label="BRT", line_labels={}, osm_stations=None, radius_m=200)
    assert [row["name"] for row in plain] == [
        "BRT AV_MEXICO · stop 3",
        "BRT ECOVIA · stop 1",
        "BRT ECOVIA · stop 2",
    ]


def test_neighbour_stops_come_from_named_metro_and_transmetro_rows() -> None:
    rows = [
        {"system": nl.METRO, "_station": "Cuauhtémoc", "latitude": 25.1, "longitude": -100.1},
        {
            "system": nl.TRANSMETRO,
            "_station": "Estacion Exposición",
            "latitude": 25.2,
            "longitude": -100.2,
        },
        {"system": nl.TRANSMETRO, "_station": "", "latitude": 25.3, "longitude": -100.3},
        {"system": nl.BUS, "_station": "Av. Bus", "latitude": 25.4, "longitude": -100.4},
    ]
    assert nl.neighbour_stops(rows) == [
        nl.NamedStop(nl.METRO, "Cuauhtémoc", 25.1, -100.1),
        nl.NamedStop(nl.TRANSMETRO, "Exposición", 25.2, -100.2),
    ]


def test_fetch_osm_brt_stations_caches_and_degrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "osm.json"
    queries: list[str] = []

    options: list[dict] = []

    def fake_overpass(query: str, **kwargs: object) -> dict:
        queries.append(query)
        options.append(kwargs)
        return OSM_PAYLOAD

    monkeypatch.setattr(nl, "retry_overpass", fake_overpass)
    stations = nl.fetch_osm_brt_stations(
        [BRT_A, BRT_C], network="Ecov[ií]a|Transmetro", cache_path=cache
    )
    assert stations is not None
    assert [s.name for s in stations] == ["México", "Terminal Valle Soleado"]  # no Metro X
    assert cache.exists() and '"Ecov[ií]a|Transmetro",i' in queries[0]
    # A live query rotates mirrors and refuses stale ones (legacy callers do neither).
    assert options[0]["endpoints"] == source_io.OVERPASS_ENDPOINTS
    assert options[0]["max_osm_age_days"] == nl.OSM_BRT_MAX_AGE_DAYS == 30
    # Cached: no second query.
    nl.fetch_osm_brt_stations([BRT_A], network="x", cache_path=cache)
    assert len(queries) == 1

    def failing(query: str, **_: object) -> dict:
        raise RuntimeError("Overpass failed after 3 attempts")

    monkeypatch.setattr(nl, "retry_overpass", failing)
    assert nl.fetch_osm_brt_stations([BRT_A], network="x", cache_path=tmp_path / "n.json") is None


def _fake_nl_network(
    monkeypatch: pytest.MonkeyPatch, files: dict[str, Path], downloads: list[str]
) -> None:
    def fake_ckan(api: str, action: str, params: dict, **_: object) -> dict:
        if action == "package_show" and "stcmetrorrey" in params["id"]:
            return {
                "name": params["id"],
                "resources": [{"url": STCM_OLD_URL}, {"url": STCM_URL}],
            }
        if action == "package_show":
            return {"name": params["id"], "resources": [{"url": IMA_URL}]}
        return {"results": []}

    def fake_stream(
        url: str,
        path: Path,
        *,
        timeout: int = 300,
        allowed_final_url: Callable[[str], bool] | None = None,
    ) -> None:
        # Every CKAN resource download carries the https + catalogue-host check; with
        # no redirect the final URL is the resource URL itself.
        assert allowed_final_url is nl.is_nl_ckan_url
        if not allowed_final_url(url):
            raise FetchError(f"Download of {url} ended at a disallowed URL {url}")
        downloads.append(url)
        shutil.copyfile(files[Path(url).name], path)

    monkeypatch.setattr(nl, "ckan_action", fake_ckan)
    monkeypatch.setattr(mx_common, "stream_download", fake_stream)
    monkeypatch.setattr(nl, "retry_overpass", lambda query, **_: OSM_PAYLOAD)


def test_fetch_nl_transit_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    files = {
        "recorridosparadas_stcm_3t2026.gpkg": make_stcm_gpkg(
            sources / "recorridosparadas_stcm_3t2026.gpkg"
        ),
        "q3_2026_recorridos_paradas_conjunto.gpkg": make_ima_gpkg(
            sources / "q3_2026_recorridos_paradas_conjunto.gpkg"
        ),
    }
    downloads: list[str] = []
    _fake_nl_network(monkeypatch, files, downloads)
    raw, out = tmp_path / "raw", tmp_path / "out" / "transit_stops.csv"
    # Clip away Talleres (the northernmost metro station) with a tighter bbox.
    profile = nl_profile(bbox={"south": 25.5, "west": -100.65, "north": 25.75, "east": -99.95})
    rows = nl.fetch_nl_transit("monterrey", profile=profile, raw_dir=raw, output_path=out)
    assert downloads == [STCM_URL, IMA_URL]
    assert (raw / "recorridosparadas_stcm_3t2026.gpkg").exists()
    assert (raw / nl.OSM_CACHE_NAME).exists()
    assert not list(raw.glob("*.part*"))
    written = read_csv_rows(out)
    assert list(written[0]) == list(gt.TRANSIT_STOP_FIELDS)
    assert len(written) == len(rows) == 4 + 3 + 2 + 4 - 1
    assert "Metrorrey L1 · Talleres" not in {row["name"] for row in written}
    first = out.read_bytes()

    # Second run: everything cached (no download, no Overpass), identical bytes.
    monkeypatch.setattr(mx_common, "stream_download", lambda *a, **k: pytest.fail("download"))
    monkeypatch.setattr(nl, "retry_overpass", lambda *a, **k: pytest.fail("overpass"))
    nl.fetch_nl_transit("monterrey", profile=profile, raw_dir=raw, output_path=out)
    assert out.read_bytes() == first


def test_fetch_nl_transit_fails_on_empty_declared_system(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    files = {
        "recorridosparadas_stcm_3t2026.gpkg": make_stcm_gpkg(
            sources / "recorridosparadas_stcm_3t2026.gpkg"
        ),
        "q3_2026_recorridos_paradas_conjunto.gpkg": make_ima_gpkg(
            sources / "q3_2026_recorridos_paradas_conjunto.gpkg"
        ),
    }
    _fake_nl_network(monkeypatch, files, [])
    profile = nl_profile()
    profile["transit_systems"] = [
        *profile["transit_systems"],
        {"code": "TREN", "slug": "tren", "group": "core", "label": "Tren"},
    ]
    out = tmp_path / "transit_stops.csv"
    with pytest.raises(FetchError, match="TREN"):
        nl.fetch_nl_transit("monterrey", profile=profile, raw_dir=tmp_path / "raw", output_path=out)
    assert not out.exists()


def test_rejected_gpkg_is_not_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    wrong = _write_gpkg(
        sources / "recorridosparadas_stcm_3t2026.gpkg",
        {"unrelated": gpd.GeoDataFrame({"a": [1]}, geometry=[Point(0, 0)], crs="EPSG:4326")},
    )
    _fake_nl_network(monkeypatch, {wrong.name: wrong}, [])
    raw = tmp_path / "raw"
    with pytest.raises(FetchError, match="layer pattern"):
        nl.fetch_package_gpkg(nl_profile()["transit_source"], "stcm", nl.STCM_LAYERS, raw)
    assert not list(raw.glob("*"))


class _RedirectedResponse:
    """A urlopen() result whose final URL (after redirects) is ``final_url``."""

    def __init__(self, body: bytes, final_url: str) -> None:
        self._body = body
        self._final_url = final_url
        self._sent = False

    def geturl(self) -> str:
        return self._final_url

    def read(self, size: int = -1) -> bytes:
        if self._sent:
            return b""
        self._sent = True
        return self._body

    def __enter__(self) -> _RedirectedResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_is_nl_ckan_url() -> None:
    assert nl.is_nl_ckan_url(STCM_URL)
    assert nl.is_nl_ckan_url(STCM_URL.replace("catalogodatos", "CATALOGODATOS"))
    assert not nl.is_nl_ckan_url(STCM_URL.replace("https://", "http://"))
    assert not nl.is_nl_ckan_url("https://evil.example/recorridosparadas_stcm_3t2026.gpkg")
    assert not nl.is_nl_ckan_url(STCM_URL.replace("nl.gob.mx", "nl.gob.mx.evil.example"))
    assert not nl.is_nl_ckan_url(STCM_URL.replace("catalogodatos.", "x.catalogodatos."))


@pytest.mark.parametrize(
    "final_url",
    [
        "https://evil.example/recorridosparadas_stcm_3t2026.gpkg",  # off-host
        STCM_URL.replace("https://", "http://"),  # downgraded to plain http
    ],
)
def test_ckan_download_redirected_off_the_catalogue_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, final_url: str
) -> None:
    body = make_stcm_gpkg(tmp_path / "source.gpkg").read_bytes()

    def fake_ckan(api: str, action: str, params: dict, **_: object) -> dict:
        if action == "package_show":
            return {"name": params["id"], "resources": [{"url": STCM_URL}]}
        return {"results": []}

    def fake_urlopen(request, timeout: int, context: object = None) -> _RedirectedResponse:
        return _RedirectedResponse(body, final_url)

    monkeypatch.setattr(nl, "ckan_action", fake_ckan)
    # The real stream_download over a fake urlopen that reports a redirect.
    monkeypatch.setattr(mx_common, "stream_download", REAL_STREAM_DOWNLOAD)
    monkeypatch.setattr(mx_common.urllib.request, "urlopen", fake_urlopen)
    raw = tmp_path / "raw"
    with pytest.raises(FetchError, match="disallowed URL"):
        nl.fetch_package_gpkg(nl_profile()["transit_source"], "stcm", nl.STCM_LAYERS, raw)
    assert list(raw.glob("*")) == []

    # The same body served from the catalogue itself is accepted.
    monkeypatch.setattr(
        mx_common.urllib.request,
        "urlopen",
        lambda request, timeout, context=None: _RedirectedResponse(body, STCM_URL),
    )
    path = nl.fetch_package_gpkg(nl_profile()["transit_source"], "stcm", nl.STCM_LAYERS, raw)
    assert path.read_bytes() == body


def test_offline_ckan_uses_newest_cached_gpkg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    make_stcm_gpkg(raw / "recorridosparadas_stcm_3t2026.gpkg")
    shutil.copyfile(
        raw / "recorridosparadas_stcm_3t2026.gpkg", raw / "recorridosparadas_stcm_4t2025.gpkg"
    )

    def down(*_: object, **__: object) -> dict:
        raise SourceUnavailableError("offline")

    monkeypatch.setattr(nl, "ckan_action", down)
    path = nl.fetch_package_gpkg(nl_profile()["transit_source"], "stcm", nl.STCM_LAYERS, raw)
    assert path.name == "recorridosparadas_stcm_3t2026.gpkg"


# ---------------------------------------------------------------------------
# GTFS (SETRAN Jalisco-like feed)
# ---------------------------------------------------------------------------

GDL_BBOX = {"south": 20.35, "west": -103.67, "north": 21.0, "east": -103.08}

GTFS_STOPS = {
    # Mi Tren
    "T1": ("Juárez", 20.6750, -103.3547),
    "T2": ("Refugio", 20.6820, -103.3542),
    "T4": ("Juárez", 20.6751, -103.3555),
    "T5": ("Plaza Universidad", 20.6753, -103.3483),
    # Mi Macro Calzada (L6): one stop_id per direction
    "C1a": ("Ciprés", 20.6528, -103.3534),
    "C1b": ("Cipres", 20.6533, -103.3534),
    "C2": ("Agua Azul", 20.6581, -103.3509),
    "C2b": ("Agua Azul L6", 20.6582, -103.3509),
    # Mi Macro Periférico (L7)
    "P1": ("Carretera a Chapala", 20.5922, -103.3194),
    "P2": ("Las Pintas", 20.5877, -103.3268),
    "P3": ("Periférico Sur", 20.6055, -103.4001),
    # Mi Macro Aeropuerto (L5) trunk and on-street stops
    "A1": ("Carretera a Chapala", 20.5868, -103.3198),  # ~600 m from P1: a real L5 station
    "A2": ("Las Torres", 20.5680, -103.3108),
    "A2b": ("Las Torres", 20.5682, -103.3109),  # other platform, served only by T02
    "A3": ("Periférico Sur", 20.6057, -103.4002),  # same name as P3, ~25 m away
    "S9": ("Av. Las Torres 100", 20.5700, -103.3150),
    # Feeder, buses, SiTren, excluded and unknown agencies
    "F1": ("Calle 1", 20.6600, -103.3600),
    "B1": ("Av. Juárez 100", 20.676010, -103.350010),
    "B2": ("Av. Juarez 100", 20.676012, -103.350008),  # same name/position at 5 dp
    "B3": ("Fuera", 21.5000, -103.3500),  # outside the bbox
    "B4": ("Calle Morelos", 20.6700, -103.3400),
    "S1": ("Av. Alcalde", 20.6900, -103.3480),
    "Z0": ("Zapotlanejo centro", 20.6200, -103.0700),
    "X0": ("Desconocida", 20.6300, -103.3000),
}
GTFS_ROUTES = [
    # route_id, agency_id, short, desc, type, stops served
    ("MT_L1", "MT", "TL-1", "Tren Ligero Línea 1", "1", ["T1", "T2"]),
    ("MT_L2", "MT", "TL-2", "Tren Ligero Línea 2", "1", ["T4", "T5"]),
    ("MC-L1P", "MM", "", "Mi Macro Calzada", "3", ["C1a", "C1b", "C2", "C2b"]),
    ("MP-T01", "MM", "T01", "Mi Macro Periférico - Troncal 01", "3", ["P1", "P2", "P3"]),
    (
        "R27",
        "MMA",
        "T01 ",
        "Mi Macro Aeropuerto - Línea 5 - Troncal 01",
        "3",
        ["P1", "A1", "A2", "A3"],
    ),
    ("R29", "MMA", "T02", "Mi Macro Aeropuerto - Línea 5 - Troncal 02", "3", ["A2", "A2b", "S9"]),
    ("MC-A03", "MM", "MC-A03", "Alimentadora Mi Macro Calzada A03", "3", ["C1a", "F1"]),
    ("C01", "BUS", "C01", "Troncal C01", "3", ["B1", "B2", "B3"]),
    ("C02", "BUS", "C02 ", "Troncal C02", "3", ["B1", "B4"]),
    ("R-01", "ST", "R-01", "Mi Transporte Tren Ligero - Ruta 01", "3", ["T1", "S1"]),
    ("Z1", "ZAP", "Z1", "Zapotlanejo", "3", ["Z0"]),
    ("X9", "XYZ", "X9", "Unknown operator", "3", ["X0"]),
]


def _csv_text(header: list[str], rows: list[list[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def make_gtfs_zip(path: Path, *, drop: str | None = None) -> Path:
    tables = {
        "agency.txt": _csv_text(
            ["agency_id", "agency_name"],
            [[a, a] for a in ["MT", "MM", "MMA", "BUS", "ST", "ZAP", "XYZ"]],
        ),
        "routes.txt": _csv_text(
            [
                "route_id",
                "agency_id",
                "route_short_name",
                "route_long_name",
                "route_desc",
                "route_type",
            ],
            [
                [rid, agency, short, "", desc, rtype]
                for rid, agency, short, desc, rtype, _ in GTFS_ROUTES
            ],
        ),
        "stops.txt": _csv_text(
            ["stop_id", "stop_name", "stop_lat", "stop_lon", "location_type"],
            [[sid, name, f"{lat}", f"{lon}", ""] for sid, (name, lat, lon) in GTFS_STOPS.items()]
            + [["BAD", "No coords", "", "", ""]],
        ),
        "trips.txt": _csv_text(
            ["route_id", "service_id", "trip_id"],
            [[rid, "1", f"{rid}_t1"] for rid, *_ in GTFS_ROUTES],
        ),
        "stop_times.txt": _csv_text(
            ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
            [
                [f"{route[0]}_t1", "08:00:00", "08:00:00", stop_id, str(seq)]
                for route in GTFS_ROUTES
                for seq, stop_id in enumerate(route[5], 1)
            ],
        ),
        "calendar.txt": _csv_text(
            [
                "service_id",
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
                "start_date",
                "end_date",
            ],
            [["1", "1", "1", "1", "1", "1", "0", "0", "20260501", "20261231"]],
        ),
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, text in tables.items():
            if name != drop:
                zf.writestr(name, "﻿" + text if name == "routes.txt" else text)
    return path


def gdl_profile(**overrides: Any) -> dict:
    profile = copy.deepcopy(load_city_profile("guadalajara"))
    profile["bbox"] = dict(GDL_BBOX)
    profile.update(overrides)
    return profile


def _gtfs_rows(tmp_path: Path, profile: dict | None = None) -> list[dict]:
    zip_path = make_gtfs_zip(tmp_path / "feed.zip")
    return gt.fetch_gtfs_transit(
        "guadalajara",
        profile=profile or gdl_profile(),
        gtfs_zip=zip_path,
        output_path=tmp_path / "transit_stops.csv",
    )


def test_gtfs_core_lines_subtraction_and_merge(tmp_path: Path) -> None:
    rows = _gtfs_rows(tmp_path)
    core = {
        (row["system"], row["line"], row["name"]): row
        for row in rows
        if row["hierarchy"] == "station"
    }
    assert set(core) == {
        ("MITREN", "L1", "Mi Tren L1 · Juárez"),
        ("MITREN", "L1", "Mi Tren L1 · Refugio"),
        ("MITREN", "L2", "Mi Tren L2 · Juárez"),
        ("MITREN", "L2", "Mi Tren L2 · Plaza Universidad"),
        # L5: P1 (same stop_id as L7) and A3 (same name as L7 within 300 m) are
        # subtracted; A1 shares a name with an L7 station but is 600 m away.
        ("MIMACRO", "L5", "Mi Macro L5 · Carretera a Chapala"),
        ("MIMACRO", "L5", "Mi Macro L5 · Las Torres"),
        # L6: both directions merged; trailing " L6" tag dropped from the name.
        ("MIMACRO", "L6", "Mi Macro L6 · Ciprés"),
        ("MIMACRO", "L6", "Mi Macro L6 · Agua Azul"),
        ("MIMACRO", "L7", "Mi Macro L7 · Carretera a Chapala"),
        ("MIMACRO", "L7", "Mi Macro L7 · Las Pintas"),
        ("MIMACRO", "L7", "Mi Macro L7 · Periférico Sur"),
    }
    chapala_l5 = core[("MIMACRO", "L5", "Mi Macro L5 · Carretera a Chapala")]
    assert (chapala_l5["latitude"], chapala_l5["longitude"]) == (20.5868, -103.3198)
    cipres = core[("MIMACRO", "L6", "Mi Macro L6 · Ciprés")]
    assert cipres["latitude"] == pytest.approx((20.6528 + 20.6533) / 2, abs=1e-6)
    # The T02 corridor platform A2b merges into the L5 Las Torres station.
    torres = core[("MIMACRO", "L5", "Mi Macro L5 · Las Torres")]
    assert torres["latitude"] == pytest.approx((20.5680 + 20.5682) / 2, abs=1e-6)
    assert cipres["id"] == "MIMACRO-L6-Cipres"
    assert {row["source"] for row in rows} == {"setran_gtfs"}


def test_gtfs_surface_rows_join_dedupe_and_exclusions(tmp_path: Path) -> None:
    rows = _gtfs_rows(tmp_path)
    surface = {row["id"]: row for row in rows if row["hierarchy"] == "stop"}
    assert surface["MITRANSPORTE-B1"]["line"] == "C01|C02"  # B2 collapsed into B1
    assert "MITRANSPORTE-B2" not in surface
    assert "MITRANSPORTE-B3" not in surface  # outside the bbox
    assert surface["MITRANSPORTE-B4"]["line"] == "C02"  # trailing space stripped
    assert surface["MITRANSPORTE-B1"]["name"] == "Mi Transporte · Av. Juárez 100"
    alimentadora = {
        key: row["line"] for key, row in surface.items() if row["system"] == "ALIMENTADORA"
    }
    assert alimentadora == {
        "ALIMENTADORA-C1a": "MC-A03",
        "ALIMENTADORA-F1": "MC-A03",
        "ALIMENTADORA-S9": "L5-T02",
    }
    assert {key for key, row in surface.items() if row["system"] == "SITREN"} == {
        "SITREN-T1",
        "SITREN-S1",
    }
    names = " ".join(row["name"] for row in rows)
    assert "Zapotlanejo" not in names and "Desconocida" not in names


def test_gtfs_output_is_deterministic_and_reports_feed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    zip_path = make_gtfs_zip(tmp_path / "feed.zip")
    out = tmp_path / "transit_stops.csv"
    gt.fetch_gtfs_transit("guadalajara", profile=gdl_profile(), gtfs_zip=zip_path, output_path=out)
    first = out.read_bytes()
    log = capsys.readouterr().out
    assert f"sha256={gt.sha256_file(zip_path)}" in log
    assert "GTFS service calendar 20260501..20261231" in log
    assert "1 matched no rule" in log and "X9" in log
    assert "MIMACRO [core] 7: L5 2, L6 2, L7 3" in log
    gt.fetch_gtfs_transit("guadalajara", profile=gdl_profile(), gtfs_zip=zip_path, output_path=out)
    assert out.read_bytes() == first
    written = read_csv_rows(out)
    assert list(written[0]) == list(gt.TRANSIT_STOP_FIELDS)
    order = [row["system"] for row in written]
    assert order == sorted(
        order, key=["MITREN", "MIMACRO", "ALIMENTADORA", "SITREN", "MITRANSPORTE"].index
    )


def test_gtfs_download_is_cached_and_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = make_gtfs_zip(tmp_path / "feed.zip")
    downloads: list[str] = []

    def fake_stream(url: str, path: Path, *, timeout: int = 300) -> None:
        downloads.append(url)
        shutil.copyfile(feed, path)

    monkeypatch.setattr(mx_common, "stream_download", fake_stream)
    cache = tmp_path / "cache"
    for _ in range(2):
        gt.fetch_gtfs_transit(
            "guadalajara",
            profile=gdl_profile(),
            cache_dir=cache,
            output_path=tmp_path / "out.csv",
        )
    assert len(downloads) == 1
    assert (cache / "guadalajara_setran_gtfs.zip").exists()

    broken = make_gtfs_zip(tmp_path / "broken.zip", drop="stop_times.txt")
    monkeypatch.setattr(
        mx_common, "stream_download", lambda url, path, **_: shutil.copyfile(broken, path)
    )
    other_cache = tmp_path / "other"
    with pytest.raises(FetchError, match="stop_times.txt"):
        gt.fetch_gtfs_transit(
            "guadalajara",
            profile=gdl_profile(),
            cache_dir=other_cache,
            output_path=tmp_path / "x.csv",
        )
    assert not list(other_cache.glob("*"))


def test_validate_gtfs_zip_rejects_bad_bodies(tmp_path: Path) -> None:
    not_zip = tmp_path / "page.zip"
    not_zip.write_text("<html>error</html>", encoding="utf-8")
    with pytest.raises(FetchError, match="not a zip"):
        gt.validate_gtfs_zip(not_zip)
    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(FetchError, match="unsafe"):
        gt.validate_gtfs_zip(unsafe)
    no_columns = make_gtfs_zip(tmp_path / "cols.zip", drop="stops.txt")
    with zipfile.ZipFile(no_columns, "a") as zf:
        zf.writestr("stops.txt", "stop_id,stop_name\nS1,x\n")
    with pytest.raises(FetchError, match="stop_lat"):
        gt.validate_gtfs_zip(no_columns)


def test_gtfs_fails_when_a_declared_system_is_empty(tmp_path: Path) -> None:
    profile = gdl_profile()
    profile["transit_systems"] = [
        *profile["transit_systems"],
        {"code": "SUBURBANO", "slug": "suburbano", "group": "core", "label": "Suburbano"},
    ]
    with pytest.raises(FetchError, match="SUBURBANO"):
        _gtfs_rows(tmp_path, profile)
    assert not (tmp_path / "transit_stops.csv").exists()


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        ({"system": "MITREN", "agency": ["MT"], "typo": 1}, "unknown keys"),
        ({"system": "NOPE"}, "not a declared"),
        ({"system": "MITREN", "agency": "MT"}, "list of strings"),
        ({"system": "MIMACRO", "corridor_only": True, "line": "L5"}, "offcorridor_system"),
        (
            {
                "system": "MIMACRO",
                "corridor_only": True,
                "line": "L5",
                "offcorridor_system": "MITREN",
            },
            "surface",
        ),
        ({"system": "SITREN", "subtract_line": "L7", "line": "x"}, "core system"),
        ({"system": "MIMACRO", "subtract_line": "L7"}, "fixed line"),
        ({"system": "MITREN", "route_desc": "("}, "valid regex"),
    ],
)
def test_parse_rules_rejects_bad_config(rule: dict, message: str) -> None:
    profile = gdl_profile()
    with pytest.raises(ConfigError, match=message):
        gt.parse_rules({"rules": [rule]}, gt.profile_systems(profile))


def test_single_linkage_chains_and_best_name() -> None:
    stops = [
        gt.Stop("b", "Independencia L3", 20.0, -103.0),
        gt.Stop("a", "Independencia", 20.0012, -103.0),  # ~133 m from b
        gt.Stop("c", "Independencia", 20.0024, -103.0),  # ~133 m from a, 267 m from b
        gt.Stop("d", "Otra", 20.0100, -103.0),
    ]
    clusters = gt.single_linkage(stops, 200)
    assert [[s.stop_id for s in c] for c in clusters] == [["a", "b", "c"], ["d"]]
    assert gt.best_station_name(clusters[0]) == "Independencia"
    tie = [gt.Stop("2", "Cipres", 0, 0), gt.Stop("1", "Ciprés", 0, 0)]
    assert gt.best_station_name(tie) == "Ciprés"


def test_load_route_stops_streams_only_classified_routes(tmp_path: Path) -> None:
    zip_path = make_gtfs_zip(tmp_path / "feed.zip")
    with zipfile.ZipFile(zip_path) as zf:
        route_stops = gt.load_route_stops(zf, ["C01", "MT_L1"])
        assert route_stops == {"C01": {"B1", "B2", "B3"}, "MT_L1": {"T1", "T2"}}
        stops = gt.load_stops(zf)
        assert "BAD" not in stops and stops["T1"].name == "Juárez"
        assert json.dumps(gt.calendar_range(zf)) == '["20260501", "20261231"]'
