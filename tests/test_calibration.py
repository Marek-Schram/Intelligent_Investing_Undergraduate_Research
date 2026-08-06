"""Tests for calibration scoring. TICKET-039."""

from __future__ import annotations

import pytest

from durable.research.calibration import (
    SPARSE_BIN_THRESHOLD,
    Prediction,
    brier_score,
    by_emotional_state,
    calibration_curve,
    compute_calibration,
    discrimination,
    overconfidence_ratio,
    override_performance,
)


class TestBrierScore:
    """Brier matches a hand fixture — acceptance criterion."""

    def test_perfect_calibration(self):
        """100% confidence, always right => Brier = 0."""
        preds = [Prediction(99, True)] * 10
        assert brier_score(preds) == pytest.approx(0.0001, abs=0.001)

    def test_always_50_always_wrong(self):
        """50% confidence, always wrong => (0.5 - 0)^2 = 0.25."""
        preds = [Prediction(50, False)] * 10
        assert brier_score(preds) == pytest.approx(0.25)

    def test_hand_fixture(self):
        """Hand-computed: 3 predictions at 70%, outcomes [T, T, F].
        BS = (1/3)*((0.7-1)^2 + (0.7-1)^2 + (0.7-0)^2)
           = (1/3)*(0.09 + 0.09 + 0.49) = 0.2233..."""
        preds = [
            Prediction(70, True),
            Prediction(70, True),
            Prediction(70, False),
        ]
        expected = (0.09 + 0.09 + 0.49) / 3
        assert brier_score(preds) == pytest.approx(expected, rel=1e-6)

    def test_empty_returns_025(self):
        assert brier_score([]) == 0.25


class TestCalibrationCurve:
    """Curve returns bin counts with sparse bins flagged — acceptance criterion."""

    def test_bins_have_counts(self):
        preds = [Prediction(conf, conf > 70) for conf in range(50, 100)]
        bins = calibration_curve(preds, n_bins=5)
        assert len(bins) == 5
        total_count = sum(b.count for b in bins)
        assert total_count == len(preds)

    def test_sparse_bins_flagged(self):
        """Bins with < SPARSE_BIN_THRESHOLD are flagged."""
        preds = [Prediction(95, True)] * 3  # Only high-confidence bin populated
        bins = calibration_curve(preds, n_bins=5)
        sparse_count = sum(1 for b in bins if b.sparse)
        assert sparse_count >= 4  # Most bins empty/sparse

    def test_sparse_threshold(self):
        assert SPARSE_BIN_THRESHOLD == 5


class TestOverconfidenceRatio:
    """Overconfidence ratio — acceptance criterion."""

    def test_overconfident(self):
        """80% confident, 60% hit rate => ratio = 0.80/0.60 = 1.33."""
        preds = [Prediction(80, True)] * 6 + [Prediction(80, False)] * 4
        ratio = overconfidence_ratio(preds)
        assert ratio == pytest.approx(0.80 / 0.60, rel=1e-6)

    def test_well_calibrated(self):
        """70% confident, 70% hit rate => ratio = 1.0."""
        preds = [Prediction(70, True)] * 7 + [Prediction(70, False)] * 3
        ratio = overconfidence_ratio(preds)
        assert ratio == pytest.approx(1.0, rel=1e-6)


class TestDiscrimination:
    """Discrimination — acceptance criterion."""

    def test_good_discrimination(self):
        """High confidence right, low confidence wrong => positive discrimination."""
        preds = [Prediction(90, True)] * 5 + [Prediction(55, False)] * 5
        disc = discrimination(preds)
        assert disc > 0

    def test_no_discrimination(self):
        """Same hit rate at all confidence levels."""
        preds = (
            [Prediction(90, True)] * 3
            + [Prediction(90, False)] * 2
            + [Prediction(55, True)] * 3
            + [Prediction(55, False)] * 2
        )
        disc = discrimination(preds)
        assert disc == pytest.approx(0.0, abs=0.01)


class TestByEmotionalState:
    """Breakdown by emotional state — acceptance criterion."""

    def test_different_states(self):
        preds = [
            Prediction(70, True, emotional_state="calm"),
            Prediction(70, True, emotional_state="calm"),
            Prediction(70, False, emotional_state="anxious"),
            Prediction(70, False, emotional_state="anxious"),
        ]
        result = by_emotional_state(preds)
        assert result["calm"] == 1.0
        assert result["anxious"] == 0.0

    def test_unrecorded_state(self):
        preds = [Prediction(70, True)]
        result = by_emotional_state(preds)
        assert "unrecorded" in result


class TestOverridePerformance:
    """Override performance cross-referenced — acceptance criterion."""

    def test_overrides_underperform(self):
        preds = (
            [Prediction(70, True, is_override=False)] * 8
            + [Prediction(70, False, is_override=False)] * 2
            + [Prediction(70, True, is_override=True)] * 3
            + [Prediction(70, False, is_override=True)] * 7
        )
        override_hr, system_hr, rec = override_performance(preds)
        assert override_hr == pytest.approx(0.30)
        assert system_hr == pytest.approx(0.80)
        assert "consider stopping" in rec

    def test_insufficient_sample(self):
        preds = [Prediction(70, True, is_override=True)] * 5
        _, _, rec = override_performance(preds)
        assert "insufficient" in rec


class TestFullCalibration:
    def test_compute_calibration(self):
        preds = [Prediction(70, True)] * 7 + [Prediction(70, False)] * 3
        result = compute_calibration(preds)
        assert result.n_predictions == 10
        assert 0 <= result.brier <= 1
        assert result.overconfidence_ratio > 0
