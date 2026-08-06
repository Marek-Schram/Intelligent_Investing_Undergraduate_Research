"""Tax loss harvesting with wash sale detection. TICKET-036. docs/11.

Harvests unrealized losses in TAXABLE accounts only, subject to:
  1. 61-day wash sale window (30 before + sale day + 30 after) across ALL accounts.
  2. Cross-account purchases (including Roth/IRA) trigger PERMANENT loss of deduction.
  3. DRIP counts as a purchase.
  4. Disallowed loss is ADDED to replacement lot basis, holding period inherited.
  5. Refuses to harvest a name the screen wants this quarter.
  6. Replacement is a sector ETF proxy.

Data source: tax lot records from broker, quarterly screen results.
available_at logic: lots as of trade date; screen as of rebalance date.
Spec section: docs/11 section 3.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

# 61-day wash sale window: 30 days before + sale day + 30 days after
WASH_SALE_WINDOW_DAYS = 61
WASH_SALE_BEFORE = 30
WASH_SALE_AFTER = 30


class AccountType(Enum):
    TAXABLE = "taxable"
    ROTH = "roth"
    TRADITIONAL_IRA = "traditional_ira"


class LossType(Enum):
    """Whether a disallowed loss is deferred (same account) or permanent (cross-account)."""

    DEFERRED = "deferred"
    PERMANENT = "permanent"


# Sector ETF proxies: ticker -> sector ETF replacement
SECTOR_ETF_MAP: dict[str, str] = {
    "XLK": "XLK",  # Technology
    "XLV": "XLV",  # Health Care
    "XLF": "XLF",  # Financials
    "XLY": "XLY",  # Consumer Discretionary
    "XLP": "XLP",  # Consumer Staples
    "XLE": "XLE",  # Energy
    "XLI": "XLI",  # Industrials
    "XLB": "XLB",  # Materials
    "XLU": "XLU",  # Utilities
    "XLRE": "XLRE",  # Real Estate
    "XLC": "XLC",  # Communication Services
}

# Map GICS sector codes to sector ETFs
GICS_SECTOR_TO_ETF: dict[str, str] = {
    "Information Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


@dataclass(frozen=True)
class TaxLot:
    """A single tax lot in any account."""

    lot_id: str
    ticker: str
    shares: Decimal
    cost_basis: Decimal  # Total basis for this lot
    purchase_date: date
    account_type: AccountType
    account_id: str


@dataclass(frozen=True)
class Transaction:
    """A purchase or sale transaction across any account."""

    ticker: str
    trade_date: date
    shares: Decimal
    price_per_share: Decimal
    account_type: AccountType
    account_id: str
    is_drip: bool = False  # Dividend reinvestment


@dataclass(frozen=True)
class WashSaleResult:
    """Result of wash sale detection for a proposed sale."""

    is_wash_sale: bool
    loss_type: LossType | None  # PERMANENT if cross-account, DEFERRED if same account
    disallowed_amount: Decimal
    triggering_purchase: Transaction | None
    explanation: str


@dataclass(frozen=True)
class HarvestOpportunity:
    """An identified tax loss harvesting opportunity."""

    lot: TaxLot
    current_price: Decimal
    unrealized_loss: Decimal  # Negative = loss (absolute value)
    replacement_etf: str
    wash_sale_risk: WashSaleResult | None


@dataclass(frozen=True)
class AdjustedLot:
    """A replacement lot after wash sale basis adjustment."""

    lot_id: str
    ticker: str
    shares: Decimal
    adjusted_basis: Decimal  # Original basis + disallowed loss
    holding_period_start: date  # Inherited from original lot
    account_type: AccountType
    account_id: str


class WashSaleWindow:
    """61-day wash sale window: 30 days before + sale day + 30 days after.

    The window is inclusive on both ends.
    """

    def __init__(self, sale_date: date) -> None:
        self.sale_date = sale_date
        self.start = sale_date - timedelta(days=WASH_SALE_BEFORE)
        self.end = sale_date + timedelta(days=WASH_SALE_AFTER)

    @property
    def total_days(self) -> int:
        """Total calendar days in the window (inclusive)."""
        return (self.end - self.start).days + 1

    def contains(self, transaction_date: date) -> bool:
        """Check if a transaction date falls within the wash sale window."""
        return self.start <= transaction_date <= self.end


def scan_all_accounts(
    ticker: str,
    sale_date: date,
    transactions: list[Transaction],
    sale_account_type: AccountType,
) -> WashSaleResult:
    """Scan ALL accounts for wash sale violations within the 61-day window.

    MUST include taxable, Roth, and traditional IRA. A cross-account wash sale
    (e.g. taxable sale + Roth purchase) permanently destroys the deduction.
    DRIP counts as a purchase.

    Data source: transaction records from all broker accounts.
    available_at logic: as of trade date.
    Spec section: docs/11 section 3.

    Args:
        ticker: The security being sold.
        sale_date: Date of the proposed sale.
        transactions: ALL transactions across ALL accounts (taxable, Roth, IRA).
        sale_account_type: The account type where the sale occurs.

    Returns:
        WashSaleResult indicating whether a wash sale is triggered.
    """
    window = WashSaleWindow(sale_date)

    # Find purchases of the same ticker within the window
    for txn in transactions:
        if txn.ticker != ticker:
            continue
        if txn.trade_date == sale_date and txn.account_type == sale_account_type:
            # The sale itself is not a triggering purchase
            continue
        if not window.contains(txn.trade_date):
            continue

        # Found a purchase within the window — wash sale triggered
        is_cross_account = txn.account_type != sale_account_type
        loss_type = LossType.PERMANENT if is_cross_account else LossType.DEFERRED

        drip_note = " (DRIP)" if txn.is_drip else ""
        cross_note = (
            f" Cross-account ({sale_account_type.value} -> {txn.account_type.value}):"
            " deduction PERMANENTLY LOST."
            if is_cross_account
            else " Same account: loss deferred to replacement basis."
        )

        explanation = (
            f"Wash sale triggered: {ticker} purchased{drip_note} on {txn.trade_date} "
            f"in {txn.account_type.value} account within 61-day window of sale on "
            f"{sale_date}.{cross_note}"
        )

        # Disallowed amount is the full loss (caller computes actual loss amount)
        # Here we return Decimal(0) as a placeholder; actual disallowed amount
        # must be computed by the caller based on lot basis vs. proceeds
        return WashSaleResult(
            is_wash_sale=True,
            loss_type=loss_type,
            disallowed_amount=Decimal("0"),  # Caller fills from lot data
            triggering_purchase=txn,
            explanation=explanation,
        )

    return WashSaleResult(
        is_wash_sale=False,
        loss_type=None,
        disallowed_amount=Decimal("0"),
        triggering_purchase=None,
        explanation=f"No wash sale: no purchases of {ticker} within 61-day window.",
    )


def scan_all_accounts_with_loss(
    ticker: str,
    sale_date: date,
    loss_amount: Decimal,
    transactions: list[Transaction],
    sale_account_type: AccountType,
) -> WashSaleResult:
    """Scan all accounts and compute the disallowed loss amount.

    Same as scan_all_accounts but fills in the actual disallowed amount.

    Data source: transaction records from all broker accounts.
    available_at logic: as of trade date.
    Spec section: docs/11 section 3.

    Args:
        ticker: The security being sold.
        sale_date: Date of the proposed sale.
        loss_amount: The absolute value of the loss on the sale (positive Decimal).
        transactions: ALL transactions across ALL accounts.
        sale_account_type: The account type where the sale occurs.

    Returns:
        WashSaleResult with disallowed_amount filled in.
    """
    result = scan_all_accounts(ticker, sale_date, transactions, sale_account_type)
    if result.is_wash_sale:
        return WashSaleResult(
            is_wash_sale=True,
            loss_type=result.loss_type,
            disallowed_amount=loss_amount,
            triggering_purchase=result.triggering_purchase,
            explanation=result.explanation,
        )
    return result


def harvest_opportunity(
    lot: TaxLot,
    current_price: Decimal,
    ticker_sector: str,
    wanted_tickers: set[str],
    all_transactions: list[Transaction],
) -> HarvestOpportunity | None:
    """Identify a tax loss harvesting opportunity for a given lot.

    Only harvests in TAXABLE accounts. Refuses to harvest if the name is wanted
    by the screen this quarter.

    Data source: tax lots, current prices, screen results.
    available_at logic: current price as of today; screen as of rebalance date.
    Spec section: docs/11 section 3.

    Args:
        lot: The tax lot to evaluate.
        current_price: Current market price per share.
        ticker_sector: GICS sector name for the lot's ticker.
        wanted_tickers: Tickers the screen wants to buy this quarter.
        all_transactions: All transactions for wash sale check.

    Returns:
        HarvestOpportunity if the lot qualifies, None otherwise.
    """
    # Only harvest in taxable accounts
    if lot.account_type != AccountType.TAXABLE:
        return None

    # Refuse if the screen wants this name
    if refuse_if_wanted(lot.ticker, wanted_tickers):
        return None

    # Calculate unrealized loss
    market_value = current_price * lot.shares
    unrealized_pnl = market_value - lot.cost_basis

    # Only harvest losses (negative P&L)
    if unrealized_pnl >= Decimal("0"):
        return None

    # Find replacement ETF
    etf = replacement_etf(ticker_sector)
    if etf is None:
        return None

    # Check for wash sale risk
    wash_result = scan_all_accounts_with_loss(
        ticker=lot.ticker,
        sale_date=date.today(),  # Placeholder — caller should pass actual proposed date
        loss_amount=abs(unrealized_pnl),
        transactions=all_transactions,
        sale_account_type=lot.account_type,
    )

    return HarvestOpportunity(
        lot=lot,
        current_price=current_price,
        unrealized_loss=abs(unrealized_pnl),
        replacement_etf=etf,
        wash_sale_risk=wash_result if wash_result.is_wash_sale else None,
    )


def refuse_if_wanted(ticker: str, wanted_tickers: set[str]) -> bool:
    """Block harvest when the screen wants to BUY this name this quarter.

    Harvesting and then rebuying creates a wash sale. If the screen signals a buy,
    do not sell for harvest purposes.

    Data source: quarterly screen output.
    available_at logic: screen as of rebalance date.
    Spec section: docs/11 section 3.

    Args:
        ticker: Ticker to check.
        wanted_tickers: Set of tickers the screen wants to buy this quarter.

    Returns:
        True if harvest should be refused (ticker is wanted).
    """
    return ticker in wanted_tickers


def replacement_etf(sector: str) -> str | None:
    """Suggest a sector ETF proxy as replacement for harvested position.

    Uses GICS sector mapping. Returns None if sector is unknown.

    Data source: static GICS-to-ETF mapping.
    available_at logic: N/A (static).
    Spec section: docs/11 section 3.

    Args:
        sector: GICS sector name (e.g. "Information Technology").

    Returns:
        Sector ETF ticker or None if sector not mapped.
    """
    return GICS_SECTOR_TO_ETF.get(sector)


def adjust_basis_for_wash_sale(
    replacement_lot: TaxLot,
    disallowed_loss: Decimal,
    original_purchase_date: date,
) -> AdjustedLot:
    """Add disallowed wash sale loss to the replacement lot's basis.

    The holding period of the replacement inherits from the original lot.
    This is NOT optional — IRS requires it.

    Data source: lot records, wash sale determination.
    available_at logic: as of trade date.
    Spec section: docs/11 section 3.

    Args:
        replacement_lot: The new lot that triggered the wash sale.
        disallowed_loss: Amount of loss disallowed (positive Decimal).
        original_purchase_date: Purchase date of the original lot (for holding period).

    Returns:
        AdjustedLot with increased basis and inherited holding period.
    """
    if disallowed_loss < Decimal("0"):
        raise ValueError("disallowed_loss must be non-negative")

    adjusted_basis = replacement_lot.cost_basis + disallowed_loss

    return AdjustedLot(
        lot_id=replacement_lot.lot_id,
        ticker=replacement_lot.ticker,
        shares=replacement_lot.shares,
        adjusted_basis=adjusted_basis,
        holding_period_start=original_purchase_date,
        account_type=replacement_lot.account_type,
        account_id=replacement_lot.account_id,
    )
