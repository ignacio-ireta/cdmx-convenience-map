"""Offline tests for the shared Mexican source helpers and the Overpass retry.

Every download goes through ``mx_common.stream_download`` (or ``io.post_overpass``),
which these tests replace; an autouse guard fails any test that would reach the
network. Inputs are tiny synthetic GeoJSON/shapefile zips built in ``tmp_path``.
"""

from __future__ import annotations

import email.message
import json
import os
import shutil
import ssl
import stat
import urllib.error
import urllib.parse
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon, box

from cdmxmap.errors import ConfigError, FetchError, SourceUnavailableError
from cdmxmap.sources import fetch_mx_postal_codes
from cdmxmap.sources import io as sio
from cdmxmap.sources import mx_common as mc

REAL_STREAM_DOWNLOAD = mc.stream_download
REPO_CITIES = Path(__file__).parents[2] / "data" / "cities"
BOWTIE = [[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(url: str, path: Path, *, timeout: int = 300) -> None:
        raise AssertionError(f"test tried to download {url}")

    monkeypatch.setattr(mc, "stream_download", refuse)


@pytest.fixture
def raw_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    target = tmp_path / "raw"
    target.mkdir()
    monkeypatch.setattr(mc, "DATA_RAW", target)
    return target


def serve(monkeypatch: pytest.MonkeyPatch, body: bytes | Path) -> list[str]:
    """Replace the network seam with one that writes ``body``; returns the URL log."""
    calls: list[str] = []

    def fake(url: str, path: Path, *, timeout: int = 300) -> None:
        calls.append(url)
        if isinstance(body, Path):
            shutil.copyfile(body, path)
        else:
            path.write_bytes(body)

    monkeypatch.setattr(mc, "stream_download", fake)
    return calls


def feature_collection(features: list[dict], **extra: object) -> bytes:
    return json.dumps({"type": "FeatureCollection", **extra, "features": features}).encode()


def polygon_feature(props: dict, ring: list[list[float]], **geometry_extra: object) -> dict:
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Polygon", "coordinates": [ring], **geometry_extra},
    }


def square(x0: float, y0: float, size: float = 0.01) -> list[list[float]]:
    return [[x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size], [x0, y0]]


def leftovers(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if ".part" in p.name)


# ---------------------------------------------------------------------------
# cached_download
# ---------------------------------------------------------------------------


class TestCachedDownload:
    def test_downloads_validates_then_promotes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = serve(monkeypatch, b"payload")
        seen: list[Path] = []

        def validate(path: Path) -> None:
            seen.append(path)
            assert path.read_bytes() == b"payload"
            assert not (tmp_path / "data.zip").exists()  # not promoted yet

        target = tmp_path / "data.zip"
        assert mc.cached_download("https://x/data.zip", target, validate=validate) == target
        assert target.read_bytes() == b"payload"
        assert calls == ["https://x/data.zip"]
        # Validation ran on a temp file beside the target that keeps its suffix
        # (so GDAL / /vsizip/ still recognize it), and nothing is left behind.
        assert seen[0].parent == tmp_path and seen[0] != target
        assert seen[0].name.endswith(".part.zip")
        assert leftovers(tmp_path) == []

    def test_reuses_non_empty_cache_unless_forced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "data.geojson"
        target.write_bytes(b"old")
        calls = serve(monkeypatch, b"new")
        mc.cached_download("https://x/data.geojson", target)
        assert calls == [] and target.read_bytes() == b"old"
        mc.cached_download("https://x/data.geojson", target, force=True)
        assert calls == ["https://x/data.geojson"] and target.read_bytes() == b"new"

    def test_empty_cache_file_is_refetched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "data.geojson"
        target.write_bytes(b"")
        calls = serve(monkeypatch, b"fresh")
        mc.cached_download("https://x/data.geojson", target)
        assert calls and target.read_bytes() == b"fresh"

    def test_validation_failure_keeps_existing_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "data.geojson"
        target.write_bytes(b"good")
        serve(monkeypatch, b"<html>error</html>")

        def reject(path: Path) -> None:
            raise ValueError("not geojson")

        with pytest.raises(FetchError, match="failed validation: not geojson"):
            mc.cached_download("https://x/data.geojson", target, validate=reject, force=True)
        assert target.read_bytes() == b"good"
        assert leftovers(tmp_path) == []

    def test_validation_failure_creates_no_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        serve(monkeypatch, b"junk")
        target = tmp_path / "sub" / "data.geojson"
        with pytest.raises(FetchError):
            mc.cached_download("https://x/data.geojson", target, validate=mc._validate_feature_file)
        assert not target.exists()
        assert leftovers(target.parent) == []

    def test_empty_body_is_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        serve(monkeypatch, b"")
        with pytest.raises(FetchError, match="empty body"):
            mc.cached_download("https://x/a.csv", tmp_path / "a.csv")
        assert not (tmp_path / "a.csv").exists()

    def test_network_error_is_typed_and_cleans_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail(url: str, path: Path, *, timeout: int = 300) -> None:
            path.write_bytes(b"partial")
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(mc, "stream_download", fail)
        with pytest.raises(SourceUnavailableError, match="connection refused"):
            mc.cached_download("https://x/a.zip", tmp_path / "a.zip")
        assert list(tmp_path.iterdir()) == []

    def test_timeout_is_passed_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[int] = []

        def fake(url: str, path: Path, *, timeout: int = 300) -> None:
            seen.append(timeout)
            path.write_bytes(b"x")

        monkeypatch.setattr(mc, "stream_download", fake)
        mc.cached_download("https://x/a.txt", tmp_path / "a.txt", timeout=12)
        assert seen == [12]

    def test_cache_file_keeps_umask_permissions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The promoted cache file must not inherit a 0600 temp-file mode.
        serve(monkeypatch, b"x")
        previous = os.umask(0o022)
        try:
            target = mc.cached_download("https://x/a.geojson", tmp_path / "a.geojson")
        finally:
            os.umask(previous)
        assert stat.S_IMODE(target.stat().st_mode) == 0o644

    def test_concurrent_downloads_use_distinct_temp_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        temps: list[Path] = []

        def fake(url: str, path: Path, *, timeout: int = 300) -> None:
            temps.append(path)
            path.write_bytes(b"x")

        monkeypatch.setattr(mc, "stream_download", fake)
        target = tmp_path / "a.zip"
        mc.cached_download("https://x/a.zip", target)
        mc.cached_download("https://x/a.zip", target, force=True)
        assert len(set(temps)) == 2 and target not in temps


class _FakeResponse:
    def __init__(self, body: bytes, final_url: str | None = None) -> None:
        self._body = body
        self._sent = False
        self._final_url = final_url

    def geturl(self) -> str:
        assert self._final_url is not None, "geturl() read without allowed_final_url"
        return self._final_url

    def read(self, size: int = -1) -> bytes:
        if self._sent:
            return b""
        self._sent = True
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class TestStreamDownload:
    def test_uses_repo_user_agent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[tuple[str, str | None, object]] = []

        def fake_urlopen(request, timeout: int, context: object = None) -> _FakeResponse:
            seen.append((request.full_url, request.get_header("User-agent"), context))
            return _FakeResponse(b"body")

        monkeypatch.setattr(mc.urllib.request, "urlopen", fake_urlopen)
        REAL_STREAM_DOWNLOAD("https://x/a.bin", tmp_path / "a.bin", timeout=5)
        assert (tmp_path / "a.bin").read_bytes() == b"body"
        assert seen == [("https://x/a.bin", sio.USER_AGENT, None)]

    def test_certifi_fallback_only_on_certificate_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        contexts: list[object] = []
        sentinel = ssl.create_default_context()

        def fake_urlopen(request, timeout: int, context: object = None) -> _FakeResponse:
            contexts.append(context)
            if context is None:
                raise urllib.error.URLError(ssl.SSLCertVerificationError("bad chain"))
            return _FakeResponse(b"ok")

        monkeypatch.setattr(mc.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(mc, "_certifi_context", lambda: sentinel)
        REAL_STREAM_DOWNLOAD("https://x/a.bin", tmp_path / "a.bin")
        assert contexts == [None, sentinel]
        assert (tmp_path / "a.bin").read_bytes() == b"ok"

        # Without certifi the verification error surfaces unchanged.
        monkeypatch.setattr(mc, "_certifi_context", lambda: None)
        with pytest.raises(urllib.error.URLError):
            REAL_STREAM_DOWNLOAD("https://x/b.bin", tmp_path / "b.bin")

    def test_other_url_errors_do_not_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[object] = []

        def fake_urlopen(request, timeout: int, context: object = None) -> _FakeResponse:
            calls.append(context)
            raise urllib.error.URLError("no route to host")

        monkeypatch.setattr(mc.urllib.request, "urlopen", fake_urlopen)
        monkeypatch.setattr(mc, "_certifi_context", lambda: ssl.create_default_context())
        with pytest.raises(urllib.error.URLError):
            REAL_STREAM_DOWNLOAD("https://x/a.bin", tmp_path / "a.bin")
        assert calls == [None]


def _https_on(host: str):
    def allowed(url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        return parts.scheme == "https" and parts.hostname == host

    return allowed


def _redirecting_urlopen(monkeypatch: pytest.MonkeyPatch, final_url: str) -> None:
    def fake_urlopen(request, timeout: int, context: object = None) -> _FakeResponse:
        return _FakeResponse(b"body", final_url=final_url)

    monkeypatch.setattr(mc.urllib.request, "urlopen", fake_urlopen)


class TestAllowedFinalUrl:
    @pytest.mark.parametrize(
        "final_url",
        [
            "https://evil.example/a.zip",  # off-host
            "http://data.example/a.zip",  # downgraded to http
            "https://data.example.evil.example/a.zip",  # look-alike host
        ],
    )
    def test_stream_download_refuses_before_writing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, final_url: str
    ) -> None:
        _redirecting_urlopen(monkeypatch, final_url)
        target = tmp_path / "a.zip"
        with pytest.raises(FetchError, match="disallowed URL"):
            REAL_STREAM_DOWNLOAD(
                "https://data.example/a.zip",
                target,
                allowed_final_url=_https_on("data.example"),
            )
        assert not target.exists()

    def test_stream_download_accepts_an_allowed_final_url(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _redirecting_urlopen(monkeypatch, "https://data.example/moved/a.zip")
        REAL_STREAM_DOWNLOAD(
            "https://data.example/a.zip",
            tmp_path / "a.zip",
            allowed_final_url=_https_on("data.example"),
        )
        assert (tmp_path / "a.zip").read_bytes() == b"body"

    def test_without_a_check_the_final_url_is_not_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # final_url=None makes geturl() fail: no check means no geturl() call.
        def fake_urlopen(request, timeout: int, context: object = None) -> _FakeResponse:
            return _FakeResponse(b"body")

        monkeypatch.setattr(mc.urllib.request, "urlopen", fake_urlopen)
        REAL_STREAM_DOWNLOAD("https://data.example/a.zip", tmp_path / "a.zip")
        assert (tmp_path / "a.zip").read_bytes() == b"body"

    def test_cached_download_writes_nothing_on_a_bad_redirect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mc, "stream_download", REAL_STREAM_DOWNLOAD)
        _redirecting_urlopen(monkeypatch, "http://evil.example/a.zip")
        validated: list[Path] = []
        with pytest.raises(FetchError, match="disallowed URL http://evil.example/a.zip"):
            mc.cached_download(
                "https://data.example/a.zip",
                tmp_path / "a.zip",
                validate=validated.append,
                allowed_final_url=_https_on("data.example"),
            )
        assert validated == []
        assert list(tmp_path.iterdir()) == []

    def test_cached_download_keeps_an_existing_target_on_a_bad_redirect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(mc, "stream_download", REAL_STREAM_DOWNLOAD)
        _redirecting_urlopen(monkeypatch, "https://evil.example/a.zip")
        target = tmp_path / "a.zip"
        target.write_bytes(b"old")
        with pytest.raises(FetchError):
            mc.cached_download(
                "https://data.example/a.zip",
                target,
                force=True,
                allowed_final_url=_https_on("data.example"),
            )
        assert target.read_bytes() == b"old"
        assert leftovers(tmp_path) == []

    def test_cached_download_passes_the_check_to_the_seam(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[object] = []
        check = _https_on("data.example")

        def fake(url: str, path: Path, *, timeout: int = 300, **kwargs: object) -> None:
            seen.append(kwargs.get("allowed_final_url"))
            path.write_bytes(b"x")

        monkeypatch.setattr(mc, "stream_download", fake)
        mc.cached_download("https://data.example/a", tmp_path / "a", allowed_final_url=check)
        mc.cached_download("https://data.example/b", tmp_path / "b")
        # without a check the seam is called exactly as before (no extra keyword)
        assert seen == [check, None]


# ---------------------------------------------------------------------------
# State files: open-mexico postal polygons
# ---------------------------------------------------------------------------


class TestStatePostalPolygons:
    def test_cached_state_file_path_is_unchanged_for_morelia(
        self, raw_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = feature_collection([polygon_feature({"d_codigo": 58000}, square(-101.2, 19.7))])
        serve(monkeypatch, body)
        url = "https://raw.githubusercontent.com/open-mexico/mexico-geojson/main/16-Mich.geojson"
        assert mc.cached_state_file(url) == raw_dir / "mx_16-Mich.geojson"
        # fetch_mx_postal_codes keeps its private name as an alias of the shared helper.
        assert fetch_mx_postal_codes._cached_state_file is mc.cached_state_file

    def test_cached_state_file_rejects_error_pages(
        self, raw_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        serve(monkeypatch, b"<html><body>429 Too Many Requests</body></html>")
        with pytest.raises(FetchError):
            mc.cached_state_file("https://x/19-NL.geojson")
        assert list(raw_dir.iterdir()) == []

    def test_load_pads_codes_and_keeps_polygonal_parts(
        self, raw_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        line_like = [[-100.0, 25.0], [-99.99, 25.0], [-99.98, 25.0], [-100.0, 25.0]]
        body = feature_collection(
            [
                polygon_feature({"d_codigo": 1000}, square(-100.3, 25.6)),
                polygon_feature({"d_codigo": "64000"}, [[x - 100.5, y + 25.5] for x, y in BOWTIE]),
                polygon_feature({"d_codigo": 64100}, line_like),
            ]
        )
        serve(monkeypatch, body)
        frame = mc.load_state_postal_polygons("https://x/19-NL.geojson")
        assert frame.crs.to_string() == "EPSG:4326"
        # The zero-area ring has no polygonal part left after make_valid -> dropped.
        assert frame["d_codigo"].tolist() == ["01000", "64000"]
        assert frame.geometry.is_valid.all()
        assert set(frame.geom_type) <= {"Polygon", "MultiPolygon"}
        assert frame.geometry.iloc[1].geom_type == "MultiPolygon"  # repaired bowtie

    def test_load_requires_d_codigo(self, raw_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        serve(monkeypatch, feature_collection([polygon_feature({"cp": 1}, square(0, 0))]))
        with pytest.raises(FetchError, match="d_codigo"):
            mc.load_state_postal_polygons("https://x/19-NL.geojson")


# ---------------------------------------------------------------------------
# INEGI municipalities (wscatgeo mgem)
# ---------------------------------------------------------------------------


def mgem_body(state: str = "19", *, drop: str | None = None) -> bytes:
    rows = [
        ("19039", "039", "Monterrey", "1142994", square(-100.4, 25.6, 0.1)),
        ("19006", "006", "Apodaca", "656464", square(-100.2, 25.7, 0.1)),
    ]
    features = []
    for cvegeo, cve_mun, name, pop, ring in rows:
        props = {
            "cvegeo": cvegeo,
            "cve_ent": state,
            "cve_mun": cve_mun,
            "nomgeo": name,
            "cve_cab": "0001",
            "pob_total": pop,
        }
        if drop:
            props.pop(drop)
        # INEGI tags each geometry with its own (non-standard) crs member.
        crs = {"type": "name", "properties": {"name": "EPSG:6365"}}
        features.append(polygon_feature(props, ring, crs=crs))
    metadatos = {"Fuente_informacion_estadistica": "INEGI. Censo de Población y Vivienda, 2020"}
    return feature_collection(features, metadatos=metadatos, totalReg=len(features))


class TestStateMunicipalities:
    def test_column_mapping(self, raw_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = serve(monkeypatch, mgem_body())
        frame = mc.load_state_municipalities("19")
        assert calls == ["https://gaia.inegi.org.mx/wscatgeo/v2/geo/mgem/19"]
        assert (raw_dir / "mx_inegi_mgem_19.geojson").exists()
        assert list(frame.columns) == ["mun_code", "cve_mun", "municipio", "population", "geometry"]
        assert frame["mun_code"].tolist() == ["19006", "19039"]  # sorted by code
        assert frame["cve_mun"].tolist() == ["006", "039"]
        assert frame["municipio"].tolist() == ["Apodaca", "Monterrey"]
        assert frame["population"].tolist() == [656464, 1142994]
        assert pd.api.types.is_integer_dtype(frame["population"])
        assert frame.crs.to_string() == "EPSG:4326"
        assert frame.attrs["inegi_metadatos"]["Fuente_informacion_estadistica"].endswith("2020")

    def test_rejects_another_states_payload(
        self, raw_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        serve(monkeypatch, mgem_body(state="14"))
        with pytest.raises(FetchError, match="expected 19"):
            mc.load_state_municipalities("19")
        assert not (raw_dir / "mx_inegi_mgem_19.geojson").exists()

    def test_rejects_missing_population(
        self, raw_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        serve(monkeypatch, mgem_body(drop="pob_total"))
        with pytest.raises(FetchError, match="pob_total"):
            mc.load_state_municipalities("19")

    def test_state_code_must_be_two_digits(self, raw_dir: Path) -> None:
        with pytest.raises(ValueError, match="2 digits"):
            mc.load_state_municipalities("9")


# ---------------------------------------------------------------------------
# INEGI DCAH 2025 colonias
# ---------------------------------------------------------------------------


def build_dcah_zip(
    directory: Path,
    state: str = "19",
    *,
    skip: str | None = None,
    extra_member: str | None = None,
) -> Path:
    """A tiny DCAH-shaped state zip: UPPERCASE fields, EPSG:6372, one bowtie polygon."""
    frame = gpd.GeoDataFrame(
        {
            "CVEGEO": [f"{state}03900010001", f"{state}03900010002"],
            "CVE_ENT": [state, state],
            "CVE_MUN": ["039", "039"],
            "CVE_LOC": ["0001", "0001"],
            "CVE_ASEN": ["0001", "0002"],
            "CP": ["64000", "00000"],
            "FECHA_ACT": ["11/2025", "11/2024"],
            "INSTITUCIO": ["MUNICIPIO", "MUNICIPIO"],
            "NOM_ASEN": ["CENTRO", "NINGUNO"],
            "TIPO": ["COLONIA", "NINGUNO"],
        },
        geometry=[
            box(2_700_000, 1_500_000, 2_700_500, 1_500_500),
            Polygon([(2_701_000 + 500 * x, 1_500_000 + 500 * y) for x, y in BOWTIE]),
        ],
        crs="EPSG:6372",
    )
    shp_dir = directory / "shp"
    shp_dir.mkdir()
    frame.to_file(shp_dir / f"{state}as.shp", engine="pyogrio", encoding="UTF-8")
    archive_path = directory / f"{state}_dcah.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("catalogos/contenido.txt", "synthetic")
        for part in sorted(shp_dir.iterdir()):
            if skip and part.suffix == f".{skip}":
                continue
            archive.write(part, f"conjunto_de_datos/{part.name}")
        if extra_member:
            archive.writestr(extra_member, "x")
    return archive_path


class TestDcah:
    def test_loads_lowercase_columns_in_wgs84(
        self, raw_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = build_dcah_zip(tmp_path)
        serve(monkeypatch, archive)
        frame = mc.load_dcah("https://x/19_nuevoleon.zip", "19")
        assert (raw_dir / "mx_inegi_dcah2025_19.zip").exists()
        for column in mc.DCAH_REQUIRED_COLUMNS:
            assert column in frame.columns
        assert all(column == column.lower() for column in frame.columns)
        assert frame.crs.to_string() == "EPSG:4326"
        assert frame["cvegeo"].tolist() == ["1903900010001", "1903900010002"]
        assert frame["cp"].tolist() == ["64000", "00000"]
        assert frame.geometry.is_valid.all()
        assert frame.geometry.iloc[1].geom_type == "MultiPolygon"  # bowtie repaired
        # Roughly central Nuevo León once reprojected from EPSG:6372.
        minx, miny, maxx, maxy = frame.total_bounds
        assert -104 < minx < maxx < -96 and 20 < miny < maxy < 30

    @pytest.mark.parametrize("skip", ["shp", "dbf", "shx", "prj"])
    def test_rejects_zip_missing_a_shapefile_part(
        self, raw_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, skip: str
    ) -> None:
        serve(monkeypatch, build_dcah_zip(tmp_path, skip=skip))
        with pytest.raises(FetchError, match=rf"19as\.{skip}"):
            mc.load_dcah("https://x/19_nuevoleon.zip", "19")
        assert list(raw_dir.iterdir()) == []

    def test_rejects_wrong_state_zip(
        self, raw_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        serve(monkeypatch, build_dcah_zip(tmp_path, state="14"))
        with pytest.raises(FetchError, match="19as"):
            mc.load_dcah("https://x/14_jalisco.zip", "19")

    def test_rejects_non_zip_and_unsafe_members(
        self, raw_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        serve(monkeypatch, b"<html>maintenance</html>")
        with pytest.raises(FetchError, match="not a zip"):
            mc.load_dcah("https://x/19_nuevoleon.zip", "19")
        serve(monkeypatch, build_dcah_zip(tmp_path, extra_member="../evil.txt"))
        with pytest.raises(FetchError, match="unsafe member"):
            mc.load_dcah("https://x/19_nuevoleon.zip", "19")
        assert list(raw_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# assign_largest_overlap
# ---------------------------------------------------------------------------


class TestAssignLargestOverlap:
    METRIC = "EPSG:32614"

    def zones(self) -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame(
            {"cve_mun": ["039", "006"]},
            geometry=[box(0, 0, 1000, 1000), box(1000, 0, 2000, 1000)],
            crs=self.METRIC,
        )

    def test_picks_majority_zone_and_aligns_index(self) -> None:
        areas = gpd.GeoDataFrame(
            {"d_codigo": ["a", "b", "c", "d", "e"]},
            geometry=[
                box(100, 100, 400, 400),  # inside 039
                box(800, 100, 1900, 400),  # mostly 006
                box(5000, 5000, 5100, 5100),  # no zone
                box(2000, 0, 2100, 100),  # touches 006 only along an edge
                box(900, 100, 1100, 200),  # exact tie -> lower key "006"
            ],
            index=[10, 11, 12, 13, 14],
            crs=self.METRIC,
        )
        result = mc.assign_largest_overlap(areas, self.zones(), "cve_mun", metric_crs=self.METRIC)
        assert list(result.index) == [10, 11, 12, 13, 14]
        assert result.name == "cve_mun"
        assert result.loc[10] == "039"
        assert result.loc[11] == "006"
        assert pd.isna(result.loc[12])
        assert pd.isna(result.loc[13])
        assert result.loc[14] == "006"

    def test_reprojects_and_handles_invalid_geometry(self) -> None:
        zones_wgs84 = self.zones().to_crs("EPSG:4326")
        bowtie = Polygon([(100 + 600 * x, 100 + 600 * y) for x, y in BOWTIE])
        areas = gpd.GeoDataFrame({"id": [1]}, geometry=[bowtie], crs=self.METRIC).to_crs(
            "EPSG:4326"
        )
        result = mc.assign_largest_overlap(areas, zones_wgs84, "cve_mun", metric_crs=self.METRIC)
        assert result.tolist() == ["039"]

    def test_empty_inputs_and_errors(self) -> None:
        empty = gpd.GeoDataFrame({"id": []}, geometry=[], crs=self.METRIC)
        assert mc.assign_largest_overlap(
            empty, self.zones(), "cve_mun", metric_crs=self.METRIC
        ).empty
        areas = gpd.GeoDataFrame({"id": [1]}, geometry=[box(0, 0, 1, 1)], crs=self.METRIC)
        with pytest.raises(ValueError, match="no 'missing' column"):
            mc.assign_largest_overlap(areas, self.zones(), "missing", metric_crs=self.METRIC)
        no_crs = gpd.GeoDataFrame({"id": [1]}, geometry=[box(0, 0, 1, 1)])
        with pytest.raises(ValueError, match="CRS"):
            mc.assign_largest_overlap(no_crs, self.zones(), "cve_mun", metric_crs=self.METRIC)


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("COLONIA DEL VALLE", "Colonia del Valle"),
        ("LA FLORIDA", "La Florida"),  # article stays capitalized as the first word
        ("VALLE DE LOS ÁLAMOS", "Valle de los Álamos"),
        ("LOMAS DE LAS PALMAS Y LA ESPERANZA", "Lomas de las Palmas y la Esperanza"),
        ("RIVERA E HIJOS", "Rivera e Hijos"),
        ("SECTOR III", "Sector III"),
        ("ETAPA IV", "Etapa IV"),
        ("LOS ÁLAMOS XIV", "Los Álamos XIV"),
        ("MI TIENDA", "Mi Tienda"),  # MI / CIVIL are words, not numerals
        ("COLEGIO CIVIL", "Colegio Civil"),
        ("1ER SECTOR", "1er Sector"),
        ("FRANCISCO A. CÁRDENAS", "Francisco A. Cárdenas"),
        ("LAGUNILLAS (SAN JOSÉ LAGUNILLAS)", "Lagunillas (San José Lagunillas)"),
        ("SAN JOSÉ-NORTE", "San José-Norte"),
        ("ÑUÑOA  ESPAÑA", "Ñuñoa España"),
        ("colonia del valle", "Colonia del Valle"),
        ("Jardines del Valle", "Jardines del Valle"),  # mixed case: unchanged
        ("5 de Mayo", "5 de Mayo"),
        ("Del Valle", "Del Valle"),
        ("123", "123"),
        ("", ""),
    ],
)
def test_spanish_title_case(raw: str, expected: str) -> None:
    assert mc.spanish_title_case(raw) == expected


# Real all-caps INEGI DCAH 2025 nom_asen values from the Monterrey (19) and
# Guadalajara (14) member municipalities, with the intended casing.
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # a leading number is the first word: the article after it is lowercase
        ("20 DE SEPTIEMBRE", "20 de Septiembre"),
        ("10 DE MAYO", "10 de Mayo"),
        ("27 DE SEPTIEMBRE", "27 de Septiembre"),
        ("AMPLIACIÓN 27 DE MAYO", "Ampliación 27 de Mayo"),
        ("PRIVADA 5 DE MAYO", "Privada 5 de Mayo"),
        # "e" is the conjunction only before an i/hi word; otherwise a sector letter
        ("RESIDENCIAL APODACA SEGUNDO SECTOR E -2", "Residencial Apodaca Segundo Sector E -2"),
        (
            "PARQUE DE INVESTIGACIÓN E INOVACIÓN TECNOLÓGICA (PITT)",
            "Parque de Investigación e Inovación Tecnológica (PITT)",
        ),
        ("HACIENDA SANTA ISABEL PRIMER SECTOR E-1", "Hacienda Santa Isabel Primer Sector E-1"),
        # digit + letter codes stay uppercase
        ("ALTAVISTA 1B-3", "Altavista 1B-3"),
        ("MIRASIERRA 1B-1", "Mirasierra 1B-1"),
        ("URBI ETAPA 7A", "Urbi Etapa 7A"),
        ("ALTAVISTA 1-A (MIRASIERRA 1-A)", "Altavista 1-A (Mirasierra 1-A)"),
        ("LA CANTERA HÁBITAT INTEGRAL F5-A", "La Cantera Hábitat Integral F5-A"),
        ("SANTA ROSA D02 NO.1", "Santa Rosa D02 No.1"),
        # institution acronyms stay uppercase
        ("CAMPESTRE CTM", "Campestre CTM"),
        ("CONJUNTO HABITACIONAL UAG", "Conjunto Habitacional UAG"),
        ("IMSS", "IMSS"),
        ("CFE SUBESTACIÓN TESISTÁN", "CFE Subestación Tesistán"),
        ("FUNDADORES DE LA CROC INFONAVIT", "Fundadores de la CROC INFONAVIT"),
        ("BELISARIO DOMÍNGUEZ (FOMERREY 71)", "Belisario Domínguez (FOMERREY 71)"),
        ("CENTRO INDUSTRIAL Y DESARROLLO (CID)", "Centro Industrial y Desarrollo (CID)"),
        ("DIF (FOMERREY 15)", "DIF (FOMERREY 15)"),
        ("UNIDAD FOVISSSTE ESTATUTO JURÍDICO", "Unidad FOVISSSTE Estatuto Jurídico"),
        ("TAD PEMEX REFINACIÓN", "Tad PEMEX Refinación"),
        # unchanged behaviour on real names
        ("LAS VILLAS G Y G", "Las Villas G y G"),
        ("JOAQUÍN GARZA Y GARZA", "Joaquín Garza y Garza"),
        ("BOSQUES DE BUGAMBILIAS SECCIÓN II M", "Bosques de Bugambilias Sección II M"),
        ("LA PAZ (CAMINO A LA PAZ)", "La Paz (Camino A la Paz)"),
        (
            "GIRASOLES ACUEDUCTO SECCIÓN 2-TERCERA ETAPA",
            "Girasoles Acueducto Sección 2-Tercera Etapa",
        ),
        ("MÁRTIRES DEL 36", "Mártires del 36"),
        # already mixed case (DCAH has both styles): returned as is
        ("FOVISSSTE la Talaverna", "FOVISSSTE la Talaverna"),
        ("Bosques de las Cumbres Sector B-1", "Bosques de las Cumbres Sector B-1"),
    ],
)
def test_spanish_title_case_real_dcah_names(raw: str, expected: str) -> None:
    assert mc.spanish_title_case(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # ordinal endings after a digit are lowercase
        ("1ER SECTOR", "1er Sector"),
        ("2DA SECCIÓN", "2da Sección"),
        ("3RA ETAPA", "3ra Etapa"),
        ("4TO SECTOR", "4to Sector"),
        ("1A. SECCIÓN", "1a. Sección"),
        ("1O. DE MAYO", "1o. de Mayo"),
        # one letter then space/hyphen/end is a code, not an ordinal
        ("SECTOR 1A", "Sector 1A"),
        ("SECTOR 1O", "Sector 1O"),
        ("1A SECCIÓN", "1A Sección"),
        ("7B-2", "7B-2"),
        ("1B.", "1B."),
        # longer runs glued to a number read as words (DENUE gym names)
        ("FIT4LIFE", "Fit4Life"),
        ("24FREEDOM", "24Freedom"),
        ("GYM 5AM", "Gym 5AM"),
        ("CROS FIT H2O", "Cros Fit H2O"),
        # e as a conjunction (i/hi next) vs a letter
        ("RIVERA E HIJOS", "Rivera e Hijos"),
        ("ARTE E ÍDOLOS", "Arte e Ídolos"),
        ("SEGUNDO SECTOR E", "Segundo Sector E"),
        ("SECTOR E -2", "Sector E -2"),
        ("E INDUSTRIAL", "E Industrial"),  # first word
        ("SECTOR E (NORTE)", "Sector E (Norte)"),
        # first word by token, not by letter run
        ("DE LA SIERRA", "De la Sierra"),
        ("5 DE MAYO", "5 de Mayo"),
        ("110 CLUB DE ENTRENAMIENTO", "110 Club de Entrenamiento"),
    ],
)
def test_spanish_title_case_digits_and_letters(raw: str, expected: str) -> None:
    assert mc.spanish_title_case(raw) == expected


@pytest.mark.parametrize(
    ("name", "unnamed"),
    [
        ("", True),
        ("   ", True),
        ("NINGUNO", True),
        ("Ninguno", True),
        (" ninguno ", True),
        ("SIN NOMBRE", True),
        ("Sin  Nombre", True),
        ("S/N", True),
        ("s/n", True),
        ("N/A", True),
        (None, True),
        (float("nan"), True),
        ("NINGUNO (LAS VARAS CENIZAS)", False),
        ("CENTRO", False),
        ("Sin Nombre de Calle Norte", False),
    ],
)
def test_is_unnamed_colonia(name: object, unnamed: bool) -> None:
    assert mc.is_unnamed_colonia(name) is unnamed  # type: ignore[arg-type]


def test_is_unnamed_colonia_ignores_accents() -> None:
    assert mc.is_unnamed_colonia("NINGÚNO")
    assert mc.is_unnamed_colonia("SÍN NÓMBRE")


# ---------------------------------------------------------------------------
# profile_mx_area
# ---------------------------------------------------------------------------


def test_profile_mx_area_reads_state_and_members() -> None:
    profile = {"mx_area": {"state_code": "19", "municipalities": ["039", "006"]}}
    assert mc.profile_mx_area(profile, "x") == ("19", ["039", "006"])


@pytest.mark.parametrize(
    ("city", "state", "count"), [("monterrey", "19", 12), ("guadalajara", "14", 7)]
)
def test_profile_mx_area_matches_committed_profiles(city: str, state: str, count: int) -> None:
    profile = json.loads((REPO_CITIES / city / "city.json").read_text(encoding="utf-8"))
    code, members = mc.profile_mx_area(profile, city)
    assert code == state
    assert len(members) == count == len(set(members))


@pytest.mark.parametrize(
    ("block", "match"),
    [
        (None, "must declare mx_area"),
        ({"municipalities": ["039"]}, "state_code"),
        ({"state_code": 19, "municipalities": ["039"]}, "state_code"),
        ({"state_code": "19", "municipalities": []}, "non-empty"),
        ({"state_code": "19", "municipalities": ["39"]}, "3-digit"),
        ({"state_code": "19", "municipalities": [39]}, "3-digit"),
        ({"state_code": "19", "municipalities": ["039", "039"]}, "repeats 039"),
    ],
)
def test_profile_mx_area_errors(block: dict | None, match: str) -> None:
    profile = {} if block is None else {"mx_area": block}
    with pytest.raises(ConfigError, match=match):
        mc.profile_mx_area(profile, "testcity")


# ---------------------------------------------------------------------------
# Overpass: endpoint rotation + backoff (io.retry_overpass)
# ---------------------------------------------------------------------------

DE, KUMI, COFFEE = sio.OVERPASS_ENDPOINTS


def http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(DE, code, "error", headers, None)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(sio, "_sleep", recorded.append)
    return recorded


def scripted_overpass(
    monkeypatch: pytest.MonkeyPatch, outcomes: list[object]
) -> list[tuple[str, int]]:
    """Replace ``post_overpass``: each call pops an outcome (exception -> raised)."""
    calls: list[tuple[str, int]] = []
    queue = list(outcomes)

    def fake(query: str, *, timeout: int = 90, endpoint: str = DE) -> dict:
        calls.append((endpoint, timeout))
        outcome = queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        assert isinstance(outcome, dict)
        return outcome

    monkeypatch.setattr(sio, "post_overpass", fake)
    return calls


class TestRetryOverpass:
    def test_endpoint_order_and_user_agent_are_stable(self) -> None:
        assert sio.OVERPASS_ENDPOINTS == (
            "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter",
        )
        assert sio.USER_AGENT == "cdmx-postal-code-convenience-map/0.1"

    def test_first_success_needs_no_sleep(
        self, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
    ) -> None:
        calls = scripted_overpass(monkeypatch, [{"elements": [1]}])
        assert sio.retry_overpass("q") == {"elements": [1]}
        assert calls == [(DE, 90)] and sleeps == []

    def test_default_retries_only_overpass_api_de(
        self, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
    ) -> None:
        # Legacy callers (fetch_gyms, fetch_osm_transit, the legacy supermarket path)
        # pass no endpoints: every attempt stays on overpass-api.de, never a mirror.
        calls = scripted_overpass(
            monkeypatch,
            [http_error(504), TimeoutError("slow"), {"elements": []}],
        )
        assert sio.retry_overpass("q", attempts=3, timeout=120) == {"elements": []}
        assert calls == [(DE, 120)] * 3
        assert sleeps == [30.0, 60.0]

    def test_rotates_mirrors_with_growing_backoff(
        self, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
    ) -> None:
        calls = scripted_overpass(
            monkeypatch,
            [urllib.error.URLError("refused"), http_error(504), {"elements": []}],
        )
        payload = sio.retry_overpass("q", attempts=3, timeout=120, endpoints=sio.OVERPASS_ENDPOINTS)
        assert payload == {"elements": []}
        assert calls == [(DE, 120), (KUMI, 120), (COFFEE, 120)]
        assert sleeps == [30.0, 60.0]
        assert all(wait >= 30 for wait in sleeps)

    def test_wraps_around_after_the_last_mirror(
        self, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
    ) -> None:
        failures: list[object] = [TimeoutError("slow")] * 3
        calls = scripted_overpass(monkeypatch, [*failures, {"elements": []}])
        sio.retry_overpass("q", attempts=4, endpoints=sio.OVERPASS_ENDPOINTS)
        assert [endpoint for endpoint, _ in calls] == [DE, KUMI, COFFEE, DE]
        assert sleeps == [30.0, 60.0, 90.0]

    def test_stale_mirror_is_skipped_when_a_maximum_age_is_set(
        self, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
    ) -> None:
        now = datetime(2026, 11, 25, 12, tzinfo=UTC)
        stale = {"osm3s": {"timestamp_osm_base": "2026-06-01T08:52:28Z"}, "elements": [0]}
        fresh = {"osm3s": {"timestamp_osm_base": "2026-11-25T11:00:00Z"}, "elements": [1]}
        calls = scripted_overpass(monkeypatch, [stale, fresh])
        payload = sio.retry_overpass(
            "q",
            attempts=3,
            endpoints=sio.OVERPASS_ENDPOINTS,
            max_osm_age_days=30,
            now=lambda: now,
        )
        assert payload is fresh
        assert [endpoint for endpoint, _ in calls] == [DE, KUMI]
        assert sleeps == [30.0]

    def test_only_stale_or_undated_replies_exhaust_into_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
    ) -> None:
        now = datetime(2026, 11, 25, 12, tzinfo=UTC)
        stale = {"osm3s": {"timestamp_osm_base": "2026-06-01T08:52:28Z"}, "elements": []}
        scripted_overpass(monkeypatch, [stale, {"elements": []}])
        with pytest.raises(RuntimeError, match="after 2 attempts") as info:
            sio.retry_overpass(
                "q",
                attempts=2,
                endpoints=sio.OVERPASS_ENDPOINTS,
                max_osm_age_days=30,
                now=lambda: now,
            )
        assert "stale mirror" in str(info.value.__cause__)
        assert "unknown" in str(info.value.__cause__)  # the undated reply

    def test_without_a_maximum_age_any_mirror_is_accepted(
        self, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
    ) -> None:
        stale = {"osm3s": {"timestamp_osm_base": "2020-01-01T00:00:00Z"}, "elements": []}
        scripted_overpass(monkeypatch, [stale])
        assert sio.retry_overpass("q") is stale
        assert sleeps == []

    def test_retryable_errors_exhaust_into_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
    ) -> None:
        last = json.JSONDecodeError("bad", "<html>", 0)
        scripted_overpass(monkeypatch, [http_error(429), ConnectionResetError("reset"), last])
        with pytest.raises(RuntimeError, match="after 3 attempts") as info:
            sio.retry_overpass("q", attempts=3)
        assert info.value.__cause__ is last
        assert len(sleeps) == 2  # no sleep after the final attempt

    def test_retry_after_header_extends_the_wait(
        self, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
    ) -> None:
        scripted_overpass(monkeypatch, [http_error(429, retry_after="120"), {"elements": []}])
        sio.retry_overpass("q")
        assert sleeps == [120.0]

    def test_retry_after_is_capped(
        self, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
    ) -> None:
        scripted_overpass(monkeypatch, [http_error(503, retry_after="86400"), {"elements": []}])
        sio.retry_overpass("q")
        assert sleeps == [sio.OVERPASS_MAX_WAIT_S]

    def test_client_errors_fail_fast(
        self, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
    ) -> None:
        calls = scripted_overpass(monkeypatch, [http_error(400), {"elements": []}])
        with pytest.raises(RuntimeError, match="HTTP 400"):
            sio.retry_overpass("q", attempts=3)
        assert len(calls) == 1 and sleeps == []

    def test_runtime_error_remark_is_retried(
        self, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
    ) -> None:
        partial = {"elements": [], "remark": "runtime error: Query timed out in 'query'"}
        calls = scripted_overpass(monkeypatch, [partial, {"elements": [1], "remark": "ok"}])
        payload = sio.retry_overpass("q", endpoints=sio.OVERPASS_ENDPOINTS)
        assert payload == {"elements": [1], "remark": "ok"}
        assert [endpoint for endpoint, _ in calls] == [DE, KUMI]
        assert sleeps == [30.0]

    def test_backoff_never_drops_below_thirty_seconds(
        self, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
    ) -> None:
        scripted_overpass(monkeypatch, [TimeoutError("slow"), {"elements": []}])
        sio.retry_overpass("q", backoff_s=1)
        assert sleeps == [30.0]

    def test_custom_endpoints_and_argument_checks(
        self, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
    ) -> None:
        calls = scripted_overpass(monkeypatch, [TimeoutError("x"), {"elements": []}])
        sio.retry_overpass("q", endpoints=["https://mirror/api"])
        assert [endpoint for endpoint, _ in calls] == ["https://mirror/api"] * 2
        with pytest.raises(ValueError, match="attempts"):
            sio.retry_overpass("q", attempts=0)
        with pytest.raises(ValueError, match="endpoint"):
            sio.retry_overpass("q", endpoints=[])


def test_post_overpass_targets_the_given_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str | None, int]] = []

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"elements": []}'

    def fake_urlopen(request, timeout: int) -> Response:
        seen.append((request.full_url, request.get_header("User-agent"), timeout))
        return Response()

    monkeypatch.setattr(sio.urllib.request, "urlopen", fake_urlopen)
    assert sio.post_overpass("q", timeout=7) == {"elements": []}
    assert sio.post_overpass("q", endpoint=KUMI) == {"elements": []}
    assert seen == [(DE, sio.USER_AGENT, 7), (KUMI, sio.USER_AGENT, 90)]
