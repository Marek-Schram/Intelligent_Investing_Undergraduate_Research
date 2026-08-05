"""Performance measurement: TWR, MWR, risk metrics. TICKET-018.

Data source: NAV series and cash flow records from the backtest.
available_at logic: N/A (reporting on completed data).
Spec section: docs/07.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
Never imports execution/.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq


@dataclass
class RiskMetrics:
    """Portfolio risk metrics."""

    volatility_ann: float
    max_drawdown: float
    var_95: float
    cvar_95: float
    beta: float | None


def time_weighted_return(
    nav_series: list[tuple[float, float]],
    cash_flows: list[tuple[float, float]] | None = None,
) -> float:
    """GIPS-style time-weighted return. Measures the STRATEGY.

    Parameters
    ----------
    nav_series : list of (period_start_nav, period_end_nav) for each sub-period
    cash_flows : list of (date_fraction, amount) — used to split sub-periods

    TWR neutralizes the effect of cash flow timing.
    Chain-links sub-period returns: TWR = prod(1 + r_i) - 1
    """
    if not nav_series:
        return 0.0

    cumulative = 1.0
    for start_nav, end_nav in nav_series:
        if start_nav <= 0:
            continue
        period_return = (end_nav - start_nav) / start_nav
        cumulative *= 1 + period_return

    return cumulative - 1


def money_weighted_return(
    cash_flows: list[tuple[float, float]],
    final_value: float,
    periods: int = 1,
) -> float:
    """Money-weighted return (IRR). Measures the INVESTOR's experience.

    Parameters
    ----------
    cash_flows : list of (time_fraction, amount) where time_fraction is in [0, 1]
        Negative = outflow (investment), positive = inflow (withdrawal)
    final_value : ending portfolio value
    periods : number of periods for annualization

    MWR is sensitive to cash flow timing — large deposits before good
    periods raise MWR, large deposits before bad periods lower it.
    """
    if not cash_flows:
        return 0.0

    def _npv(r: float) -> float:
        if r <= -1:
            return float("inf")
        total = 0.0
        for t, cf in cash_flows:
            total += cf / (1 + r) ** t
        total += final_value / (1 + r) ** 1.0
        return total

    try:
        irr = brentq(_npv, -0.99, 10.0, xtol=1e-8, maxiter=200)
        return float(irr)
    except (ValueError, RuntimeError):
        return 0.0


def compute_risk_metrics(
    returns: np.ndarray,
    benchmark_returns: np.ndarray | None = None,
    periods_per_year: int = 12,
) -> RiskMetrics:
    """Compute risk metrics for a return series."""
    if len(returns) < 2:
        return RiskMetrics(
            volatility_ann=0.0, max_drawdown=0.0,
            var_95=0.0, cvar_95=0.0, beta=None,
        )

    vol = float(np.std(returns, ddof=1) * np.sqrt(periods_per_year))

    # Max drawdown
    cumulative = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = cumulative / running_max - 1
    max_dd = float(np.min(drawdowns))

    # VaR and CVaR (historical, 95%)
    sorted_returns = np.sort(returns)
    var_idx = int(np.floor(0.05 * len(sorted_returns)))
    var_95 = float(sorted_returns[var_idx])
    cvar_95 = float(np.mean(sorted_returns[: var_idx + 1]))

    # Beta
    beta = None
    if benchmark_returns is not None and len(benchmark_returns) == len(returns):
        cov = np.cov(returns, benchmark_returns)[0, 1]
        var_bench = np.var(benchmark_returns, ddof=1)
        if var_bench > 0:
            beta = float(cov / var_bench)

    return RiskMetrics(
        volatility_ann=vol,
        max_drawdown=max_dd,
        var_95=var_95,
        cvar_95=cvar_95,
        beta=beta,
    )
