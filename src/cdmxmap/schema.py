"""Pydantic validation for config files (engineering standards §E).

The models validate ``city.json`` and ``places.json`` on load and fail fast with
a `ConfigError`. They are lenient (``extra="allow"``) and the validators return
the *original* dict unchanged, so every downstream consumer — and the byte-for-
byte scored output — is unaffected; only malformed config is rejected.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from cdmxmap.errors import ConfigError


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


class RoadRoutingConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    engine: str | None = None
    tiles_dir: str | None = None
    modes: list[str] | None = None
    candidate_count: int | None = None
    version: str | None = None
    osm_source: str | None = None


class PlacesConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    workplace: Workplace | None = None
    travel_time: TravelTimeConfig | None = None
    amenity_travel_time: dict | None = None
    transit_commute: dict | None = None
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
