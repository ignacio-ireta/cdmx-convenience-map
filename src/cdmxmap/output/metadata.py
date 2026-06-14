"""Run metadata + provenance sidecar (engineering standards §S)."""

from __future__ import annotations

from pathlib import Path

from cdmxmap.citycontext import CityContext, load_city_context
from cdmxmap.models import AreaConfig, PointDatasets
from cdmxmap.sources.io import DATA_CITIES, DATA_CONFIG, ROOT

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


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
    ctx: CityContext | None = None,
) -> dict:
    ctx = ctx or load_city_context()

    def repo_path(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(ROOT))
        except ValueError:
            return str(path)

    city_places = DATA_CITIES / ctx.city_id / "places.json"
    places_path = city_places if city_places.exists() else DATA_CONFIG / "places.json"

    # Provenance URLs come from the city profile's ``sources`` block, plus the
    # active area unit's source and the always-on Overpass endpoint.
    profile_sources = ctx.profile.get("sources") or {}
    source_urls = {
        config.source_url_key: config.source_url,
        "openstreetmap_overpass": OVERPASS_URL,
        **profile_sources,
    }
    source_urls = {key: value for key, value in source_urls.items() if value}

    return {
        "generated_at": score_metadata["generated_at"],
        "city_id": ctx.city_id,
        "area_unit": config.area_unit,
        "feature_count": score_metadata["feature_count"],
        "weights": ctx.weights,
        "point_counts": {
            "transit_stops": int(len(point_datasets.transit)),
            "transit_core_points": int(len(point_datasets.core_transit)),
            "transit_surface_points": int(len(point_datasets.surface_transit)),
            "transit_system_points": {
                slug: int(len(point_datasets.transit_by_system[code]))
                for code, slug in ctx.transit_slugs.items()
            },
            "supermarkets": int(len(point_datasets.supermarkets)),
            "gyms": int(len(point_datasets.gyms)),
            "workplaces": int(len(point_datasets.workplaces)),
            "crime_records": int(len(point_datasets.crimes)),
        },
        "crime": score_metadata["crime"],
        "workplace": score_metadata["workplace"],
        "travel_time": score_metadata["travel_time"],
        "road_routing": score_metadata.get("road_routing"),
        "amenity_travel_time": score_metadata["amenity_travel_time"],
        "transit_commute_source": score_metadata["transit_commute"]["transit_commute_source"],
        "transit_commute": score_metadata["transit_commute"],
        "source_urls": source_urls,
        "sources": {
            "areas": repo_path(input_path),
            config.area_unit: repo_path(input_path),
            "places_config": repo_path(places_path),
            "transit_stops": repo_path(ctx.data_dir / "transit_stops.csv"),
            "supermarkets": repo_path(ctx.data_dir / "supermarkets.csv"),
            "gyms": repo_path(ctx.data_dir / "gyms.csv"),
            "workplaces_legacy_csv": repo_path(ctx.raw_dir / "workplaces.csv"),
            "crime_points": repo_path(ctx.data_dir / "crime_points.csv"),
        },
        "outputs": {
            "processed": repo_path(output_path),
            "public": repo_path(public_output_path),
            "legacy_processed": [repo_path(path) for path in legacy_output_paths],
            "legacy_public": [repo_path(path) for path in public_legacy_output_paths],
        },
        "notes": score_metadata["notes"],
    }
