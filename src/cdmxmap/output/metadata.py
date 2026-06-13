"""Run metadata + provenance sidecar (engineering standards §S)."""

from __future__ import annotations

from pathlib import Path

from cdmxmap.config import DEFAULT_WEIGHTS, R5PY_OSM_SOURCE, TRANSIT_SYSTEM_FIELD_SLUGS
from cdmxmap.models import AreaConfig, PointDatasets
from cdmxmap.sources.io import DATA_CONFIG, DATA_PROCESSED, DATA_RAW, ROOT


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
            "transit_system_points": {
                slug: int(len(point_datasets.transit_by_system[system]))
                for system, slug in TRANSIT_SYSTEM_FIELD_SLUGS.items()
            },
            "supermarkets": int(len(point_datasets.supermarkets)),
            "gyms": int(len(point_datasets.gyms)),
            "workplaces": int(len(point_datasets.workplaces)),
            "crime_records": int(len(point_datasets.crimes)),
        },
        "crime": score_metadata["crime"],
        "workplace": score_metadata["workplace"],
        "travel_time": score_metadata["travel_time"],
        "amenity_travel_time": score_metadata["amenity_travel_time"],
        "transit_commute_source": score_metadata["transit_commute"]["transit_commute_source"],
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
