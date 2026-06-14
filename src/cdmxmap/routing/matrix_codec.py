"""Binary codec for the area-to-area routed travel-time matrix.

The dynamic-workplace feature lets the browser pick any area as the workplace and
needs routed times *from every area to that one*. We precompute the full N×N
matrix offline and serve it as a compact binary the frontend reads one column at
a time via an HTTP Range request (see ``docs/road-routing.md``).

Layout (per ``area_unit`` and ``mode``):

* values are travel time in **deciminutes** (minutes × 10) as little-endian
  ``uint16`` (``<u2``) — 0.1-min resolution, ceiling ~6553 min;
* the sentinel ``65535`` marks an unreachable / failed cell;
* the buffer is **destination-major** (column-major over an ``[origin, destination]``
  matrix), so the column for one workplace destination ``j`` is the contiguous
  block ``[j·N·2, (j+1)·N·2)`` — a single Range request.

The ``.bin`` carries no header; all metadata (N, dtype, scale, sentinel, axis
order, filenames, provenance) lives in the JSON index sidecar so the frontend
Range math stays trivial and the sidecar is the single source of truth.
"""

from __future__ import annotations

import numpy as np

MATRIX_SCALE = 10  # deciminutes
MATRIX_SENTINEL = 65535
MATRIX_DTYPE = "<u2"  # little-endian uint16
_MAX_ENCODABLE = MATRIX_SENTINEL - 1


def encode_matrix(minutes: np.ndarray) -> bytes:
    """Encode an ``[origin, destination]`` minutes matrix to destination-major bytes.

    ``np.nan``/``inf``, negatives, and values that would overflow ``uint16`` all
    map to the sentinel so they decode back to ``np.nan`` (caller falls back).
    """
    matrix = np.asarray(minutes, dtype=float)
    if matrix.ndim != 2:
        raise ValueError(f"minutes matrix must be 2-D, got shape {matrix.shape}")
    deci = matrix * MATRIX_SCALE
    encoded = np.full(matrix.shape, MATRIX_SENTINEL, dtype=np.uint16)
    valid = np.isfinite(deci) & (deci >= 0)
    rounded = np.rint(np.where(valid, deci, 0.0))
    valid &= rounded <= _MAX_ENCODABLE
    encoded[valid] = rounded[valid].astype(np.uint16)
    # order="F" => column-major => destination-major for an [origin, dest] matrix.
    return encoded.astype(MATRIX_DTYPE).tobytes(order="F")


def decode_matrix(data: bytes, n_origins: int, n_destinations: int) -> np.ndarray:
    """Inverse of :func:`encode_matrix`. Returns minutes with ``np.nan`` for sentinels."""
    expected = n_origins * n_destinations * 2
    if len(data) != expected:
        raise ValueError(f"buffer is {len(data)} bytes, expected {expected}")
    raw = np.frombuffer(data, dtype=MATRIX_DTYPE).reshape((n_origins, n_destinations), order="F")
    minutes = raw.astype(float) / MATRIX_SCALE
    minutes[raw == MATRIX_SENTINEL] = np.nan
    return minutes


def extract_column(data: bytes, n_origins: int, destination_index: int) -> np.ndarray:
    """Decode just one destination column (mirrors the frontend Range fetch)."""
    start = destination_index * n_origins * 2
    end = start + n_origins * 2
    if start < 0 or end > len(data):
        raise IndexError(f"destination column {destination_index} is out of range")
    raw = np.frombuffer(data[start:end], dtype=MATRIX_DTYPE)
    minutes = raw.astype(float) / MATRIX_SCALE
    minutes[raw == MATRIX_SENTINEL] = np.nan
    return minutes


def build_matrix_index(
    *,
    area_unit: str,
    area_ids: list[str],
    mode_files: dict[str, str],
    engine: str,
    version: str,
    profiles: dict[str, str],
    inputs_hash: str,
    osm_source: str | None,
    osm_sha: str | None,
    osm_date: str | None,
    generated_at: str,
) -> dict:
    """Assemble the JSON sidecar describing the matrix binaries for one area unit."""
    return {
        "area_unit": area_unit,
        "n": len(area_ids),
        "dtype": MATRIX_DTYPE,
        "scale": MATRIX_SCALE,
        "sentinel": MATRIX_SENTINEL,
        "axis0": "origin",
        "axis1": "destination",
        "layout": "destination_major",
        "unit": "minutes",
        "area_ids": area_ids,
        "modes": list(mode_files),
        "mode_files": mode_files,
        "engine": engine,
        "version": version,
        "profiles": profiles,
        "inputs_hash": inputs_hash,
        "osm_source": osm_source,
        "osm_sha": osm_sha,
        "osm_date": osm_date,
        "generated_at": generated_at,
    }
