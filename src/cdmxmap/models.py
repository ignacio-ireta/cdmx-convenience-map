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


@dataclass(frozen=True)
class PointDatasets:
    transit: gpd.GeoDataFrame
    core_transit: gpd.GeoDataFrame
    surface_transit: gpd.GeoDataFrame
    transit_by_system: dict[str, gpd.GeoDataFrame]
    supermarkets: gpd.GeoDataFrame
    costcos: gpd.GeoDataFrame
    walmarts: gpd.GeoDataFrame
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
