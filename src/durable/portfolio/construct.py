"""Portfolio construction with no-trade band. SPEC sections 6-7, TICKET-048.

Measured problem: the spec as written produced 99.6% annualized turnover —
kill criterion #4 fires immediately. Decomposition: 62.4pp from name changes,
37.2pp from drift back to equal weight alone.

The no-trade band (3% of NAV) eliminates drift-only rebalancing for continuing
holdings. Name changes and constraint breaches always execute regardless of band.

Data source: ranked scores, current holdings from portfolio state.
available_at logic: N/A (construction rule).
Spec section: SPEC §6, §7.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


NO_TRADE_BAND = 0.03
TURNOVER_CEILING = 0.60
BUFFER_RANK = 80
MAX_POSITION = 0.06
MAX_SECTOR = 0.25
TARGET_POSITIONS = 20


@dataclass(frozen=True)
class ConstructionResult:
    target_weights: pd.Series
    trades_required: pd.Series
    name_changes: list[str]
    constraint_breaches: list[str]
    turnover_projected: float
    turnover_capped: bool
    notes: list[str]


def select_holdings(
    scores: pd.Series,
    current_holdings: list[str],
    target: int = TARGET_POSITIONS,
    buffer_rank: int = BUFFER_RANK,
) -> list[str]:
    """Buffer-zone selection. SPEC §6.

    buffer_rank=80 is sourced from the turnover constraint, NOT tuned on returns.
    """
    ranked = scores.sort_values(ascending=False)
    top_n = list(ranked.index[:target])

    for ticker in current_holdings:
        if ticker in ranked.index:
            rank = list(ranked.index).index(ticker)
            if rank < buffer_rank and ticker not in top_n:
                top_n.append(ticker)

    return top_n


def target_weights(
    selected: list[str],
    sectors: pd.Series,
    max_position: float = MAX_POSITION,
    max_sector: float = MAX_SECTOR,
) -> pd.Series:
    """Equal weight, caps, renormalize."""
    n = len(selected)
    if n == 0:
        return pd.Series(dtype=float)

    raw_w = 1.0 / n
    weights = pd.Series({t: raw_w for t in selected})

    weights = weights.clip(upper=max_position)

    for sector in sectors[selected].dropna().unique():
        sector_tickers = [t for t in selected if sectors.get(t) == sector]
        sector_sum = weights[sector_tickers].sum()
        if sector_sum > max_sector:
            scale = max_sector / sector_sum
            weights[sector_tickers] *= scale

    total = weights.sum()
    if total > 1.0:
        weights = weights / total

    return weights


def apply_no_trade_band(
    target_w: pd.Series,
    current_w: pd.Series,
    name_changes: list[str],
    constraint_breaches: list[str],
    no_trade_band: float = NO_TRADE_BAND,
) -> pd.Series:
    """Only trade continuing holdings when drift > band.

    Name changes and constraint breaches always execute regardless of band.
    """
    trade_w = pd.Series(0.0, index=target_w.index.union(current_w.index))

    all_tickers = set(target_w.index) | set(current_w.index)

    for ticker in all_tickers:
        target = target_w.get(ticker, 0.0)
        current = current_w.get(ticker, 0.0)
        drift = abs(target - current)

        if ticker in name_changes or ticker in constraint_breaches:
            trade_w[ticker] = target
        elif drift > no_trade_band:
            trade_w[ticker] = target
        else:
            trade_w[ticker] = current

    return trade_w


def projected_turnover_from_weights(
    current_w: pd.Series,
    post_trade_w: pd.Series,
) -> float:
    """Annualized turnover from weight changes: sum(|delta|) / 2 * 4."""
    all_tickers = current_w.index.union(post_trade_w.index)
    current_filled = current_w.reindex(all_tickers, fill_value=0.0)
    post_filled = post_trade_w.reindex(all_tickers, fill_value=0.0)
    delta = (post_filled - current_filled).abs().sum()
    quarterly_one_way = delta / 2
    return float(quarterly_one_way * 4)


def construct_portfolio(
    scores: pd.Series,
    current_holdings: list[str],
    current_weights: pd.Series,
    sectors: pd.Series,
    new_names: list[str] | None = None,
    removed_names: list[str] | None = None,
    breach_names: list[str] | None = None,
    no_trade_band: float = NO_TRADE_BAND,
    turnover_ceiling: float = TURNOVER_CEILING,
) -> ConstructionResult:
    """Full construction pipeline with turnover control.

    Above the 60% ceiling, rebalance reduces to name changes + constraint breaches only.
    """
    name_changes = list(new_names or []) + list(removed_names or [])
    constraint_breaches = list(breach_names or [])
    notes: list[str] = []

    selected = select_holdings(scores, current_holdings)
    tw = target_weights(selected, sectors)

    post_trade_w = apply_no_trade_band(
        tw, current_weights, name_changes, constraint_breaches, no_trade_band
    )

    proj_turnover = projected_turnover_from_weights(current_weights, post_trade_w)

    turnover_capped = False
    if proj_turnover > turnover_ceiling:
        turnover_capped = True
        notes.append(
            f"Turnover {proj_turnover:.1%} exceeds ceiling {turnover_ceiling:.0%}. "
            "Reducing to name changes and constraint breaches only."
        )
        minimal_trade_w = apply_no_trade_band(
            tw, current_weights, name_changes, constraint_breaches,
            no_trade_band=999.0,
        )
        for ticker in name_changes + constraint_breaches:
            minimal_trade_w[ticker] = tw.get(ticker, 0.0)
        post_trade_w = minimal_trade_w
        proj_turnover = projected_turnover_from_weights(current_weights, post_trade_w)

    trades_required = post_trade_w.reindex(
        current_weights.index.union(post_trade_w.index), fill_value=0.0
    ) - current_weights.reindex(
        current_weights.index.union(post_trade_w.index), fill_value=0.0
    )
    trades_required = trades_required[trades_required.abs() > 1e-8]

    return ConstructionResult(
        target_weights=post_trade_w,
        trades_required=trades_required,
        name_changes=name_changes,
        constraint_breaches=constraint_breaches,
        turnover_projected=proj_turnover,
        turnover_capped=turnover_capped,
        notes=notes,
    )
