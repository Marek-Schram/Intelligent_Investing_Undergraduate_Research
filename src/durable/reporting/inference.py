"""Statistical inference: bootstrap CI, deflated Sharpe. TICKET-019.

Data source: return series from backtests.
available_at logic: N/A (post-hoc inference).
Spec section: docs/07, docs/09.

STATIONARY BLOCK bootstrap, not IID — squared returns are highly persistent.
CI returns NaN below 8 periods. DSR raises if experiment_log.csv is missing.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


class ExperimentLogMissingError(RuntimeError):
    """Raised when experiment_log.csv is missing for DSR calculation."""


@dataclass
class BootstrapCI:
    """Bootstrap confidence interval result."""

    point_estimate: float
    ci_low: float
    ci_high: float
    n_periods: int
    significant: bool  # CI excludes zero


def stationary_block_bootstrap(
    returns: np.ndarray,
    statistic_fn: callable,
    n_boot: int = 10_000,
    avg_block_size: float | None = None,
    confidence: float = 0.95,
    seed: int = 42,
) -> BootstrapCI:
    """Stationary block bootstrap CI. NOT IID — acceptance criterion.

    Uses geometric distribution for block lengths (Politis & Romano 1994).
    Returns NaN CI below 8 periods.

    Parameters
    ----------
    returns : the return series
    statistic_fn : function that computes the statistic from a return series
    n_boot : number of bootstrap replications
    avg_block_size : average block length (default: sqrt(T))
    confidence : confidence level
    seed : random seed for reproducibility
    """
    T = len(returns)

    # Below 8 periods: return NaN
    if T < 8:
        point = statistic_fn(returns)
        return BootstrapCI(
            point_estimate=point,
            ci_low=float("nan"),
            ci_high=float("nan"),
            n_periods=T,
            significant=False,
        )

    if avg_block_size is None:
        avg_block_size = max(2.0, np.sqrt(T))

    # Probability of starting a new block
    p = 1.0 / avg_block_size

    rng = np.random.default_rng(seed)
    point = statistic_fn(returns)
    boot_stats = np.empty(n_boot)

    for b in range(n_boot):
        # Generate stationary block bootstrap sample
        sample = np.empty(T)
        idx = rng.integers(0, T)
        for t in range(T):
            sample[t] = returns[idx]
            # With probability p, jump to a new random position
            idx = rng.integers(0, T) if rng.random() < p else (idx + 1) % T
        boot_stats[b] = statistic_fn(sample)

    alpha = 1 - confidence
    ci_low = float(np.percentile(boot_stats, 100 * alpha / 2))
    ci_high = float(np.percentile(boot_stats, 100 * (1 - alpha / 2)))

    significant = (ci_low > 0) or (ci_high < 0)

    return BootstrapCI(
        point_estimate=point,
        ci_low=ci_low,
        ci_high=ci_high,
        n_periods=T,
        significant=significant,
    )


def deflated_sharpe_ratio(
    sharpe: float,
    n_periods: int,
    n_trials: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014).

    Adjusts for multiple testing. n_trials from experiment_log.csv.
    RAISES if n_trials is not provided (caller must verify log exists).

    Parameters
    ----------
    sharpe : observed Sharpe ratio
    n_periods : number of return observations
    n_trials : number of trials/backtests run (from experiment_log.csv)
    skewness : return skewness
    kurtosis : return kurtosis (excess kurtosis + 3)
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")

    # Expected max Sharpe under null (Euler-Mascheroni approximation)
    from scipy.stats import norm

    e_max_sharpe = (
        norm.ppf(1 - 1 / (2 * n_trials)) * (1 - 0.5772 / np.log(n_trials)) if n_trials > 1 else 0.0
    )

    # PSR (probabilistic Sharpe ratio) standard error, adjusted for skew/kurtosis
    # (Bailey & Lopez de Prado 2014) -- the adjustment lives in this denominator, not in a
    # separately-adjusted numerator.
    se_sharpe = np.sqrt(
        (1 + 0.5 * sharpe**2 - skewness * sharpe + (kurtosis - 3) / 4 * sharpe**2) / n_periods
    )

    if se_sharpe == 0:
        return 0.0

    dsr = float(norm.cdf((sharpe - e_max_sharpe) / se_sharpe))
    return dsr


def require_experiment_log(log_path: str | Path) -> int:
    """Read n_trials from experiment_log.csv. Raises if missing.

    The log defaulting to 1 silently inflates every result — it MUST exist.
    """
    p = Path(log_path)
    if not p.exists():
        raise ExperimentLogMissingError(
            f"experiment_log.csv not found at {log_path}. "
            "DSR requires a trial count — defaulting to 1 silently inflates results."
        )
    # Count non-header lines
    lines = p.read_text().strip().split("\n")
    n_trials = max(1, len(lines) - 1)  # Subtract header
    return n_trials
