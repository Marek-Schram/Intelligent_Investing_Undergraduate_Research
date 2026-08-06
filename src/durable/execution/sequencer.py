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
from decimal import ROUND_DOWN, Decimal


@dataclass(frozen=True)
class Order:
    ticker: str
    side: str  # "buy" | "sell"
    notional: Decimal
    limit_price: Decimal
    lot_ids: list[str] | None  # required on sells; never let the broker default to FIFO
    reason: str  # "name_change" | "rebalance" | "trim" | sell rule S1-S5


@dataclass(frozen=True)
class SequencedPlan:
    sells: list[Order]
    buys: list[Order]
    scale_applied: Decimal  # 1.0 = fully funded; < 1.0 = buys scaled pro-rata
    cash_before: Decimal
    cash_after_sells: Decimal
    cash_after_buys: Decimal
    shortfall: bool
    notes: list[str]


class InvariantViolation(AssertionError):
    """Raised when sequencing invariants are violated — invalidates the run."""


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
    sells = [o for o in orders if o.side == "sell"]
    buys = [o for o in orders if o.side == "buy"]
    notes: list[str] = []

    cash = cash_on_hand
    cash_before = cash

    for sell in sells:
        proceeds = sell.notional * (Decimal("1") - cost_rate)
        cash += proceeds

    cash_after_sells = cash

    desired_buy_total = sum(b.notional for b in buys)
    affordable = cash / (Decimal("1") + cost_rate) if cash > 0 else Decimal("0")

    shortfall = False
    scale = Decimal("1")

    if desired_buy_total > affordable and desired_buy_total > 0:
        scale = affordable / desired_buy_total
        shortfall = True
        notes.append(
            f"Buys scaled pro-rata to {float(scale):.4f} "
            f"(desired={float(desired_buy_total):.2f}, affordable={float(affordable):.2f})"
        )

    scaled_buys = []
    for b in buys:
        scaled_notional = (b.notional * scale).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if scaled_notional > 0:
            scaled_buys.append(
                Order(
                    ticker=b.ticker,
                    side="buy",
                    notional=scaled_notional,
                    limit_price=b.limit_price,
                    lot_ids=b.lot_ids,
                    reason=b.reason,
                )
            )

    actual_buy_total = sum(b.notional for b in scaled_buys)
    buy_cost = actual_buy_total * cost_rate
    cash_after_buys = cash - actual_buy_total - buy_cost

    if cash_after_buys < 0:
        raise InvariantViolation(
            f"Negative cash after buys: {float(cash_after_buys):.2f}. Sequencing logic is broken."
        )

    plan = SequencedPlan(
        sells=sells,
        buys=scaled_buys,
        scale_applied=scale,
        cash_before=cash_before,
        cash_after_sells=cash_after_sells,
        cash_after_buys=cash_after_buys,
        shortfall=shortfall,
        notes=notes,
    )

    assert_invariants(plan)
    return plan


def assert_invariants(plan: SequencedPlan) -> None:
    """PROTOCOL section 4.1. Raise on any violation -- these invalidate a run.

    1. cash never negative at any step
    2. every sell references lot_ids
    3. no order has non-positive notional
    4. scale_applied in (0, 1]
    """
    if plan.cash_before < 0:
        raise InvariantViolation(f"cash_before negative: {plan.cash_before}")
    if plan.cash_after_sells < 0:
        raise InvariantViolation(f"cash_after_sells negative: {plan.cash_after_sells}")
    if plan.cash_after_buys < 0:
        raise InvariantViolation(f"cash_after_buys negative: {plan.cash_after_buys}")

    for sell in plan.sells:
        if not sell.lot_ids:
            raise InvariantViolation(
                f"Sell of {sell.ticker} has no lot_ids — never let broker default to FIFO"
            )
        if sell.notional <= 0:
            raise InvariantViolation(f"Sell of {sell.ticker} has non-positive notional")

    for buy in plan.buys:
        if buy.notional <= 0:
            raise InvariantViolation(f"Buy of {buy.ticker} has non-positive notional")

    if plan.scale_applied <= 0 or plan.scale_applied > 1:
        raise InvariantViolation(f"scale_applied out of range: {plan.scale_applied}")


def projected_turnover(orders: list[Order], nav: Decimal) -> Decimal:
    """Annualized turnover this rebalance implies: sum(|notional|) / nav * 4.

    Called BEFORE trading (SPEC section 7.2). Above the 60% ceiling, the caller must reduce
    the rebalance to name changes and constraint breaches only, and log the event. A kill
    criterion with no control mechanism is a post-mortem, not a control.
    """
    if nav <= 0:
        return Decimal("0")
    total_notional = sum(abs(o.notional) for o in orders)
    quarterly_turnover = total_notional / nav
    annualized = quarterly_turnover * 4
    return annualized
