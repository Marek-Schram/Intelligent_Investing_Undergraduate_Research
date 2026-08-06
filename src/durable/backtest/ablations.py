"""Ablation study: all nine variants from one command. SPEC §10. TICKET-014.

Data source: backtest results from the engine.
available_at logic: N/A (post-hoc analysis of completed backtests).
Spec section: SPEC §10.

Uses Newey-West HAC standard errors for t-stats. Reports whether |t| > 2.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


class AblationVariant(Enum):
    """The nine ablation variants. SPEC §10."""

    FULL = "full"
    MINUS_POLITICAL = "minus_political"
    MINUS_INSIDER = "minus_insider"
    MINUS_INSTITUTIONAL = "minus_institutional"
    MINUS_MOMENTUM = "minus_momentum"
    DURABILITY_ONLY = "durability_only"
    VALUATION_ONLY = "valuation_only"
    MINUS_LLM = "minus_llm"
    FF5_MOM_REGRESSION = "ff5_mom_regression"


ALL_VARIANTS = list(AblationVariant)


@dataclass
class AblationResult:
    """Result for one ablation variant."""

    variant: AblationVariant
    excess_return: float
    t_stat: float
    newey_west_se: float
    significant: bool  # |t| > 2
    sharpe: float
    n_periods: int


def newey_west_se(
    residuals: np.ndarray,
    n_lags: int | None = None,
) -> float:
    """Newey-West HAC standard error for the mean.

    Uses Bartlett kernel. Default lags = floor(4 * (T/100)^(2/9)).
    """
    T = len(residuals)
    if T < 2:
        return 0.0

    if n_lags is None:
        n_lags = int(4 * (T / 100) ** (2 / 9))
    n_lags = max(1, n_lags)

    mean = np.mean(residuals)
    demeaned = residuals - mean

    # Gamma_0 (variance)
    gamma_0 = np.sum(demeaned**2) / T

    # Autocovariances with Bartlett weights
    weighted_sum = gamma_0
    for j in range(1, n_lags + 1):
        gamma_j = np.sum(demeaned[j:] * demeaned[:-j]) / T
        weight = 1 - j / (n_lags + 1)  # Bartlett kernel
        weighted_sum += 2 * weight * gamma_j

    # SE of the mean
    se = np.sqrt(weighted_sum / T)
    return float(se)


def t_stat_newey_west(
    returns: np.ndarray, benchmark_returns: np.ndarray | None = None
) -> tuple[float, float]:
    """Compute t-statistic using Newey-West standard errors.

    Returns (t_stat, se).
    """
    if benchmark_returns is not None:
        excess = returns - benchmark_returns
    else:
        excess = returns

    if len(excess) < 2:
        return 0.0, 0.0

    mean_excess = np.mean(excess)
    se = newey_west_se(excess)

    if se == 0:
        return 0.0, 0.0

    t = mean_excess / se
    return float(t), se


def run_ablation(
    variant: AblationVariant,
    returns: np.ndarray,
    benchmark_returns: np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 12,
) -> AblationResult:
    """Run one ablation variant and compute statistics."""
    excess = returns - benchmark_returns
    t, se = t_stat_newey_west(returns, benchmark_returns)

    # Sharpe of excess returns
    mean_excess = np.mean(excess)
    std_excess = np.std(excess, ddof=1)
    sharpe = (mean_excess / std_excess * np.sqrt(periods_per_year)) if std_excess > 0 else 0.0

    return AblationResult(
        variant=variant,
        excess_return=float(np.mean(excess) * periods_per_year),
        t_stat=t,
        newey_west_se=se,
        significant=abs(t) > 2.0,
        sharpe=float(sharpe),
        n_periods=len(returns),
    )


def run_all_ablations(
    variant_returns: dict[AblationVariant, np.ndarray],
    benchmark_returns: np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 12,
) -> list[AblationResult]:
    """Run all nine ablation variants from one call.

    Parameters
    ----------
    variant_returns : dict mapping each variant to its monthly return series
    benchmark_returns : the benchmark (SPY/VTI) return series

    Returns list of AblationResult, one per variant.
    """
    results = []
    for variant in ALL_VARIANTS:
        if variant in variant_returns:
            result = run_ablation(
                variant=variant,
                returns=variant_returns[variant],
                benchmark_returns=benchmark_returns,
                risk_free_rate=risk_free_rate,
                periods_per_year=periods_per_year,
            )
            results.append(result)
    return results


def format_ablation_table(results: list[AblationResult]) -> pd.DataFrame:
    """Format ablation results as a summary table."""
    rows = []
    for r in results:
        rows.append(
            {
                "variant": r.variant.value,
                "excess_return_ann": f"{r.excess_return:.4f}",
                "t_stat": f"{r.t_stat:.2f}",
                "nw_se": f"{r.newey_west_se:.4f}",
                "|t|>2": r.significant,
                "sharpe": f"{r.sharpe:.2f}",
                "n": r.n_periods,
            }
        )
    return pd.DataFrame(rows)
