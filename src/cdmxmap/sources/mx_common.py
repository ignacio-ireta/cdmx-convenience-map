"""Shared helpers for the Mexican profile-city fetchers (Monterrey, Guadalajara, ...).

Everything here is source plumbing used by several fetchers:

- ``cached_download``: atomic, validated download into the gitignored raw cache.
- State-wide inputs, each cached once under ``DATA_RAW`` and trimmed per city:
  open-mexico SEPOMEX postal polygons (``load_state_postal_polygons``), INEGI
  municipalities with Censo 2020 population (``load_state_municipalities``) and
  INEGI DCAH 2025 colonia polygons (``load_dcah``).
- Small pure helpers: ``assign_largest_overlap``, ``spanish_title_case``,
  ``is_unnamed_colonia`` and ``profile_mx_area``.

Downloaded bodies are untrusted: each one is validated on a temp file next to its
target and only promoted with ``os.replace`` once it passes, so an error page or a
truncated body never poisons a later run.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import ssl
import unicodedata
import urllib.error
import urllib.request
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from cdmxmap.errors import ConfigError, FetchError, SourceUnavailableError

from .io import DATA_RAW, USER_AGENT

MGEM_URL_TEMPLATE = "https://gaia.inegi.org.mx/wscatgeo/v2/geo/mgem/{state}"
WGS84 = "EPSG:4326"

# Columns the INEGI wscatgeo ``mgem`` service returns per municipality.
MGEM_REQUIRED_PROPERTIES = ("cvegeo", "cve_ent", "cve_mun", "nomgeo", "pob_total")
# Columns of the INEGI DCAH 2025 colonia shapefile (lowercase in the 2025 edition).
DCAH_REQUIRED_COLUMNS = (
    "cvegeo",
    "cve_ent",
    "cve_mun",
    "cve_loc",
    "cve_asen",
    "cp",
    "fecha_act",
    "nom_asen",
    "tipo",
)
DCAH_SHAPEFILE_PARTS = ("shp", "shx", "dbf", "prj")

_DOWNLOAD_CHUNK = 1 << 20
_NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    urllib.error.URLError,
    TimeoutError,
    ConnectionError,
    http.client.HTTPException,
)


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------


def _is_cert_verification_error(exc: urllib.error.URLError) -> bool:
    return isinstance(exc.reason, ssl.SSLCertVerificationError)


def _certifi_context() -> ssl.SSLContext | None:
    """A CA context from certifi when it is already importable (it is not a direct dependency)."""
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def stream_download(
    url: str,
    path: Path,
    *,
    timeout: int = 300,
    allowed_final_url: Callable[[str], bool] | None = None,
) -> None:
    """Stream ``url`` into ``path`` with the repo User-Agent.

    Uses the default TLS context. Only when certificate verification fails and
    ``certifi`` happens to be importable does it retry once with certifi's CA
    bundle (some Mexican government hosts serve chains the system store lacks).
    This is the single network seam: tests monkeypatch it.

    urllib follows redirects to any host and to plain http. With
    ``allowed_final_url`` set, the response's final URL (``geturl()``, after every
    redirect) must satisfy it; otherwise ``FetchError`` is raised before ``path`` is
    even created.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.URLError as exc:
        context = _certifi_context() if _is_cert_verification_error(exc) else None
        if context is None:
            raise
        print(f"Default TLS verification failed for {url}; retrying with the certifi CA bundle")
        response = urllib.request.urlopen(request, timeout=timeout, context=context)
    with response:
        if allowed_final_url is not None:
            final_url = str(response.geturl())
            if not allowed_final_url(final_url):
                raise FetchError(f"Download of {url} ended at a disallowed URL {final_url}")
        with path.open("wb") as handle:
            shutil.copyfileobj(response, handle, _DOWNLOAD_CHUNK)


def cached_download(
    url: str,
    target: Path,
    *,
    validate: Callable[[Path], None] | None = None,
    timeout: int = 300,
    force: bool = False,
    allowed_final_url: Callable[[str], bool] | None = None,
) -> Path:
    """Download ``url`` to ``target`` once, atomically, validating before promotion.

    An existing non-empty ``target`` is reused unless ``force``. Otherwise the body
    is streamed to a unique temp file in the target's directory (keeping the
    target's suffix, so GDAL drivers and ``/vsizip/`` still recognize it),
    ``validate(tmp)`` runs on it, and only then is it moved into place with
    ``os.replace``. Any failure removes the temp file and leaves an existing
    target untouched. ``allowed_final_url`` is handed to ``stream_download``: a
    redirect that ends on a URL it rejects writes nothing.

    Raises
    ------
    SourceUnavailableError
        The download failed (HTTP error, timeout, connection reset).
    FetchError
        The body downloaded but ``validate`` rejected it, or it was empty, or the
        final URL after redirects failed ``allowed_final_url``.
    """
    if not force and target.exists() and target.stat().st_size > 0:
        print(f"Using cached {target}")
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    # Unique per call (parallel fetchers may race on one cache file) and created by
    # ``stream_download`` with the normal umask, unlike ``mkstemp``'s 0600.
    tmp_path = target.with_name(f"{target.stem}.{uuid.uuid4().hex[:12]}.part{target.suffix}")
    try:
        print(f"Downloading {url}")
        try:
            if allowed_final_url is None:
                stream_download(url, tmp_path, timeout=timeout)
            else:
                stream_download(url, tmp_path, timeout=timeout, allowed_final_url=allowed_final_url)
        except _NETWORK_ERRORS as exc:
            raise SourceUnavailableError(f"Could not download {url}: {exc}") from exc
        if tmp_path.stat().st_size == 0:
            raise FetchError(f"Download of {url} returned an empty body")
        if validate is not None:
            try:
                validate(tmp_path)
            except Exception as exc:  # any parser error means the body is unusable
                raise FetchError(f"Download of {url} failed validation: {exc}") from exc
        os.replace(tmp_path, target)
    finally:
        tmp_path.unlink(missing_ok=True)
    print(f"Wrote {target} ({target.stat().st_size:,} bytes)")
    return target


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _polygonal_part(geom: BaseGeometry | None) -> BaseGeometry | None:
    """The polygonal content of ``geom`` (``make_valid`` can emit collections)."""
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, Polygon | MultiPolygon):
        return geom
    polygons = [
        part
        for part in shapely.get_parts(shapely.get_parts(geom))
        if isinstance(part, Polygon) and not part.is_empty
    ]
    if not polygons:
        return None
    merged = shapely.union_all(polygons)
    return merged if isinstance(merged, Polygon | MultiPolygon) else None


def make_valid_polygonal(frame: gpd.GeoDataFrame, *, label: str = "features") -> gpd.GeoDataFrame:
    """``make_valid`` every geometry, keep only polygonal parts, drop rows left empty."""
    fixed = [_polygonal_part(geom) for geom in frame.geometry.make_valid()]
    keep = np.array([geom is not None for geom in fixed], dtype=bool)
    result = frame.copy()
    result["geometry"] = gpd.GeoSeries(fixed, index=frame.index, crs=frame.crs)
    dropped = int((~keep).sum())
    if dropped:
        print(f"Dropped {dropped} {label} with no polygonal geometry after make_valid")
    return result[keep].copy()


def assign_largest_overlap(
    areas: gpd.GeoDataFrame,
    zones: gpd.GeoDataFrame,
    zone_key: str,
    *,
    metric_crs: str,
) -> pd.Series:
    """For each area, the ``zone_key`` of the zone it overlaps most (by area).

    Overlap is measured in ``metric_crs``. Areas that touch no zone with positive
    area get ``NaN``. Ties break on the zone key (ascending string order), so the
    result is deterministic. The returned Series is index-aligned with ``areas``.
    """
    if areas.crs is None or zones.crs is None:
        raise ValueError("assign_largest_overlap needs both frames to carry a CRS")
    if zone_key not in zones.columns:
        raise ValueError(f"Zone frame has no {zone_key!r} column")
    result = pd.Series(np.nan, index=areas.index, dtype="object", name=zone_key)
    if areas.empty or zones.empty:
        return result

    left_geoms = np.array(
        [_polygonal_part(g) for g in areas.geometry.to_crs(metric_crs).make_valid()],
        dtype=object,
    )
    right_geoms = np.array(
        [_polygonal_part(g) for g in zones.geometry.to_crs(metric_crs).make_valid()],
        dtype=object,
    )
    left = gpd.GeoDataFrame(
        {"_pos": np.arange(len(areas))}, geometry=list(left_geoms), crs=metric_crs
    )
    right = gpd.GeoDataFrame(
        {"_zone": zones[zone_key].to_numpy()}, geometry=list(right_geoms), crs=metric_crs
    )
    left = left[left.geometry.notna()]
    right = right[right.geometry.notna()]
    pairs = gpd.sjoin(left, right, how="inner", predicate="intersects")
    if pairs.empty:
        return result

    area_pos = pairs["_pos"].to_numpy(dtype=int)
    zone_pos = pairs["index_right"].to_numpy(dtype=int)
    overlap = shapely.area(shapely.intersection(left_geoms[area_pos], right_geoms[zone_pos]))
    candidates = pd.DataFrame(
        {
            "pos": area_pos,
            "zone": pairs["_zone"].to_numpy(),
            "zone_sort": pairs["_zone"].astype(str).to_numpy(),
            "overlap": overlap,
        }
    )
    candidates = candidates[candidates["overlap"] > 0]
    best = candidates.sort_values(
        ["pos", "overlap", "zone_sort"], ascending=[True, False, True], kind="mergesort"
    ).drop_duplicates("pos")
    values = result.to_numpy(copy=True)
    values[best["pos"].to_numpy(dtype=int)] = best["zone"].to_numpy()
    return pd.Series(values, index=areas.index, dtype="object", name=zone_key)


# ---------------------------------------------------------------------------
# Validators (run on the temp file before it is promoted into the cache)
# ---------------------------------------------------------------------------


def _validate_feature_file(path: Path) -> None:
    frame = gpd.read_file(path)  # fails loudly on an error page / HTML / truncated body
    if frame.empty:
        raise ValueError(f"{path.name} parsed but contains no features")


def _validate_mgem(state_code: str) -> Callable[[Path], None]:
    def validate(path: Path) -> None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            raise ValueError("INEGI mgem response is not a GeoJSON FeatureCollection")
        features = payload.get("features")
        if not isinstance(features, list) or not features:
            raise ValueError("INEGI mgem response has no features")
        for feature in features:
            props = feature.get("properties") or {}
            missing = [key for key in MGEM_REQUIRED_PROPERTIES if key not in props]
            if missing:
                raise ValueError(f"INEGI mgem feature is missing {missing}")
            if str(props["cve_ent"]) != state_code:
                raise ValueError(
                    f"INEGI mgem feature {props['cvegeo']} belongs to state "
                    f"{props['cve_ent']}, expected {state_code}"
                )
            if not re.fullmatch(r"\d{5}", str(props["cvegeo"])):
                raise ValueError(f"INEGI mgem cvegeo {props['cvegeo']!r} is not 5 digits")
            if not re.fullmatch(r"\d+", str(props["pob_total"]).strip()):
                raise ValueError(f"INEGI mgem pob_total {props['pob_total']!r} is not an integer")
            if not feature.get("geometry"):
                raise ValueError(f"INEGI mgem feature {props['cvegeo']} has no geometry")
        _validate_feature_file(path)

    return validate


def _dcah_member(state_code: str, ext: str) -> str:
    return f"conjunto_de_datos/{state_code}as.{ext}"


def _validate_dcah_zip(state_code: str) -> Callable[[Path], None]:
    def validate(path: Path) -> None:
        if not zipfile.is_zipfile(path):
            raise ValueError("DCAH download is not a zip archive")
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            for name in names:
                member = PurePosixPath(name)
                if member.is_absolute() or ".." in member.parts or "\\" in name:
                    raise ValueError(f"DCAH zip has an unsafe member path {name!r}")
            missing = [
                _dcah_member(state_code, ext)
                for ext in DCAH_SHAPEFILE_PARTS
                if _dcah_member(state_code, ext) not in names
            ]
            if missing:
                raise ValueError(f"DCAH zip is missing {missing}")
            corrupt = archive.testzip()
            if corrupt is not None:
                raise ValueError(f"DCAH zip member {corrupt!r} fails its CRC check")
        info = pyogrio.read_info(f"zip://{path}!{_dcah_member(state_code, 'shp')}")
        fields = {str(field).lower() for field in info["fields"]}
        missing_fields = [column for column in DCAH_REQUIRED_COLUMNS if column not in fields]
        if missing_fields:
            raise ValueError(f"DCAH shapefile is missing fields {missing_fields}")
        if int(info["features"]) <= 0:
            raise ValueError("DCAH shapefile has no features")

    return validate


def _check_state_code(state_code: str) -> str:
    code = str(state_code).strip()
    if not re.fullmatch(r"\d{2}", code):
        raise ValueError(f"INEGI state code must be 2 digits, got {state_code!r}")
    return code


# ---------------------------------------------------------------------------
# State-wide loaders
# ---------------------------------------------------------------------------


def cached_state_file(url: str) -> Path:
    """Cache a state-wide GeoJSON once under the shared (gitignored) raw dir.

    The cache path is ``DATA_RAW / f"mx_{basename}"`` (e.g. ``mx_16-Mich.geojson``),
    shared by every municipality of that state; the body must parse as a
    non-empty feature collection before it is promoted.
    """
    target = DATA_RAW / f"mx_{os.path.basename(url)}"
    return cached_download(url, target, validate=_validate_feature_file, timeout=300)


def _postal_code_text(value: object) -> str:
    text = str(value if value is not None else "").strip()
    if re.fullmatch(r"\d+(\.0+)?", text):
        text = text.split(".", 1)[0]
    if not re.fullmatch(r"\d{1,5}", text):
        raise FetchError(f"Postal polygon has an invalid d_codigo {value!r}")
    return text.zfill(5)


def load_state_postal_polygons(url: str) -> gpd.GeoDataFrame:
    """open-mexico SEPOMEX state polygons in EPSG:4326 with a 5-digit ``d_codigo``.

    Geometries are repaired with ``make_valid`` keeping polygonal parts only
    (the raw files contain self-intersections that become collections).
    """
    frame = gpd.read_file(cached_state_file(url))
    if "d_codigo" not in frame.columns:
        raise FetchError(f"Postal polygons from {url} have no d_codigo column")
    frame = frame.set_crs(WGS84) if frame.crs is None else frame.to_crs(WGS84)
    frame["d_codigo"] = [_postal_code_text(value) for value in frame["d_codigo"]]
    return make_valid_polygonal(frame, label="postal polygons").reset_index(drop=True)


def load_state_municipalities(state_code: str) -> gpd.GeoDataFrame:
    """INEGI municipalities of one state with Censo 2020 population.

    Source: the INEGI wscatgeo ``mgem`` service (Marco Geoestadístico vector,
    Censo de Población y Vivienda 2020 counts). Cached at
    ``DATA_RAW / f"mx_inegi_mgem_{state}.geojson"``.

    The service tags each geometry with EPSG:6365 (Mexico ITRF2008, geographic);
    it differs from WGS84 by well under a metre, so coordinates are read as
    EPSG:4326 (the GeoJSON default) without a transform.

    Returns columns ``mun_code`` ("19039"), ``cve_mun`` ("039"), ``municipio``,
    ``population`` (int) and ``geometry``, sorted by ``mun_code``. The service's
    ``metadatos`` block is kept in ``frame.attrs["inegi_metadatos"]``.
    """
    state = _check_state_code(state_code)
    target = DATA_RAW / f"mx_inegi_mgem_{state}.geojson"
    path = cached_download(
        MGEM_URL_TEMPLATE.format(state=state), target, validate=_validate_mgem(state)
    )
    raw = gpd.read_file(path)
    raw = raw.set_crs(WGS84) if raw.crs is None else raw.to_crs(WGS84)
    frame = gpd.GeoDataFrame(
        {
            "mun_code": raw["cvegeo"].astype(str).str.strip(),
            "cve_mun": raw["cve_mun"].astype(str).str.strip().str.zfill(3),
            "municipio": raw["nomgeo"].astype(str).str.strip(),
            "population": raw["pob_total"].astype(str).str.strip().astype(int),
        },
        geometry=raw.geometry.values,
        crs=WGS84,
    )
    if frame["mun_code"].duplicated().any():
        raise FetchError(f"INEGI mgem for state {state} repeats a municipality code")
    frame = make_valid_polygonal(frame, label="municipalities")
    frame = frame.sort_values("mun_code", kind="mergesort").reset_index(drop=True)
    metadatos = json.loads(path.read_text(encoding="utf-8")).get("metadatos")
    frame.attrs["inegi_metadatos"] = metadatos if isinstance(metadatos, dict) else {}
    return frame


def load_dcah(url: str, state_code: str) -> gpd.GeoDataFrame:
    """INEGI DCAH 2025 colonia polygons for one state, in EPSG:4326.

    The state zip is cached at ``DATA_RAW / f"mx_inegi_dcah2025_{state}.zip"``
    after checking it holds ``conjunto_de_datos/{state}as.shp`` (+ .shx/.dbf/.prj)
    with the expected fields. Column names are lowercased (cvegeo, cve_ent,
    cve_mun, cve_loc, cve_asen, cp, fecha_act, nom_asen, tipo, ...); geometries are
    repaired in the source CRS (EPSG:6372) keeping polygonal parts only.
    """
    state = _check_state_code(state_code)
    target = DATA_RAW / f"mx_inegi_dcah2025_{state}.zip"
    path = cached_download(url, target, validate=_validate_dcah_zip(state))
    frame = gpd.read_file(f"zip://{path}!{_dcah_member(state, 'shp')}")
    frame.columns = [str(column).lower() for column in frame.columns]
    frame = frame.set_geometry("geometry")
    missing = [column for column in DCAH_REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise FetchError(f"DCAH shapefile for state {state} is missing columns {missing}")
    if frame.crs is None:
        raise FetchError(f"DCAH shapefile for state {state} has no CRS (.prj)")
    frame = make_valid_polygonal(frame, label="DCAH colonias")
    return frame.to_crs(WGS84).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

_SPANISH_LOWERCASE_WORDS = frozenset({"de", "del", "la", "las", "los", "y"})
# I..XXXIX: enough for "Sector III" / "Etapa XIV" without catching words like "MI".
_ROMAN_NUMERAL = re.compile(r"(?=[IVX])X{0,3}(?:IX|IV|V?I{0,3})")
_LETTER_RUN = re.compile(r"[^\W\d_]+")
# Spanish ordinal endings after a digit ("1ER", "2DA", "4TO", "1A."): lowercased.
_ORDINAL_SUFFIXES = frozenset(
    {"er", "ero", "era", "ro", "ra", "do", "da", "to", "ta", "mo", "ma"}
    | {"vo", "va", "no", "na", "o", "a"}
)
# Institutions and housing programmes that name colonias ("CAMPESTRE CTM",
# "CONJUNTO HABITACIONAL UAG", "(FOMERREY 71)"): kept uppercase.
_ACRONYMS = frozenset(
    {"CTM", "CFE", "IMSS", "ISSSTE", "INFONAVIT", "FOVISSSTE", "UAG", "UANL", "UDG"}
    | {"UNAM", "PEMEX", "CROC", "CROM", "SNTE", "FSTSE", "ITESM", "IPN", "CNOP", "CNC"}
    | {"SEDENA", "CONALEP", "DIF", "ISSSTELEON", "SUTERM", "FOMERREY", "PITT", "CID"}
)


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _before_i_sound(word: str | None) -> bool:
    """True when ``word`` starts with i/hi (where Spanish writes "e" for "y")."""
    if not word:
        return False
    match = _LETTER_RUN.search(word)
    if match is None or match.start() > 0:
        return False
    folded = _strip_accents(match.group(0)).casefold()
    return folded.startswith(("i", "hi"))


def _after_digit(run: str, next_char: str) -> str:
    """Case for a letter run glued to a preceding digit.

    One letter then a space/hyphen/end is a code ("7A", "1B-3", "H2O") and stays
    uppercase; an ordinal ending ("1ER", "2DA", "1A.") is lowercased; a run of
    three or more letters is a word glued to a number and is capitalized like one
    ("FIT4LIFE" -> "Fit4Life", "24FREEDOM" -> "24Freedom"); any other short run
    stays uppercase ("5AM", "1B.").
    """
    if len(run) == 1 and next_char in ("", "-"):
        return run.upper()
    if run.casefold() in _ORDINAL_SUFFIXES:
        return run.lower()
    if len(run) >= 3:
        return run[0].upper() + run[1:].lower()
    return run.upper()


def spanish_title_case(text: str) -> str:
    """Title-case an all-caps (or all-lowercase) Spanish place name.

    ``"COLONIA DEL VALLE"`` -> ``"Colonia del Valle"``. The articles and the
    conjunction de/del/la/las/los/y stay lowercase except as the first word
    (``"20 DE SEPTIEMBRE"`` -> ``"20 de Septiembre"``); "e" is lowercased only as
    the conjunction before an i/hi word (``"RIVERA E HIJOS"``), otherwise it is a
    sector letter (``"SEGUNDO SECTOR E -2"`` -> ``"Segundo Sector E -2"``). Roman
    numerals I..XXXIX and a few institution acronyms (CTM, IMSS, INFONAVIT,
    FOMERREY, ...) stay uppercase. Letters glued to a preceding digit stay
    uppercase (``"1B-3"``, ``"URBI ETAPA 7A"``) unless they are an ordinal ending
    (``"1ER SECTOR"`` -> ``"1er Sector"``, ``"2DA"``, ``"1A."``) or a word of three
    or more letters (``"FIT4LIFE"`` -> ``"Fit4Life"``). Accents are preserved. A
    string that already mixes upper and lower case is returned unchanged, as is one
    without letters. Whitespace is collapsed.
    """
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return text
    has_upper = any(char.isupper() for char in letters)
    has_lower = any(char.islower() for char in letters)
    if has_upper and has_lower:
        return text

    tokens = text.split()
    words: list[str] = []
    for index, token in enumerate(tokens):
        next_token = tokens[index + 1] if index + 1 < len(tokens) else None
        pieces: list[str] = []
        cursor = 0
        for match in _LETTER_RUN.finditer(token):
            run = match.group(0)
            start, end = match.start(), match.end()
            pieces.append(token[cursor:start])
            upper = run.upper()
            folded = run.casefold()
            whole_word = run == token
            if start > 0 and token[start - 1].isdigit():
                pieces.append(_after_digit(run, token[end : end + 1]))
            elif upper in _ACRONYMS:
                pieces.append(upper)
            elif index > 0 and whole_word and folded in _SPANISH_LOWERCASE_WORDS:
                pieces.append(run.lower())
            elif index > 0 and whole_word and folded == "e" and _before_i_sound(next_token):
                pieces.append(run.lower())
            elif _ROMAN_NUMERAL.fullmatch(upper):
                pieces.append(upper)
            else:
                pieces.append(run[0].upper() + run[1:].lower())
            cursor = end
        pieces.append(token[cursor:])
        words.append("".join(pieces))
    return " ".join(words)


_UNNAMED_COLONIA_NAMES = frozenset({"", "ninguno", "sin nombre", "s/n", "n/a"})


def is_unnamed_colonia(name: str | None) -> bool:
    """True for the DCAH placeholders: "", NINGUNO, SIN NOMBRE, S/N, N/A.

    Case-, accent- and whitespace-insensitive; ``None``/NaN count as unnamed. A
    placeholder with a real name attached ("NINGUNO (LAS VARAS)") is named.
    """
    if not isinstance(name, str):
        return True
    normalized = " ".join(_strip_accents(name).casefold().split())
    return normalized in _UNNAMED_COLONIA_NAMES


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def profile_mx_area(profile: dict, city: str) -> tuple[str, list[str]]:
    """``(state_code, [cve_mun, ...])`` from a profile's ``mx_area`` block.

    ``state_code`` is the 2-digit INEGI state code and every municipality is a
    3-digit INEGI ``cve_mun`` string, in declared order.

    Raises
    ------
    ConfigError
        The block is missing or malformed.
    """
    block = profile.get("mx_area")
    if not isinstance(block, dict):
        raise ConfigError(
            f"City profile '{city}' must declare mx_area {{state_code, municipalities}}"
        )
    state = block.get("state_code")
    if not isinstance(state, str) or not re.fullmatch(r"\d{2}", state):
        raise ConfigError(
            f"City profile '{city}' mx_area.state_code must be a 2-digit string, got {state!r}"
        )
    municipalities = block.get("municipalities")
    if not isinstance(municipalities, list) or not municipalities:
        raise ConfigError(f"City profile '{city}' mx_area.municipalities must be a non-empty list")
    codes: list[str] = []
    for code in municipalities:
        if not isinstance(code, str) or not re.fullmatch(r"\d{3}", code):
            raise ConfigError(
                f"City profile '{city}' mx_area.municipalities entries must be 3-digit "
                f"strings, got {code!r}"
            )
        if code in codes:
            raise ConfigError(f"City profile '{city}' mx_area.municipalities repeats {code}")
        codes.append(code)
    return state, codes
