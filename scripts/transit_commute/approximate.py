from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from .models import TransitCommuteConfig


WGS84_CRS = "EPSG:4326"
METRIC_CRS = "EPSG:32614"
TRANSIT_COMMUTE_SOURCE = "apimetro_stop_pair_approximation"


OUTPUT_COLUMNS = [
    "area_unit",
    "area_id",
    "time_work_transit_min",
    "score_work_transit",
    "transit_commute_source",
    "transit_origin_stop_name",
    "transit_origin_system",
    "transit_origin_line",
    "transit_origin_walk_m",
    "transit_destination_stop_name",
    "transit_destination_system",
    "transit_destination_line",
    "transit_destination_walk_m",
    "transit_transfer_penalty_min",
    "transit_route_complexity",
    "transit_commute_notes",
]


@dataclass(frozen=True)
class StopArrays:
    x: np.ndarray
    y: np.ndarray
    names: np.ndarray
    systems: np.ndarray
    lines: np.ndarray


@dataclass(frozen=True)
class StopCandidate:
    index: int
    walk_m: float


@dataclass(frozen=True)
class PairEstimate:
    total_min: float
    origin: StopCandidate
    destination: StopCandidate
    in_vehicle_min: float
    transfer_penalty_min: float
    route_complexity: str
    notes: list[str]


def score_transit_commute_minutes(minutes: float | int | None) -> float | None:
    """Score a public-transport commute estimate on a 0-100 monotonic scale."""
    if minutes is None:
        return None
    try:
        value = float(minutes)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if value <= 0:
        return 100.0
    if value <= 20:
        return 100.0 - (value * 0.5)
    if value <= 30:
        return 90.0 - ((value - 20.0) * 1.0)
    if value <= 45:
        return 80.0 - ((value - 30.0) * (20.0 / 15.0))
    if value <= 60:
        return 60.0 - ((value - 45.0) * (25.0 / 15.0))
    if value <= 90:
        return 35.0 - ((value - 60.0) * (35.0 / 30.0))
    return 0.0


def estimate_transit_commute_to_work(
    areas_gdf: gpd.GeoDataFrame,
    transit_points_gdf: gpd.GeoDataFrame,
    workplace_lat: float,
    workplace_lon: float,
    config: dict[str, Any] | TransitCommuteConfig | None = None,
) -> pd.DataFrame:
    commute_config = (
        config
        if isinstance(config, TransitCommuteConfig)
        else TransitCommuteConfig.from_mapping(config)
    )
    area_identity = _area_identity_frame(areas_gdf)
    if transit_points_gdf.empty:
        return _empty_result(area_identity, "no_transit_stops_available")

    areas_metric = _to_metric(areas_gdf)
    transit_metric = _to_metric(transit_points_gdf)
    transit_metric = _valid_transit_points(transit_metric)
    if transit_metric.empty:
        return _empty_result(area_identity, "no_valid_transit_stop_coordinates")

    reference_points = areas_metric.geometry.make_valid().representative_point()
    workplace_point = _workplace_point(workplace_lat, workplace_lon)
    stops = _stop_arrays(transit_metric)
    candidate_limit = min(commute_config.candidate_stop_count, len(transit_metric))
    destination_candidates = _nearest_candidates(
        workplace_point.x,
        workplace_point.y,
        stops,
        candidate_limit,
    )

    rows: list[dict[str, Any]] = []
    for (_, identity), reference_point in zip(area_identity.iterrows(), reference_points):
        origin_candidates = _nearest_candidates(
            reference_point.x,
            reference_point.y,
            stops,
            candidate_limit,
        )
        best = _best_pair(origin_candidates, destination_candidates, stops, commute_config)
        rows.append(_row_from_estimate(identity, best, stops, commute_config))

    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def transit_commute_metadata(
    config: dict[str, Any] | TransitCommuteConfig | None = None,
) -> dict[str, Any]:
    commute_config = (
        config
        if isinstance(config, TransitCommuteConfig)
        else TransitCommuteConfig.from_mapping(config)
    )
    return {
        **commute_config.to_metadata(),
        "known_limitations": [
            "Uses Apimetro stop points only; no GTFS schedules, headways, stop order, or route geometry are used.",
            "Line values are only used when present in the processed stop data; the current Apimetro cache does not include line/order fields.",
            "In-vehicle time is straight-line stop-to-stop distance divided by mode speed.",
            "Walking access and egress are straight-line distances and do not account for street barriers or station entrances.",
            "Different-line and different-system trips use fixed penalties instead of a real transfer graph.",
        ],
    }


def _area_identity_frame(areas_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    if "area_id" in areas_gdf.columns:
        area_ids = areas_gdf["area_id"].fillna("").astype(str)
    else:
        area_ids = pd.Series(
            [f"area-{index + 1}" for index in range(len(areas_gdf))],
            index=areas_gdf.index,
            dtype="object",
        )
    if "area_unit" in areas_gdf.columns:
        area_units = areas_gdf["area_unit"].fillna("").astype(str)
    else:
        area_units = pd.Series(["area"] * len(areas_gdf), index=areas_gdf.index)
    return pd.DataFrame({"area_unit": area_units, "area_id": area_ids})


def _empty_result(area_identity: pd.DataFrame, source: str) -> pd.DataFrame:
    rows = []
    for _, identity in area_identity.iterrows():
        rows.append(
            {
                "area_unit": identity["area_unit"],
                "area_id": identity["area_id"],
                "time_work_transit_min": None,
                "score_work_transit": None,
                "transit_commute_source": source,
                "transit_origin_stop_name": None,
                "transit_origin_system": None,
                "transit_origin_line": None,
                "transit_origin_walk_m": None,
                "transit_destination_stop_name": None,
                "transit_destination_system": None,
                "transit_destination_line": None,
                "transit_destination_walk_m": None,
                "transit_transfer_penalty_min": None,
                "transit_route_complexity": None,
                "transit_commute_notes": "No usable transit stops were available.",
            }
        )
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def _to_metric(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if frame.crs is None:
        frame = frame.set_crs(WGS84_CRS)
    if str(frame.crs) == METRIC_CRS:
        return frame.copy()
    return frame.to_crs(METRIC_CRS)


def _valid_transit_points(transit_metric: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    valid = transit_metric[~transit_metric.geometry.is_empty].copy()
    valid = valid[valid.geometry.geom_type == "Point"].copy()
    return valid


def _workplace_point(workplace_lat: float, workplace_lon: float):
    point = gpd.GeoSeries(
        gpd.points_from_xy([float(workplace_lon)], [float(workplace_lat)]),
        crs=WGS84_CRS,
    ).to_crs(METRIC_CRS)
    return point.iloc[0]


def _stop_arrays(transit_metric: gpd.GeoDataFrame) -> StopArrays:
    systems = _series_or_default(transit_metric, "system").str.upper().to_numpy()
    names = _stop_names(transit_metric, systems).to_numpy()
    return StopArrays(
        x=transit_metric.geometry.x.to_numpy(dtype=float),
        y=transit_metric.geometry.y.to_numpy(dtype=float),
        names=names,
        systems=systems,
        lines=_series_or_default(transit_metric, "line").to_numpy(),
    )


def _series_or_default(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([""] * len(frame), index=frame.index, dtype="object")
    return frame[column].fillna("").astype(str).str.strip()


def _stop_names(frame: pd.DataFrame, systems: np.ndarray) -> pd.Series:
    raw_names = _series_or_default(frame, "name")
    clean_names: list[str] = []
    for raw_name, system in zip(raw_names, systems):
        prefix = f"{system} · "
        clean_names.append(raw_name.removeprefix(prefix) or raw_name or "Unnamed stop")
    return pd.Series(clean_names, index=frame.index, dtype="object")


def _nearest_candidates(
    x: float,
    y: float,
    stops: StopArrays,
    limit: int,
) -> list[StopCandidate]:
    squared = np.square(stops.x - x) + np.square(stops.y - y)
    if limit >= len(stops.x):
        indexes = np.argsort(squared)
    else:
        indexes = np.argpartition(squared, limit - 1)[:limit]
        indexes = indexes[np.argsort(squared[indexes])]
    return [
        StopCandidate(index=int(index), walk_m=float(math.sqrt(float(squared[index]))))
        for index in indexes
    ]


def _best_pair(
    origin_candidates: list[StopCandidate],
    destination_candidates: list[StopCandidate],
    stops: StopArrays,
    config: TransitCommuteConfig,
) -> PairEstimate:
    best: PairEstimate | None = None
    for origin in origin_candidates:
        for destination in destination_candidates:
            estimate = _estimate_pair(origin, destination, stops, config)
            if best is None or estimate.total_min < best.total_min:
                best = estimate
    if best is None:
        raise ValueError("No origin/destination transit stop candidates were available")
    return best


def _estimate_pair(
    origin: StopCandidate,
    destination: StopCandidate,
    stops: StopArrays,
    config: TransitCommuteConfig,
) -> PairEstimate:
    origin_system = str(stops.systems[origin.index])
    destination_system = str(stops.systems[destination.index])
    origin_line = str(stops.lines[origin.index])
    destination_line = str(stops.lines[destination.index])
    same_system = bool(origin_system and origin_system == destination_system)
    same_line = bool(
        same_system
        and origin_line
        and destination_line
        and origin_line.casefold() == destination_line.casefold()
    )

    if same_line:
        transfer_penalty = config.same_line_transfer_penalty_min
        route_complexity = "same_line"
    elif same_system:
        transfer_penalty = config.same_system_different_line_penalty_min
        route_complexity = (
            "same_system_different_line"
            if origin_line and destination_line
            else "same_system_unknown_line"
        )
    else:
        transfer_penalty = config.different_system_penalty_min
        route_complexity = "different_system"

    stop_distance_m = math.hypot(
        stops.x[origin.index] - stops.x[destination.index],
        stops.y[origin.index] - stops.y[destination.index],
    )
    speed_kmh = _pair_speed_kmh(origin_system, destination_system, config)
    in_vehicle_min = _minutes_for_distance(stop_distance_m, speed_kmh)
    origin_walk_min = _minutes_for_distance(origin.walk_m, config.walking_speed_kmh)
    destination_walk_min = _minutes_for_distance(
        destination.walk_m, config.walking_speed_kmh
    )
    origin_walk_penalty = _excess_walk_penalty(
        origin.walk_m, config.max_origin_walk_m, config.walking_speed_kmh
    )
    destination_walk_penalty = _excess_walk_penalty(
        destination.walk_m,
        config.max_destination_walk_m,
        config.walking_speed_kmh,
    )
    total_min = (
        origin_walk_min
        + in_vehicle_min
        + destination_walk_min
        + transfer_penalty
        + origin_walk_penalty
        + destination_walk_penalty
    )

    notes = ["Approximation from Apimetro stops; not schedule-aware."]
    if not same_line:
        notes.append("Line/order data is unavailable or does not match.")
    if origin.walk_m > config.max_origin_walk_m:
        notes.append("Origin stop exceeds configured max walk distance; penalty applied.")
    if destination.walk_m > config.max_destination_walk_m:
        notes.append(
            "Destination stop exceeds configured max walk distance; penalty applied."
        )
    if route_complexity == "different_system":
        notes.append("Different-system pair uses fixed transfer/complexity penalty.")
    elif route_complexity == "same_system_unknown_line":
        notes.append("Same-system pair has unknown line, so transfer risk is penalized.")

    return PairEstimate(
        total_min=total_min,
        origin=origin,
        destination=destination,
        in_vehicle_min=in_vehicle_min,
        transfer_penalty_min=transfer_penalty
        + origin_walk_penalty
        + destination_walk_penalty,
        route_complexity=route_complexity,
        notes=notes,
    )


def _pair_speed_kmh(
    origin_system: str,
    destination_system: str,
    config: TransitCommuteConfig,
) -> float:
    origin_speed = _system_speed_kmh(origin_system, config)
    destination_speed = _system_speed_kmh(destination_system, config)
    if origin_system and origin_system == destination_system:
        return origin_speed
    return min(origin_speed, destination_speed)


def _system_speed_kmh(system: str, config: TransitCommuteConfig) -> float:
    if system == "METRO":
        return config.metro_speed_kmh
    if system == "MB":
        return config.metrobus_speed_kmh
    if system == "TROLE":
        return config.trolleybus_speed_kmh
    if system in {"RTP", "CC"}:
        return config.bus_speed_kmh
    return config.default_transit_speed_kmh


def _minutes_for_distance(distance_m: float, speed_kmh: float) -> float:
    if speed_kmh <= 0:
        return math.inf
    return float(distance_m) / ((float(speed_kmh) * 1000.0) / 60.0)


def _excess_walk_penalty(distance_m: float, max_walk_m: float, walking_speed_kmh: float) -> float:
    if distance_m <= max_walk_m:
        return 0.0
    excess_m = distance_m - max_walk_m
    return 5.0 + (0.5 * _minutes_for_distance(excess_m, walking_speed_kmh))


def _row_from_estimate(
    identity: pd.Series,
    estimate: PairEstimate,
    stops: StopArrays,
    config: TransitCommuteConfig,
) -> dict[str, Any]:
    score = score_transit_commute_minutes(estimate.total_min)
    return {
        "area_unit": identity["area_unit"],
        "area_id": identity["area_id"],
        "time_work_transit_min": _round_float(estimate.total_min, 1),
        "score_work_transit": _round_float(score, 1),
        "transit_commute_source": config.source,
        "transit_origin_stop_name": _nullable_string(stops.names[estimate.origin.index]),
        "transit_origin_system": _nullable_string(stops.systems[estimate.origin.index]),
        "transit_origin_line": _nullable_string(stops.lines[estimate.origin.index]),
        "transit_origin_walk_m": _round_float(estimate.origin.walk_m, 0),
        "transit_destination_stop_name": _nullable_string(
            stops.names[estimate.destination.index]
        ),
        "transit_destination_system": _nullable_string(
            stops.systems[estimate.destination.index]
        ),
        "transit_destination_line": _nullable_string(
            stops.lines[estimate.destination.index]
        ),
        "transit_destination_walk_m": _round_float(estimate.destination.walk_m, 0),
        "transit_transfer_penalty_min": _round_float(
            estimate.transfer_penalty_min, 1
        ),
        "transit_route_complexity": estimate.route_complexity,
        "transit_commute_notes": " ".join(estimate.notes),
    }


def _round_float(value: float | None, digits: int) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return float(round(float(value), digits))


def _nullable_string(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
