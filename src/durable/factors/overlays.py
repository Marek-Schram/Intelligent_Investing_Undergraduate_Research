"""Overlay tie-breakers, gated to top-40 base rank. SPEC §5. TICKET-009.

Data source: Form 4 (insider), STOCK Act PTRs (political), 13F (institutional).
available_at logic:
  - Insider: Form 4 filed_at + 1 trading day
  - Political: STOCK Act filed_at (45-day lag is real, not traded_at)
  - Institutional: 13F filed_at (not period_end)
Spec section: SPEC §5.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def insider_overlay(
    form4_transactions: pd.DataFrame,
    as_of: date,
) -> int:
    """Insider overlay (±3). SPEC §5.1.

    Only transaction code 'P' (open-market purchase) counts.
    'F' (tax withholding) and routine 10b5-1 are noise.

    Parameters
    ----------
    form4_transactions : DataFrame with columns:
        [filed_at, transaction_code, is_officer_director, amount_usd,
         is_10b5_1, shares_transacted, insider_shares_held]

    Returns integer in [-2, +3].
    """
    if form4_transactions.empty:
        return 0

    df = form4_transactions.copy()
    df["filed_at"] = pd.to_datetime(df["filed_at"]).dt.date

    # 6-month lookback from as_of
    lookback_start = as_of - timedelta(days=180)
    df = df[(df["filed_at"] >= lookback_start) & (df["filed_at"] <= as_of)]

    if df.empty:
        return 0

    # Only code 'P' counts
    purchases = df[
        (df["transaction_code"] == "P") & (df["is_officer_director"])
    ]

    # Check for simultaneous 10b5-1 plans
    has_10b5_1 = df["is_10b5_1"].any() if "is_10b5_1" in df.columns else False

    if not purchases.empty and not has_10b5_1:
        total_bought = purchases["amount_usd"].sum()
        n_buyers = purchases["is_officer_director"].sum()

        if n_buyers >= 2 and total_bought >= 250_000:
            return 3
        elif n_buyers >= 1:
            return 1

    # Check for net selling
    sells = df[df["transaction_code"] == "S"]
    if not sells.empty and "insider_shares_held" in df.columns:
        total_sold_shares = sells["shares_transacted"].sum()
        total_held = df["insider_shares_held"].max()
        if total_held > 0 and total_sold_shares / total_held > 0.02:
            return -2

    return 0


def political_overlay(
    stock_act_transactions: pd.DataFrame,
    as_of: date,
    ticker: str,
) -> int:
    """Political overlay (±2). SPEC §5.2.

    STOCK Act PTRs. Uses filed_at, NOT traded_at (45-day lag is real).

    Parameters
    ----------
    stock_act_transactions : DataFrame with columns:
        [filed_at, ticker, transaction_type, has_committee_jurisdiction]

    Returns integer in [-1, +2].
    """
    if stock_act_transactions.empty:
        return 0

    df = stock_act_transactions.copy()
    df["filed_at"] = pd.to_datetime(df["filed_at"]).dt.date

    # 90-day lookback
    lookback_start = as_of - timedelta(days=90)
    df = df[
        (df["filed_at"] >= lookback_start)
        & (df["filed_at"] <= as_of)
        & (df["ticker"] == ticker)
    ]

    if df.empty:
        return 0

    buys = df[df["transaction_type"] == "purchase"]
    sells = df[df["transaction_type"] == "sale"]

    n_buyers = len(buys)
    n_sellers = len(sells)

    if n_buyers >= 3:
        if buys["has_committee_jurisdiction"].any():
            return 2
        return 1

    if n_sellers >= 3:
        return -1

    return 0


def institutional_overlay(
    holdings_13f: pd.DataFrame,
    as_of: date,
    ticker: str,
) -> int:
    """Institutional conviction overlay (±2). SPEC §5.3.

    13F data. available_at = filed_at (NOT period_end).
    Managers from config, never "whoever did well recently."

    Parameters
    ----------
    holdings_13f : DataFrame with columns:
        [filed_at, ticker, manager_name, is_top_10, action]
        action: 'hold', 'add', 'exit'

    Returns integer in [-1, +2].
    """
    if holdings_13f.empty:
        return 0

    df = holdings_13f.copy()
    df["filed_at"] = pd.to_datetime(df["filed_at"]).dt.date

    # Most recent quarter's filings only
    df = df[(df["filed_at"] <= as_of) & (df["ticker"] == ticker)]
    if df.empty:
        return 0

    # Latest filing batch
    latest_filed = df["filed_at"].max()
    df = df[df["filed_at"] == latest_filed]

    holders_top10 = df[df["is_top_10"]]
    n_top10_holders = len(holders_top10)
    n_added = len(holders_top10[holders_top10["action"] == "add"])
    n_exited = len(df[df["action"] == "exit"])

    if n_top10_holders >= 3 and n_added >= 1:
        return 2
    elif n_top10_holders >= 3:
        return 1
    elif n_exited >= 3:
        return -1

    return 0


def compute_overlays(
    base_rank: int,
    form4_transactions: pd.DataFrame,
    stock_act_transactions: pd.DataFrame,
    holdings_13f: pd.DataFrame,
    as_of: date,
    ticker: str,
    top_n_gate: int = 40,
) -> tuple[int, dict]:
    """Compute all overlays for a ticker. SPEC §5.

    Overlays are tie-breakers only, gated to top-40 base rank.
    Outside top-40 gets zero. Total clipped to ±5.

    Returns (total_overlay, breakdown_dict).
    """
    breakdown = {
        "base_rank": base_rank,
        "gated": base_rank > top_n_gate,
        "insider": 0,
        "political": 0,
        "institutional": 0,
        "total_raw": 0,
        "total_clipped": 0,
    }

    if base_rank > top_n_gate:
        return 0, breakdown

    insider = insider_overlay(form4_transactions, as_of)
    political = political_overlay(stock_act_transactions, as_of, ticker)
    institutional = institutional_overlay(holdings_13f, as_of, ticker)

    total_raw = insider + political + institutional
    total_clipped = max(-5, min(5, total_raw))

    breakdown.update(
        {
            "insider": insider,
            "political": political,
            "institutional": institutional,
            "total_raw": total_raw,
            "total_clipped": total_clipped,
        }
    )

    return total_clipped, breakdown
