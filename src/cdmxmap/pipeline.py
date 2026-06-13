"""Pipeline orchestration: build one area unit, or run a full city.

This is the home of the logic that used to live in ``scripts/build_scores.py``'s
``main()`` and ``scripts/run_city.py``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from cdmxmap.config import TRANSIT_ROUTER_APIMETRO, load_places_config
from cdmxmap.models import AREA_CONFIGS
from cdmxmap.output import build_metadata, write_geojson
from cdmxmap.scoring import score_areas
from cdmxmap.scoring.points import load_point_datasets
from cdmxmap.sources.io import DATA_PROCESSED, FRONTEND_PUBLIC_DATA, ensure_dirs

# Source fetchers run as modules, in the order the pipeline expects them.
FETCH_SEQUENCE = [
    "fetch_postal_codes",
    "fetch_colonias",
    "fetch_transit",
    "fetch_supermarkets",
    "fetch_gyms",
    "fetch_crime",
]
CITY_AWARE_FETCHERS = {"fetch_supermarkets", "fetch_gyms"}


def build_area(
    area_unit: str,
    *,
    input_path: Path | None = None,
    output_path: Path | None = None,
    skip_legacy: bool = False,
    transit_router: str = TRANSIT_ROUTER_APIMETRO,
) -> dict:
    """Score one area unit and write its GeoJSON + metadata. Returns the metadata."""
    ensure_dirs()
    config = AREA_CONFIGS[area_unit]
    resolved_input = input_path or config.default_input_path
    resolved_output = output_path or DATA_PROCESSED / config.output_name
    public_output_path = FRONTEND_PUBLIC_DATA / resolved_output.name

    places_config = load_places_config()
    point_datasets = load_point_datasets(places_config)
    scored = score_areas(
        config=config,
        input_path=resolved_input,
        point_datasets=point_datasets,
        places_config=places_config,
        transit_router=transit_router,
    )

    write_geojson(scored.output, resolved_output)
    shutil.copyfile(resolved_output, public_output_path)
    print(f"Copied frontend asset to {public_output_path}")

    legacy_output_paths: list[Path] = []
    public_legacy_output_paths: list[Path] = []
    if not skip_legacy:
        for legacy_name in config.legacy_output_names:
            legacy_path = DATA_PROCESSED / legacy_name
            public_legacy_path = FRONTEND_PUBLIC_DATA / legacy_name
            shutil.copyfile(resolved_output, legacy_path)
            shutil.copyfile(resolved_output, public_legacy_path)
            legacy_output_paths.append(legacy_path)
            public_legacy_output_paths.append(public_legacy_path)
            print(f"Copied legacy asset to {legacy_path}")
            print(f"Copied legacy frontend asset to {public_legacy_path}")

    metadata = build_metadata(
        config=config,
        input_path=resolved_input,
        output_path=resolved_output,
        public_output_path=public_output_path,
        legacy_output_paths=legacy_output_paths,
        public_legacy_output_paths=public_legacy_output_paths,
        point_datasets=point_datasets,
        score_metadata=scored.metadata,
        places_config=places_config,
    )
    metadata_path = DATA_PROCESSED / f"score_metadata_{config.area_unit}.json"
    public_metadata_path = FRONTEND_PUBLIC_DATA / metadata_path.name
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    shutil.copyfile(metadata_path, public_metadata_path)

    legacy_metadata_path = DATA_PROCESSED / "score_metadata.json"
    legacy_public_metadata_path = FRONTEND_PUBLIC_DATA / "score_metadata.json"
    shutil.copyfile(metadata_path, legacy_metadata_path)
    shutil.copyfile(metadata_path, legacy_public_metadata_path)

    print(f"Wrote {metadata_path}")
    print(f"Copied frontend metadata to {public_metadata_path}")
    print(f"Copied legacy metadata to {legacy_metadata_path}")
    print(f"Copied legacy frontend metadata to {legacy_public_metadata_path}")
    return metadata


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def fetch_sources(city: str = "cdmx") -> None:
    """Run every source fetcher in sequence, propagating --city where supported."""
    if city != "cdmx":
        print(
            "Note: only OSM-based fetchers are city-aware today. "
            "CDMX-specific source fetchers still require city adapters.",
            file=sys.stderr,
        )
    for module in FETCH_SEQUENCE:
        cmd = [sys.executable, "-m", f"cdmxmap.sources.{module}"]
        if module in CITY_AWARE_FETCHERS:
            cmd.extend(["--city", city])
        _run(cmd)


def run_city(
    city: str = "cdmx",
    *,
    area_unit: str = "postal_code",
    skip_fetch: bool = False,
    transit_router: str = TRANSIT_ROUTER_APIMETRO,
) -> dict:
    """Fetch sources (unless skipped) and build scores for one area unit."""
    if not skip_fetch:
        fetch_sources(city)
    return build_area(area_unit, transit_router=transit_router)
