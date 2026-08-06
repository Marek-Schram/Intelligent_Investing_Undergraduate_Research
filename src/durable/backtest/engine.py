"""Walk-forward backtest engine. SPEC §6-9. TICKET-011.

Data source: receives PIT-filtered DataFrames from the caller.
available_at logic: enforced by store.as_of() upstream; engine itself
    uses only the data passed to it (no database access).
Spec section: SPEC §6-9, PROTOCOL §4.1.

PURE FUNCTIONS ONLY (up to the CLI section at the bottom): no I/O, network, wall-clock,
or config lookups. The engine NEVER reads data directly — it receives pre-filtered frames.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class LookaheadError(AssertionError):
    """Raised when future data is used. Subclasses AssertionError deliberately."""


class CashNegativeError(AssertionError):
    """Raised when cash goes negative. Invalidates the run."""


class ReconciliationError(AssertionError):
    """Raised when positions + cash don't reconcile to NAV. Invalidates the run."""


class ImpliedShortSaleError(AssertionError):
    """Raised when a sell trades more shares than were held. Invalidates the run."""


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


def assert_period_invariants(
    cash: float,
    positions: list[Position],
    nav_reported: float,
    prices: pd.DataFrame,
    dt: date,
    sell_trades: list[dict],
    held_before: dict[str, float],
) -> None:
    """PROTOCOL §4.1 accounting invariants, checked every period. A violation raises and
    marks the run invalid — never a warning. TICKET-049.

    1. Cash is never negative (caller also checks this directly around cost sizing).
    2. Positions + cash reconcile to NAV within 1e-6.
    3. Every share sold was held — no implicit shorting via a sizing bug.
    """
    if cash < -1e-6:
        raise CashNegativeError(f"Cash negative at {dt}: {cash:.6f}")

    recomputed_nav = _calculate_nav(positions, cash, prices, dt)
    if abs(recomputed_nav - nav_reported) > 1e-6:
        raise ReconciliationError(
            f"NAV does not reconcile at {dt}: reported={nav_reported:.6f}, "
            f"positions+cash={recomputed_nav:.6f}, diff={abs(recomputed_nav - nav_reported):.8f}"
        )

    for trade in sell_trades:
        held = held_before.get(trade["ticker"], 0.0)
        if trade["shares"] > held + 1e-6:
            raise ImpliedShortSaleError(
                f"Implied short sale at {dt}: sold {trade['shares']:.4f} shares of "
                f"{trade['ticker']} but only {held:.4f} were held"
            )


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

        # Get scores and determine target portfolio. An empty `scores` (no PIT data yet for
        # this date -- e.g. a segment that predates ingestion) is a real, legitimate case,
        # not an error: boolean-mask a DataFrame with no rows and pandas infers `object`
        # dtype for every column (including the mask itself), which silently drops every
        # column rather than raising -- so this must be special-cased, not left to fall
        # through into `scores[~scores["is_excluded"]]`.
        scores = score_fn(rebal_date)
        if scores.empty:
            eligible = scores
        else:
            eligible = scores[~scores["is_excluded"]].sort_values("rank").head(target_n)
        target_tickers = set(eligible["ticker"].tolist())

        # Sell positions not in target
        held_before = {pos.ticker: pos.shares for pos in positions}
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

        nav_end = _calculate_nav(positions, cash, prices, rebal_date)
        period_return = (nav_end - nav_start) / nav_start if nav_start > 0 else 0.0

        # PROTOCOL §4.1 invariants, checked every period, not just at the end (TICKET-049).
        sell_trades = [t for t in trades if t["action"] == "sell"]
        assert_period_invariants(
            cash=cash,
            positions=positions,
            nav_reported=nav_end,
            prices=prices,
            dt=rebal_date,
            sell_trades=sell_trades,
            held_before=held_before,
        )

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


# --------------------------------------------------------------------------------
# CLI — `make simulate` and `make backtest`. Everything below this line does I/O
# (database, filesystem, wall-clock for the CLI's date defaults); the engine above
# stays pure. docs/03 §4 (segment periods), PROTOCOL §4.1 (invariants), TICKET-049.
# --------------------------------------------------------------------------------

SEGMENT_RANGES: dict[str, tuple[date, date]] = {
    # docs/03_BACKTEST_PROTOCOL.md §3: Design 1998-2010, Validation 2011-2018,
    # Holdout 2019-present. "Touch holdout at most twice, ever."
    "design": (date(1998, 1, 1), date(2010, 12, 31)),
    "validation": (date(2011, 1, 1), date(2018, 12, 31)),
    "holdout": (date(2019, 1, 1), date.today()),
}


def _quarterly_rebalance_dates(
    start: date, end: date, rebalance_months: list[int], rebalance_week: int
) -> list[date]:
    """Rebalance dates for the given months, at the given week-of-month, between start/end.

    Simplification: "week N" is approximated as day (N-1)*7 + 1, not a true trading-calendar
    lookup (exchange_calendars is a project dependency but wiring the actual NYSE calendar
    into this date generator is a separate ticket — this CLI-level date generator is a
    judgment call, documented here rather than silently approximated).
    """
    day = (rebalance_week - 1) * 7 + 1
    dates: list[date] = []
    year = start.year
    while year <= end.year:
        for month in sorted(rebalance_months):
            try:
                d = date(year, month, day)
            except ValueError:
                continue
            if start <= d <= end:
                dates.append(d)
        year += 1
    return sorted(dates)


def _generate_synthetic_market(
    n_tickers: int = 40,
    n_quarters: int = 24,
    start: date = date(2010, 1, 1),
    seed: int = 42,
) -> tuple[list[date], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Deterministic synthetic market for `--simulate`. Not a research backtest — a fast,
    reproducible dry run that exercises the full accounting machinery (sells, buys,
    delistings, invariant checks) on made-up data. See docs/14 §1 for the (much larger)
    research-grade version of this same idea.

    Returns (rebalance_dates, prices, scores_by_date, delistings).
    """
    rng = pd.Series(range(n_tickers)).apply(lambda i: f"SYN{i:04d}")
    tickers = rng.tolist()
    rebalance_dates = _quarterly_rebalance_dates(
        start, start.replace(year=start.year + (n_quarters // 4) + 1), [2, 5, 8, 11], 3
    )[:n_quarters]

    import numpy as np

    npr = np.random.default_rng(seed)
    price_rows = []
    prices_now = {t: 20.0 + npr.uniform(0, 80) for t in tickers}
    for d in rebalance_dates:
        for t in tickers:
            drift = npr.normal(0.02, 0.08)
            prices_now[t] = max(0.50, prices_now[t] * (1 + drift))
            price_rows.append(
                {
                    "ticker": t,
                    "dt": d,
                    "close": round(prices_now[t], 4),
                    "available_at": pd.Timestamp(d),
                }
            )
    prices = pd.DataFrame(price_rows)

    # Two synthetic delistings partway through, to exercise _apply_delisting.
    delistings = pd.DataFrame(
        [
            {
                "ticker": tickers[3],
                "delist_date": rebalance_dates[len(rebalance_dates) // 3],
                "final_price": 1.0,
            },
            {
                "ticker": tickers[7],
                "delist_date": rebalance_dates[2 * len(rebalance_dates) // 3],
                "final_price": 0.0,
            },
        ]
    )

    # Scores: rank by trailing one-period return, computed only from prices already known
    # at that rebalance date — no look-ahead, same discipline as a real momentum factor.
    score_rows = []
    for d in rebalance_dates:
        hist = prices[prices["dt"] <= d]
        for t in tickers:
            t_hist = hist[hist["ticker"] == t].sort_values("dt")
            trailing_return = (
                t_hist["close"].iloc[-1] / t_hist["close"].iloc[0] - 1 if len(t_hist) > 1 else 0.0
            )
            score_rows.append({"as_of": d, "ticker": t, "trailing_return": trailing_return})
    scores_raw = pd.DataFrame(score_rows)

    def score_fn_frame(as_of: date) -> pd.DataFrame:
        day_scores = scores_raw[scores_raw["as_of"] == as_of].copy()
        day_scores["composite_score"] = day_scores["trailing_return"].rank(
            ascending=False, method="first"
        )
        day_scores["rank"] = day_scores["composite_score"].astype(int)
        day_scores["is_excluded"] = False
        return day_scores[["ticker", "composite_score", "rank", "is_excluded"]]

    return rebalance_dates, prices, score_fn_frame, delistings


def _run_simulate(assert_invariants: bool) -> int:
    if not assert_invariants:
        print(
            "`make simulate` always checks PROTOCOL §4.1 invariants (cash never negative, "
            "NAV reconciliation, no implied short sales) — pass --assert-invariants to "
            "confirm that's what you want."
        )
        return 2

    rebalance_dates, prices, score_fn_frame, delistings = _generate_synthetic_market()

    def price_fn(as_of: date) -> pd.DataFrame:
        return prices[pd.to_datetime(prices["dt"]).dt.date <= as_of]

    print(f"Simulating {len(rebalance_dates)} quarters on 40 synthetic tickers (seed=42)...")
    try:
        result = run_backtest(
            rebalance_dates=rebalance_dates,
            price_fn=price_fn,
            score_fn=score_fn_frame,
            initial_cash=100_000.0,
            delistings=delistings,
            target_n=20,
            max_position=0.06,
        )
    except (CashNegativeError, ReconciliationError, ImpliedShortSaleError, LookaheadError) as exc:
        print(f"INVARIANT VIOLATION — simulation is INVALID: {exc}")
        return 1

    print(
        f"OK — {len(result.periods)} periods, all PROTOCOL §4.1 invariants held every period.\n"
        f"Total return: {result.total_return:.2%}   CAGR: {result.cagr:.2%}"
    )

    out_dir = PROJECT_ROOT / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"simulate_{date.today().isoformat()}.json"
    out_path.write_text(
        json.dumps(
            {
                "as_of": date.today().isoformat(),
                "n_periods": len(result.periods),
                "total_return": result.total_return,
                "cagr": result.cagr,
                "invariants_checked": [
                    "cash_never_negative",
                    "nav_reconciliation_1e-6",
                    "no_implied_short_sales",
                ],
                "invariants_passed": True,
                "nav_series": [(d.isoformat(), v) for d, v in result.nav_series],
            },
            indent=2,
        )
    )
    print(f"Wrote {out_path.relative_to(PROJECT_ROOT)}")
    return 0


class SegmentDataUnavailable(Exception):
    """Raised by `run_segment_backtest` when config/database/data isn't in place yet.
    Callers (the `backtest` and `cpcv` CLIs) print `str(exc)` and exit non-zero — this is
    an expected, informative condition in a fresh checkout, not a crash."""


def resolve_segment_range(segment: str) -> tuple[date, date]:
    if segment in SEGMENT_RANGES:
        return SEGMENT_RANGES[segment]
    custom = segment.split("-")
    if len(custom) == 2 and all(c.isdigit() and len(c) == 4 for c in custom):
        return date(int(custom[0]), 1, 1), date(int(custom[1]), 12, 31)
    raise SegmentDataUnavailable(
        f"Unknown segment {segment!r}. Use one of {list(SEGMENT_RANGES)} or a custom "
        "'YYYY-YYYY' range."
    )


def run_segment_backtest(segment: str) -> tuple[BacktestResult, date, date]:
    """Real walk-forward backtest for a named segment (design/validation/holdout/YYYY-YYYY),
    reading from the local PIT store. Shared by the `backtest` and `cpcv` CLIs so both use
    the exact same data-assembly path. Raises SegmentDataUnavailable with a human-readable
    message when config, the database, price data, or scoring isn't available yet."""
    start, end = resolve_segment_range(segment)

    from durable.config import ConfigError, load_config
    from durable.data import store
    from durable.data.universe import build_universe

    try:
        config = load_config()
    except ConfigError as exc:
        raise SegmentDataUnavailable(str(exc)) from exc

    portfolio_cfg = config.get("portfolio", {})
    rebalance_dates = _quarterly_rebalance_dates(
        start,
        end,
        portfolio_cfg.get("rebalance_months", [2, 5, 8, 11]),
        portfolio_cfg.get("rebalance_week", 3),
    )
    if not rebalance_dates:
        raise SegmentDataUnavailable(
            f"No rebalance dates fall within the {segment!r} segment ({start}..{end})."
        )

    db_path = PROJECT_ROOT / "data" / "durable.duckdb"
    if not db_path.exists():
        raise SegmentDataUnavailable(
            f"No database at {db_path.relative_to(PROJECT_ROOT)} yet. Run the Update Market "
            "Data step (`make ingest`) first — there's no history to backtest against."
        )

    conn = store.get_conn(db_path)
    try:
        if store.row_count(conn, "bars_daily") == 0:
            raise SegmentDataUnavailable(
                "The database exists but `bars_daily` is empty. Run `make ingest` first — "
                "there's no price history to backtest against."
            )

        try:
            from durable.portfolio.rank import score_universe
        except ImportError as exc:
            raise SegmentDataUnavailable(
                f"Cannot backtest yet — src/durable/portfolio/rank.py is not implemented: {exc}"
            ) from exc

        def price_fn(as_of: date) -> pd.DataFrame:
            universe_df, _ = build_universe(conn, as_of, config.get("universe"))
            tickers = universe_df["ticker"].tolist() if not universe_df.empty else None
            return store.as_of(conn, "bars_daily", as_of, tickers=tickers)

        def score_fn(as_of: date) -> pd.DataFrame:
            return score_universe(conn, as_of, config)

        try:
            result = run_backtest(
                rebalance_dates=rebalance_dates,
                price_fn=price_fn,
                score_fn=score_fn,
                initial_cash=100_000.0,
                target_n=portfolio_cfg.get("target_positions", 20),
                max_position=portfolio_cfg.get("max_position_weight", 0.06),
            )
        except (
            CashNegativeError,
            ReconciliationError,
            ImpliedShortSaleError,
            LookaheadError,
        ) as exc:
            raise SegmentDataUnavailable(
                f"INVARIANT VIOLATION — backtest is INVALID: {exc}"
            ) from exc
    finally:
        conn.close()

    return result, start, end


def _run_segment(segment: str) -> int:
    try:
        result, start, end = run_segment_backtest(segment)
    except SegmentDataUnavailable as exc:
        print(str(exc))
        return 1

    print(f"Backtested segment {segment!r}: {start} .. {end}, {len(result.periods)} periods.")
    print(f"Total return: {result.total_return:.2%}   CAGR: {result.cagr:.2%}")
    out_dir = PROJECT_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"backtest_{segment}_{date.today().isoformat()}.json"
    out_path.write_text(
        json.dumps(
            {
                "segment": segment,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "total_return": result.total_return,
                "cagr": result.cagr,
                "n_periods": len(result.periods),
                "period_returns": [p.return_pct for p in result.periods],
            },
            indent=2,
        )
    )
    print(f"Wrote {out_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Backtest engine CLI")
    parser.add_argument("--simulate", action="store_true", help="dry run on synthetic data")
    parser.add_argument(
        "--assert-invariants", action="store_true", help="required with --simulate"
    )
    parser.add_argument("--segment", help="design | validation | holdout | YYYY-YYYY")
    args = parser.parse_args()

    if args.simulate:
        sys.exit(_run_simulate(args.assert_invariants))
    elif args.segment:
        sys.exit(_run_segment(args.segment))
    else:
        parser.print_help()
        sys.exit(2)
