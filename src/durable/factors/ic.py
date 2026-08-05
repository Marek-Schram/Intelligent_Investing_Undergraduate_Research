"""Information coefficient analysis. TICKET-043.

Answers the question the portfolio backtest cannot: **is the factor itself predictive?**

A portfolio can look perfectly respectable because of construction -- equal weighting, sector
caps, the top-60 buffer -- while every underlying factor has zero information content. IC is
the direct measurement. See docs/09 section 7 and docs/13 section 2.3.

Data source: factor scores, forward returns from PIT store.
available_at logic: all data filtered via store.as_of(as_of) upstream.
Spec section: docs/09 §7.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr


HORIZONS_QUARTERS = (1, 2, 4, 8)
N_QUANTILES = 5
LOOKAHEAD_IC_THRESHOLD = 0.15


def rank_ic(
    factor: pd.DataFrame,
    forward_returns: pd.DataFrame,
    method: str = "spearman",
) -> pd.Series:
    """Cross-sectional rank IC per date. Returns a Series indexed by date.

    SPEARMAN, not Pearson. Financial cross-sections have fat tails; a linear correlation
    is dominated by a handful of outliers.
    """
    dates = factor.index.intersection(forward_returns.index)
    ics = {}

    for dt in dates:
        f_row = factor.loc[dt].dropna()
        r_row = forward_returns.loc[dt].dropna()
        common = f_row.index.intersection(r_row.index)

        if len(common) < 5:
            continue

        if method == "spearman":
            corr, _ = spearmanr(f_row[common], r_row[common])
        else:
            corr, _ = pearsonr(f_row[common], r_row[common])

        ics[dt] = corr

    return pd.Series(ics, dtype=float)


def ic_summary(ic_series: pd.Series) -> dict:
    """Mean IC, std, information ratio, t-stat, hit rate, n_periods.

    Flags |mean IC| > 0.15 as suspected look-ahead.
    """
    n = len(ic_series)
    if n == 0:
        return {
            "mean_ic": 0.0, "std_ic": 0.0, "ir": 0.0,
            "t_stat": 0.0, "hit_rate": 0.0, "n_periods": 0,
            "suspected_lookahead": False,
        }

    mean_ic = float(ic_series.mean())
    std_ic = float(ic_series.std(ddof=1)) if n > 1 else 0.0
    ir = mean_ic / std_ic if std_ic > 0 else 0.0
    t_stat = ir * np.sqrt(n)
    hit_rate = float((ic_series > 0).sum() / n)

    suspected = abs(mean_ic) > LOOKAHEAD_IC_THRESHOLD

    return {
        "mean_ic": mean_ic,
        "std_ic": std_ic,
        "ir": ir,
        "t_stat": t_stat,
        "hit_rate": hit_rate,
        "n_periods": n,
        "suspected_lookahead": suspected,
    }


def ic_decay(
    factor: pd.DataFrame,
    forward_returns_by_horizon: dict[int, pd.DataFrame],
    horizons: tuple[int, ...] = HORIZONS_QUARTERS,
) -> pd.DataFrame:
    """IC at each forward horizon."""
    rows = []
    for h in horizons:
        if h not in forward_returns_by_horizon:
            rows.append({"horizon": h, "mean_ic": 0.0, "ir": 0.0, "t_stat": 0.0})
            continue
        ic_s = rank_ic(factor, forward_returns_by_horizon[h])
        summary = ic_summary(ic_s)
        rows.append({
            "horizon": h,
            "mean_ic": summary["mean_ic"],
            "ir": summary["ir"],
            "t_stat": summary["t_stat"],
        })
    return pd.DataFrame(rows).set_index("horizon")


def quantile_returns(
    factor: pd.DataFrame,
    forward_returns: pd.DataFrame,
    n_quantiles: int = N_QUANTILES,
) -> pd.DataFrame:
    """Mean forward return per factor quantile."""
    dates = factor.index.intersection(forward_returns.index)
    quantile_rets: dict[int, list[float]] = {q: [] for q in range(1, n_quantiles + 1)}

    for dt in dates:
        f_row = factor.loc[dt].dropna()
        r_row = forward_returns.loc[dt].dropna()
        common = f_row.index.intersection(r_row.index)

        if len(common) < n_quantiles:
            continue

        ranks = f_row[common].rank(method="first")
        quantiles = pd.qcut(ranks, n_quantiles, labels=range(1, n_quantiles + 1))

        for q in range(1, n_quantiles + 1):
            tickers_in_q = quantiles[quantiles == q].index
            if len(tickers_in_q) > 0:
                quantile_rets[q].extend(r_row[tickers_in_q].tolist())

    rows = []
    for q in range(1, n_quantiles + 1):
        rets = quantile_rets[q]
        if rets:
            arr = np.array(rets)
            rows.append({
                "quantile": q,
                "mean_return": float(arr.mean()),
                "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
                "n_obs": len(arr),
                "t_stat": float(arr.mean() / (arr.std(ddof=1) / np.sqrt(len(arr)))) if len(arr) > 1 and arr.std(ddof=1) > 0 else 0.0,
            })
        else:
            rows.append({"quantile": q, "mean_return": 0.0, "std": 0.0, "n_obs": 0, "t_stat": 0.0})

    return pd.DataFrame(rows).set_index("quantile")


def is_monotonic(quantile_table: pd.DataFrame, tolerance: float = 0.0) -> tuple[bool, str]:
    """Are quantile returns monotonically increasing?

    Non-monotonic with large spread = tail effect, not a factor.
    """
    means = quantile_table["mean_return"].values
    if len(means) < 2:
        return True, "insufficient quantiles"

    diffs = np.diff(means)
    monotonic = bool(np.all(diffs >= -tolerance))

    if monotonic:
        return True, "monotonic"

    spread = means[-1] - means[0]
    if abs(spread) > 0.02 and not monotonic:
        return False, "tail effect: large spread but non-monotonic"
    return False, "non-monotonic"


def factor_autocorrelation(factor: pd.DataFrame, lag: int = 1) -> float:
    """Rank autocorrelation of factor across periods.

    Low autocorrelation = high implied turnover = cannot trade quarterly in taxable.
    """
    dates = sorted(factor.index)
    if len(dates) < lag + 1:
        return 0.0

    corrs = []
    for i in range(lag, len(dates)):
        curr = factor.loc[dates[i]].dropna()
        prev = factor.loc[dates[i - lag]].dropna()
        common = curr.index.intersection(prev.index)
        if len(common) >= 5:
            corr, _ = spearmanr(curr[common].rank(), prev[common].rank())
            corrs.append(corr)

    return float(np.mean(corrs)) if corrs else 0.0


def sector_neutral_ic(
    factor: pd.DataFrame,
    forward_returns: pd.DataFrame,
    sectors: pd.Series,
) -> pd.Series:
    """IC computed within sector, then averaged.

    If raw IC strong but sector-neutral IC near zero, the "factor" is a sector bet.
    """
    dates = factor.index.intersection(forward_returns.index)
    ics = {}

    for dt in dates:
        f_row = factor.loc[dt].dropna()
        r_row = forward_returns.loc[dt].dropna()
        common = f_row.index.intersection(r_row.index).intersection(sectors.index)

        if len(common) < 5:
            continue

        sector_ics = []
        for sector in sectors[common].unique():
            mask = sectors[common] == sector
            tickers = common[mask]
            if len(tickers) >= 3:
                f_vals = f_row[tickers]
                if f_vals.nunique() < 2:
                    sector_ics.append(0.0)
                    continue
                corr, _ = spearmanr(f_vals, r_row[tickers])
                if not np.isnan(corr):
                    sector_ics.append(corr)

        if sector_ics:
            ics[dt] = float(np.mean(sector_ics))

    return pd.Series(ics, dtype=float)
