"""Pydantic validation for config files (engineering standards §E).

The models validate ``city.json`` and ``places.json`` on load and fail fast with
a `ConfigError`. They are lenient (``extra="allow"``) and the validators return
the *original* dict unchanged, so every downstream consumer — and the byte-for-
byte scored output — is unaffected; only malformed config is rejected.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from cdmxmap.errors import ConfigError

PositiveSpeed = Annotated[float, Field(gt=0)]


class BBox(BaseModel):
    model_config = ConfigDict(extra="allow")

    south: float
    west: float
    north: float
    east: float

    @model_validator(mode="after")
    def _check_ordering(self) -> BBox:
        if self.south >= self.north:
            raise ValueError("bbox south must be less than north")
        if self.west >= self.east:
            raise ValueError("bbox west must be less than east")
        return self


class TransitSystemEntry(BaseModel):
    """One ``transit_systems`` item; ``slug`` becomes part of output field names."""

    model_config = ConfigDict(extra="allow")

    code: str = Field(min_length=1)
    slug: str = Field(pattern=r"^[a-z0-9_]+$")
    group: Literal["core", "surface"] = "surface"
    label: str = ""


class CrimeStatisticsConfig(BaseModel):
    """The ``crime_statistics`` block read by the ``city_statistics`` crime mode."""

    model_config = ConfigDict(extra="allow")

    scope: str | None = None
    area_key_field: str | None = None
    source: str | None = None
    source_label: str | None = None
    scored_label: str | None = None
    population_source: str | None = None
    scored_definition: str | None = None
    scored_offenses: list[str] | None = None


class CrimeSourceConfig(BaseModel):
    """The ``crime_source`` block of an ``incident_points`` profile city."""

    model_config = ConfigDict(extra="allow")

    source: str | None = None
    source_label: str | None = None
    # Meters each area is buffered by before counting incidents; 0/absent = polygon.
    density_buffer_m: int | None = Field(default=None, ge=0, strict=True)


class AreaUnitEntry(BaseModel):
    """One object entry of a profile's ``area_units`` (bare strings are CDMX-only)."""

    model_config = ConfigDict(extra="allow")

    area_unit: str
    # Publish the frontend copy in parts of at most this many bytes (output/parts.py).
    public_part_max_bytes: int | None = Field(default=None, gt=0, strict=True)


class CityProfile(BaseModel):
    model_config = ConfigDict(extra="allow")

    city_id: str
    bbox: BBox
    display_name: str | None = None
    country_code: str | None = None
    timezone: str | None = None
    crs_metric_epsg: int | None = None
    amenity_brands: dict | None = None
    sources: dict | None = None
    crime_mode: Literal["incident_points", "city_statistics"] | None = None
    crime_statistics: CrimeStatisticsConfig | None = None
    crime_source: CrimeSourceConfig | None = None
    transit_systems: list[TransitSystemEntry] | None = None
    area_units: list[AreaUnitEntry | str] | None = None

    @model_validator(mode="after")
    def _check_transit_systems_unique(self) -> CityProfile:
        systems = self.transit_systems or []
        codes = [system.code.strip().upper() for system in systems]
        slugs = [system.slug for system in systems]
        if len(set(codes)) != len(codes):
            raise ValueError("transit_systems codes must be unique (case-insensitive)")
        if len(set(slugs)) != len(slugs):
            raise ValueError("transit_systems slugs must be unique")
        return self


class Workplace(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    postal_code: str | None = None
    source: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class TravelTimeConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str | None = None
    speeds_kmh: dict[str, float] | None = None
    detour_factors: dict[str, float] | None = None


class TransitCommuteSettings(BaseModel):
    """``places.json`` ``transit_commute``; every new key is opt-in (absent = CDMX)."""

    model_config = ConfigDict(extra="allow")

    source: str | None = None
    stop_source_label: str | None = None
    engine_label: str | None = None
    candidate_stop_count: int | None = None
    has_line_data: bool | None = None
    system_speeds_kmh: dict[str, PositiveSpeed] | None = None
    priority_candidate_systems: list[str] | None = None
    priority_candidate_stop_count: int | None = Field(default=None, ge=0)


class RoadRoutingConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    engine: str | None = None
    tiles_dir: str | None = None
    modes: list[str] | None = None
    candidate_count: int | None = None
    version: str | None = None
    osm_source: str | None = None
    osm_md5: str | None = None
    osm_date: str | None = None
    search_filter: dict | None = None


class PlacesConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    workplace: Workplace | None = None
    travel_time: TravelTimeConfig | None = None
    amenity_travel_time: dict | None = None
    transit_commute: TransitCommuteSettings | None = None
    road_routing: RoadRoutingConfig | None = None


def validate_city_profile(data: dict, *, city: str | None = None) -> dict:
    """Validate a city profile; return the original dict unchanged."""
    try:
        CityProfile.model_validate(data)
    except ValidationError as exc:
        label = f" for city '{city}'" if city else ""
        raise ConfigError(f"Invalid city profile{label}: {exc}") from exc
    return data


def validate_places_config(data: dict) -> dict:
    """Validate places.json; return the original dict unchanged."""
    try:
        PlacesConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid places config: {exc}") from exc
    return data
