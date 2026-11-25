"""SESNSP municipal crime statistics for ``crime_mode == "city_statistics"`` cities.

Writes ``processed/<city>/crime_statistics.csv``: one row per INEGI municipality of
the profile's ``crime_statistics.state_codes`` with

- ``incidents_12m``: every fuero-común carpeta (SESNSP "Incidencia delictiva
  municipal", Delitos) registered in the last 12 published months;
- ``scored_incidents_12m``: the "street crime" subset that drives the safety score
  (``DEFAULT_SCORED_OFFENSES``, or the profile's ``crime_statistics.scored_offenses``);
- ``top_category_12m``: the most frequent *Tipo de delito*;
- ``population``: INEGI Censo 2020 (``mx_common.load_state_municipalities``).

Sources. The SESNSP open-data page lists each release as a SharePoint share link,
and the links change with every monthly upload, so they are found by anchor text:
the current-methodology file of the latest year (RNID 2026: UTF-8 with BOM) and,
only while the 12-month window still reaches into earlier years, the 2015-2025
file (Latin-1, a ~121 MB zip). Both are national; they are cached once under
``data/raw/`` and read as streams, keeping only the profile's states. Months that
are not yet published are 0, not blank, so the window ends at the last month with
a non-zero national total.

SESNSP counts carpetas by the month and municipality where they were *registered*,
not where or when the crime happened. Only aggregates are written.
"""

from __future__ import annotations

import argparse
import calendar
import codecs
import csv
import http.client
import http.cookiejar
import os
import re
import shutil
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath

import pandas as pd

from cdmxmap.citycontext import CRIME_STATISTICS_FILENAME
from cdmxmap.errors import ConfigError, FetchError, SourceUnavailableError

from .io import DATA_PROCESSED, DATA_RAW, USER_AGENT, city_data_dir, load_city_profile
from .mx_common import load_state_municipalities

MONTHS = (
    "Enero",
    "Febrero",
    "Marzo",
    "Abril",
    "Mayo",
    "Junio",
    "Julio",
    "Agosto",
    "Septiembre",
    "Octubre",
    "Noviembre",
    "Diciembre",
)
YEAR_COLUMN = "Año"
STATE_COLUMN = "Clave_Ent"
MUNICIPALITY_COLUMN = "Cve. Municipio"
TIPO_COLUMN = "Tipo de delito"
SUBTIPO_COLUMN = "Subtipo de delito"
ID_COLUMNS = (YEAR_COLUMN, STATE_COLUMN, MUNICIPALITY_COLUMN, TIPO_COLUMN, SUBTIPO_COLUMN)
SESNSP_COLUMNS = (*ID_COLUMNS, *MONTHS)

# The 2015-2025 "metodología actual" and the RNID 2026 files share one layout; the
# 2011-2017 municipal file (old methodology) has different columns and is never used.
CURRENT_METHODOLOGY_FIRST_YEAR = 2015
WINDOW_MONTHS = 12

# The "street crime" subset. An entry matches a row when it equals the row's tipo
# or subtipo (case- and accent-insensitive), so "Robo" takes every robbery subtipo.
# Strings checked in both the 2015-2025 and the RNID 2026 files:
# - Robo: all subtipos (RNID splits vehicles and maquinaria further).
# - Homicidio doloso and, from RNID 2026, Tentativa de homicidio doloso (Homicidio
#   culposo is excluded).
# - Feminicidio: the tipo, so RNID's Tentativa de feminicidio counts too. In Nuevo
#   León about 300 lesiones dolosas a year moved to that subtipo in 2026, and
#   lesiones dolosas are scored, so this keeps the series continuous.
# - Lesiones dolosas (Lesiones culposas excluded).
# - Secuestro and Extorsión: the tipos, i.e. every subtipo. 2015-2025 has a single
#   "Extorsión"/"Secuestro" subtipo; RNID 2026 splits them (presencial, por otros
#   medios, tentativas), and Nuevo León files all 2026 extortion as "por otros medios".
# - Violación: the RNID tipo; "Violación simple"/"Violación equiparada" were tipos of
#   their own until 2025.
DEFAULT_SCORED_OFFENSES = (
    "Robo",
    "Homicidio doloso",
    "Tentativa de homicidio doloso",
    "Feminicidio",
    "Lesiones dolosas",
    "Secuestro",
    "Extorsión",
    "Violación",
    "Violación simple",
    "Violación equiparada",
)
# 2015-2025 tipos that RNID 2026 merged into one, so ``top_category_12m`` does not
# split a category across a mixed-methodology window.
TIPO_ALIASES = {
    "violacion simple": "Violación",
    "violacion equiparada": "Violación",
}

OUTPUT_COLUMNS = [
    "unit_key",
    "unit_name",
    "population",
    "population_source",
    "period_start",
    "period_end",
    "incidents_12m",
    "scored_incidents_12m",
    "top_category_12m",
    "source",
]

SHAREPOINT_HOST_SUFFIX = ".sharepoint.com"
_NETWORK_ERRORS: tuple[type[BaseException], ...] = (
    urllib.error.URLError,
    TimeoutError,
    ConnectionError,
    http.client.HTTPException,
)
_DOWNLOAD_CHUNK = 1 << 20
_SAMPLE_BYTES = 1 << 16
_CSV_CHUNK_ROWS = 250_000
_MAX_PAGE_BYTES = 8_000_000

YearMonth = tuple[int, int]


# ---------------------------------------------------------------------------
# Text and HTML helpers (also used by fetch_iieg_crime)
# ---------------------------------------------------------------------------


def normalize_text(text: str) -> str:
    """Casefold, strip accents and collapse whitespace (``&nbsp;`` included)."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(stripped.casefold().split())


class _AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def _close(self) -> None:
        if self._href is not None:
            self.anchors.append((self._href, " ".join("".join(self._text).split())))
        self._href = None
        self._text = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._close()  # an unclosed <a> ends where the next one starts
            self._href = (dict(attrs).get("href") or "").strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._close()

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)


def collect_anchors(html: str) -> list[tuple[str, str]]:
    """Every ``<a href>`` in ``html`` as ``(href, visible text)``, in page order.

    Entities are decoded and whitespace (including ``&nbsp;``) is collapsed.
    """
    collector = _AnchorCollector()
    collector.feed(html)
    collector.close()
    collector._close()
    return collector.anchors


def fetch_page(url: str, *, timeout: int = 60) -> str:
    """GET an HTML index page with the repo User-Agent (never cached).

    Raises
    ------
    SourceUnavailableError
        The page could not be fetched.
    FetchError
        The page is larger than 8 MB (an index page never is).
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(_MAX_PAGE_BYTES + 1)
            charset = response.headers.get_content_charset() or "utf-8"
    except _NETWORK_ERRORS as exc:
        raise SourceUnavailableError(f"Could not fetch {url}: {exc}") from exc
    if len(body) > _MAX_PAGE_BYTES:
        raise FetchError(f"{url} returned more than {_MAX_PAGE_BYTES:,} bytes")
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def write_csv_atomic(frame: pd.DataFrame, path: Path) -> None:
    """Write ``frame`` as UTF-8 CSV via a temp file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.stem}.{uuid.uuid4().hex[:12]}.part{path.suffix}")
    try:
        frame.to_csv(tmp_path, index=False, encoding="utf-8", lineterminator="\n")
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)
    print(f"Wrote {path} ({len(frame):,} rows)")


# ---------------------------------------------------------------------------
# Releases listed on the SESNSP page
# ---------------------------------------------------------------------------

_MONTH_NUMBERS = {normalize_text(name): number for number, name in enumerate(MONTHS, start=1)}
# "Enero - octubre 2026 (Fuero común - Delitos). Incidencia delictiva municipal",
# "Enero 2027 (...)" (only January published) and "2015 - 2025 (Fuero Común - Delitos).
# Incidencia delictiva municipal", matched on ``normalize_text`` of the anchor text.
_RELEASE_LABEL = re.compile(
    r"^(?:enero(?:\s*-\s*(?P<month>[a-z]+))?\s+(?P<year>\d{4})"
    r"|(?P<first>\d{4})\s*-\s*(?P<last>\d{4}))"
    r"\s*\(\s*fuero comun\s*-\s*delitos\s*\)\s*\.?\s*incidencia delictiva municipal\s*\.?$"
)


@dataclass(frozen=True)
class SesnspRelease:
    """One "Incidencia delictiva municipal (Fuero común - Delitos)" download link."""

    label: str
    url: str
    first_year: int
    last_year: int
    last_month: int  # the cut month of a partial year; 12 for full-year ranges

    def covers(self, year: int) -> bool:
        return self.first_year <= year <= self.last_year

    @property
    def slug(self) -> str:
        period = normalize_text(self.label).split("(", 1)[0]
        return re.sub(r"[^a-z0-9]+", "-", period).strip("-")

    @property
    def download_url(self) -> str:
        """The share link with ``download=1``, which redirects to the file itself."""
        query = urllib.parse.urlsplit(self.url).query
        if "download" in dict(urllib.parse.parse_qsl(query, keep_blank_values=True)):
            return self.url
        return f"{self.url}{'&' if query else '?'}download=1"


def _is_sharepoint_url(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and host.endswith(SHAREPOINT_HOST_SUFFIX)


def parse_releases(html: str, *, base_url: str) -> list[SesnspRelease]:
    """The municipal fuero-común Delitos releases linked from the SESNSP page.

    Víctimas, estatal, fuero federal and "Tablero dinámico" links do not match the
    label pattern; ranges that start before 2015 (old methodology) and links that
    are not https SharePoint URLs are skipped.
    """
    releases: list[SesnspRelease] = []
    for href, text in collect_anchors(html):
        match = _RELEASE_LABEL.match(normalize_text(text))
        if match is None:
            continue
        url = urllib.parse.urljoin(base_url, href)
        if not _is_sharepoint_url(url):
            print(f"Skipping SESNSP link {text!r}: not an https SharePoint URL")
            continue
        if match["year"] is not None:
            year = int(match["year"])
            month_name = match["month"] or "enero"
            if month_name not in _MONTH_NUMBERS:
                print(f"Skipping SESNSP link {text!r}: unknown month {month_name!r}")
                continue
            first, last, last_month = year, year, _MONTH_NUMBERS[month_name]
        else:
            first, last, last_month = int(match["first"]), int(match["last"]), 12
        if first < CURRENT_METHODOLOGY_FIRST_YEAR or first > last:
            continue
        releases.append(SesnspRelease(text, url, first, last, last_month))
    return releases


def select_current_release(releases: Sequence[SesnspRelease]) -> SesnspRelease:
    """The release with the latest cut; on a tie, the narrowest (single-year) one."""
    if not releases:
        raise FetchError(
            "The SESNSP page lists no 'Incidencia delictiva municipal (Fuero común - "
            "Delitos)' download"
        )
    return max(releases, key=lambda r: (r.last_year, r.last_month, r.first_year))


def release_covering(
    releases: Sequence[SesnspRelease], year: int, *, exclude: SesnspRelease
) -> SesnspRelease:
    """The most recent release (other than ``exclude``) whose years include ``year``."""
    candidates = [r for r in releases if r != exclude and r.covers(year)]
    if not candidates:
        raise FetchError(
            f"The 12-month window needs {year}, but the SESNSP page lists no municipal "
            f"Delitos release covering it (current release: {exclude.label!r})"
        )
    return max(candidates, key=lambda r: (r.last_year, r.last_month, r.first_year))


def release_cache_path(release: SesnspRelease, current: SesnspRelease) -> Path:
    """National cache file under ``data/raw/``.

    The historic file is reissued with every monthly cut (its member is named e.g.
    ``Municipal-Delitos-2015-2025_oct2026.csv``), so its cache name carries the cut
    of the current release it was downloaded with.
    """
    if release == current:
        return DATA_RAW / f"mx_sesnsp_delitos_municipal_{release.slug}.zip"
    return DATA_RAW / f"mx_sesnsp_delitos_municipal_{release.slug}_as-of-{current.slug}.zip"


# ---------------------------------------------------------------------------
# Downloads (SharePoint needs a cookie between the redirect and the file)
# ---------------------------------------------------------------------------


def sharepoint_download(url: str, path: Path, *, timeout: int = 600) -> None:
    """Stream a SharePoint ``download=1`` link into ``path``.

    The share link answers with a 302 that sets a ``FedAuth`` cookie which the file
    URL then requires (a cookie-less client gets 403), so this uses a cookie-aware
    opener. The final URL must still be https on SharePoint. This is the network
    seam that tests replace.
    """
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener.open(request, timeout=timeout) as response:
        final_url = response.geturl()
        if not _is_sharepoint_url(final_url):
            raise FetchError(f"SESNSP link {url} redirected off SharePoint to {final_url}")
        with path.open("wb") as handle:
            shutil.copyfileobj(response, handle, _DOWNLOAD_CHUNK)


def cached_release_download(
    url: str,
    target: Path,
    *,
    validate: Callable[[Path], None],
    force: bool = False,
    timeout: int = 600,
) -> Path:
    """``mx_common.cached_download`` semantics over ``sharepoint_download``.

    Reuses a non-empty ``target`` unless ``force``; otherwise streams to a unique
    temp file next to it, validates, and promotes it with ``os.replace``.
    """
    if not force and target.exists() and target.stat().st_size > 0:
        print(f"Using cached {target}")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f"{target.stem}.{uuid.uuid4().hex[:12]}.part{target.suffix}")
    try:
        print(f"Downloading {url}")
        try:
            sharepoint_download(url, tmp_path, timeout=timeout)
        except _NETWORK_ERRORS as exc:
            raise SourceUnavailableError(f"Could not download {url}: {exc}") from exc
        if tmp_path.stat().st_size == 0:
            raise FetchError(f"Download of {url} returned an empty body")
        try:
            validate(tmp_path)
        except (ValueError, zipfile.BadZipFile, UnicodeDecodeError, csv.Error) as exc:
            raise FetchError(f"Download of {url} failed validation: {exc}") from exc
        os.replace(tmp_path, target)
    finally:
        tmp_path.unlink(missing_ok=True)
    print(f"Wrote {target} ({target.stat().st_size:,} bytes)")
    return target


# ---------------------------------------------------------------------------
# Reading a release zip
# ---------------------------------------------------------------------------

_CANONICAL_COLUMNS = {normalize_text(column): column for column in SESNSP_COLUMNS}


def _is_delitos_csv(name: str) -> bool:
    base = normalize_text(PurePosixPath(name.replace("\\", "/")).name)
    return base.endswith(".csv") and "delitos" in base and "municipal" in base


def release_csv_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    """The single municipal Delitos CSV in a release zip (xlsx/pdf extras are ignored)."""
    members = [
        info for info in archive.infolist() if not info.is_dir() and _is_delitos_csv(info.filename)
    ]
    if len(members) != 1:
        names = [info.filename for info in archive.infolist()]
        raise ValueError(f"expected one municipal Delitos CSV in the zip, found {names}")
    return members[0]


def detect_encoding(sample: bytes) -> str:
    """``utf-8-sig`` with a BOM (RNID), ``utf-8`` if the sample decodes, else Latin-1.

    The 2015-2025 file is Latin-1 (its header already has ``A\\xf1o``), and it has
    no bytes in 0x80-0x9F, so Latin-1 and cp1252 read it identically.
    """
    if sample.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    complete = sample[: sample.rfind(b"\n") + 1] or sample
    try:
        complete.decode("utf-8")
    except UnicodeDecodeError:
        return "latin-1"
    return "utf-8"


def _read_header(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> tuple[str, list[str]]:
    with archive.open(member) as handle:
        sample = handle.read(_SAMPLE_BYTES)
    encoding = detect_encoding(sample)
    first_line = sample.split(b"\n", 1)[0].rstrip(b"\r").decode(encoding)
    return encoding, next(csv.reader([first_line]))


def column_map(header: Sequence[str]) -> dict[str, str]:
    """Map the file's header names to the canonical ``SESNSP_COLUMNS`` names."""
    mapping = {
        name: _CANONICAL_COLUMNS[normalize_text(name)]
        for name in header
        if normalize_text(name) in _CANONICAL_COLUMNS
    }
    missing = sorted(set(SESNSP_COLUMNS) - set(mapping.values()))
    if missing:
        raise ValueError(f"SESNSP CSV is missing columns {missing}")
    return mapping


def validate_release_zip(path: Path) -> None:
    """Zip with one municipal Delitos CSV whose header has every SESNSP column.

    The member is read to the end once so ``zipfile`` checks its CRC.
    """
    if not zipfile.is_zipfile(path):
        raise ValueError("SESNSP download is not a zip archive")
    with zipfile.ZipFile(path) as archive:
        member = release_csv_member(archive)
        _encoding, header = _read_header(archive, member)
        column_map(header)
        with archive.open(member) as handle:
            while handle.read(_DOWNLOAD_CHUNK):
                pass


@dataclass(frozen=True)
class ReleaseCounts:
    """What one release contributes: national monthly totals and the states' rows.

    ``national`` maps (year, month) to the national carpetas for every month of
    every year read (0 = not published). ``rows`` has columns year, mun_code
    (5-digit), tipo, subtipo and the twelve month names, for the requested states.
    """

    national: dict[YearMonth, int]
    rows: pd.DataFrame

    @property
    def years(self) -> set[int]:
        return {year for year, _ in self.national}


def _monthly_counts(chunk: pd.DataFrame) -> pd.DataFrame:
    counts: dict[str, pd.Series] = {}
    for month in MONTHS:
        values = chunk[month]
        if not pd.api.types.is_numeric_dtype(values):
            text = values.astype(str).str.strip()
            values = pd.to_numeric(text.where(text != "", "0"), errors="coerce")
        if values.isna().any() or (values < 0).any() or (values % 1 != 0).any():
            raise FetchError(f"SESNSP file has a non-count value in column {month}")
        counts[month] = values.astype("int64")
    return pd.DataFrame(counts, index=chunk.index)


def _state_rows(chunk: pd.DataFrame, counts: pd.DataFrame, states: set[str]) -> pd.DataFrame:
    state = chunk[STATE_COLUMN].str.strip().str.zfill(2)
    keep = state.isin(states)
    municipality = chunk.loc[keep, MUNICIPALITY_COLUMN].str.strip().str.zfill(5)
    if not municipality.str.fullmatch(r"\d{5}").all():
        raise FetchError("SESNSP file has a municipality code that is not 5 digits")
    if (municipality.str[:2] != state[keep]).any():
        raise FetchError("SESNSP file has a municipality code outside its Clave_Ent")
    frame = pd.DataFrame(
        {
            "year": chunk.loc[keep, YEAR_COLUMN],
            "mun_code": municipality,
            "tipo": chunk.loc[keep, TIPO_COLUMN].str.strip(),
            "subtipo": chunk.loc[keep, SUBTIPO_COLUMN].str.strip(),
        }
    )
    return pd.concat([frame, counts.loc[keep]], axis=1)


def read_release(
    path: Path, *, state_codes: Collection[str], years: Collection[int] | None = None
) -> ReleaseCounts:
    """Stream a release CSV out of its zip, keeping the given states (and years).

    National monthly totals are summed over every row of the kept years (all
    states), so unpublished months can be told apart. Only the needed columns are
    parsed; codes are zero-padded (``1`` -> ``01``, ``1001`` -> ``01001``).
    """
    states = {str(code).zfill(2) for code in state_codes}
    national: Counter[YearMonth] = Counter()
    parts: list[pd.DataFrame] = []
    with zipfile.ZipFile(path) as archive:
        member = release_csv_member(archive)
        encoding, header = _read_header(archive, member)
        columns = column_map(header)
        id_columns = [name for name, canonical in columns.items() if canonical in ID_COLUMNS]
        with archive.open(member) as handle:
            reader = pd.read_csv(
                handle,
                encoding=encoding,
                usecols=list(columns),
                dtype=dict.fromkeys(id_columns, str),
                keep_default_na=False,
                chunksize=_CSV_CHUNK_ROWS,
            )
            for raw_chunk in reader:
                chunk = raw_chunk.rename(columns=columns)
                year = pd.to_numeric(chunk[YEAR_COLUMN].str.strip(), errors="coerce")
                if year.isna().any():
                    raise FetchError(f"SESNSP file {member.filename} has a non-numeric Año")
                chunk[YEAR_COLUMN] = year.astype(int)
                if years is not None:
                    chunk = chunk[chunk[YEAR_COLUMN].isin(set(years))]
                if chunk.empty:
                    continue
                counts = _monthly_counts(chunk)
                totals = counts.groupby(chunk[YEAR_COLUMN]).sum()
                for row_year, values in zip(totals.index.astype(int), totals.to_numpy()):
                    for number, total in enumerate(values, start=1):
                        national[(int(row_year), number)] += int(total)
                parts.append(_state_rows(chunk, counts, states))
    rows = (
        pd.concat(parts, ignore_index=True)
        if parts
        else pd.DataFrame(columns=["year", "mun_code", "tipo", "subtipo", *MONTHS])
    )
    print(f"Read {member.filename} ({encoding}): {len(rows):,} rows for states {sorted(states)}")
    return ReleaseCounts(dict(national), rows)


# ---------------------------------------------------------------------------
# Window and aggregation
# ---------------------------------------------------------------------------


def latest_populated_month(national: Mapping[YearMonth, int]) -> YearMonth:
    """The last (year, month) with a non-zero national total."""
    populated = [key for key, total in national.items() if total > 0]
    if not populated:
        raise FetchError("The SESNSP release has no month with national records")
    return max(populated)


def trailing_months(end: YearMonth, count: int = WINDOW_MONTHS) -> list[YearMonth]:
    """``count`` consecutive months ending at ``end``, oldest first."""
    year, month = end
    months: list[YearMonth] = []
    for _ in range(count):
        months.append((year, month))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return months[::-1]


def period_bounds(window: Sequence[YearMonth]) -> tuple[str, str]:
    """``("YYYY-MM-01", "YYYY-MM-<last day>")`` of a month window."""
    (first_year, first_month), (last_year, last_month) = window[0], window[-1]
    last_day = calendar.monthrange(last_year, last_month)[1]
    return (
        f"{first_year:04d}-{first_month:02d}-01",
        f"{last_year:04d}-{last_month:02d}-{last_day:02d}",
    )


def check_window_published(window: Sequence[YearMonth], national: Mapping[YearMonth, int]) -> None:
    """Every window month must have national records (a gap is never a real zero)."""
    gaps = [f"{year}-{month:02d}" for year, month in window if national.get((year, month), 0) <= 0]
    if gaps:
        raise FetchError(f"SESNSP has no national records for {gaps}; refusing a partial window")


def window_counts(rows: pd.DataFrame, window: Sequence[YearMonth]) -> pd.DataFrame:
    """Long frame (mun_code, tipo, subtipo, n): each row's carpetas inside the window."""
    parts = []
    for year in sorted({year for year, _ in window}):
        months = [MONTHS[month - 1] for row_year, month in window if row_year == year]
        subset = rows[rows["year"] == year]
        parts.append(
            pd.DataFrame(
                {
                    "mun_code": subset["mun_code"],
                    "tipo": subset["tipo"],
                    "subtipo": subset["subtipo"],
                    "n": subset[months].sum(axis=1).astype("int64"),
                }
            )
        )
    return pd.concat(parts, ignore_index=True)


def harmonize_tipo(tipo: str) -> str:
    return TIPO_ALIASES.get(normalize_text(tipo), tipo)


def scored_mask(long: pd.DataFrame, scored_offenses: Iterable[str]) -> pd.Series:
    """Rows whose tipo (raw or harmonized) or subtipo is a scored offense."""
    keys = {normalize_text(offense) for offense in scored_offenses}

    def matches(values: pd.Series) -> pd.Series:
        lookup = {value: normalize_text(value) in keys for value in values.unique()}
        return values.map(lookup).astype(bool)

    return (
        matches(long["tipo"]) | matches(long["tipo"].map(harmonize_tipo)) | matches(long["subtipo"])
    )


def aggregate_municipalities(long: pd.DataFrame, scored_offenses: Iterable[str]) -> pd.DataFrame:
    """Per mun_code: incidents_12m, scored_incidents_12m and top_category_12m.

    ``top_category_12m`` is the harmonized tipo with the most carpetas (ties broken
    alphabetically), or "" for a municipality with none.
    """
    frame = long.assign(tipo=long["tipo"].map(harmonize_tipo))
    frame["scored"] = frame["n"].where(scored_mask(long, scored_offenses), 0)
    totals = frame.groupby("mun_code", sort=True)[["n", "scored"]].sum()
    by_tipo = frame.groupby(["mun_code", "tipo"], sort=True)["n"].sum().reset_index()
    top = (
        by_tipo[by_tipo["n"] > 0]
        .sort_values(["mun_code", "n", "tipo"], ascending=[True, False, True], kind="mergesort")
        .drop_duplicates("mun_code")
        .set_index("mun_code")["tipo"]
    )
    return pd.DataFrame(
        {
            "incidents_12m": totals["n"].astype("int64"),
            "scored_incidents_12m": totals["scored"].astype("int64"),
            "top_category_12m": top.reindex(totals.index).fillna(""),
        }
    )


# ---------------------------------------------------------------------------
# Profile and orchestration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StatisticsConfig:
    index_url: str
    state_codes: tuple[str, ...]
    source: str
    population_source: str
    scored_offenses: tuple[str, ...]
    metro_members: tuple[str, ...]  # 5-digit codes from mx_area, may be empty


def statistics_config(profile: dict, city: str) -> StatisticsConfig:
    """The validated ``crime_statistics`` block (plus ``mx_area`` metro members)."""
    block = profile.get("crime_statistics")
    if not isinstance(block, dict):
        raise ConfigError(f"City profile '{city}' must declare a crime_statistics block")
    index_url = block.get("index_url")
    if not isinstance(index_url, str) or not index_url.startswith("https://"):
        raise ConfigError(f"City profile '{city}' crime_statistics.index_url must be https")
    states = block.get("state_codes")
    if (
        not isinstance(states, list)
        or not states
        or not all(isinstance(code, str) and re.fullmatch(r"\d{2}", code) for code in states)
    ):
        raise ConfigError(
            f"City profile '{city}' crime_statistics.state_codes must list 2-digit strings"
        )
    for key in ("source", "population_source"):
        if not isinstance(block.get(key), str) or not block[key].strip():
            raise ConfigError(f"City profile '{city}' crime_statistics.{key} must be a string")
    scored = block.get("scored_offenses", list(DEFAULT_SCORED_OFFENSES))
    if not isinstance(scored, list) or not scored or not all(isinstance(s, str) for s in scored):
        raise ConfigError(
            f"City profile '{city}' crime_statistics.scored_offenses must be a list of strings"
        )
    area = profile.get("mx_area")
    if not isinstance(area, dict):
        area = {}
    members = tuple(f"{area.get('state_code')}{code}" for code in area.get("municipalities") or [])
    return StatisticsConfig(
        index_url=index_url,
        state_codes=tuple(states),
        source=block["source"].strip(),
        population_source=block["population_source"].strip(),
        scored_offenses=tuple(scored),
        metro_members=members,
    )


def collect_window(
    releases: Sequence[SesnspRelease], states: Collection[str], *, force: bool = False
) -> tuple[list[YearMonth], pd.DataFrame, set[str]]:
    """Download what the window needs and return (window, long counts, codes present).

    The current release decides the window (its last month with national records);
    older releases are fetched only for window years the current file lacks. A
    municipality is "present" when every contributing file has rows for it.
    """
    current = select_current_release(releases)
    print(f"Current SESNSP release: {current.label}")
    path = cached_release_download(
        current.download_url,
        release_cache_path(current, current),
        validate=validate_release_zip,
        force=force,
    )
    parts = [read_release(path, state_codes=states)]
    end = latest_populated_month(parts[0].national)
    if end[1] != current.last_month or end[0] != current.last_year:
        print(f"Note: the link says {current.label!r} but the data ends {end[0]}-{end[1]:02d}")
    window = trailing_months(end)
    for year in sorted({year for year, _ in window} - parts[0].years):
        older = release_covering(releases, year, exclude=current)
        print(f"Window reaches {year}: also using {older.label}")
        older_path = cached_release_download(
            older.download_url,
            release_cache_path(older, current),
            validate=validate_release_zip,
            force=force,
        )
        parts.append(read_release(older_path, state_codes=states, years={year}))
    national: dict[YearMonth, int] = {}
    for part in reversed(parts):  # the current file wins for any year both carry
        national.update(part.national)
    check_window_published(window, national)
    present = set.intersection(*(set(part.rows["mun_code"]) for part in parts))
    rows = pd.concat([part.rows for part in parts], ignore_index=True)
    return window, window_counts(rows, window), present


def statistics_rows(
    aggregates: pd.DataFrame,
    municipalities: pd.DataFrame,
    present: set[str],
    config: StatisticsConfig,
    window: Sequence[YearMonth],
) -> pd.DataFrame:
    """One output row per INEGI municipality that the SESNSP files cover.

    A municipality missing from the SESNSP files is left out with a warning (never
    written as a fake zero); a missing metro member is an error.
    """
    missing = sorted(set(municipalities["mun_code"]) - present)
    if missing:
        print(f"WARNING: no SESNSP rows for INEGI municipalities {missing}; left out")
    missing_members = sorted(set(config.metro_members) & set(missing))
    if missing_members:
        raise FetchError(f"SESNSP has no rows for metro municipalities {missing_members}")
    unknown = aggregates[~aggregates.index.isin(set(municipalities["mun_code"]))]
    if not unknown.empty:
        print(
            f"SESNSP codes without an INEGI municipality (dropped): {sorted(unknown.index)} "
            f"with {int(unknown['incidents_12m'].sum()):,} carpetas in the window"
        )
    if (municipalities["population"] <= 0).any():
        raise FetchError("INEGI reports a municipality with no population")
    start, end = period_bounds(window)
    kept = municipalities[municipalities["mun_code"].isin(present)].sort_values("mun_code")
    joined = aggregates.reindex(kept["mun_code"])
    return pd.DataFrame(
        {
            "unit_key": kept["mun_code"].to_numpy(),
            "unit_name": kept["municipio"].to_numpy(),
            "population": kept["population"].astype("int64").to_numpy(),
            "population_source": config.population_source,
            "period_start": start,
            "period_end": end,
            "incidents_12m": joined["incidents_12m"].fillna(0).astype("int64").to_numpy(),
            "scored_incidents_12m": joined["scored_incidents_12m"]
            .fillna(0)
            .astype("int64")
            .to_numpy(),
            "top_category_12m": joined["top_category_12m"].fillna("").to_numpy(),
            "source": config.source,
        },
        columns=OUTPUT_COLUMNS,
    )


def _print_summary(table: pd.DataFrame, config: StatisticsConfig, long: pd.DataFrame) -> None:
    scored = long[scored_mask(long, config.scored_offenses)]
    pairs = sorted({f"{tipo} / {subtipo}" for tipo, subtipo in zip(scored.tipo, scored.subtipo)})
    print(f"Scored offense rows ({len(pairs)} tipo/subtipo pairs): {'; '.join(pairs)}")
    tipos, subtipos = long["tipo"].unique(), long["subtipo"].unique()
    keys = {normalize_text(value) for value in [*tipos, *subtipos]}
    keys |= {normalize_text(harmonize_tipo(value)) for value in tipos}
    unmatched = [o for o in config.scored_offenses if normalize_text(o) not in keys]
    if unmatched:
        print(f"Scored offenses matching no tipo/subtipo in the window: {unmatched}")
    print(
        f"Window {table['period_start'].iloc[0]} to {table['period_end'].iloc[0]}: "
        f"{len(table)} municipalities, {int(table['incidents_12m'].sum()):,} carpetas, "
        f"{int(table['scored_incidents_12m'].sum()):,} scored"
    )
    members = table[table["unit_key"].isin(set(config.metro_members))]
    for row in members.to_dict("records"):
        population, scored_n = int(row["population"]), int(row["scored_incidents_12m"])
        print(
            f"  {row['unit_key']} {row['unit_name']}: pop {population:,}, "
            f"{int(row['incidents_12m']):,} carpetas, {scored_n:,} scored "
            f"({scored_n / population * 100_000:.1f}/100k), top {row['top_category_12m']}"
        )


def build_crime_statistics(city: str, *, force: bool = False) -> Path:
    """Fetch, aggregate and write ``crime_statistics.csv`` for ``city``."""
    profile = load_city_profile(city)
    config = statistics_config(profile, city)
    releases = parse_releases(fetch_page(config.index_url), base_url=config.index_url)
    window, long, present = collect_window(releases, config.state_codes, force=force)
    aggregates = aggregate_municipalities(long, config.scored_offenses)
    municipalities = pd.concat(
        [
            pd.DataFrame(load_state_municipalities(state)[["mun_code", "municipio", "population"]])
            for state in config.state_codes
        ],
        ignore_index=True,
    )
    table = statistics_rows(aggregates, municipalities, present, config, window)
    if table.empty:
        raise FetchError(f"SESNSP has no rows for any municipality of states {config.state_codes}")
    target = city_data_dir(DATA_PROCESSED, city) / CRIME_STATISTICS_FILENAME
    write_csv_atomic(table, target)
    _print_summary(table, config, long)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build municipal crime statistics from SESNSP open data."
    )
    parser.add_argument("--city", required=True, help="City profile id (e.g. monterrey).")
    parser.add_argument("--force", action="store_true", help="Redownload cached releases.")
    args = parser.parse_args()
    build_crime_statistics(args.city, force=args.force)


if __name__ == "__main__":
    main()
