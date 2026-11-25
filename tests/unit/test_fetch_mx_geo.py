"""Offline tests for the Mexican geography fetchers (workstream B).

``fetch_mx_postal_codes`` (municipality mode via ``mx_area``, and the legacy
``postal_code_range`` mode Morelia uses) and ``fetch_mx_colonias`` (INEGI DCAH
2025). The state-wide loaders in ``mx_common`` are replaced with tiny synthetic
GeoDataFrames, and an autouse guard fails any test that would reach the network.

Synthetic geography (lon/lat near Monterrey; the metric CRS is EPSG:32614)::

    lon  -100.40     -100.30     -100.20     -100.10
          +-----------+-----------+-----------+  25.70
          | Alfa 001  | Beta 002  | Gamma 003 |
          +-----------+-----------+-----------+  25.60

Postal polygons: 64000 and 64040 lie in Alfa; 64010 straddles Alfa (5 km) and
Beta (2 km), so Alfa wins; 64020 is in Beta; 64030 is 2 km Beta / 8 km Gamma, so
Gamma wins and it is dropped; 64050 is far away and overlaps nothing.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box, mapping

from cdmxmap.errors import ConfigError, FetchError
from cdmxmap.sources import fetch_mx_colonias as fc
from cdmxmap.sources import fetch_mx_postal_codes as fp
from cdmxmap.sources import mx_common as mc
from cdmxmap.sources.io import load_city_profile

WGS84 = "EPSG:4326"
METRIC = "EPSG:32614"
CITY = "testcity"
POSTAL_URL = "https://example.invalid/19-NL.geojson"
DCAH_URL = "https://example.invalid/19_nuevoleon.zip"
PROFILE = {
    "city_id": CITY,
    "crs_metric_epsg": 32614,
    "bbox": {"south": 25.5, "west": -100.5, "north": 25.8, "east": -100.0},
    "mx_area": {"state_code": "19", "municipalities": ["001", "002"]},
    "sources": {"postal_codes": POSTAL_URL, "colonias": DCAH_URL},
}

COLONIA_KEYS = [
    "area_unit",
    "area_id",
    "area_name",
    "display_name",
    "colonia_name",
    "municipio",
    "mun_code",
    "col_code",
    "col_type",
    "postal_code",
    "year",
    "source",
]
POSTAL_KEYS = ["d_codigo", "mun_code", "municipio", "colonias_label", "colonias_count", "source"]


# ---------------------------------------------------------------------------
# Synthetic inputs
# ---------------------------------------------------------------------------


def municipalities_frame() -> gpd.GeoDataFrame:
    """Shape of ``mx_common.load_state_municipalities``: the whole state."""
    return gpd.GeoDataFrame(
        {
            "mun_code": ["19001", "19002", "19003"],
            "cve_mun": ["001", "002", "003"],
            "municipio": ["Alfa", "Beta", "Gamma"],
            "population": [1000, 2000, 3000],
        },
        geometry=[
            box(-100.40, 25.60, -100.30, 25.70),
            box(-100.30, 25.60, -100.20, 25.70),
            box(-100.20, 25.60, -100.10, 25.70),
        ],
        crs=WGS84,
    )


def postal_frame() -> gpd.GeoDataFrame:
    """Shape of ``mx_common.load_state_postal_polygons``: 5-digit str ``d_codigo``."""
    return gpd.GeoDataFrame(
        {"d_codigo": ["64000", "64010", "64020", "64030", "64040", "64050"]},
        geometry=[
            box(-100.40, 25.60, -100.35, 25.65),
            box(-100.35, 25.60, -100.28, 25.65),
            box(-100.28, 25.60, -100.20, 25.65),
            box(-100.22, 25.65, -100.12, 25.70),
            box(-100.40, 25.65, -100.33, 25.70),
            box(-99.00, 24.00, -98.90, 24.10),
        ],
        crs=WGS84,
    )


# (cvegeo, cp, fecha_act, nom_asen, tipo); cve_mun is cvegeo[2:5], cve_asen cvegeo[-4:].
DCAH_ROWS = [
    # 64000 (Alfa): two spellings of one name, a roman numeral, a placeholder.
    ("1900100010001", "64000", "11/2025", "COLONIA DEL VALLE", "COLONIA"),
    ("1900100010002", "00000", "11/2024", "JARDINES DEL VALLE", "FRACCIONAMIENTO"),
    ("1900100010003", "64000", "11/2022", "COLONIA  DEL VÁLLE", "COLONIA"),
    ("1900100010004", "64000", "11/2025", "SECTOR III", "NINGUNO"),
    ("1900100010005", "64000", "11/2025", "NINGUNO", "NINGUNO"),
    ("1900100010006", "64000", "11/2025", "LAS PALMAS", "BARRIO"),
    # 64010 (Alfa side): an empty cp falls back to the polygon at the representative point.
    ("1900100010007", "", "11/2024", "CENTRO", "COLONIA"),
    # Alfa, outside every postal polygon: no postal code at all.
    ("1900100010008", "00000", "sin fecha", "LOMA ALTA", "COLONIA"),
    # 64020 (Beta): the larger "Zacatecas" must come before the smaller "Mixed Case Name".
    ("1900200010001", "64020", "11/2025", "Mixed Case Name", "COLONIA"),
    ("1900200010002", "64020", "11/2025", "ZACATECAS", "COLONIA"),
    # Gamma (not a member): one inside a member CP, one inside its own CP.
    ("1900300010001", "64020", "11/2025", "INTRUSO", "COLONIA"),
    ("1900300010002", "64030", "11/2025", "GAMMA NORTE", "COLONIA"),
]
DCAH_BOUNDS = [
    (-100.40, 25.60, -100.37, 25.63),
    (-100.37, 25.60, -100.355, 25.615),
    (-100.36, 25.63, -100.355, 25.635),
    (-100.39, 25.635, -100.38, 25.645),
    (-100.385, 25.64, -100.38, 25.645),
    (-100.37, 25.64, -100.368, 25.642),
    (-100.34, 25.61, -100.33, 25.62),
    (-100.32, 25.66, -100.31, 25.67),
    (-100.27, 25.61, -100.26, 25.62),
    (-100.25, 25.61, -100.22, 25.64),
    (-100.24, 25.605, -100.235, 25.61),
    (-100.18, 25.66, -100.15, 25.69),
]


def dcah_frame(count: int | None = None) -> gpd.GeoDataFrame:
    """Shape of ``mx_common.load_dcah`` (lowercase DCAH columns, EPSG:4326).

    ``count`` keeps only the first rows of ``DCAH_ROWS``.
    """
    rows = DCAH_ROWS[:count]
    return gpd.GeoDataFrame(
        {
            "cvegeo": [row[0] for row in rows],
            "cve_ent": ["19"] * len(rows),
            "cve_mun": [row[0][2:5] for row in rows],
            "cve_loc": ["0001"] * len(rows),
            "cve_asen": [row[0][-4:] for row in rows],
            "cp": [row[1] for row in rows],
            "fecha_act": [row[2] for row in rows],
            "institucio": ["MUNICIPIO"] * len(rows),
            "nom_asen": [row[3] for row in rows],
            "tipo": [row[4] for row in rows],
        },
        geometry=[box(*bounds) for bounds in DCAH_BOUNDS[: len(rows)]],
        crs=WGS84,
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(url: str, path: Path, *, timeout: int = 300) -> None:
        raise AssertionError(f"test tried to download {url}")

    monkeypatch.setattr(mc, "stream_download", refuse)


@pytest.fixture
def loader_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Replace the three state loaders with the synthetic frames; log their args."""
    calls: list[tuple] = []

    def municipalities(state_code: str) -> gpd.GeoDataFrame:
        calls.append(("municipalities", state_code))
        return municipalities_frame()

    def postal(url: str) -> gpd.GeoDataFrame:
        calls.append(("postal", url))
        return postal_frame()

    def dcah(url: str, state_code: str) -> gpd.GeoDataFrame:
        calls.append(("dcah", url, state_code))
        return dcah_frame()

    monkeypatch.setattr(mc, "load_state_municipalities", municipalities)
    monkeypatch.setattr(mc, "load_state_postal_polygons", postal)
    monkeypatch.setattr(mc, "load_dcah", dcah)
    return calls


def run_main(monkeypatch: pytest.MonkeyPatch, module: ModuleType, raw: Path, profile: dict) -> None:
    monkeypatch.setattr(module, "load_city_profile", lambda city: profile)
    monkeypatch.setattr(module, "DATA_RAW", raw)
    monkeypatch.setattr(sys, "argv", ["fetch", "--city", CITY])
    module.main()


def as_json(value: object) -> object:
    """Round-trip through JSON so tuples compare equal to parsed lists."""
    return json.loads(json.dumps(value))


def read_properties(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["type"] == "FeatureCollection"
    return [feature["properties"] for feature in payload["features"]]


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_colonias_label_takes_two_names_and_counts_the_rest(self) -> None:
        assert fp.colonias_label([]) == ("", 0)
        assert fp.colonias_label(["Centro"]) == ("Centro", 1)
        assert fp.colonias_label(["A", "B"]) == ("A, B", 2)
        assert fp.colonias_label(["A", "B", "C", "D"]) == ("A, B +2", 4)

    def test_colonias_label_dedupes_case_accent_and_space_insensitively(self) -> None:
        names = ["Del Valle", "del  valle", "DEL VÁLLE", "Jardines", "Centro"]
        assert fp.colonias_label(names) == ("Del Valle, Jardines +1", 3)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("64000", "64000"), (" 66220 ", "66220"), ("00000", ""), ("", ""), (None, "")],
    )
    def test_dcah_postal_code(self, value: object, expected: str) -> None:
        assert fc.dcah_postal_code(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"), [("11/2025", "2025"), ("2021", "2021"), ("", ""), (None, "")]
    )
    def test_dcah_year(self, value: object, expected: str) -> None:
        assert fc.dcah_year(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("COLONIA", "Colonia"),
            ("PARQUE INDUSTRIAL", "Parque Industrial"),
            ("RANCHERÍA", "Ranchería"),
            ("NINGUNO", ""),
            ("Ninguno", ""),
        ],
    )
    def test_colonia_type(self, value: str, expected: str) -> None:
        assert fc.colonia_type(value) == expected

    def test_metric_crs_and_sources_come_from_the_profile(self) -> None:
        assert fc.metric_crs(PROFILE, CITY) == METRIC
        assert fc.source_url(PROFILE, "colonias", CITY) == DCAH_URL
        with pytest.raises(ConfigError):
            fc.metric_crs({}, CITY)
        with pytest.raises(ConfigError):
            fc.source_url({"sources": {"colonias": ""}}, "colonias", CITY)

    def test_point_postal_codes_picks_the_lowest_code_on_a_shared_edge(self) -> None:
        postal = gpd.GeoDataFrame(
            {"d_codigo": ["64020", "64010"]},
            geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
            crs=WGS84,
        )
        points = gpd.GeoSeries.from_xy([1.0, 0.5, 5.0], [0.5, 0.5, 5.0], crs=WGS84)
        # Compared in WGS84 so no projection can nudge the point off the shared edge.
        codes = fc.point_postal_codes(points, postal, WGS84)
        assert codes.tolist() == ["64010", "64020", ""]
        assert fc.point_postal_codes(points.iloc[:0], postal, WGS84).tolist() == []


# ---------------------------------------------------------------------------
# Colonias
# ---------------------------------------------------------------------------


class TestColonias:
    def test_member_colonias_keeps_named_member_polygons(self) -> None:
        kept, dropped = fc.member_colonias(dcah_frame(), "19", ["001", "002"])
        assert dropped == 1  # NINGUNO in Alfa; Gamma's rows are not members at all
        assert kept["cvegeo"].tolist() == [
            "1900100010001",
            "1900100010002",
            "1900100010003",
            "1900100010004",
            "1900100010006",
            "1900100010007",
            "1900100010008",
            "1900200010001",
            "1900200010002",
        ]
        assert kept["colonia_name"].tolist()[:4] == [
            "Colonia del Valle",
            "Jardines del Valle",
            "Colonia del Válle",
            "Sector III",
        ]

    def test_member_colonias_pads_municipality_codes(self) -> None:
        frame = dcah_frame(1)
        frame["cve_mun"] = [1]
        kept, dropped = fc.member_colonias(frame, "19", ["001"])
        assert (len(kept), dropped) == (1, 0)
        assert kept["cve_mun"].tolist() == ["001"]

    def test_normalize_colonias_matches_the_spec_contract(self) -> None:
        kept, _ = fc.member_colonias(dcah_frame(), "19", ["001", "002"])
        frame = fc.normalize_colonias(kept, municipalities_frame(), postal_frame(), METRIC)
        assert list(frame.columns) == [*COLONIA_KEYS, "geometry"]
        assert frame.crs == WGS84
        assert frame["area_id"].tolist() == sorted(frame["area_id"])
        rows = {row["area_id"]: row for row in frame.drop(columns="geometry").to_dict("records")}
        assert rows["1900100010001"] == {
            "area_unit": "colonia",
            "area_id": "1900100010001",
            "area_name": "Colonia del Valle",
            "display_name": "Colonia del Valle",
            "colonia_name": "Colonia del Valle",
            "municipio": "Alfa",
            "mun_code": "19001",
            "col_code": "0001",
            "col_type": "Colonia",
            "postal_code": "64000",
            "year": "2025",
            "source": "inegi_dcah_2025",
        }
        # "00000" and "" fall back to the polygon at the representative point.
        assert rows["1900100010002"]["postal_code"] == "64000"
        assert rows["1900100010007"]["postal_code"] == "64010"
        # No polygon there either: left empty, never invented.
        assert rows["1900100010008"]["postal_code"] == ""
        assert rows["1900100010008"]["year"] == ""
        assert rows["1900100010004"]["col_type"] == ""  # tipo NINGUNO
        assert rows["1900100010004"]["colonia_name"] == "Sector III"
        assert rows["1900200010001"]["colonia_name"] == "Mixed Case Name"
        assert rows["1900200010001"]["municipio"] == "Beta"
        assert frame.attrs["postal_code_counts"] == {"dcah": 6, "sepomex_polygon": 2, "missing": 1}

    def test_normalize_colonias_rejects_bad_identifiers(self) -> None:
        kept, _ = fc.member_colonias(dcah_frame(), "19", ["001", "002"])
        repeated = kept.copy()
        repeated.loc[repeated.index[1], "cvegeo"] = repeated["cvegeo"].iloc[0]
        with pytest.raises(FetchError, match="repeats"):
            fc.normalize_colonias(repeated, municipalities_frame(), postal_frame(), METRIC)
        short = kept.copy()
        short.loc[short.index[0], "cvegeo"] = "19001"
        with pytest.raises(FetchError, match="13 characters"):
            fc.normalize_colonias(short, municipalities_frame(), postal_frame(), METRIC)

    def test_main_writes_colonias_geojson(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        loader_calls: list[tuple],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_main(monkeypatch, fc, tmp_path, PROFILE)
        target = tmp_path / CITY / "colonias.geojson"
        properties = read_properties(target)
        assert len(properties) == 9
        assert all(list(props) == COLONIA_KEYS for props in properties)
        assert {props["mun_code"] for props in properties} == {"19001", "19002"}
        assert all(props["source"] == "inegi_dcah_2025" for props in properties)
        assert ("dcah", DCAH_URL, "19") in loader_calls
        assert ("municipalities", "19") in loader_calls
        assert ("postal", POSTAL_URL) in loader_calls
        out = capsys.readouterr().out
        assert "Kept 9 named DCAH colonias in 2 municipalities; dropped 1 unnamed" in out
        assert "WARNING" not in out
        assert not list((tmp_path / CITY).glob("*.part*"))
        # The GeoJSON layer is named after the target, not the random temp file,
        # so a rerun on identical inputs rewrites identical bytes.
        assert json.loads(target.read_text(encoding="utf-8"))["name"] == "colonias"
        first = target.read_bytes()
        run_main(monkeypatch, fc, tmp_path, PROFILE)
        assert target.read_bytes() == first

    def test_main_warns_when_colonias_leave_the_bbox(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        loader_calls: list[tuple],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        tight = {**PROFILE, "bbox": {"south": 25.6, "west": -100.39, "north": 25.7, "east": -100.2}}
        run_main(monkeypatch, fc, tmp_path, tight)
        assert (
            "WARNING: testcity colonias extend beyond the profile bbox" in capsys.readouterr().out
        )

    def test_member_without_named_colonias_fails_loudly(
        self, monkeypatch: pytest.MonkeyPatch, loader_calls: list[tuple]
    ) -> None:
        profile = {**PROFILE, "mx_area": {"state_code": "19", "municipalities": ["001", "003"]}}
        monkeypatch.setattr(mc, "load_dcah", lambda url, state: dcah_frame(8))
        with pytest.raises(FetchError, match=r"\['003'\]"):
            fc.build_colonias(profile, CITY)

    def test_unknown_member_municipality_is_a_config_error(self, loader_calls: list[tuple]) -> None:
        profile = {**PROFILE, "mx_area": {"state_code": "19", "municipalities": ["001", "099"]}}
        with pytest.raises(ConfigError, match="099"):
            fc.build_colonias(profile, CITY)


# ---------------------------------------------------------------------------
# Postal codes, municipality mode
# ---------------------------------------------------------------------------


EXPECTED_POSTAL = [
    {
        "d_codigo": "64000",
        "mun_code": "19001",
        "municipio": "Alfa",
        "colonias_label": "Colonia del Valle, Jardines del Valle +2",
        "colonias_count": 4,
        "source": "open_mexico_sepomex",
    },
    {
        "d_codigo": "64010",
        "mun_code": "19001",
        "municipio": "Alfa",
        "colonias_label": "Centro",
        "colonias_count": 1,
        "source": "open_mexico_sepomex",
    },
    {
        "d_codigo": "64020",
        "mun_code": "19002",
        "municipio": "Beta",
        "colonias_label": "Zacatecas, Mixed Case Name",
        "colonias_count": 2,
        "source": "open_mexico_sepomex",
    },
    {
        "d_codigo": "64040",
        "mun_code": "19001",
        "municipio": "Alfa",
        "colonias_label": "",
        "colonias_count": 0,
        "source": "open_mexico_sepomex",
    },
]


class TestPostalMunicipalityMode:
    def test_municipality_postal_areas_matches_the_spec_contract(self) -> None:
        colonias, _ = fc.member_colonias(dcah_frame(), "19", ["001", "002"])
        frame = fp.municipality_postal_areas(
            postal_frame(), municipalities_frame(), colonias, ["001", "002"], METRIC, CITY
        )
        assert list(frame.columns) == [*POSTAL_KEYS, "geometry"]
        assert frame.crs == WGS84
        assert frame.drop(columns="geometry").to_dict("records") == EXPECTED_POSTAL
        expected_geometry = postal_frame().set_index("d_codigo").geometry
        for code, geometry in zip(frame["d_codigo"], frame.geometry):
            assert geometry.equals(expected_geometry[code])

    def test_main_writes_postal_codes_geojson(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        loader_calls: list[tuple],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_main(monkeypatch, fp, tmp_path, PROFILE)
        target = tmp_path / CITY / "postal_codes.geojson"
        properties = read_properties(target)
        assert properties == EXPECTED_POSTAL
        assert json.loads(target.read_text(encoding="utf-8"))["name"] == "postal_codes"
        assert [list(props) for props in properties] == [POSTAL_KEYS] * len(EXPECTED_POSTAL)
        assert ("postal", POSTAL_URL) in loader_calls
        assert ("dcah", DCAH_URL, "19") in loader_calls
        out = capsys.readouterr().out
        assert "1 postal polygons overlap no INEGI municipality" in out
        assert "4 postal polygons in 2 municipalities; 1 without a DCAH colonia label" in out
        assert "WARNING" not in out

    def test_member_municipality_without_polygons_fails_loudly(self) -> None:
        municipalities = municipalities_frame()
        far = gpd.GeoDataFrame(
            {"mun_code": ["19004"], "cve_mun": ["004"], "municipio": ["Delta"], "population": [1]},
            geometry=[box(-101.5, 26.5, -101.4, 26.6)],
            crs=WGS84,
        )
        state = gpd.GeoDataFrame(pd.concat([municipalities, far], ignore_index=True), crs=WGS84)
        colonias, _ = fc.member_colonias(dcah_frame(), "19", ["001", "004"])
        with pytest.raises(FetchError, match=r"\['19004'\]"):
            fp.municipality_postal_areas(
                postal_frame(), state, colonias, ["001", "004"], METRIC, CITY
            )

    def test_repeated_postal_code_fails_loudly(self) -> None:
        postal = postal_frame()
        postal.loc[1, "d_codigo"] = "64000"
        colonias, _ = fc.member_colonias(dcah_frame(), "19", ["001", "002"])
        with pytest.raises(FetchError, match="repeats d_codigo"):
            fp.municipality_postal_areas(
                postal, municipalities_frame(), colonias, ["001", "002"], METRIC, CITY
            )

    def test_committed_profiles_select_the_right_mode(self) -> None:
        for city, state, count in [("monterrey", "19", 12), ("guadalajara", "14", 7)]:
            profile = load_city_profile(city)
            assert "mx_area" in profile
            assert "postal_code_range" not in profile
            code, members = mc.profile_mx_area(profile, city)
            assert (code, len(members)) == (state, count)
            assert fc.source_url(profile, "colonias", city).endswith(".zip")
            assert fc.metric_crs(profile, city) in {"EPSG:32613", "EPSG:32614"}
        morelia = load_city_profile("morelia")
        assert "mx_area" not in morelia
        assert fp._postal_range(morelia, "morelia") == (58000, 58399)


# ---------------------------------------------------------------------------
# Postal codes, legacy range mode (Morelia) must not move
# ---------------------------------------------------------------------------


MICHOACAN_URL = "https://raw.githubusercontent.com/open-mexico/mexico-geojson/main/16-Mich.geojson"
LEGACY_BBOX = {"south": 19.44, "west": -101.61, "north": 19.96, "east": -101.04}
LEGACY_PROFILE = {
    "city_id": "morelia",
    "postal_code_range": [58000, 58399],
    "bbox": LEGACY_BBOX,
    "sources": {"postal_codes": MICHOACAN_URL},
}


def legacy_state_file(path: Path) -> None:
    """A tiny Michoacán-like state file: integer d_codigo, the only property."""
    features = []
    for code, bounds in [
        (58000, (-101.20, 19.70, -101.19, 19.71)),  # in range, in bbox
        (57999, (-101.30, 19.70, -101.29, 19.71)),  # below range
        (58399, (-101.62, 19.60, -101.60, 19.62)),  # in range, straddles the west edge
        (58400, (-101.10, 19.80, -101.09, 19.81)),  # above range
        (58100, (-100.50, 19.70, -100.49, 19.71)),  # in range, outside bbox
        (58250, (-101.05, 19.90, -101.04, 19.91)),  # in range, in bbox
    ]:
        geometry = mapping(box(*bounds))
        features.append({"type": "Feature", "properties": {"d_codigo": code}, "geometry": geometry})
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))


def legacy_reference(source: Path, target: Path) -> None:
    """The pre-municipality-mode algorithm, verbatim, as an independent oracle."""
    areas = gpd.read_file(source).to_crs("EPSG:4326")
    bbox = LEGACY_BBOX
    areas = areas.cx[bbox["west"] : bbox["east"], bbox["south"] : bbox["north"]].copy()
    codes = areas["d_codigo"].astype(int)
    areas = areas[(codes >= 58000) & (codes <= 58399)].copy()
    areas.to_file(target, driver="GeoJSON")


class TestPostalLegacyMode:
    def test_range_mode_output_is_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = tmp_path / "16-Mich.geojson"
        legacy_state_file(source)
        cache = tmp_path / "cache"
        out = tmp_path / "out"
        downloads: list[str] = []

        def serve(url: str, path: Path, *, timeout: int = 300) -> None:
            downloads.append(url)
            shutil.copyfile(source, path)

        def forbidden(*args: object) -> None:
            raise AssertionError("legacy mode must not load municipality-mode inputs")

        monkeypatch.setattr(mc, "stream_download", serve)
        monkeypatch.setattr(mc, "DATA_RAW", cache)
        for loader in ("load_state_municipalities", "load_state_postal_polygons", "load_dcah"):
            monkeypatch.setattr(mc, loader, forbidden)
        monkeypatch.setattr(fp, "city_bbox", lambda city: LEGACY_BBOX)
        run_main(monkeypatch, fp, out, LEGACY_PROFILE)

        assert downloads == [MICHOACAN_URL]
        assert (cache / "mx_16-Mich.geojson").read_bytes() == source.read_bytes()
        target = out / CITY / "postal_codes.geojson"
        assert read_properties(target) == [
            {"d_codigo": 58000},
            {"d_codigo": 58399},
            {"d_codigo": 58250},
        ]
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["name"] == "postal_codes"
        assert [feature["geometry"] for feature in payload["features"]] == [
            as_json(mapping(box(*bounds)))
            for bounds in [
                (-101.20, 19.70, -101.19, 19.71),
                (-101.62, 19.60, -101.60, 19.62),
                (-101.05, 19.90, -101.04, 19.91),
            ]
        ]
        # Same file name, so GDAL's layer name matches too: the bytes must be identical.
        reference = tmp_path / "oracle" / "postal_codes.geojson"
        reference.parent.mkdir()
        legacy_reference(source, reference)
        assert target.read_bytes() == reference.read_bytes()

    def test_range_mode_still_requires_a_range(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile = {
            key: value for key, value in LEGACY_PROFILE.items() if key != "postal_code_range"
        }
        with pytest.raises(ValueError, match="postal_code_range"):
            run_main(monkeypatch, fp, tmp_path, profile)
