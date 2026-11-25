"""Validate processed scored GeoJSON against the data contract (standards §G)."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from cdmxmap.citycontext import (
    CDMX_CITY_ID,
    CRIME_MODE_CITY_STATISTICS,
    CityContext,
    load_city_context,
)
from cdmxmap.output.parts import PARTS_INDEX_TYPE, PARTS_INDEX_VERSION, parts_index_name
from cdmxmap.sources.io import DATA_PROCESSED

DEFAULT_GEOJSON_PATHS = [
    DATA_PROCESSED / "scores_postal_code.geojson",
    DATA_PROCESSED / "scores_colonia.geojson",
    DATA_PROCESSED / "cdmx_postal_scores.geojson",
]

GENERIC_FIELDS = [
    "area_unit",
    "area_id",
    "area_name",
    "display_name",
]

DISTANCE_FIELDS = [
    "dist_work_m",
    "dist_transit_m",
    "dist_core_transit_m",
    "dist_surface_transit_m",
    "dist_supermarket_m",
    "dist_costco_m",
    "dist_walmart_m",
    "dist_gym_m",
]

TIME_FIELDS = [
    "time_work_driving_min",
    "time_work_walking_min",
    "time_work_biking_min",
    "time_supermarket_min",
    "time_costco_min",
    "time_walmart_min",
    "time_gym_min",
]

SCORE_FIELDS = [
    "score_work",
    "score_work_driving",
    "score_work_walking",
    "score_work_biking",
    "score_transit",
    "score_supermarkets",
    "score_supermarkets_time",
    "score_gyms",
    "score_gyms_time",
    "score_safety",
    "score_combined_default",
]

TRANSIT_COMMUTE_FIELDS = [
    "time_work_transit_min",
    "time_work_transit_p75_min",
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

CRIME_COUNT_FIELDS = [
    "crime_incidents_total",
    "crime_incidents_recent_12m",
    "crime_density_recent_12m_per_km2",
]
# Optional: the meters each area was buffered by before counting incidents.
CRIME_BUFFER_FIELD = "crime_buffer_m"

# crime_mode "city_statistics": every feature carries its unit's aggregates instead
# of per-area incident counts (which must then be absent: no fake zeros).
CRIME_STATISTICS_NUMBER_FIELDS = [
    "crime_scope_population",
    "crime_scope_incidents_12m",
    "crime_scope_scored_incidents_12m",
    "crime_rate_per_100k_12m",
    "crime_total_rate_per_100k_12m",
]
CRIME_STATISTICS_TEXT_FIELDS = [
    "crime_statistics_scope",
    "crime_statistics_area",
    "crime_statistics_period",
]

# Additive, optional: present only when road routing ran. Each is meters >= 0, or
# null on a row that fell back to the straight-line estimate.
ROUTED_DISTANCE_FIELDS = [
    "dist_work_routed_m",
    "dist_supermarket_routed_m",
    "dist_costco_routed_m",
    "dist_walmart_routed_m",
    "dist_gym_routed_m",
]

# Per-feature travel-time provenance. Must be a single string, never a JSON array.
SOURCE_FIELDS = [
    "work_travel_time_source",
    "amenity_travel_time_source",
]


def _brand_distance_fields(ctx: CityContext) -> list[str]:
    """City distance fields: the generic set with per-brand columns spliced in
    (CDMX -> exactly DISTANCE_FIELDS, i.e. dist_costco_m/dist_walmart_m)."""
    fields = [
        "dist_work_m",
        "dist_transit_m",
        "dist_core_transit_m",
        "dist_surface_transit_m",
        "dist_supermarket_m",
    ]
    fields += [f"dist_{brand.slug}_m" for brand in ctx.store_brands]
    fields.append("dist_gym_m")
    return fields


def _brand_time_fields(ctx: CityContext) -> list[str]:
    fields = [
        "time_work_driving_min",
        "time_work_walking_min",
        "time_work_biking_min",
        "time_supermarket_min",
    ]
    fields += [f"time_{brand.slug}_min" for brand in ctx.store_brands]
    fields.append("time_gym_min")
    return fields


def _brand_routed_distance_fields(ctx: CityContext) -> list[str]:
    fields = ["dist_work_routed_m", "dist_supermarket_routed_m"]
    fields += [f"dist_{brand.slug}_routed_m" for brand in ctx.store_brands]
    fields.append("dist_gym_routed_m")
    return fields


def _profile_transit_slugs(ctx: CityContext) -> list[str]:
    """Transit systems a profile city declares (CDMX and profile-less contexts: none)."""
    if ctx.city_id == CDMX_CITY_ID or not ctx.profile.get("transit_systems"):
        return []
    return [spec.slug for spec in ctx.transit_systems]


def _assert_crime_fields(props: dict, ctx: CityContext) -> None:
    if CRIME_BUFFER_FIELD in props:
        # Present only on buffered-density cities, and then a real radius.
        value = props[CRIME_BUFFER_FIELD]
        assert_number(value, minimum=0)
        if float(value) <= 0:
            raise AssertionError(f"{CRIME_BUFFER_FIELD} must be > 0, got {value}")
    if ctx.crime_mode != CRIME_MODE_CITY_STATISTICS:
        for field in CRIME_COUNT_FIELDS:
            assert_number(props.get(field), minimum=0)
        return
    for field in CRIME_STATISTICS_NUMBER_FIELDS:
        assert_number(props.get(field), minimum=0)
    for field in CRIME_STATISTICS_TEXT_FIELDS:
        value = props.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AssertionError(f"Feature has empty {field}")
    present = [field for field in CRIME_COUNT_FIELDS if field in props]
    if present:
        raise AssertionError(f"Statistics-mode feature must not carry incident fields {present}")


def _assert_transit_systems_present(features: list[dict], slugs: list[str]) -> None:
    """Each declared system must be the nearest-of-system for at least one feature.

    An empty system silently yields distance 0 / name "" everywhere, which the
    browser would then score as 100; fail instead.
    """
    for slug in slugs:
        field = f"nearest_{slug}_transit_name"
        if not any(str(f.get("properties", {}).get(field) or "").strip() for f in features):
            raise AssertionError(f"Transit system '{slug}' has no stops: every {field} is empty")


def assert_number(value: object, *, minimum: float, maximum: float | None = None) -> None:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise AssertionError(f"Expected finite number, got {value!r}")
    if float(value) < minimum:
        raise AssertionError(f"Expected value >= {minimum}, got {value}")
    if maximum is not None and float(value) > maximum:
        raise AssertionError(f"Expected value <= {maximum}, got {value}")


def assert_optional_number(
    value: object,
    *,
    minimum: float,
    maximum: float | None = None,
) -> bool:
    if value is None:
        return False
    assert_number(value, minimum=minimum, maximum=maximum)
    return True


def validate_geojson(path: Path, *, ctx: CityContext | None = None) -> int:
    ctx = ctx or load_city_context()
    distance_fields = _brand_distance_fields(ctx)
    time_fields = _brand_time_fields(ctx)
    routed_distance_fields = _brand_routed_distance_fields(ctx)

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise AssertionError("Processed file is not a FeatureCollection")
    features = payload.get("features", [])
    if not features:
        raise AssertionError("Processed file has no features")

    transit_estimate_count = 0
    for feature in features:
        if not feature.get("geometry"):
            raise AssertionError("Feature is missing geometry")
        props = feature.get("properties", {})
        for field in GENERIC_FIELDS:
            if not props.get(field):
                raise AssertionError(f"Feature is missing {field}")
        if props.get("area_unit") == "postal_code" and not props.get("postal_code"):
            raise AssertionError("Feature is missing postal_code")
        for field in distance_fields:
            assert_number(props.get(field), minimum=0)
        for field in time_fields:
            assert_number(props.get(field), minimum=0)
        for field in SCORE_FIELDS:
            assert_number(props.get(field), minimum=0, maximum=100)
        for field in TRANSIT_COMMUTE_FIELDS:
            if field not in props:
                raise AssertionError(f"Feature is missing {field}")
        if not props.get("transit_commute_source"):
            raise AssertionError("Feature has empty transit_commute_source")
        if assert_optional_number(props.get("time_work_transit_min"), minimum=0):
            transit_estimate_count += 1
        assert_optional_number(props.get("score_work_transit"), minimum=0, maximum=100)
        assert_optional_number(props.get("time_work_transit_p75_min"), minimum=0)
        assert_optional_number(props.get("transit_origin_walk_m"), minimum=0)
        assert_optional_number(props.get("transit_destination_walk_m"), minimum=0)
        assert_optional_number(props.get("transit_transfer_penalty_min"), minimum=0)
        _assert_crime_fields(props, ctx)
        for field in routed_distance_fields:
            if field in props:
                assert_optional_number(props.get(field), minimum=0)
        for field in SOURCE_FIELDS:
            value = props.get(field)
            if value is not None and not isinstance(value, str):
                raise AssertionError(f"{field} must be a string, got {type(value).__name__}")

    if transit_estimate_count == 0:
        raise AssertionError("No features have non-null transit commute estimates")
    _assert_transit_systems_present(features, _profile_transit_slugs(ctx))

    area_unit = features[0].get("properties", {}).get("area_unit", "area")
    print(f"Validated {len(features)} processed {area_unit} features in {path}")
    return len(features)


def validate_public_parts(
    index_path: Path, *, max_bytes: int | None = None, processed_path: Path | None = None
) -> int:
    """Check a parts-published layer (output/parts.py) against its index.

    Every part named by the index must sit beside it, match its recorded size,
    SHA-256 and feature count, and fit both the index's ``max_part_bytes`` and
    ``max_bytes`` when given. Area ids must be unique across parts and the counts
    must add up. With ``processed_path``, the parts' features in index order must
    equal the processed file's features exactly. Returns the feature count.
    """
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("type") != PARTS_INDEX_TYPE or index.get("version") != PARTS_INDEX_VERSION:
        raise AssertionError(f"{index_path} is not a version {PARTS_INDEX_VERSION} parts index")
    parts = index.get("parts") or []
    if not parts:
        raise AssertionError(f"{index_path} lists no parts")
    limit = index["max_part_bytes"]
    if max_bytes is not None:
        limit = min(limit, max_bytes)
    features: list[dict] = []
    for part in parts:
        name = part["path"]
        if Path(name).name != name or name in {"", ".", ".."}:
            raise AssertionError(f"{index_path}: part path {name!r} must be a bare file name")
        path = index_path.parent / name
        data = path.read_bytes()
        if len(data) != part["bytes"]:
            raise AssertionError(f"{path}: {len(data)} bytes, index says {part['bytes']}")
        if len(data) > limit:
            raise AssertionError(f"{path}: {len(data)} bytes is over the {limit}-byte part limit")
        if hashlib.sha256(data).hexdigest() != part["sha256"]:
            raise AssertionError(f"{path}: SHA-256 does not match the index")
        payload = json.loads(data)
        if payload.get("type") != "FeatureCollection":
            raise AssertionError(f"{path} is not a FeatureCollection")
        part_features = payload.get("features", [])
        if len(part_features) != part["feature_count"]:
            raise AssertionError(
                f"{path}: {len(part_features)} features, index says {part['feature_count']}"
            )
        features.extend(part_features)
    if len(features) != index["feature_count"]:
        expected = index["feature_count"]
        raise AssertionError(
            f"{index_path}: parts hold {len(features)} features, index says {expected}"
        )
    area_ids = [feature.get("properties", {}).get("area_id") for feature in features]
    if len(set(area_ids)) != len(area_ids):
        raise AssertionError(f"{index_path}: area_id values repeat across parts")
    if processed_path is not None:
        processed = json.loads(processed_path.read_text(encoding="utf-8"))
        if processed.get("features") != features:
            raise AssertionError(f"{index_path}: parts in index order differ from {processed_path}")
    print(f"Validated {len(features)} features in {len(parts)} public parts of {index_path}")
    return len(features)


def validate(paths: list[Path] | None = None, *, city: str | None = None) -> None:
    if city is not None:
        ctx = load_city_context(city)
        default_paths = [ctx.data_dir / config.output_name for config in ctx.area_configs.values()]
        selected = paths or [path for path in default_paths if path.exists()]
        if not selected:
            raise FileNotFoundError(f"No processed GeoJSON files were found for city '{city}'")
        for path in selected:
            validate_geojson(path, ctx=ctx)
        if not paths:
            for config in ctx.area_configs.values():
                processed = ctx.data_dir / config.output_name
                if not config.public_part_max_bytes or not processed.exists():
                    continue
                validate_public_parts(
                    ctx.public_dir / parts_index_name(processed.stem),
                    max_bytes=config.public_part_max_bytes,
                    processed_path=processed,
                )
        return

    selected = paths or [path for path in DEFAULT_GEOJSON_PATHS if path.exists()]
    if not selected:
        raise FileNotFoundError("No processed GeoJSON files were found to validate")
    for path in selected:
        validate_geojson(path)
