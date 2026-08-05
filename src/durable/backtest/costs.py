"""Transaction cost model with tax impact. SPEC §7. TICKET-012.

Data source: trade records from the backtest engine.
available_at logic: N/A (post-hoc cost calculation on executed trades).
Spec section: SPEC §7, docs/04 risk.

Supports 1x/2x/3x cost multipliers for sensitivity analysis.
ST vs LT capital gains rates. Wash-sale defers loss into basis.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class TaxRates:
    """Federal tax rates for capital gains."""

    short_term: float = 0.37  # Ordinary income (top bracket)
    long_term: float = 0.20
    niit: float = 0.038  # Net Investment Income Tax
    state: float = 0.05  # State rate (varies, configurable)

    @property
    def effective_st(self) -> float:
        return self.short_term + self.niit + self.state

    @property
    def effective_lt(self) -> float:
        return self.long_term + self.niit + self.state


@dataclass
class TradeCost:
    """Cost breakdown for a single trade."""

    ticker: str
    shares: float
    price: float
    commission: float
    spread_cost: float
    market_impact: float
    total_execution_cost: float
    tax_cost: float
    total_cost: float
    is_short_term: bool
    wash_sale_deferred: float


def holding_period_days(entry_date: date, exit_date: date) -> int:
    """Days held. > 365 qualifies for long-term rates."""
    return (exit_date - entry_date).days


def is_long_term(entry_date: date, exit_date: date) -> bool:
    """Whether a position qualifies for long-term capital gains rates."""
    return holding_period_days(entry_date, exit_date) > 365


def execution_cost_bps(
    shares: float,
    price: float,
    adv: float,
    spread_bps: float = 5.0,
    impact_coeff: float = 0.1,
    multiplier: float = 1.0,
) -> float:
    """Total execution cost in basis points. SPEC §7.

    Components: half-spread + market impact (sqrt of participation).
    Multiplied by the scenario multiplier (1x/2x/3x) for sensitivity.
    """
    half_spread = spread_bps / 2.0

    # Market impact: coefficient * sqrt(participation rate)
    notional = shares * price
    participation = notional / adv if adv > 0 else 1.0
    impact = impact_coeff * (participation**0.5) * 10_000  # Convert to bps

    total = (half_spread + impact) * multiplier
    return total


def execution_cost_dollars(
    shares: float,
    price: float,
    adv: float,
    spread_bps: float = 5.0,
    impact_coeff: float = 0.1,
    multiplier: float = 1.0,
) -> float:
    """Total execution cost in dollars."""
    bps = execution_cost_bps(shares, price, adv, spread_bps, impact_coeff, multiplier)
    notional = shares * price
    return notional * bps / 10_000


def tax_cost(
    gain: float,
    entry_date: date,
    exit_date: date,
    rates: TaxRates | None = None,
) -> float:
    """Tax cost on a realized gain. Returns 0 for losses (harvested separately)."""
    if gain <= 0:
        return 0.0
    if rates is None:
        rates = TaxRates()
    if is_long_term(entry_date, exit_date):
        return gain * rates.effective_lt
    return gain * rates.effective_st


def wash_sale_adjustment(
    loss: float,
    replacement_basis: float,
    replacement_entry: date,
    original_entry: date,
) -> tuple[float, float, date]:
    """Apply wash-sale rule: deferred loss added to replacement basis.

    Returns (deferred_amount, new_basis, inherited_holding_start).
    The disallowed loss is ADDED to the replacement lot's basis,
    and the holding period is inherited from the original lot.
    """
    deferred = abs(loss)
    new_basis = replacement_basis + deferred
    inherited_date = original_entry  # Holding period inherited
    return deferred, new_basis, inherited_date


def compute_trade_cost(
    ticker: str,
    shares: float,
    price: float,
    entry_date: date,
    exit_date: date,
    cost_basis: float,
    adv: float,
    rates: TaxRates | None = None,
    multiplier: float = 1.0,
    wash_sale_loss: float = 0.0,
) -> TradeCost:
    """Compute full cost for a sell trade including execution and tax.

    Parameters
    ----------
    wash_sale_loss : if > 0, this loss was deferred into basis (not realized)
    """
    if rates is None:
        rates = TaxRates()

    notional = shares * price
    exec_cost = execution_cost_dollars(shares, price, adv, multiplier=multiplier)

    gain = notional - cost_basis
    tax = tax_cost(gain, entry_date, exit_date, rates)

    short_term = not is_long_term(entry_date, exit_date)

    return TradeCost(
        ticker=ticker,
        shares=shares,
        price=price,
        commission=0.0,  # Commission-free at Alpaca
        spread_cost=exec_cost * 0.5,  # Approximate half from spread
        market_impact=exec_cost * 0.5,  # Approximate half from impact
        total_execution_cost=exec_cost,
        tax_cost=tax,
        total_cost=exec_cost + tax,
        is_short_term=short_term,
        wash_sale_deferred=wash_sale_loss,
    )
