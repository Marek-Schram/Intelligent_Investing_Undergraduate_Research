"""Momentum and trend score. SPEC §4. TICKET-008.

Data source: bars_daily (via pre-filtered DataFrame).
available_at logic: receives only PIT-filtered data from the caller.
Spec section: SPEC §4.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd


def total_return_12_1(
    bars: pd.DataFrame,
    as_of: date,
    corporate_actions: pd.DataFrame | None = None,
) -> float | None:
    """12-month total return excluding the most recent month. SPEC §4.

    'Dividends included' means splits are accounted for via corporate_actions.
    The most recent month is genuinely excluded (standard momentum skip-month).

    Parameters
    ----------
    bars : DataFrame with columns [dt, close] sorted by dt
    as_of : the evaluation date (most recent month ends here)
    corporate_actions : DataFrame with [ex_date, action_type, factor] or None

    Returns None if insufficient data (< 220 trading days in the window).
    """
    if bars.empty:
        return None

    bars = bars.copy()
    bars["dt"] = pd.to_datetime(bars["dt"]).dt.date
    bars = bars.sort_values("dt")

    # Skip most recent month: go back ~21 trading days from as_of
    end_date = as_of - timedelta(days=30)
    # Start date: 12 months before end_date
    start_date = date(end_date.year - 1, end_date.month, end_date.day)

    window = bars[(bars["dt"] >= start_date) & (bars["dt"] <= end_date)]
    if len(window) < 220:
        return None

    start_price = window.iloc[0]["close"]
    end_price = window.iloc[-1]["close"]

    if start_price <= 0:
        return None

    # Adjust for splits within the window
    cumulative_factor = 1.0
    if corporate_actions is not None and not corporate_actions.empty:
        ca = corporate_actions.copy()
        ca["ex_date"] = pd.to_datetime(ca["ex_date"]).dt.date
        splits = ca[
            (ca["action_type"] == "split")
            & (ca["ex_date"] >= start_date)
            & (ca["ex_date"] <= end_date)
        ]
        if not splits.empty:
            cumulative_factor = splits["factor"].prod()

    adjusted_start = start_price / cumulative_factor
    return (end_price - adjusted_start) / adjusted_start


def price_above_sma200(bars: pd.DataFrame, as_of: date) -> bool | None:
    """Whether the current price is above the 200-day simple moving average.

    Returns None if insufficient data (< 200 trading days).
    """
    if bars.empty:
        return None

    bars = bars.copy()
    bars["dt"] = pd.to_datetime(bars["dt"]).dt.date
    bars = bars[bars["dt"] <= as_of].sort_values("dt")

    if len(bars) < 200:
        return None

    current_price = bars.iloc[-1]["close"]
    sma_200 = bars["close"].iloc[-200:].mean()

    return bool(current_price > sma_200)


def momentum_12_1_score(
    return_12_1: float | None,
    sector_returns: list[float] | None = None,
) -> float:
    """12-1 momentum score, sector-ranked (0-10). SPEC §4."""
    if return_12_1 is None:
        return 0.0

    if sector_returns and len(sector_returns) > 1:
        percentile = sum(1 for x in sector_returns if x < return_12_1) / len(
            sector_returns
        )
        return percentile * 10.0

    # Absolute fallback: [-30%, +60%] range
    if return_12_1 >= 0.60:
        return 10.0
    elif return_12_1 <= -0.30:
        return 0.0
    return (return_12_1 + 0.30) / 0.90 * 10.0


def sma200_score(above_sma: bool | None) -> float:
    """Price vs 200-day SMA score (0 or 5). SPEC §4."""
    if above_sma is None:
        return 0.0
    return 5.0 if above_sma else 0.0


def momentum_score(
    bars: pd.DataFrame,
    as_of: date,
    corporate_actions: pd.DataFrame | None = None,
    sector_returns: list[float] | None = None,
) -> tuple[float, dict]:
    """Complete momentum score (0-15). SPEC §4.

    Returns (score, breakdown).
    """
    ret_12_1 = total_return_12_1(bars, as_of, corporate_actions)
    above_sma = price_above_sma200(bars, as_of)

    mom_pts = momentum_12_1_score(ret_12_1, sector_returns)
    sma_pts = sma200_score(above_sma)

    total = mom_pts + sma_pts
    total = min(15.0, max(0.0, total))

    breakdown = {
        "return_12_1": round(ret_12_1, 4) if ret_12_1 is not None else None,
        "above_sma200": above_sma,
        "momentum_12_1_points": round(mom_pts, 2),
        "sma200_points": round(sma_pts, 2),
        "total": round(total, 2),
    }

    return total, breakdown
