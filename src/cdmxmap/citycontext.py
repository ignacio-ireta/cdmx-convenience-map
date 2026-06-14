"""City context: every per-city assumption bundled behind one object.

The multi-city refactor hangs on this. ``load_city_context("cdmx")`` reproduces
the exact constants the pipeline used before this abstraction existed, so any code
path that does not pass a context keeps CDMX behavior byte-for-byte. Other cities
derive their context from ``data/cities/<city>/city.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cdmxmap.config import (
    CORE_TRANSIT_SYSTEMS,
    DEFAULT_WEIGHTS,
    METRIC_CRS,
    TRANSIT_SYSTEM_FIELD_SLUGS,
)
from cdmxmap.errors import ConfigError
from cdmxmap.models import AREA_CONFIGS, AreaConfig, build_area_configs
from cdmxmap.sources.io import (
    DATA_PROCESSED,
    DATA_RAW,
    FRONTEND_PUBLIC_DATA,
    load_city_profile,
)

CDMX_CITY_ID = "cdmx"
CRIME_MODE_INCIDENT_POINTS = "incident_points"
DEFAULT_CORE_WEIGHT = 0.70
DEFAULT_SURFACE_WEIGHT = 0.30


@dataclass(frozen=True)
class TransitSystemSpec:
    """One transit system: how it appears in data, its output slug, and grouping."""

    code: str  # raw value of the "system" column in transit_stops.csv, e.g. "METRO"
    slug: str  # output-column slug, e.g. "metro" -> dist_metro_transit_m
    group: str  # "core" | "surface"


@dataclass(frozen=True)
class StoreBrandSpec:
    """One supermarket brand family rendered as its own column set."""

    slug: str  # output-column slug, e.g. "costco" -> dist_costco_m
    match: tuple[str, ...]  # lowercased substrings matched against supermarkets.brand


@dataclass(frozen=True)
class CityContext:
    """Resolved, immutable per-city configuration threaded through the pipeline."""

    city_id: str
    profile: dict
    metric_crs: str
    weights: dict[str, float]
    transit_systems: tuple[TransitSystemSpec, ...]
    store_brands: tuple[StoreBrandSpec, ...]
    core_weight: float
    surface_weight: float
    crime_mode: str
    area_configs: dict[str, AreaConfig]
    raw_dir: Path
    data_dir: Path
    public_dir: Path

    @property
    def transit_slugs(self) -> dict[str, str]:
        """Ordered ``{system_code: slug}`` — drives engine column emission order."""
        return {spec.code: spec.slug for spec in self.transit_systems}

    @property
    def core_codes(self) -> set[str]:
        return {spec.code for spec in self.transit_systems if spec.group == "core"}

    @property
    def surface_codes(self) -> set[str]:
        return {spec.code for spec in self.transit_systems if spec.group == "surface"}


def _city_subdir(base: Path, city_id: str) -> Path:
    """CDMX uses the flat data dirs (back-compat); other cities nest under <city>/."""
    return base if city_id == CDMX_CITY_ID else base / city_id


def _cdmx_transit_systems() -> tuple[TransitSystemSpec, ...]:
    """Rebuild the CDMX transit specs from the existing constants, in their order."""
    return tuple(
        TransitSystemSpec(
            code=code,
            slug=slug,
            group="core" if code in CORE_TRANSIT_SYSTEMS else "surface",
        )
        for code, slug in TRANSIT_SYSTEM_FIELD_SLUGS.items()
    )


def _cdmx_context(profile: dict) -> CityContext:
    """The CDMX context, built from in-code constants so it is byte-identical to
    the pre-refactor behavior regardless of what cdmx/city.json declares."""
    return CityContext(
        city_id=CDMX_CITY_ID,
        profile=profile,
        metric_crs=METRIC_CRS,
        weights=dict(DEFAULT_WEIGHTS),
        transit_systems=_cdmx_transit_systems(),
        store_brands=(
            StoreBrandSpec(slug="costco", match=("costco",)),
            StoreBrandSpec(slug="walmart", match=("walmart",)),
        ),
        core_weight=DEFAULT_CORE_WEIGHT,
        surface_weight=DEFAULT_SURFACE_WEIGHT,
        crime_mode=CRIME_MODE_INCIDENT_POINTS,
        area_configs=AREA_CONFIGS,
        raw_dir=DATA_RAW,
        data_dir=DATA_PROCESSED,
        public_dir=FRONTEND_PUBLIC_DATA,
    )


def _transit_systems_from_profile(profile: dict) -> tuple[TransitSystemSpec, ...]:
    specs = profile.get("transit_systems") or []
    return tuple(
        TransitSystemSpec(
            code=str(spec["code"]),
            slug=str(spec["slug"]),
            group=str(spec.get("group", "surface")),
        )
        for spec in specs
    )


def _store_brands_from_profile(profile: dict) -> tuple[StoreBrandSpec, ...]:
    declared = profile.get("store_brands")
    if declared:
        return tuple(
            StoreBrandSpec(
                slug=str(brand["slug"]),
                match=tuple(
                    str(token).lower() for token in (brand.get("match") or [brand["slug"]])
                ),
            )
            for brand in declared
        )
    # Fall back to amenity_brands.supermarkets: one column family per brand.
    brands = (profile.get("amenity_brands") or {}).get("supermarkets") or []
    return tuple(
        StoreBrandSpec(slug=str(brand).lower(), match=(str(brand).lower(),)) for brand in brands
    )


def _profile_context(city: str, profile: dict) -> CityContext:
    crs_epsg = profile.get("crs_metric_epsg")
    if crs_epsg is None:
        raise ConfigError(f"City profile '{city}' is missing crs_metric_epsg")
    weights = profile.get("default_weights") or dict(DEFAULT_WEIGHTS)
    raw_dir = _city_subdir(DATA_RAW, city)
    area_configs = build_area_configs(profile, raw_dir)
    if not area_configs:
        raise ConfigError(
            f"City profile '{city}' must declare at least one complete area_units entry"
        )
    weights = {key: float(value) for key, value in weights.items()}
    if set(weights) != set(DEFAULT_WEIGHTS):
        raise ConfigError(
            f"City profile '{city}' default_weights must define {sorted(DEFAULT_WEIGHTS)}"
        )
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ConfigError(f"City profile '{city}' default_weights must sum to 1")
    return CityContext(
        city_id=city,
        profile=profile,
        metric_crs=f"EPSG:{int(crs_epsg)}",
        weights=weights,
        transit_systems=_transit_systems_from_profile(profile),
        store_brands=_store_brands_from_profile(profile),
        core_weight=float(profile.get("transit_core_weight", DEFAULT_CORE_WEIGHT)),
        surface_weight=float(profile.get("transit_surface_weight", DEFAULT_SURFACE_WEIGHT)),
        crime_mode=str(profile.get("crime_mode", CRIME_MODE_INCIDENT_POINTS)),
        area_configs=area_configs,
        raw_dir=raw_dir,
        data_dir=_city_subdir(DATA_PROCESSED, city),
        public_dir=_city_subdir(FRONTEND_PUBLIC_DATA, city),
    )


def load_city_context(city: str = CDMX_CITY_ID) -> CityContext:
    """Load and resolve a city's full pipeline context from its profile."""
    profile = load_city_profile(city)
    if city == CDMX_CITY_ID:
        return _cdmx_context(profile)
    return _profile_context(city, profile)
