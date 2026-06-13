"""Point datasets and nearest/candidate spatial queries."""

from __future__ import annotations

import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from cdmxmap.config import (
    CORE_TRANSIT_SYSTEMS,
    METRIC_CRS,
    SURFACE_TRANSIT_SYSTEMS,
    TRANSIT_SYSTEM_FIELD_SLUGS,
    WGS84_CRS,
)
from cdmxmap.models import AmenityRouteResult, NearestResult, PointDatasets
from cdmxmap.scoring.crime import read_crimes
from cdmxmap.scoring.metrics import estimate_travel_minutes, nullable_number
from cdmxmap.sources.io import DATA_PROCESSED, DATA_RAW


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


def workplace_coordinates(
    places_config: dict, workplaces: gpd.GeoDataFrame
) -> tuple[float, float] | None:
    configured = places_config.get("workplace", {})
    latitude = nullable_number(configured.get("latitude"))
    longitude = nullable_number(configured.get("longitude"))
    if latitude is not None and longitude is not None:
        return latitude, longitude
    if workplaces.empty:
        return None
    first_workplace = workplaces.to_crs(WGS84_CRS).geometry.iloc[0]
    return float(first_workplace.y), float(first_workplace.x)


def nearest(reference_points: gpd.GeoSeries, points: gpd.GeoDataFrame) -> NearestResult:
    if points.empty:
        return NearestResult(
            distances=np.full(len(reference_points), np.nan),
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
        squared = np.square(point_x - reference_point.x) + np.square(point_y - reference_point.y)
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
        return AmenityRouteResult(
            distances=np.full(len(reference_points), np.nan),
            times=np.full(len(reference_points), np.nan),
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
        squared = np.square(point_x - reference_point.x) + np.square(point_y - reference_point.y)
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


def load_point_datasets(places_config: dict, *, data_dir: Path = DATA_PROCESSED) -> PointDatasets:
    transit = read_points(data_dir / "transit_stops.csv")
    supermarkets = read_points(data_dir / "supermarkets.csv")
    gyms = read_points(data_dir / "gyms.csv")
    workplaces = load_workplaces(places_config)
    crimes = read_crimes(data_dir / "crime_points.csv")

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
        transit_by_system = {
            system: transit[transit_system.eq(system)].copy()
            for system in TRANSIT_SYSTEM_FIELD_SLUGS
        }
    else:
        core_transit = transit
        surface_transit = transit
        empty_transit = gpd.GeoDataFrame(
            transit.iloc[0:0].copy(), geometry="geometry", crs=transit.crs
        )
        transit_by_system = {system: empty_transit.copy() for system in TRANSIT_SYSTEM_FIELD_SLUGS}

    return PointDatasets(
        transit=transit,
        core_transit=core_transit,
        surface_transit=surface_transit,
        transit_by_system=transit_by_system,
        supermarkets=supermarkets,
        costcos=costcos,
        walmarts=walmarts,
        gyms=gyms,
        workplaces=workplaces,
        crimes=crimes,
    )
