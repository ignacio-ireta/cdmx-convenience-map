"""Pipeline constants and configuration loading (engineering standards §E).

Centralizes coordinate systems, area field-name candidates, scoring weights,
transit-system groupings, and the loaders for ``data/config/places.json``.
"""

from __future__ import annotations

import json
from typing import Any

from cdmxmap.schema import validate_places_config
from cdmxmap.sources.io import DATA_CITIES, DATA_CONFIG
from cdmxmap.transit_commute import OUTPUT_COLUMNS as TRANSIT_COMMUTE_COLUMNS
from cdmxmap.transit_commute import TransitCommuteConfig

WGS84_CRS = "EPSG:4326"
METRIC_CRS = "EPSG:32614"

POSTAL_CODE_FIELDS = [
    "postal_code",
    "codigo_postal",
    "codigo",
    "d_cp",
    "d_codigo",
    "cp",
    "cve_cp",
    "CVE_CP",
    "CODIGO",
]

POSTAL_LABEL_FIELDS = [
    "colonia",
    "asentamiento",
    "d_asenta",
    "nomgeo",
]

COLONIA_ID_FIELDS = [
    "area_id",
    "colonia_id",
    "id",
    "col_code",
    "cve_colonia",
    "cve_asenta",
    "cvegeo",
    "CVEGEO",
]

COLONIA_NAME_FIELDS = [
    "area_name",
    "colonia_name",
    "col_name",
    "colonia",
    "nombre",
    "nomgeo",
    "NOMGEO",
]

ALCALDIA_FIELDS = [
    "alcaldia",
    "municipio",
    "D_mnpio",
    "nom_mun",
    "NOM_MUN",
    "alcaldia_catalogo",
]

DEFAULT_WEIGHTS = {
    "work": 0.30,
    "transit": 0.25,
    "supermarkets": 0.18,
    "gyms": 0.12,
    "safety": 0.15,
}

CORE_TRANSIT_SYSTEMS = {"METRO", "MB", "TROLE"}
SURFACE_TRANSIT_SYSTEMS = {"RTP", "CC"}
TRANSIT_SYSTEM_FIELD_SLUGS = {
    "METRO": "metro",
    "MB": "metrobus",
    "RTP": "rtp",
    "TROLE": "trolebus",
    "CC": "corredor",
}
WORK_TRAVEL_MODES = ("driving", "walking", "biking")
DEFAULT_TRAVEL_TIME_CONFIG: dict[str, Any] = {
    "source": "fallback_straight_line_estimate",
    "speeds_kmh": {
        "driving": 24.0,
        "walking": 4.8,
        "biking": 14.0,
    },
    "detour_factors": {
        "driving": 1.35,
        "walking": 1.15,
        "biking": 1.25,
    },
}

ROAD_ROUTER_NONE = "none"
ROAD_ROUTER_VALHALLA = "valhalla"
DEFAULT_ROAD_ROUTING_CONFIG: dict[str, Any] = {
    "engine": ROAD_ROUTER_NONE,
    "tiles_dir": "data/processed/valhalla",
    "modes": list(WORK_TRAVEL_MODES),
    "candidate_count": 5,
}

TRANSIT_COMMUTE_NOT_CONFIGURED_SOURCE = "transit_commute_not_configured"
TRANSIT_COMMUTE_FAILED_SOURCE = "transit_commute_failed"
TRANSIT_ROUTER_APIMETRO = "apimetro_approximation"
TRANSIT_ROUTER_R5PY = "r5py"
R5PY_TRANSIT_COMMUTE_SOURCE = "r5py_gtfs_schedule"
R5PY_OSM_SOURCE = "https://download.bbbike.org/osm/bbbike/MexicoCity/MexicoCity.osm.pbf"

TRANSIT_COMMUTE_OUTPUT_COLUMNS: list[str] = []
for transit_column in TRANSIT_COMMUTE_COLUMNS:
    TRANSIT_COMMUTE_OUTPUT_COLUMNS.append(transit_column)
    if transit_column == "time_work_transit_min":
        TRANSIT_COMMUTE_OUTPUT_COLUMNS.append("time_work_transit_p75_min")


def load_places_config(city: str = "cdmx") -> dict:
    """Load a city's places.json.

    Resolution order: ``data/cities/<city>/places.json`` first; for CDMX, fall
    back to the legacy ``data/config/places.json`` so existing behavior is
    unchanged. Missing config yields safe defaults.
    """
    candidates = [DATA_CITIES / city / "places.json"]
    if city == "cdmx":
        candidates.append(DATA_CONFIG / "places.json")
    for path in candidates:
        if path.exists():
            return validate_places_config(json.loads(path.read_text(encoding="utf-8")))
    return {
        "workplace": {},
        "travel_time": DEFAULT_TRAVEL_TIME_CONFIG,
    }


def merged_travel_time_config(places_config: dict) -> dict:
    configured = places_config.get("travel_time", {})
    speeds = {
        **DEFAULT_TRAVEL_TIME_CONFIG["speeds_kmh"],
        **configured.get("speeds_kmh", {}),
    }
    detour_factors = {
        **DEFAULT_TRAVEL_TIME_CONFIG["detour_factors"],
        **configured.get("detour_factors", {}),
    }
    return {
        "source": configured.get("source", DEFAULT_TRAVEL_TIME_CONFIG["source"]),
        "speeds_kmh": {mode: float(speeds[mode]) for mode in WORK_TRAVEL_MODES},
        "detour_factors": {mode: float(detour_factors[mode]) for mode in WORK_TRAVEL_MODES},
    }


def amenity_travel_time_config(places_config: dict, travel_time_config: dict) -> dict:
    configured = places_config.get("amenity_travel_time", {})
    source = str(configured.get("source", travel_time_config["source"])).strip()
    if source != "fallback_straight_line_estimate":
        source = "fallback_straight_line_estimate"
    mode = str(configured.get("mode", "walking")).strip().lower()
    if mode not in WORK_TRAVEL_MODES:
        mode = "walking"
    candidate_count = int(configured.get("candidate_count", 5) or 5)
    return {
        "source": source,
        "mode": mode,
        "candidate_count": max(1, min(candidate_count, 10)),
    }


def transit_commute_config(places_config: dict) -> TransitCommuteConfig:
    return TransitCommuteConfig.from_mapping(places_config.get("transit_commute", {}))


def road_routing_config(places_config: dict) -> dict:
    """Merge the optional ``road_routing`` block with defaults.

    ``engine`` defaults to ``none`` (straight-line fallback). ``modes`` is filtered
    to the supported work modes; ``candidate_count`` is clamped to 1..10.
    """
    configured = places_config.get("road_routing", {}) or {}
    engine = str(configured.get("engine", DEFAULT_ROAD_ROUTING_CONFIG["engine"])).strip().lower()
    modes = configured.get("modes") or list(WORK_TRAVEL_MODES)
    modes = [mode for mode in modes if mode in WORK_TRAVEL_MODES] or list(WORK_TRAVEL_MODES)
    candidate_count = int(configured.get("candidate_count", 5) or 5)
    return {
        "engine": engine,
        "tiles_dir": configured.get("tiles_dir", DEFAULT_ROAD_ROUTING_CONFIG["tiles_dir"]),
        "modes": tuple(modes),
        "candidate_count": max(1, min(candidate_count, 10)),
        "version": configured.get("version"),
        "osm_source": configured.get("osm_source"),
    }
