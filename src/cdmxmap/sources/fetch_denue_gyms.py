"""Gyms from INEGI DENUE (Directorio Estadístico Nacional de Unidades Económicas).

For Mexican profile cities OSM gyms are sparse (Monterrey ~92, Guadalajara ~88)
while DENUE lists ~1,400 fitness centres per metro, so these cities read gyms
from DENUE instead. The profile's ``gyms_source`` block drives it::

    "gyms_source": {
      "type": "inegi_denue",
      "url": "https://www.inegi.org.mx/contenidos/masiva/denue/denue_00_71_csv.zip",
      "activity_codes": ["713943", "713944"],
      "state_codes": ["19"]
    }

The national sector-71 zip (~7 MB) is downloaded once into the gitignored raw cache
(``data/raw/mx_inegi_<basename>``), validated before it is promoted (zip member
paths, CRC, the ``conjunto_de_datos/denue_inegi_*.csv`` member and its header).
Rows are kept when ``codigo_act`` is one of ``activity_codes`` (SCIAN 713943
private / 713944 public "centros de acondicionamiento físico"), ``cve_ent`` is one
of ``state_codes`` and the WGS84 ``latitud``/``longitud`` fall inside the profile
bbox. Output: ``gyms.csv`` with ``name,latitude,longitude,source`` and
``source="inegi_denue"``. Licence: INEGI Términos de Libre Uso (attribution).
"""

from __future__ import annotations

import argparse
import csv
import io
import math
import os
import re
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cdmxmap.errors import ConfigError, FetchError

from . import mx_common
from .io import DATA_PROCESSED, city_data_dir, load_city_profile, write_csv

GYMS_SOURCE_KEY = "gyms_source"
GYMS_SOURCE_TYPE = "inegi_denue"
SOURCE_LABEL = "inegi_denue"
OUTPUT_FIELDS = ["name", "latitude", "longitude", "source"]
MIN_ROWS = 20
DENUE_ENCODING = "latin-1"
REQUIRED_COLUMNS = ("id", "nom_estab", "codigo_act", "cve_ent", "latitud", "longitud")
UNNAMED_GYM = "Unnamed gym"

_CSV_MEMBER = re.compile(r"conjunto_de_datos/denue_inegi_[^/]*\.csv")
_METADATA_MEMBER = "metadatos/metadatos_denue.txt"
_ACTIVITY_CODE = re.compile(r"\d{6}")
_STATE_CODE = re.compile(r"\d{2}")
# Acronyms that stay uppercase in gym names (public institutions, sports formats).
_ACRONYMS = frozenset(
    {"CTM", "DIF", "IMSS", "IPN", "ISSSTE", "ITESM", "MMA", "SNTE", "TRX", "UAG", "UANL"}
    | {"UDG", "UFC", "YMCA"}
)
_WORD = re.compile(r"[^\W\d_]+")
_POSSESSIVE = re.compile(r"(?<=[^\W\d_])'S\b")


@dataclass(frozen=True)
class GymsSource:
    url: str
    activity_codes: frozenset[str]
    state_codes: frozenset[str]


def _code_list(value: object, pattern: re.Pattern[str], *, where: str) -> frozenset[str]:
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{where} must be a non-empty list of codes")
    codes = [str(item).strip() for item in value]
    bad = [code for code in codes if not pattern.fullmatch(code)]
    if bad:
        raise ConfigError(f"{where} has invalid codes {bad}")
    return frozenset(codes)


def parse_gyms_source(profile: Mapping[str, object], city: str) -> GymsSource:
    where = f"City profile '{city}' {GYMS_SOURCE_KEY}"
    block = profile.get(GYMS_SOURCE_KEY)
    if not isinstance(block, dict):
        raise ConfigError(f"{where} must be an object (fetch_denue_gyms needs it)")
    if block.get("type") != GYMS_SOURCE_TYPE:
        raise ConfigError(f"{where}.type must be {GYMS_SOURCE_TYPE!r}, got {block.get('type')!r}")
    url = block.get("url")
    if not isinstance(url, str) or not url.startswith("https://") or not url.endswith(".zip"):
        raise ConfigError(f"{where}.url must be an https:// URL of a .zip file")
    return GymsSource(
        url=url,
        activity_codes=_code_list(
            block.get("activity_codes"), _ACTIVITY_CODE, where=f"{where}.activity_codes"
        ),
        state_codes=_code_list(block.get("state_codes"), _STATE_CODE, where=f"{where}.state_codes"),
    )


def _bbox_from_profile(profile: Mapping[str, object], city: str) -> dict[str, float]:
    bbox = profile.get("bbox")
    keys = ("south", "west", "north", "east")
    if not isinstance(bbox, dict) or not all(key in bbox for key in keys):
        raise ConfigError(f"City profile '{city}' is missing bbox keys {list(keys)}")
    return {key: float(bbox[key]) for key in keys}


# ---------------------------------------------------------------------------
# Download + validation
# ---------------------------------------------------------------------------


def denue_cache_path(url: str) -> Path:
    """Shared national cache: ``DATA_RAW / f"mx_inegi_{basename}"``."""
    return mx_common.DATA_RAW / f"mx_inegi_{os.path.basename(url)}"


def _csv_member(archive: zipfile.ZipFile) -> str:
    names = archive.namelist()
    for name in names:
        member = PurePosixPath(name)
        if member.is_absolute() or ".." in member.parts or "\\" in name:
            raise ValueError(f"DENUE zip has an unsafe member path {name!r}")
    members = [name for name in names if _CSV_MEMBER.fullmatch(name)]
    if len(members) != 1:
        raise ValueError(
            f"DENUE zip must hold exactly one conjunto_de_datos/denue_inegi_*.csv, found {members}"
        )
    return members[0]


def _open_csv(archive: zipfile.ZipFile, member: str) -> io.TextIOWrapper:
    return io.TextIOWrapper(archive.open(member), encoding=DENUE_ENCODING, newline="")


def validate_denue_zip(path: Path) -> None:
    """Reject anything but a DENUE bulk-download zip with the columns we read."""
    if not zipfile.is_zipfile(path):
        raise ValueError("DENUE download is not a zip archive")
    with zipfile.ZipFile(path) as archive:
        member = _csv_member(archive)
        corrupt = archive.testzip()
        if corrupt is not None:
            raise ValueError(f"DENUE zip member {corrupt!r} fails its CRC check")
        with _open_csv(archive, member) as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
            first_row = next(reader, None)
    columns = {column.strip().lower() for column in header}
    missing = [column for column in REQUIRED_COLUMNS if column not in columns]
    if missing:
        raise ValueError(f"DENUE CSV {member} is missing columns {missing}")
    if first_row is None:
        raise ValueError(f"DENUE CSV {member} has no data rows")


def fetch_denue_zip(url: str, *, force: bool = False) -> Path:
    return mx_common.cached_download(
        url, denue_cache_path(url), validate=validate_denue_zip, timeout=300, force=force
    )


def denue_edition(path: Path) -> str:
    """The ``Title:`` line of the zip's metadata file (e.g. "... (DENUE) 05_2026")."""
    with zipfile.ZipFile(path) as archive:
        if _METADATA_MEMBER not in archive.namelist():
            return "unknown edition"
        text = archive.read(_METADATA_MEMBER).decode("utf-8-sig", errors="replace")
    for line in text.splitlines():
        if line.startswith("Title:"):
            return line.removeprefix("Title:").strip()
    return "unknown edition"


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def format_gym_name(raw: str) -> str:
    """All-caps DENUE ``nom_estab`` -> display name.

    ``spanish_title_case`` does the work (``"GIMNASIO MUNICIPAL DE APODACA"`` ->
    ``"Gimnasio Municipal de Apodaca"``); possessives stay lowercase
    (``"GOLD'S GYM"`` -> ``"Gold's Gym"``) and a few acronyms stay uppercase
    (``"YMCA"``, ``"UANL"``). Mixed-case input is only whitespace-collapsed.
    """
    collapsed = " ".join(str(raw or "").split())
    if not collapsed:
        return UNNAMED_GYM
    if any(char.islower() for char in collapsed):
        return collapsed
    titled = mx_common.spanish_title_case(collapsed)
    titled = _POSSESSIVE.sub("'s", titled)
    return _WORD.sub(
        lambda m: m.group(0).upper() if m.group(0).upper() in _ACRONYMS else m.group(0), titled
    )


def _coordinate(value: str | None) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def read_denue_gyms(
    path: Path, source: GymsSource, bbox: Mapping[str, float]
) -> tuple[list[dict], Counter[str]]:
    """Filtered, de-duplicated gym rows from the cached DENUE zip, plus filter stats."""
    stats: Counter[str] = Counter()
    rows: list[dict] = []
    seen: set[tuple[str, float, float]] = set()
    with zipfile.ZipFile(path) as archive, _open_csv(archive, _csv_member(archive)) as handle:
        reader = csv.DictReader(handle)
        reader.fieldnames = [name.strip().lower() for name in reader.fieldnames or []]
        missing = [column for column in REQUIRED_COLUMNS if column not in reader.fieldnames]
        if missing:
            raise FetchError(f"DENUE CSV in {path.name} is missing columns {missing}")
        for record in reader:
            stats["read"] += 1
            if str(record.get("codigo_act") or "").strip() not in source.activity_codes:
                continue
            stats["activity"] += 1
            if str(record.get("cve_ent") or "").strip().zfill(2) not in source.state_codes:
                continue
            stats["state"] += 1
            lat = _coordinate(record.get("latitud"))
            lon = _coordinate(record.get("longitud"))
            if lat is None or lon is None:
                stats["bad_coordinates"] += 1
                continue
            if not (bbox["south"] <= lat <= bbox["north"] and bbox["west"] <= lon <= bbox["east"]):
                stats["outside_bbox"] += 1
                continue
            name = format_gym_name(str(record.get("nom_estab") or ""))
            key = (name, lat, lon)
            if key in seen:
                stats["duplicates"] += 1
                continue
            seen.add(key)
            rows.append({"name": name, "latitude": lat, "longitude": lon, "source": SOURCE_LABEL})
            stats[f"codigo_act {str(record.get('codigo_act')).strip()}"] += 1
    rows.sort(key=lambda row: (row["name"].casefold(), row["latitude"], row["longitude"]))
    return rows, stats


def fetch_denue_gyms(
    city: str, profile: Mapping[str, object], *, target: Path, force: bool = False
) -> list[dict]:
    source = parse_gyms_source(profile, city)
    bbox = _bbox_from_profile(profile, city)
    path = fetch_denue_zip(source.url, force=force)
    print(f"DENUE edition: {denue_edition(path)}")
    rows, stats = read_denue_gyms(path, source, bbox)
    print(
        f"DENUE rows read {stats['read']:,}; activity {sorted(source.activity_codes)} "
        f"{stats['activity']:,}; state {sorted(source.state_codes)} {stats['state']:,}; "
        f"outside bbox {stats['outside_bbox']:,}; bad coordinates {stats['bad_coordinates']:,}; "
        f"exact duplicates {stats['duplicates']:,}"
    )
    by_code = ", ".join(
        f"{key.removeprefix('codigo_act ')}: {count:,}"
        for key, count in sorted(stats.items())
        if key.startswith("codigo_act ")
    )
    print(f"Kept {len(rows):,} gyms for {city} ({by_code or 'none'})")
    if len(rows) < MIN_ROWS:
        raise FetchError(
            f"Only {len(rows)} DENUE gyms for {city} (need at least {MIN_ROWS}); "
            "check gyms_source codes and the profile bbox"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    write_csv(target, rows, OUTPUT_FIELDS)
    return rows


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Fetch gyms from INEGI DENUE for a Mexican city profile (gyms_source)."
    )
    parser.add_argument("--city", required=True, help="City profile id with gyms_source.")
    parser.add_argument(
        "--force", action="store_true", help="Re-download the DENUE zip even if it is cached."
    )
    args = parser.parse_args(argv)
    profile = load_city_profile(args.city)
    target = city_data_dir(DATA_PROCESSED, args.city) / "gyms.csv"
    fetch_denue_gyms(args.city, profile, target=target, force=args.force)


if __name__ == "__main__":
    main()
