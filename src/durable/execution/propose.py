"""Rebalance proposal generation. SPEC §8, §9. TICKET-010.

Data source: composite scores, current holdings, portfolio state.
available_at logic: uses only PIT-filtered scores passed by caller.
Spec section: SPEC §6-9.

Proposals are generated here; submission is a separate entry point with a
human step between (CLAUDE.md non-negotiable #4).

PURE FUNCTIONS ONLY (up to the CLI section at the bottom): no I/O, network, wall-clock,
or config lookups.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from pathlib import Path

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
    limit_price: float | None = None  # Filled in by the CLI. Limit orders only — never market.


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

    held_tickers = (
        set(current_holdings["ticker"].tolist()) if not current_holdings.empty else set()
    )

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
            (~scores["ticker"].isin(held_tickers)) & (~scores["is_excluded"])
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


# --------------------------------------------------------------------------------
# CLI — `make propose`. Sends nothing to any broker (CLAUDE.md non-negotiable #4:
# generation and submission are separate entry points with a human step between).
# This section does I/O; generate_proposal() above stays pure.
# --------------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ProposalDataUnavailable(Exception):
    """Raised when config/database/scoring isn't in place yet. The CLI prints str(exc)
    and exits non-zero — an expected condition in a fresh checkout, not a crash."""


def _load_current_holdings(conn, as_of: date) -> pd.DataFrame:
    """Sleeve C holdings = open tax lots aggregated by ticker. There is no separate
    live position/cash table in this store (docs/01) — internal position state is
    derived from the lot ledger, same as a real portfolio's cost-basis records.
    Columns: [ticker, shares, lot_ids]. (generate_proposal() never reads a `sector`
    column off current_holdings — its own per-holding sector-weight check is a fixed
    0.0 placeholder, "Caller computes sector weight", a pre-existing gap in that
    function, not something this CLI can supply without changing its signature.)
    """
    lots = conn.execute(
        "SELECT ticker, lot_id, shares FROM tax_lots "
        "WHERE sleeve = 'C' AND closed_at IS NULL AND acquired_at <= ?",
        [as_of],
    ).fetchdf()
    if lots.empty:
        return pd.DataFrame(columns=["ticker", "shares", "lot_ids"])
    grouped = lots.groupby("ticker").agg(shares=("shares", "sum"), lot_ids=("lot_id", list))
    return grouped.reset_index()


def _load_recent_sales(conn, as_of: date) -> pd.DataFrame:
    """Closed lots in the wash-sale lookback window. Columns: [ticker, sale_date, realized_gain].
    generate_proposal()'s wash-sale check only cares about loss sales within 30 days of `as_of`
    on either side; 90 days of margin is queried so a sale just inside the window is never missed
    because of a timezone/date-boundary edge case.
    """
    rows = conn.execute(
        "SELECT ticker, closed_at AS sale_date, realized_gain FROM tax_lots "
        "WHERE closed_at IS NOT NULL AND closed_at BETWEEN ? AND ? AND realized_gain < 0",
        [as_of - timedelta(days=90), as_of],
    ).fetchdf()
    if rows.empty:
        return pd.DataFrame(columns=["ticker", "sale_date", "realized_gain"])
    return rows


def build_proposal(conn, as_of: date, config: dict) -> RebalanceProposal:
    """Assemble real inputs from the PIT store and produce a fully-priced proposal
    (shares, limit prices, explicit tax lots on every sell)."""
    from decimal import Decimal

    from durable.data import store
    from durable.execution.sequencer import Order, projected_turnover
    from durable.tax.lots import Lot, LotSelection, select_lots

    try:
        from durable.portfolio.rank import score_universe
    except ImportError as exc:
        raise ProposalDataUnavailable(
            f"Cannot propose trades yet — src/durable/portfolio/rank.py is not implemented: {exc}"
        ) from exc

    scores = score_universe(conn, as_of, config)
    if scores.empty:
        raise ProposalDataUnavailable(
            f"No scores for {as_of}. Run the Score Companies step first — there's nothing to "
            "propose against."
        )

    holdings = _load_current_holdings(conn, as_of)

    tickers = sorted(set(scores["ticker"]) | set(holdings["ticker"] if not holdings.empty else []))
    prices = store.as_of(conn, "bars_daily", as_of, tickers=tickers)
    if prices.empty:
        raise ProposalDataUnavailable(
            f"No price data as of {as_of}. Run the Update Market Data step first."
        )
    latest_price = prices.sort_values("dt").groupby("ticker")["close"].last().to_dict()

    if not holdings.empty:
        holdings["price"] = holdings["ticker"].map(latest_price)
        holdings = holdings.dropna(subset=["price"])
        nav = float((holdings["shares"] * holdings["price"]).sum())
        holdings["weight"] = (holdings["shares"] * holdings["price"]) / nav if nav > 0 else 0.0
    else:
        nav = 0.0

    portfolio_cfg = config.get("portfolio", {})
    prev_ranks = _load_prev_ranks(as_of)
    recent_sales = _load_recent_sales(conn, as_of)

    proposal = generate_proposal(
        scores=scores,
        current_holdings=holdings,
        prev_ranks=prev_ranks,
        recent_sales=recent_sales,
        as_of=as_of,
        target_n=portfolio_cfg.get("target_positions", 20),
        buffer_rank=portfolio_cfg.get("buffer_rank", 80),
        max_position=portfolio_cfg.get("max_position_weight", 0.06),
        max_sector=portfolio_cfg.get("max_sector_weight", 0.25),
    )

    cost_buffer = config.get("reserve_cost_rate", 0.0025)
    orders: list[Order] = []
    for trade in proposal.trades:
        price = latest_price.get(trade.ticker)
        if price is None or price <= 0:
            trade.notes = (trade.notes + " " if trade.notes else "") + (
                "SKIPPED: no current price available — do not execute."
            )
            continue

        if trade.action == "buy":
            trade.limit_price = round(price * (1 + cost_buffer), 2)
            if nav > 0:
                trade.shares = round((trade.target_weight * nav) / price, 6)
            else:
                # No existing holdings means no known NAV — this store has no cash-balance
                # table (documented above), so a first-ever proposal can't size share counts.
                # Report the target weight only; a human sizes the first buy manually.
                trade.shares = 0.0
                trade.notes = (
                    f"No current NAV (empty portfolio) — target weight is "
                    f"{trade.target_weight:.2%}; compute shares manually from actual cash."
                )
        elif trade.action == "sell":
            trade.limit_price = round(price * (1 - cost_buffer), 2)
            # Full liquidation: every open lot for the ticker is sold. generate_proposal()
            # already set lot_ids from current_holdings — nothing more to select.
        elif trade.action == "trim":
            trade.limit_price = round(price * (1 - cost_buffer), 2)
            trim_shares = Decimal(str(round(trade.current_weight - trade.target_weight, 8))) * (
                Decimal(str(nav)) / Decimal(str(price))
            )
            trim_shares = trim_shares.quantize(Decimal("0.000001"))
            open_lots = [
                Lot(
                    lot_id=row.lot_id,
                    ticker=trade.ticker,
                    sleeve="C",
                    account="taxable",
                    acquired_at=row.acquired_at,
                    shares=Decimal(str(row.shares)),
                    cost_basis_per_share=Decimal(str(row.cost_basis_per_share)),
                    adjusted_basis=Decimal(
                        str(row.adjusted_basis or row.shares * row.cost_basis_per_share)
                    ),
                )
                for row in conn.execute(
                    "SELECT lot_id, acquired_at, shares, cost_basis_per_share, adjusted_basis "
                    "FROM tax_lots WHERE ticker = ? AND closed_at IS NULL",
                    [trade.ticker],
                )
                .fetchdf()
                .itertuples()
            ]
            if open_lots and trim_shares > 0:
                selection = select_lots(
                    open_lots, trim_shares, Decimal(str(price)), as_of, strategy=LotSelection.HIFO
                )
                trade.lot_ids = [r.lot.lot_id for r in selection]
                trade.shares = float(trim_shares)
                trade.notes = "; ".join(
                    f"{r.lot.lot_id}: {r.shares_to_sell} sh ({r.reason})" for r in selection
                )

        if trade.action in ("buy", "sell", "trim") and trade.shares > 0:
            orders.append(
                Order(
                    ticker=trade.ticker,
                    side="sell" if trade.action in ("sell", "trim") else "buy",
                    notional=Decimal(str(round(trade.shares * (trade.limit_price or price), 2))),
                    limit_price=Decimal(str(trade.limit_price or price)),
                    lot_ids=trade.lot_ids or None,
                    reason=trade.sell_rule.value if trade.sell_rule else "rebalance",
                )
            )

    if orders and nav > 0:
        turnover = projected_turnover(orders, Decimal(str(nav)))
        proposal.projected_turnover_pct = float(turnover)
        max_turnover = portfolio_cfg.get("max_turnover_annual", 0.60)
        if float(turnover) > max_turnover:
            proposal.mistakes = (
                f"PRE-TRADE WARNING: projected annualized turnover {float(turnover):.1%} "
                f"exceeds the {max_turnover:.0%} kill-criterion ceiling (PROTOCOL §4.1 #4, "
                "docs/14 §3). Review before submitting."
            )

    return proposal


def _load_prev_ranks(as_of: date) -> pd.DataFrame | None:
    """The most recent scores CSV dated before `as_of`, written by the Score Companies step
    (data/processed/scores/scores_<date>.csv). There is no dedicated ranks-history table in
    the store, so the prior rebalance's own output file is the source of truth for S1
    (rank out of top-80 at two consecutive rebalances) — documented judgment call."""
    scores_dir = PROJECT_ROOT / "data" / "processed" / "scores"
    if not scores_dir.is_dir():
        return None
    candidates = sorted(scores_dir.glob("scores_*.csv"))
    prior = [p for p in candidates if p.stem.removeprefix("scores_") < as_of.isoformat()]
    if not prior:
        return None
    df = pd.read_csv(prior[-1])
    if "rank" not in df.columns or "ticker" not in df.columns:
        return None
    return df[["ticker", "rank"]]


def _proposal_to_dict(proposal: RebalanceProposal) -> dict:
    return {
        "as_of": proposal.as_of.isoformat(),
        "mistakes": proposal.mistakes,
        "projected_turnover_pct": proposal.projected_turnover_pct,
        "holds": proposal.holds,
        "wash_sale_blocks": proposal.wash_sale_blocks,
        "trades": [
            {
                "ticker": t.ticker,
                "action": t.action,
                "shares": t.shares,
                "limit_price": t.limit_price,
                "target_weight": t.target_weight,
                "current_weight": t.current_weight,
                "sell_rule": t.sell_rule.value if t.sell_rule else None,
                "lot_ids": t.lot_ids,
                "wash_sale_blocked": t.wash_sale_blocked,
                "notes": t.notes,
            }
            for t in proposal.trades
        ],
    }


def _write_proposal_files(proposal: RebalanceProposal) -> Path:
    out_dir = PROJECT_ROOT / "proposals"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"proposal_{proposal.as_of.isoformat()}"
    data = _proposal_to_dict(proposal)

    json_path = out_dir / f"{stem}.json"
    json_path.write_text(json.dumps(data, indent=2))

    lines = [
        f"# Rebalance proposal — {proposal.as_of.isoformat()}",
        "",
        "**This proposal sends nothing. Read every line before using Review & Submit.**",
        "",
    ]
    if proposal.mistakes:
        lines += [f"> {proposal.mistakes}", ""]
    lines += [
        "| Ticker | Action | Shares | Limit price | Reason | Lots | Notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in proposal.trades:
        reason = t.sell_rule.value if t.sell_rule else "buy — new position"
        lines.append(
            f"| {t.ticker} | {t.action} | {t.shares:.4f} | "
            f"{'' if t.limit_price is None else f'${t.limit_price:.2f}'} | {reason} | "
            f"{', '.join(t.lot_ids) or '—'} | {t.notes or '—'} |"
        )
    lines += ["", f"**Holds ({len(proposal.holds)}):** {', '.join(proposal.holds) or 'none'}"]
    if proposal.wash_sale_blocks:
        lines += [f"**Wash-sale blocked:** {', '.join(proposal.wash_sale_blocks)}"]
    lines += ["", "**Mistake / lesson (fill in after review):** _____"]
    md_path = out_dir / f"{stem}.md"
    md_path.write_text("\n".join(lines))

    return json_path


def _run_cli(as_of_str: str) -> int:
    from durable.config import ConfigError, load_config
    from durable.data import store

    as_of = date.fromisoformat(as_of_str)

    try:
        config = load_config()
    except ConfigError as exc:
        print(str(exc))
        return 1

    db_path = PROJECT_ROOT / "data" / "durable.duckdb"
    if not db_path.exists():
        print(
            f"No database at {db_path.relative_to(PROJECT_ROOT)} yet. Run the Update Market "
            "Data step (`make ingest`) first."
        )
        return 1

    conn = store.get_conn(db_path)
    try:
        proposal = build_proposal(conn, as_of, config)
    except ProposalDataUnavailable as exc:
        print(str(exc))
        return 1
    finally:
        conn.close()

    json_path = _write_proposal_files(proposal)
    print(
        f"Proposal for {as_of}: {len(proposal.trades)} trades, {len(proposal.holds)} holds. "
        f"Sent nothing — this is a proposal only."
    )
    if proposal.mistakes:
        print(proposal.mistakes)
    print(f"Wrote {json_path.relative_to(PROJECT_ROOT)} (and matching .md)")
    return 0


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Generate a rebalance proposal. Sends nothing.")
    parser.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    sys.exit(_run_cli(args.as_of))
