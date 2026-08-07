"""Tests for no-trade-band and turnover control. TICKET-048. Hand-computed fixtures.

Supersedes the xfail placeholders in the old tests/test_turnover.py (deleted): every
acceptance criterion listed there is covered here against the real implementation.
"""

from __future__ import annotations

import pandas as pd
import pytest

from durable.portfolio.construct import (
    BUFFER_RANK,
    NO_TRADE_BAND,
    TURNOVER_CEILING,
    ConstructionResult,
    apply_no_trade_band,
    construct_portfolio,
    projected_turnover_from_weights,
    select_holdings,
    target_weights,
)


class TestSelectHoldings:
    def test_top_n_selected(self):
        scores = pd.Series({"A": 90, "B": 80, "C": 70, "D": 60, "E": 50, "F": 40})
        selected = select_holdings(scores, current_holdings=[], target=2, buffer_rank=5)
        assert selected == ["A", "B"]

    def test_holding_retained_inside_buffer(self):
        """D is rank index 3 (0-indexed), inside buffer_rank=5 -> retained though outside top 2."""
        scores = pd.Series({"A": 90, "B": 80, "C": 70, "D": 60, "E": 50, "F": 40})
        selected = select_holdings(scores, current_holdings=["D"], target=2, buffer_rank=5)
        assert "D" in selected

    def test_holding_dropped_outside_buffer(self):
        """F is rank index 5; buffer_rank=5 means retained only while rank < 5 -> F drops."""
        scores = pd.Series({"A": 90, "B": 80, "C": 70, "D": 60, "E": 50, "F": 40})
        selected = select_holdings(scores, current_holdings=["F"], target=2, buffer_rank=5)
        assert "F" not in selected


class TestTargetWeights:
    def test_equal_weight_no_caps(self):
        sectors = pd.Series({"A": "Tech", "B": "Health"})
        weights = target_weights(["A", "B"], sectors, max_position=0.50, max_sector=0.90)
        assert weights["A"] == pytest.approx(0.5)
        assert weights["B"] == pytest.approx(0.5)

    def test_position_cap_applied(self):
        """n=1 -> raw weight 1.0, clipped to max_position."""
        sectors = pd.Series({"A": "Tech"})
        weights = target_weights(["A"], sectors, max_position=0.06, max_sector=0.25)
        assert weights["A"] == pytest.approx(0.06)

    def test_sector_cap_rescales_within_sector(self):
        """A, B, C equal-weighted at 1/3 each; A+B share Tech (sum 2/3), capped to 0.6 ->
        each of A, B scaled by 0.6/(2/3) = 0.9 -> 0.3. C (Health) is untouched at 1/3."""
        sectors = pd.Series({"A": "Tech", "B": "Tech", "C": "Health"})
        weights = target_weights(["A", "B", "C"], sectors, max_position=0.50, max_sector=0.60)
        assert weights["A"] == pytest.approx(0.3)
        assert weights["B"] == pytest.approx(0.3)
        assert weights["C"] == pytest.approx(1 / 3)

    def test_empty_selection_returns_empty_series(self):
        weights = target_weights([], pd.Series(dtype=object))
        assert weights.empty


class TestApplyNoTradeBand:
    def test_drift_below_band_holds(self):
        target = pd.Series({"A": 0.10})
        current = pd.Series({"A": 0.08})  # drift 0.02 < 0.03
        result = apply_no_trade_band(target, current, [], [], no_trade_band=0.03)
        assert result["A"] == pytest.approx(0.08)

    def test_drift_exactly_at_band_holds(self):
        """Strict inequality: drift == band does not trade."""
        target = pd.Series({"A": 0.10})
        current = pd.Series({"A": 0.07})  # drift exactly 0.03
        result = apply_no_trade_band(target, current, [], [], no_trade_band=0.03)
        assert result["A"] == pytest.approx(0.07)

    def test_drift_above_band_trades(self):
        target = pd.Series({"A": 0.10})
        current = pd.Series({"A": 0.06})  # drift 0.04 > 0.03
        result = apply_no_trade_band(target, current, [], [], no_trade_band=0.03)
        assert result["A"] == pytest.approx(0.10)

    def test_name_change_ignores_band(self):
        """Exit: target has no entry for A, but A is a name change -> forced to 0 regardless
        of how small the nominal drift would otherwise read."""
        target = pd.Series(dtype=float)
        current = pd.Series({"A": 0.01})
        result = apply_no_trade_band(target, current, ["A"], [], no_trade_band=0.03)
        assert result["A"] == pytest.approx(0.0)

    def test_constraint_breach_ignores_band(self):
        """Drift is 0.001, well under the 0.03 band, but A is a constraint breach ->
        trades to full target anyway."""
        target = pd.Series({"A": 0.061})
        current = pd.Series({"A": 0.06})
        result = apply_no_trade_band(target, current, [], ["A"], no_trade_band=0.03)
        assert result["A"] == pytest.approx(0.061)

    def test_ticker_not_in_target_without_name_change_holds(self):
        """A caller that forgets to pass an exiting ticker in name_changes does not get an
        implicit exit -- apply_no_trade_band only ever zeroes tickers explicitly flagged."""
        target = pd.Series(dtype=float)
        current = pd.Series({"C": 0.03})
        result = apply_no_trade_band(target, current, [], [], no_trade_band=0.03)
        assert result["C"] == pytest.approx(0.03)


class TestProjectedTurnoverFromWeights:
    def test_hand_computed(self):
        current = pd.Series({"A": 0.5, "B": 0.3})
        post = pd.Series({"A": 0.4, "B": 0.3, "C": 0.1})
        # delta = |0.4-0.5| + |0.3-0.3| + |0.1-0| = 0.2 -> quarterly 0.1 -> annualized 0.4
        assert projected_turnover_from_weights(current, post) == pytest.approx(0.4)

    def test_no_change_is_zero_turnover(self):
        w = pd.Series({"A": 0.5, "B": 0.5})
        assert projected_turnover_from_weights(w, w) == pytest.approx(0.0)


class TestConstructPortfolioUncapped:
    def test_within_band_and_ceiling(self):
        scores = pd.Series({"A": 90, "B": 80, "C": 70})
        sectors = pd.Series({"A": "Tech", "B": "Health", "C": "Energy"})
        current_weights = pd.Series({"A": 0.06, "B": 0.06, "C": 0.06})  # already at target
        result = construct_portfolio(
            scores=scores,
            current_holdings=["A", "B", "C"],
            current_weights=current_weights,
            sectors=sectors,
        )
        assert isinstance(result, ConstructionResult)
        assert result.turnover_capped is False
        assert result.notes == []
        assert result.turnover_projected == pytest.approx(0.0)
        assert result.trades_required.empty


class TestConstructPortfolioTurnoverCeiling:
    """SPEC §7.2: above the 60% ceiling, reduce to name changes + constraint breaches only,
    and log the event -- checked BEFORE trading, not reported after."""

    def test_large_drift_with_no_name_changes_is_capped_to_zero_trades(self):
        scores = pd.Series({"A": 90, "B": 80, "C": 70})
        sectors = pd.Series({"A": "Tech", "B": "Health", "C": "Energy"})
        # A is wildly overweight relative to the 0.06 equal-weight target; B, C are already
        # within the no-trade band. With no new_names/breach_names, projected turnover from
        # rebalancing A alone is 168% -- above the 60% default ceiling.
        current_weights = pd.Series({"A": 0.90, "B": 0.05, "C": 0.05})
        result = construct_portfolio(
            scores=scores,
            current_holdings=["A", "B", "C"],
            current_weights=current_weights,
            sectors=sectors,
        )
        assert result.turnover_capped is True
        assert len(result.notes) == 1
        assert "ceiling" in result.notes[0].lower()
        # Capped pass has no name changes or constraint breaches to force -> reverts fully
        # to current weights, i.e. no trades and zero turnover.
        assert result.turnover_projected == pytest.approx(0.0)
        assert result.trades_required.empty
        assert result.target_weights["A"] == pytest.approx(0.90)

    def test_name_change_still_executes_when_capped(self):
        scores = pd.Series({"A": 90, "B": 80, "C": 70, "D": 60})
        sectors = pd.Series({"A": "Tech", "B": "Health", "C": "Energy", "D": "Tech"})
        current_weights = pd.Series({"A": 0.90, "B": 0.05, "C": 0.05})
        result = construct_portfolio(
            scores=scores,
            current_holdings=["A", "B", "C"],
            current_weights=current_weights,
            sectors=sectors,
            new_names=["D"],
        )
        assert result.turnover_capped is True
        # D is a name change: it must appear in the final target at its full weight even
        # though the rebalance was otherwise capped down to nothing.
        assert result.target_weights["D"] == pytest.approx(0.06)
        assert "D" in result.trades_required.index


class TestBufferRank:
    def test_buffer_rank_is_80_sourced_from_turnover_not_returns(self):
        """Buffer rank 80 is chosen on the turnover constraint (SPEC §6, §7.2), not on
        return performance. The measured CAGR sweep across ranks 55-105 was non-monotonic
        (7.36/6.62/8.59/6.58/8.13%) -- noise. No return benefit may be claimed for this
        value; do not retune it against backtest CAGR. See docs/14 §2."""
        assert BUFFER_RANK == 80


class TestModuleConstants:
    def test_no_trade_band_matches_config_default(self):
        assert pytest.approx(0.03) == NO_TRADE_BAND

    def test_turnover_ceiling_matches_kill_criterion(self):
        assert pytest.approx(0.60) == TURNOVER_CEILING
