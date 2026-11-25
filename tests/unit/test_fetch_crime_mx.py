"""Offline tests for the Mexican crime fetchers (SESNSP statistics, IIEG points).

Every network seam is replaced: ``sharepoint_download`` and ``fetch_page`` in both
modules and ``mx_common.stream_download``; an autouse guard fails any test that
would reach the network. The SESNSP and IIEG files are tiny synthetic CSVs zipped in
``tmp_path`` (Latin-1 without BOM like 2015-2025, UTF-8 with BOM like RNID 2026);
the index pages are small synthetic HTML files in ``tests/fixtures/mx_crime/``.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from cdmxmap.errors import FetchError
from cdmxmap.sources import fetch_iieg_crime as iieg
from cdmxmap.sources import fetch_sesnsp_crime_statistics as sesnsp
from cdmxmap.sources import mx_common

FIXTURES = Path(__file__).parents[1] / "fixtures" / "mx_crime"
REAL_SHAREPOINT_DOWNLOAD = sesnsp.sharepoint_download
REAL_STREAM_DOWNLOAD = mx_common.stream_download
SESNSP_INDEX = (
    "https://www.gob.mx/sesnsp/acciones-y-programas/datos-abiertos-de-incidencia-delictiva"
)
IIEG_INDEX = "https://iieg.gob.mx/ns/?page_id=31143"
SHARE = "https://sspcgob-my.sharepoint.com/:u:/g/personal/test"
CURRENT_URL = f"{SHARE}/MUN26?e=bbb&download=1"
HISTORIC_URL = f"{SHARE}/MUN1525?e=fff&download=1"
IIEG_2025 = (
    "https://iieg.gob.mx/ns/wp-content/uploads/2025/09/"
    "historico_incidencia_delictiva_region_centro_jalisco_enero-2017_agosto2025.zip"
)
IIEG_2024 = "https://iieg.gob.mx/ns/wp-content/uploads/2024/09/Centro_agosto24.zip"

HEADER = (
    "Año,Clave_Ent,Entidad,Cve. Municipio,Municipio,Bien jurídico afectado,"
    "Tipo de delito,Subtipo de delito,Modalidad," + ",".join(sesnsp.MONTHS)
)
# (Clave_Ent, Cve. Municipio, Tipo, Subtipo); municipality names are irrelevant.
OffenseRow = tuple[str, str, str, str, Sequence[int]]


# ---------------------------------------------------------------------------
# Fixtures and builders
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(url: str, *args: object, **kwargs: object) -> None:
        raise AssertionError(f"test tried to reach {url}")

    monkeypatch.setattr(mx_common, "stream_download", refuse)
    monkeypatch.setattr(sesnsp, "sharepoint_download", refuse)
    monkeypatch.setattr(sesnsp, "fetch_page", refuse)
    monkeypatch.setattr(iieg, "fetch_page", refuse)


@pytest.fixture
def data_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    raw, processed = tmp_path / "raw", tmp_path / "processed"
    raw.mkdir()
    processed.mkdir()
    for module in (sesnsp, iieg):
        monkeypatch.setattr(module, "DATA_RAW", raw)
        monkeypatch.setattr(module, "DATA_PROCESSED", processed)
    monkeypatch.setattr(mx_common, "DATA_RAW", raw)
    return raw, processed


def sesnsp_csv(year: int, rows: Sequence[OffenseRow], *, encoding: str) -> bytes:
    lines = [HEADER]
    for state, mun, tipo, subtipo, months in rows:
        values = list(months) + [0] * (12 - len(months))
        lines.append(
            f"{year},{state},Estado,{mun},Municipio,Bien,{tipo},{subtipo},Modalidad,"
            + ",".join(str(v) for v in values)
        )
    body = ("\r\n".join(lines) + "\r\n").encode(encoding)
    return body


def write_zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def rnid_zip(path: Path, rows: Sequence[OffenseRow], year: int = 2026) -> Path:
    body = sesnsp_csv(year, rows, encoding="utf-8-sig")
    return write_zip(path, {f"RNID-Delitos_Municipal-{year}-oct{year}.csv": body})


def historic_zip(path: Path, rows_by_year: dict[int, Sequence[OffenseRow]]) -> Path:
    parts = [sesnsp_csv(year, rows, encoding="latin-1") for year, rows in rows_by_year.items()]
    body = parts[0] + b"".join(part.split(b"\r\n", 1)[1] for part in parts[1:])
    return write_zip(
        path,
        {
            "1. PARA_EVITAR_ERRORES_ANTES_DE_SU_USO.pdf": b"%PDF-1.4",
            "2025_oct26.xlsx": b"not a csv",
            "Municipal-Delitos-2015-2025_oct2026.csv": body,
        },
    )


TEN = [1] * 10  # Jan-Oct published, Nov-Dec still 0 (unpublished)
CURRENT_ROWS: list[OffenseRow] = [
    ("19", "19039", "Robo", "Robo a negocio", [2] * 10),
    ("19", "19039", "Violencia familiar", "Violencia familiar", [5] * 10),
    ("19", "19039", "Homicidio", "Homicidio culposo", TEN),
    ("19", "19039", "Homicidio", "Tentativa de homicidio doloso", TEN),
    ("19", "19039", "Extorsión", "Extorsión por otros medios", TEN),
    ("19", "19019", "Fraude", "Fraude", [3] * 10),
    ("19", "19019", "Violación", "Violación simple", TEN),
    ("19", "19999", "Robo", "Otros robos", [0] * 10),
    ("9", "9015", "Robo", "Otros robos", [7] * 10),  # another state, national totals only
]
HISTORIC_2025: list[OffenseRow] = [
    ("19", "19039", "Robo", "Robo a negocio", [9] * 12),
    ("19", "19039", "Violencia familiar", "Violencia familiar", [1] * 12),
    ("19", "19019", "Violación simple", "Violación simple", [4] * 12),
    ("19", "19999", "Robo", "Otros robos", [0] * 12),
    ("9", "9015", "Robo", "Otros robos", [7] * 12),
]


def municipalities_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "mun_code": ["19019", "19039", "19050"],
            "cve_mun": ["019", "039", "050"],
            "municipio": ["San Pedro Garza García", "Monterrey", "Vallecillo"],
            "population": [100_000, 1_000_000, 2_000],
        }
    )


def sesnsp_profile(**extra: object) -> dict:
    block = {
        "scope": "municipality",
        "state_codes": ["19"],
        "source": "sesnsp_municipal",
        "population_source": "INEGI Censo de Población y Vivienda 2020",
        "index_url": SESNSP_INDEX,
        **extra,
    }
    return {
        "city_id": "testcity",
        "bbox": {"south": 25.0, "west": -101.0, "north": 26.0, "east": -100.0},
        "mx_area": {"state_code": "19", "municipalities": ["019", "039"]},
        "crime_statistics": block,
    }


def serve_sharepoint(monkeypatch: pytest.MonkeyPatch, files: dict[str, Path]) -> list[str]:
    calls: list[str] = []

    def fake(url: str, path: Path, *, timeout: int = 600) -> None:
        calls.append(url)
        shutil.copyfile(files[url], path)

    monkeypatch.setattr(sesnsp, "sharepoint_download", fake)
    return calls


@pytest.fixture
def sesnsp_city(
    tmp_path: Path, data_dirs: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> Callable[..., tuple[pd.DataFrame, list[str]]]:
    """Run ``build_crime_statistics`` against synthetic releases; return (csv, URLs)."""

    def run(
        current_rows: Sequence[OffenseRow] = CURRENT_ROWS,
        historic: dict[int, Sequence[OffenseRow]] | None = None,
        profile: dict | None = None,
        html: str | None = None,
    ) -> tuple[pd.DataFrame, list[str]]:
        sources = tmp_path / "sources"
        sources.mkdir(exist_ok=True)
        files = {
            CURRENT_URL: rnid_zip(sources / "current.zip", current_rows),
            HISTORIC_URL: historic_zip(
                sources / "historic.zip", historic or {2024: HISTORIC_2025, 2025: HISTORIC_2025}
            ),
        }
        calls = serve_sharepoint(monkeypatch, files)
        page = html if html is not None else (FIXTURES / "sesnsp_index.html").read_text()
        monkeypatch.setattr(sesnsp, "fetch_page", lambda url, **_: page)
        monkeypatch.setattr(sesnsp, "load_city_profile", lambda city: profile or sesnsp_profile())
        monkeypatch.setattr(
            sesnsp, "load_state_municipalities", lambda state: municipalities_frame()
        )
        target = sesnsp.build_crime_statistics("testcity")
        return pd.read_csv(target, dtype={"unit_key": str}, keep_default_na=False), calls

    return run


# ---------------------------------------------------------------------------
# HTML anchors and SESNSP release discovery
# ---------------------------------------------------------------------------


def test_collect_anchors_decodes_entities_and_nested_tags() -> None:
    html = (
        '<p><a href=" /a.zip ">Enero&nbsp;-&nbsp;mayo <b>2026</b>\n (Fuero com&uacute;n)</a>'
        '<a href="/b">unclosed<a href="/c">third</a></p>'
    )
    assert sesnsp.collect_anchors(html) == [
        ("/a.zip", "Enero - mayo 2026 (Fuero común)"),
        ("/b", "unclosed"),
        ("/c", "third"),
    ]


def test_parse_releases_keeps_only_municipal_delitos_on_sharepoint() -> None:
    html = (FIXTURES / "sesnsp_index.html").read_text()
    releases = sesnsp.parse_releases(html, base_url=SESNSP_INDEX)
    assert [(r.first_year, r.last_year, r.last_month) for r in releases] == [
        (2026, 2026, 10),
        (2015, 2025, 12),
    ]
    current = sesnsp.select_current_release(releases)
    assert current.url == f"{SHARE}/MUN26?e=bbb"
    assert current.download_url == CURRENT_URL
    assert current.slug == "enero-octubre-2026"
    historic = sesnsp.release_covering(releases, 2025, exclude=current)
    assert historic.download_url == HISTORIC_URL
    assert sesnsp.release_cache_path(historic, current).name == (
        "mx_sesnsp_delitos_municipal_2015-2025_as-of-enero-octubre-2026.zip"
    )


def test_release_labels_cover_a_january_only_cut_and_reject_unknown_months() -> None:
    html = (
        f'<a href="{SHARE}/J?e=1">Enero 2027 (Fuero común - Delitos). '
        "Incidencia delictiva municipal</a>"
        f'<a href="{SHARE}/X?e=2">Enero - brumario 2026 (Fuero común - Delitos). '
        "Incidencia delictiva municipal</a>"
    )
    releases = sesnsp.parse_releases(html, base_url=SESNSP_INDEX)
    assert [(r.first_year, r.last_month) for r in releases] == [(2027, 1)]


def test_download_url_does_not_duplicate_the_flag() -> None:
    release = sesnsp.SesnspRelease("x", f"{SHARE}/A?download=1", 2026, 2026, 10)
    assert release.download_url == f"{SHARE}/A?download=1"
    bare = sesnsp.SesnspRelease("x", f"{SHARE}/A", 2026, 2026, 10)
    assert bare.download_url == f"{SHARE}/A?download=1"


def test_release_covering_fails_when_no_release_has_the_year() -> None:
    current = sesnsp.SesnspRelease("Enero 2027", f"{SHARE}/J", 2027, 2027, 1)
    older = sesnsp.SesnspRelease("2015 - 2025", f"{SHARE}/H", 2015, 2025, 12)
    with pytest.raises(FetchError, match="needs 2026"):
        sesnsp.release_covering([current, older], 2026, exclude=current)


def test_sharepoint_download_rejects_a_redirect_off_sharepoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def geturl(self) -> str:
            return "https://evil.example/file.zip"

    class Opener:
        def open(self, request: object, timeout: int) -> Response:
            return Response()

    monkeypatch.setattr(sesnsp.urllib.request, "build_opener", lambda *handlers: Opener())
    with pytest.raises(FetchError, match="off SharePoint"):
        REAL_SHAREPOINT_DOWNLOAD(f"{SHARE}/A?download=1", tmp_path / "x.zip")
    assert not (tmp_path / "x.zip").exists()


# ---------------------------------------------------------------------------
# Release zips: encodings, validation, streaming reads
# ---------------------------------------------------------------------------


def test_detect_encoding() -> None:
    assert sesnsp.detect_encoding(b"\xef\xbb\xbfA\xc3\xb1o,x\r\n") == "utf-8-sig"
    assert sesnsp.detect_encoding("Año,x\r\n".encode()) == "utf-8"
    assert sesnsp.detect_encoding("Año,x\r\n".encode("latin-1")) == "latin-1"


def test_read_release_handles_both_encodings_and_zero_pads(tmp_path: Path) -> None:
    rows: list[OffenseRow] = [
        ("1", "1001", "Robo", "Robo a negocio", [1, 2, 3]),
        ("19", "19039", "Robo", "Robo a negocio", [5, 0, 0]),
    ]
    old = historic_zip(tmp_path / "old.zip", {2024: rows, 2025: rows})
    new = rnid_zip(tmp_path / "new.zip", rows)

    old_counts = sesnsp.read_release(old, state_codes=["01"], years={2025})
    assert old_counts.years == {2025}
    assert old_counts.national[(2025, 1)] == 6
    assert old_counts.national[(2025, 4)] == 0
    assert old_counts.rows["mun_code"].tolist() == ["01001"]
    assert old_counts.rows[["Enero", "Febrero", "Marzo"]].iloc[0].tolist() == [1, 2, 3]

    new_counts = sesnsp.read_release(new, state_codes=["19"])
    assert new_counts.years == {2026}
    assert new_counts.national[(2026, 1)] == 6
    assert new_counts.rows["tipo"].tolist() == ["Robo"]
    assert new_counts.rows["year"].tolist() == [2026]


@pytest.mark.parametrize(
    ("members", "message"),
    [
        ({"readme.txt": b"x"}, "one municipal Delitos CSV"),
        (
            {"a/Municipal-Delitos-2015.csv": b"x", "b/RNID-Delitos_Municipal.csv": b"x"},
            "one municipal Delitos CSV",
        ),
        ({"RNID-Delitos_Municipal-2026.csv": b"\xef\xbb\xbfA,B\r\n1,2\r\n"}, "missing columns"),
    ],
)
def test_validate_release_zip_rejects_bad_archives(
    tmp_path: Path, members: dict[str, bytes], message: str
) -> None:
    path = write_zip(tmp_path / "bad.zip", members)
    with pytest.raises(ValueError, match=message):
        sesnsp.validate_release_zip(path)


def test_validate_release_zip_rejects_html(tmp_path: Path) -> None:
    path = tmp_path / "page.zip"
    path.write_text("<html>Access denied</html>")
    with pytest.raises(ValueError, match="not a zip"):
        sesnsp.validate_release_zip(path)


def test_cached_release_download_never_promotes_an_invalid_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake(url: str, path: Path, *, timeout: int = 600) -> None:
        path.write_text("<html>error</html>")

    monkeypatch.setattr(sesnsp, "sharepoint_download", fake)
    target = tmp_path / "cache" / "release.zip"
    with pytest.raises(FetchError, match="failed validation"):
        sesnsp.cached_release_download(CURRENT_URL, target, validate=sesnsp.validate_release_zip)
    assert list(target.parent.iterdir()) == []


def test_non_count_month_values_fail(tmp_path: Path) -> None:
    body = HEADER + "\r\n2026,19,E,19039,M,B,Robo,Otros robos,X,1,abc,0,0,0,0,0,0,0,0,0,0\r\n"
    path = write_zip(tmp_path / "x.zip", {"RNID-Delitos_Municipal.csv": body.encode()})
    with pytest.raises(FetchError, match="non-count value in column Febrero"):
        sesnsp.read_release(path, state_codes=["19"])


# ---------------------------------------------------------------------------
# Window and classification
# ---------------------------------------------------------------------------


def test_latest_populated_month_ignores_trailing_zero_months() -> None:
    national = {(2026, month): (100 if month <= 10 else 0) for month in range(1, 13)}
    assert sesnsp.latest_populated_month(national) == (2026, 10)
    with pytest.raises(FetchError):
        sesnsp.latest_populated_month({(2026, 1): 0})


def test_trailing_window_crosses_the_year_and_period_bounds() -> None:
    window = sesnsp.trailing_months((2026, 10))
    assert window[0] == (2025, 11)
    assert window[-1] == (2026, 10)
    assert len(window) == 12
    assert sesnsp.period_bounds(window) == ("2025-11-01", "2026-10-31")
    assert sesnsp.period_bounds(sesnsp.trailing_months((2024, 2))) == ("2023-03-01", "2024-02-29")


def test_window_with_an_unpublished_month_is_refused() -> None:
    national = {(2026, month): 100 for month in range(1, 11)}
    national[(2026, 3)] = 0
    with pytest.raises(FetchError, match="2026-03"):
        sesnsp.check_window_published(sesnsp.trailing_months((2026, 10)), national)


def test_scored_mask_covers_both_taxonomies() -> None:
    pairs = [
        ("Robo", "Robo de vehículo automotor - Motocicleta", True),
        ("Robo", "Otros robos", True),
        ("Homicidio", "Homicidio doloso", True),
        ("Homicidio", "Tentativa de homicidio doloso", True),
        ("Homicidio", "Homicidio culposo", False),
        ("Feminicidio", "Tentativa de feminicidio", True),
        ("Lesiones", "Lesiones dolosas", True),
        ("Lesiones", "Lesiones culposas", False),
        ("Secuestro", "Secuestro", True),
        ("Secuestro", "Secuestro exprés", True),
        ("Extorsión", "Extorsión", True),
        ("Extorsión", "Tentativa de extorsión por otros medios", True),
        ("Violación simple", "Violación simple", True),
        ("Violación equiparada", "Violación equiparada", True),
        ("Violación", "Violación simple", True),
        ("Violación a la intimidad sexual", "Violación a la intimidad sexual", False),
        ("Violencia familiar", "Violencia familiar", False),
        ("Narcomenudeo", "Narcomenudeo posesión simple", False),
        ("Fraude", "Fraude", False),
    ]
    long = pd.DataFrame({"tipo": [p[0] for p in pairs], "subtipo": [p[1] for p in pairs], "n": 1})
    mask = sesnsp.scored_mask(long, sesnsp.DEFAULT_SCORED_OFFENSES)
    assert mask.tolist() == [p[2] for p in pairs]
    custom = sesnsp.scored_mask(long, ["FRAUDE", "homicidio dolOSO"])
    assert long.loc[custom, "subtipo"].tolist() == ["Homicidio doloso", "Fraude"]


def test_aggregate_harmonizes_violacion_and_breaks_ties_alphabetically() -> None:
    long = pd.DataFrame(
        {
            "mun_code": ["19001", "19001", "19001", "19002", "19002", "19003"],
            "tipo": ["Violación simple", "Violación", "Fraude", "Robo", "Amenazas", "Robo"],
            "subtipo": [
                "Violación simple",
                "Violación equiparada",
                "Fraude",
                "Otros robos",
                "Amenazas",
                "Otros robos",
            ],
            "n": [2, 2, 3, 4, 4, 0],
        }
    )
    result = sesnsp.aggregate_municipalities(long, sesnsp.DEFAULT_SCORED_OFFENSES)
    assert result.loc["19001"].tolist() == [7, 4, "Violación"]
    assert result.loc["19002"].tolist() == [8, 4, "Amenazas"]
    assert result.loc["19003"].tolist() == [0, 0, ""]


# ---------------------------------------------------------------------------
# End to end (synthetic releases, no network)
# ---------------------------------------------------------------------------


def test_window_spans_the_historic_and_current_files(
    sesnsp_city: Callable[..., tuple[pd.DataFrame, list[str]]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    table, calls = sesnsp_city()
    assert calls == [CURRENT_URL, HISTORIC_URL]
    assert list(table.columns) == sesnsp.OUTPUT_COLUMNS
    # 19050 has no SESNSP rows: left out (never a fake zero); 19999 has no INEGI row.
    assert table["unit_key"].tolist() == ["19019", "19039"]
    assert set(table["period_start"]) == {"2025-11-01"}
    assert set(table["period_end"]) == {"2026-10-31"}
    assert set(table["source"]) == {"sesnsp_municipal"}
    assert set(table["population_source"]) == {"INEGI Censo de Población y Vivienda 2020"}

    monterrey = table.set_index("unit_key").loc["19039"]
    # Nov-Dec 2025: robo 9+9, violencia familiar 1+1; Jan-Oct 2026: robo 20,
    # violencia 50, culposo 10, tentativa 10, extorsión 10.
    assert monterrey["incidents_12m"] == 18 + 2 + 20 + 50 + 10 + 10 + 10
    assert monterrey["scored_incidents_12m"] == 18 + 20 + 10 + 10
    assert monterrey["top_category_12m"] == "Violencia familiar"
    assert monterrey["population"] == 1_000_000
    assert monterrey["unit_name"] == "Monterrey"

    san_pedro = table.set_index("unit_key").loc["19019"]
    assert san_pedro["incidents_12m"] == 8 + 30 + 10
    assert san_pedro["scored_incidents_12m"] == 8 + 10
    assert san_pedro["top_category_12m"] == "Fraude"

    out = capsys.readouterr().out
    assert "no SESNSP rows for INEGI municipalities ['19050']" in out
    assert "['19999'] with 0 carpetas" in out


def test_full_year_in_the_current_file_skips_the_historic_download(
    sesnsp_city: Callable[..., tuple[pd.DataFrame, list[str]]],
) -> None:
    rows = [(s, m, t, st, [1] * 12) for s, m, t, st, _ in CURRENT_ROWS]
    table, calls = sesnsp_city(current_rows=rows)
    assert calls == [CURRENT_URL]
    assert set(table["period_start"]) == {"2026-01-01"}
    assert set(table["period_end"]) == {"2026-12-31"}


def test_reruns_reuse_the_cached_releases(
    sesnsp_city: Callable[..., tuple[pd.DataFrame, list[str]]],
) -> None:
    first, calls = sesnsp_city()
    assert len(calls) == 2
    second, calls = sesnsp_city()
    assert calls == []
    pd.testing.assert_frame_equal(first, second)


def test_profile_scored_offenses_override_the_default(
    sesnsp_city: Callable[..., tuple[pd.DataFrame, list[str]]],
) -> None:
    table, _ = sesnsp_city(profile=sesnsp_profile(scored_offenses=["Violencia familiar"]))
    scored = table.set_index("unit_key")["scored_incidents_12m"]
    assert scored.to_dict() == {"19019": 0, "19039": 2 + 50}


def test_missing_metro_member_is_an_error(
    sesnsp_city: Callable[..., tuple[pd.DataFrame, list[str]]],
) -> None:
    profile = sesnsp_profile()
    profile["mx_area"]["municipalities"] = ["039", "050"]
    with pytest.raises(FetchError, match="metro municipalities \\['19050'\\]"):
        sesnsp_city(profile=profile)


def test_missing_historic_link_fails_loudly(
    sesnsp_city: Callable[..., tuple[pd.DataFrame, list[str]]],
) -> None:
    html = (FIXTURES / "sesnsp_index.html").read_text().replace("MUN1525", "STATE1525")
    html = html.replace("2015 - 2025 (Fuero Com&uacute;n - Delitos).</span>", "Otro</span>")
    with pytest.raises(FetchError, match="needs 2025"):
        sesnsp_city(html=html)


# ---------------------------------------------------------------------------
# IIEG: link discovery
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "historico_incidencia_delictiva_region_centro_jalisco_enero-2017_agosto2025.zip",
            date(2025, 8, 1),
        ),
        ("Centro_agosto24.zip", date(2024, 8, 1)),
        ("microdatos_incidencia_delictiva_region_norte_jalisco_dic25.zip", date(2025, 12, 1)),
        ("valles_abr24.zip", date(2024, 4, 1)),
        ("base_datos_incidencia_delictiva_jalisco_region_valles_abril_2025.zip", date(2025, 4, 1)),
        ("Sierra_Amula_ene24.zip", date(2024, 1, 1)),
        ("incidencia_jalisco.zip", None),
    ],
)
def test_end_month_from_name(name: str, expected: date | None) -> None:
    assert iieg.end_month_from_name(name) == expected


def test_region_candidates_follow_only_https_iieg_zips() -> None:
    html = (FIXTURES / "iieg_index.html").read_text()
    pattern = re.compile(r"regi[oó]n\s+Centro", re.IGNORECASE)
    candidates = iieg.region_zip_candidates(html, base_url=IIEG_INDEX, pattern=pattern)
    assert sorted(url for _, url in candidates) == sorted([IIEG_2025, IIEG_2024])
    assert iieg.choose_newest(candidates) == IIEG_2025


def iieg_config(fallback: str | None = IIEG_2024) -> iieg.CrimeSourceConfig:
    profile = iieg_profile()
    profile["crime_source"]["fallback_url"] = fallback
    return iieg.crime_source_config(profile, "testgdl")


def test_discover_uses_the_newest_page_link(monkeypatch: pytest.MonkeyPatch) -> None:
    html = (FIXTURES / "iieg_index.html").read_text()
    monkeypatch.setattr(iieg, "fetch_page", lambda url, **_: html)
    assert iieg.discover_zip_url(iieg_config()) == IIEG_2025


def test_discover_falls_back_when_the_page_is_down_or_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def down(url: str, **_: object) -> str:
        raise iieg.SourceUnavailableError("timeout")

    monkeypatch.setattr(iieg, "fetch_page", down)
    assert iieg.discover_zip_url(iieg_config()) == IIEG_2024
    monkeypatch.setattr(iieg, "fetch_page", lambda url, **_: "<p>spam only</p>")
    assert iieg.discover_zip_url(iieg_config()) == IIEG_2024
    with pytest.raises(FetchError, match="no crime_source.fallback_url"):
        iieg.discover_zip_url(iieg_config(fallback=None))


def test_config_rejects_a_fallback_off_iieg() -> None:
    profile = iieg_profile()
    profile["crime_source"]["fallback_url"] = "https://casino-bonus.example/centro_agosto25.zip"
    with pytest.raises(iieg.ConfigError, match="fallback_url"):
        iieg.crime_source_config(profile, "testgdl")


# ---------------------------------------------------------------------------
# IIEG: zip validation and row filtering
# ---------------------------------------------------------------------------

IIEG_COLUMNS = (
    "fecha",
    "delito",
    "x",
    "y",
    "colonia",
    "municipio",
    "clave_mun",
    "hora",
    "bien_afectado",
    "zona_geografica",
)
# (fecha, delito, x, y, colonia, municipio, hora, zona_geografica); NA = missing like IIEG.
IIEG_ROWS = [
    ("2024-09-01", "Robo a persona", "-103.35", "20.67", "CENTRO", "Guadalajara", "10:00", "AMG"),
    ("2025-08-31", "Homicidio doloso", "-103.40", "20.70", "OCULTA", "Zapopan", "N.D.", "AMG"),
    ("2025-01-15", "Violencia familiar", "NA", "NA", "NO DISPONIBLE", "Tonalá", "N.D.", "AMG"),
    ("2025-02-01", "Robo a negocio", "-103.30", "20.60", "X", "Cuquío", "9:00", "Interior"),
    ("2025-03-01", "Lesiones dolosas", "-99.10", "19.40", "X", "Guadalajara", "9:00", "AMG"),
    ("2031-01-01", "Robo a persona", "-103.35", "20.67", "X", "Guadalajara", "9:00", "AMG"),
    ("no date", "Robo a persona", "-103.35", "20.67", "X", "Guadalajara", "9:00", "AMG"),
]


def iieg_line(row: tuple[str, ...]) -> str:
    fecha, delito, x, y, colonia, municipio, hora, zona = row
    fields = [f'"{fecha}"', f'"{delito}"', x, y, f'"{colonia}"', f'"{municipio}"', "1"]
    return ",".join([*fields, f'"{hora}"', '"Bien"', f'"{zona}"'])


def iieg_zip(
    path: Path, rows: Sequence[tuple[str, ...]] = IIEG_ROWS, *, extra: dict | None = None
) -> Path:
    header = ",".join(f'"{name}"' for name in IIEG_COLUMNS)
    body = ("\n".join([header, *map(iieg_line, rows)]) + "\n").encode("utf-8-sig")
    return write_zip(path, {"Centro_agosto25.csv": body, **(extra or {})})


def iieg_profile() -> dict:
    return {
        "city_id": "testgdl",
        "bbox": {"south": 20.35, "west": -103.67, "north": 21.0, "east": -103.08},
        "crime_source": {
            "type": "iieg_jalisco",
            "source": "iieg_jalisco_fge",
            "index_url": IIEG_INDEX,
            "link_text_pattern": "regi[oó]n\\s+Centro",
            "fallback_url": IIEG_2024,
            "zona_geografica": "AMG",
        },
    }


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"second.csv": b"a,b\n"}, "exactly one CSV"),
        ({"../escape.txt": b"x"}, "unsafe member path"),
    ],
)
def test_validate_iieg_zip_rejects_bad_archives(
    tmp_path: Path, extra: dict[str, bytes], message: str
) -> None:
    path = iieg_zip(tmp_path / "x.zip", extra=extra)
    with pytest.raises(ValueError, match=message):
        iieg.validate_iieg_zip(path)


def test_validate_iieg_zip_checks_the_header(tmp_path: Path) -> None:
    path = write_zip(tmp_path / "x.zip", {"a.csv": '"fecha","delito"\n'.encode("utf-8-sig")})
    with pytest.raises(ValueError, match="missing columns"):
        iieg.validate_iieg_zip(path)
    iieg.validate_iieg_zip(iieg_zip(tmp_path / "ok.zip", extra={"notas.pdf": b"%PDF"}))


def test_read_points_filters_and_maps_columns(tmp_path: Path) -> None:
    points, counts = iieg.read_points(
        iieg_zip(tmp_path / "x.zip"),
        zona="AMG",
        bbox=iieg.sanity_bbox(iieg_profile()),
        source="iieg_jalisco_fge",
        latest_date=date(2025, 8, 31),
    )
    assert list(points.columns) == iieg.OUTPUT_COLUMNS
    assert points[["date", "category", "offense", "borough"]].values.tolist() == [
        ["2024-09-01", "Robo a persona", "Robo a persona", "Guadalajara"],
        ["2025-08-31", "Homicidio doloso", "Homicidio doloso", "Zapopan"],
    ]
    assert points["latitude"].tolist() == [20.67, 20.70]
    assert points["longitude"].tolist() == [-103.35, -103.40]
    assert set(points["source"]) == {"iieg_jalisco_fge"}
    assert counts == {
        "rows_read": 7,
        "kept_zona": 6,
        "dropped_invalid_date": 2,  # the future date and the unparseable one
        "dropped_no_offense": 0,
        "dropped_no_coordinates": 1,
        "dropped_outside_bbox": 1,
        "written": 2,
    }


def test_fetch_iieg_crime_end_to_end_prints_counts_only(
    tmp_path: Path,
    data_dirs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw, processed = data_dirs
    source = iieg_zip(tmp_path / "source.zip")
    calls: list[str] = []
    checks: list[Callable[[str], bool] | None] = []

    def serve(
        url: str,
        path: Path,
        *,
        timeout: int = 300,
        allowed_final_url: Callable[[str], bool] | None = None,
    ) -> None:
        calls.append(url)
        checks.append(allowed_final_url)
        shutil.copyfile(source, path)

    monkeypatch.setattr(mx_common, "stream_download", serve)
    html = (FIXTURES / "iieg_index.html").read_text()
    monkeypatch.setattr(iieg, "fetch_page", lambda url, **_: html)
    monkeypatch.setattr(iieg, "load_city_profile", lambda city: iieg_profile())

    target = iieg.fetch_iieg_crime("testgdl")
    assert calls == [IIEG_2025]
    # the zip download carries the https + iieg.gob.mx final-URL check
    assert checks == [iieg.is_iieg_url]
    assert target == processed / "testgdl" / "crime_points.csv"
    assert (raw / "testgdl" / f"iieg_{IIEG_2025.rsplit('/', 1)[1]}").exists()
    written = pd.read_csv(target)
    assert len(written) == 2
    out = capsys.readouterr().out
    assert "Points by year: 2024 1, 2025 1" in out
    for secret in ("OCULTA", "-103.4", "20.7", "N.D."):
        assert secret not in out

    iieg.fetch_iieg_crime("testgdl")  # cached: no second download
    assert calls == [IIEG_2025]


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


@pytest.mark.parametrize(
    "final_url",
    [
        "https://evil.example/historico.zip",  # off-host
        IIEG_2025.replace("https://", "http://"),  # downgraded to plain http
        "https://iieg.gob.mx.evil.example/historico.zip",  # look-alike host
    ],
)
def test_fetch_iieg_crime_refuses_a_redirect_off_https_iieg(
    tmp_path: Path,
    data_dirs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    final_url: str,
) -> None:
    raw, processed = data_dirs
    body = iieg_zip(tmp_path / "source.zip").read_bytes()
    opened: list[str] = []

    def fake_urlopen(request, timeout: int, context: object = None) -> _RedirectedResponse:
        opened.append(request.full_url)
        return _RedirectedResponse(body, final_url)

    # The real stream_download over a fake urlopen that reports a redirect.
    monkeypatch.setattr(mx_common, "stream_download", REAL_STREAM_DOWNLOAD)
    monkeypatch.setattr(mx_common.urllib.request, "urlopen", fake_urlopen)
    html = (FIXTURES / "iieg_index.html").read_text()
    monkeypatch.setattr(iieg, "fetch_page", lambda url, **_: html)
    monkeypatch.setattr(iieg, "load_city_profile", lambda city: iieg_profile())

    with pytest.raises(FetchError, match="disallowed URL"):
        iieg.fetch_iieg_crime("testgdl")
    assert opened == [IIEG_2025]
    # nothing cached (no temp file either) and nothing written downstream
    assert not (raw / "testgdl").exists() or list((raw / "testgdl").iterdir()) == []
    assert not (processed / "testgdl" / "crime_points.csv").exists()


def test_fetch_iieg_crime_accepts_an_on_host_https_final_url(
    tmp_path: Path,
    data_dirs: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, _ = data_dirs
    body = iieg_zip(tmp_path / "source.zip").read_bytes()
    final_url = IIEG_2025.replace("/2025/09/", "/2025/10/")  # same host, moved file

    def fake_urlopen(request, timeout: int, context: object = None) -> _RedirectedResponse:
        return _RedirectedResponse(body, final_url)

    monkeypatch.setattr(mx_common, "stream_download", REAL_STREAM_DOWNLOAD)
    monkeypatch.setattr(mx_common.urllib.request, "urlopen", fake_urlopen)
    html = (FIXTURES / "iieg_index.html").read_text()
    monkeypatch.setattr(iieg, "fetch_page", lambda url, **_: html)
    monkeypatch.setattr(iieg, "load_city_profile", lambda city: iieg_profile())

    iieg.fetch_iieg_crime("testgdl")
    assert (raw / "testgdl" / f"iieg_{IIEG_2025.rsplit('/', 1)[1]}").read_bytes() == body
