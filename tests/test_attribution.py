"""Tests for Brinson attribution. TICKET-020."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from durable.reporting.attribution import (
    BrinsonAttribution,
    brinson_single_period,
    carino_linking,
)


class TestBrinsonSinglePeriod:
    def test_effects_sum_to_excess(self):
        """Brinson effects sum to excess to 1e-10 — acceptance criterion."""
        w_p = pd.Series({"Tech": 0.40, "Health": 0.30, "Finance": 0.30})
        w_b = pd.Series({"Tech": 0.30, "Health": 0.35, "Finance": 0.35})
        r_p = pd.Series({"Tech": 0.08, "Health": 0.04, "Finance": 0.02})
        r_b = pd.Series({"Tech": 0.06, "Health": 0.05, "Finance": 0.03})

        result = brinson_single_period(w_p, w_b, r_p, r_b)

        # Portfolio return
        port_return = (w_p * r_p).sum()
        bench_return = (w_b * r_b).sum()
        expected_excess = port_return - bench_return

        # Sum of effects must equal excess
        effects_sum = result.allocation.sum() + result.selection.sum() + result.interaction.sum()
        assert abs(effects_sum - expected_excess) < 1e-10
        assert abs(result.total_excess - expected_excess) < 1e-10

    def test_interaction_own_column(self):
        """Interaction is its own column — acceptance criterion."""
        w_p = pd.Series({"Tech": 0.50, "Health": 0.50})
        w_b = pd.Series({"Tech": 0.30, "Health": 0.70})
        r_p = pd.Series({"Tech": 0.10, "Health": 0.02})
        r_b = pd.Series({"Tech": 0.05, "Health": 0.03})

        result = brinson_single_period(w_p, w_b, r_p, r_b)

        # Interaction should be non-zero when both weight and return differ
        assert isinstance(result.interaction, pd.Series)
        assert result.interaction.abs().sum() > 0

    def test_zero_excess_when_equal(self):
        """Identical portfolio and benchmark => zero excess."""
        w = pd.Series({"Tech": 0.50, "Health": 0.50})
        r = pd.Series({"Tech": 0.06, "Health": 0.04})

        result = brinson_single_period(w, w, r, r)
        assert abs(result.total_excess) < 1e-10

    def test_pure_allocation_effect(self):
        """Same stock selection, different weights => only allocation matters."""
        w_p = pd.Series({"Tech": 0.60, "Health": 0.40})
        w_b = pd.Series({"Tech": 0.40, "Health": 0.60})
        # Same returns for portfolio and benchmark sectors
        r = pd.Series({"Tech": 0.10, "Health": 0.02})

        result = brinson_single_period(w_p, w_b, r, r)
        # Selection should be zero (same returns)
        assert abs(result.selection.sum()) < 1e-10
        # Interaction should be zero (same returns)
        assert abs(result.interaction.sum()) < 1e-10
        # All excess from allocation
        assert abs(result.allocation.sum() - result.total_excess) < 1e-10


class TestCarinoLinking:
    def test_linked_sums_to_cumulative_excess(self):
        """Carino linking reproduces cumulative excess — acceptance criterion."""
        # Two periods
        w_p = pd.Series({"Tech": 0.50, "Health": 0.50})
        w_b = pd.Series({"Tech": 0.30, "Health": 0.70})
        r_p1 = pd.Series({"Tech": 0.08, "Health": 0.03})
        r_b1 = pd.Series({"Tech": 0.06, "Health": 0.04})
        r_p2 = pd.Series({"Tech": 0.05, "Health": 0.07})
        r_b2 = pd.Series({"Tech": 0.04, "Health": 0.06})

        attr1 = brinson_single_period(w_p, w_b, r_p1, r_b1)
        attr2 = brinson_single_period(w_p, w_b, r_p2, r_b2)

        port_r1 = (w_p * r_p1).sum()
        port_r2 = (w_p * r_p2).sum()
        bench_r1 = (w_b * r_b1).sum()
        bench_r2 = (w_b * r_b2).sum()

        linked = carino_linking(
            [attr1, attr2],
            [port_r1, port_r2],
            [bench_r1, bench_r2],
        )

        # Cumulative excess
        cum_port = (1 + port_r1) * (1 + port_r2) - 1
        cum_bench = (1 + bench_r1) * (1 + bench_r2) - 1
        cum_excess = cum_port - cum_bench

        # Linked total should match cumulative excess
        assert abs(linked.total_excess - cum_excess) < 1e-8

    def test_single_period_passthrough(self):
        """Single period linking is a passthrough."""
        w_p = pd.Series({"Tech": 0.50, "Health": 0.50})
        w_b = pd.Series({"Tech": 0.30, "Health": 0.70})
        r_p = pd.Series({"Tech": 0.08, "Health": 0.03})
        r_b = pd.Series({"Tech": 0.06, "Health": 0.04})

        attr = brinson_single_period(w_p, w_b, r_p, r_b)
        linked = carino_linking([attr], [0.055], [0.046])

        assert abs(linked.total_excess - attr.total_excess) < 1e-10
