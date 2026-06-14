"""Area geometry loading and property normalization."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from cdmxmap.config import ALCALDIA_FIELDS, METRIC_CRS, WGS84_CRS
from cdmxmap.models import AreaConfig


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


def field_text(frame: gpd.GeoDataFrame, fields: list[str], *, default: str = "") -> pd.Series:
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


def prepare_area_properties(areas: gpd.GeoDataFrame, config: AreaConfig) -> gpd.GeoDataFrame:
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
    prepared["display_name"] = "CP " + area_ids if config.area_unit == "postal_code" else area_names
    prepared["alcaldia"] = alcaldias

    if config.area_unit == "postal_code":
        prepared["postal_label"] = area_names.where(area_names != area_ids, "")
    else:
        prepared["colonia_name"] = area_names

    return prepared


def area_representative_latlon(
    input_path: Path, config: AreaConfig
) -> tuple[list[str], list[tuple[float, float]]]:
    """Area ids and their ``(lat, lon)`` representative points.

    Uses the exact computation the scoring engine uses (``score_areas``) so the
    area-to-area matrix build produces routed cells aligned with the scored output.
    """
    areas = prepare_area_properties(load_area_geometries(input_path), config)
    areas_metric = areas.to_crs(METRIC_CRS)
    areas_metric["geometry"] = areas_metric.geometry.make_valid()
    reference_points = areas_metric.geometry.representative_point()
    reference_wgs84 = gpd.GeoSeries(reference_points, crs=METRIC_CRS).to_crs(WGS84_CRS)
    area_ids = areas["area_id"].tolist()
    latlon = list(zip(reference_wgs84.y.tolist(), reference_wgs84.x.tolist()))
    return area_ids, latlon
