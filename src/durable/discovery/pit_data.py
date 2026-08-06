"""Shared point-in-time data assembly for Sleeve E discovery. Supports TICKET-024/027/028/029.

`discovery/screens.py --as-of` and `discovery/dossier.py --ticker` both need the same raw
ingredients — fundamentals, prices, 13F, insider transactions, short interest, corporate
actions — turned into the flat fields the pure `discovery/*` and `signals/*` modules expect.
This module is the ONE place that does that translation, so there is exactly one place to
audit for point-in-time correctness (everything goes through `store.as_of()`) and exactly one
place to update when the ingestion schema (`data/sec.py:FUNDAMENTAL_CONCEPTS`) grows a field.

Data source: facts_fundamentals, bars_daily, institutional_holdings, insider_txns,
short_interest, corporate_actions, filing_extractions — all via `store.as_of()`.
available_at logic: every read goes through `store.as_of(as_of_date)`; 13F rows are filtered
    by `filed_at`-derived `available_at` upstream at ingestion (docs/10 §2), never `period_end`.
Spec section: docs/08 (Sleeve E), docs/10 (signal extensions).

NOT pure — this module performs real I/O against the DuckDB store (`store.as_of`, plain SQL for
the restated-facts disqualifier check). That is intentional: it is the translation layer
between the store and the pure `discovery/*` / `signals/*` modules, which stay pure and take
plain dicts/DataFrames.

--------------------------------------------------------------------------------------------
KNOWN DATA GAPS (as of this ticket) — read before trusting a candidate list
--------------------------------------------------------------------------------------------
The current ingestion schema (`data/sec.py:FUNDAMENTAL_CONCEPTS`, TICKET-002) does not populate
several fields the Sleeve E universe rule (.claude/rules/speculation-limits.md §"Universe") and
the seven screens (docs/08 §8) need. Rather than fabricate proxies for these, this module
returns `None` (or an empty structure) and lets the downstream pure functions apply their own
documented "missing data => excluded, never imputed" behavior
(`discovery/universe.py` module docstring). Concretely, as of this ticket:

  - **exchange**: no listing-exchange table exists. Optional forward-compatible extension
    point: a future ingestion ticket MAY populate a numeric `facts_fundamentals` row with
    `field="exchange_code"`, mapped via `EXCHANGE_CODE_MAP` below. Until it does, `exchange`
    is always `None`, so `discovery.universe.screen_candidate` will exclude every real
    candidate with `missing_exchange`. This is correct, conservative behavior, not a bug —
    but it means `make discover` will return an empty watchlist against real data today.
  - **sic_code**: same extension-point pattern, `field="sic_code"` (SEC's own SIC code is a
    plain integer, e.g. 5080; trivially ingestable from EDGAR `submissions` JSON — flagged for
    the data-engineering ticket that owns `data/sec.py`).
  - **public_float / float_shares**: extension-point fields `field="public_float"` /
    `field="float_shares"`. `dei:EntityPublicFloatCurrent` is a real, standard XBRL tag not yet
    in `FUNDAMENTAL_CONCEPTS`.
  - **months_since_ipo**: no IPO-date field exists. We use a documented, non-fabricated proxy:
    months between `as_of_date` and the EARLIEST `available_at` observed for the ticker in
    `facts_fundamentals`. This is a floor, not the true IPO date — it can only ever
    UNDER-count company age (conservative: risks a false exclusion of a long-listed company
    whose ingestion history starts late, never a false inclusion of a fresh IPO).
  - **analyst_count**: no sell-side coverage table exists (`data/coverage.py` is an unbuilt
    scaffold). Always `None`. Screens treat `None` as "well covered" (conservative — see
    `discovery/screens.py` `analyst_count is None -> 99`), so analyst-count-gated screens will
    not fire on real data until coverage data is ingested.
  - **filing_text** (raw full-text for keyword/toxic-financing/promotional-8-K screens): the
    PIT store only carries structured LLM extractions with citations (`filing_extractions`),
    not raw filing bodies. Always `None`. `screen_filing_language` and the toxic-financing /
    promotional-8-K manipulation checks will read "no data" (not triggered) until a full-text
    ingestion path exists.
  - **has_8k_within_3_days / has_filing_within_3_days**: proxied by "any SEC filing event
    visible in the store (a new `facts_fundamentals` accession or a Form 4) within the
    window." This under-detects pure-press-release 8-Ks that carry no XBRL facts — flagged.
  - **social_mentions_ratio, has_section_17b_disclosure, detected_paid_promotion,
    has_sec_action, has_class_action, has_trading_suspension**: no ingestion source exists.
    Always the manipulation-screen default (no data / not triggered).
  - **conviction_managers**: real, not a proxy — sourced from `config/managers.yaml` (via
    `signals/institutional.py:ManagerConfig`) cross-referenced against `institutional_holdings`.
    `config/managers.yaml` ships with an empty manager list, so this is legitimately `[]` until
    a human curates it.

PURE-function callers (`discovery/score.py`, `discovery/manipulation.py`, `discovery/neglect.py`,
`discovery/screens.py` screen functions, `signals/distress.py`, `signals/institutional.py`) are
never modified by this module — it only assembles their inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import yaml

if TYPE_CHECKING:
    import duckdb

from durable.data.store import as_of as store_as_of
from durable.discovery.score import QualityClaim
from durable.factors.durability import durability_score as compute_durability_score
from durable.signals.distress import DistanceToDefaultResult, compute_distance_to_default
from durable.signals.institutional import ChangeType, ManagerConfig

# Optional forward-compatible extension point — see module docstring. Not populated by
# data/sec.py (TICKET-002) as of this ticket.
EXCHANGE_CODE_MAP: dict[float, str] = {1.0: "NYSE", 2.0: "NASDAQ", 3.0: "NYSEAMERICAN"}

TAX_RATE = 0.21  # matches factors/durability.py:roic_points
TRADING_DAYS_PER_YEAR = 252


@dataclass
class CandidateData:
    """Everything downstream Sleeve E code needs for one ticker as of one date.

    `universe_kwargs` feeds `discovery.universe.screen_candidate` directly (as `**kwargs`,
    minus `ticker`). `screen_fields` is the flat dict `discovery.screens.run_all_screens`
    expects. `score_kwargs`, `manipulation_kwargs`, and `neglect_kwargs` feed the matching
    `compute_discovery_score` / `run_manipulation_screen` / `compute_neglect_score` calls.
    `data_gaps` lists, in plain English, which fields for THIS ticker could not be verified
    from the current store — always non-empty against real data today (see module docstring).
    """

    ticker: str
    universe_kwargs: dict[str, Any]
    screen_fields: dict[str, Any]
    score_kwargs: dict[str, Any]
    manipulation_kwargs: dict[str, Any]
    neglect_kwargs: dict[str, Any]
    dd_result: DistanceToDefaultResult | None
    ev: float | None = None
    ebit: float | None = None
    fcf_0: float | None = None
    data_gaps: list[str] = field(default_factory=list)


def load_tracked_managers(managers_path: str | Path) -> list[ManagerConfig]:
    """Load `config/managers.yaml` into `ManagerConfig` objects. Empty file => empty list."""
    path = Path(managers_path)
    if not path.is_file():
        return []
    with path.open() as f:
        raw = yaml.safe_load(f) or {}
    managers = raw.get("managers") or []
    return [
        ManagerConfig(name=m["name"], cik=str(m["cik"]), style=m.get("style", ""))
        for m in managers
    ]


def list_tickers_with_fundamentals(conn: duckdb.DuckDBPyConnection, as_of_date: date) -> list[str]:
    """Every ticker with at least one fundamentals row available as of `as_of_date`."""
    fundamentals = store_as_of(conn, "facts_fundamentals", as_of_date)
    if fundamentals.empty:
        return []
    return sorted(fundamentals["ticker"].unique().tolist())


# --------------------------------------------------------------------------------------------
# Fundamentals helpers
# --------------------------------------------------------------------------------------------


def _latest_value(facts: pd.DataFrame, field_name: str) -> float | None:
    s = facts[facts["field"] == field_name].sort_values("period_end")
    if s.empty:
        return None
    return float(s.iloc[-1]["value"])


def _annual_values(facts: pd.DataFrame, field_name: str, n_years: int = 5) -> pd.DataFrame:
    """Collapse a possibly-quarterly series to one row per calendar year (latest report in
    that year kept — typically the fiscal-year-end/10-K figure). Ascending by period_end,
    at most `n_years` most recent years. Documented heuristic — see module docstring."""
    s = facts[facts["field"] == field_name].copy()
    if s.empty:
        # Same shape callers get on the non-empty path (this ticker just has no data for
        # this field) -- e.g. _fcf_annual()'s merge on "_year" would otherwise KeyError
        # whenever one of operating_cash_flow/capex is missing but not the other.
        return pd.DataFrame(columns=[*s.columns.tolist(), "_year"])
    s["period_end"] = pd.to_datetime(s["period_end"])
    s["_year"] = s["period_end"].dt.year
    s = s.sort_values("period_end").drop_duplicates("_year", keep="last")
    return s.tail(n_years).reset_index(drop=True)


def _cagr(annual: pd.DataFrame) -> float | None:
    """CAGR from the first to last row of an ascending annual series. None if not computable."""
    if len(annual) < 2:
        return None
    first, last = annual.iloc[0], annual.iloc[-1]
    years = (last["period_end"] - first["period_end"]).days / 365.25
    if years <= 0 or first["value"] <= 0 or last["value"] <= 0:
        return None
    return (last["value"] / first["value"]) ** (1 / years) - 1


def _fcf_annual(facts: pd.DataFrame, n_years: int = 6) -> pd.DataFrame:
    """FCF = operating_cash_flow - |capex|, one row per calendar year."""
    cfo = _annual_values(facts, "operating_cash_flow", n_years)
    capex = _annual_values(facts, "capex", n_years)
    if cfo.empty:
        return cfo
    merged = cfo[["period_end", "_year", "value"]].merge(
        capex[["_year", "value"]], on="_year", how="left", suffixes=("_cfo", "_capex")
    )
    merged["value_capex"] = merged["value_capex"].fillna(0.0)
    merged["value"] = merged["value_cfo"] - merged["value_capex"].abs()
    return merged[["period_end", "value"]]


def _median_roic(facts: pd.DataFrame, n_years: int = 5) -> float | None:
    """Median ROIC over up to `n_years` years. Same formula as factors/durability.py's
    `roic_points`, but returns the raw fraction (e.g. 0.15) instead of a 0-14 score."""
    ebit_series = _annual_values(facts, "ebit", n_years)
    if ebit_series.empty:
        return None
    roics = []
    for _, row in ebit_series.iterrows():
        equity = _value_near(facts, "stockholders_equity", row["period_end"])
        debt = _value_near(facts, "long_term_debt", row["period_end"])
        cash = _value_near(facts, "cash_and_equivalents", row["period_end"]) or 0.0
        if equity is None or debt is None:
            continue
        invested_capital = debt + equity - cash
        if invested_capital <= 0:
            continue
        nopat = row["value"] * (1 - TAX_RATE)
        roics.append(nopat / invested_capital)
    if not roics:
        return None
    return float(np.median(roics))


def _value_near(facts: pd.DataFrame, field_name: str, target: pd.Timestamp) -> float | None:
    s = facts[facts["field"] == field_name].copy()
    if s.empty:
        return None
    s["period_end"] = pd.to_datetime(s["period_end"])
    idx = (s["period_end"] - target).abs().idxmin()
    return float(s.loc[idx, "value"])


def _profitable_years(facts: pd.DataFrame) -> int | None:
    """Positive `ebit` (operating-income proxy) in how many of the last 4 fiscal years."""
    annual = _annual_values(facts, "ebit", 4)
    if annual.empty:
        return None
    return int((annual["value"] > 0).sum())


def _quarters_filed(facts: pd.DataFrame) -> int:
    return int(facts[facts["field"] == "revenue"]["period_end"].nunique())


def _months_since_ipo_proxy(facts: pd.DataFrame, as_of_date: date) -> int | None:
    """Months since the EARLIEST `available_at` seen for this ticker. A floor, not the true
    IPO date — see module docstring. None if no data."""
    if facts.empty or "available_at" not in facts.columns:
        return None
    earliest = pd.to_datetime(facts["available_at"]).min()
    months = (as_of_date.year - earliest.year) * 12 + (as_of_date.month - earliest.month)
    return max(months, 0)


def _extension_value(facts: pd.DataFrame, field_name: str) -> float | None:
    """Read an optional forward-compatible extension field (see module docstring)."""
    return _latest_value(facts, field_name)


# --------------------------------------------------------------------------------------------
# Price / volume helpers
# --------------------------------------------------------------------------------------------


def _price_adv_market_cap(
    bars: pd.DataFrame, shares_outstanding: float | None
) -> tuple[float | None, float | None, float | None]:
    """(price, adv_60d, market_cap) from the trailing 60 daily bars. Mirrors
    data/universe.py's build_universe pattern."""
    if bars.empty:
        return None, None, None
    recent = bars.sort_values("dt").tail(60)
    price = float(recent.iloc[-1]["close"])
    adv_60d = float((recent["close"] * recent["volume"]).median())
    market_cap = price * shares_outstanding if shares_outstanding else None
    return price, adv_60d, market_cap


def _realized_annualized_vol(bars: pd.DataFrame, min_obs: int = 20) -> float | None:
    """Annualized stdev of daily log returns over the available (already as_of-filtered)
    trailing bars. None below `min_obs` observations — no fabricated volatility."""
    if len(bars) < min_obs + 1:
        return None
    closes = bars.sort_values("dt")["close"].to_numpy(dtype=float)
    log_returns = np.diff(np.log(closes))
    if len(log_returns) < min_obs:
        return None
    return float(np.std(log_returns, ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))


def _price_volume_spike(bars: pd.DataFrame) -> tuple[float | None, float | None]:
    """(price_change_pct, volume_ratio) for the most recent bar vs the prior 60 sessions."""
    if len(bars) < 2:
        return None, None
    ordered = bars.sort_values("dt")
    last, prev = ordered.iloc[-1], ordered.iloc[-2]
    if prev["close"] in (0, None):
        price_change_pct = None
    else:
        price_change_pct = float((last["close"] - prev["close"]) / prev["close"])
    baseline = ordered.iloc[:-1].tail(60)["volume"]
    if baseline.empty or baseline.median() in (0, None):
        volume_ratio = None
    else:
        volume_ratio = float(last["volume"] / baseline.median())
    return price_change_pct, volume_ratio


# --------------------------------------------------------------------------------------------
# 13F / insider / short interest / corporate actions
# --------------------------------------------------------------------------------------------


def _institutional_pct(inst: pd.DataFrame, shares_outstanding: float | None) -> float | None:
    """Sum of the latest-per-manager reported shares / shares_outstanding."""
    if inst.empty or not shares_outstanding:
        return None
    latest_per_manager = inst.sort_values("filed_at").drop_duplicates("manager_cik", keep="last")
    total_shares = latest_per_manager["shares"].sum()
    if total_shares <= 0:
        return None
    return float(total_shares / shares_outstanding)


def _conviction_managers(inst: pd.DataFrame, tracked_managers: list[ManagerConfig]) -> list[str]:
    """Tracked managers whose latest reported position is new or increased. Real data,
    driven entirely by config/managers.yaml — see module docstring."""
    if inst.empty or not tracked_managers:
        return []
    tracked_ciks = {m.cik for m in tracked_managers}
    cik_to_name = {m.cik: m.name for m in tracked_managers}
    tracked = inst[inst["manager_cik"].astype(str).isin(tracked_ciks)]
    if tracked.empty:
        return []
    latest = tracked.sort_values("filed_at").drop_duplicates("manager_cik", keep="last")
    conviction_change_types = {ChangeType.NEW_POSITION.value, ChangeType.INCREASED.value}
    hits = latest[latest["change_type"].isin(conviction_change_types)]
    return [cik_to_name.get(str(c), str(c)) for c in hits["manager_cik"].astype(str)]


def _form4_purchases_90d(insider: pd.DataFrame, as_of_date: date) -> list[dict]:
    """Form 4 code 'P' (open-market purchase) transactions in the trailing 90 days."""
    if insider.empty:
        return []
    window_start = as_of_date - timedelta(days=90)
    df = insider.copy()
    df["txn_date"] = pd.to_datetime(df["txn_date"]).dt.date
    recent = df[(df["txn_date"] >= window_start) & (df["txn_date"] <= as_of_date)]
    purchases = recent[recent["txn_code"] == "P"]
    return [
        {"insider_name": row["filer_name"], "code": row["txn_code"]}
        for _, row in purchases.iterrows()
    ]


def _months_since_spinoff(actions: pd.DataFrame, as_of_date: date) -> float | None:
    if actions.empty:
        return None
    spinoffs = actions[
        actions["action_type"].str.lower().isin(["spinoff", "spin-off", "spin_off"])
    ]
    if spinoffs.empty:
        return None
    latest = spinoffs.sort_values("ex_date").iloc[-1]
    ex_date = latest["ex_date"]
    if isinstance(ex_date, pd.Timestamp):
        ex_date = ex_date.date()
    return (as_of_date - ex_date).days / 30.44


def _si_pct_float(short_interest: pd.DataFrame) -> float | None:
    if short_interest.empty:
        return None
    latest = short_interest.sort_values("publication_date").iloc[-1]
    return None if pd.isna(latest["pct_float"]) else float(latest["pct_float"])


def _has_recent_filing_event(
    facts: pd.DataFrame, insider: pd.DataFrame, as_of_date: date, window_days: int = 3
) -> bool:
    """Proxy for 'has an 8-K/filing within N days' — see module docstring KNOWN DATA GAPS."""
    window_start = as_of_date - timedelta(days=window_days)
    for df, col in ((facts, "filed_at"), (insider, "filed_at")):
        if df.empty or col not in df.columns:
            continue
        dates = pd.to_datetime(df[col]).dt.date
        if ((dates >= window_start) & (dates <= as_of_date)).any():
            return True
    return False


def _quality_claims(facts: pd.DataFrame, extractions: pd.DataFrame) -> list[QualityClaim]:
    """Filing-cited quality claims per docs/08 §4: recurring revenue (3), top customer < 20%
    (2), insider ownership 5-40% (3), sustained R&D/capex (2). Sourced from
    `filing_extractions` (LLM-extracted, cited by accession — TICKET-031) where present;
    otherwise the claim is simply not made (0 points, honest absence, not a fabricated 0)."""
    claims: list[QualityClaim] = []
    if extractions.empty:
        return claims

    def _latest_extraction(field_name: str) -> pd.Series | None:
        rows = extractions[extractions["field"] == field_name].sort_values("available_at")
        return None if rows.empty else rows.iloc[-1]

    recurring = _latest_extraction("recurring_revenue_pct")
    if (
        recurring is not None
        and recurring["citation"]
        and recurring["value"] is not None
        and float(recurring["value"]) >= 0.5
    ):
        claims.append(QualityClaim("recurring revenue >= 50%", cited=True, points=3))

    top_customer = _latest_extraction("customer_concentration")
    if (
        top_customer is not None
        and top_customer["citation"]
        and top_customer["value"] is not None
        and float(top_customer["value"]) < 0.20
    ):
        claims.append(QualityClaim("top customer < 20% of revenue", cited=True, points=2))

    insider_own = _latest_extraction("insider_ownership_pct")
    if insider_own is not None and insider_own["citation"] and insider_own["value"] is not None:
        v = float(insider_own["value"])
        if 0.05 <= v <= 0.40:
            claims.append(QualityClaim("insider ownership 5-40%", cited=True, points=3))

    rd = _latest_extraction("rd_to_revenue")
    if rd is not None and rd["citation"] and rd["value"] is not None and float(rd["value"]) > 0:
        claims.append(QualityClaim("sustained R&D/capex", cited=True, points=2))

    return claims


def _auto_disqualifier_flags(
    conn: duckdb.DuckDBPyConnection,
    ticker: str,
    as_of_date: date,
    facts: pd.DataFrame,
    actions: pd.DataFrame,
) -> dict[str, bool]:
    """The 11 auto-disqualifiers (speculation-limits.md §"Automatic permanent exclusions").
    Only the ones derivable from the current schema are computed; the rest default to False
    (not triggered) — consistent with `discovery.universe.check_auto_disqualifiers`'s own
    `flags.get(flag, False)` semantics, and documented in the module docstring."""
    window_start = as_of_date - timedelta(days=365 * 2)

    flags = {
        "reverse_split_within_24m": False,
        "multiple_name_changes_5y": False,
        "reverse_merger_within_5y": False,
        "sec_trading_suspension": False,
        "repeated_late_filings": False,
        "auditor_resignation_24m": False,
        "restatement_within_24m": False,
        "share_dilution_25pct_1y": False,
        "detected_paid_promotion": False,
        "otc_history_within_24m": False,
        "unsolicited_source": False,  # always False: this candidate came from a screen (rule 17)
    }

    if not actions.empty:
        recent = actions[pd.to_datetime(actions["ex_date"]).dt.date >= window_start]
        splits = recent[(recent["action_type"].str.lower() == "split") & (recent["factor"] < 1.0)]
        flags["reverse_split_within_24m"] = not splits.empty

    # Restated facts: store.as_of() always filters restated=FALSE (no-lookahead.md rule 3),
    # so a plain SQL query is used here deliberately to see what WAS restated.
    as_of_dt = datetime(as_of_date.year, as_of_date.month, as_of_date.day, 23, 59, 59)
    window_start_dt = datetime(window_start.year, window_start.month, window_start.day)
    restated_count = conn.execute(
        "SELECT COUNT(*) FROM facts_fundamentals "
        "WHERE ticker = ? AND restated = TRUE AND filed_at <= ? AND filed_at >= ?",
        [ticker, as_of_dt, window_start_dt],
    ).fetchone()[0]
    flags["restatement_within_24m"] = restated_count > 0

    shares = facts[facts["field"] == "shares_outstanding"].copy()
    if len(shares) >= 2:
        shares["period_end"] = pd.to_datetime(shares["period_end"])
        shares = shares.sort_values("period_end")
        one_year_ago = pd.Timestamp(as_of_date) - pd.Timedelta(days=365)
        prior = shares[shares["period_end"] <= one_year_ago]
        if not prior.empty:
            prior_val = prior.iloc[-1]["value"]
            latest_val = shares.iloc[-1]["value"]
            if prior_val > 0 and (latest_val / prior_val - 1) > 0.25:
                flags["share_dilution_25pct_1y"] = True

    return flags


# --------------------------------------------------------------------------------------------
# Top-level builder
# --------------------------------------------------------------------------------------------


def build_candidate(
    conn: duckdb.DuckDBPyConnection,
    as_of_date: date,
    ticker: str,
    tracked_managers: list[ManagerConfig] | None = None,
) -> CandidateData:
    """Assemble everything Sleeve E discovery code needs for one ticker, as of one date.

    All reads go through `store.as_of(as_of_date)` (or, for the restated-facts disqualifier
    check, a deliberate raw query — see `_auto_disqualifier_flags`). Missing data becomes
    `None` / an empty structure, never an imputed value — downstream pure functions apply
    their own documented "missing => excluded" behavior.
    """
    tracked_managers = tracked_managers or []
    data_gaps: list[str] = []

    facts = store_as_of(conn, "facts_fundamentals", as_of_date, tickers=ticker)
    bars = store_as_of(conn, "bars_daily", as_of_date, tickers=ticker)
    inst = store_as_of(conn, "institutional_holdings", as_of_date, tickers=ticker)
    insider = store_as_of(conn, "insider_txns", as_of_date, tickers=ticker)
    short_interest = store_as_of(conn, "short_interest", as_of_date, tickers=ticker)
    actions = store_as_of(conn, "corporate_actions", as_of_date, tickers=ticker)
    extractions = store_as_of(conn, "filing_extractions", as_of_date, tickers=ticker)

    shares_outstanding = _latest_value(facts, "shares_outstanding")
    price, adv_60d, market_cap = _price_adv_market_cap(bars, shares_outstanding)

    exchange_code = _extension_value(facts, "exchange_code")
    exchange = EXCHANGE_CODE_MAP.get(exchange_code) if exchange_code is not None else None
    if exchange is None:
        data_gaps.append("exchange: not in the ingestion schema yet (see module docstring)")

    sic_raw = _extension_value(facts, "sic_code")
    sic_code = f"{int(sic_raw):04d}" if sic_raw is not None else None
    if sic_code is None:
        data_gaps.append("sic_code: not in the ingestion schema yet")

    float_value = _extension_value(facts, "public_float")
    float_shares = _extension_value(facts, "float_shares")
    if float_value is None or float_shares is None:
        data_gaps.append("public float: not in the ingestion schema yet")

    months_since_ipo = _months_since_ipo_proxy(facts, as_of_date)
    quarters_filed = _quarters_filed(facts)
    profitable_years = _profitable_years(facts)
    si_pct_float = _si_pct_float(short_interest)

    long_term_debt = _latest_value(facts, "long_term_debt")
    cash = _latest_value(facts, "cash_and_equivalents") or 0.0
    ebit = _latest_value(facts, "ebit")
    ev = None
    if market_cap is not None and long_term_debt is not None:
        ev = market_cap + long_term_debt - cash
    ev_ebit = ev / ebit if (ev is not None and ebit is not None and ebit > 0) else None

    durability_raw, durability_breakdown = (None, {})
    if not facts.empty:
        durability_raw, durability_breakdown = compute_durability_score(facts)
    else:
        data_gaps.append("durability: no fundamentals available")

    equity_vol = _realized_annualized_vol(bars)
    sic_int = int(sic_raw) if sic_raw is not None else None
    dd_result: DistanceToDefaultResult | None = None
    if long_term_debt is not None and market_cap is not None:
        dd_result = compute_distance_to_default(
            ticker=ticker,
            equity_value=market_cap,
            equity_volatility=equity_vol,
            debt=long_term_debt,
            sic_code=sic_int,
        )
    else:
        data_gaps.append("distance_to_default: missing market cap or long-term debt")

    price_change_pct, volume_ratio = _price_volume_spike(bars)
    has_filing_within_3_days = _has_recent_filing_event(facts, insider, as_of_date)

    institutional_pct = _institutional_pct(inst, shares_outstanding)
    conviction_managers = _conviction_managers(inst, tracked_managers)
    form4_transactions = _form4_purchases_90d(insider, as_of_date)
    months_since_spinoff = _months_since_spinoff(actions, as_of_date)

    revenue_cagr_5y = _cagr(_annual_values(facts, "revenue", 6))
    fcf_annual = _fcf_annual(facts, 6)
    fcf_cagr_5y = _cagr(fcf_annual) if not fcf_annual.empty else None
    fcf_0 = float(fcf_annual.iloc[-1]["value"]) if not fcf_annual.empty else None
    shares_annual = _annual_values(facts, "shares_outstanding", 6)
    shares_growth_5y = _cagr(shares_annual)
    roic = _median_roic(facts)

    auto_disqualifier_flags = _auto_disqualifier_flags(conn, ticker, as_of_date, facts, actions)

    universe_kwargs = {
        "exchange": exchange,
        "price": price,
        "market_cap": market_cap,
        "adv_60d": adv_60d,
        "float_value": float_value,
        "float_shares": float_shares,
        "quarters_filed": quarters_filed,
        "months_since_ipo": months_since_ipo,
        "profitable_years": profitable_years,
        "si_pct_float": si_pct_float,
        "distance_to_default": dd_result.dd if (dd_result and dd_result.is_valid) else None,
        "auto_disqualifier_flags": auto_disqualifier_flags,
    }

    screen_fields = {
        "ticker": ticker,
        "profitable": bool(profitable_years is not None and profitable_years >= 3),
        "market_cap": market_cap,
        "analyst_count": None,  # not ingested — see module docstring
        "institutional_pct": institutional_pct,
        "sic_code": sic_code,
        "durability_score": durability_raw,
        "form4_transactions": form4_transactions,
        "months_since_spinoff": months_since_spinoff,
        "filing_text": None,  # not ingested — see module docstring
        "revenue_cagr_5y": revenue_cagr_5y,
        "fcf_cagr_5y": fcf_cagr_5y,
        "shares_growth_5y": shares_growth_5y,
        "roic": roic,
        "conviction_managers": conviction_managers,
    }

    score_kwargs = {
        "durability_raw": durability_raw,
        "ev_ebit": ev_ebit,
        "quality_claims": _quality_claims(facts, extractions),
        "insider_purchases_90d": len({t["insider_name"] for t in form4_transactions}),
        "institutional_conviction_count": len(conviction_managers),
    }

    manipulation_kwargs = {
        "price_change_pct": price_change_pct,
        "volume_ratio": volume_ratio,
        "has_filing_within_3_days": has_filing_within_3_days,
        "has_8k_within_3_days": has_filing_within_3_days,
        "distance_to_default": dd_result.dd if (dd_result and dd_result.is_valid) else None,
        "si_pct_float": si_pct_float,
        "from_unsolicited": False,  # this pipeline IS the systematic screen (rule 17)
    }

    neglect_kwargs = {
        "analyst_count": None,  # not ingested — see module docstring
        "institutional_ownership_pct": institutional_pct,
        "media_mentions_decile": None,  # not ingested
        "has_sell_side_initiation_24m": None,  # not ingested
    }

    return CandidateData(
        ticker=ticker,
        universe_kwargs=universe_kwargs,
        screen_fields=screen_fields,
        score_kwargs=score_kwargs,
        manipulation_kwargs=manipulation_kwargs,
        neglect_kwargs=neglect_kwargs,
        dd_result=dd_result,
        ev=ev,
        ebit=ebit,
        fcf_0=fcf_0,
        data_gaps=data_gaps,
    )


def peer_ev_ebit_group(
    conn: duckdb.DuckDBPyConnection,
    as_of_date: date,
    tickers: list[str],
    sic_code: str | None,
    exclude_ticker: str,
    tracked_managers: list[ManagerConfig] | None = None,
) -> tuple[list[float], bool]:
    """EV/EBIT for Sleeve-E-range peers sharing `sic_code`'s 2-digit prefix, per docs/08 §4.

    Returns (peer_ev_ebits, used_fallback). Fallback (all Sleeve-E-cap-range tickers,
    regardless of SIC) is used when the same-SIC-2-digit group has < 5 members — the
    threshold and fallback rule live in `discovery.score` (MIN_PEER_GROUP_SIZE); this
    function just assembles the two candidate pools for the caller to choose between.
    """
    from durable.discovery.score import MIN_PEER_GROUP_SIZE

    prefix = sic_code[:2] if sic_code else None
    same_sic: list[float] = []
    broader: list[float] = []

    for t in tickers:
        if t == exclude_ticker:
            continue
        cand = build_candidate(conn, as_of_date, t, tracked_managers)
        mcap = cand.universe_kwargs["market_cap"]
        if mcap is None or not (300e6 <= mcap <= 3e9):
            continue
        ev_ebit = cand.score_kwargs["ev_ebit"]
        if ev_ebit is None:
            continue
        broader.append(ev_ebit)
        cand_sic = cand.screen_fields["sic_code"]
        if prefix is not None and cand_sic is not None and cand_sic[:2] == prefix:
            same_sic.append(ev_ebit)

    if len(same_sic) >= MIN_PEER_GROUP_SIZE:
        return same_sic, False
    return broader, True
