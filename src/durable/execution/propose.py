"""Rebalance proposal generation. SPEC §8, §9. TICKET-010.

Data source: composite scores, current holdings, portfolio state.
available_at logic: uses only PIT-filtered scores passed by caller.
Spec section: SPEC §6-9.

Proposals are generated here; submission is a separate entry point with a
human step between (CLAUDE.md non-negotiable #4).

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

import pandas as pd


class SellRule(Enum):
    """Enumerated sell rules. SPEC §8."""

    S1_RANK_OUT = "S1: rank out of top 80 at two consecutive rebalances"
    S2_EXCLUSION_FLAG = "S2: exclusion-level red flag (§2.5)"
    S3_IMPLIED_GROWTH = "S3: implied growth > 25%"
    S4_CONCENTRATION = "S4: position > 12% (trim to 6%) or sector > 30%"
    S5_CORPORATE_ACTION = "S5: corporate action (merger, delist, spin-off)"


@dataclass
class ProposedTrade:
    """A single proposed trade within a rebalance proposal."""

    ticker: str
    action: str  # 'buy' or 'sell' or 'trim'
    shares: float
    target_weight: float
    current_weight: float
    sell_rule: SellRule | None = None
    lot_ids: list[str] = field(default_factory=list)
    wash_sale_blocked: bool = False
    notes: str = ""


@dataclass
class RebalanceProposal:
    """A complete rebalance proposal. SPEC §9."""

    as_of: date
    trades: list[ProposedTrade]
    holds: list[str]
    mistakes: str = ""  # Blank "mistake" line — human fills in post-review
    projected_turnover_pct: float = 0.0
    wash_sale_blocks: list[str] = field(default_factory=list)


def _check_sell_rules(
    ticker: str,
    current_rank: int | None,
    prev_rank: int | None,
    is_excluded: bool,
    implied_growth: float | None,
    position_weight: float,
    sector_weight: float,
    has_corporate_action: bool,
    buffer_rank: int = 80,
) -> list[SellRule]:
    """Check which sell rules fire for a holding."""
    rules: list[SellRule] = []

    # S1: rank out of top 80 at TWO consecutive rebalances
    if (
        current_rank is not None
        and prev_rank is not None
        and current_rank > buffer_rank
        and prev_rank > buffer_rank
    ):
        rules.append(SellRule.S1_RANK_OUT)

    # S2: exclusion-level flag
    if is_excluded:
        rules.append(SellRule.S2_EXCLUSION_FLAG)

    # S3: implied growth > 25%
    if implied_growth is not None and implied_growth > 0.25:
        rules.append(SellRule.S3_IMPLIED_GROWTH)

    # S4: concentration
    if position_weight > 0.12 or sector_weight > 0.30:
        rules.append(SellRule.S4_CONCENTRATION)

    # S5: corporate action
    if has_corporate_action:
        rules.append(SellRule.S5_CORPORATE_ACTION)

    return rules


def _is_wash_sale_blocked(
    ticker: str,
    recent_sales: pd.DataFrame,
    as_of: date,
) -> bool:
    """Check if buying this ticker is blocked by a recent loss sale.

    61-day window: 30 days before AND after the sale, plus the sale date.
    A wash-sale blocks a loss-repurchase within this window.
    """
    if recent_sales.empty:
        return False

    ticker_sales = recent_sales[recent_sales["ticker"] == ticker]
    if ticker_sales.empty:
        return False

    # Only loss sales create wash-sale risk
    loss_sales = ticker_sales[ticker_sales["realized_gain"] < 0]
    if loss_sales.empty:
        return False

    for _, sale in loss_sales.iterrows():
        sale_date = pd.to_datetime(sale["sale_date"]).date()
        window_start = sale_date - timedelta(days=30)
        window_end = sale_date + timedelta(days=30)
        if window_start <= as_of <= window_end:
            return True

    return False


def generate_proposal(
    scores: pd.DataFrame,
    current_holdings: pd.DataFrame,
    prev_ranks: pd.DataFrame | None,
    recent_sales: pd.DataFrame,
    as_of: date,
    target_n: int = 20,
    buffer_rank: int = 80,
    max_position: float = 0.06,
    max_sector: float = 0.25,
) -> RebalanceProposal:
    """Generate a rebalance proposal. SPEC §6-9.

    Parameters
    ----------
    scores : DataFrame with [ticker, composite_score, rank, is_excluded,
             implied_growth, sector, has_corporate_action]
    current_holdings : DataFrame with [ticker, shares, weight, sector, lot_ids]
    prev_ranks : DataFrame with [ticker, rank] from the previous rebalance, or None
    recent_sales : DataFrame with [ticker, sale_date, realized_gain] for wash-sale check
    as_of : the rebalance date

    Returns a RebalanceProposal with blank "mistake" line.
    """
    trades: list[ProposedTrade] = []
    holds: list[str] = []
    wash_sale_blocks: list[str] = []

    held_tickers = set(current_holdings["ticker"].tolist()) if not current_holdings.empty else set()

    # Determine sells
    for _, holding in current_holdings.iterrows():
        ticker = holding["ticker"]
        ticker_score = scores[scores["ticker"] == ticker]

        current_rank = int(ticker_score["rank"].iloc[0]) if not ticker_score.empty else None
        prev_rank = None
        if prev_ranks is not None and not prev_ranks.empty:
            prev_row = prev_ranks[prev_ranks["ticker"] == ticker]
            if not prev_row.empty:
                prev_rank = int(prev_row["rank"].iloc[0])

        is_excluded = bool(ticker_score["is_excluded"].iloc[0]) if not ticker_score.empty else True
        implied_growth = (
            float(ticker_score["implied_growth"].iloc[0])
            if not ticker_score.empty and "implied_growth" in ticker_score.columns
            else None
        )
        has_corporate_action = (
            bool(ticker_score["has_corporate_action"].iloc[0])
            if not ticker_score.empty and "has_corporate_action" in ticker_score.columns
            else False
        )

        sell_rules = _check_sell_rules(
            ticker=ticker,
            current_rank=current_rank,
            prev_rank=prev_rank,
            is_excluded=is_excluded,
            implied_growth=implied_growth,
            position_weight=float(holding["weight"]),
            sector_weight=0.0,  # Caller computes sector weight
            has_corporate_action=has_corporate_action,
            buffer_rank=buffer_rank,
        )

        if sell_rules:
            # S4 concentration: trim to 6%, don't full sell
            if sell_rules == [SellRule.S4_CONCENTRATION] and holding["weight"] <= 0.12:
                target_w = max_position
                trades.append(
                    ProposedTrade(
                        ticker=ticker,
                        action="trim",
                        shares=0.0,  # Caller fills in actual shares
                        target_weight=target_w,
                        current_weight=float(holding["weight"]),
                        sell_rule=sell_rules[0],
                        lot_ids=holding.get("lot_ids", []),
                    )
                )
            else:
                trades.append(
                    ProposedTrade(
                        ticker=ticker,
                        action="sell",
                        shares=float(holding["shares"]),
                        target_weight=0.0,
                        current_weight=float(holding["weight"]),
                        sell_rule=sell_rules[0],
                        lot_ids=holding.get("lot_ids", []),
                    )
                )
        else:
            holds.append(ticker)

    # Determine buys: top-ranked tickers not currently held
    if not scores.empty:
        eligible = scores[
            (~scores["ticker"].isin(held_tickers))
            & (~scores["is_excluded"])
        ].sort_values("rank")

        n_to_buy = max(0, target_n - len(holds))
        for _, candidate in eligible.head(n_to_buy).iterrows():
            ticker = candidate["ticker"]

            # Wash-sale check
            if _is_wash_sale_blocked(ticker, recent_sales, as_of):
                wash_sale_blocks.append(ticker)
                continue

            trades.append(
                ProposedTrade(
                    ticker=ticker,
                    action="buy",
                    shares=0.0,  # Caller fills in from target weight
                    target_weight=max_position,
                    current_weight=0.0,
                )
            )

    return RebalanceProposal(
        as_of=as_of,
        trades=trades,
        holds=holds,
        mistakes="",  # Blank — human fills post-review
        wash_sale_blocks=wash_sale_blocks,
    )
