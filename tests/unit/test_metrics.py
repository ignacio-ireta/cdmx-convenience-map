"""Property tests for the numeric scoring helpers (cdmxmap.scoring.metrics).

These assert invariants (range, monotonicity, shape) rather than exact formulas,
so they remain valid as long as the scoring contract holds.
"""

from __future__ import annotations

import numpy as np
import pytest

from cdmxmap.scoring import metrics as bs


def test_pipeline_entry_points_exist() -> None:
    # Smoke test: the package graph (geopandas/transit imports included) loads.
    import cdmxmap.pipeline
    import cdmxmap.scoring

    assert hasattr(cdmxmap.scoring, "score_areas")
    assert hasattr(cdmxmap.pipeline, "build_area")


class TestDistanceScore:
    def test_scores_stay_in_range(self) -> None:
        scores = bs.distance_score(np.array([100.0, 500.0, 2000.0]))
        assert np.all(scores >= 0)
        assert np.all(scores <= 100)
        assert np.all(np.isfinite(scores))

    def test_closer_is_not_worse(self) -> None:
        scores = bs.distance_score(np.array([100.0, 500.0, 2000.0]))
        # Closer-is-better: the nearest point should not score below the farthest.
        assert scores[0] >= scores[-1]

    def test_shape_is_preserved(self) -> None:
        values = np.array([10.0, 20.0, 30.0, 40.0])
        assert bs.distance_score(values).shape == values.shape


class TestInverseDensityScore:
    def test_scores_stay_in_range(self) -> None:
        scores = bs.inverse_density_score(np.array([0.0, 1.0, 5.0, 25.0]))
        assert np.all(scores >= 0)
        assert np.all(scores <= 100)
        assert np.all(np.isfinite(scores))


class TestRounding:
    def test_round_distance_returns_ints(self) -> None:
        result = bs.round_distance(np.array([1.4, 2.6, 100.0]))
        assert all(isinstance(value, int) for value in result)
        assert len(result) == 3

    def test_round_score_returns_floats(self) -> None:
        result = bs.round_score(np.array([50.456, 99.99]))
        assert all(isinstance(value, float) for value in result)
        assert len(result) == 2

    def test_round_minutes_returns_floats(self) -> None:
        result = bs.round_minutes(np.array([5.123, 42.0]))
        assert all(isinstance(value, float) for value in result)


@pytest.mark.parametrize("digits", [0, 1, 2])
def test_nullable_round_passes_through_none(digits: int) -> None:
    assert bs.nullable_round(None, digits) is None
