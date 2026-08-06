"""Performance statistics. TICKET-013.

Data source: NAV series from the backtest engine.
available_at logic: N/A (post-hoc statistics on completed backtest).
Spec section: SPEC §10, docs/07.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class PerformanceStats:
    """Complete performance statistics for a return series."""

    total_return: float
    cagr: float
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    volatility: float
    downside_vol: float
    best_month: float
    worst_month: float
    win_rate: float
    n_periods: int


def sharpe_ratio(
    returns: pd.Series | np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 12,
) -> float:
    """Annualized Sharpe ratio matching quantstats convention.

    Sharpe = (mean(excess_returns) / std(excess_returns)) * sqrt(periods_per_year)

    Uses sample std (ddof=1) to match quantstats.
    """
    returns = np.asarray(returns, dtype=np.float64)
    if len(returns) < 2:
        return 0.0

    rf_per_period = risk_free_rate / periods_per_year
    excess = returns - rf_per_period
    std = np.std(excess, ddof=1)

    if std == 0 or np.isnan(std):
        return 0.0

    return float((np.mean(excess) / std) * np.sqrt(periods_per_year))


def sortino_ratio(
    returns: pd.Series | np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 12,
) -> float:
    """Annualized Sortino ratio (downside deviation only)."""
    returns = np.asarray(returns, dtype=np.float64)
    if len(returns) < 2:
        return 0.0

    rf_per_period = risk_free_rate / periods_per_year
    excess = returns - rf_per_period
    downside = excess[excess < 0]

    if len(downside) == 0:
        return float("inf") if np.mean(excess) > 0 else 0.0

    downside_std = np.sqrt(np.mean(downside**2))
    if downside_std == 0:
        return 0.0

    return float((np.mean(excess) / downside_std) * np.sqrt(periods_per_year))


def max_drawdown(returns: pd.Series | np.ndarray) -> float:
    """Maximum drawdown from peak. Returns a negative number."""
    returns = np.asarray(returns, dtype=np.float64)
    if len(returns) == 0:
        return 0.0

    cumulative = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = cumulative / running_max - 1
    return float(np.min(drawdowns))


def cagr(returns: pd.Series | np.ndarray, periods_per_year: int = 12) -> float:
    """Compound annual growth rate."""
    returns = np.asarray(returns, dtype=np.float64)
    if len(returns) == 0:
        return 0.0

    total = np.prod(1 + returns)
    n_years = len(returns) / periods_per_year
    if n_years <= 0 or total <= 0:
        return 0.0

    return float(total ** (1 / n_years) - 1)


def volatility(returns: pd.Series | np.ndarray, periods_per_year: int = 12) -> float:
    """Annualized volatility (sample std)."""
    returns = np.asarray(returns, dtype=np.float64)
    if len(returns) < 2:
        return 0.0
    return float(np.std(returns, ddof=1) * np.sqrt(periods_per_year))


def calmar_ratio(returns: pd.Series | np.ndarray, periods_per_year: int = 12) -> float:
    """Calmar ratio = CAGR / |max drawdown|."""
    dd = max_drawdown(returns)
    if dd == 0:
        return 0.0
    annual_return = cagr(returns, periods_per_year)
    return float(annual_return / abs(dd))


def compute_stats(
    returns: pd.Series | np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 12,
) -> PerformanceStats:
    """Compute full performance statistics suite."""
    returns = np.asarray(returns, dtype=np.float64)

    total = float(np.prod(1 + returns) - 1)
    annual = cagr(returns, periods_per_year)
    sharpe = sharpe_ratio(returns, risk_free_rate, periods_per_year)
    sortino = sortino_ratio(returns, risk_free_rate, periods_per_year)
    dd = max_drawdown(returns)
    calmar = calmar_ratio(returns, periods_per_year)
    vol = volatility(returns, periods_per_year)

    # Downside volatility
    downside_returns = returns[returns < 0]
    dsvol = (
        float(np.std(downside_returns, ddof=1) * np.sqrt(periods_per_year))
        if len(downside_returns) > 1
        else 0.0
    )

    return PerformanceStats(
        total_return=total,
        cagr=annual,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=dd,
        calmar=calmar,
        volatility=vol,
        downside_vol=dsvol,
        best_month=float(np.max(returns)) if len(returns) > 0 else 0.0,
        worst_month=float(np.min(returns)) if len(returns) > 0 else 0.0,
        win_rate=float(np.mean(returns > 0)) if len(returns) > 0 else 0.0,
        n_periods=len(returns),
    )
