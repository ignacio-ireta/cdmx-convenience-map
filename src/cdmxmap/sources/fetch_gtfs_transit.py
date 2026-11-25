"""Build ``transit_stops.csv`` from a GTFS feed, driven by the city profile.

Used by Guadalajara (SETRAN Jalisco GTFS, Mobility Database mdb-3632). Everything
city-specific lives in the profile's ``transit_source`` block (``type == "gtfs"``):

- ``url``: the feed zip. It is downloaded once, validated, and cached atomically
  under ``data/raw/gtfs/`` (gitignored); its SHA-256 is printed on every run.
- ``source``: the value written to the ``source`` column of every row.
- ``exclude_agencies``: agency ids whose routes are ignored (out-of-area services).
- ``core_merge_m``: single-linkage radius that merges the platforms (one stop_id per
  direction) of a core station into one point, per system and line.
- ``subtract_match_m`` (optional, default 300): radius of the same-name test used by
  ``subtract_line``.
- ``rules``: ordered route classifiers; the first rule that matches a route wins.

Rule keys:

- Match: ``agency`` (list of ``agency_id``), ``route_type`` (list), ``route_desc``
  (regex, searched). Every key present must match.
- ``system``: a code declared in the profile's ``transit_systems``.
- Line id: ``line`` (fixed), or ``line_from_short_name`` (regex on the stripped
  ``route_short_name``) formatted with ``line_format`` (``"{0}"`` by default); without
  either, the stripped ``route_short_name`` (``route_id`` when it is empty).
- Core systems (``group == "core"``): every stop a matching route serves is a station
  of (system, line) (``station_routes: true`` states this explicitly).
  ``subtract_line`` drops the stations this line shares with another line of the same
  system, matched by stop_id or by the same normalized name within ``subtract_match_m``.
  ``corridor_only`` routes add no stations of their own: their stops that are stations
  of (system, line) (same stop_id, or same name within ``core_merge_m``) count for the
  line, and every other stop becomes a surface stop of ``offcorridor_system`` with line
  ``offcorridor_line_prefix`` + the route's short name.
- Surface systems: every stop a matching route serves is a stop of the system.

Output rows (spec §3): core systems get one row per (station, line), placed at the
centroid of the merged platforms; surface systems get one row per stop_id whose
``line`` is the sorted route short names joined with ``"|"``, and stops of one system
with the same normalized name and the same coordinates at 5 decimals are collapsed.
``stop_times.txt`` (hundreds of MB) is streamed from the zip with ``csv``; it is
never extracted or loaded whole.

This module also holds the small output helpers shared with ``fetch_nl_transit``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import math
import os
import re
import sys
import unicodedata
import uuid
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

from cdmxmap.errors import CdmxmapError, ConfigError, FetchError

from . import mx_common
from .io import DATA_PROCESSED, DATA_RAW, city_data_dir, load_city_profile

TRANSIT_STOP_FIELDS = (
    "id",
    "name",
    "system",
    "line",
    "hierarchy",
    "latitude",
    "longitude",
    "source",
)
GTFS_CACHE_DIR = DATA_RAW / "gtfs"
DEFAULT_CORE_MERGE_M = 200.0
DEFAULT_SUBTRACT_MATCH_M = 300.0
EARTH_RADIUS_M = 6_371_000.0
COORD_DECIMALS = 6
SURFACE_COLLAPSE_DECIMALS = 5
LINE_SEPARATOR = "|"

# Tables (and their columns) every usable feed must carry.
REQUIRED_TABLES: dict[str, tuple[str, ...]] = {
    "routes.txt": ("route_id",),
    "trips.txt": ("route_id", "trip_id"),
    "stops.txt": ("stop_id", "stop_name", "stop_lat", "stop_lon"),
    "stop_times.txt": ("trip_id", "stop_id"),
}
RULE_KEYS = frozenset(
    {
        "system",
        "agency",
        "route_type",
        "route_desc",
        "line",
        "line_from_short_name",
        "line_format",
        "station_routes",
        "subtract_line",
        "corridor_only",
        "offcorridor_system",
        "offcorridor_line_prefix",
    }
)
_TRAILING_LINE_TAG = re.compile(r"\s+L\d+$")


# ---------------------------------------------------------------------------
# Shared output helpers (also used by fetch_nl_transit)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SystemInfo:
    """One declared transit system of the profile, in declaration order."""

    code: str
    label: str
    group: str
    order: int


def profile_systems(profile: Mapping[str, Any]) -> dict[str, SystemInfo]:
    """``{code: SystemInfo}`` from the profile's ``transit_systems`` (codes upper-cased)."""
    specs = profile.get("transit_systems") or []
    systems: dict[str, SystemInfo] = {}
    for order, spec in enumerate(specs):
        code = str(spec.get("code") or "").strip().upper()
        if not code:
            raise ConfigError(f"transit_systems[{order}] has no code")
        if code in systems:
            raise ConfigError(f"transit_systems declares {code} twice")
        group = str(spec.get("group") or "surface")
        if group not in {"core", "surface"}:
            raise ConfigError(f"transit system {code} has group {group!r}; use core or surface")
        label = str(spec.get("label") or "").strip() or code
        systems[code] = SystemInfo(code=code, label=label, group=group, order=order)
    if not systems:
        raise ConfigError("The city profile declares no transit_systems")
    return systems


def profile_bbox(profile: Mapping[str, Any]) -> dict[str, float]:
    bbox = profile.get("bbox") or {}
    keys = ("south", "west", "north", "east")
    if not all(key in bbox for key in keys):
        raise ConfigError(f"The city profile bbox needs {list(keys)}")
    return {key: float(bbox[key]) for key in keys}


def transit_source_config(profile: Mapping[str, Any], expected_type: str) -> dict[str, Any]:
    config = profile.get("transit_source")
    if not isinstance(config, dict):
        raise ConfigError("The city profile has no transit_source block")
    if config.get("type") != expected_type:
        raise ConfigError(
            f"transit_source.type is {config.get('type')!r}; this fetcher reads {expected_type!r}"
        )
    return config


def in_bbox(latitude: float, longitude: float, bbox: Mapping[str, float]) -> bool:
    return bbox["south"] <= latitude <= bbox["north"] and bbox["west"] <= longitude <= bbox["east"]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def normalize_name(name: str) -> str:
    """Accent-, case- and punctuation-insensitive form used to compare stop names."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def id_slug(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", folded).strip("_") or "x"


def natural_key(text: str) -> tuple[tuple[tuple[int, int | str], ...], str]:
    """Sort key that orders embedded numbers numerically ("R2" < "R10")."""
    parts: list[tuple[int, int | str]] = []
    for part in re.split(r"(\d+)", text.casefold()):
        if not part:
            continue
        parts.append((0, int(part)) if part.isdigit() else (1, part))
    return tuple(parts), text


def join_lines(refs: Iterable[str]) -> str:
    """Sorted unique route refs joined with ``"|"`` (a ``"|"`` inside a ref becomes ``"/"``)."""
    cleaned = {
        str(ref).strip().replace(LINE_SEPARATOR, "/") for ref in refs if ref and str(ref).strip()
    }
    return LINE_SEPARATOR.join(sorted(cleaned, key=natural_key))


def finalize_rows(
    rows: Sequence[Mapping[str, Any]], systems: Mapping[str, SystemInfo]
) -> list[dict]:
    """Round coordinates, sort deterministically and assign unique ids.

    A row may carry a private ``_key`` (a stable source id such as a stop_id); its id
    is then ``"<SYSTEM>-<_key>"``, otherwise ``"<SYSTEM>-<n>"`` numbered in sorted
    order. Clashing ids get ``-2``, ``-3``... suffixes. Only the spec columns survive.
    """
    prepared: list[dict] = []
    for row in rows:
        system = str(row["system"])
        if system not in systems:
            raise FetchError(f"Row for undeclared transit system {system!r}: {row}")
        item = dict(row)
        item["latitude"] = round(float(row["latitude"]), COORD_DECIMALS)
        item["longitude"] = round(float(row["longitude"]), COORD_DECIMALS)
        item["line"] = str(row.get("line") or "")
        item["name"] = str(row.get("name") or "")
        prepared.append(item)
    prepared.sort(
        key=lambda r: (
            systems[r["system"]].order,
            natural_key(r["line"]),
            r["name"].casefold(),
            r["name"],
            r["latitude"],
            r["longitude"],
            str(r.get("_key") or ""),
        )
    )
    seen: set[str] = set()
    sequence: Counter[str] = Counter()
    final: list[dict] = []
    for item in prepared:
        system = item["system"]
        key = str(item.get("_key") or "")
        if key:
            base = f"{system}-{key}"
        else:
            sequence[system] += 1
            base = f"{system}-{sequence[system]}"
        row_id, suffix = base, 1
        while row_id in seen:
            suffix += 1
            row_id = f"{base}-{suffix}"
        seen.add(row_id)
        item["id"] = row_id
        final.append({name: item.get(name, "") for name in TRANSIT_STOP_FIELDS})
    return final


def check_declared_systems(rows: Iterable[Mapping[str, Any]], systems: Iterable[str]) -> None:
    """Fail loudly when a declared system ended up with no rows (spec §3)."""
    counts = Counter(str(row["system"]) for row in rows)
    empty = [code for code in systems if counts[code] == 0]
    if empty:
        raise FetchError(f"Declared transit systems with 0 rows: {', '.join(empty)}")


def print_counts(rows: Sequence[Mapping[str, Any]], systems: Mapping[str, SystemInfo]) -> None:
    by_system: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_system[str(row["system"])].append(row)
    print(f"Transit rows per system ({len(rows)} total):")
    for code, info in sorted(systems.items(), key=lambda item: item[1].order):
        system_rows = by_system.get(code, [])
        lines = [str(row["line"]) for row in system_rows]
        if info.group == "core":
            per_line = Counter(lines)
            detail = ", ".join(
                f"{line or '(none)'} {per_line[line]}" for line in sorted(per_line, key=natural_key)
            )
            print(f"  {code} [core] {len(system_rows)}: {detail}")
        else:
            refs = {ref for line in lines for ref in line.split(LINE_SEPARATOR) if ref}
            multi = sum(1 for line in lines if LINE_SEPARATOR in line)
            no_line = sum(1 for line in lines if not line)
            print(
                f"  {code} [surface] {len(system_rows)} stops, {len(refs)} route refs, "
                f"{multi} multi-route stops, {no_line} without a route"
            )


def write_transit_stops(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """Write the CSV atomically (temp file in the same directory, then ``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.stem}.{uuid.uuid4().hex[:12]}.part{path.suffix}")
    try:
        with tmp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(TRANSIT_STOP_FIELDS))
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name, "") for name in TRANSIT_STOP_FIELDS})
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)
    print(f"Wrote {path}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_cli(action: Callable[[], object]) -> None:
    """Run a fetcher; a pipeline error prints one ``error:`` line and exits non-zero."""
    try:
        action()
    except CdmxmapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(exc.exit_code) from None


# ---------------------------------------------------------------------------
# GTFS rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Stop:
    stop_id: str
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class GtfsRule:
    """One route classifier from ``transit_source.rules`` (see the module docstring)."""

    index: int
    system: str
    core: bool
    agencies: frozenset[str] | None = None
    route_types: frozenset[str] | None = None
    route_desc: re.Pattern[str] | None = None
    line: str | None = None
    line_pattern: re.Pattern[str] | None = None
    line_format: str = "{0}"
    subtract_line: str | None = None
    corridor_only: bool = False
    offcorridor_system: str | None = None
    offcorridor_line_prefix: str = ""

    def matches(self, route: Mapping[str, str]) -> bool:
        if self.agencies is not None and route.get("agency_id", "").strip() not in self.agencies:
            return False
        if (
            self.route_types is not None
            and route.get("route_type", "").strip() not in self.route_types
        ):
            return False
        return self.route_desc is None or bool(self.route_desc.search(route.get("route_desc", "")))

    def route_line(self, route: Mapping[str, str]) -> str:
        if self.line:
            return self.line
        ref = route_ref(route)
        if self.line_pattern is not None:
            match = self.line_pattern.search(ref)
            if match:
                groups = match.groups() or (match.group(0),)
                return self.line_format.format(*groups)
        return ref


def route_ref(route: Mapping[str, str]) -> str:
    """The route's public ref: stripped short name, else its route_id."""
    return (route.get("route_short_name") or "").strip() or route["route_id"].strip()


def _string_set(value: object, *, key: str, index: int) -> frozenset[str] | None:
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, list):
        raise ConfigError(f"transit_source.rules[{index}].{key} must be a list of strings")
    return frozenset(str(item).strip() for item in value)


def _regex(value: object, *, key: str, index: int) -> re.Pattern[str] | None:
    if value is None:
        return None
    try:
        return re.compile(str(value))
    except re.error as exc:
        raise ConfigError(
            f"transit_source.rules[{index}].{key} is not a valid regex: {exc}"
        ) from exc


def parse_rules(config: Mapping[str, Any], systems: Mapping[str, SystemInfo]) -> list[GtfsRule]:
    raw_rules = config.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ConfigError("transit_source.rules must be a non-empty list")
    rules: list[GtfsRule] = []
    for index, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            raise ConfigError(f"transit_source.rules[{index}] must be an object")
        unknown = sorted(set(raw) - RULE_KEYS)
        if unknown:
            raise ConfigError(f"transit_source.rules[{index}] has unknown keys {unknown}")
        system = str(raw.get("system") or "").strip().upper()
        if system not in systems:
            raise ConfigError(
                f"transit_source.rules[{index}].system {system!r} is not a declared transit system"
            )
        core = systems[system].group == "core"
        corridor_only = bool(raw.get("corridor_only", False))
        line = str(raw["line"]).strip() if raw.get("line") is not None else None
        subtract_line = str(raw["subtract_line"]).strip() if raw.get("subtract_line") else None
        offcorridor = str(raw.get("offcorridor_system") or "").strip().upper() or None
        if (corridor_only or subtract_line or raw.get("station_routes")) and not core:
            raise ConfigError(
                f"transit_source.rules[{index}]: station_routes/subtract_line/corridor_only "
                f"need a core system, not {system}"
            )
        if (subtract_line or corridor_only) and not line:
            raise ConfigError(f"transit_source.rules[{index}] needs a fixed line")
        if corridor_only:
            if offcorridor is None or offcorridor not in systems:
                raise ConfigError(
                    f"transit_source.rules[{index}].offcorridor_system must be a declared system"
                )
            if systems[offcorridor].group != "surface":
                raise ConfigError(
                    f"transit_source.rules[{index}].offcorridor_system must be a surface system"
                )
        rules.append(
            GtfsRule(
                index=index,
                system=system,
                core=core,
                agencies=_string_set(raw.get("agency"), key="agency", index=index),
                route_types=_string_set(raw.get("route_type"), key="route_type", index=index),
                route_desc=_regex(raw.get("route_desc"), key="route_desc", index=index),
                line=line,
                line_pattern=_regex(
                    raw.get("line_from_short_name"), key="line_from_short_name", index=index
                ),
                line_format=str(raw.get("line_format") or "{0}"),
                subtract_line=subtract_line,
                corridor_only=corridor_only,
                offcorridor_system=offcorridor if corridor_only else None,
                offcorridor_line_prefix=str(raw.get("offcorridor_line_prefix") or ""),
            )
        )
    return rules


# ---------------------------------------------------------------------------
# GTFS reading (streamed from the zip)
# ---------------------------------------------------------------------------


def _member_is_safe(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and "\\" not in name


def _read_header(zf: zipfile.ZipFile, table: str) -> list[str]:
    with zf.open(table) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
        header = next(csv.reader(text), [])
    return [column.strip() for column in header]


def validate_gtfs_zip(path: Path) -> None:
    """Raise ``FetchError`` unless ``path`` is a zip holding the GTFS tables we need."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            unsafe = [name for name in names if not _member_is_safe(name)]
            if unsafe:
                raise FetchError(f"GTFS zip has unsafe member names: {unsafe[:5]}")
            for table, columns in REQUIRED_TABLES.items():
                if table not in names:
                    raise FetchError(f"GTFS zip has no {table}")
                header = _read_header(zf, table)
                missing = [column for column in columns if column not in header]
                if missing:
                    raise FetchError(f"GTFS {table} lacks columns {missing}")
    except zipfile.BadZipFile as exc:
        raise FetchError(f"{path} is not a zip file: {exc}") from exc


def iter_table(zf: zipfile.ZipFile, table: str) -> Iterator[dict[str, str]]:
    """Stream one GTFS table as dicts of stripped-header -> raw value."""
    with zf.open(table) as raw, io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
        reader = csv.reader(text)
        header = [column.strip() for column in next(reader, [])]
        for values in reader:
            if values:
                yield dict(zip(header, values))


def load_routes(zf: zipfile.ZipFile) -> dict[str, dict[str, str]]:
    routes: dict[str, dict[str, str]] = {}
    for row in iter_table(zf, "routes.txt"):
        route_id = row.get("route_id", "")
        if route_id:
            routes[route_id] = row
    return routes


def load_stops(zf: zipfile.ZipFile) -> dict[str, Stop]:
    stops: dict[str, Stop] = {}
    bad = 0
    for row in iter_table(zf, "stops.txt"):
        stop_id = row.get("stop_id", "")
        try:
            lat, lon = float(row.get("stop_lat", "")), float(row.get("stop_lon", ""))
        except ValueError:
            bad += 1
            continue
        if not stop_id or not (math.isfinite(lat) and math.isfinite(lon)):
            bad += 1
            continue
        stops[stop_id] = Stop(stop_id, (row.get("stop_name") or "").strip(), lat, lon)
    if bad:
        print(f"Skipped {bad} GTFS stops without an id or valid coordinates")
    return stops


def load_route_stops(zf: zipfile.ZipFile, route_ids: Iterable[str]) -> dict[str, set[str]]:
    """``{route_id: {stop_id}}`` for the given routes, streaming ``stop_times.txt``."""
    wanted = set(route_ids)
    trip_route: dict[str, str] = {}
    for row in iter_table(zf, "trips.txt"):
        if row.get("route_id") in wanted:
            trip_route[row["trip_id"]] = row["route_id"]
    route_stops: dict[str, set[str]] = defaultdict(set)
    with (
        zf.open("stop_times.txt") as raw,
        io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text,
    ):
        reader = csv.reader(text)
        header = [column.strip() for column in next(reader, [])]
        trip_index, stop_index = header.index("trip_id"), header.index("stop_id")
        width = max(trip_index, stop_index)
        rows = 0
        for values in reader:
            rows += 1
            if len(values) <= width:
                continue
            route_id = trip_route.get(values[trip_index])
            if route_id is not None:
                route_stops[route_id].add(values[stop_index])
    print(f"Streamed {rows:,} stop_times rows for {len(wanted)} classified routes")
    return dict(route_stops)


def calendar_range(zf: zipfile.ZipFile) -> tuple[str, str] | None:
    """(first, last) service date as YYYYMMDD from calendar.txt / calendar_dates.txt."""
    dates: list[str] = []
    names = set(zf.namelist())
    if "calendar.txt" in names:
        for row in iter_table(zf, "calendar.txt"):
            dates.extend(row.get(key, "") for key in ("start_date", "end_date"))
    if "calendar_dates.txt" in names:
        for row in iter_table(zf, "calendar_dates.txt"):
            if row.get("exception_type", "").strip() == "1":
                dates.append(row.get("date", ""))
    valid = sorted(value.strip() for value in dates if re.fullmatch(r"\d{8}", value.strip()))
    return (valid[0], valid[-1]) if valid else None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@dataclass
class GtfsBuild:
    rows: list[dict] = field(default_factory=list)
    unmatched_routes: list[str] = field(default_factory=list)
    excluded_routes: int = 0


def classify_routes(
    routes: Mapping[str, Mapping[str, str]],
    rules: Sequence[GtfsRule],
    exclude_agencies: Iterable[str],
) -> tuple[dict[str, GtfsRule], list[str], int]:
    """First matching rule per route; returns (assigned, unmatched ids, excluded count)."""
    excluded_agencies = {str(agency).strip() for agency in exclude_agencies}
    assigned: dict[str, GtfsRule] = {}
    unmatched: list[str] = []
    excluded = 0
    for route_id in sorted(routes):
        route = routes[route_id]
        if route.get("agency_id", "").strip() in excluded_agencies:
            excluded += 1
            continue
        rule = next((rule for rule in rules if rule.matches(route)), None)
        if rule is None:
            unmatched.append(route_id)
        else:
            assigned[route_id] = rule
    return assigned, unmatched, excluded


def _same_station(
    stop: Stop, station_ids: Iterable[str], stops: Mapping[str, Stop], radius_m: float
) -> bool:
    """``stop`` is one of ``station_ids`` or shares a normalized name with one within radius."""
    ids = station_ids if isinstance(station_ids, set | frozenset) else set(station_ids)
    if stop.stop_id in ids:
        return True
    name = normalize_name(stop.name)
    if not name:
        return False
    for station_id in ids:
        station = stops[station_id]
        if (
            normalize_name(station.name) == name
            and haversine_m(stop.lat, stop.lon, station.lat, station.lon) <= radius_m
        ):
            return True
    return False


def single_linkage(points: Sequence[Stop], radius_m: float) -> list[list[Stop]]:
    """Clusters where every point is within ``radius_m`` of some other member (chained)."""
    ordered = sorted(points, key=lambda stop: stop.stop_id)
    parent = list(range(len(ordered)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i, first in enumerate(ordered):
        for j in range(i + 1, len(ordered)):
            second = ordered[j]
            if haversine_m(first.lat, first.lon, second.lat, second.lon) <= radius_m:
                root_i, root_j = find(i), find(j)
                if root_i != root_j:
                    parent[max(root_i, root_j)] = min(root_i, root_j)
    groups: dict[int, list[Stop]] = defaultdict(list)
    for index, stop in enumerate(ordered):
        groups[find(index)].append(stop)
    return [groups[root] for root in sorted(groups)]


def best_station_name(members: Sequence[Stop]) -> str:
    """Most common member name (trailing " L<n>" tags dropped); ties go to the lowest stop_id."""
    counts: Counter[str] = Counter()
    first_seen: dict[str, str] = {}
    for stop in sorted(members, key=lambda item: item.stop_id):
        name = _TRAILING_LINE_TAG.sub("", stop.name).strip() or stop.name.strip()
        if not name:
            continue
        counts[name] += 1
        first_seen.setdefault(name, stop.stop_id)
    if not counts:
        return "Unnamed station"
    return min(counts, key=lambda name: (-counts[name], first_seen[name]))


def build_gtfs_rows(
    routes: Mapping[str, Mapping[str, str]],
    stops: Mapping[str, Stop],
    route_stops: Mapping[str, set[str]],
    rules: Sequence[GtfsRule],
    systems: Mapping[str, SystemInfo],
    bbox: Mapping[str, float],
    *,
    exclude_agencies: Iterable[str] = (),
    core_merge_m: float = DEFAULT_CORE_MERGE_M,
    subtract_match_m: float = DEFAULT_SUBTRACT_MATCH_M,
    source: str,
) -> GtfsBuild:
    """Classify routes and turn their stops into transit_stops rows (not yet finalized)."""
    assigned, unmatched, excluded = classify_routes(routes, rules, exclude_agencies)
    result = GtfsBuild(unmatched_routes=unmatched, excluded_routes=excluded)

    def served(route_id: str) -> set[str]:
        return {stop_id for stop_id in route_stops.get(route_id, ()) if stop_id in stops}

    # Pass 1: station sets per core (system, line), from every stop of the station
    # routes (not bbox-clipped, so line-vs-line matching sees whole lines).
    stations: dict[tuple[str, str], set[str]] = defaultdict(set)
    subtractions: dict[tuple[str, str], str] = {}
    for route_id, rule in assigned.items():
        if not rule.core or rule.corridor_only:
            continue
        key = (rule.system, rule.route_line(routes[route_id]))
        stations[key] |= served(route_id)
        if rule.subtract_line:
            subtractions[key] = rule.subtract_line
    snapshot = {key: frozenset(ids) for key, ids in stations.items()}
    for key, other_line in sorted(subtractions.items()):
        other = snapshot.get((key[0], other_line), frozenset())
        kept = {
            stop_id
            for stop_id in stations[key]
            if not _same_station(stops[stop_id], other, stops, subtract_match_m)
        }
        print(
            f"{key[0]} {key[1]}: {len(stations[key]) - len(kept)} of {len(stations[key])} "
            f"stops are {other_line} stations and were subtracted"
        )
        stations[key] = kept

    # Pass 2: members inside the bbox.
    core_members: dict[tuple[str, str], set[str]] = defaultdict(set)
    surface_refs: dict[tuple[str, str], set[str]] = defaultdict(set)
    for route_id, rule in assigned.items():
        route = routes[route_id]
        stop_ids = {
            stop_id
            for stop_id in served(route_id)
            if in_bbox(stops[stop_id].lat, stops[stop_id].lon, bbox)
        }
        if rule.core:
            key = (rule.system, rule.route_line(route))
            if rule.corridor_only:
                line_set = stations.get(key, set())
                on_corridor = {
                    stop_id
                    for stop_id in stop_ids
                    if _same_station(stops[stop_id], line_set, stops, core_merge_m)
                }
                core_members[key] |= on_corridor
                assert rule.offcorridor_system is not None  # enforced by parse_rules
                ref = rule.offcorridor_line_prefix + route_ref(route)
                for stop_id in stop_ids - on_corridor:
                    surface_refs[(rule.offcorridor_system, stop_id)].add(ref)
            else:
                core_members[key] |= stop_ids & stations[key]
        else:
            ref = route_ref(route)
            for stop_id in stop_ids:
                surface_refs[(rule.system, stop_id)].add(ref)

    # Core: one row per merged station per line.
    for (system, line), member_ids in sorted(core_members.items()):
        label = systems[system].label
        for cluster in single_linkage([stops[stop_id] for stop_id in member_ids], core_merge_m):
            name = best_station_name(cluster)
            result.rows.append(
                {
                    "system": system,
                    "line": line,
                    "name": f"{label} {line} · {name}",
                    "hierarchy": "station",
                    "latitude": sum(stop.lat for stop in cluster) / len(cluster),
                    "longitude": sum(stop.lon for stop in cluster) / len(cluster),
                    "source": source,
                    "_key": f"{id_slug(line)}-{id_slug(name)}",
                }
            )

    # Surface: one row per stop_id, collapsing same-name same-position duplicates.
    collapsed: dict[tuple[str, str, float, float], dict[str, Any]] = {}
    for (system, stop_id), refs in sorted(surface_refs.items()):
        stop = stops[stop_id]
        collapse_key = (
            system,
            normalize_name(stop.name),
            round(stop.lat, SURFACE_COLLAPSE_DECIMALS),
            round(stop.lon, SURFACE_COLLAPSE_DECIMALS),
        )
        entry = collapsed.get(collapse_key)
        if entry is None:
            collapsed[collapse_key] = {"system": system, "stop": stop, "refs": set(refs)}
        else:
            entry["refs"] |= refs
    duplicates = len(surface_refs) - len(collapsed)
    if duplicates:
        print(f"Collapsed {duplicates} surface stop_ids with the same name and position")
    for entry in collapsed.values():
        stop = entry["stop"]
        system = entry["system"]
        result.rows.append(
            {
                "system": system,
                "line": join_lines(entry["refs"]),
                "name": f"{systems[system].label} · {stop.name or 'Unnamed stop'}",
                "hierarchy": "stop",
                "latitude": stop.lat,
                "longitude": stop.lon,
                "source": source,
                "_key": stop.stop_id,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def gtfs_cache_path(city: str, source: str, cache_dir: Path | None = None) -> Path:
    return (cache_dir or GTFS_CACHE_DIR) / f"{city}_{id_slug(source)}.zip"


def fetch_gtfs_transit(
    city: str,
    *,
    profile: Mapping[str, Any] | None = None,
    force: bool = False,
    gtfs_zip: Path | None = None,
    cache_dir: Path | None = None,
    output_path: Path | None = None,
    today: date | None = None,
) -> list[dict]:
    """Fetch (or reuse) the city's GTFS feed and write its transit_stops.csv."""
    resolved = profile if profile is not None else load_city_profile(city)
    config = transit_source_config(resolved, "gtfs")
    systems = profile_systems(resolved)
    bbox = profile_bbox(resolved)
    rules = parse_rules(config, systems)
    source = str(config.get("source") or "gtfs")
    core_merge_m = float(config.get("core_merge_m", DEFAULT_CORE_MERGE_M))
    subtract_match_m = float(config.get("subtract_match_m", DEFAULT_SUBTRACT_MATCH_M))

    if gtfs_zip is not None:
        zip_path = gtfs_zip
        validate_gtfs_zip(zip_path)
        print(f"Using local GTFS zip {zip_path}")
    else:
        url = str(config.get("url") or "")
        if not url:
            raise ConfigError("transit_source.url (the GTFS zip) is required")
        zip_path = mx_common.cached_download(
            url, gtfs_cache_path(city, source, cache_dir), validate=validate_gtfs_zip, force=force
        )
    print(
        f"GTFS feed {config.get('feed_label') or source}: sha256={sha256_file(zip_path)} "
        f"bytes={zip_path.stat().st_size:,} path={zip_path}"
    )

    with zipfile.ZipFile(zip_path) as zf:
        span = calendar_range(zf)
        if span is not None:
            print(f"GTFS service calendar {span[0]}..{span[1]}")
            if span[1] < (today or date.today()).strftime("%Y%m%d"):
                print(f"WARNING: the GTFS calendar ended on {span[1]}; refresh the feed")
        routes = load_routes(zf)
        stops = load_stops(zf)
        assigned, _, _ = classify_routes(routes, rules, config.get("exclude_agencies") or [])
        route_stops = load_route_stops(zf, assigned)

    build = build_gtfs_rows(
        routes,
        stops,
        route_stops,
        rules,
        systems,
        bbox,
        exclude_agencies=config.get("exclude_agencies") or [],
        core_merge_m=core_merge_m,
        subtract_match_m=subtract_match_m,
        source=source,
    )
    print(
        f"Routes: {len(routes)} total, {build.excluded_routes} excluded by agency, "
        f"{len(build.unmatched_routes)} matched no rule"
    )
    if build.unmatched_routes:
        print(f"WARNING: routes with no rule (ignored): {build.unmatched_routes[:20]}")
    rows = finalize_rows(build.rows, systems)
    print_counts(rows, systems)
    check_declared_systems(rows, systems)
    target = output_path or city_data_dir(DATA_PROCESSED, city) / "transit_stops.csv"
    write_transit_stops(target, rows)
    return rows


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Build transit_stops.csv from the city's GTFS feed (profile transit_source)."
    )
    parser.add_argument("--city", required=True)
    parser.add_argument("--force", action="store_true", help="Redownload the cached feed.")
    parser.add_argument(
        "--gtfs-zip", type=Path, default=None, help="Use this local GTFS zip instead of the URL."
    )
    args = parser.parse_args(argv)
    run_cli(lambda: fetch_gtfs_transit(args.city, force=args.force, gtfs_zip=args.gtfs_zip))


if __name__ == "__main__":
    main()
