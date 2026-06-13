"""Pure numeric scoring helpers (closer-is-better scoring, rounding, coercion)."""

from __future__ import annotations

import math

import numpy as np


def distance_score(distances: np.ndarray) -> np.ndarray:
    valid = distances[np.isfinite(distances)]
    if len(valid) == 0:
        return np.zeros_like(distances, dtype=float)
    cap = float(np.nanpercentile(valid, 95))
    if cap <= 0:
        cap = float(np.nanmax(valid)) or 1.0
    clipped = np.clip(distances, 0, cap)
    scores = 100.0 * (1.0 - clipped / cap)
    scores[~np.isfinite(scores)] = 0.0
    return scores


def estimate_travel_minutes(
    distances_m: np.ndarray, mode: str, travel_time_config: dict
) -> np.ndarray:
    speeds = travel_time_config["speeds_kmh"]
    detour_factors = travel_time_config["detour_factors"]
    speed_kmh = float(speeds.get(mode, 0))
    detour_factor = float(detour_factors.get(mode, 1))
    if speed_kmh <= 0:
        return np.full_like(distances_m, np.nan, dtype=float)
    meters_per_minute = speed_kmh * 1000 / 60
    minutes = distances_m.astype(float) * detour_factor / meters_per_minute
    minutes[~np.isfinite(minutes)] = np.nan
    return minutes


def inverse_density_score(values: np.ndarray) -> np.ndarray:
    valid = values[np.isfinite(values)]
    if len(valid) == 0:
        return np.zeros_like(values, dtype=float)
    cap = float(np.nanpercentile(valid, 95))
    if cap <= 0:
        cap = float(np.nanmax(valid)) or 1.0
    clipped = np.clip(values, 0, cap)
    scores = 100.0 * (1.0 - clipped / cap)
    scores[~np.isfinite(scores)] = 0.0
    return scores


def round_distance(values: np.ndarray) -> list[int]:
    clean = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    return np.rint(clean).astype(int).tolist()


def round_score(values: np.ndarray) -> list[float]:
    clean = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    return np.round(np.clip(clean, 0, 100), 1).tolist()


def round_minutes(values: np.ndarray) -> list[float]:
    clean = np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)
    return np.round(np.clip(clean, 0, None), 1).tolist()


def nullable_number(value: object) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def nullable_round(value: object, digits: int) -> float | None:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return round(numeric, digits)
