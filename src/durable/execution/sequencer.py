"""Order sequencing. TICKET-047. docs/01 "Execution sequencing".

WHY THIS MODULE EXISTS (measured, not theoretical):

An end-to-end simulation of the spec as originally written produced **negative cash in 11 of
54 quarters**. Root cause: the naive approach computes `target = NAV x weight` and executes
every trade against it, but transaction costs are paid FROM cash and are never budgeted INTO
the target. The account ends each rebalance short by roughly the cost amount.

A real broker rejects those orders or silently extends margin. Either way the backtest is
measuring a portfolio the account could not have held.

The obvious fix does not work. Cash buffers were tested at 0.5 / 1.0 / 1.5 / 2.0% and the
count of negative quarters went 4 -> 4 -> 7 -> 8. Larger buffers made it WORSE, because a
smaller invested base means a larger catch-up trade next quarter.

Sequencing eliminates the problem by construction: 11 negative quarters -> 0, at a cost of
0.06pp/yr in CAGR.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Order:
    ticker: str
    side: str            # "buy" | "sell"
    notional: Decimal
    limit_price: Decimal
    lot_ids: list[str] | None    # required on sells; never let the broker default to FIFO
    reason: str                  # "name_change" | "rebalance" | "trim" | sell rule S1-S5


@dataclass(frozen=True)
class SequencedPlan:
    sells: list[Order]
    buys: list[Order]
    scale_applied: Decimal       # 1.0 = fully funded; < 1.0 = buys scaled pro-rata
    cash_before: Decimal
    cash_after_sells: Decimal
    cash_after_buys: Decimal
    shortfall: bool
    notes: list[str]


def sequence(
    orders: list[Order],
    cash_on_hand: Decimal,
    cost_rate: Decimal = Decimal("0.0025"),
) -> SequencedPlan:
    """Split into sells-then-buys and size buys from cash actually available.

    Steps:
      1. Partition into sells and buys.
      2. Settle sells: `cash += proceeds * (1 - cost_rate)`.
      3. `affordable = cash / (1 + cost_rate)` -- reserve cost on the buy side.
      4. If desired buys exceed `affordable`, scale ALL buys pro-rata and set `shortfall`.

    Invariant, asserted at the end: `cash_after_buys >= 0`. If it can be violated, the
    function is wrong -- raise rather than emitting the plan.

    Pro-rata (not priority-ordered) scaling is deliberate: funding the top-ranked names first
    would silently concentrate the portfolio in exactly the quarters where cash is tight,
    which is a risk change disguised as an execution detail.
    """
    raise NotImplementedError("TICKET-047")


def assert_invariants(plan: SequencedPlan) -> None:
    """PROTOCOL section 4.1. Raise on any violation -- these invalidate a run.

    1. cash never negative at any step
    2. every sell references lot_ids
    3. no order has non-positive notional
    4. scale_applied in (0, 1]
    """
    raise NotImplementedError("TICKET-047")


def projected_turnover(orders: list[Order], nav: Decimal) -> Decimal:
    """Annualized turnover this rebalance implies: sum(|notional|) / nav * 4.

    Called BEFORE trading (SPEC section 7.2). Above the 60% ceiling, the caller must reduce
    the rebalance to name changes and constraint breaches only, and log the event. A kill
    criterion with no control mechanism is a post-mortem, not a control.
    """
    raise NotImplementedError("TICKET-047")
