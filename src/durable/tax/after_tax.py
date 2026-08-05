"""After-tax return calculation. TICKET-037. docs/11.

Data source: realized gains/losses from lot-level tracking (tax/lots.py).
available_at logic: uses only realized events with known settlement dates.
Spec section: SPEC §11 (Tax), BUILD_TICKETS TICKET-037.

Models after-tax returns alongside pre-tax, tax alpha vs naive-FIFO counterfactual,
loss carryforward with $3,000 annual cap, and "use now" vs "carry forward" comparison.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

# Default tax rates (configurable via function params)
DEFAULT_ST_RATE = Decimal("0.37")
DEFAULT_LT_RATE = Decimal("0.20")

# IRS annual capital loss deduction cap against ordinary income
ANNUAL_LOSS_CAP = Decimal("3000")


@dataclass(frozen=True)
class RealizedGain:
    """A single realized gain or loss event.

    Attributes:
        proceeds: Sale proceeds (Decimal).
        cost_basis: Original cost basis of the lot (Decimal).
        is_long_term: Whether the holding period exceeds 1 year.
    """

    proceeds: Decimal
    cost_basis: Decimal
    is_long_term: bool

    @property
    def gain(self) -> Decimal:
        """Net gain (positive) or loss (negative)."""
        return self.proceeds - self.cost_basis


@dataclass
class LossCarryforward:
    """Tracks capital loss carryforward across tax years.

    The IRS allows net capital losses to offset gains dollar-for-dollar, plus up to
    $3,000 per year against ordinary income. Unused losses carry forward indefinitely.

    Attributes:
        short_term: Accumulated short-term loss carryforward (stored as positive).
        long_term: Accumulated long-term loss carryforward (stored as positive).
    """

    short_term: Decimal = Decimal("0")
    long_term: Decimal = Decimal("0")

    @property
    def total(self) -> Decimal:
        """Total loss carryforward available."""
        return self.short_term + self.long_term


@dataclass(frozen=True)
class AfterTaxResult:
    """Result of after-tax return calculation for a single period.

    Attributes:
        pre_tax_return: Gross return before taxes (Decimal).
        after_tax_return: Net return after realized taxes (Decimal).
        tax_drag: Taxes paid as a fraction of beginning value (Decimal).
        st_taxes_paid: Short-term capital gains taxes paid (Decimal).
        lt_taxes_paid: Long-term capital gains taxes paid (Decimal).
    """

    pre_tax_return: Decimal
    after_tax_return: Decimal
    tax_drag: Decimal
    st_taxes_paid: Decimal
    lt_taxes_paid: Decimal


@dataclass(frozen=True)
class TaxAlphaResult:
    """Result of comparing optimal lot selection to naive FIFO.

    Attributes:
        optimal_tax: Total tax under optimal selection (Decimal).
        fifo_tax: Total tax under naive FIFO ordering (Decimal).
        tax_alpha: Savings from optimal selection (fifo_tax - optimal_tax) (Decimal).
        alpha_bps: Tax alpha in basis points relative to portfolio value (Decimal).
    """

    optimal_tax: Decimal
    fifo_tax: Decimal
    tax_alpha: Decimal
    alpha_bps: Decimal


@dataclass(frozen=True)
class CarryforwardResult:
    """Result of applying carryforward to current-year gains.

    Attributes:
        taxable_gains_after: Net taxable gains after applying carryforward (Decimal).
        ordinary_income_offset: Amount applied against ordinary income, capped (Decimal).
        remaining_carryforward: Updated LossCarryforward for next year.
    """

    taxable_gains_after: Decimal
    ordinary_income_offset: Decimal
    remaining_carryforward: LossCarryforward


@dataclass(frozen=True)
class UseNowVsCarryResult:
    """Comparison of using losses now vs carrying forward.

    Attributes:
        use_now_benefit: Tax benefit from harvesting and using losses immediately (Decimal).
        carry_forward_benefit: Projected benefit from carrying losses forward (Decimal).
        recommendation: Either "use_now" or "carry_forward".
        breakeven_rate: The future tax rate at which the two strategies are equal (Decimal).
    """

    use_now_benefit: Decimal
    carry_forward_benefit: Decimal
    recommendation: str
    breakeven_rate: Decimal


def after_tax_return(
    gains: list[RealizedGain],
    beginning_value: Decimal,
    ending_value: Decimal,
    *,
    st_rate: Decimal = DEFAULT_ST_RATE,
    lt_rate: Decimal = DEFAULT_LT_RATE,
) -> AfterTaxResult:
    """Compute after-tax return for a single period given realized gains/losses.

    Data source: lot-level realized gain/loss records.
    available_at logic: only uses events with known settlement date <= period end.
    Spec section: SPEC §11, TICKET-037.

    Args:
        gains: List of realized gain/loss events in this period.
        beginning_value: Portfolio value at start of period (Decimal).
        ending_value: Portfolio value at end of period before tax payment (Decimal).
        st_rate: Short-term capital gains tax rate (default 0.37).
        lt_rate: Long-term capital gains tax rate (default 0.20).

    Returns:
        AfterTaxResult with pre-tax and after-tax return alongside tax drag.

    Raises:
        ValueError: If beginning_value is zero or negative.
    """
    if beginning_value <= Decimal("0"):
        raise ValueError("beginning_value must be positive")

    st_taxes = Decimal("0")
    lt_taxes = Decimal("0")

    for g in gains:
        gain_amount = g.gain
        if gain_amount > Decimal("0"):
            if g.is_long_term:
                lt_taxes += gain_amount * lt_rate
            else:
                st_taxes += gain_amount * st_rate

    total_taxes = st_taxes + lt_taxes
    pre_tax_ret = (ending_value - beginning_value) / beginning_value
    after_tax_val = ending_value - total_taxes
    after_tax_ret = (after_tax_val - beginning_value) / beginning_value
    tax_drag = total_taxes / beginning_value

    return AfterTaxResult(
        pre_tax_return=pre_tax_ret,
        after_tax_return=after_tax_ret,
        tax_drag=tax_drag,
        st_taxes_paid=st_taxes,
        lt_taxes_paid=lt_taxes,
    )


def tax_alpha_vs_fifo(
    optimal_gains: list[RealizedGain],
    fifo_gains: list[RealizedGain],
    portfolio_value: Decimal,
    *,
    st_rate: Decimal = DEFAULT_ST_RATE,
    lt_rate: Decimal = DEFAULT_LT_RATE,
) -> TaxAlphaResult:
    """Compare optimal lot selection to naive FIFO for tax efficiency.

    Data source: lot-level records under two selection strategies.
    available_at logic: both strategies use identical available_at filtering.
    Spec section: SPEC §11, TICKET-037.

    Tax alpha is the savings from intelligent lot selection (e.g., highest-tax-cost
    first) compared to the default FIFO approach most brokers use.

    Args:
        optimal_gains: Realized gains under optimal lot selection.
        fifo_gains: Realized gains under naive FIFO ordering.
        portfolio_value: Total portfolio value for bps calculation (Decimal).
        st_rate: Short-term capital gains tax rate.
        lt_rate: Long-term capital gains tax rate.

    Returns:
        TaxAlphaResult with tax under each method and the alpha.

    Raises:
        ValueError: If portfolio_value is zero or negative.
    """
    if portfolio_value <= Decimal("0"):
        raise ValueError("portfolio_value must be positive")

    def _compute_tax(gains: list[RealizedGain]) -> Decimal:
        total = Decimal("0")
        for g in gains:
            gain_amount = g.gain
            if gain_amount > Decimal("0"):
                rate = lt_rate if g.is_long_term else st_rate
                total += gain_amount * rate
        return total

    optimal_tax = _compute_tax(optimal_gains)
    fifo_tax = _compute_tax(fifo_gains)
    alpha = fifo_tax - optimal_tax
    alpha_bps = (alpha / portfolio_value) * Decimal("10000")

    return TaxAlphaResult(
        optimal_tax=optimal_tax,
        fifo_tax=fifo_tax,
        tax_alpha=alpha,
        alpha_bps=alpha_bps,
    )


def apply_carryforward(
    carryforward: LossCarryforward,
    st_gains: Decimal,
    lt_gains: Decimal,
    *,
    annual_cap: Decimal = ANNUAL_LOSS_CAP,
) -> CarryforwardResult:
    """Apply loss carryforward to reduce current-year taxable gains.

    Data source: prior-year loss carryforward records.
    available_at logic: carryforward is known at tax-year close.
    Spec section: SPEC §11, TICKET-037.

    IRS ordering rules:
    1. Short-term carryforward offsets short-term gains first.
    2. Long-term carryforward offsets long-term gains first.
    3. Remaining losses of either type cross over to the other.
    4. Net losses exceeding gains offset up to $3,000 of ordinary income.
    5. Anything left carries forward to the next year.

    Args:
        carryforward: Current loss carryforward state.
        st_gains: Net short-term realized gains this year (positive = gains).
        lt_gains: Net long-term realized gains this year (positive = gains).
        annual_cap: Maximum loss deduction against ordinary income per year.

    Returns:
        CarryforwardResult with updated taxable gains and remaining carryforward.
    """
    # Step 1: ST carryforward offsets ST gains
    remaining_st_cf = carryforward.short_term
    net_st = st_gains - remaining_st_cf
    if net_st >= Decimal("0"):
        # ST carryforward fully consumed
        remaining_st_cf = Decimal("0")
    else:
        # ST gains fully offset, excess ST carryforward remains
        remaining_st_cf = -net_st
        net_st = Decimal("0")

    # Step 2: LT carryforward offsets LT gains
    remaining_lt_cf = carryforward.long_term
    net_lt = lt_gains - remaining_lt_cf
    if net_lt >= Decimal("0"):
        remaining_lt_cf = Decimal("0")
    else:
        remaining_lt_cf = -net_lt
        net_lt = Decimal("0")

    # Step 3: Cross-apply remaining carryforward
    # Remaining ST carryforward can offset LT gains
    if remaining_st_cf > Decimal("0") and net_lt > Decimal("0"):
        offset = min(remaining_st_cf, net_lt)
        net_lt -= offset
        remaining_st_cf -= offset

    # Remaining LT carryforward can offset ST gains
    if remaining_lt_cf > Decimal("0") and net_st > Decimal("0"):
        offset = min(remaining_lt_cf, net_st)
        net_st -= offset
        remaining_lt_cf -= offset

    # Step 4: Any remaining carryforward offsets ordinary income up to cap
    total_remaining_cf = remaining_st_cf + remaining_lt_cf
    ordinary_offset = min(total_remaining_cf, annual_cap)

    # Reduce carryforward by the ordinary income offset (ST first per IRS rules)
    if ordinary_offset > Decimal("0"):
        st_used_for_ordinary = min(remaining_st_cf, ordinary_offset)
        remaining_st_cf -= st_used_for_ordinary
        lt_used_for_ordinary = ordinary_offset - st_used_for_ordinary
        remaining_lt_cf -= lt_used_for_ordinary

    # Taxable gains after all offsets
    taxable_gains_after = net_st + net_lt

    return CarryforwardResult(
        taxable_gains_after=taxable_gains_after,
        ordinary_income_offset=ordinary_offset,
        remaining_carryforward=LossCarryforward(
            short_term=remaining_st_cf,
            long_term=remaining_lt_cf,
        ),
    )


def model_use_now_vs_carry(
    available_loss: Decimal,
    current_gains: Decimal,
    *,
    current_st_rate: Decimal = DEFAULT_ST_RATE,
    current_lt_rate: Decimal = DEFAULT_LT_RATE,
    expected_future_rate: Decimal = DEFAULT_ST_RATE,
    gains_are_short_term: bool = True,
    annual_cap: Decimal = ANNUAL_LOSS_CAP,
) -> UseNowVsCarryResult:
    """Compare immediate use of losses vs carrying them forward.

    Data source: current unrealized loss positions and projected gain profile.
    available_at logic: uses only currently known positions and rates.
    Spec section: SPEC §11, TICKET-037.

    "Use now" means harvesting and applying losses against current-year gains.
    "Carry forward" means deferring the loss to offset future (potentially higher-rate)
    gains or the $3,000 annual ordinary income cap.

    Args:
        available_loss: Total harvestable loss amount (positive number = loss).
        current_gains: Current-year gains that could be offset (positive).
        current_st_rate: Current short-term rate.
        current_lt_rate: Current long-term rate.
        expected_future_rate: Expected tax rate on future gains to be offset.
        gains_are_short_term: Whether current gains are short-term.
        annual_cap: Annual cap on ordinary income offset.

    Returns:
        UseNowVsCarryResult comparing the two strategies.
    """
    # Use now: offset current gains at current rate
    applicable_rate = current_st_rate if gains_are_short_term else current_lt_rate
    offset_amount = min(available_loss, current_gains)
    use_now_benefit = offset_amount * applicable_rate

    # If loss exceeds current gains, remainder only offsets $3,000/yr of ordinary income
    excess = available_loss - offset_amount
    if excess > Decimal("0"):
        # Value of $3,000 ordinary offset at top marginal rate this year
        ordinary_benefit = min(excess, annual_cap) * current_st_rate
        use_now_benefit += ordinary_benefit

    # Carry forward: offset future gains at expected future rate
    carry_benefit = available_loss * expected_future_rate

    # Breakeven: the future rate at which carry = use_now
    breakeven = use_now_benefit / available_loss if available_loss > Decimal("0") else Decimal("0")

    recommendation = "use_now" if use_now_benefit >= carry_benefit else "carry_forward"

    return UseNowVsCarryResult(
        use_now_benefit=use_now_benefit,
        carry_forward_benefit=carry_benefit,
        recommendation=recommendation,
        breakeven_rate=breakeven,
    )
