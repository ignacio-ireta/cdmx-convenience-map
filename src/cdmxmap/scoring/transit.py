"""Transit-commute frame assembly and the opt-in r5py schedule-aware overlay."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from cdmxmap.config import (
    METRIC_CRS,
    R5PY_OSM_SOURCE,
    R5PY_TRANSIT_COMMUTE_SOURCE,
    TRANSIT_COMMUTE_FAILED_SOURCE,
    TRANSIT_COMMUTE_NOT_CONFIGURED_SOURCE,
    TRANSIT_COMMUTE_OUTPUT_COLUMNS,
    TRANSIT_ROUTER_APIMETRO,
    TRANSIT_ROUTER_R5PY,
)
from cdmxmap.models import PointDatasets
from cdmxmap.scoring.metrics import nullable_round
from cdmxmap.scoring.points import workplace_coordinates
from cdmxmap.sources.io import DATA_PROCESSED, ROOT
from cdmxmap.transit_commute import (
    TransitCommuteConfig,
    estimate_transit_commute_to_work,
    score_transit_commute_minutes,
)

logger = logging.getLogger(__name__)


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


def failed_transit_commute_frame(
    areas: gpd.GeoDataFrame,
    source: str,
    notes: str,
) -> pd.DataFrame:
    rows = []
    for _, area in areas.iterrows():
        row: dict[str, object] = {column: None for column in TRANSIT_COMMUTE_OUTPUT_COLUMNS}
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
    *,
    metric_crs: str = METRIC_CRS,
) -> pd.DataFrame:
    coordinates = workplace_coordinates(places_config, point_datasets.workplaces)
    if coordinates is None:
        logger.warning("Transit commute skipped because no workplace coordinates exist.")
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
                metric_crs=metric_crs,
            )
        )
    except Exception as exc:  # noqa: BLE001 - keep score generation robust.
        logger.warning("Transit commute estimation failed: %s", exc)
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
        logger.warning("Could not parse r5py metadata %s: %s", metadata_path, exc)
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
    router_info: dict[str, object] = {
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
        logger.warning("r5py transit CSV missing at %s; using Apimetro fallback.", csv_path)
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
        logger.warning("Could not read r5py transit CSV %s: %s", csv_path, exc)
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
        logger.warning(
            "r5py transit CSV is missing required columns %s; using Apimetro fallback.",
            ", ".join(missing),
        )
        router_info["status"] = "invalid_csv"
        router_info["missing_columns"] = missing
        return result, router_info

    r5py = r5py.copy()
    r5py["area_id"] = r5py["area_id"].fillna("").astype(str)
    if area_unit == "postal_code":
        r5py["area_id"] = r5py["area_id"].str.zfill(5)
    r5py["routed_successfully"] = r5py["routed_successfully"].map(normalize_bool)
    r5py["time_work_transit_min"] = pd.to_numeric(r5py["time_work_transit_min"], errors="coerce")
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
            nullable_round(score_transit_commute_minutes(value), 1) for value in median_values
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
            key: value for key, value in metadata.items() if key not in {"global_traceback"}
        }
    return result, router_info
