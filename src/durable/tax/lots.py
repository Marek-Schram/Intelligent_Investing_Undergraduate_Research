"""Tax lot tracking and after-tax-optimal lot selection. TICKET-035.

Data source: internal lot ledger (purchases tracked in-system).
available_at logic: lots are available immediately upon purchase confirmation.
Spec section: docs/11 section 2-3.

Every purchase creates a tax lot. Every sale specifies lots explicitly — never let
the broker default to FIFO. The optimizer maximizes after-tax proceeds, not minimum
realized gain. A short-term lot with a small gain can cost more than a long-term lot
with a larger one.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import NamedTuple

logger = logging.getLogger(__name__)

# Long-term capital gains threshold: 1 year + 1 day
_LT_HOLDING_DAYS = 366


class LotSelection(Enum):
    """Available lot selection strategies."""

    HIFO = "hifo"
    LIFO = "lifo"
    FIFO = "fifo"
    TAX_OPTIMAL = "tax_optimal"


@dataclass(frozen=True)
class Lot:
    """A single tax lot. All money fields are Decimal. Fractional shares to 6 decimals.

    Data source: internal purchase ledger.
    available_at logic: available upon purchase confirmation.
    Spec section: docs/11 section 2.
    """

    lot_id: str
    ticker: str
    sleeve: str
    account: str
    acquired_at: date
    shares: Decimal  # 6-decimal fractional shares
    cost_basis_per_share: Decimal
    adjusted_basis: Decimal
    wash_sale_deferred: Decimal = Decimal("0")
    holding_start: date | None = None  # None means same as acquired_at
    closed_at: date | None = None
    proceeds: Decimal | None = None
    realized_gain: Decimal | None = None
    term: str | None = None  # "ST" or "LT" or None if open

    def __post_init__(self) -> None:
        """Validate that money fields are Decimal and shares have <= 6 decimals."""
        money_fields = [
            "shares",
            "cost_basis_per_share",
            "adjusted_basis",
            "wash_sale_deferred",
        ]
        for fname in money_fields:
            val = getattr(self, fname)
            if not isinstance(val, Decimal):
                msg = f"Lot.{fname} must be Decimal, got {type(val).__name__}"
                raise TypeError(msg)
        # Verify 6-decimal precision for shares
        if self.shares.as_tuple().exponent < -6:  # type: ignore[operator]
            msg = f"Shares must have <= 6 decimal places, got {self.shares}"
            raise ValueError(msg)

    @property
    def effective_holding_start(self) -> date:
        """The actual holding start date (accounts for wash-sale inheritance)."""
        return self.holding_start if self.holding_start is not None else self.acquired_at

    def is_long_term(self, as_of: date) -> bool:
        """Whether this lot qualifies for long-term capital gains treatment."""
        holding_days = (as_of - self.effective_holding_start).days
        return holding_days >= _LT_HOLDING_DAYS

    def unrealized_gain_per_share(self, current_price: Decimal) -> Decimal:
        """Per-share unrealized gain using adjusted basis."""
        basis_per_share = self.adjusted_basis / self.shares
        return current_price - basis_per_share

    def total_unrealized_gain(self, current_price: Decimal) -> Decimal:
        """Total unrealized gain for all shares in this lot."""
        return self.unrealized_gain_per_share(current_price) * self.shares


class LotSelectionResult(NamedTuple):
    """Result of a lot selection decision."""

    lot: Lot
    shares_to_sell: Decimal
    reason: str


@dataclass
class TaxRates:
    """Tax rates for after-tax optimization.

    Data source: user configuration / tax bracket lookup.
    Spec section: docs/11 section 3.
    """

    short_term_rate: Decimal  # Marginal ordinary income rate
    long_term_rate: Decimal  # Long-term capital gains rate
    state_rate: Decimal = Decimal("0")  # State tax rate (applies to both)

    def __post_init__(self) -> None:
        for fname in ("short_term_rate", "long_term_rate", "state_rate"):
            val = getattr(self, fname)
            if not isinstance(val, Decimal):
                msg = f"TaxRates.{fname} must be Decimal, got {type(val).__name__}"
                raise TypeError(msg)

    @property
    def effective_st_rate(self) -> Decimal:
        """Combined federal + state short-term rate."""
        return self.short_term_rate + self.state_rate

    @property
    def effective_lt_rate(self) -> Decimal:
        """Combined federal + state long-term rate."""
        return self.long_term_rate + self.state_rate


@dataclass
class WashSaleRisk:
    """Wash-sale risk assessment for a lot.

    Data source: internal purchase/sale ledger cross-account scan.
    Spec section: docs/11 section 5.
    """

    at_risk: bool
    conflicting_lot_id: str | None = None
    reason: str = ""


def _compute_tax_cost(
    lot: Lot,
    shares_to_sell: Decimal,
    current_price: Decimal,
    sale_date: date,
    tax_rates: TaxRates,
    wash_sale_risk: WashSaleRisk | None = None,
) -> Decimal:
    """Compute the tax cost of selling shares from a lot.

    Returns the dollar tax cost (positive = tax owed, negative = tax benefit from loss).
    """
    basis_per_share = lot.adjusted_basis / lot.shares
    gain_per_share = current_price - basis_per_share
    total_gain = gain_per_share * shares_to_sell

    is_lt = lot.is_long_term(sale_date)
    rate = tax_rates.effective_lt_rate if is_lt else tax_rates.effective_st_rate

    tax_cost = total_gain * rate

    # If there's wash-sale risk on a loss, the loss is disallowed (not deferred if cross-account)
    if wash_sale_risk and wash_sale_risk.at_risk and total_gain < 0:
        # Loss would be disallowed — no tax benefit
        tax_cost = Decimal("0")

    return tax_cost


def _after_tax_proceeds(
    lot: Lot,
    shares_to_sell: Decimal,
    current_price: Decimal,
    sale_date: date,
    tax_rates: TaxRates,
    wash_sale_risk: WashSaleRisk | None = None,
) -> Decimal:
    """Compute after-tax proceeds from selling shares of a lot.

    Maximizing after-tax proceeds is the correct objective (docs/11 section 3).
    """
    gross_proceeds = current_price * shares_to_sell
    tax_cost = _compute_tax_cost(
        lot, shares_to_sell, current_price, sale_date, tax_rates, wash_sale_risk
    )
    return gross_proceeds - tax_cost


def select_lots(
    lots: list[Lot],
    shares_needed: Decimal,
    current_price: Decimal,
    sale_date: date,
    strategy: LotSelection = LotSelection.TAX_OPTIMAL,
    tax_rates: TaxRates | None = None,
    wash_sale_risks: dict[str, WashSaleRisk] | None = None,
) -> list[LotSelectionResult]:
    """Select lots to sell, maximizing after-tax proceeds.

    Data source: internal lot ledger.
    available_at logic: all lots available as of sale_date.
    Spec section: docs/11 section 3.

    Parameters
    ----------
    lots : list[Lot]
        Available open lots for the ticker (closed_at must be None).
    shares_needed : Decimal
        Total shares to sell (6-decimal precision).
    current_price : Decimal
        Current market price per share.
    sale_date : date
        Date of sale (for holding period determination).
    strategy : LotSelection
        Selection strategy. TAX_OPTIMAL requires tax_rates.
    tax_rates : TaxRates | None
        Required for TAX_OPTIMAL strategy.
    wash_sale_risks : dict[str, WashSaleRisk] | None
        Map of lot_id -> wash sale risk assessment.

    Returns
    -------
    list[LotSelectionResult]
        Ordered list of lots to sell with shares and reasons.

    Raises
    ------
    ValueError
        If shares_needed exceeds available shares, or TAX_OPTIMAL without tax_rates.
    """
    if not isinstance(shares_needed, Decimal):
        msg = f"shares_needed must be Decimal, got {type(shares_needed).__name__}"
        raise TypeError(msg)
    if not isinstance(current_price, Decimal):
        msg = f"current_price must be Decimal, got {type(current_price).__name__}"
        raise TypeError(msg)

    # Filter to open lots only
    open_lots = [lot for lot in lots if lot.closed_at is None]

    if not open_lots:
        msg = "No open lots available"
        raise ValueError(msg)

    total_available = sum((lot.shares for lot in open_lots), Decimal("0"))
    if shares_needed > total_available:
        msg = (
            f"Need {shares_needed} shares but only {total_available} available "
            f"across {len(open_lots)} open lots"
        )
        raise ValueError(msg)

    if strategy == LotSelection.TAX_OPTIMAL and tax_rates is None:
        msg = "TAX_OPTIMAL strategy requires tax_rates"
        raise ValueError(msg)

    if strategy == LotSelection.HIFO:
        return _select_hifo(open_lots, shares_needed, current_price, sale_date)
    elif strategy == LotSelection.LIFO:
        return _select_lifo(open_lots, shares_needed, sale_date)
    elif strategy == LotSelection.FIFO:
        return _select_fifo(open_lots, shares_needed, sale_date)
    elif strategy == LotSelection.TAX_OPTIMAL:
        assert tax_rates is not None  # guarded above
        return _select_tax_optimal(
            open_lots, shares_needed, current_price, sale_date, tax_rates, wash_sale_risks
        )
    else:
        msg = f"Unknown strategy: {strategy}"
        raise ValueError(msg)


def _select_hifo(
    lots: list[Lot],
    shares_needed: Decimal,
    current_price: Decimal,
    sale_date: date,
) -> list[LotSelectionResult]:
    """Highest-In, First-Out: sell lots with highest cost basis first."""
    sorted_lots = sorted(
        lots,
        key=lambda lot: lot.adjusted_basis / lot.shares,
        reverse=True,
    )
    return _fill_from_sorted(sorted_lots, shares_needed, sale_date, "HIFO: highest basis first")


def _select_lifo(
    lots: list[Lot],
    shares_needed: Decimal,
    sale_date: date,
) -> list[LotSelectionResult]:
    """Last-In, First-Out: sell most recently acquired lots first."""
    sorted_lots = sorted(lots, key=lambda lot: lot.acquired_at, reverse=True)
    return _fill_from_sorted(sorted_lots, shares_needed, sale_date, "LIFO: most recent first")


def _select_fifo(
    lots: list[Lot],
    shares_needed: Decimal,
    sale_date: date,
) -> list[LotSelectionResult]:
    """First-In, First-Out: sell oldest lots first."""
    sorted_lots = sorted(lots, key=lambda lot: lot.acquired_at)
    return _fill_from_sorted(sorted_lots, shares_needed, sale_date, "FIFO: oldest first")


def _fill_from_sorted(
    sorted_lots: list[Lot],
    shares_needed: Decimal,
    sale_date: date,
    base_reason: str,
) -> list[LotSelectionResult]:
    """Fill shares_needed from a pre-sorted lot list."""
    results: list[LotSelectionResult] = []
    remaining = shares_needed

    for lot in sorted_lots:
        if remaining <= Decimal("0"):
            break
        sell_qty = min(lot.shares, remaining)
        term = "LT" if lot.is_long_term(sale_date) else "ST"
        basis_per_share = lot.adjusted_basis / lot.shares
        reason = (
            f"{base_reason}; lot={lot.lot_id}, shares={sell_qty}, "
            f"basis/sh={basis_per_share}, term={term}"
        )
        logger.info(reason)
        results.append(LotSelectionResult(lot=lot, shares_to_sell=sell_qty, reason=reason))
        remaining -= sell_qty

    return results


def _select_tax_optimal(
    lots: list[Lot],
    shares_needed: Decimal,
    current_price: Decimal,
    sale_date: date,
    tax_rates: TaxRates,
    wash_sale_risks: dict[str, WashSaleRisk] | None = None,
) -> list[LotSelectionResult]:
    """After-tax-optimal lot selection.

    Maximizes after-tax proceeds by considering:
    1. Holding period (ST vs LT rate difference)
    2. Loss harvesting value (losses at higher ST rate vs lower LT rate)
    3. Wash sale risk (disallowed losses provide no tax benefit)

    The key insight: a short-term lot with a small gain can cost MORE in tax than
    a long-term lot with a larger gain, because the ST rate is higher.
    """
    if wash_sale_risks is None:
        wash_sale_risks = {}

    # Score each lot by after-tax proceeds per share
    @dataclass
    class _ScoredLot:
        lot: Lot
        after_tax_proceeds_per_share: Decimal = field(default=Decimal("0"))
        reason_parts: list[str] = field(default_factory=list)

    scored: list[_ScoredLot] = []

    for lot in lots:
        wsr = wash_sale_risks.get(lot.lot_id)
        atp = _after_tax_proceeds(lot, lot.shares, current_price, sale_date, tax_rates, wsr)
        atp_per_share = atp / lot.shares

        # Build reason explanation
        basis_per_share = lot.adjusted_basis / lot.shares
        gain_per_share = current_price - basis_per_share
        is_lt = lot.is_long_term(sale_date)
        term = "LT" if is_lt else "ST"
        rate = tax_rates.effective_lt_rate if is_lt else tax_rates.effective_st_rate
        tax_per_share = gain_per_share * rate

        reason_parts = [
            f"basis/sh={basis_per_share}",
            f"gain/sh={gain_per_share}",
            f"term={term}",
            f"rate={rate}",
            f"tax/sh={tax_per_share}",
            f"after_tax_proceeds/sh={atp_per_share}",
        ]

        if wsr and wsr.at_risk:
            if gain_per_share < 0:
                reason_parts.append(
                    f"WASH_SALE_RISK: loss disallowed (conflict={wsr.conflicting_lot_id})"
                )
                # Penalize: loss won't provide tax benefit
                # after_tax_proceeds already accounts for this via _after_tax_proceeds

        scored.append(
            _ScoredLot(
                lot=lot,
                after_tax_proceeds_per_share=atp_per_share,
                reason_parts=reason_parts,
            )
        )

    # Sort by after-tax proceeds per share, descending (best first)
    scored.sort(key=lambda s: s.after_tax_proceeds_per_share, reverse=True)

    # Fill from the best lots
    results: list[LotSelectionResult] = []
    remaining = shares_needed

    for s in scored:
        if remaining <= Decimal("0"):
            break
        sell_qty = min(s.lot.shares, remaining)
        reason = f"TAX_OPTIMAL: lot={s.lot.lot_id}, shares={sell_qty}, " + ", ".join(
            s.reason_parts
        )
        logger.info(reason)
        results.append(LotSelectionResult(lot=s.lot, shares_to_sell=sell_qty, reason=reason))
        remaining -= sell_qty

    return results
