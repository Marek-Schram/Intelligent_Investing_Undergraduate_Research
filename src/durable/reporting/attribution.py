"""Brinson-Fachler performance attribution. TICKET-020.

Data source: portfolio and benchmark weights/returns by sector.
available_at logic: N/A (reporting artifact).
Spec section: docs/07.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BrinsonAttribution:
    """Single-period Brinson attribution result."""

    allocation: pd.Series  # By sector
    selection: pd.Series  # By sector
    interaction: pd.Series  # By sector — its own column
    total_excess: float


def brinson_single_period(
    portfolio_weights: pd.Series,
    benchmark_weights: pd.Series,
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
) -> BrinsonAttribution:
    """Brinson-Fachler single-period attribution.

    allocation_i = (w_p_i - w_b_i) * (R_b_i - R_b_total)
    selection_i  = w_b_i * (R_p_i - R_b_i)
    interaction_i = (w_p_i - w_b_i) * (R_p_i - R_b_i)

    Sum of all three = total excess return (to 1e-10).
    Interaction is its own column — never redistributed.
    """
    sectors = portfolio_weights.index.union(benchmark_weights.index)

    w_p = portfolio_weights.reindex(sectors, fill_value=0.0)
    w_b = benchmark_weights.reindex(sectors, fill_value=0.0)
    r_p = portfolio_returns.reindex(sectors, fill_value=0.0)
    r_b = benchmark_returns.reindex(sectors, fill_value=0.0)

    r_b_total = (w_b * r_b).sum()

    allocation = (w_p - w_b) * (r_b - r_b_total)
    selection = w_b * (r_p - r_b)
    interaction = (w_p - w_b) * (r_p - r_b)

    total_excess = allocation.sum() + selection.sum() + interaction.sum()

    return BrinsonAttribution(
        allocation=allocation,
        selection=selection,
        interaction=interaction,
        total_excess=total_excess,
    )


def carino_linking(
    period_attributions: list[BrinsonAttribution],
    period_portfolio_returns: list[float],
    period_benchmark_returns: list[float],
) -> BrinsonAttribution:
    """Carino smoothing for multi-period attribution linking.

    Ensures that linked attribution effects sum to cumulative excess.
    """
    n = len(period_attributions)
    if n == 0:
        empty = pd.Series(dtype=float)
        return BrinsonAttribution(
            allocation=empty, selection=empty, interaction=empty, total_excess=0.0
        )

    if n == 1:
        return period_attributions[0]

    # Cumulative returns
    cum_port = np.prod([1 + r for r in period_portfolio_returns]) - 1
    cum_bench = np.prod([1 + r for r in period_benchmark_returns]) - 1
    cum_excess = cum_port - cum_bench

    # Carino linking factors
    log_cum_port = np.log(1 + cum_port) if cum_port != 0 else 1.0
    log_cum_bench = np.log(1 + cum_bench) if cum_bench != 0 else 1.0

    # Compute Carino weights for each period
    sectors = period_attributions[0].allocation.index
    for attr in period_attributions[1:]:
        sectors = sectors.union(attr.allocation.index)

    linked_alloc = pd.Series(0.0, index=sectors)
    linked_sel = pd.Series(0.0, index=sectors)
    linked_inter = pd.Series(0.0, index=sectors)

    for t in range(n):
        r_p_t = period_portfolio_returns[t]
        r_b_t = period_benchmark_returns[t]

        # Carino factor
        log_rp = np.log(1 + r_p_t) if r_p_t != 0 else 1.0
        log_rb = np.log(1 + r_b_t) if r_b_t != 0 else 1.0

        if cum_port != 0 and r_p_t != 0:
            k_t = log_rp / log_cum_port
        else:
            k_t = 1.0 / n

        attr = period_attributions[t]
        linked_alloc = linked_alloc.add(
            attr.allocation.reindex(sectors, fill_value=0.0) * k_t, fill_value=0.0
        )
        linked_sel = linked_sel.add(
            attr.selection.reindex(sectors, fill_value=0.0) * k_t, fill_value=0.0
        )
        linked_inter = linked_inter.add(
            attr.interaction.reindex(sectors, fill_value=0.0) * k_t, fill_value=0.0
        )

    # Scale to match cumulative excess
    raw_total = linked_alloc.sum() + linked_sel.sum() + linked_inter.sum()
    if raw_total != 0 and cum_excess != 0:
        scale = cum_excess / raw_total
        linked_alloc *= scale
        linked_sel *= scale
        linked_inter *= scale

    total = linked_alloc.sum() + linked_sel.sum() + linked_inter.sum()

    return BrinsonAttribution(
        allocation=linked_alloc,
        selection=linked_sel,
        interaction=linked_inter,
        total_excess=total,
    )
