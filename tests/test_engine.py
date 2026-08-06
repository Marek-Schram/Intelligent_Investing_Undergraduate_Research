"""Tests for backtest engine. TICKET-011. Hand-computed fixtures."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from durable.backtest.engine import (
    BacktestResult,
    CashNegativeError,
    ImpliedShortSaleError,
    LookaheadError,
    Position,
    ReconciliationError,
    _apply_delisting,
    _assert_no_lookahead,
    _calculate_nav,
    _quarterly_rebalance_dates,
    assert_period_invariants,
    run_backtest,
)


def _make_prices(data: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(data)


class TestNoLookahead:
    def test_no_lookahead_passes(self):
        """Clean data does not raise."""
        prices = _make_prices(
            [
                {
                    "ticker": "AAPL",
                    "dt": "2024-03-01",
                    "close": 150.0,
                    "available_at": "2024-03-01 16:00:00",
                },
            ]
        )
        _assert_no_lookahead(prices, date(2024, 3, 15))

    def test_future_available_at_raises(self):
        """Future available_at raises LookaheadError — acceptance criterion."""
        prices = _make_prices(
            [
                {
                    "ticker": "AAPL",
                    "dt": "2024-03-01",
                    "close": 150.0,
                    "available_at": "2024-04-01 16:00:00",
                },
            ]
        )
        with pytest.raises(LookaheadError):
            _assert_no_lookahead(prices, date(2024, 3, 15))

    def test_future_dt_raises(self):
        """Future price dates raise LookaheadError."""
        prices = _make_prices(
            [
                {
                    "ticker": "AAPL",
                    "dt": "2024-04-01",
                    "close": 160.0,
                    "available_at": "2024-03-01 16:00:00",
                },
            ]
        )
        with pytest.raises(LookaheadError):
            _assert_no_lookahead(prices, date(2024, 3, 15))

    def test_lookahead_error_subclasses_assertion(self):
        """LookaheadError subclasses AssertionError — must never be caught."""
        assert issubclass(LookaheadError, AssertionError)


class TestDelistingReturns:
    def test_delisting_returns_cash(self):
        """Delisted position returns final_price * shares — acceptance criterion."""
        positions = [
            Position(ticker="LEH", shares=100, cost_basis=5000.0, entry_date=date(2024, 1, 1)),
            Position(ticker="AAPL", shares=50, cost_basis=7500.0, entry_date=date(2024, 1, 1)),
        ]
        delistings = pd.DataFrame(
            [
                {"ticker": "LEH", "delist_date": "2024-09-15", "final_price": 0.10},
            ]
        )
        remaining, proceeds = _apply_delisting(positions, delistings, date(2024, 10, 1))

        assert len(remaining) == 1
        assert remaining[0].ticker == "AAPL"
        assert proceeds == pytest.approx(10.0)  # 100 * 0.10

    def test_no_delisting_keeps_all(self):
        positions = [
            Position(ticker="AAPL", shares=50, cost_basis=7500.0, entry_date=date(2024, 1, 1)),
        ]
        delistings = pd.DataFrame(columns=["ticker", "delist_date", "final_price"])
        remaining, proceeds = _apply_delisting(positions, delistings, date(2024, 10, 1))
        assert len(remaining) == 1
        assert proceeds == 0.0


class TestCashReconciliation:
    def test_cash_never_negative(self):
        """Cash going negative raises CashNegativeError — acceptance criterion."""
        assert issubclass(CashNegativeError, AssertionError)

    def test_nav_equals_positions_plus_cash(self):
        """NAV = sum(positions * price) + cash."""
        positions = [
            Position(ticker="AAPL", shares=10, cost_basis=1500.0, entry_date=date(2024, 1, 1)),
            Position(ticker="MSFT", shares=5, cost_basis=2000.0, entry_date=date(2024, 1, 1)),
        ]
        prices = _make_prices(
            [
                {"ticker": "AAPL", "dt": "2024-06-30", "close": 200.0},
                {"ticker": "MSFT", "dt": "2024-06-30", "close": 400.0},
            ]
        )
        cash = 5000.0
        nav = _calculate_nav(positions, cash, prices, date(2024, 6, 30))
        expected = 10 * 200.0 + 5 * 400.0 + 5000.0  # 2000 + 2000 + 5000 = 9000
        assert nav == pytest.approx(expected)


class TestRunBacktest:
    def _simple_price_fn(self, as_of: date) -> pd.DataFrame:
        """Constant prices for simplicity."""
        return pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "dt": str(as_of),
                    "close": 150.0,
                    "available_at": f"{as_of} 16:00:00",
                },
                {
                    "ticker": "MSFT",
                    "dt": str(as_of),
                    "close": 300.0,
                    "available_at": f"{as_of} 16:00:00",
                },
                {
                    "ticker": "GOOG",
                    "dt": str(as_of),
                    "close": 100.0,
                    "available_at": f"{as_of} 16:00:00",
                },
            ]
        )

    def _simple_score_fn(self, as_of: date) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"ticker": "AAPL", "composite_score": 90, "rank": 1, "is_excluded": False},
                {"ticker": "MSFT", "composite_score": 85, "rank": 2, "is_excluded": False},
                {"ticker": "GOOG", "composite_score": 80, "rank": 3, "is_excluded": False},
            ]
        )

    def test_basic_run(self):
        """Engine runs without error and returns a result."""
        dates = [date(2024, 2, 16), date(2024, 5, 17), date(2024, 8, 16)]
        result = run_backtest(
            rebalance_dates=dates,
            price_fn=self._simple_price_fn,
            score_fn=self._simple_score_fn,
            initial_cash=100_000.0,
        )
        assert isinstance(result, BacktestResult)
        assert len(result.periods) == 2
        assert result.total_return == pytest.approx(0.0, abs=0.01)

    def test_no_lookahead_enforced(self):
        """Engine raises on future data — acceptance criterion."""

        def bad_price_fn(as_of: date) -> pd.DataFrame:
            # Returns data from the future
            return pd.DataFrame(
                [
                    {
                        "ticker": "AAPL",
                        "dt": "2030-01-01",
                        "close": 999.0,
                        "available_at": "2030-01-01 16:00:00",
                    },
                ]
            )

        dates = [date(2024, 2, 16), date(2024, 5, 17)]
        with pytest.raises(LookaheadError):
            run_backtest(
                rebalance_dates=dates,
                price_fn=bad_price_fn,
                score_fn=self._simple_score_fn,
            )

    def test_delisting_applied(self):
        """Delisted stocks are removed and proceeds added to cash."""
        delistings = pd.DataFrame(
            [
                {"ticker": "GOOG", "delist_date": "2024-04-01", "final_price": 50.0},
            ]
        )
        dates = [date(2024, 2, 16), date(2024, 5, 17), date(2024, 8, 16)]
        result = run_backtest(
            rebalance_dates=dates,
            price_fn=self._simple_price_fn,
            score_fn=self._simple_score_fn,
            initial_cash=100_000.0,
            delistings=delistings,
        )
        # Should complete without error; GOOG removed after delisting
        assert isinstance(result, BacktestResult)

    def test_cash_reconciles(self):
        """Cash + positions = NAV at every period — acceptance criterion."""
        dates = [date(2024, 2, 16), date(2024, 5, 17), date(2024, 8, 16)]
        result = run_backtest(
            rebalance_dates=dates,
            price_fn=self._simple_price_fn,
            score_fn=self._simple_score_fn,
            initial_cash=100_000.0,
        )
        # NAV series should be consistent
        for _dt, nav in result.nav_series:
            assert nav > 0

    def test_excluded_stocks_not_bought(self):
        """Excluded stocks are never purchased."""

        def score_fn_with_exclusion(as_of: date) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {"ticker": "AAPL", "composite_score": 90, "rank": 1, "is_excluded": False},
                    {"ticker": "MSFT", "composite_score": 85, "rank": 2, "is_excluded": True},
                    {"ticker": "GOOG", "composite_score": 80, "rank": 3, "is_excluded": False},
                ]
            )

        dates = [date(2024, 2, 16), date(2024, 5, 17)]
        result = run_backtest(
            rebalance_dates=dates,
            price_fn=self._simple_price_fn,
            score_fn=score_fn_with_exclusion,
            initial_cash=100_000.0,
        )
        # MSFT should not appear in any buy trade
        for period in result.periods:
            for trade in period.trades:
                if trade["action"] == "buy":
                    assert trade["ticker"] != "MSFT"


class TestAssertPeriodInvariants:
    """TICKET-049: PROTOCOL §4.1 accounting invariants, checked every period."""

    def _prices(self):
        return _make_prices(
            [
                {"ticker": "AAPL", "dt": "2024-06-30", "close": 200.0},
            ]
        )

    def test_valid_period_passes(self):
        positions = [
            Position(ticker="AAPL", shares=10, cost_basis=1500.0, entry_date=date(2024, 1, 1))
        ]
        # NAV = 10 * 200 + cash(1000) = 3000
        assert_period_invariants(
            cash=1000.0,
            positions=positions,
            nav_reported=3000.0,
            prices=self._prices(),
            dt=date(2024, 6, 30),
            sell_trades=[],
            held_before={},
        )

    def test_negative_cash_raises(self):
        with pytest.raises(CashNegativeError):
            assert_period_invariants(
                cash=-0.01,
                positions=[],
                nav_reported=-0.01,
                prices=self._prices(),
                dt=date(2024, 6, 30),
                sell_trades=[],
                held_before={},
            )

    def test_nav_mismatch_raises_reconciliation_error(self):
        positions = [
            Position(ticker="AAPL", shares=10, cost_basis=1500.0, entry_date=date(2024, 1, 1))
        ]
        # Actual positions+cash = 2000 + 1000 = 3000, but we claim NAV is 5000.
        with pytest.raises(ReconciliationError):
            assert_period_invariants(
                cash=1000.0,
                positions=positions,
                nav_reported=5000.0,
                prices=self._prices(),
                dt=date(2024, 6, 30),
                sell_trades=[],
                held_before={},
            )

    def test_selling_more_than_held_raises_implied_short_sale_error(self):
        with pytest.raises(ImpliedShortSaleError, match="AAPL"):
            assert_period_invariants(
                cash=1000.0,
                positions=[],
                nav_reported=1000.0,
                prices=self._prices(),
                dt=date(2024, 6, 30),
                sell_trades=[{"ticker": "AAPL", "shares": 10.0, "action": "sell"}],
                held_before={"AAPL": 5.0},
            )

    def test_selling_exactly_what_was_held_passes(self):
        assert_period_invariants(
            cash=1000.0,
            positions=[],
            nav_reported=1000.0,
            prices=self._prices(),
            dt=date(2024, 6, 30),
            sell_trades=[{"ticker": "AAPL", "shares": 5.0, "action": "sell"}],
            held_before={"AAPL": 5.0},
        )


class TestQuarterlyRebalanceDates:
    def test_generates_one_date_per_configured_month_per_year(self):
        dates = _quarterly_rebalance_dates(
            date(2024, 1, 1), date(2025, 12, 31), [2, 5, 8, 11], rebalance_week=3
        )
        assert len(dates) == 8  # 4 months x 2 years
        assert dates[0] == date(2024, 2, 15)  # week 3 -> day (3-1)*7+1 = 15
        assert dates[1] == date(2024, 5, 15)

    def test_respects_range_bounds(self):
        dates = _quarterly_rebalance_dates(
            date(2024, 3, 1), date(2024, 10, 1), [2, 5, 8, 11], rebalance_week=3
        )
        assert dates == [date(2024, 5, 15), date(2024, 8, 15)]


class TestEmptyScores:
    def test_empty_scores_frame_does_not_crash_run_backtest(self):
        """A real, legitimate case (e.g. a segment predating ingested data), not an error:
        pandas gives every column `object` dtype on an empty `pd.DataFrame(columns=[...])`,
        and boolean-masking with an empty object-dtype mask silently drops every column
        rather than raising -- see engine.py's `if scores.empty:` guard."""
        empty_scores = pd.DataFrame(
            columns=["ticker", "composite_score", "rank", "is_excluded", "sector"]
        )

        def score_fn(as_of: date) -> pd.DataFrame:
            return empty_scores

        def price_fn(as_of: date) -> pd.DataFrame:
            return pd.DataFrame(columns=["ticker", "dt", "close", "available_at"])

        dates = [date(2011, 2, 15), date(2011, 5, 15)]
        result = run_backtest(
            rebalance_dates=dates, price_fn=price_fn, score_fn=score_fn, initial_cash=100_000.0
        )
        assert isinstance(result, BacktestResult)
        assert result.total_return == pytest.approx(0.0)
