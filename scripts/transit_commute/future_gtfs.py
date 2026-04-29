"""Future schedule-aware transit routing integration point.

The current implementation intentionally uses only Apimetro stop points. A real
router should replace the approximation behind the same output fields after a
current GTFS feed and street network are validated.
"""

from __future__ import annotations


def estimate_gtfs_transit_commute_to_work(*_args, **_kwargs):
    raise NotImplementedError(
        "Schedule-aware transit routing is not implemented. Use r5py/R5 or "
        "OpenTripPlanner offline during preprocessing, then emit the same static "
        "transit commute fields."
    )

