"""IIEG Jalisco incident points (Fiscalía del Estado microdata) for ``incident_points`` cities.

Writes ``processed/<city>/crime_points.csv`` with the columns the engine's
``read_crimes`` accepts (``date,category,offense,borough,latitude,longitude,source``)
from the IIEG regional "Incidencia delictiva" microdata:

- The profile's ``crime_source.index_url`` lists one zip per region and release;
  the newest one whose link text (or file name) matches ``link_text_pattern`` is
  used, judged by the end month in its file name, with ``fallback_url`` as a
  candidate too (and the only one when the page is down or lists none).
- Only https links on iieg.gob.mx that end in ``.zip`` are followed: the IIEG
  WordPress site has shown injected spam, so the page and the zip are untrusted
  data. The download must also *end* on https iieg.gob.mx after any redirect
  (checked before anything is written). The zip must hold exactly one CSV with the
  expected header.
- Rows are kept when ``zona_geografica`` equals the profile's value (AMG) and the
  WGS84 ``x``/``y`` fall inside the profile bbox expanded by ``BBOX_MARGIN_DEG``.
  Every date is written; the engine picks the 12-month window.

The rows are victim-level records, so this module prints counts only (by year and
by category), never a row; downstream outputs are aggregates.
"""

from __future__ import annotations

import argparse
import calendar
import re
import urllib.parse
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath

import pandas as pd

from cdmxmap.errors import ConfigError, FetchError, SourceUnavailableError

from . import mx_common
from .fetch_sesnsp_crime_statistics import (
    collect_anchors,
    fetch_page,
    normalize_text,
    write_csv_atomic,
)
from .io import DATA_PROCESSED, DATA_RAW, city_data_dir, load_city_profile

IIEG_HOST = "iieg.gob.mx"
REQUIRED_COLUMNS = ("fecha", "delito", "x", "y", "municipio", "zona_geografica")
OUTPUT_COLUMNS = ["date", "category", "offense", "borough", "latitude", "longitude", "source"]
BBOX_MARGIN_DEG = 0.05

# Spanish month names and the abbreviations IIEG uses in file names
# ("..._agosto2025.zip", "Centro_agosto24.zip", "..._dic25.zip", "valles_abr24.zip").
_MONTH_TOKENS = {
    "enero": 1,
    "ene": 1,
    "febrero": 2,
    "feb": 2,
    "marzo": 3,
    "mar": 3,
    "abril": 4,
    "abr": 4,
    "mayo": 5,
    "may": 5,
    "junio": 6,
    "jun": 6,
    "julio": 7,
    "jul": 7,
    "agosto": 8,
    "ago": 8,
    "septiembre": 9,
    "setiembre": 9,
    "sept": 9,
    "sep": 9,
    "octubre": 10,
    "oct": 10,
    "noviembre": 11,
    "nov": 11,
    "diciembre": 12,
    "dic": 12,
}
_MONTH_ALTERNATION = "|".join(sorted(_MONTH_TOKENS, key=len, reverse=True))
_NAME_MONTH_YEAR = re.compile(rf"(?<![a-z])({_MONTH_ALTERNATION})[\s_.-]*(\d{{4}}|\d{{2}})(?!\d)")
_TEXT_MONTH_YEAR = re.compile(rf"(?<![a-z])({_MONTH_ALTERNATION})\s+(?:de\s+)?(\d{{4}})(?!\d)")
_SAFE_ZIP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.zip")


@dataclass(frozen=True)
class CrimeSourceConfig:
    index_url: str
    link_pattern: re.Pattern[str]
    fallback_url: str | None
    zona_geografica: str
    source: str


def crime_source_config(profile: dict, city: str) -> CrimeSourceConfig:
    """The validated ``crime_source`` block of an IIEG profile city."""
    block = profile.get("crime_source")
    if not isinstance(block, dict) or block.get("type") != "iieg_jalisco":
        raise ConfigError(f"City profile '{city}' must declare crime_source.type 'iieg_jalisco'")
    index_url = block.get("index_url")
    if not isinstance(index_url, str) or not is_iieg_url(index_url):
        raise ConfigError(f"City profile '{city}' crime_source.index_url must be https on iieg")
    fallback = block.get("fallback_url")
    if fallback is not None and (not isinstance(fallback, str) or not is_iieg_zip_url(fallback)):
        raise ConfigError(f"City profile '{city}' crime_source.fallback_url must be an IIEG zip")
    for key in ("link_text_pattern", "zona_geografica", "source"):
        if not isinstance(block.get(key), str) or not block[key].strip():
            raise ConfigError(f"City profile '{city}' crime_source.{key} must be a string")
    try:
        pattern = re.compile(block["link_text_pattern"], re.IGNORECASE)
    except re.error as exc:
        raise ConfigError(f"City profile '{city}' crime_source.link_text_pattern: {exc}") from exc
    return CrimeSourceConfig(
        index_url=index_url,
        link_pattern=pattern,
        fallback_url=fallback,
        zona_geografica=block["zona_geografica"].strip(),
        source=block["source"].strip(),
    )


# ---------------------------------------------------------------------------
# Finding the newest regional zip
# ---------------------------------------------------------------------------


def is_iieg_url(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host == IIEG_HOST or host.endswith(f".{IIEG_HOST}"))


def is_iieg_zip_url(url: str) -> bool:
    """https on iieg.gob.mx and a path ending in ``.zip`` (no query tricks)."""
    parts = urllib.parse.urlsplit(url)
    return is_iieg_url(url) and parts.path.lower().endswith(".zip") and not parts.query


def zip_basename(url: str) -> str:
    return urllib.parse.unquote(PurePosixPath(urllib.parse.urlsplit(url).path).name)


def end_month_from_name(name: str) -> date | None:
    """The last ``<month><year>`` in a file name, as the first day of that month.

    ``..._enero-2017_agosto2025.zip`` -> 2025-08-01, ``Centro_agosto24.zip`` ->
    2024-08-01, ``..._dic25.zip`` -> 2025-12-01.
    """
    matches = list(_NAME_MONTH_YEAR.finditer(normalize_text(name)))
    if not matches:
        return None
    month_token, year_text = matches[-1].groups()
    year = int(year_text) + (2000 if len(year_text) == 2 else 0)
    return date(year, _MONTH_TOKENS[month_token], 1)


def end_month_from_text(text: str) -> date | None:
    """The last "<mes> <YYYY>" in a link text ("..., septiembre 2024 a agosto 2025")."""
    matches = list(_TEXT_MONTH_YEAR.finditer(normalize_text(text)))
    if not matches:
        return None
    month_token, year_text = matches[-1].groups()
    return date(int(year_text), _MONTH_TOKENS[month_token], 1)


def _name_words(url: str) -> str:
    return re.sub(r"[_.\-]+", " ", zip_basename(url))


def region_zip_candidates(
    html: str, *, base_url: str, pattern: re.Pattern[str]
) -> list[tuple[date | None, str]]:
    """``(end month, url)`` for each IIEG zip link whose text or file name matches."""
    candidates: dict[str, date | None] = {}
    for href, text in collect_anchors(html):
        url = urllib.parse.urljoin(base_url, href)
        if not is_iieg_zip_url(url):
            continue
        if not (pattern.search(text) or pattern.search(_name_words(url))):
            continue
        end = end_month_from_name(zip_basename(url)) or end_month_from_text(text)
        candidates.setdefault(url, end)
    return [(end, url) for url, end in candidates.items()]


def choose_newest(candidates: Sequence[tuple[date | None, str]]) -> str | None:
    """The candidate with the latest end month (undated last; ties by URL)."""
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0] or date.min, item[1]))[1]


def discover_zip_url(config: CrimeSourceConfig) -> str:
    """The newest matching zip on the index page, falling back to ``fallback_url``."""
    candidates: list[tuple[date | None, str]] = []
    try:
        html = fetch_page(config.index_url)
    except (SourceUnavailableError, FetchError) as exc:
        print(f"IIEG index page unavailable ({exc}); using the profile fallback_url")
    else:
        candidates = region_zip_candidates(
            html, base_url=config.index_url, pattern=config.link_pattern
        )
        print(f"IIEG index lists {len(candidates)} matching zip link(s)")
    if config.fallback_url is not None:
        fallback_end = end_month_from_name(zip_basename(config.fallback_url))
        candidates.append((fallback_end, config.fallback_url))
    url = choose_newest(candidates)
    if url is None:
        raise FetchError(
            f"No IIEG zip matching {config.link_pattern.pattern!r} on {config.index_url} "
            "and no crime_source.fallback_url"
        )
    return url


# ---------------------------------------------------------------------------
# Reading the zip
# ---------------------------------------------------------------------------


def iieg_csv_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    """The single CSV member (anything else may sit beside it, but only one CSV)."""
    for name in archive.namelist():
        member = PurePosixPath(name.replace("\\", "/"))
        if member.is_absolute() or ".." in member.parts:
            raise ValueError(f"IIEG zip has an unsafe member path {name!r}")
    csvs = [
        info
        for info in archive.infolist()
        if not info.is_dir() and info.filename.lower().endswith(".csv")
    ]
    if len(csvs) != 1:
        raise ValueError(f"expected exactly one CSV in the IIEG zip, found {len(csvs)}")
    return csvs[0]


def _header(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> list[str]:
    with archive.open(member) as handle:
        first_line = handle.readline(1 << 16).decode("utf-8-sig")
    return [name.strip().strip('"').strip().lower() for name in first_line.split(",")]


def validate_iieg_zip(path: Path) -> None:
    """One CSV whose header has the IIEG columns; every member passes its CRC."""
    if not zipfile.is_zipfile(path):
        raise ValueError("IIEG download is not a zip archive")
    with zipfile.ZipFile(path) as archive:
        member = iieg_csv_member(archive)
        missing = [column for column in REQUIRED_COLUMNS if column not in _header(archive, member)]
        if missing:
            raise ValueError(f"IIEG CSV is missing columns {missing}")
        corrupt = archive.testzip()
        if corrupt is not None:
            raise ValueError(f"IIEG zip member {corrupt!r} fails its CRC check")


def sanity_bbox(profile: dict, margin: float = BBOX_MARGIN_DEG) -> dict[str, float]:
    """The profile bbox grown by ``margin`` degrees on every side."""
    bbox = profile.get("bbox") or {}
    try:
        return {
            "south": float(bbox["south"]) - margin,
            "west": float(bbox["west"]) - margin,
            "north": float(bbox["north"]) + margin,
            "east": float(bbox["east"]) + margin,
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"City profile bbox is incomplete: {exc}") from exc


def _end_of_month(month: date) -> date:
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def read_points(
    path: Path,
    *,
    zona: str,
    bbox: dict[str, float],
    source: str,
    latest_date: date,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Normalized points and the drop counts per reason (counts only, no rows).

    Dates after ``latest_date`` are dropped: one mistyped future date would move
    the engine's 12-month window off the real data.
    """
    with zipfile.ZipFile(path) as archive, archive.open(iieg_csv_member(archive)) as handle:
        frame = pd.read_csv(
            handle,
            encoding="utf-8-sig",
            dtype=str,
            na_values=["NA"],
            usecols=lambda name: str(name).strip().lower() in REQUIRED_COLUMNS,
        )
    frame.columns = [str(name).strip().lower() for name in frame.columns]
    counts = {"rows_read": len(frame)}

    frame = frame[frame["zona_geografica"].str.strip() == zona]
    counts["kept_zona"] = len(frame)
    when = pd.to_datetime(frame["fecha"].str.strip(), format="%Y-%m-%d", errors="coerce")
    valid_date = when.notna() & (when <= pd.Timestamp(latest_date))
    offense = frame["delito"].str.strip()
    valid_offense = offense.notna() & (offense != "")
    longitude = pd.to_numeric(frame["x"], errors="coerce")
    latitude = pd.to_numeric(frame["y"], errors="coerce")
    has_xy = longitude.notna() & latitude.notna()
    inside = latitude.between(bbox["south"], bbox["north"]) & longitude.between(
        bbox["west"], bbox["east"]
    )
    counts["dropped_invalid_date"] = int((~valid_date).sum())
    counts["dropped_no_offense"] = int((valid_date & ~valid_offense).sum())
    counts["dropped_no_coordinates"] = int((valid_date & valid_offense & ~has_xy).sum())
    counts["dropped_outside_bbox"] = int((valid_date & valid_offense & has_xy & ~inside).sum())
    keep = valid_date & valid_offense & has_xy & inside

    borough = frame["municipio"].str.strip().fillna("Sin municipio")
    points = pd.DataFrame(
        {
            "date": when[keep].dt.strftime("%Y-%m-%d"),
            "category": offense[keep],
            "offense": offense[keep],
            "borough": borough[keep],
            "latitude": latitude[keep],
            "longitude": longitude[keep],
            "source": source,
        },
        columns=OUTPUT_COLUMNS,
    )
    points = points.sort_values("date", kind="mergesort").reset_index(drop=True)
    counts["written"] = len(points)
    return points, counts


def _print_summary(points: pd.DataFrame, counts: dict[str, int]) -> None:
    print("IIEG rows: " + ", ".join(f"{key} {value:,}" for key, value in counts.items()))
    if points.empty:
        return
    print(f"Dates {points['date'].min()} to {points['date'].max()}")
    years = points["date"].str[:4].value_counts().sort_index()
    print("Points by year: " + ", ".join(f"{year} {n:,}" for year, n in years.items()))
    latest = pd.Timestamp(points["date"].max())
    recent_start = (latest - pd.DateOffset(months=12)).strftime("%Y-%m-%d")
    recent = points[points["date"] > recent_start]
    print(f"Points after {recent_start} (last 12 months of the file): {len(recent):,}")
    categories = recent["category"].value_counts()
    print("Last-12-month points by category:")
    for category, n in categories.items():
        print(f"  {category}: {n:,}")


def fetch_iieg_crime(city: str, *, force: bool = False, today: date | None = None) -> Path:
    """Download (cached), filter and write ``crime_points.csv`` for ``city``."""
    profile = load_city_profile(city)
    config = crime_source_config(profile, city)
    url = discover_zip_url(config)
    name = zip_basename(url)
    if not _SAFE_ZIP_NAME.fullmatch(name):
        raise FetchError(f"IIEG zip name {name!r} is not a plain file name")
    print(f"IIEG release: {url}")
    path = mx_common.cached_download(
        url,
        city_data_dir(DATA_RAW, city) / f"iieg_{name}",
        validate=validate_iieg_zip,
        force=force,
        allowed_final_url=is_iieg_url,
    )
    release_end = end_month_from_name(name)
    latest = _end_of_month(release_end) if release_end else (today or date.today())
    points, counts = read_points(
        path,
        zona=config.zona_geografica,
        bbox=sanity_bbox(profile),
        source=config.source,
        latest_date=latest,
    )
    if points.empty:
        raise FetchError(f"IIEG file {name} has no {config.zona_geografica} points in the bbox")
    target = city_data_dir(DATA_PROCESSED, city) / "crime_points.csv"
    write_csv_atomic(points, target)
    _print_summary(points, counts)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch IIEG Jalisco incident points (Fiscalía microdata) for a city."
    )
    parser.add_argument("--city", required=True, help="City profile id (e.g. guadalajara).")
    parser.add_argument("--force", action="store_true", help="Redownload the cached zip.")
    args = parser.parse_args()
    fetch_iieg_crime(args.city, force=args.force)


if __name__ == "__main__":
    main()
