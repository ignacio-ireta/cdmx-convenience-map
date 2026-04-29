from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GEOJSON_PATHS = [
    ROOT / "data" / "processed" / "scores_postal_code.geojson",
    ROOT / "data" / "processed" / "scores_colonia.geojson",
    ROOT / "data" / "processed" / "cdmx_postal_scores.geojson",
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

CRIME_COUNT_FIELDS = [
    "crime_incidents_total",
    "crime_incidents_recent_12m",
    "crime_density_recent_12m_per_km2",
]


def assert_number(value: object, *, minimum: float, maximum: float | None = None) -> None:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise AssertionError(f"Expected finite number, got {value!r}")
    if float(value) < minimum:
        raise AssertionError(f"Expected value >= {minimum}, got {value}")
    if maximum is not None and float(value) > maximum:
        raise AssertionError(f"Expected value <= {maximum}, got {value}")


def validate_geojson(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise AssertionError("Processed file is not a FeatureCollection")
    features = payload.get("features", [])
    if not features:
        raise AssertionError("Processed file has no features")

    for feature in features:
        props = feature.get("properties", {})
        for field in GENERIC_FIELDS:
            if not props.get(field):
                raise AssertionError(f"Feature is missing {field}")
        if props.get("area_unit") == "postal_code" and not props.get("postal_code"):
            raise AssertionError("Feature is missing postal_code")
        for field in DISTANCE_FIELDS:
            assert_number(props.get(field), minimum=0)
        for field in TIME_FIELDS:
            assert_number(props.get(field), minimum=0)
        for field in SCORE_FIELDS:
            assert_number(props.get(field), minimum=0, maximum=100)
        for field in CRIME_COUNT_FIELDS:
            assert_number(props.get(field), minimum=0)

    area_unit = features[0].get("properties", {}).get("area_unit", "area")
    print(f"Validated {len(features)} processed {area_unit} features in {path}")
    return len(features)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate processed scored GeoJSON.")
    parser.add_argument(
        "--path",
        action="append",
        type=Path,
        help="GeoJSON path to validate. Can be provided more than once.",
    )
    args = parser.parse_args()

    paths = args.path or [path for path in DEFAULT_GEOJSON_PATHS if path.exists()]
    if not paths:
        raise FileNotFoundError("No processed GeoJSON files were found to validate")
    for path in paths:
        validate_geojson(path)


if __name__ == "__main__":
    main()
