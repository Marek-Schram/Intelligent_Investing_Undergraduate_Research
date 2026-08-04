"""Information coefficient analysis. TICKET-043.

Answers the question the portfolio backtest cannot: **is the factor itself predictive?**

A portfolio can look perfectly respectable because of construction -- equal weighting, sector
caps, the top-60 buffer -- while every underlying factor has zero information content. IC is
the direct measurement. See docs/09 section 7 and docs/13 section 2.3.

Implemented directly rather than depending on Alphalens, which has been unmaintained since
Quantopian closed. The math is ~200 lines and we need to be able to defend it.
"""

from __future__ import annotations

import pandas as pd

HORIZONS_QUARTERS = (1, 2, 4, 8)
N_QUANTILES = 5


def rank_ic(
    factor: pd.DataFrame,
    forward_returns: pd.DataFrame,
    method: str = "spearman",
) -> pd.Series:
    """Cross-sectional rank IC per date. Returns a Series indexed by date.

    SPEARMAN, not Pearson. Financial cross-sections have fat tails; a linear correlation
    is dominated by a handful of outliers, which is exactly the wrong sensitivity for a
    signal meant to rank an entire universe.
    """
    raise NotImplementedError("TICKET-043")


def ic_summary(ic_series: pd.Series) -> dict:
    """Mean IC, std, information ratio (mean/std), t-stat, hit rate, n_periods.

    Interpretation guardrails that belong in the output, not just the docs:
      - |mean IC| of 0.02-0.05 is typical for a real equity factor.
      - **|mean IC| > 0.15 on real data almost always means look-ahead.** Flag it loudly
        and recommend the backtest-validator subagent before anyone believes it.
      - t-stat < 2 means the factor is indistinguishable from noise on this sample.
      - Always report n_periods. 40 quarters is a small sample and the report must say so.
    """
    raise NotImplementedError("TICKET-043")


def ic_decay(
    factor: pd.DataFrame,
    prices: pd.DataFrame,
    horizons: tuple[int, ...] = HORIZONS_QUARTERS,
) -> pd.DataFrame:
    """IC at each forward horizon. Returns index=horizon, columns=[mean_ic, ir, t_stat].

    The decay curve determines the natural rebalance frequency. **If IC dies inside one
    quarter, our quarterly cycle structurally cannot capture the signal** -- and that is a
    reason to drop the factor, not to trade more often.
    """
    raise NotImplementedError("TICKET-043")


def quantile_returns(
    factor: pd.DataFrame,
    forward_returns: pd.DataFrame,
    n_quantiles: int = N_QUANTILES,
) -> pd.DataFrame:
    """Mean forward return per factor quantile, plus the top-minus-bottom spread.

    Returns index=quantile, columns=[mean_return, std, n_obs, t_stat].
    """
    raise NotImplementedError("TICKET-043")


def is_monotonic(quantile_table: pd.DataFrame, tolerance: float = 0.0) -> tuple[bool, str]:
    """Are quantile returns monotonically increasing?

    **A factor whose quantiles are not monotonic is not a factor; it is noise with a
    threshold.** A non-monotonic table with a large top-minus-bottom spread means you have
    a tail effect -- possibly real, but not the linear signal the score assumes -- and the
    report must say that explicitly rather than quoting the spread alone.
    """
    raise NotImplementedError("TICKET-043")


def factor_autocorrelation(factor: pd.DataFrame, lag: int = 1) -> float:
    """Rank autocorrelation of the factor across periods.

    This is the turnover the factor implies BEFORE any buffer rule. A factor with low
    autocorrelation cannot be traded quarterly in a taxable account regardless of its IC --
    the tax drag will eat it.
    """
    raise NotImplementedError("TICKET-043")


def sector_neutral_ic(
    factor: pd.DataFrame,
    forward_returns: pd.DataFrame,
    sectors: pd.Series,
) -> pd.Series:
    """IC computed within sector, then averaged.

    If raw IC is strong but sector-neutral IC is near zero, the "factor" is a sector bet.
    That is a materially different claim and belongs in the report.
    """
    raise NotImplementedError("TICKET-043")


def full_ic_report(
    factor: pd.DataFrame,
    prices: pd.DataFrame,
    sectors: pd.Series,
    factor_name: str,
) -> dict:
    """Everything above, assembled. Log the run to experiment_log.csv -- an IC test is a
    trial and counts toward the Deflated Sharpe trial count."""
    raise NotImplementedError("TICKET-043")
