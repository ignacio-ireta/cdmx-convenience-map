"""Typed intermediate model (engineering standards §F).

Fetch -> these frozen dataclasses -> scoring engine -> output writer. Keeping
the model explicit means each stage is separately testable and every output
field is traceable to a source.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np

from cdmxmap.config import (
    COLONIA_ID_FIELDS,
    COLONIA_NAME_FIELDS,
    POSTAL_CODE_FIELDS,
    POSTAL_LABEL_FIELDS,
)
from cdmxmap.sources.io import DATA_RAW


@dataclass(frozen=True)
class AreaConfig:
    area_unit: str
    default_input_path: Path
    output_name: str
    legacy_output_names: tuple[str, ...]
    id_fields: list[str]
    name_fields: list[str]
    source_url_key: str
    source_url: str
    # ``postal_width`` is the zero-pad width for postal-style ids (5 for CDMX
    # postal codes, 4 for Norwegian postnummer); ``None`` marks a named unit
    # (colonia, grunnkrets) that is not normalized as a postal code.
    postal_width: int | None = None
    # Prefix for the postal display_name ("CP " for CDMX); ignored for named units.
    display_prefix: str = "CP "


@dataclass(frozen=True)
class NearestResult:
    distances: np.ndarray
    names: list[str]
    sources: list[str]


@dataclass(frozen=True)
class AmenityRouteResult:
    distances: np.ndarray
    times: np.ndarray
    names: list[str]
    sources: list[str]
    candidate_pairs: int
    estimated_pairs: int
    # Routed distance (meters) of the chosen genuinely-fastest POI; NaN where the
    # row fell back to the straight-line estimate. ``routed_mask`` is True per row
    # that routed (all False without a router); ``routed_count``/``fallback_count``
    # tally per-row outcomes.
    routed_distances: np.ndarray
    routed_mask: np.ndarray
    routed_count: int = 0
    fallback_count: int = 0


@dataclass(frozen=True)
class RoutedWorkResult:
    """Per-mode routed work travel times + routed distance, with per-row fallback.

    ``times[mode]`` is always populated (routed where available, else the
    straight-line estimate). ``routed_distances`` is the routed driving distance in
    meters where the row routed, else NaN. ``sources`` is one honest label per row
    (engine source when fully routed, fallback label otherwise).
    """

    times: dict[str, np.ndarray]
    routed_distances: np.ndarray
    sources: list[str]
    routed_count: dict[str, int]
    fallback_count: dict[str, int]
    error_count: int


@dataclass(frozen=True)
class PointDatasets:
    transit: gpd.GeoDataFrame
    core_transit: gpd.GeoDataFrame
    surface_transit: gpd.GeoDataFrame
    # Keyed by the raw transit-system code (e.g. "METRO", "TBANE").
    transit_by_system: dict[str, gpd.GeoDataFrame]
    supermarkets: gpd.GeoDataFrame
    # Keyed by store-brand slug (e.g. "costco", "rema"); see CityContext.store_brands.
    supermarkets_by_brand: dict[str, gpd.GeoDataFrame]
    gyms: gpd.GeoDataFrame
    workplaces: gpd.GeoDataFrame
    crimes: gpd.GeoDataFrame


@dataclass(frozen=True)
class ScoredAreaResult:
    output: gpd.GeoDataFrame
    metadata: dict


AREA_CONFIGS = {
    "postal_code": AreaConfig(
        area_unit="postal_code",
        default_input_path=DATA_RAW / "correos-postales.json",
        output_name="scores_postal_code.geojson",
        legacy_output_names=("cdmx_postal_scores.geojson",),
        id_fields=POSTAL_CODE_FIELDS,
        name_fields=POSTAL_LABEL_FIELDS,
        source_url_key="postal_codes",
        source_url="https://datos.cdmx.gob.mx/dataset/codigos-postales",
        postal_width=5,
        display_prefix="CP ",
    ),
    "colonia": AreaConfig(
        area_unit="colonia",
        default_input_path=DATA_RAW / "colonias.geojson",
        output_name="scores_colonia.geojson",
        legacy_output_names=(),
        id_fields=COLONIA_ID_FIELDS,
        name_fields=COLONIA_NAME_FIELDS,
        source_url_key="colonias",
        source_url=(
            "https://public.opendatasoft.com/explore/dataset/georef-mexico-colonia/export/"
        ),
    ),
}


def build_area_configs(profile: dict, raw_dir: Path) -> dict[str, AreaConfig]:
    """Build a city's ``{area_unit: AreaConfig}`` from its profile ``area_units``.

    Each entry is an object declaring the unit's input filename, id/name field
    candidates, and output naming. ``default_input_path`` is resolved under the
    city's ``raw_dir``. CDMX does not use this — its configs are the in-code
    ``AREA_CONFIGS`` global, kept byte-stable.
    """
    configs: dict[str, AreaConfig] = {}
    for entry in profile.get("area_units", []):
        if isinstance(entry, str):
            # Bare-string units carry no field mapping; skip (non-CDMX profiles
            # must declare full objects).
            continue
        unit = entry["area_unit"]
        configs[unit] = AreaConfig(
            area_unit=unit,
            default_input_path=raw_dir / entry["default_input"],
            output_name=entry.get("output_name", f"scores_{unit}.geojson"),
            legacy_output_names=tuple(entry.get("legacy_output_names", ())),
            id_fields=list(entry.get("id_fields", [])),
            name_fields=list(entry.get("name_fields", [])),
            source_url_key=entry.get("source_url_key", unit),
            source_url=entry.get("source_url", ""),
            postal_width=entry.get("postal_width"),
            display_prefix=entry.get("display_prefix", "CP "),
        )
    return configs
