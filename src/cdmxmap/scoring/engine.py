"""The scoring engine: assemble the full output contract for one area unit."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from cdmxmap.config import (
    DEFAULT_WEIGHTS,
    METRIC_CRS,
    R5PY_TRANSIT_COMMUTE_SOURCE,
    TRANSIT_COMMUTE_OUTPUT_COLUMNS,
    TRANSIT_ROUTER_APIMETRO,
    TRANSIT_ROUTER_R5PY,
    TRANSIT_SYSTEM_FIELD_SLUGS,
    WGS84_CRS,
    WORK_TRAVEL_MODES,
    amenity_travel_time_config,
    merged_travel_time_config,
    road_routing_config,
    transit_commute_config,
)
from cdmxmap.models import AreaConfig, PointDatasets, ScoredAreaResult
from cdmxmap.routing.base import FALLBACK_STRAIGHT_LINE_SOURCE, Router
from cdmxmap.routing.cache import RoutingCache
from cdmxmap.scoring.areas import load_area_geometries, prepare_area_properties
from cdmxmap.scoring.crime import aggregate_crime
from cdmxmap.scoring.metrics import (
    distance_score,
    estimate_travel_minutes,
    inverse_density_score,
    nullable_round_distance,
    round_distance,
    round_minutes,
    round_score,
)
from cdmxmap.scoring.points import (
    amenity_route_candidates,
    nearest,
    route_work,
    workplace_coordinates,
)
from cdmxmap.scoring.transit import (
    apply_r5py_transit_commute,
    build_transit_commute_frame,
    ensure_transit_commute_columns,
    transit_route_summary,
)
from cdmxmap.transit_commute import transit_commute_metadata


def score_areas(
    *,
    config: AreaConfig,
    input_path: Path,
    point_datasets: PointDatasets,
    places_config: dict,
    transit_router: str = TRANSIT_ROUTER_APIMETRO,
    router: Router | None = None,
    routing_cache: RoutingCache | None = None,
) -> ScoredAreaResult:
    areas = prepare_area_properties(load_area_geometries(input_path), config)
    areas_metric = areas.to_crs(METRIC_CRS)
    areas_metric["geometry"] = areas_metric.geometry.make_valid()
    reference_points = areas_metric.geometry.representative_point()
    reference_wgs84 = gpd.GeoSeries(reference_points, crs=METRIC_CRS).to_crs(WGS84_CRS)
    travel_time_config = merged_travel_time_config(places_config)
    amenity_time_config = amenity_travel_time_config(places_config, travel_time_config)
    work_transit_config = transit_commute_config(places_config)

    # Road routing (opt-in). When no router is supplied the engine keeps its
    # deterministic straight-line fallback and byte-identical output.
    rr_config = road_routing_config(places_config)
    routing_modes = rr_config["modes"]
    area_id_list = areas["area_id"].tolist()
    reference_latlon = list(zip(reference_wgs84.y.tolist(), reference_wgs84.x.tolist()))
    workplace_latlon = workplace_coordinates(places_config, point_datasets.workplaces)
    inputs_hash = ""
    amenity_route_kwargs: dict = {}
    if router is not None:
        inputs_hash = "|".join(
            [router.engine, router.version, str(rr_config.get("osm_source") or "")]
        )
        amenity_route_kwargs = {
            "router": router,
            "reference_latlon": reference_latlon,
            "cache": routing_cache,
            "area_unit": config.area_unit,
            "area_ids": area_id_list,
            "inputs_hash": inputs_hash,
        }

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
    nearest_transit_by_system = {
        system: nearest(reference_points, point_datasets.transit_by_system[system])
        for system in TRANSIT_SYSTEM_FIELD_SLUGS
    }
    nearest_supermarket = nearest(reference_points, point_datasets.supermarkets)
    nearest_costco = nearest(
        reference_points,
        point_datasets.costcos if not point_datasets.costcos.empty else point_datasets.supermarkets,
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
        travel_time_config=travel_time_config,
        **amenity_route_kwargs,
    )
    routed_costco = amenity_route_candidates(
        reference_points,
        point_datasets.costcos if not point_datasets.costcos.empty else point_datasets.supermarkets,
        candidate_count=amenity_time_config["candidate_count"],
        mode=amenity_time_config["mode"],
        travel_time_config=travel_time_config,
        **amenity_route_kwargs,
    )
    routed_walmart = amenity_route_candidates(
        reference_points,
        point_datasets.walmarts
        if not point_datasets.walmarts.empty
        else point_datasets.supermarkets,
        candidate_count=amenity_time_config["candidate_count"],
        mode=amenity_time_config["mode"],
        travel_time_config=travel_time_config,
        **amenity_route_kwargs,
    )
    routed_gym = amenity_route_candidates(
        reference_points,
        point_datasets.gyms,
        candidate_count=amenity_time_config["candidate_count"],
        mode=amenity_time_config["mode"],
        travel_time_config=travel_time_config,
        **amenity_route_kwargs,
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
        "failed_count": int(
            len(transit_commute) - transit_commute["time_work_transit_min"].notna().sum()
        ),
    }
    if transit_router == TRANSIT_ROUTER_R5PY:
        transit_commute, transit_router_info = apply_r5py_transit_commute(
            area_unit=config.area_unit,
            transit_commute=transit_commute,
        )
    transit_commute = ensure_transit_commute_columns(transit_commute)
    transit_commute = transit_commute.set_index("area_id").reindex(areas["area_id"])

    # score_work and the combined score stay straight-line distance based for a
    # stable headline; only the per-mode work *times* become routed.
    score_work = distance_score(nearest_work.distances)
    routed_work = None
    if router is not None and workplace_latlon is not None:
        routed_work = route_work(
            router,
            routing_cache,
            reference_latlon=reference_latlon,
            workplace=workplace_latlon,
            modes=routing_modes,
            travel_time_config=travel_time_config,
            straight_line_distances=nearest_work.distances,
            area_unit=config.area_unit,
            area_ids=area_id_list,
            inputs_hash=inputs_hash,
        )
    if routed_work is not None:
        work_times = dict(routed_work.times)
        for mode in WORK_TRAVEL_MODES:
            if mode not in work_times:
                work_times[mode] = estimate_travel_minutes(
                    nearest_work.distances, mode, travel_time_config
                )
    else:
        work_times = {
            mode: estimate_travel_minutes(nearest_work.distances, mode, travel_time_config)
            for mode in WORK_TRAVEL_MODES
        }
    score_work_times = {mode: distance_score(minutes) for mode, minutes in work_times.items()}
    score_core_transit = distance_score(nearest_core_transit.distances)
    score_surface_transit = distance_score(nearest_surface_transit.distances)
    score_transit_by_system = {
        system: distance_score(nearest_result.distances)
        for system, nearest_result in nearest_transit_by_system.items()
    }
    score_transit = (0.70 * score_core_transit) + (0.30 * score_surface_transit)
    score_supermarkets = distance_score(nearest_supermarket.distances)
    score_gyms = distance_score(nearest_gym.distances)
    score_supermarkets_time = distance_score(routed_supermarket.times)
    score_gyms_time = distance_score(routed_gym.times)
    crime_aggregation, crime_metadata = aggregate_crime(areas_metric, point_datasets.crimes)
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
    if routed_work is not None:
        areas["dist_work_routed_m"] = nullable_round_distance(routed_work.routed_distances)
    areas["dist_transit_m"] = round_distance(nearest_transit.distances)
    areas["dist_core_transit_m"] = round_distance(nearest_core_transit.distances)
    areas["dist_surface_transit_m"] = round_distance(nearest_surface_transit.distances)
    for system, slug in TRANSIT_SYSTEM_FIELD_SLUGS.items():
        areas[f"dist_{slug}_transit_m"] = round_distance(
            nearest_transit_by_system[system].distances
        )
    areas["dist_supermarket_m"] = round_distance(nearest_supermarket.distances)
    areas["dist_costco_m"] = round_distance(nearest_costco.distances)
    areas["dist_walmart_m"] = round_distance(nearest_walmart.distances)
    areas["dist_gym_m"] = round_distance(nearest_gym.distances)
    areas["time_supermarket_min"] = round_minutes(routed_supermarket.times)
    areas["time_costco_min"] = round_minutes(routed_costco.times)
    areas["time_walmart_min"] = round_minutes(routed_walmart.times)
    areas["time_gym_min"] = round_minutes(routed_gym.times)
    if router is not None:
        areas["dist_supermarket_routed_m"] = nullable_round_distance(
            routed_supermarket.routed_distances
        )
        areas["dist_costco_routed_m"] = nullable_round_distance(routed_costco.routed_distances)
        areas["dist_walmart_routed_m"] = nullable_round_distance(routed_walmart.routed_distances)
        areas["dist_gym_routed_m"] = nullable_round_distance(routed_gym.routed_distances)
    areas["score_work"] = round_score(score_work)
    for mode in WORK_TRAVEL_MODES:
        areas[f"time_work_{mode}_min"] = round_minutes(work_times[mode])
        areas[f"score_work_{mode}"] = round_score(score_work_times[mode])
    areas["score_transit"] = round_score(score_transit)
    for system, slug in TRANSIT_SYSTEM_FIELD_SLUGS.items():
        areas[f"score_transit_{slug}"] = round_score(score_transit_by_system[system])
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
    for system, slug in TRANSIT_SYSTEM_FIELD_SLUGS.items():
        areas[f"nearest_{slug}_transit_name"] = nearest_transit_by_system[system].names
    areas["nearest_supermarket_name"] = nearest_supermarket.names
    areas["nearest_costco_name"] = nearest_costco.names
    areas["nearest_walmart_name"] = nearest_walmart.names
    areas["nearest_gym_name"] = nearest_gym.names
    areas["nearest_work_source"] = nearest_work.sources
    areas["work_travel_time_source"] = (
        routed_work.sources if routed_work is not None else travel_time_config["source"]
    )
    areas["nearest_transit_source"] = nearest_transit.sources
    areas["nearest_core_transit_source"] = nearest_core_transit.sources
    areas["nearest_surface_transit_source"] = nearest_surface_transit.sources
    for system, slug in TRANSIT_SYSTEM_FIELD_SLUGS.items():
        areas[f"nearest_{slug}_transit_source"] = nearest_transit_by_system[system].sources
    areas["nearest_supermarket_source"] = nearest_supermarket.sources
    areas["nearest_costco_source"] = nearest_costco.sources
    areas["nearest_walmart_source"] = nearest_walmart.sources
    areas["nearest_gym_source"] = nearest_gym.sources
    if router is not None:
        amenity_routed_row = (
            routed_supermarket.routed_mask
            | routed_costco.routed_mask
            | routed_walmart.routed_mask
            | routed_gym.routed_mask
        )
        areas["amenity_travel_time_source"] = [
            router.source if flag else FALLBACK_STRAIGHT_LINE_SOURCE for flag in amenity_routed_row
        ]
    else:
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
    areas["crime_density_recent_12m_per_km2"] = np.round(
        crime_aggregation["crime_density_recent_12m_per_km2"].fillna(0).to_numpy(dtype=float),
        1,
    ).tolist()
    areas["crime_top_category_recent_12m"] = (
        crime_aggregation["crime_top_category_recent_12m"].fillna("").astype(str).tolist()
    )
    areas["crime_source"] = crime_aggregation["crime_source"].fillna("").astype(str).tolist()

    output = areas.to_crs(WGS84_CRS)
    output["geometry"] = areas_metric.geometry.simplify(8, preserve_topology=True).to_crs(WGS84_CRS)

    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    transit_estimated = int(transit_commute["time_work_transit_min"].notna().sum())
    transit_sources = (
        transit_commute["transit_commute_source"].fillna("unknown").value_counts().to_dict()
    )
    road_routing_meta = None
    if router is not None:
        road_routing_meta = {
            "engine": router.engine,
            "version": router.version,
            "source": router.source,
            "modes": list(routing_modes),
            "profiles": {mode: router.profile(mode) for mode in routing_modes},
            "osm_source": rr_config.get("osm_source"),
            "work": {
                "routed_count": routed_work.routed_count if routed_work is not None else {},
                "fallback_count": routed_work.fallback_count if routed_work is not None else {},
                "error_count": routed_work.error_count if routed_work is not None else len(output),
                "routed": workplace_latlon is not None,
            },
            "amenities": {
                "supermarkets": {
                    "routed_count": routed_supermarket.routed_count,
                    "fallback_count": routed_supermarket.fallback_count,
                },
                "costco": {
                    "routed_count": routed_costco.routed_count,
                    "fallback_count": routed_costco.fallback_count,
                },
                "walmart": {
                    "routed_count": routed_walmart.routed_count,
                    "fallback_count": routed_walmart.fallback_count,
                },
                "gyms": {
                    "routed_count": routed_gym.routed_count,
                    "fallback_count": routed_gym.fallback_count,
                },
            },
            "cache": routing_cache.stats() if routing_cache is not None else None,
            "generated_at": generated_at,
        }
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
            "source": (router.source if router is not None else travel_time_config["source"]),
            "fallback_source": travel_time_config["source"],
            "modes": list(WORK_TRAVEL_MODES),
            "speeds_kmh": travel_time_config["speeds_kmh"],
            "detour_factors": travel_time_config["detour_factors"],
        },
        "road_routing": road_routing_meta,
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
            (
                f"Work and amenity travel times use offline {router.source} road routing "
                "(free-flow, not live traffic) where the point routes, with a straight-line "
                "estimate fallback labeled per feature."
                if router is not None
                else "Work travel times are offline fallback estimates unless the travel_time source is replaced with cached routing results."
            ),
            (
                "Work transit commute uses opt-in r5py schedule-aware routing where available, "
                "with Apimetro approximation fallback."
                if transit_router == TRANSIT_ROUTER_R5PY
                else "Work transit commute uses an offline Apimetro stop-pair approximation and is not schedule-aware."
            ),
            "Amenity travel times consider only the nearest configured candidate POIs before routing or fallback estimation.",
            "Transit score is 70% nearest Metro/Metrobus/Trolebus and 30% nearest RTP/Corredor Concesionado.",
            "System-specific transit distance and score fields support client-side transit method filters.",
            "Safety score is lower-is-better crime density using the latest 12 months available in the FGJ file.",
        ],
    }
    return ScoredAreaResult(output=output, metadata=metadata)
