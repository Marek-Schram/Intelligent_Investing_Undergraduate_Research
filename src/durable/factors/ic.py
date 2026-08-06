"""Information coefficient analysis. TICKET-043.

Answers the question the portfolio backtest cannot: **is the factor itself predictive?**

A portfolio can look perfectly respectable because of construction -- equal weighting, sector
caps, the top-60 buffer -- while every underlying factor has zero information content. IC is
the direct measurement. See docs/09 section 7 and docs/13 section 2.3.

Data source: factor scores, forward returns from PIT store.
available_at logic: all data filtered via store.as_of(as_of) upstream.
Spec section: docs/09 §7.

The functions below this line (through `factor_autocorrelation`) are PURE: no I/O, network,
wall-clock, or config lookups. The `--factor` CLI at the bottom of this file is deliberately
NOT pure -- it opens the DuckDB store, reads config/config.yaml, writes reports/, and appends
to reports/experiment_log.csv. That I/O is confined to the CLI section; it is never mixed into
the analysis functions above.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

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
            "mean_ic": 0.0,
            "std_ic": 0.0,
            "ir": 0.0,
            "t_stat": 0.0,
            "hit_rate": 0.0,
            "n_periods": 0,
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
        rows.append(
            {
                "horizon": h,
                "mean_ic": summary["mean_ic"],
                "ir": summary["ir"],
                "t_stat": summary["t_stat"],
            }
        )
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
            rows.append(
                {
                    "quantile": q,
                    "mean_return": float(arr.mean()),
                    "std": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
                    "n_obs": len(arr),
                    "t_stat": float(arr.mean() / (arr.std(ddof=1) / np.sqrt(len(arr))))
                    if len(arr) > 1 and arr.std(ddof=1) > 0
                    else 0.0,
                }
            )
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


# ==================================================================================
# CLI: `python -m durable.factors.ic --factor {durability,valuation,momentum,overlays}`
# Everything below does I/O (store reads, config reads, file writes) — see module docstring.
# ==================================================================================

import argparse  # noqa: E402
import csv  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from datetime import date, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import TYPE_CHECKING  # noqa: E402

from durable.config import PROJECT_ROOT, ConfigError, load_config  # noqa: E402
from durable.data.prices import get_total_return  # noqa: E402
from durable.data.store import get_conn, init_schema  # noqa: E402
from durable.portfolio.rank import _component_scores  # noqa: E402

if TYPE_CHECKING:
    import duckdb

FACTOR_COLUMN = {
    "durability": "durability_score",
    "valuation": "valuation_score",
    "momentum": "momentum_score",
    "overlays": "overlay_score",
}

# H6 in research/protocol/preregistration.md is the standing preregistered hypothesis that
# covers "mean rank IC for each component factor" — every `make ic` run tests it.
IC_HYPOTHESIS_ID = "H6"


def _third_friday(year: int, month: int) -> date:
    """Third Friday of (year, month). SPEC §9 rebalance-day rule."""
    d = date(year, month, 1)
    first_friday = d + timedelta(days=(4 - d.weekday()) % 7)
    return first_friday + timedelta(days=14)


def _quarterly_rebalance_dates(
    end: date,
    n_periods: int,
    rebalance_months: tuple[int, ...] = (2, 5, 8, 11),
) -> list[date]:
    """The `n_periods` most recent quarterly rebalance dates on/before `end`, ascending.

    Deterministic given `end` — no wall-clock read. `end` is supplied by the CLI's
    `--as-of` argument (defaulting to `date.today()` only in argument parsing, never here).
    """
    years_back = n_periods // len(rebalance_months) + 2
    dates = [
        _third_friday(y, m)
        for y in range(end.year - years_back, end.year + 1)
        for m in rebalance_months
    ]
    dates = sorted(d for d in dates if d <= end)
    return dates[-n_periods:] if n_periods > 0 else dates


def _horizon_end_date(
    start: date, horizon_quarters: int, rebalance_months: tuple[int, ...] = (2, 5, 8, 11)
) -> date:
    """The rebalance date `horizon_quarters` quarterly steps after `start`."""
    months = sorted(rebalance_months)
    year, month = start.year, start.month
    for _ in range(horizon_quarters):
        later = [m for m in months if m > month]
        if later:
            month = later[0]
        else:
            month = months[0]
            year += 1
    return _third_friday(year, month)


def _build_factor_panel(
    conn: duckdb.DuckDBPyConnection,
    factor: str,
    dates: list[date],
    config: dict,
) -> pd.DataFrame:
    """Wide factor panel: index=date, columns=ticker, values=the named component score.

    Excluded names score NaN for `valuation` (matches `_component_scores`'s own NaN
    convention) so they are naturally dropped by `rank_ic`'s `.dropna()`.
    """
    column = FACTOR_COLUMN[factor]
    rows: dict[date, pd.Series] = {}
    for dt in dates:
        detail = _component_scores(conn, dt, config)
        if detail.empty or column not in detail.columns:
            continue
        rows[dt] = detail.set_index("ticker")[column]
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).T.sort_index()


def _build_forward_returns_panel(
    conn: duckdb.DuckDBPyConnection,
    tickers: list[str],
    dates: list[date],
    horizon_quarters: int,
    rebalance_months: tuple[int, ...] = (2, 5, 8, 11),
) -> pd.DataFrame:
    """Wide forward-total-return panel for one horizon: index=date, columns=ticker.

    Uses `data/prices.py::get_total_return` — raw OHLCV plus corporate-action factors,
    never an adjusted-close series (CLAUDE.md: "Never use adjusted-close-only price
    loaders"). `as_of_date` is passed as the horizon end date: this is a retrospective
    IC measurement (what actually happened between two past rebalance dates), not a live
    trading decision, so looking at realized prices up to the horizon end is correct, not
    a look-ahead violation.
    """
    rows: dict[date, dict[str, float]] = {}
    for dt in dates:
        end = _horizon_end_date(dt, horizon_quarters, rebalance_months)
        row: dict[str, float] = {}
        for ticker in tickers:
            row[ticker] = get_total_return(conn, ticker, dt, end, as_of_date=end)
        rows[dt] = row
    return pd.DataFrame(rows).T.sort_index()


def _preregistered() -> bool:
    """Whether H6 (the factor-IC hypothesis) is on record in the preregistration protocol."""
    path = PROJECT_ROOT / "research" / "protocol" / "preregistration.md"
    if not path.is_file():
        return False
    return IC_HYPOTHESIS_ID in path.read_text()


def _log_experiment(
    factor: str,
    as_of_date: date,
    n_periods: int,
    summary: dict,
    monotonic: bool,
    log_path: Path | None = None,
) -> None:
    """Append one row to reports/experiment_log.csv. docs/09 §7: "An IC test is a trial and
    counts toward the Deflated Sharpe trial count. Log it." Append-only; never rewrites
    prior rows (research-integrity.md rule 2: log every run, including ones you don't like).
    `log_path` defaults to reports/experiment_log.csv; overridable for tests so test runs
    never mutate the real, tracked log.
    """
    if log_path is None:
        log_path = PROJECT_ROOT / "reports" / "experiment_log.csv"
    columns = [
        "run_id",
        "date",
        "hypothesis_id",
        "preregistered",
        "segment_used",
        "params_changed",
        "seed",
        "llm_model_version",
        "prompt_version",
        "cagr",
        "sharpe",
        "max_dd",
        "pbo",
        "mean_ic",
        "notes",
    ]
    row = {
        "run_id": f"ic-{factor}-{as_of_date.isoformat()}",
        "date": as_of_date.isoformat(),
        "hypothesis_id": IC_HYPOTHESIS_ID,
        "preregistered": _preregistered(),
        "segment_used": "",
        "params_changed": f"factor={factor};n_periods={n_periods}",
        "seed": "",
        "llm_model_version": "",
        "prompt_version": "",
        "cagr": "",
        "sharpe": "",
        "max_dd": "",
        "pbo": "",
        "mean_ic": summary["mean_ic"],
        "notes": (
            f"n_periods={summary['n_periods']};t_stat={summary['t_stat']:.3f};"
            f"monotonic={monotonic};suspected_lookahead={summary['suspected_lookahead']}"
        ),
    }
    write_header = not log_path.exists()
    with log_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m durable.factors.ic --factor {durability,valuation,momentum,overlays}`.

    Builds historical factor-value and forward-return panels from the PIT store, runs
    `rank_ic` / `ic_summary` / `ic_decay` / `quantile_returns` / `is_monotonic` /
    `factor_autocorrelation`, prints a summary, writes reports/ic_<factor>_<date>.json, and
    logs the trial to reports/experiment_log.csv.
    """
    parser = argparse.ArgumentParser(description="Factor IC analysis (docs/09 §7).")
    parser.add_argument(
        "--factor", required=True, choices=sorted(FACTOR_COLUMN), help="Factor to validate."
    )
    parser.add_argument(
        "--as-of", default=None, help="Upper-bound date YYYY-MM-DD (default: today)."
    )
    parser.add_argument("--n-periods", type=int, default=None, help="Quarterly periods to sample.")
    parser.add_argument("--db-path", default=None, help="Override the DuckDB path (for tests).")
    parser.add_argument(
        "--out-dir", default=None, help="Override the reports output directory (for tests)."
    )
    parser.add_argument(
        "--log-path", default=None, help="Override reports/experiment_log.csv (for tests)."
    )
    args = parser.parse_args(argv)

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.as_of is not None:
        try:
            end = date.fromisoformat(args.as_of)
        except ValueError:
            print(f"ERROR: --as-of must be YYYY-MM-DD, got {args.as_of!r}.", file=sys.stderr)
            return 2
    else:
        end = date.today()

    ic_cfg = config.get("factor_ic", {}) or {}
    horizons = tuple(ic_cfg.get("horizons_quarters", list(HORIZONS_QUARTERS)))
    n_quantiles = ic_cfg.get("n_quantiles", N_QUANTILES)
    method = ic_cfg.get("method", "spearman")
    suspicious_threshold = ic_cfg.get("suspicious_ic_threshold", LOOKAHEAD_IC_THRESHOLD)
    rebalance_months = tuple(config.get("portfolio", {}).get("rebalance_months", [2, 5, 8, 11]))
    n_periods = args.n_periods or (max(horizons) * 4 if horizons else 40)

    db_path = args.db_path or config.get("data", {}).get("duckdb_path", "data/durable.duckdb")
    try:
        conn = get_conn(db_path)
        init_schema(conn)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"ERROR: could not open the data store at {db_path}: {exc}", file=sys.stderr)
        return 1

    dates = _quarterly_rebalance_dates(end, n_periods, rebalance_months)
    factor_panel = _build_factor_panel(conn, args.factor, dates, config)

    if factor_panel.empty or factor_panel.dropna(how="all").empty:
        print(
            f"No {args.factor!r} factor data available in the store for any of the "
            f"{n_periods} quarterly dates on/before {end}. Run `make ingest` and "
            "`make score` first, then retry `make ic`."
        )
        return 1

    tickers = factor_panel.columns.tolist()
    forward_by_horizon = {
        h: _build_forward_returns_panel(conn, tickers, dates, h, rebalance_months)
        for h in horizons
    }
    primary_horizon = min(horizons)
    primary_returns = forward_by_horizon[primary_horizon]

    ic_series = rank_ic(factor_panel, primary_returns, method=method)
    summary = ic_summary(ic_series)
    decay = ic_decay(factor_panel, forward_by_horizon, horizons=horizons)
    qret = quantile_returns(factor_panel, primary_returns, n_quantiles=n_quantiles)
    mono, mono_msg = is_monotonic(qret)
    autocorr = factor_autocorrelation(factor_panel)

    print(f"Factor IC: {args.factor} (n_periods={summary['n_periods']}, as-of<={end})")
    print(
        f"  mean_ic={summary['mean_ic']:.4f}  std_ic={summary['std_ic']:.4f}  "
        f"ir={summary['ir']:.3f}  t_stat={summary['t_stat']:.3f}  "
        f"hit_rate={summary['hit_rate']:.2%}"
    )
    if summary["suspected_lookahead"]:
        print(
            f"  WARNING: |mean IC| exceeds the suspicious threshold ({suspicious_threshold}) "
            "-- docs/09 §7 says this almost always means look-ahead. Run the backtest-"
            "validator / leakage-audit before believing this result."
        )
    if summary["n_periods"] < config.get("factor_ic", {}).get("min_periods_for_tstat", 8):
        print(
            f"  NOTE: n_periods={summary['n_periods']} < min_periods_for_tstat -- "
            "t-stat is unreliable."
        )
    print("  IC decay by horizon (quarters):")
    print(decay.to_string())
    print(f"  Quantile monotonicity: {mono} ({mono_msg})")
    print("  Quantile returns:")
    print(qret.to_string())
    print(f"  Factor autocorrelation (lag 1): {autocorr:.4f}")

    out_dir = Path(args.out_dir) if args.out_dir else PROJECT_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"ic_{args.factor}_{end.isoformat()}.json"
    payload = {
        "factor": args.factor,
        "as_of": end.isoformat(),
        "n_periods_requested": n_periods,
        "method": method,
        "summary": summary,
        "decay": decay.reset_index().to_dict(orient="records"),
        "quantile_returns": qret.reset_index().to_dict(orient="records"),
        "is_monotonic": mono,
        "monotonicity_note": mono_msg,
        "factor_autocorrelation": autocorr,
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {out_path}")

    log_path = Path(args.log_path) if args.log_path else None
    _log_experiment(args.factor, end, n_periods, summary, mono, log_path=log_path)
    print(f"Logged trial to {log_path or 'reports/experiment_log.csv'} (H={IC_HYPOTHESIS_ID}).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
