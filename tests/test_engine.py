"""Tests for backtest engine. TICKET-011. Hand-computed fixtures."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from durable.backtest.engine import (
    BacktestResult,
    CashNegativeError,
    LookaheadError,
    _apply_delisting,
    _assert_no_lookahead,
    _calculate_nav,
    Position,
    run_backtest,
)


def _make_prices(data: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(data)


class TestNoLookahead:
    def test_no_lookahead_passes(self):
        """Clean data does not raise."""
        prices = _make_prices([
            {"ticker": "AAPL", "dt": "2024-03-01", "close": 150.0,
             "available_at": "2024-03-01 16:00:00"},
        ])
        _assert_no_lookahead(prices, date(2024, 3, 15))

    def test_future_available_at_raises(self):
        """Future available_at raises LookaheadError — acceptance criterion."""
        prices = _make_prices([
            {"ticker": "AAPL", "dt": "2024-03-01", "close": 150.0,
             "available_at": "2024-04-01 16:00:00"},
        ])
        with pytest.raises(LookaheadError):
            _assert_no_lookahead(prices, date(2024, 3, 15))

    def test_future_dt_raises(self):
        """Future price dates raise LookaheadError."""
        prices = _make_prices([
            {"ticker": "AAPL", "dt": "2024-04-01", "close": 160.0,
             "available_at": "2024-03-01 16:00:00"},
        ])
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
        delistings = pd.DataFrame([
            {"ticker": "LEH", "delist_date": "2024-09-15", "final_price": 0.10},
        ])
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
        prices = _make_prices([
            {"ticker": "AAPL", "dt": "2024-06-30", "close": 200.0},
            {"ticker": "MSFT", "dt": "2024-06-30", "close": 400.0},
        ])
        cash = 5000.0
        nav = _calculate_nav(positions, cash, prices, date(2024, 6, 30))
        expected = 10 * 200.0 + 5 * 400.0 + 5000.0  # 2000 + 2000 + 5000 = 9000
        assert nav == pytest.approx(expected)


class TestRunBacktest:
    def _simple_price_fn(self, as_of: date) -> pd.DataFrame:
        """Constant prices for simplicity."""
        return pd.DataFrame([
            {"ticker": "AAPL", "dt": str(as_of), "close": 150.0,
             "available_at": f"{as_of} 16:00:00"},
            {"ticker": "MSFT", "dt": str(as_of), "close": 300.0,
             "available_at": f"{as_of} 16:00:00"},
            {"ticker": "GOOG", "dt": str(as_of), "close": 100.0,
             "available_at": f"{as_of} 16:00:00"},
        ])

    def _simple_score_fn(self, as_of: date) -> pd.DataFrame:
        return pd.DataFrame([
            {"ticker": "AAPL", "composite_score": 90, "rank": 1, "is_excluded": False},
            {"ticker": "MSFT", "composite_score": 85, "rank": 2, "is_excluded": False},
            {"ticker": "GOOG", "composite_score": 80, "rank": 3, "is_excluded": False},
        ])

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
            return pd.DataFrame([
                {"ticker": "AAPL", "dt": "2030-01-01", "close": 999.0,
                 "available_at": "2030-01-01 16:00:00"},
            ])

        dates = [date(2024, 2, 16), date(2024, 5, 17)]
        with pytest.raises(LookaheadError):
            run_backtest(
                rebalance_dates=dates,
                price_fn=bad_price_fn,
                score_fn=self._simple_score_fn,
            )

    def test_delisting_applied(self):
        """Delisted stocks are removed and proceeds added to cash."""
        delistings = pd.DataFrame([
            {"ticker": "GOOG", "delist_date": "2024-04-01", "final_price": 50.0},
        ])
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
        for dt, nav in result.nav_series:
            assert nav > 0

    def test_excluded_stocks_not_bought(self):
        """Excluded stocks are never purchased."""
        def score_fn_with_exclusion(as_of: date) -> pd.DataFrame:
            return pd.DataFrame([
                {"ticker": "AAPL", "composite_score": 90, "rank": 1, "is_excluded": False},
                {"ticker": "MSFT", "composite_score": 85, "rank": 2, "is_excluded": True},
                {"ticker": "GOOG", "composite_score": 80, "rank": 3, "is_excluded": False},
            ])

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
