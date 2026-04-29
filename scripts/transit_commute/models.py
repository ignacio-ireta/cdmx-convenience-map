from __future__ import annotations

from dataclasses import asdict, dataclass
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

    @classmethod
    def from_mapping(cls, values: dict[str, Any] | None) -> "TransitCommuteConfig":
        if not values:
            return cls()

        defaults = asdict(cls())
        merged = {
            key: values.get(key, default_value)
            for key, default_value in defaults.items()
        }
        merged["candidate_stop_count"] = max(
            1, min(int(merged["candidate_stop_count"]), 25)
        )
        for key in defaults:
            if key in {"source", "candidate_stop_count"}:
                continue
            merged[key] = float(merged[key])
        return cls(**merged)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "candidate_stop_count": self.candidate_stop_count,
            "walking_speed_kmh": self.walking_speed_kmh,
            "speeds_kmh": {
                "metro": self.metro_speed_kmh,
                "metrobus": self.metrobus_speed_kmh,
                "bus": self.bus_speed_kmh,
                "trolleybus": self.trolleybus_speed_kmh,
                "default_transit": self.default_transit_speed_kmh,
            },
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
