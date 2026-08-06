"""Company scoring and ranking — "Score Companies" in the GUI. SPEC section 6. TICKET-011.

Data source: point-in-time universe (`data/universe.py::build_universe`), fundamentals
    (`facts_fundamentals`), prices (`bars_daily`, `corporate_actions`), macro (`macro_series`
    "DGS10"), and the three overlay tables (`insider_txns`, `political_txns`,
    `institutional_holdings`) — all read exclusively via `data/store.py::as_of()`.
available_at logic: every read goes through `store.as_of(conn, table, as_of, ...)`, which
    filters to `available_at <= as_of`. This module never reads a table directly and never
    reads the wall clock; `as_of` is always an explicit argument, never a default computed
    inside `score_universe()` (the CLI wrapper's `--as-of` default to today is the only place
    `date.today()` may appear, and it happens before `score_universe()` is called).
Spec section: SPEC §2 (durability), §3 (valuation), §4 (momentum), §5 (overlays),
    §6 (composite = durability + valuation + momentum + overlays, clipped).

Composite: `base = durability + valuation + momentum` (0-100); `composite = base + overlays`,
clipped to the sum of the three configured maxima (100 by default). Overlays are gated to the
top `scoring.overlay_gate_rank` names by `base` rank (CLAUDE.md rule 6), never to the final rank.

--------------------------------------------------------------------------------------------
KNOWN LIMITATIONS / DOCUMENTED ASSUMPTIONS (flag these to a human before trusting output)
--------------------------------------------------------------------------------------------
1. **Sector = SIC code, and it is currently always "UNKNOWN".** `data/universe.py::
   _get_sic_code` is a stub that always returns `None` (its own docstring says so). Until
   ingestion populates GICS/SIC metadata, every ticker falls into a single "UNKNOWN" sector
   bucket, so every "sector-percentile" computation below degrades to a universe-wide
   percentile. This is not a silent proxy: it is the documented, current behavior of a
   dependency outside this module's scope (owned by the ingestion ticket), grouping is
   already sector-aware and will start working correctly the moment `_get_sic_code` is
   implemented — no change needed here.
2. **Durability's ROIC (§2.2) and gross-margin-trend (§2.4) sector percentiles are NOT
   computed here.** `factors/durability.py::roic_points` and `growth_durability_points`
   compute their own raw median-ROIC / margin-trend internally and only accept a
   pre-computed sector comparison set (`sector_roics`, a raw ROIC `pd.Series`;
   `sector_gm_rank`, a pre-ranked 0-1 percentile) — neither raw metric is exposed as a
   standalone function, and reimplementing that math here to build the sector context
   would duplicate scoring logic the ticket instructed not to touch. Both are passed as
   `None`, which is each function's own documented absolute-threshold fallback path (see
   their docstrings: "Without sector context, use absolute thresholds"), not an invented
   proxy. A follow-up ticket should add raw-metric extraction helpers to `factors/
   durability.py` to close this gap.
3. **Valuation (§3) and momentum (§4) sector percentiles ARE computed properly**, via a
   two-pass approach: pass 1 computes each ticker's raw EV/EBIT ratio, FCF yield,
   reverse-DCF gap (calling the real `factors.valuation.reverse_dcf_gap`), and 12-1 return
   (calling the real `factors.momentum.total_return_12_1`) directly; pass 2 groups those raw
   values by `sector` and passes the (self-inclusive) peer list into `ev_ebit_score`,
   `fcf_yield_score`, `reverse_dcf_score`, and `momentum_12_1_score`.
4. **Merton distance-to-default is not wired in.** `durability_score`'s
   `distance_to_default` parameter is passed `None` (its own documented default) because
   the Merton/KMV signal (docs/10 §3) lives in a separate, not-yet-built module
   (`signals/distress.py`) outside this ticket's scope.
5. **Shareholder-yield field-name contract (§3, shareholder yield).** No canonical
   `facts_fundamentals` field names for dividends paid / buybacks / debt repayment exist
   anywhere else in this codebase (checked `tests/test_valuation.py` — it only exercises
   `valuation_score` with pre-computed floats). This module assumes three fields:
   `dividends_paid`, `share_repurchases`, `debt_repayment` (most recent fiscal year, each
   divided by market cap). **This is an assumption, not an established contract — confirm
   the exact field names with whoever builds `data/ingest.py` / the SEC fundamentals
   parser before trusting real output.** A missing field defaults to a yield of 0.0 (a
   company that pays no dividend legitimately has a dividend yield of 0 — this is a real
   zero, not a silently papered-over missing required metric).
6. **Risk-free rate.** WACC per SPEC §3.1 is `DGS10 + ERP, floored`. If `macro_series`
   has no `DGS10` row available as of the scoring date, the risk-free rate is never
   silently defaulted to 0 (that would silently understate every WACC and inflate every
   valuation score whenever real rates are meaningfully above zero). Instead every ticker's
   valuation is excluded for that date with reason `missing_risk_free_rate_dgs10`.
7. **`has_corporate_action`** is True if any as-of `corporate_actions` row for the ticker
   has `action_type` in `CORPORATE_ACTION_SELL_TRIGGERS` below (merger/acquisition/spin-off/
   delisting/bankruptcy/reorganization) — splits and dividends do not count. SPEC §8 S5
   names "merger, delist, spin-off" as examples but does not give an exhaustive enum;
   this is a documented judgment call, not a spec quote.
8. **`overlay_gate_rank`/`insider_overlay_range`/`political_overlay_range`/
   `institutional_overlay_range`/`overlay_total_clip`** from `config['scoring']`:
   `overlay_gate_rank` IS used (passed as `compute_overlays(..., top_n_gate=...)`). The
   three `*_range` keys and `overlay_total_clip` are informational only — they already
   match the hardcoded ranges/clip baked into `factors/overlays.py` (±3/±2/±2, clip ±5),
   which does not accept them as parameters (this module was told not to modify
   `factors/overlays.py`).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from durable.config import PROJECT_ROOT, ConfigError, load_config
from durable.data.store import as_of, get_conn, init_schema
from durable.data.universe import UNIVERSE_PARAMS_DEFAULT, build_universe, is_financial
from durable.factors.durability import durability_score
from durable.factors.momentum import momentum_score, total_return_12_1
from durable.factors.overlays import compute_overlays
from durable.factors.valuation import reverse_dcf_gap, valuation_score

if TYPE_CHECKING:
    import duckdb

# SPEC §8 S5: "corporate action (merger, delist, spin-off)" — not an exhaustive enum in the
# spec text. This set is a documented interpretation (see module docstring, limitation 7).
CORPORATE_ACTION_SELL_TRIGGERS = frozenset(
    {"merger", "acquisition", "spinoff", "spin-off", "delisting", "bankruptcy", "reorganization"}
)

# factors/overlays.py's three overlay functions are pure and pre-existing (do not modify);
# each expects a specific column shape that does NOT match the raw store tables verbatim
# (e.g. insider_overlay wants `transaction_code`/`amount_usd`/`is_officer_director`, but
# `insider_txns` stores `txn_code`/`price`+`shares`/`filer_title`). These helpers do that
# one-time translation so overlay scoring reads real ingested data instead of crashing on a
# column mismatch or, worse, silently reading the wrong column and always returning 0.
_OFFICER_DIRECTOR_TITLE_KEYWORDS = (
    "CEO",
    "CFO",
    "COO",
    "CTO",
    "CIO",
    "PRESIDENT",
    "CHAIRMAN",
    "CHAIR",
    "DIRECTOR",
    "EVP",
    "SVP",
    "VP",
    "VICE PRESIDENT",
    "OFFICER",
    "SECRETARY",
    "TREASURER",
    "GENERAL COUNSEL",
)


def _looks_like_officer_or_director(filer_title: Any) -> bool:
    """SEC Form 4 doesn't give us the raw officer/director/10%-owner checkbox in this
    ingestion schema (`insider_txns` only carries free-text `filer_title`) — a title-keyword
    match is a documented approximation, not the real checkbox. False (excluded from the
    overlay) for anything that doesn't match, never guessed True."""
    if filer_title is None or (isinstance(filer_title, float) and pd.isna(filer_title)):
        return False
    title = str(filer_title).upper()
    return any(kw in title for kw in _OFFICER_DIRECTOR_TITLE_KEYWORDS)


def _prepare_form4_for_overlay(form4_all: pd.DataFrame) -> pd.DataFrame:
    """Raw `insider_txns` -> the columns `factors.overlays.insider_overlay()` expects."""
    if form4_all.empty:
        return form4_all
    df = form4_all.copy()
    df["transaction_code"] = df["txn_code"]
    df["shares_transacted"] = df["shares"]
    df["insider_shares_held"] = df["shares_after"]
    df["amount_usd"] = df["shares"] * df["price"]
    df["is_officer_director"] = df["filer_title"].apply(_looks_like_officer_or_director)
    return df


def _prepare_political_for_overlay(political_all: pd.DataFrame) -> pd.DataFrame:
    """Raw `political_txns` -> the columns `factors.overlays.political_overlay()` expects.

    `has_committee_jurisdiction` cannot be honestly derived here: it requires a
    committee-to-sector/industry jurisdiction map that does not exist anywhere in this
    codebase yet (a future ticket). Defaulting to False is conservative — it can only ever
    under-credit the overlay (capping it at +1 instead of +2), never fabricate a jurisdiction
    match that isn't real.
    """
    if political_all.empty:
        return political_all
    df = political_all.copy()
    df["transaction_type"] = df["txn_type"]
    df["has_committee_jurisdiction"] = False
    return df


def _prepare_institutional_for_overlay(inst_all_unfiltered: pd.DataFrame) -> pd.DataFrame:
    """Raw `institutional_holdings` -> the columns `factors.overlays.institutional_overlay()`
    expects. MUST be called on the manager's FULL filing (every ticker they hold), not a
    frame pre-filtered to our own universe — `is_top_10` is a rank within one manager's one
    13F filing, and filtering to our universe first would make an out-of-universe top holding
    invisible, silently inflating in-universe tickers' apparent rank. The caller is
    responsible for fetching unfiltered and filtering to our tickers only AFTER this runs.
    """
    if inst_all_unfiltered.empty:
        return inst_all_unfiltered
    df = inst_all_unfiltered.copy()
    df["is_top_10"] = (
        df.groupby(["manager_name", "filed_at"])["pct_of_portfolio"].rank(
            ascending=False, method="first"
        )
        <= 10
    )
    df["action"] = df["change_type"].map(_CHANGE_TYPE_TO_ACTION).fillna("hold")
    return df


# Best-effort mapping pending a real 13F ingestion pipeline (data/institutional.py is an
# unbuilt scaffold) — documented rather than assumed. Unknown values fall back to "hold"
# (the neutral case institutional_overlay() treats as neither a buy nor a sell signal).
_CHANGE_TYPE_TO_ACTION = {
    "add": "add",
    "increase": "add",
    "increased": "add",
    "new": "add",
    "new_position": "add",
    "exit": "exit",
    "sold_out": "exit",
    "close": "exit",
    "closed": "exit",
    "hold": "hold",
    "reduce": "hold",
    "reduced": "hold",
}

# The exact columns execution/propose.py::generate_proposal() consumes. Do not add or remove.
SCORE_COLUMNS = [
    "ticker",
    "composite_score",
    "rank",
    "is_excluded",
    "implied_growth",
    "sector",
    "has_corporate_action",
]


def _latest(facts: pd.DataFrame, field: str) -> float | None:
    """Most recent value of `field` in a per-ticker facts_fundamentals slice, or None."""
    series = facts[facts["field"] == field].sort_values("period_end")
    if series.empty:
        return None
    return float(series.iloc[-1]["value"])


def _fcf_series(facts: pd.DataFrame, n: int = 5) -> list[tuple[Any, float]]:
    """Trailing up-to-`n` fiscal-year (period_end, FCF) pairs, ascending by period_end.

    FCF = operating_cash_flow - |capex|, matching the convention already used in
    `factors/durability.py::cash_and_safety_points`.
    """
    cfo_series = facts[facts["field"] == "operating_cash_flow"].sort_values("period_end").tail(n)
    capex_series = facts[facts["field"] == "capex"].sort_values("period_end")

    pairs: list[tuple[Any, float]] = []
    for _, crow in cfo_series.iterrows():
        match = capex_series[capex_series["period_end"] == crow["period_end"]]
        capex_val = float(match.iloc[0]["value"]) if not match.empty else 0.0
        pairs.append((crow["period_end"], float(crow["value"]) - abs(capex_val)))
    pairs.sort(key=lambda p: p[0])
    return pairs


def _fcf_5y_cagr(fcf_pairs: list[tuple[Any, float]]) -> float:
    """CAGR of the FCF series' first-to-last value. 0.0 if undefined (SPEC gives no formula
    for the undefined case; a non-positive start/end value makes CAGR mathematically
    undefined, so this returns 0.0 -- no growth credit -- rather than crashing or guessing
    a sign convention).
    """
    if len(fcf_pairs) < 2:
        return 0.0
    first_period, first_val = fcf_pairs[0]
    last_period, last_val = fcf_pairs[-1]
    if first_val <= 0 or last_val <= 0:
        return 0.0
    years = max((pd.Timestamp(last_period) - pd.Timestamp(first_period)).days / 365.25, 1.0)
    return (last_val / first_val) ** (1.0 / years) - 1.0


def _component_scores(
    conn: duckdb.DuckDBPyConnection,
    as_of_date: date,
    config: dict,
) -> pd.DataFrame:
    """Full per-ticker score breakdown. Internal — shared by `score_universe()` (which
    truncates to the public 7-column contract) and `factors/ic.py`'s CLI (which needs the
    individual durability/valuation/momentum/overlay components across historical dates to
    validate each factor separately, per docs/09 §7).

    Returns columns: ticker, sector, is_financial, durability_score, valuation_score
    (float or NaN if excluded), momentum_score, base_score, base_rank, overlay_score,
    composite_score, rank, is_excluded, implied_growth, has_corporate_action.
    """
    universe_params = {**UNIVERSE_PARAMS_DEFAULT, **(config.get("universe") or {})}
    universe_df, _exclusions = build_universe(conn, as_of_date, params=universe_params)

    empty_detail_cols = [
        "ticker",
        "sector",
        "is_financial",
        "durability_score",
        "valuation_score",
        "momentum_score",
        "base_score",
        "base_rank",
        "overlay_score",
        "composite_score",
        "rank",
        "is_excluded",
        "implied_growth",
        "has_corporate_action",
    ]
    if universe_df.empty:
        return pd.DataFrame(columns=empty_detail_cols)

    tickers = universe_df["ticker"].tolist()

    scoring_cfg = config.get("scoring", {}) or {}
    valuation_cfg = config.get("valuation", {}) or {}

    erp = valuation_cfg.get("equity_risk_premium", 0.05)
    wacc_floor = valuation_cfg.get("wacc_floor", 0.08)
    terminal_growth = valuation_cfg.get("terminal_growth", 0.025)
    max_ev_ebit = valuation_cfg.get("max_ev_ebit", 45)
    max_implied_growth = valuation_cfg.get("max_implied_growth", 0.25)

    macro = as_of(conn, "macro_series", as_of_date)
    dgs10 = macro[macro["series_id"] == "DGS10"].sort_values("dt") if not macro.empty else macro
    risk_free_rate = float(dgs10.iloc[-1]["value"]) if not dgs10.empty else None
    wacc = max(risk_free_rate + erp, wacc_floor) if risk_free_rate is not None else None

    facts_all = as_of(conn, "facts_fundamentals", as_of_date, tickers=tickers)
    bars_all = as_of(conn, "bars_daily", as_of_date, tickers=tickers)
    actions_all = as_of(conn, "corporate_actions", as_of_date, tickers=tickers)
    short_all = as_of(conn, "short_interest", as_of_date, tickers=tickers)
    form4_all = _prepare_form4_for_overlay(
        as_of(conn, "insider_txns", as_of_date, tickers=tickers)
    )
    political_all = _prepare_political_for_overlay(
        as_of(conn, "political_txns", as_of_date, tickers=tickers)
    )
    # Unfiltered: is_top_10 ranks within one manager's FULL 13F filing (see
    # _prepare_institutional_for_overlay's docstring) — filtering to our universe first
    # would hide out-of-universe top holdings and silently corrupt the ranking.
    inst_all_full = _prepare_institutional_for_overlay(
        as_of(conn, "institutional_holdings", as_of_date)
    )
    inst_all = (
        inst_all_full[inst_all_full["ticker"].isin(tickers)]
        if not inst_all_full.empty
        else inst_all_full
    )

    # --- Pass 1: raw, per-ticker inputs (no scoring yet) ------------------------------
    raw_rows: list[dict] = []
    for _, urow in universe_df.iterrows():
        ticker = urow["ticker"]
        facts = facts_all[facts_all["ticker"] == ticker]
        bars = bars_all[bars_all["ticker"] == ticker]
        actions = actions_all[actions_all["ticker"] == ticker]

        sic = urow.get("sic")
        sector = str(sic) if sic is not None and pd.notna(sic) else "UNKNOWN"
        fin = is_financial(sic)

        market_cap = float(urow["market_cap"])

        fcf_pairs = _fcf_series(facts)
        fcf_values = [v for _, v in fcf_pairs]
        fcf_5y_median = float(np.median(fcf_values)) if fcf_values else 0.0
        fcf_0 = fcf_values[-1] if fcf_values else 0.0
        fcf_5y_cagr = _fcf_5y_cagr(fcf_pairs)

        ebit = _latest(facts, "ebit")
        long_term_debt = _latest(facts, "long_term_debt") or 0.0
        cash = _latest(facts, "cash_and_equivalents") or 0.0
        ev = market_cap + long_term_debt - cash

        dividends_paid = max(_latest(facts, "dividends_paid") or 0.0, 0.0)
        share_repurchases = max(_latest(facts, "share_repurchases") or 0.0, 0.0)
        debt_repayment = max(_latest(facts, "debt_repayment") or 0.0, 0.0)
        dividend_yield = dividends_paid / market_cap if market_cap > 0 else 0.0
        buyback_yield = share_repurchases / market_cap if market_cap > 0 else 0.0
        debt_paydown_yield = debt_repayment / market_cap if market_cap > 0 else 0.0

        ev_ebit_ratio = ev / ebit if ebit is not None and ebit > 0 and ev > 0 else None
        fcf_yield = fcf_0 / ev if ev > 0 else None
        gap = None
        if wacc is not None and ebit is not None and ebit > 0 and fcf_0 > 0 and ev > 0:
            gap = reverse_dcf_gap(ev, fcf_0, fcf_5y_cagr, wacc, terminal_growth)

        return_12_1 = total_return_12_1(bars, as_of_date, actions)

        short_row = short_all[short_all["ticker"] == ticker]
        short_row = short_row.sort_values("publication_date") if not short_row.empty else short_row
        short_interest_pct = (
            float(short_row.iloc[-1]["pct_float"]) if not short_row.empty else None
        )

        ticker_actions = actions_all[actions_all["ticker"] == ticker]
        has_corp_action = bool(
            not ticker_actions.empty
            and ticker_actions["action_type"]
            .str.lower()
            .isin(CORPORATE_ACTION_SELL_TRIGGERS)
            .any()
        )

        raw_rows.append(
            {
                "ticker": ticker,
                "sector": sector,
                "is_financial": fin,
                "market_cap": market_cap,
                "ev": ev,
                "ebit": ebit,
                "fcf_0": fcf_0,
                "fcf_5y_median": fcf_5y_median,
                "fcf_5y_cagr": fcf_5y_cagr,
                "dividend_yield": dividend_yield,
                "buyback_yield": buyback_yield,
                "debt_paydown_yield": debt_paydown_yield,
                "ev_ebit_ratio": ev_ebit_ratio,
                "fcf_yield": fcf_yield,
                "reverse_dcf_gap": gap,
                "return_12_1": return_12_1,
                "short_interest_pct": short_interest_pct,
                "has_corporate_action": has_corp_action,
            }
        )

    raw_df = pd.DataFrame(raw_rows)

    # --- Sector peer sets (self-inclusive), pass 2 input ------------------------------
    def _peer_list(col: str) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {}
        for sector_name, group in raw_df.groupby("sector"):
            vals = group[col].dropna().tolist()
            out[sector_name] = vals
        return out

    sector_ev_ebits = _peer_list("ev_ebit_ratio")
    sector_fcf_yields = _peer_list("fcf_yield")
    sector_gaps = _peer_list("reverse_dcf_gap")
    sector_returns = _peer_list("return_12_1")

    # --- Pass 2: component scores -------------------------------------------------
    scored_rows: list[dict] = []
    for _, r in raw_df.iterrows():
        ticker = r["ticker"]
        facts = facts_all[facts_all["ticker"] == ticker]
        bars = bars_all[bars_all["ticker"] == ticker]
        actions = actions_all[actions_all["ticker"] == ticker]
        sector = r["sector"]

        dur_score, dur_bd = durability_score(
            facts,
            sector_roics=None,  # see module docstring, limitation 2
            sector_gm_rank=None,  # see module docstring, limitation 2
            distance_to_default=None,  # see module docstring, limitation 4
            short_interest_pct=r["short_interest_pct"],
            is_financial=r["is_financial"],
        )

        if wacc is None:
            val_score, val_bd = None, {"excluded": "missing_risk_free_rate_dgs10"}
        elif r["ebit"] is None:
            val_score, val_bd = None, {"excluded": "ebit_missing"}
        else:
            val_score, val_bd = valuation_score(
                ev=r["ev"],
                ebit=r["ebit"],
                fcf=r["fcf_0"],
                fcf_5y_cagr=r["fcf_5y_cagr"],
                market_cap=r["market_cap"],
                dividend_yield=r["dividend_yield"],
                buyback_yield=r["buyback_yield"],
                debt_paydown_yield=r["debt_paydown_yield"],
                risk_free_rate=risk_free_rate,
                fcf_5y_median=r["fcf_5y_median"],
                sector_ev_ebits=sector_ev_ebits.get(sector),
                sector_fcf_yields=sector_fcf_yields.get(sector),
                sector_gaps=sector_gaps.get(sector),
                erp=erp,
                wacc_floor=wacc_floor,
                terminal_growth=terminal_growth,
                max_ev_ebit=max_ev_ebit,
                max_implied_growth=max_implied_growth,
            )

        mom_score, _mom_bd = momentum_score(
            bars, as_of_date, actions, sector_returns=sector_returns.get(sector)
        )

        is_excluded = bool(dur_bd["excluded"]) or val_score is None
        base_score = dur_score + (val_score or 0.0) + mom_score
        implied_growth = val_bd.get("implied_growth") if val_bd else None

        scored_rows.append(
            {
                "ticker": ticker,
                "sector": sector,
                "is_financial": r["is_financial"],
                "durability_score": dur_score,
                "valuation_score": val_score if val_score is not None else float("nan"),
                "momentum_score": mom_score,
                "base_score": base_score,
                "is_excluded": is_excluded,
                "implied_growth": implied_growth,
                "has_corporate_action": r["has_corporate_action"],
            }
        )

    scored_df = pd.DataFrame(scored_rows)

    # base_rank: used only to gate overlays (CLAUDE.md rule 6, top-40 by base rank).
    scored_df["base_rank"] = (
        scored_df["base_score"].rank(ascending=False, method="first").astype(int)
    )

    gate = scoring_cfg.get("overlay_gate_rank", 40)
    overlay_scores = []
    for _, r in scored_df.iterrows():
        ticker = r["ticker"]
        f4 = form4_all[form4_all["ticker"] == ticker]
        pol = political_all[political_all["ticker"] == ticker]
        inst = inst_all[inst_all["ticker"] == ticker]
        overlay, _bd = compute_overlays(
            int(r["base_rank"]), f4, pol, inst, as_of_date, ticker, top_n_gate=gate
        )
        overlay_scores.append(overlay)
    scored_df["overlay_score"] = overlay_scores

    max_total = (
        scoring_cfg.get("durability_max", 50)
        + scoring_cfg.get("valuation_max", 35)
        + scoring_cfg.get("momentum_max", 15)
    )
    scored_df["composite_score"] = (scored_df["base_score"] + scored_df["overlay_score"]).clip(
        0, max_total
    )
    scored_df["rank"] = (
        scored_df["composite_score"].rank(ascending=False, method="first").astype(int)
    )

    return scored_df.sort_values("rank").reset_index(drop=True)


def score_universe(
    conn: duckdb.DuckDBPyConnection,
    as_of_date: date,
    config: dict,
) -> pd.DataFrame:
    """Score and rank the point-in-time investable universe. SPEC §6.

    Pure given (conn, as_of_date, config): never reads the wall clock, never reads
    config/config.yaml itself (the caller passes `config` in), and every data read goes
    through `store.as_of()`. See the module docstring for documented limitations.

    Returns a DataFrame with EXACTLY these columns (the contract
    `execution/propose.py::generate_proposal()` consumes):
    [ticker, composite_score, rank, is_excluded, implied_growth, sector,
     has_corporate_action]
    `rank` 1 = best. Sorted by rank ascending. Empty (but correctly-columned) DataFrame if
    the point-in-time universe is empty (no data yet, or nothing passes universe filters).
    """
    detail = _component_scores(conn, as_of_date, config)
    if detail.empty:
        return pd.DataFrame(columns=SCORE_COLUMNS)
    return detail[SCORE_COLUMNS].sort_values("rank").reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m durable.portfolio.rank --as-of DATE`. Writes and prints scores.

    `--as-of` is data, not a default computed inside scoring logic — see module docstring.
    """
    parser = argparse.ArgumentParser(description="Score and rank the durability universe.")
    parser.add_argument("--as-of", required=True, help="Rebalance date, YYYY-MM-DD.")
    parser.add_argument("--top-n", type=int, default=20, help="Rows to print (default 20).")
    parser.add_argument(
        "--db-path", default=None, help="Override the DuckDB path (mainly for tests)."
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Override the scores output directory (default data/processed/scores; "
        "mainly for tests).",
    )
    args = parser.parse_args(argv)

    try:
        as_of_date = date.fromisoformat(args.as_of)
    except ValueError:
        print(f"ERROR: --as-of must be YYYY-MM-DD, got {args.as_of!r}.", file=sys.stderr)
        return 2

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    db_path = args.db_path or config.get("data", {}).get("duckdb_path", "data/durable.duckdb")
    try:
        conn = get_conn(db_path)
        init_schema(conn)
    except Exception as exc:  # pragma: no cover - defensive; duckdb open/schema errors
        print(f"ERROR: could not open the data store at {db_path}: {exc}", file=sys.stderr)
        return 1

    scores = score_universe(conn, as_of_date, config)

    if scores.empty:
        print(
            f"No investable universe as of {as_of_date}. The data store at {db_path} has no "
            "fundamentals/price data yet (or nothing currently passes the universe filters "
            "in config/config.yaml). Run `make ingest` first, then retry "
            f"`make score AS_OF={as_of_date}`."
        )
        return 1

    out_dir = (
        Path(args.out_dir) if args.out_dir else PROJECT_ROOT / "data" / "processed" / "scores"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"scores_{as_of_date.isoformat()}.csv"
    scores.to_csv(out_path, index=False)

    n_excluded = int(scores["is_excluded"].sum())
    print(f"Scored {len(scores)} names as of {as_of_date} ({n_excluded} excluded). ")
    print(f"Wrote {out_path}")
    print()
    top = scores.sort_values("rank").head(args.top_n)
    print(top.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
