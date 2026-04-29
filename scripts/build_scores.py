from __future__ import annotations

import argparse
import json
import math
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from common import (
    DATA_CONFIG,
    DATA_PROCESSED,
    DATA_RAW,
    FRONTEND_PUBLIC_DATA,
    ROOT,
    ensure_dirs,
)
from transit_commute import (
    OUTPUT_COLUMNS as TRANSIT_COMMUTE_COLUMNS,
    TransitCommuteConfig,
    estimate_transit_commute_to_work,
    score_transit_commute_minutes,
    transit_commute_metadata,
)


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
WORK_TRAVEL_MODES = ("driving", "walking", "biking")
DEFAULT_TRAVEL_TIME_CONFIG = {
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

TRANSIT_COMMUTE_NOT_CONFIGURED_SOURCE = "transit_commute_not_configured"
TRANSIT_COMMUTE_FAILED_SOURCE = "transit_commute_failed"
TRANSIT_ROUTER_APIMETRO = "apimetro_approximation"
TRANSIT_ROUTER_R5PY = "r5py"
R5PY_TRANSIT_COMMUTE_SOURCE = "r5py_gtfs_schedule"
R5PY_OSM_SOURCE = "https://download.bbbike.org/osm/bbbike/MexicoCity/MexicoCity.osm.pbf"
TRANSIT_COMMUTE_OUTPUT_COLUMNS = []
for transit_column in TRANSIT_COMMUTE_COLUMNS:
    TRANSIT_COMMUTE_OUTPUT_COLUMNS.append(transit_column)
    if transit_column == "time_work_transit_min":
        TRANSIT_COMMUTE_OUTPUT_COLUMNS.append("time_work_transit_p75_min")


@dataclass(frozen=True)
class AreaConfig:
    area_unit: str
    default_input_path: Path
    output_name: str
    legacy_output_names: tuple[str, ...]
    id_fields: list[str]
    name_fields: list[str]
    source_url_key: str
    source_url: str


@dataclass(frozen=True)
class NearestResult:
    distances: np.ndarray
    names: list[str]
    sources: list[str]


@dataclass(frozen=True)
class AmenityRouteResult:
    distances: np.ndarray
    times: np.ndarray
    names: list[str]
    sources: list[str]
    candidate_pairs: int
    estimated_pairs: int


@dataclass(frozen=True)
class PointDatasets:
    transit: gpd.GeoDataFrame
    core_transit: gpd.GeoDataFrame
    surface_transit: gpd.GeoDataFrame
    supermarkets: gpd.GeoDataFrame
    costcos: gpd.GeoDataFrame
    walmarts: gpd.GeoDataFrame
    gyms: gpd.GeoDataFrame
    workplaces: gpd.GeoDataFrame
    crimes: gpd.GeoDataFrame


@dataclass(frozen=True)
class ScoredAreaResult:
    output: gpd.GeoDataFrame
    metadata: dict


AREA_CONFIGS = {
    "postal_code": AreaConfig(
        area_unit="postal_code",
        default_input_path=DATA_RAW / "correos-postales.json",
        output_name="scores_postal_code.geojson",
        legacy_output_names=("cdmx_postal_scores.geojson",),
        id_fields=POSTAL_CODE_FIELDS,
        name_fields=POSTAL_LABEL_FIELDS,
        source_url_key="postal_codes",
        source_url="https://datos.cdmx.gob.mx/dataset/codigos-postales",
    ),
    "colonia": AreaConfig(
        area_unit="colonia",
        default_input_path=DATA_RAW / "colonias.geojson",
        output_name="scores_colonia.geojson",
        legacy_output_names=(),
        id_fields=COLONIA_ID_FIELDS,
        name_fields=COLONIA_NAME_FIELDS,
        source_url_key="colonias",
        source_url=(
            "https://public.opendatasoft.com/explore/dataset/"
            "georef-mexico-colonia/export/"
        ),
    ),
}


def first_existing(columns: list[str], candidates: list[str]) -> str | None:
    by_lower = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate in columns:
            return candidate
        if candidate.lower() in by_lower:
            return by_lower[candidate.lower()]
    return None


def normalize_postal_code(value: object) -> str:
    text = str(value or "").strip()
    digits = "".join(character for character in text if character.isdigit())
    return digits.zfill(5)[-5:] if digits else text.zfill(5)


def normalize_text_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def field_text(
    frame: gpd.GeoDataFrame, fields: list[str], *, default: str = ""
) -> pd.Series:
    field = first_existing(list(frame.columns), fields)
    if field is None:
        return pd.Series([default] * len(frame), index=frame.index, dtype="object")
    return normalize_text_series(frame[field])


def ensure_unique_area_ids(values: pd.Series) -> pd.Series:
    counts: dict[str, int] = {}
    unique_values: list[str] = []
    for index, value in enumerate(values.astype(str)):
        area_id = value.strip() or f"area-{index + 1}"
        counts[area_id] = counts.get(area_id, 0) + 1
        unique_values.append(area_id if counts[area_id] == 1 else f"{area_id}-{counts[area_id]}")
    return pd.Series(unique_values, index=values.index, dtype="object")


def load_area_geometries(path: Path) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing area GeoJSON: {path}")
    areas = gpd.read_file(path)
    if areas.empty:
        raise ValueError(f"{path} did not contain any area features")
    if areas.crs is None:
        areas = areas.set_crs(WGS84_CRS)
    return areas


def prepare_area_properties(
    areas: gpd.GeoDataFrame, config: AreaConfig
) -> gpd.GeoDataFrame:
    prepared = areas.copy()
    id_field = first_existing(list(prepared.columns), config.id_fields)
    if id_field is None:
        raw_area_ids = pd.Series(
            [f"{config.area_unit}-{idx + 1}" for idx in range(len(prepared))],
            index=prepared.index,
        )
    else:
        raw_area_ids = normalize_text_series(prepared[id_field])

    if config.area_unit == "postal_code":
        area_ids = raw_area_ids.map(normalize_postal_code)
        prepared["postal_code"] = area_ids
        if "d_cp" not in prepared.columns:
            prepared["d_cp"] = area_ids
    else:
        area_ids = raw_area_ids
        prepared["colonia_name"] = field_text(prepared, config.name_fields)

    area_ids = ensure_unique_area_ids(area_ids)
    area_names = field_text(prepared, config.name_fields)
    area_names = area_names.where(area_names != "", area_ids)
    alcaldias = field_text(prepared, ALCALDIA_FIELDS)

    prepared["area_unit"] = config.area_unit
    prepared["area_id"] = area_ids
    prepared["area_name"] = area_names
    prepared["display_name"] = (
        "CP " + area_ids if config.area_unit == "postal_code" else area_names
    )
    prepared["alcaldia"] = alcaldias

    if config.area_unit == "postal_code":
        prepared["postal_label"] = area_names.where(area_names != area_ids, "")
    else:
        prepared["colonia_name"] = area_names

    return prepared


def read_points(path: Path, *, required: bool = True) -> gpd.GeoDataFrame:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Missing required point file: {path}")
        return gpd.GeoDataFrame(columns=["name", "latitude", "longitude"], geometry=[])

    df = pd.read_csv(path)
    if df.empty and required:
        raise ValueError(f"{path} has no rows")
    for column in ["latitude", "longitude"]:
        if column not in df.columns:
            raise ValueError(f"{path} is missing {column}")
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["latitude", "longitude"]).copy()
    if "name" not in df.columns:
        df["name"] = path.stem

    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
        crs=WGS84_CRS,
    )
    return gdf.to_crs(METRIC_CRS)


def load_places_config() -> dict:
    path = DATA_CONFIG / "places.json"
    if not path.exists():
        return {
            "workplace": {},
            "travel_time": DEFAULT_TRAVEL_TIME_CONFIG,
        }
    return json.loads(path.read_text(encoding="utf-8"))


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
        "detour_factors": {
            mode: float(detour_factors[mode]) for mode in WORK_TRAVEL_MODES
        },
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


def load_workplaces(places_config: dict) -> gpd.GeoDataFrame:
    workplace = places_config.get("workplace", {})
    latitude = workplace.get("latitude")
    longitude = workplace.get("longitude")
    if latitude is not None and longitude is not None:
        df = pd.DataFrame(
            [
                {
                    "name": workplace.get("name", "Configured workplace"),
                    "postal_code": str(workplace.get("postal_code", "")).strip(),
                    "latitude": float(latitude),
                    "longitude": float(longitude),
                    "source": workplace.get("source", "places_config"),
                }
            ]
        )
        gdf = gpd.GeoDataFrame(
            df,
            geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
            crs=WGS84_CRS,
        )
        return gdf.to_crs(METRIC_CRS)

    return read_points(DATA_RAW / "workplaces.csv")


def nearest(reference_points: gpd.GeoSeries, points: gpd.GeoDataFrame) -> NearestResult:
    if points.empty:
        distances = np.full(len(reference_points), np.nan)
        return NearestResult(
            distances=distances,
            names=[""] * len(reference_points),
            sources=[""] * len(reference_points),
        )

    point_x = points.geometry.x.to_numpy()
    point_y = points.geometry.y.to_numpy()
    point_names = points["name"].fillna("Unnamed").astype(str).to_numpy()
    point_sources = (
        points["source"].fillna("unknown").astype(str).to_numpy()
        if "source" in points.columns
        else np.array(["unknown"] * len(points))
    )

    distances: list[float] = []
    names: list[str] = []
    sources: list[str] = []
    for reference_point in reference_points:
        squared = np.square(point_x - reference_point.x) + np.square(
            point_y - reference_point.y
        )
        index = int(np.argmin(squared))
        distances.append(float(math.sqrt(float(squared[index]))))
        names.append(str(point_names[index]))
        sources.append(str(point_sources[index]))

    return NearestResult(distances=np.array(distances), names=names, sources=sources)


def amenity_route_candidates(
    reference_points: gpd.GeoSeries,
    points: gpd.GeoDataFrame,
    *,
    candidate_count: int,
    mode: str,
    route_source: str,
    travel_time_config: dict,
) -> AmenityRouteResult:
    if points.empty:
        distances = np.full(len(reference_points), np.nan)
        times = np.full(len(reference_points), np.nan)
        return AmenityRouteResult(
            distances=distances,
            times=times,
            names=[""] * len(reference_points),
            sources=[""] * len(reference_points),
            candidate_pairs=0,
            estimated_pairs=0,
        )

    point_x = points.geometry.x.to_numpy()
    point_y = points.geometry.y.to_numpy()
    point_names = points["name"].fillna("Unnamed").astype(str).to_numpy()
    point_sources = (
        points["source"].fillna("unknown").astype(str).to_numpy()
        if "source" in points.columns
        else np.array(["unknown"] * len(points))
    )
    limit = min(candidate_count, len(points))

    distances: list[float] = []
    times: list[float] = []
    names: list[str] = []
    sources: list[str] = []
    candidate_pairs = 0
    estimated_pairs = 0

    for reference_point in reference_points:
        squared = np.square(point_x - reference_point.x) + np.square(
            point_y - reference_point.y
        )
        if limit == len(points):
            candidate_indexes = np.argsort(squared)
        else:
            candidate_indexes = np.argpartition(squared, limit - 1)[:limit]
            candidate_indexes = candidate_indexes[np.argsort(squared[candidate_indexes])]

        candidate_distances = np.sqrt(squared[candidate_indexes]).astype(float)
        candidate_times = estimate_travel_minutes(
            candidate_distances,
            mode,
            travel_time_config,
        )
        candidate_pairs += len(candidate_indexes)
        if route_source == "fallback_straight_line_estimate":
            estimated_pairs += len(candidate_indexes)

        best_offset = int(np.nanargmin(candidate_times))
        best_index = int(candidate_indexes[best_offset])
        distances.append(float(candidate_distances[best_offset]))
        times.append(float(candidate_times[best_offset]))
        names.append(str(point_names[best_index]))
        sources.append(str(point_sources[best_index]))

    return AmenityRouteResult(
        distances=np.array(distances),
        times=np.array(times),
        names=names,
        sources=sources,
        candidate_pairs=candidate_pairs,
        estimated_pairs=estimated_pairs,
    )


def distance_score(distances: np.ndarray) -> np.ndarray:
    valid = distances[np.isfinite(distances)]
    if len(valid) == 0:
        return np.zeros_like(distances, dtype=float)
    cap = float(np.nanpercentile(valid, 95))
    if cap <= 0:
        cap = float(np.nanmax(valid)) or 1.0
    clipped = np.clip(distances, 0, cap)
    scores = 100.0 * (1.0 - clipped / cap)
    scores[~np.isfinite(scores)] = 0.0
    return scores


def estimate_travel_minutes(
    distances_m: np.ndarray, mode: str, travel_time_config: dict
) -> np.ndarray:
    speeds = travel_time_config["speeds_kmh"]
    detour_factors = travel_time_config["detour_factors"]
    speed_kmh = float(speeds.get(mode, 0))
    detour_factor = float(detour_factors.get(mode, 1))
    if speed_kmh <= 0:
        return np.full_like(distances_m, np.nan, dtype=float)
    meters_per_minute = speed_kmh * 1000 / 60
    minutes = distances_m.astype(float) * detour_factor / meters_per_minute
    minutes[~np.isfinite(minutes)] = np.nan
    return minutes


def inverse_density_score(values: np.ndarray) -> np.ndarray:
    valid = values[np.isfinite(values)]
    if len(valid) == 0:
        return np.zeros_like(values, dtype=float)
    cap = float(np.nanpercentile(valid, 95))
    if cap <= 0:
        cap = float(np.nanmax(valid)) or 1.0
    clipped = np.clip(values, 0, cap)
    scores = 100.0 * (1.0 - clipped / cap)
    scores[~np.isfinite(scores)] = 0.0
    return scores


def round_distance(values: np.ndarray) -> list[int]:
    clean = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    return np.rint(clean).astype(int).tolist()


def round_score(values: np.ndarray) -> list[float]:
    clean = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    return np.round(np.clip(clean, 0, 100), 1).tolist()


def round_minutes(values: np.ndarray) -> list[float]:
    clean = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    return np.round(np.clip(clean, 0, None), 1).tolist()


def nullable_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def workplace_coordinates(places_config: dict, workplaces: gpd.GeoDataFrame) -> tuple[float, float] | None:
    configured = places_config.get("workplace", {})
    latitude = nullable_number(configured.get("latitude"))
    longitude = nullable_number(configured.get("longitude"))
    if latitude is not None and longitude is not None:
        return latitude, longitude
    if workplaces.empty:
        return None
    first_workplace = workplaces.to_crs(WGS84_CRS).geometry.iloc[0]
    return float(first_workplace.y), float(first_workplace.x)


def failed_transit_commute_frame(
    areas: gpd.GeoDataFrame,
    source: str,
    notes: str,
) -> pd.DataFrame:
    rows = []
    for _, area in areas.iterrows():
        row = {column: None for column in TRANSIT_COMMUTE_OUTPUT_COLUMNS}
        row["area_unit"] = area.get("area_unit", "")
        row["area_id"] = area.get("area_id", "")
        row["score_work_transit"] = None
        row["transit_commute_source"] = source
        row["transit_commute_notes"] = notes
        rows.append(row)
    return pd.DataFrame(rows, columns=TRANSIT_COMMUTE_OUTPUT_COLUMNS)


def ensure_transit_commute_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in TRANSIT_COMMUTE_OUTPUT_COLUMNS:
        if column not in output.columns:
            output[column] = None
    return output[TRANSIT_COMMUTE_OUTPUT_COLUMNS]


def build_transit_commute_frame(
    areas: gpd.GeoDataFrame,
    point_datasets: PointDatasets,
    places_config: dict,
    config: TransitCommuteConfig,
) -> pd.DataFrame:
    coordinates = workplace_coordinates(places_config, point_datasets.workplaces)
    if coordinates is None:
        print("WARNING: Transit commute skipped because no workplace coordinates exist.")
        return failed_transit_commute_frame(
            areas,
            TRANSIT_COMMUTE_NOT_CONFIGURED_SOURCE,
            "Transit commute was not estimated because no workplace coordinates were configured.",
        )

    try:
        return ensure_transit_commute_columns(
            estimate_transit_commute_to_work(
                areas,
                point_datasets.transit,
                workplace_lat=coordinates[0],
                workplace_lon=coordinates[1],
                config=config,
            )
        )
    except Exception as exc:  # noqa: BLE001 - keep score generation robust.
        print(f"WARNING: Transit commute estimation failed: {exc}")
        return failed_transit_commute_frame(
            areas,
            TRANSIT_COMMUTE_FAILED_SOURCE,
            f"Transit commute estimation failed during preprocessing: {exc}",
        )


def normalize_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def load_r5py_metadata(csv_path: Path) -> dict:
    metadata_path = csv_path.with_suffix(".metadata.json")
    if not metadata_path.exists():
        return {}
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"WARNING: Could not parse r5py metadata {metadata_path}: {exc}")
        return {"metadata_error": str(exc)}


def transit_commute_r5py_csv_path(area_unit: str) -> Path:
    return DATA_PROCESSED / f"transit_commute_r5py_{area_unit}.csv"


def apply_r5py_transit_commute(
    *,
    area_unit: str,
    transit_commute: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    csv_path = transit_commute_r5py_csv_path(area_unit)
    result = ensure_transit_commute_columns(transit_commute)
    router_info = {
        "engine": TRANSIT_ROUTER_R5PY,
        "fallback_engine": TRANSIT_ROUTER_APIMETRO,
        "csv_path": repo_relative(csv_path),
        "status": "not_loaded",
        "gtfs_sha1": None,
        "osm_source": R5PY_OSM_SOURCE,
        "service_date": None,
        "departure_window_minutes": None,
        "routed_count": 0,
        "failed_count": int(len(result)),
    }

    if not csv_path.exists():
        print(f"WARNING: r5py transit CSV missing at {csv_path}; using Apimetro fallback.")
        router_info["status"] = "missing_csv"
        return result, router_info

    metadata = load_r5py_metadata(csv_path)
    router_info.update(
        {
            "status": "loaded",
            "metadata_path": repo_relative(csv_path.with_suffix(".metadata.json")),
            "gtfs_sha1": metadata.get("gtfs_sha1"),
            "osm_source": metadata.get("osm_source") or R5PY_OSM_SOURCE,
            "osm_sha1": metadata.get("osm_sha1"),
            "service_date": metadata.get("service_date"),
            "departure_time": metadata.get("departure_time"),
            "departure_window_minutes": metadata.get("departure_window_minutes"),
            "max_time_minutes": metadata.get("max_time_minutes"),
            "global_error": metadata.get("global_error"),
        }
    )

    try:
        r5py = pd.read_csv(csv_path, dtype={"area_id": str})
    except Exception as exc:  # noqa: BLE001 - keep opt-in fallback robust.
        print(f"WARNING: Could not read r5py transit CSV {csv_path}: {exc}")
        router_info["status"] = "read_failed"
        router_info["error"] = str(exc)
        return result, router_info

    required = {
        "area_id",
        "time_work_transit_min",
        "routed_successfully",
        "transit_commute_source",
    }
    missing = sorted(required - set(r5py.columns))
    if missing:
        print(
            "WARNING: r5py transit CSV is missing required columns "
            f"{', '.join(missing)}; using Apimetro fallback."
        )
        router_info["status"] = "invalid_csv"
        router_info["missing_columns"] = missing
        return result, router_info

    r5py = r5py.copy()
    r5py["area_id"] = r5py["area_id"].fillna("").astype(str)
    if area_unit == "postal_code":
        r5py["area_id"] = r5py["area_id"].str.zfill(5)
    r5py["routed_successfully"] = r5py["routed_successfully"].map(normalize_bool)
    r5py["time_work_transit_min"] = pd.to_numeric(
        r5py["time_work_transit_min"], errors="coerce"
    )
    if "time_work_transit_p75_min" not in r5py.columns:
        r5py["time_work_transit_p75_min"] = np.nan
    r5py["time_work_transit_p75_min"] = pd.to_numeric(
        r5py["time_work_transit_p75_min"], errors="coerce"
    )
    successful = r5py[
        r5py["routed_successfully"] & r5py["time_work_transit_min"].notna()
    ].drop_duplicates("area_id", keep="first")
    successful = successful.set_index("area_id")

    matched_area_ids = result["area_id"].fillna("").astype(str).isin(successful.index)
    if matched_area_ids.any():
        result_area_ids = result.loc[matched_area_ids, "area_id"].astype(str)
        median_values = result_area_ids.map(successful["time_work_transit_min"])
        p75_values = result_area_ids.map(successful["time_work_transit_p75_min"])
        result.loc[matched_area_ids, "time_work_transit_min"] = median_values.round(1).to_numpy()
        result.loc[matched_area_ids, "time_work_transit_p75_min"] = p75_values.round(1).to_numpy()
        result.loc[matched_area_ids, "score_work_transit"] = [
            nullable_round(score_transit_commute_minutes(value), 1)
            for value in median_values
        ]
        result.loc[matched_area_ids, "transit_commute_source"] = R5PY_TRANSIT_COMMUTE_SOURCE
        result.loc[matched_area_ids, "transit_commute_notes"] = (
            "Schedule-aware r5py route using CDMX GTFS and BBBike MexicoCity OSM. "
            "Stop names remain Apimetro nearest-stop context, not r5py itinerary legs."
        )

    routed_count = int(matched_area_ids.sum())
    router_info["routed_count"] = routed_count
    router_info["failed_count"] = int(len(result) - routed_count)
    router_info["coverage_percent"] = (
        round((routed_count / len(result)) * 100, 1) if len(result) else 0.0
    )
    if metadata:
        router_info["prototype_metadata"] = {
            key: value
            for key, value in metadata.items()
            if key not in {"global_traceback"}
        }
    return result, router_info


def nullable_round(value: object, digits: int) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return round(numeric, digits)


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def transit_route_summary(row: pd.Series) -> str:
    origin_name = str(row.get("transit_origin_stop_name") or "").strip()
    origin_system = str(row.get("transit_origin_system") or "").strip()
    destination_name = str(row.get("transit_destination_stop_name") or "").strip()
    destination_system = str(row.get("transit_destination_system") or "").strip()
    if not origin_name or not destination_name:
        return ""
    origin = f"{origin_system} {origin_name}".strip()
    destination = f"{destination_system} {destination_name}".strip()
    return f"{origin} -> {destination}"


def read_crimes(path: Path) -> gpd.GeoDataFrame:
    if not path.exists():
        return gpd.GeoDataFrame(
            columns=[
                "date",
                "category",
                "offense",
                "borough",
                "latitude",
                "longitude",
                "source",
            ],
            geometry=[],
            crs=WGS84_CRS,
        ).to_crs(METRIC_CRS)

    df = pd.read_csv(path)
    if df.empty:
        return gpd.GeoDataFrame(df, geometry=[], crs=WGS84_CRS).to_crs(METRIC_CRS)

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["date", "latitude", "longitude"]).copy()
    if "category" not in df.columns:
        df["category"] = "Sin categoria"
    if "offense" not in df.columns:
        df["offense"] = "Sin delito"
    if "source" not in df.columns:
        df["source"] = "fgj_cdmx_victimas"

    crimes = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["longitude"], df["latitude"]),
        crs=WGS84_CRS,
    )
    return crimes.to_crs(METRIC_CRS)


def aggregate_crime(
    areas_metric: gpd.GeoDataFrame, crimes: gpd.GeoDataFrame
) -> tuple[pd.DataFrame, dict]:
    columns = [
        "area_id",
        "crime_incidents_total",
        "crime_incidents_recent_12m",
        "crime_density_recent_12m_per_km2",
        "crime_top_category_recent_12m",
        "crime_source",
    ]
    empty = pd.DataFrame(
        {
            "area_id": areas_metric["area_id"],
            "crime_incidents_total": 0,
            "crime_incidents_recent_12m": 0,
            "crime_density_recent_12m_per_km2": 0.0,
            "crime_top_category_recent_12m": "",
            "crime_source": "",
        },
        columns=columns,
    )
    if crimes.empty:
        return empty, {
            "records_total": 0,
            "records_recent_12m": 0,
            "latest_date": None,
            "recent_start_date": None,
        }

    area_lookup = areas_metric[["area_id", "geometry"]].copy()
    joined = gpd.sjoin(
        crimes,
        area_lookup,
        how="inner",
        predicate="within",
    )
    if joined.empty:
        return empty, {
            "records_total": int(len(crimes)),
            "records_recent_12m": 0,
            "latest_date": None,
            "recent_start_date": None,
        }

    latest_date = joined["date"].max()
    recent_start = latest_date - pd.DateOffset(months=12)
    recent = joined[joined["date"] >= recent_start].copy()

    totals = joined.groupby("area_id").size().rename("crime_incidents_total")
    recent_counts = recent.groupby("area_id").size().rename("crime_incidents_recent_12m")
    if recent.empty:
        top_categories = pd.Series(dtype=str, name="crime_top_category_recent_12m")
    else:
        top_categories = (
            recent.groupby("area_id")["category"]
            .agg(lambda series: series.value_counts().idxmax())
            .rename("crime_top_category_recent_12m")
        )

    area_km2 = areas_metric.set_index("area_id").geometry.area / 1_000_000
    aggregated = (
        pd.DataFrame({"area_id": areas_metric["area_id"]})
        .merge(totals, on="area_id", how="left")
        .merge(recent_counts, on="area_id", how="left")
        .merge(top_categories, on="area_id", how="left")
    )
    aggregated["crime_incidents_total"] = (
        aggregated["crime_incidents_total"].fillna(0).astype(int)
    )
    aggregated["crime_incidents_recent_12m"] = (
        aggregated["crime_incidents_recent_12m"].fillna(0).astype(int)
    )
    aggregated["crime_density_recent_12m_per_km2"] = (
        aggregated["crime_incidents_recent_12m"]
        / aggregated["area_id"].map(area_km2).replace(0, np.nan)
    ).fillna(0.0)
    aggregated["crime_top_category_recent_12m"] = aggregated[
        "crime_top_category_recent_12m"
    ].fillna("")
    aggregated["crime_source"] = "fgj_cdmx_victimas"

    return aggregated[columns], {
        "records_total": int(len(joined)),
        "records_recent_12m": int(len(recent)),
        "latest_date": latest_date.strftime("%Y-%m-%d"),
        "recent_start_date": recent_start.strftime("%Y-%m-%d"),
    }


def load_point_datasets(places_config: dict) -> PointDatasets:
    transit = read_points(DATA_PROCESSED / "transit_stops.csv")
    supermarkets = read_points(DATA_PROCESSED / "supermarkets.csv")
    gyms = read_points(DATA_PROCESSED / "gyms.csv")
    workplaces = load_workplaces(places_config)
    crimes = read_crimes(DATA_PROCESSED / "crime_points.csv")

    supermarket_brand = (
        supermarkets["brand"].fillna("").astype(str).str.lower()
        if "brand" in supermarkets.columns
        else pd.Series([""] * len(supermarkets), index=supermarkets.index)
    )
    costcos = supermarkets[supermarket_brand.str.contains("costco", na=False)].copy()
    walmarts = supermarkets[supermarket_brand.str.contains("walmart", na=False)].copy()

    if "system" in transit.columns:
        transit_system = transit["system"].fillna("").astype(str).str.upper()
        core_transit = transit[transit_system.isin(CORE_TRANSIT_SYSTEMS)].copy()
        surface_transit = transit[transit_system.isin(SURFACE_TRANSIT_SYSTEMS)].copy()
    else:
        core_transit = transit
        surface_transit = transit

    return PointDatasets(
        transit=transit,
        core_transit=core_transit,
        surface_transit=surface_transit,
        supermarkets=supermarkets,
        costcos=costcos,
        walmarts=walmarts,
        gyms=gyms,
        workplaces=workplaces,
        crimes=crimes,
    )


def score_areas(
    *,
    config: AreaConfig,
    input_path: Path,
    point_datasets: PointDatasets,
    places_config: dict,
    transit_router: str = TRANSIT_ROUTER_APIMETRO,
) -> ScoredAreaResult:
    areas = prepare_area_properties(load_area_geometries(input_path), config)
    areas_metric = areas.to_crs(METRIC_CRS)
    areas_metric["geometry"] = areas_metric.geometry.make_valid()
    reference_points = areas_metric.geometry.representative_point()
    reference_wgs84 = gpd.GeoSeries(reference_points, crs=METRIC_CRS).to_crs(WGS84_CRS)
    travel_time_config = merged_travel_time_config(places_config)
    amenity_time_config = amenity_travel_time_config(places_config, travel_time_config)
    work_transit_config = transit_commute_config(places_config)

    nearest_work = nearest(reference_points, point_datasets.workplaces)
    nearest_transit = nearest(reference_points, point_datasets.transit)
    nearest_core_transit = nearest(
        reference_points,
        point_datasets.core_transit
        if not point_datasets.core_transit.empty
        else point_datasets.transit,
    )
    nearest_surface_transit = nearest(
        reference_points,
        point_datasets.surface_transit
        if not point_datasets.surface_transit.empty
        else point_datasets.transit,
    )
    nearest_supermarket = nearest(reference_points, point_datasets.supermarkets)
    nearest_costco = nearest(
        reference_points,
        point_datasets.costcos
        if not point_datasets.costcos.empty
        else point_datasets.supermarkets,
    )
    nearest_walmart = nearest(
        reference_points,
        point_datasets.walmarts
        if not point_datasets.walmarts.empty
        else point_datasets.supermarkets,
    )
    nearest_gym = nearest(reference_points, point_datasets.gyms)
    routed_supermarket = amenity_route_candidates(
        reference_points,
        point_datasets.supermarkets,
        candidate_count=amenity_time_config["candidate_count"],
        mode=amenity_time_config["mode"],
        route_source=amenity_time_config["source"],
        travel_time_config=travel_time_config,
    )
    routed_costco = amenity_route_candidates(
        reference_points,
        point_datasets.costcos
        if not point_datasets.costcos.empty
        else point_datasets.supermarkets,
        candidate_count=amenity_time_config["candidate_count"],
        mode=amenity_time_config["mode"],
        route_source=amenity_time_config["source"],
        travel_time_config=travel_time_config,
    )
    routed_walmart = amenity_route_candidates(
        reference_points,
        point_datasets.walmarts
        if not point_datasets.walmarts.empty
        else point_datasets.supermarkets,
        candidate_count=amenity_time_config["candidate_count"],
        mode=amenity_time_config["mode"],
        route_source=amenity_time_config["source"],
        travel_time_config=travel_time_config,
    )
    routed_gym = amenity_route_candidates(
        reference_points,
        point_datasets.gyms,
        candidate_count=amenity_time_config["candidate_count"],
        mode=amenity_time_config["mode"],
        route_source=amenity_time_config["source"],
        travel_time_config=travel_time_config,
    )
    transit_commute = build_transit_commute_frame(
        areas,
        point_datasets,
        places_config,
        work_transit_config,
    )
    transit_router_info = {
        "engine": TRANSIT_ROUTER_APIMETRO,
        "source": work_transit_config.source,
        "routed_count": int(transit_commute["time_work_transit_min"].notna().sum()),
        "failed_count": int(len(transit_commute) - transit_commute["time_work_transit_min"].notna().sum()),
    }
    if transit_router == TRANSIT_ROUTER_R5PY:
        transit_commute, transit_router_info = apply_r5py_transit_commute(
            area_unit=config.area_unit,
            transit_commute=transit_commute,
        )
    transit_commute = ensure_transit_commute_columns(transit_commute)
    transit_commute = transit_commute.set_index("area_id").reindex(areas["area_id"])

    score_work = distance_score(nearest_work.distances)
    work_times = {
        mode: estimate_travel_minutes(
            nearest_work.distances,
            mode,
            travel_time_config,
        )
        for mode in WORK_TRAVEL_MODES
    }
    score_work_times = {
        mode: distance_score(minutes) for mode, minutes in work_times.items()
    }
    score_core_transit = distance_score(nearest_core_transit.distances)
    score_surface_transit = distance_score(nearest_surface_transit.distances)
    score_transit = (0.70 * score_core_transit) + (0.30 * score_surface_transit)
    score_supermarkets = distance_score(nearest_supermarket.distances)
    score_gyms = distance_score(nearest_gym.distances)
    score_supermarkets_time = distance_score(routed_supermarket.times)
    score_gyms_time = distance_score(routed_gym.times)
    crime_aggregation, crime_metadata = aggregate_crime(
        areas_metric, point_datasets.crimes
    )
    crime_aggregation = crime_aggregation.set_index("area_id").reindex(areas["area_id"])
    score_safety = inverse_density_score(
        crime_aggregation["crime_density_recent_12m_per_km2"].to_numpy(dtype=float)
    )
    combined = (
        DEFAULT_WEIGHTS["work"] * score_work
        + DEFAULT_WEIGHTS["transit"] * score_transit
        + DEFAULT_WEIGHTS["supermarkets"] * score_supermarkets
        + DEFAULT_WEIGHTS["gyms"] * score_gyms
        + DEFAULT_WEIGHTS["safety"] * score_safety
    )

    # Keep the historical centroid_* field names for frontend compatibility, but
    # populate them with representative points that are guaranteed to sit inside
    # the scored polygon.
    areas["centroid_lat"] = np.round(reference_wgs84.y.to_numpy(), 6)
    areas["centroid_lon"] = np.round(reference_wgs84.x.to_numpy(), 6)
    areas["dist_work_m"] = round_distance(nearest_work.distances)
    areas["dist_transit_m"] = round_distance(nearest_transit.distances)
    areas["dist_core_transit_m"] = round_distance(nearest_core_transit.distances)
    areas["dist_surface_transit_m"] = round_distance(nearest_surface_transit.distances)
    areas["dist_supermarket_m"] = round_distance(nearest_supermarket.distances)
    areas["dist_costco_m"] = round_distance(nearest_costco.distances)
    areas["dist_walmart_m"] = round_distance(nearest_walmart.distances)
    areas["dist_gym_m"] = round_distance(nearest_gym.distances)
    areas["time_supermarket_min"] = round_minutes(routed_supermarket.times)
    areas["time_costco_min"] = round_minutes(routed_costco.times)
    areas["time_walmart_min"] = round_minutes(routed_walmart.times)
    areas["time_gym_min"] = round_minutes(routed_gym.times)
    areas["score_work"] = round_score(score_work)
    for mode in WORK_TRAVEL_MODES:
        areas[f"time_work_{mode}_min"] = round_minutes(work_times[mode])
        areas[f"score_work_{mode}"] = round_score(score_work_times[mode])
    areas["score_transit"] = round_score(score_transit)
    areas["score_supermarkets"] = round_score(score_supermarkets)
    areas["score_supermarkets_time"] = round_score(score_supermarkets_time)
    areas["score_gyms"] = round_score(score_gyms)
    areas["score_gyms_time"] = round_score(score_gyms_time)
    areas["score_safety"] = round_score(score_safety)
    areas["score_combined_default"] = round_score(combined)
    areas["nearest_work_name"] = nearest_work.names
    areas["nearest_transit_name"] = nearest_transit.names
    areas["nearest_core_transit_name"] = nearest_core_transit.names
    areas["nearest_surface_transit_name"] = nearest_surface_transit.names
    areas["nearest_supermarket_name"] = nearest_supermarket.names
    areas["nearest_costco_name"] = nearest_costco.names
    areas["nearest_walmart_name"] = nearest_walmart.names
    areas["nearest_gym_name"] = nearest_gym.names
    areas["nearest_work_source"] = nearest_work.sources
    areas["work_travel_time_source"] = travel_time_config["source"]
    areas["nearest_transit_source"] = nearest_transit.sources
    areas["nearest_core_transit_source"] = nearest_core_transit.sources
    areas["nearest_surface_transit_source"] = nearest_surface_transit.sources
    areas["nearest_supermarket_source"] = nearest_supermarket.sources
    areas["nearest_costco_source"] = nearest_costco.sources
    areas["nearest_walmart_source"] = nearest_walmart.sources
    areas["nearest_gym_source"] = nearest_gym.sources
    areas["amenity_travel_time_source"] = amenity_time_config["source"]
    for column in TRANSIT_COMMUTE_OUTPUT_COLUMNS:
        if column in {"area_unit", "area_id"}:
            continue
        values = transit_commute[column] if column in transit_commute.columns else None
        if values is None:
            areas[column] = [None] * len(areas)
        else:
            areas[column] = values.astype("object").where(pd.notna(values), None).tolist()
    areas["transfers_work_transit"] = [
        0 if complexity == "same_line" else 1 if isinstance(complexity, str) else None
        for complexity in areas["transit_route_complexity"]
    ]
    areas["walk_to_origin_stop_m"] = areas["transit_origin_walk_m"]
    areas["destination_walk_m"] = areas["transit_destination_walk_m"]
    areas["transit_route_summary"] = [
        transit_route_summary(row)
        for _, row in areas[
            [
                "transit_origin_stop_name",
                "transit_origin_system",
                "transit_destination_stop_name",
                "transit_destination_system",
            ]
        ].iterrows()
    ]
    areas["crime_incidents_total"] = (
        crime_aggregation["crime_incidents_total"].fillna(0).astype(int).tolist()
    )
    areas["crime_incidents_recent_12m"] = (
        crime_aggregation["crime_incidents_recent_12m"].fillna(0).astype(int).tolist()
    )
    areas["crime_density_recent_12m_per_km2"] = (
        np.round(
            crime_aggregation["crime_density_recent_12m_per_km2"]
            .fillna(0)
            .to_numpy(dtype=float),
            1,
        ).tolist()
    )
    areas["crime_top_category_recent_12m"] = (
        crime_aggregation["crime_top_category_recent_12m"].fillna("").astype(str).tolist()
    )
    areas["crime_source"] = (
        crime_aggregation["crime_source"].fillna("").astype(str).tolist()
    )

    output = areas.to_crs(WGS84_CRS)
    output["geometry"] = (
        areas_metric.geometry.simplify(8, preserve_topology=True).to_crs(WGS84_CRS)
    )

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    transit_estimated = int(transit_commute["time_work_transit_min"].notna().sum())
    transit_sources = (
        transit_commute["transit_commute_source"].fillna("unknown").value_counts().to_dict()
    )
    metadata = {
        "generated_at": generated_at,
        "area_unit": config.area_unit,
        "feature_count": int(len(output)),
        "crime": crime_metadata,
        "workplace": {
            "name": places_config.get("workplace", {}).get("name"),
            "postal_code": places_config.get("workplace", {}).get("postal_code"),
            "source": places_config.get("workplace", {}).get("source"),
        },
        "travel_time": {
            "source": travel_time_config["source"],
            "modes": list(WORK_TRAVEL_MODES),
            "speeds_kmh": travel_time_config["speeds_kmh"],
            "detour_factors": travel_time_config["detour_factors"],
        },
        "amenity_travel_time": {
            "source": amenity_time_config["source"],
            "mode": amenity_time_config["mode"],
            "candidate_count": amenity_time_config["candidate_count"],
            "candidate_pairs": {
                "supermarkets": routed_supermarket.candidate_pairs,
                "costco": routed_costco.candidate_pairs,
                "walmart": routed_walmart.candidate_pairs,
                "gyms": routed_gym.candidate_pairs,
            },
            "estimated_pairs": {
                "supermarkets": routed_supermarket.estimated_pairs,
                "costco": routed_costco.estimated_pairs,
                "walmart": routed_walmart.estimated_pairs,
                "gyms": routed_gym.estimated_pairs,
            },
        },
        "transit_commute": {
            **transit_commute_metadata(work_transit_config),
            "generated_at": generated_at,
            "engine": transit_router_info.get("engine", TRANSIT_ROUTER_APIMETRO),
            "router": transit_router_info,
            "transit_commute_source": (
                R5PY_TRANSIT_COMMUTE_SOURCE
                if transit_router == TRANSIT_ROUTER_R5PY
                else work_transit_config.source
            ),
            "estimated_areas": transit_estimated,
            "failed_areas": int(len(output) - transit_estimated),
            "source_counts": {str(key): int(value) for key, value in transit_sources.items()},
        },
        "notes": [
            "Distances are straight-line representative-point-to-point distances in meters.",
            "The centroid_lat and centroid_lon properties are retained for compatibility and now store representative points.",
            "Scores are closer-is-better and clipped at the 95th percentile per metric.",
            "Work travel times are offline fallback estimates unless the travel_time source is replaced with cached routing results.",
            (
                "Work transit commute uses opt-in r5py schedule-aware routing where available, "
                "with Apimetro approximation fallback."
                if transit_router == TRANSIT_ROUTER_R5PY
                else "Work transit commute uses an offline Apimetro stop-pair approximation and is not schedule-aware."
            ),
            "Amenity travel times consider only the nearest configured candidate POIs before routing or fallback estimation.",
            "Transit score is 70% nearest Metro/Metrobus/Trolebus and 30% nearest RTP/Corredor Concesionado.",
            "Safety score is lower-is-better crime density using the latest 12 months available in the FGJ file.",
        ],
    }
    return ScoredAreaResult(output=output, metadata=metadata)


def write_geojson(output: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output.to_file(path, driver="GeoJSON")
    print(f"Wrote {path}")


def build_metadata(
    *,
    config: AreaConfig,
    input_path: Path,
    output_path: Path,
    public_output_path: Path,
    legacy_output_paths: list[Path],
    public_legacy_output_paths: list[Path],
    point_datasets: PointDatasets,
    score_metadata: dict,
    places_config: dict,
) -> dict:
    def repo_path(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(ROOT))
        except ValueError:
            return str(path)

    source_urls = {
        config.source_url_key: config.source_url,
        "transit_apimetro": "https://apimetro.dev/docs",
        "transit_gtfs_cdmx": (
            "https://datos.cdmx.gob.mx/dataset/75538d96-3ade-4bc5-ae7d-d85595e4522d/"
            "resource/32ed1b6b-41cd-49b3-b7f0-b57acb0eb819/download/gtfs-2.zip"
        ),
        "osm_bbbike_mexico_city": R5PY_OSM_SOURCE,
        "openstreetmap_overpass": "https://overpass-api.de/api/interpreter",
        "crime_victims_fgj": "https://datos.cdmx.gob.mx/dataset/victimas-en-carpetas-de-investigacion-fgj/resource/d543a7b1-f8cb-439f-8a5c-e56c5479eeb5",
    }
    source_urls = {key: value for key, value in source_urls.items() if value}

    return {
        "generated_at": score_metadata["generated_at"],
        "area_unit": config.area_unit,
        "feature_count": score_metadata["feature_count"],
        "weights": DEFAULT_WEIGHTS,
        "point_counts": {
            "transit_stops": int(len(point_datasets.transit)),
            "transit_core_points": int(len(point_datasets.core_transit)),
            "transit_surface_points": int(len(point_datasets.surface_transit)),
            "supermarkets": int(len(point_datasets.supermarkets)),
            "gyms": int(len(point_datasets.gyms)),
            "workplaces": int(len(point_datasets.workplaces)),
            "crime_records": int(len(point_datasets.crimes)),
        },
        "crime": score_metadata["crime"],
        "workplace": score_metadata["workplace"],
        "travel_time": score_metadata["travel_time"],
        "amenity_travel_time": score_metadata["amenity_travel_time"],
        "transit_commute_source": score_metadata["transit_commute"][
            "transit_commute_source"
        ],
        "transit_commute": score_metadata["transit_commute"],
        "source_urls": source_urls,
        "sources": {
            "areas": repo_path(input_path),
            config.area_unit: repo_path(input_path),
            "places_config": repo_path(DATA_CONFIG / "places.json"),
            "transit_stops": repo_path(DATA_PROCESSED / "transit_stops.csv"),
            "supermarkets": repo_path(DATA_PROCESSED / "supermarkets.csv"),
            "gyms": repo_path(DATA_PROCESSED / "gyms.csv"),
            "workplaces_legacy_csv": repo_path(DATA_RAW / "workplaces.csv"),
            "crime_points": repo_path(DATA_PROCESSED / "crime_points.csv"),
        },
        "outputs": {
            "processed": repo_path(output_path),
            "public": repo_path(public_output_path),
            "legacy_processed": [repo_path(path) for path in legacy_output_paths],
            "legacy_public": [repo_path(path) for path in public_legacy_output_paths],
        },
        "notes": score_metadata["notes"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build scored area GeoJSON for a configured CDMX area unit."
    )
    parser.add_argument(
        "--area-unit",
        choices=sorted(AREA_CONFIGS),
        default="postal_code",
        help="Area unit to score. Only postal_code has a checked-in fetch pipeline today.",
    )
    parser.add_argument(
        "--input-area-geojson",
        type=Path,
        help="Override the configured area GeoJSON input path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Override the processed scored GeoJSON output path.",
    )
    parser.add_argument(
        "--skip-legacy",
        action="store_true",
        help="Do not write legacy output aliases such as cdmx_postal_scores.geojson.",
    )
    parser.add_argument(
        "--transit-router",
        choices=[TRANSIT_ROUTER_APIMETRO, TRANSIT_ROUTER_R5PY],
        default=TRANSIT_ROUTER_APIMETRO,
        help=(
            "Transit commute router to use. Defaults to the existing Apimetro "
            "approximation; r5py overlays cached schedule-aware CSV results when present."
        ),
    )
    return parser.parse_args()


def main() -> None:
    ensure_dirs()
    args = parse_args()
    config = AREA_CONFIGS[args.area_unit]
    input_path = args.input_area_geojson or config.default_input_path
    output_path = args.output or DATA_PROCESSED / config.output_name
    public_output_path = FRONTEND_PUBLIC_DATA / output_path.name

    places_config = load_places_config()
    point_datasets = load_point_datasets(places_config)
    scored = score_areas(
        config=config,
        input_path=input_path,
        point_datasets=point_datasets,
        places_config=places_config,
        transit_router=args.transit_router,
    )

    write_geojson(scored.output, output_path)
    shutil.copyfile(output_path, public_output_path)
    print(f"Copied frontend asset to {public_output_path}")

    legacy_output_paths: list[Path] = []
    public_legacy_output_paths: list[Path] = []
    if not args.skip_legacy:
        for legacy_name in config.legacy_output_names:
            legacy_path = DATA_PROCESSED / legacy_name
            public_legacy_path = FRONTEND_PUBLIC_DATA / legacy_name
            shutil.copyfile(output_path, legacy_path)
            shutil.copyfile(output_path, public_legacy_path)
            legacy_output_paths.append(legacy_path)
            public_legacy_output_paths.append(public_legacy_path)
            print(f"Copied legacy asset to {legacy_path}")
            print(f"Copied legacy frontend asset to {public_legacy_path}")

    metadata = build_metadata(
        config=config,
        input_path=input_path,
        output_path=output_path,
        public_output_path=public_output_path,
        legacy_output_paths=legacy_output_paths,
        public_legacy_output_paths=public_legacy_output_paths,
        point_datasets=point_datasets,
        score_metadata=scored.metadata,
        places_config=places_config,
    )
    metadata_path = DATA_PROCESSED / f"score_metadata_{config.area_unit}.json"
    public_metadata_path = FRONTEND_PUBLIC_DATA / metadata_path.name
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    shutil.copyfile(metadata_path, public_metadata_path)

    legacy_metadata_path = DATA_PROCESSED / "score_metadata.json"
    legacy_public_metadata_path = FRONTEND_PUBLIC_DATA / "score_metadata.json"
    shutil.copyfile(metadata_path, legacy_metadata_path)
    shutil.copyfile(metadata_path, legacy_public_metadata_path)

    print(f"Wrote {metadata_path}")
    print(f"Copied frontend metadata to {public_metadata_path}")
    print(f"Copied legacy metadata to {legacy_metadata_path}")
    print(f"Copied legacy frontend metadata to {legacy_public_metadata_path}")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
