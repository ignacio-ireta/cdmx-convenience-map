from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class TransitCommuteConfig:
    walking_speed_kmh: float = 4.8
    metro_speed_kmh: float = 28.0
    metrobus_speed_kmh: float = 18.0
    bus_speed_kmh: float = 14.0
    trolleybus_speed_kmh: float = 14.0
    default_transit_speed_kmh: float = 16.0
    same_line_transfer_penalty_min: float = 2.0
    same_system_different_line_penalty_min: float = 8.0
    different_system_penalty_min: float = 12.0
    max_origin_walk_m: float = 1200.0
    max_destination_walk_m: float = 1200.0
    candidate_stop_count: int = 5
    source: str = "apimetro_stop_pair_approximation"
    # Human-readable provenance of the stop points, used in the per-feature notes
    # and metadata limitations text (e.g. "Apimetro" for CDMX, "OpenStreetMap" for
    # Norway).
    stop_source_label: str = "Apimetro"
    # Machine engine label surfaced in the metadata ``transit_commute.engine`` /
    # ``router.engine`` fields; kept distinct from ``source`` so CDMX stays
    # byte-identical (its historical engine value differs from its source).
    engine_label: str = "apimetro_approximation"
    # Opt-in places.json keys. Their defaults reproduce the historical behavior
    # exactly, so a city that does not declare them is unchanged.
    # In-vehicle speed per upper-cased system code, checked before the CDMX codes.
    system_speeds_kmh: dict[str, float] = field(default_factory=dict, hash=False)
    # True when the stop cache carries real line ids (changes the limitation text).
    has_line_data: bool = False
    # Systems whose nearest ``priority_candidate_stop_count`` stops are added to the
    # origin/destination candidates even when other stops are closer.
    priority_candidate_systems: tuple[str, ...] = ()
    priority_candidate_stop_count: int = 0

    _STR_FIELDS = frozenset({"source", "stop_source_label", "engine_label"})
    _NON_FLOAT_FIELDS = _STR_FIELDS | {
        "candidate_stop_count",
        "system_speeds_kmh",
        "has_line_data",
        "priority_candidate_systems",
        "priority_candidate_stop_count",
    }

    @classmethod
    def from_mapping(cls, values: dict[str, Any] | None) -> TransitCommuteConfig:
        if not values:
            return cls()

        defaults = {k: v for k, v in asdict(cls()).items() if not k.startswith("_")}
        merged = {key: values.get(key, default_value) for key, default_value in defaults.items()}
        merged["candidate_stop_count"] = max(1, min(int(merged["candidate_stop_count"]), 25))
        merged["system_speeds_kmh"] = _system_speeds(values.get("system_speeds_kmh"))
        merged["has_line_data"] = _flag(values.get("has_line_data"))
        merged["priority_candidate_systems"] = _system_codes(
            values.get("priority_candidate_systems")
        )
        merged["priority_candidate_stop_count"] = max(
            0, min(int(values.get("priority_candidate_stop_count") or 0), 25)
        )
        for key in defaults:
            if key in cls._NON_FLOAT_FIELDS:
                continue
            merged[key] = float(merged[key])
        return cls(**merged)

    def to_metadata(self) -> dict[str, Any]:
        speeds_kmh: dict[str, Any] = {
            "metro": self.metro_speed_kmh,
            "metrobus": self.metrobus_speed_kmh,
            "bus": self.bus_speed_kmh,
            "trolleybus": self.trolleybus_speed_kmh,
            "default_transit": self.default_transit_speed_kmh,
        }
        if self.system_speeds_kmh:
            speeds_kmh["systems"] = dict(self.system_speeds_kmh)
        metadata: dict[str, Any] = {
            "source": self.source,
            "candidate_stop_count": self.candidate_stop_count,
            "walking_speed_kmh": self.walking_speed_kmh,
            "speeds_kmh": speeds_kmh,
            "penalties_min": {
                "same_line": self.same_line_transfer_penalty_min,
                "same_system_different_or_unknown_line": (
                    self.same_system_different_line_penalty_min
                ),
                "different_system": self.different_system_penalty_min,
            },
            "max_walk_m": {
                "origin": self.max_origin_walk_m,
                "destination": self.max_destination_walk_m,
            },
        }
        # Opt-in settings are recorded only when set, so default metadata is unchanged.
        if self.has_line_data:
            metadata["has_line_data"] = True
        if self.priority_candidates_enabled:
            metadata["priority_candidates"] = {
                "systems": list(self.priority_candidate_systems),
                "stop_count": self.priority_candidate_stop_count,
            }
        return metadata

    @property
    def priority_candidates_enabled(self) -> bool:
        return bool(self.priority_candidate_systems) and self.priority_candidate_stop_count > 0


def _system_speeds(value: object) -> dict[str, float]:
    if not value:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"system_speeds_kmh must be an object of code -> km/h, got {value!r}")
    speeds = {str(code).strip().upper(): float(speed) for code, speed in value.items()}
    invalid = sorted(code for code, speed in speeds.items() if not speed > 0)
    if invalid:
        raise ValueError(f"system_speeds_kmh must be positive; invalid for {invalid}")
    return speeds


def _system_codes(value: object) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list | tuple):
        raise ValueError(f"priority_candidate_systems must be a list of codes, got {value!r}")
    codes: list[str] = []
    for item in value:
        code = str(item).strip().upper()
        if code and code not in codes:
            codes.append(code)
    return tuple(codes)


def _flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}
