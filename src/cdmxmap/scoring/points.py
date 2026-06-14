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
from cdmxmap.models import (
    AmenityRouteResult,
    NearestResult,
    PointDatasets,
    RoutedWorkResult,
)
from cdmxmap.routing.base import FALLBACK_STRAIGHT_LINE_SOURCE, LatLon, Router
from cdmxmap.routing.cache import RouteCacheKey, RoutingCache
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


def _route_targets_cached(
    router: Router,
    cache: RoutingCache | None,
    *,
    origin: LatLon,
    targets: list[LatLon],
    mode: str,
    area_unit: str,
    area_id: str,
    inputs_hash: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Route one origin to k targets, reusing cached results. NaN = unreachable.

    Only finite results are cached; unreachable cells are recomputed on resume.
    """
    profile = router.profile(mode)
    minutes = np.full(len(targets), np.nan)
    meters = np.full(len(targets), np.nan)
    keys = [
        RouteCacheKey(
            area_unit=area_unit,
            area_id=area_id,
            origin=origin,
            destination=target,
            mode=mode,
            engine=router.engine,
            version=router.version,
            profile=profile,
            inputs_hash=inputs_hash,
        )
        for target in targets
    ]
    missing: list[int] = []
    for idx, key in enumerate(keys):
        cached = cache.get(key) if cache is not None else None
        if cached is None:
            missing.append(idx)
        else:
            minutes[idx], meters[idx] = cached
    if missing:
        result = router.matrix([origin], [targets[idx] for idx in missing], mode)
        for offset, idx in enumerate(missing):
            route_minutes = float(result.minutes[0, offset])
            route_meters = float(result.meters[0, offset])
            minutes[idx] = route_minutes
            meters[idx] = route_meters
            if cache is not None and math.isfinite(route_minutes) and math.isfinite(route_meters):
                cache.set(keys[idx], route_minutes, route_meters)
    return minutes, meters


def route_work(
    router: Router,
    cache: RoutingCache | None,
    *,
    reference_latlon: list[LatLon],
    workplace: LatLon,
    modes: tuple[str, ...],
    travel_time_config: dict,
    straight_line_distances: np.ndarray,
    area_unit: str,
    area_ids: list[str],
    inputs_hash: str,
) -> RoutedWorkResult:
    """Route every representative point to the workplace for each mode.

    Times are routed where the point snaps to the network, else the straight-line
    estimate (so each per-mode field is always populated). The row's routed
    distance and source key on the *primary* mode (driving when requested), so a
    row's source is the engine label exactly when ``dist_work_routed_m`` is present.
    """
    count = len(reference_latlon)
    times: dict[str, np.ndarray] = {}
    routed_count: dict[str, int] = {}
    fallback_count: dict[str, int] = {}
    primary_mode = "driving" if "driving" in modes else modes[0]
    primary_routed = np.zeros(count, dtype=bool)
    routed_distances = np.full(count, np.nan)

    for mode in modes:
        estimate = estimate_travel_minutes(straight_line_distances, mode, travel_time_config)
        routed_minutes = np.full(count, np.nan)
        routed_meters = np.full(count, np.nan)
        keys = [
            RouteCacheKey(
                area_unit=area_unit,
                area_id=area_ids[i],
                origin=reference_latlon[i],
                destination=workplace,
                mode=mode,
                engine=router.engine,
                version=router.version,
                profile=router.profile(mode),
                inputs_hash=inputs_hash,
            )
            for i in range(count)
        ]
        missing: list[int] = []
        for i, key in enumerate(keys):
            cached = cache.get(key) if cache is not None else None
            if cached is None:
                missing.append(i)
            else:
                routed_minutes[i], routed_meters[i] = cached
        if missing:
            result = router.matrix([reference_latlon[i] for i in missing], [workplace], mode)
            for offset, i in enumerate(missing):
                route_minutes = float(result.minutes[offset, 0])
                route_meters = float(result.meters[offset, 0])
                routed_minutes[i] = route_minutes
                routed_meters[i] = route_meters
                if (
                    cache is not None
                    and math.isfinite(route_minutes)
                    and math.isfinite(route_meters)
                ):
                    cache.set(keys[i], route_minutes, route_meters)

        routed_mask = np.isfinite(routed_minutes)
        times[mode] = np.where(routed_mask, routed_minutes, estimate)
        routed_count[mode] = int(routed_mask.sum())
        fallback_count[mode] = int(count - routed_mask.sum())
        if mode == primary_mode:
            primary_routed = routed_mask
            routed_distances = np.where(routed_mask, routed_meters, np.nan)

    sources = [
        router.source if primary_routed[i] else FALLBACK_STRAIGHT_LINE_SOURCE for i in range(count)
    ]
    return RoutedWorkResult(
        times=times,
        routed_distances=routed_distances,
        sources=sources,
        routed_count=routed_count,
        fallback_count=fallback_count,
        error_count=int((~primary_routed).sum()),
    )


def amenity_route_candidates(
    reference_points: gpd.GeoSeries,
    points: gpd.GeoDataFrame,
    *,
    candidate_count: int,
    mode: str,
    travel_time_config: dict,
    router: Router | None = None,
    reference_latlon: list[LatLon] | None = None,
    cache: RoutingCache | None = None,
    area_unit: str = "",
    area_ids: list[str] | None = None,
    inputs_hash: str = "",
) -> AmenityRouteResult:
    if points.empty:
        return AmenityRouteResult(
            distances=np.full(len(reference_points), np.nan),
            times=np.full(len(reference_points), np.nan),
            names=[""] * len(reference_points),
            sources=[""] * len(reference_points),
            candidate_pairs=0,
            estimated_pairs=0,
            routed_distances=np.full(len(reference_points), np.nan),
            routed_mask=np.zeros(len(reference_points), dtype=bool),
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

    # Routing needs POI coordinates in WGS84; the straight-line narrowing stays in
    # the metric CRS. ``routing`` is on only when a router and origin coords exist.
    routing = router is not None and reference_latlon is not None
    if routing:
        points_wgs = points.to_crs(WGS84_CRS)
        poi_lat = points_wgs.geometry.y.to_numpy()
        poi_lon = points_wgs.geometry.x.to_numpy()
    resolved_area_ids = area_ids or [""] * len(reference_points)

    distances: list[float] = []
    times: list[float] = []
    names: list[str] = []
    sources: list[str] = []
    routed_distances: list[float] = []
    routed_mask: list[bool] = []
    candidate_pairs = 0
    estimated_pairs = 0
    routed_count = 0
    fallback_count = 0

    for i, reference_point in enumerate(reference_points):
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

        routed_minutes = None
        if routing:
            assert router is not None and reference_latlon is not None
            targets = [(float(poi_lat[k]), float(poi_lon[k])) for k in candidate_indexes]
            routed_minutes, routed_meters = _route_targets_cached(
                router,
                cache,
                origin=reference_latlon[i],
                targets=targets,
                mode=mode,
                area_unit=area_unit,
                area_id=resolved_area_ids[i],
                inputs_hash=inputs_hash,
            )

        if routed_minutes is not None and np.isfinite(routed_minutes).any():
            best_offset = int(np.nanargmin(routed_minutes))
            best_index = int(candidate_indexes[best_offset])
            distances.append(float(candidate_distances[best_offset]))
            times.append(float(routed_minutes[best_offset]))
            routed_distances.append(float(routed_meters[best_offset]))
            routed_mask.append(True)
            routed_count += 1
        else:
            estimated_pairs += len(candidate_indexes)
            best_offset = int(np.nanargmin(candidate_times))
            best_index = int(candidate_indexes[best_offset])
            distances.append(float(candidate_distances[best_offset]))
            times.append(float(candidate_times[best_offset]))
            routed_distances.append(float("nan"))
            routed_mask.append(False)
            if routing:
                fallback_count += 1
        names.append(str(point_names[best_index]))
        sources.append(str(point_sources[best_index]))

    return AmenityRouteResult(
        distances=np.array(distances),
        times=np.array(times),
        names=names,
        sources=sources,
        candidate_pairs=candidate_pairs,
        estimated_pairs=estimated_pairs,
        routed_distances=np.array(routed_distances),
        routed_mask=np.array(routed_mask, dtype=bool),
        routed_count=routed_count,
        fallback_count=fallback_count,
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
