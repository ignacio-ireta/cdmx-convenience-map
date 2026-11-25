"""Fetch Monterrey transit stops from Nuevo León's official open data (CKAN, CC-BY).

Sources (profile ``transit_source``, ``type == "nl_open_data"``):

- STC Metrorrey quarterly GeoPackage (package ``packages.stcm``): Metro stations
  (one point per station and line) and TransMetro stops (BRT and feeder routes).
- IMA quarterly GeoPackage (package ``packages.ima``): urban-bus stops and route shapes.

The newest file of each package is chosen from the resource *URL* basename with
``resource_url_patterns`` (one group is the 4-digit year, the other the quarter),
never from resource names, which are wrong ("2026_T4_..." points to 4t2025).
``package_show`` is asked first and ``package_search`` with
``package_search_fallback`` is consulted too, so files published under next fiscal
year's package ids are found; either may fail as long as one answers. Downloads must
end on https ``catalogodatos.nl.gob.mx`` after any redirect, are validated (required
layers present) and cached atomically under ``data/raw/<city>/``.
Layers are picked by ``layer_patterns`` (names drift between quarters) and only the
latest Spanish month in each layer is used (each quarter repeats three months).

Systems written (codes must be declared in ``transit_systems``):

- ``METRO``: station × line from the Metro stations layer; line ``L<n>``.
- ``BRT``: TransMetro rows with ``LINEA == "BRT"`` or a ``RUTA`` listed in
  ``brt_routes`` (RUTA -> line id). The official BRT stop names do not match their
  coordinates, so names come from the nearest OSM ``public_transport=station``
  (network ``osm_brt_network``) within ``osm_brt_name_radius_m``, best effort through
  ``sources.io.retry_overpass`` (mirror rotation, replies older than
  ``OSM_BRT_MAX_AGE_DAYS`` rejected); the answer is cached under ``data/raw/<city>/``.
  A stop without a nearby OSM station (or every stop when Overpass fails) takes the
  name of the nearest METRO or TRANSMETRO stop within ``NEIGHBOUR_NAME_RADIUS_M``
  (a leading "Estación " dropped), and only failing that ``"<label> <line> · stop <n>"``.
- ``TRANSMETRO``: every other TransMetro row, one point per unique coordinate
  (6 decimals); line = the routes (``RUTA`` stripped, upper-cased) joined with ``"|"``.
  Rows with an empty ``RUTA`` (and not ``LINEA == "BRT"``) are placeholder points on
  no route and are dropped.
- ``BUS``: IMA stops, one per ``ID_parada``; coordinates from the geometry (the
  ``Latitud``/``Longitud`` columns disagree with it on some rows); line = the IMA
  route numbers (``^R(\\d+)`` of ``ID_servicio``) of every route shape within
  ``bus_route_buffer_m`` of the stop, joined with ``"|"``.

Rows outside the profile bbox are dropped; any declared system with no rows is an
error (non-zero exit).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio

from cdmxmap.errors import ConfigError, FetchError, SourceUnavailableError

from . import mx_common
from .fetch_gtfs_transit import (
    SystemInfo,
    check_declared_systems,
    finalize_rows,
    haversine_m,
    id_slug,
    in_bbox,
    join_lines,
    print_counts,
    profile_bbox,
    profile_systems,
    run_cli,
    sha256_file,
    transit_source_config,
    write_transit_stops,
)
from .io import (
    DATA_PROCESSED,
    DATA_RAW,
    OVERPASS_ENDPOINTS,
    USER_AGENT,
    city_data_dir,
    element_center,
    load_city_profile,
    retry_overpass,
)

SOURCE_STCM = "nl_stcm_metrorrey"
SOURCE_IMA = "nl_ima"
WGS84 = "EPSG:4326"
METRO, BRT, TRANSMETRO, BUS = "METRO", "BRT", "TRANSMETRO", "BUS"
SYSTEM_CODES = (METRO, BRT, TRANSMETRO, BUS)

SPANISH_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
_MONTH_ALIASES = {"setiembre": "septiembre"}
METRO_NAME_RE = re.compile(r"Estaci[oó]n\s+(.+?)\s+(?:L[ií]nea\s*|L)(\d+)\b", re.IGNORECASE)
IMA_ROUTE_RE = re.compile(r"^R(\d+)")
NO_PARADA_RE = re.compile(r"(\d+)")
DEFAULT_OSM_BRT_NETWORK = "Ecov[ií]a|Transmetro"
DEFAULT_OSM_NAME_RADIUS_M = 200.0
# A BRT stop with no OSM station nearby borrows the name of a METRO/TRANSMETRO stop
# this close (the feeder stops at a BRT station are named after it).
NEIGHBOUR_NAME_RADIUS_M = 75.0
ESTACION_PREFIX_RE = re.compile(r"^Estaci[oó]n\s+", re.IGNORECASE)
DEFAULT_BUS_BUFFER_M = 25.0
OSM_NAME_PREFIX_RE = re.compile(
    r"^(?:Ecov[ií]a|Transmetro)\b\s*(?:-\s*)?(?:Estaci[oó]n\s+)?", re.IGNORECASE
)
OSM_CACHE_NAME = "osm_brt_stations.json"
OSM_BBOX_PAD_DEG = 0.01
# A live BRT-name query rotates Overpass mirrors and rejects replies older than this.
OSM_BRT_MAX_AGE_DAYS = 30
# The NL open-data CKAN serves its resource files itself; a download that ends
# anywhere else (or on plain http) after redirects is refused before it is written.
NL_CKAN_HOST = "catalogodatos.nl.gob.mx"
STCM_LAYERS = ("metro_stations", "transmetro_stops")
IMA_LAYERS = ("ima_stops", "ima_routes")


# ---------------------------------------------------------------------------
# CKAN resolution and cached downloads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceChoice:
    url: str
    year: int
    quarter: int
    package: str

    @property
    def basename(self) -> str:
        return Path(urllib.parse.urlsplit(self.url).path).name


def ckan_action(api: str, action: str, params: Mapping[str, str], *, timeout: int = 60) -> dict:
    """GET a CKAN action and return its ``result`` (the network seam tests replace)."""
    url = f"{api.rstrip('/')}/{action}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
        raise SourceUnavailableError(f"CKAN {action} failed: {exc}") from exc
    if not isinstance(payload, dict) or not payload.get("success"):
        raise SourceUnavailableError(f"CKAN {action} answered without success: {url}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise SourceUnavailableError(f"CKAN {action} returned no result object: {url}")
    return result


def is_nl_ckan_url(url: str) -> bool:
    """https on the NL open-data catalogue host (exact host, no subdomains)."""
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and (parts.hostname or "").lower() == NL_CKAN_HOST


def resource_period(url: str, pattern: re.Pattern[str]) -> tuple[int, int] | None:
    """(year, quarter) from the URL basename, or None when the pattern does not match."""
    basename = Path(urllib.parse.urlsplit(url).path).name
    match = pattern.search(basename)
    if not match or len(match.groups()) < 2:
        return None
    first, second = match.group(1), match.group(2)
    year, quarter = (first, second) if len(first) == 4 else (second, first)
    if len(year) != 4 or not quarter.isdigit() or not 1 <= int(quarter) <= 4:
        return None
    return int(year), int(quarter)


def _package_choices(package: Mapping[str, Any], pattern: re.Pattern[str]) -> list[ResourceChoice]:
    choices = []
    for resource in package.get("resources") or []:
        url = str((resource or {}).get("url") or "")
        period = resource_period(url, pattern) if url else None
        if period is not None:
            choices.append(ResourceChoice(url, period[0], period[1], str(package.get("name"))))
    return choices


def resolve_latest_resource(
    api: str, package: str, pattern: re.Pattern[str], search_query: str | None
) -> ResourceChoice:
    """Newest resource matching ``pattern`` across package_show and package_search."""
    choices: list[ResourceChoice] = []
    errors: list[str] = []
    try:
        choices.extend(_package_choices(ckan_action(api, "package_show", {"id": package}), pattern))
    except SourceUnavailableError as exc:
        errors.append(str(exc))
        print(f"WARNING: package_show {package} failed: {exc}")
    if search_query:
        try:
            found = ckan_action(api, "package_search", {"q": search_query, "rows": "100"})
            for item in found.get("results") or []:
                if isinstance(item, dict):
                    choices.extend(_package_choices(item, pattern))
        except SourceUnavailableError as exc:
            errors.append(str(exc))
            print(f"WARNING: package_search {search_query!r} failed: {exc}")
    if not choices:
        detail = "; ".join(errors) if errors else "no resource URL matched"
        raise SourceUnavailableError(
            f"No resource matching {pattern.pattern} for package {package}: {detail}"
        )
    return max(choices, key=lambda c: (c.year, c.quarter, c.package == package, c.url))


def _latest_cached(raw_dir: Path, pattern: re.Pattern[str]) -> Path | None:
    candidates = []
    for path in raw_dir.glob("*.gpkg"):
        period = resource_period(path.name, pattern)
        if period is not None and path.stat().st_size > 0:
            candidates.append((period, path.name, path))
    return max(candidates)[2] if candidates else None


def pick_layer(path: Path, pattern: str) -> str:
    regex = re.compile(pattern, re.IGNORECASE)
    names = [str(name) for name, _ in pyogrio.list_layers(path) if regex.search(str(name))]
    if len(names) != 1:
        raise FetchError(f"{path.name}: layer pattern {pattern!r} matched {names} (need exactly 1)")
    return names[0]


def _validate_layers(patterns: Sequence[str]) -> Callable[[Path], None]:
    def validate(path: Path) -> None:
        for pattern in patterns:
            pick_layer(path, pattern)

    return validate


def fetch_package_gpkg(
    config: Mapping[str, Any],
    key: str,
    layer_keys: Sequence[str],
    raw_dir: Path,
    *,
    force: bool = False,
) -> Path:
    """Resolve, download (cached, validated) and return the newest GPKG of a package."""
    packages = config.get("packages") or {}
    patterns = config.get("resource_url_patterns") or {}
    layer_patterns = config.get("layer_patterns") or {}
    if key not in packages or key not in patterns:
        raise ConfigError(f"transit_source needs packages.{key} and resource_url_patterns.{key}")
    missing = [name for name in layer_keys if name not in layer_patterns]
    if missing:
        raise ConfigError(f"transit_source.layer_patterns lacks {missing}")
    pattern = re.compile(str(patterns[key]), re.IGNORECASE)
    validate = _validate_layers([str(layer_patterns[name]) for name in layer_keys])
    api = str(config.get("ckan_api") or "")
    if not api:
        raise ConfigError("transit_source.ckan_api is required")
    try:
        choice = resolve_latest_resource(
            api, str(packages[key]), pattern, config.get("package_search_fallback")
        )
    except SourceUnavailableError as exc:
        cached = _latest_cached(raw_dir, pattern)
        if cached is None:
            raise
        print(f"WARNING: {exc}; using the newest cached file {cached}")
        validate(cached)
        return cached
    print(
        f"{key}: newest resource {choice.basename} ({choice.quarter}T{choice.year}, "
        f"package {choice.package})"
    )
    path = mx_common.cached_download(
        choice.url,
        raw_dir / choice.basename,
        validate=validate,
        force=force,
        allowed_final_url=is_nl_ckan_url,
    )
    print(f"{key}: sha256={sha256_file(path)} path={path}")
    return path


# ---------------------------------------------------------------------------
# Layer helpers
# ---------------------------------------------------------------------------


def column(frame: pd.DataFrame, name: str, *, required: bool = True) -> str | None:
    """The actual column called ``name`` ignoring case (names drift between quarters)."""
    for candidate in frame.columns:
        if str(candidate).casefold() == name.casefold():
            return str(candidate)
    if required:
        raise FetchError(f"Layer has no {name!r} column (columns: {list(frame.columns)})")
    return None


def _month_index(value: object) -> int | None:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    key = text.strip().casefold()
    key = _MONTH_ALIASES.get(key, key)
    return SPANISH_MONTHS.index(key) if key in SPANISH_MONTHS else None


def latest_month_rows(frame: gpd.GeoDataFrame, name: str) -> tuple[gpd.GeoDataFrame, str]:
    """Rows of the latest Spanish month in column ``name`` (any case), and that month."""
    month_column = column(frame, name)
    assert month_column is not None
    indices = frame[month_column].map(_month_index)
    known = indices.dropna()
    if known.empty:
        raise FetchError(f"Column {month_column} has no Spanish month names")
    unknown = sorted({str(v) for v, i in zip(frame[month_column], indices) if pd.isna(i)})
    if unknown:
        print(f"WARNING: ignoring rows with unrecognized months {unknown}")
    latest = int(known.max())
    subset = frame[indices == latest].copy()
    return subset, str(subset[month_column].iloc[0]).strip()


def read_layer(path: Path, pattern: str) -> gpd.GeoDataFrame:
    frame = gpd.read_file(path, layer=pick_layer(path, pattern))
    if frame.crs is None:
        raise FetchError(f"{path.name}: layer for {pattern!r} has no CRS")
    return frame


def _text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


# ---------------------------------------------------------------------------
# METRO / BRT / TRANSMETRO (STC Metrorrey)
# ---------------------------------------------------------------------------


def metro_rows(
    stations: gpd.GeoDataFrame, *, label: str, name_fixes: Mapping[str, str]
) -> list[dict]:
    """One row per (station, line) from ``Estación <name> Línea <n> ...`` point names."""
    frame = stations.to_crs(WGS84)
    name_column = column(frame, "Name")
    rows: dict[tuple[str, str], dict] = {}
    for raw_name, geometry in zip(frame[name_column], frame.geometry):
        text = _text(raw_name)
        match = METRO_NAME_RE.search(text)
        if not match or geometry is None or geometry.is_empty:
            raise FetchError(
                f"Metro station {text!r} does not parse as 'Estación <name> Línea <n>'"
            )
        station = match.group(1).strip()
        station = name_fixes.get(station, station)
        line = f"L{int(match.group(2))}"
        rows.setdefault(
            (line, station),
            {
                "system": METRO,
                "line": line,
                "name": f"{label} {line} · {station}",
                "hierarchy": "station",
                "latitude": geometry.y,
                "longitude": geometry.x,
                "source": SOURCE_STCM,
                "_key": f"{line}-{id_slug(station)}",
                "_station": station,
            },
        )
    return list(rows.values())


@dataclass(frozen=True)
class OsmStation:
    name: str
    lat: float
    lon: float


def clean_osm_station_name(name: str) -> str:
    return OSM_NAME_PREFIX_RE.sub("", name.strip()).strip() or name.strip()


def parse_osm_stations(payload: Mapping[str, Any], network: str | None = None) -> list[OsmStation]:
    """Named ``public_transport=station`` elements (optionally only matching ``network``)."""
    network_re = re.compile(network, re.IGNORECASE) if network else None
    stations = []
    for element in payload.get("elements") or []:
        tags = element.get("tags") or {}
        center = element_center(element)
        name = str(tags.get("name") or "").strip()
        if center is None or not name or tags.get("public_transport") != "station":
            continue
        if network_re is not None and not network_re.search(str(tags.get("network") or "")):
            continue
        stations.append(OsmStation(clean_osm_station_name(name), center[0], center[1]))
    return sorted(stations, key=lambda s: (s.name, s.lat, s.lon))


def osm_brt_query(bbox: Mapping[str, float], network: str) -> str:
    box = ",".join(f"{bbox[key]:.5f}" for key in ("south", "west", "north", "east"))
    return (
        "[out:json][timeout:120];\n"
        f'nwr["public_transport"="station"]["network"~"{network}",i][!"construction"]({box});\n'
        "out tags center;\n"
    )


def fetch_osm_brt_stations(
    points: Iterable[tuple[float, float]],
    *,
    network: str,
    cache_path: Path,
    force: bool = False,
) -> list[OsmStation] | None:
    """OSM BRT station names near ``points`` (cached); None when Overpass is unavailable."""
    coords = list(points)
    if not coords:
        return []
    if cache_path.exists() and not force:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            print(f"Using cached {cache_path}")
            return parse_osm_stations(payload, network)
        except (OSError, ValueError) as exc:
            print(f"WARNING: ignoring unreadable OSM cache {cache_path}: {exc}")
    bbox = {
        "south": min(lat for lat, _ in coords) - OSM_BBOX_PAD_DEG,
        "west": min(lon for _, lon in coords) - OSM_BBOX_PAD_DEG,
        "north": max(lat for lat, _ in coords) + OSM_BBOX_PAD_DEG,
        "east": max(lon for _, lon in coords) + OSM_BBOX_PAD_DEG,
    }
    try:
        payload = retry_overpass(
            osm_brt_query(bbox, network),
            attempts=3,
            timeout=180,
            endpoints=OVERPASS_ENDPOINTS,
            max_osm_age_days=OSM_BRT_MAX_AGE_DAYS,
        )
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"WARNING: Overpass unavailable for BRT station names ({exc}); using generic names")
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        print("WARNING: Overpass answered without an elements list; using generic BRT names")
        return None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_name(f"{cache_path.stem}.{uuid.uuid4().hex[:12]}.part.json")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, cache_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    stations = parse_osm_stations(payload, network)
    print(f"Overpass returned {len(stations)} named BRT stations (cached in {cache_path})")
    return stations


def nearest_station_name(
    lat: float, lon: float, stations: Sequence[OsmStation], radius_m: float
) -> str | None:
    best: tuple[float, str] | None = None
    for station in stations:
        distance = haversine_m(lat, lon, station.lat, station.lon)
        if distance <= radius_m and (best is None or (distance, station.name) < best):
            best = (distance, station.name)
    return best[1] if best else None


@dataclass(frozen=True)
class NamedStop:
    """A METRO/TRANSMETRO stop name a BRT stop may borrow (``system`` for the counts)."""

    system: str
    name: str
    lat: float
    lon: float


def strip_estacion(name: str) -> str:
    """``"Estacion Exposición"`` -> ``"Exposición"`` (unchanged if nothing is left)."""
    return ESTACION_PREFIX_RE.sub("", name.strip()).strip() or name.strip()


def neighbour_stops(rows: Iterable[Mapping[str, Any]]) -> list[NamedStop]:
    """Named METRO/TRANSMETRO points from built rows (their private ``_station``)."""
    stops = []
    for row in rows:
        station = str(row.get("_station") or "").strip()
        if station and row.get("system") in (METRO, TRANSMETRO):
            stops.append(
                NamedStop(
                    str(row["system"]),
                    strip_estacion(station),
                    float(row["latitude"]),
                    float(row["longitude"]),
                )
            )
    return sorted(stops, key=lambda s: (s.name, s.lat, s.lon, s.system))


def nearest_named_stop(
    lat: float, lon: float, stops: Sequence[NamedStop], radius_m: float
) -> NamedStop | None:
    """The closest stop within ``radius_m`` (ties by name, then system), else None."""
    in_range = [
        (distance, stop)
        for stop in stops
        if (distance := haversine_m(lat, lon, stop.lat, stop.lon)) <= radius_m
    ]
    if not in_range:
        return None
    return min(in_range, key=lambda item: (item[0], item[1].name, item[1].system))[1]


def _stop_number(values: Iterable[object]) -> int | None:
    numbers = []
    for value in values:
        match = NO_PARADA_RE.search(_text(value))
        if match:
            numbers.append(int(match.group(1)))
    return min(numbers) if numbers else None


@dataclass
class TransmetroFrames:
    brt: pd.DataFrame
    other: pd.DataFrame
    month: str


def split_transmetro(stops: gpd.GeoDataFrame, brt_routes: Mapping[str, str]) -> TransmetroFrames:
    """Latest-month TransMetro rows split into BRT (with line ids) and the rest."""
    frame, month = latest_month_rows(stops, "MES")
    frame = frame.to_crs(WGS84)
    ruta_column = column(frame, "RUTA")
    linea_column = column(frame, "LINEA")
    stop_column = column(frame, "NO_PARADA", required=False)
    name_column = column(frame, "NOM_VIAL", required=False)
    brt_map = {str(k).strip().upper(): str(v).strip() for k, v in brt_routes.items()}
    table = pd.DataFrame(
        {
            "ruta": [_text(v).upper() for v in frame[ruta_column]],
            "linea": [_text(v).upper() for v in frame[linea_column]],
            "stop_no": [_text(v) for v in frame[stop_column]] if stop_column else "",
            "nom_vial": [_text(v) for v in frame[name_column]] if name_column else "",
            "lat": frame.geometry.y.round(6).to_numpy(),
            "lon": frame.geometry.x.round(6).to_numpy(),
        }
    )
    mapped = table["ruta"].map(brt_map)
    is_brt = (table["linea"] == "BRT") | mapped.notna()
    # A non-BRT row without a RUTA serves no route (the Q3-2026 file has a few
    # all-null rows next to real terminals): a placeholder point, not a stop.
    placeholder = ~is_brt & (table["ruta"] == "")
    if placeholder.any():
        print(f"TRANSMETRO: dropped {int(placeholder.sum())} {month} stop rows without a RUTA")
    fallback_line = table["ruta"].where(table["ruta"] != "", "BRT")
    table["brt_line"] = mapped.fillna(fallback_line)
    other = ~is_brt & ~placeholder
    return TransmetroFrames(brt=table[is_brt].copy(), other=table[other].copy(), month=month)


def brt_rows(
    brt: pd.DataFrame,
    *,
    label: str,
    line_labels: Mapping[str, str],
    osm_stations: Sequence[OsmStation] | None,
    radius_m: float,
    neighbours: Sequence[NamedStop] = (),
    neighbour_radius_m: float = NEIGHBOUR_NAME_RADIUS_M,
) -> list[dict]:
    """One BRT station per (line, coordinate). Names, in order of preference: the
    nearest OSM station within ``radius_m``, the nearest METRO/TRANSMETRO stop in
    ``neighbours`` within ``neighbour_radius_m``, then ``"stop <NO_PARADA>"``."""
    rows = []
    sources: dict[str, int] = {"OSM": 0, METRO: 0, TRANSMETRO: 0, "generic": 0}
    for _, group in brt.groupby(["brt_line", "lat", "lon"], sort=True):
        line_text = str(group["brt_line"].iloc[0])
        lat, lon = float(group["lat"].iloc[0]), float(group["lon"].iloc[0])
        display_line = line_labels.get(line_text, line_text)
        osm_name = nearest_station_name(lat, lon, osm_stations, radius_m) if osm_stations else None
        neighbour = (
            None if osm_name else nearest_named_stop(lat, lon, neighbours, neighbour_radius_m)
        )
        if osm_name:
            sources["OSM"] += 1
            station = osm_name
        elif neighbour is not None:
            sources[neighbour.system] += 1
            station = neighbour.name
        else:
            sources["generic"] += 1
            number = _stop_number(group["stop_no"])
            station = f"stop {number}" if number is not None else "stop"
        rows.append(
            {
                "system": BRT,
                "line": line_text,
                "name": f"{label} {display_line} · {station}",
                "hierarchy": "station",
                "latitude": lat,
                "longitude": lon,
                "source": SOURCE_STCM,
            }
        )
    print(
        f"BRT names for {len(rows)} stops: {sources['OSM']} from OSM stations within "
        f"{radius_m:g} m, {sources[METRO]} from METRO and {sources[TRANSMETRO]} from "
        f"TRANSMETRO stops within {neighbour_radius_m:g} m, {sources['generic']} generic"
    )
    return rows


def transmetro_rows(other: pd.DataFrame, *, label: str) -> list[dict]:
    rows = []
    for _, group in other.groupby(["lat", "lon"], sort=True):
        lat, lon = float(group["lat"].iloc[0]), float(group["lon"].iloc[0])
        ordered = group.sort_values(["ruta", "stop_no", "nom_vial"])
        names = [name for name in ordered["nom_vial"] if name]
        street = mx_common.spanish_title_case(names[0]) if names else ""
        rows.append(
            {
                "system": TRANSMETRO,
                "line": join_lines(ordered["ruta"]),
                "name": f"{label} · {street or 'Parada'}",
                "hierarchy": "stop",
                "latitude": lat,
                "longitude": lon,
                "source": SOURCE_STCM,
                "_station": street,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# BUS (IMA)
# ---------------------------------------------------------------------------


def ima_route_number(service_id: object) -> str:
    text = _text(service_id)
    match = IMA_ROUTE_RE.match(text)
    return str(int(match.group(1))) if match else text


def bus_rows(
    stops: gpd.GeoDataFrame,
    routes: gpd.GeoDataFrame,
    *,
    label: str,
    buffer_m: float,
    metric_crs: str,
) -> list[dict]:
    """IMA stops (latest month, one per ID_parada) with the route numbers passing them."""
    frame, month = latest_month_rows(stops, "mes")
    id_column = column(frame, "ID_parada")
    ids = frame[id_column].map(_text)
    missing = int((ids == "").sum())
    if missing:
        print(f"BUS: dropped {missing} {month} stop rows without an ID_parada")
    frame = frame[ids != ""].copy()
    frame["_stop_id"] = ids[ids != ""]
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty].copy()

    # Among rows repeating an ID_parada keep the one whose geometry agrees best with
    # its own Latitud/Longitud columns (coordinates still come from the geometry).
    wgs = frame.to_crs(WGS84)
    lat_column = column(frame, "Latitud", required=False)
    lon_column = column(frame, "Longitud", required=False)
    if lat_column and lon_column:
        declared_lat = pd.to_numeric(frame[lat_column], errors="coerce")
        declared_lon = pd.to_numeric(frame[lon_column], errors="coerce")
        mismatch = [
            haversine_m(y, x, la, lo) if pd.notna(la) and pd.notna(lo) else float("inf")
            for y, x, la, lo in zip(wgs.geometry.y, wgs.geometry.x, declared_lat, declared_lon)
        ]
    else:
        mismatch = [0.0] * len(frame)
    frame["_mismatch"] = mismatch
    frame["_order"] = range(len(frame))
    duplicates = int(frame["_stop_id"].duplicated().sum())
    frame = frame.sort_values(["_stop_id", "_mismatch", "_order"]).drop_duplicates("_stop_id")
    if duplicates:
        print(f"BUS: {duplicates} repeated ID_parada rows dropped")

    route_frame = routes
    route_month_column = column(routes, "mes", required=False)
    if route_month_column:
        same_month = routes[routes[route_month_column].map(_month_index) == _month_index(month)]
        if same_month.empty:
            route_frame, route_month = latest_month_rows(routes, "mes")
            print(f"BUS: no {month} route shapes; using {route_month}")
        else:
            route_frame = same_month
    service_column = column(route_frame, "ID_servicio")
    route_metric = route_frame.to_crs(metric_crs).reset_index(drop=True)
    buffered = gpd.GeoDataFrame(
        {"route": [ima_route_number(v) for v in route_metric[service_column]]},
        geometry=route_metric.geometry.buffer(buffer_m).to_numpy(),
        crs=metric_crs,
    )
    buffered = buffered[buffered["route"] != ""]
    points = gpd.GeoDataFrame(
        {"_stop_id": frame["_stop_id"].to_numpy()},
        geometry=frame.geometry.to_crs(metric_crs).to_numpy(),
        crs=metric_crs,
    )
    joined = gpd.sjoin(points, buffered, how="left", predicate="intersects")
    routes_by_stop: dict[str, set[str]] = {}
    for stop_id, route in zip(joined["_stop_id"], joined["route"]):
        bucket = routes_by_stop.setdefault(str(stop_id), set())
        if isinstance(route, str) and route:
            bucket.add(route)

    wgs = frame.to_crs(WGS84)
    street_column = column(frame, "NomVial", required=False)
    cross_column = column(frame, "Cruce", required=False)
    rows = []
    for index, stop_id in enumerate(wgs["_stop_id"]):
        street = _text(wgs[street_column].iloc[index]) if street_column else ""
        cross = _text(wgs[cross_column].iloc[index]) if cross_column else ""
        place = ", ".join(part for part in (street, cross) if part) or stop_id
        geometry = wgs.geometry.iloc[index]
        rows.append(
            {
                "system": BUS,
                "line": join_lines(routes_by_stop.get(str(stop_id), ())),
                "name": f"{label} · {place}",
                "hierarchy": "stop",
                "latitude": geometry.y,
                "longitude": geometry.x,
                "source": SOURCE_IMA,
                "_key": stop_id,
            }
        )
    unmatched = sum(1 for row in rows if not row["line"])
    print(f"BUS: {len(rows)} {month} stops; {unmatched} with no route within {buffer_m:g} m")
    return rows


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _require_systems(systems: Mapping[str, SystemInfo]) -> None:
    missing = [code for code in SYSTEM_CODES if code not in systems]
    if missing:
        raise ConfigError(f"fetch_nl_transit writes {SYSTEM_CODES}; the profile lacks {missing}")


def build_nl_rows(
    stcm_path: Path,
    ima_path: Path,
    config: Mapping[str, Any],
    systems: Mapping[str, SystemInfo],
    *,
    metric_crs: str,
    osm_lookup: Callable[[list[tuple[float, float]]], Sequence[OsmStation] | None],
) -> list[dict]:
    """All rows (unfinalized) from the two GeoPackages; ``osm_lookup`` names BRT stops."""
    _require_systems(systems)
    layers = config.get("layer_patterns") or {}
    metro = metro_rows(
        read_layer(stcm_path, str(layers["metro_stations"])),
        label=systems[METRO].label,
        name_fixes=config.get("metro_name_fixes") or {},
    )
    split = split_transmetro(
        read_layer(stcm_path, str(layers["transmetro_stops"])), config.get("brt_routes") or {}
    )
    transmetro = transmetro_rows(split.other, label=systems[TRANSMETRO].label)
    brt_points = sorted(set(zip(split.brt["lat"].astype(float), split.brt["lon"].astype(float))))
    osm_stations = osm_lookup(brt_points) if config.get("osm_brt_station_names", True) else None
    brt = brt_rows(
        split.brt,
        label=systems[BRT].label,
        line_labels=config.get("line_labels") or {},
        osm_stations=osm_stations,
        radius_m=float(config.get("osm_brt_name_radius_m", DEFAULT_OSM_NAME_RADIUS_M)),
        neighbours=neighbour_stops(metro + transmetro),
    )
    bus = bus_rows(
        read_layer(ima_path, str(layers["ima_stops"])),
        read_layer(ima_path, str(layers["ima_routes"])),
        label=systems[BUS].label,
        buffer_m=float(config.get("bus_route_buffer_m", DEFAULT_BUS_BUFFER_M)),
        metric_crs=metric_crs,
    )
    print(f"Months used: STCM {split.month}")
    return metro + brt + transmetro + bus


def clip_rows(rows: Iterable[dict], bbox: Mapping[str, float]) -> list[dict]:
    kept = [row for row in rows if in_bbox(float(row["latitude"]), float(row["longitude"]), bbox)]
    return kept


def fetch_nl_transit(
    city: str,
    *,
    profile: Mapping[str, Any] | None = None,
    force: bool = False,
    raw_dir: Path | None = None,
    output_path: Path | None = None,
) -> list[dict]:
    resolved = profile if profile is not None else load_city_profile(city)
    config = transit_source_config(resolved, "nl_open_data")
    systems = profile_systems(resolved)
    _require_systems(systems)
    bbox = profile_bbox(resolved)
    epsg = resolved.get("crs_metric_epsg")
    if not epsg:
        raise ConfigError("The city profile needs crs_metric_epsg for the bus route buffer")
    city_raw = raw_dir or city_data_dir(DATA_RAW, city)
    stcm_path = fetch_package_gpkg(config, "stcm", STCM_LAYERS, city_raw, force=force)
    ima_path = fetch_package_gpkg(config, "ima", IMA_LAYERS, city_raw, force=force)
    network = str(config.get("osm_brt_network") or DEFAULT_OSM_BRT_NETWORK)

    def osm_lookup(points: list[tuple[float, float]]) -> Sequence[OsmStation] | None:
        return fetch_osm_brt_stations(
            points, network=network, cache_path=city_raw / OSM_CACHE_NAME, force=force
        )

    rows = build_nl_rows(
        stcm_path,
        ima_path,
        config,
        systems,
        metric_crs=f"EPSG:{int(epsg)}",
        osm_lookup=osm_lookup,
    )
    clipped = clip_rows(rows, bbox)
    if len(clipped) != len(rows):
        print(f"Dropped {len(rows) - len(clipped)} stops outside the profile bbox")
    final = finalize_rows(clipped, systems)
    print_counts(final, systems)
    check_declared_systems(final, systems)
    target = output_path or city_data_dir(DATA_PROCESSED, city) / "transit_stops.csv"
    write_transit_stops(target, final)
    return final


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Fetch Monterrey transit stops from Nuevo León open data (STC Metrorrey, IMA)."
    )
    parser.add_argument("--city", required=True)
    parser.add_argument(
        "--force", action="store_true", help="Redownload the GeoPackages and OSM station names."
    )
    args = parser.parse_args(argv)
    run_cli(lambda: fetch_nl_transit(args.city, force=args.force))


if __name__ == "__main__":
    main()
