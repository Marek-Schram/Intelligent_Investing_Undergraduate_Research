"""Walk-forward backtest engine. SPEC §6-9. TICKET-011.

Data source: receives PIT-filtered DataFrames from the caller.
available_at logic: enforced by store.as_of() upstream; engine itself
    uses only the data passed to it (no database access).
Spec section: SPEC §6-9, PROTOCOL §4.1.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
The engine NEVER reads data directly — it receives pre-filtered frames.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


class LookaheadError(AssertionError):
    """Raised when future data is used. Subclasses AssertionError deliberately."""


class CashNegativeError(AssertionError):
    """Raised when cash goes negative. Invalidates the run."""


@dataclass
class Position:
    ticker: str
    shares: float
    cost_basis: float
    entry_date: date


@dataclass
class PeriodResult:
    period_start: date
    period_end: date
    nav_start: float
    nav_end: float
    cash_start: float
    cash_end: float
    positions_start: list[Position]
    positions_end: list[Position]
    trades: list[dict]
    return_pct: float


@dataclass
class BacktestResult:
    periods: list[PeriodResult]
    total_return: float
    cagr: float
    nav_series: list[tuple[date, float]]


def _assert_no_lookahead(
    prices: pd.DataFrame,
    as_of: date,
) -> None:
    """Assert no future data is present."""
    if prices.empty:
        return
    if "available_at" in prices.columns:
        max_avail = pd.to_datetime(prices["available_at"]).dt.date.max()
        if max_avail > as_of:
            raise LookaheadError(
                f"Future data detected: max available_at={max_avail} > as_of={as_of}"
            )
    if "dt" in prices.columns:
        max_dt = pd.to_datetime(prices["dt"]).dt.date.max()
        if max_dt > as_of:
            raise LookaheadError(f"Future prices detected: max dt={max_dt} > as_of={as_of}")


def _get_price(prices: pd.DataFrame, ticker: str, dt: date) -> float | None:
    """Get the closing price for a ticker on or before a given date."""
    if prices.empty:
        return None
    ticker_prices = prices[prices["ticker"] == ticker].copy()
    ticker_prices["dt"] = pd.to_datetime(ticker_prices["dt"]).dt.date
    ticker_prices = ticker_prices[ticker_prices["dt"] <= dt].sort_values("dt")
    if ticker_prices.empty:
        return None
    return float(ticker_prices.iloc[-1]["close"])


def _apply_delisting(
    positions: list[Position],
    delistings: pd.DataFrame,
    as_of: date,
) -> tuple[list[Position], float]:
    """Apply delisting returns to positions. Returns (remaining_positions, cash_proceeds)."""
    if delistings.empty:
        return positions, 0.0

    delistings = delistings.copy()
    delistings["delist_date"] = pd.to_datetime(delistings["delist_date"]).dt.date

    remaining = []
    proceeds = 0.0

    delisted_tickers = set(delistings[delistings["delist_date"] <= as_of]["ticker"].tolist())

    for pos in positions:
        if pos.ticker in delisted_tickers:
            row = delistings[delistings["ticker"] == pos.ticker].iloc[0]
            final_price = float(row.get("final_price", 0.0))
            proceeds += pos.shares * final_price
        else:
            remaining.append(pos)

    return remaining, proceeds


def _calculate_nav(
    positions: list[Position],
    cash: float,
    prices: pd.DataFrame,
    dt: date,
) -> float:
    """Calculate NAV = sum(positions * price) + cash."""
    total = cash
    for pos in positions:
        price = _get_price(prices, pos.ticker, dt)
        if price is not None:
            total += pos.shares * price
        else:
            total += pos.shares * pos.cost_basis / pos.shares if pos.shares > 0 else 0
    return total


def run_backtest(
    rebalance_dates: list[date],
    price_fn: callable,
    score_fn: callable,
    initial_cash: float = 100_000.0,
    delistings: pd.DataFrame | None = None,
    target_n: int = 20,
    max_position: float = 0.06,
) -> BacktestResult:
    """Run a walk-forward backtest. SPEC §6-9.

    Parameters
    ----------
    rebalance_dates : sorted list of rebalance dates
    price_fn : callable(as_of: date) -> DataFrame with [ticker, dt, close, available_at]
    score_fn : callable(as_of: date) -> DataFrame with [ticker, composite_score, rank, is_excluded]
    initial_cash : starting cash
    delistings : DataFrame with [ticker, delist_date, final_price] or None
    target_n : target number of positions
    max_position : maximum position weight

    Returns BacktestResult.
    """
    if delistings is None:
        delistings = pd.DataFrame(columns=["ticker", "delist_date", "final_price"])

    cash = initial_cash
    positions: list[Position] = []
    periods: list[PeriodResult] = []
    nav_series: list[tuple[date, float]] = [(rebalance_dates[0], initial_cash)]

    for i, rebal_date in enumerate(rebalance_dates):
        prices = price_fn(rebal_date)
        _assert_no_lookahead(prices, rebal_date)

        # Apply delistings
        positions, delist_proceeds = _apply_delisting(positions, delistings, rebal_date)
        cash += delist_proceeds

        nav_start = _calculate_nav(positions, cash, prices, rebal_date)

        # Get scores and determine target portfolio
        scores = score_fn(rebal_date)
        eligible = scores[~scores["is_excluded"]].sort_values("rank").head(target_n)
        target_tickers = set(eligible["ticker"].tolist())

        # Sell positions not in target
        trades = []
        new_positions = []
        for pos in positions:
            if pos.ticker not in target_tickers:
                price = _get_price(prices, pos.ticker, rebal_date)
                if price is not None:
                    cash += pos.shares * price
                    trades.append(
                        {
                            "ticker": pos.ticker,
                            "action": "sell",
                            "shares": pos.shares,
                            "price": price,
                        }
                    )
            else:
                new_positions.append(pos)

        # Buy new positions
        held_tickers = {p.ticker for p in new_positions}
        tickers_to_buy = [t for t in target_tickers if t not in held_tickers]

        if tickers_to_buy:
            nav_for_sizing = _calculate_nav(new_positions, cash, prices, rebal_date)
            target_weight = min(max_position, 1.0 / max(target_n, len(tickers_to_buy)))
            alloc_per_ticker = nav_for_sizing * target_weight

            for ticker in tickers_to_buy:
                price = _get_price(prices, ticker, rebal_date)
                if price is None or price <= 0:
                    continue
                shares = alloc_per_ticker / price
                cost = shares * price
                if cost > cash:
                    shares = cash / price
                    cost = shares * price
                if shares > 0:
                    cash -= cost
                    new_positions.append(
                        Position(
                            ticker=ticker, shares=shares, cost_basis=cost, entry_date=rebal_date
                        )
                    )
                    trades.append(
                        {
                            "ticker": ticker,
                            "action": "buy",
                            "shares": shares,
                            "price": price,
                        }
                    )

        positions = new_positions

        # Assert cash never negative
        if cash < -1e-6:
            raise CashNegativeError(f"Cash negative at {rebal_date}: {cash:.2f}")

        nav_end = _calculate_nav(positions, cash, prices, rebal_date)
        period_return = (nav_end - nav_start) / nav_start if nav_start > 0 else 0.0

        if i > 0:
            periods.append(
                PeriodResult(
                    period_start=rebalance_dates[i - 1],
                    period_end=rebal_date,
                    nav_start=nav_start,
                    nav_end=nav_end,
                    cash_start=cash,
                    cash_end=cash,
                    positions_start=[],
                    positions_end=list(positions),
                    trades=trades,
                    return_pct=period_return,
                )
            )

        nav_series.append((rebal_date, nav_end))

    # Calculate total metrics
    final_nav = nav_series[-1][1] if nav_series else initial_cash
    total_return = (final_nav - initial_cash) / initial_cash

    n_years = (rebalance_dates[-1] - rebalance_dates[0]).days / 365.25
    cagr = (final_nav / initial_cash) ** (1 / n_years) - 1 if n_years > 0 else 0.0

    return BacktestResult(
        periods=periods,
        total_return=total_return,
        cagr=cagr,
        nav_series=nav_series,
    )
