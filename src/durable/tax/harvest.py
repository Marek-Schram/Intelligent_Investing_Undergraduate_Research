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

Everything above the "CLI: tax-review orchestration" marker is PURE: no I/O, network,
wall-clock, or config lookups. The CLI section below it (`make tax-review` /
`python -m durable.tax.harvest --review`) is the one place in this module that touches
the database, the config file, and the wall clock -- and it touches the wall clock in
exactly one place, `main()`, resolving `--as-of` to `date.today()` only when the flag is
omitted, then threading that single explicit `date` through every pure function below.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import duckdb

    from durable.tax.lots import TaxRates
    from durable.tax.selection import LotSelectionComparison

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
    sale_date: date,
) -> HarvestOpportunity | None:
    """Identify a tax loss harvesting opportunity for a given lot.

    Only harvests in TAXABLE accounts. Refuses to harvest if the name is wanted
    by the screen this quarter.

    Data source: tax lots, current prices, screen results.
    available_at logic: current price as of `sale_date`; screen as of rebalance date.
    Spec section: docs/11 section 3.

    Args:
        lot: The tax lot to evaluate.
        current_price: Current market price per share.
        ticker_sector: GICS sector name for the lot's ticker.
        wanted_tickers: Tickers the screen wants to buy this quarter.
        all_transactions: All transactions for wash sale check.
        sale_date: The proposed sale date. Callers must pass this explicitly (e.g. from
            a CLI's `--as-of` flag, defaulting to `date.today()` only at that CLI boundary)
            -- this function must never read the wall clock itself, per
            .claude/rules/no-lookahead.md rule 4.

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
        sale_date=sale_date,
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


# ---------------------------------------------------------------------------
# CLI: tax-review orchestration (TICKET-036 wiring; `make tax-review`)
# ---------------------------------------------------------------------------
#
# Everything below this line does I/O (DuckDB, config, stdout, the filesystem) and is
# the only part of this module allowed to. `main()` is the one function permitted to
# read the wall clock, and only to resolve `--as-of` when the flag is omitted.

logger = logging.getLogger(__name__)

_LT_HOLDING_DAYS = 366  # 1 year + 1 day; must match durable.tax.lots._LT_HOLDING_DAYS
_TWELVE_MONTH_WATCH_WINDOW_DAYS = 45

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REPORTS_DIR = PROJECT_ROOT / "reports"


class NoTaxLotsError(RuntimeError):
    """Raised when the `tax_lots` table has no rows as of the review date.

    Distinct from "lots exist but nothing to harvest" (a normal, successful review):
    this means the ledger itself is empty, most likely because ingest/broker
    reconciliation hasn't populated it yet.
    """


@dataclass(frozen=True)
class _LotRecord:
    """One row of `tax_lots`, translated into `harvest.TaxLot` plus the fields
    `TaxLot` doesn't carry (`sleeve`, `closed_at`, `holding_start`) but the review needs."""

    tax_lot: TaxLot
    sleeve: str
    closed_at: date | None
    holding_start: date


@dataclass(frozen=True)
class HarvestCandidate:
    """One ticker's aggregated harvest opportunity across its taxable lots."""

    ticker: str
    sleeve: str
    lots_considered: list[TaxLot]
    current_price: Decimal
    total_shares: Decimal
    total_cost_basis: Decimal
    unrealized_loss: Decimal  # positive Decimal
    loss_pct: Decimal
    meets_threshold: bool
    wash_sale: WashSaleResult
    replacement_etf: str | None
    sector: str | None
    comparison: LotSelectionComparison | None  # which specific lots to sell, and why


@dataclass(frozen=True)
class TwelveMonthWatch:
    """A lot approaching the long-term capital-gains threshold."""

    lot_id: str
    ticker: str
    days_to_long_term: int


@dataclass(frozen=True)
class TaxReviewReport:
    """Full result of a tax-loss-harvest review as of one date."""

    as_of: date
    n_lots_total: int
    n_lots_by_account: dict[str, int]
    harvest_candidates: list[HarvestCandidate]
    wash_sale_blocked: list[HarvestCandidate]
    below_threshold: list[HarvestCandidate]
    twelve_month_watch: list[TwelveMonthWatch]
    total_tax_alpha_vs_fifo: Decimal
    use_now_vs_carry: object | None  # durable.tax.after_tax.UseNowVsCarryResult, if any
    notes: list[str]


def _to_decimal_shares(value: object) -> Decimal:
    """Convert a `tax_lots.shares` value to a 6-decimal Decimal.

    `tax_lots.shares` is declared `DOUBLE` in `store.py` (a schema this module does not
    own and must not change), so DuckDB's DBAPI hands back a Python `float`. Converting
    via `str()` (never `Decimal(float)` directly) avoids binary-float artifacts, and the
    result is quantized to 6 decimal places per tax-correctness rule 7.
    """
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.000001"))
    return Decimal(str(value)).quantize(Decimal("0.000001"))


def _load_all_lots_as_of(conn: duckdb.DuckDBPyConnection, as_of: date) -> list[_LotRecord]:
    """Load every tax lot acquired on or before `as_of`, across ALL accounts.

    Includes lots already closed by `as_of`: a closed lot's acquisition can still be the
    *triggering purchase* of a wash sale on a different, currently-open lot, so it must
    stay in the transaction history even though it is excluded from "what's open to sell".

    Deliberately bypasses `store.as_of()`: that helper explicitly rejects the `tax_lots`
    table (`store.py::as_of` raises for `table in ("snapshots", "firewall_violations",
    "tax_lots")`) because `tax_lots` is mutable ledger state, not an append-only
    point-in-time snapshot series. No-look-ahead is instead enforced directly here: any
    lot with `acquired_at > as_of` is excluded by the query itself. Rows are read via the
    raw DBAPI cursor (`.fetchall()`), never `.fetchdf()` -- `.fetchdf()` silently widens
    DECIMAL columns to float64 (verified against this DuckDB version), which would put a
    float into a tax calculation the instant it touched one.

    Data source: `tax_lots` table (`durable.data.store`).
    available_at logic: `acquired_at <= as_of`, enforced in the WHERE clause above.
    Spec section: docs/11 section 2.
    """
    query = """
        SELECT lot_id, ticker, sleeve, account, acquired_at, shares, cost_basis_per_share,
               adjusted_basis, holding_start, closed_at
        FROM tax_lots
        WHERE acquired_at <= ?
        ORDER BY ticker, acquired_at
    """
    cursor = conn.execute(query, [as_of])
    columns = [d[0] for d in cursor.description]
    rows = cursor.fetchall()

    records: list[_LotRecord] = []
    for row in rows:
        rec = dict(zip(columns, row, strict=True))
        shares = _to_decimal_shares(rec["shares"])
        adjusted_basis = rec["adjusted_basis"]
        if adjusted_basis is None:
            adjusted_basis = rec["cost_basis_per_share"] * shares
        try:
            account_type = AccountType(rec["account"])
        except ValueError as exc:
            msg = (
                f"Lot {rec['lot_id']}: unknown account {rec['account']!r}; expected one of "
                f"{[a.value for a in AccountType]}"
            )
            raise ValueError(msg) from exc

        records.append(
            _LotRecord(
                tax_lot=TaxLot(
                    lot_id=rec["lot_id"],
                    ticker=rec["ticker"],
                    shares=shares,
                    cost_basis=adjusted_basis,
                    purchase_date=rec["acquired_at"],
                    account_type=account_type,
                    account_id=rec["account"],
                ),
                sleeve=rec["sleeve"],
                closed_at=rec["closed_at"],
                holding_start=rec["holding_start"],
            )
        )
    return records


def _lots_to_transactions(all_lots: list[TaxLot]) -> list[Transaction]:
    """Treat every lot acquisition as a purchase transaction for wash-sale scanning.

    KNOWN SCHEMA GAP: `tax_lots` has no `is_drip` column, so every transaction built here
    is marked `is_drip=False`. Per tax-correctness rule 5, DRIP must count as a purchase --
    it still does functionally, because a DRIP purchase creates its own lot row (typically
    a small fractional-share lot) which becomes its own `Transaction` here and is scanned
    for the wash-sale window exactly like a manual buy. Only the report's DRIP-specific
    label is unavailable until the schema carries the flag; flagged in `main()`'s notes.
    """
    return [
        Transaction(
            ticker=lot.ticker,
            trade_date=lot.purchase_date,
            shares=lot.shares,
            price_per_share=(lot.cost_basis / lot.shares) if lot.shares else Decimal("0"),
            account_type=lot.account_type,
            account_id=lot.account_id,
            is_drip=False,
        )
        for lot in all_lots
    ]


def _twelve_month_watch(open_records: list[_LotRecord], as_of: date) -> list[TwelveMonthWatch]:
    """Flag open lots within `_TWELVE_MONTH_WATCH_WINDOW_DAYS` of the long-term threshold.

    Uses `holding_start`, not `acquired_at`: a lot whose holding period was inherited via
    a prior wash-sale basis adjustment (rule 4) must be measured from the inherited date.
    """
    watch: list[TwelveMonthWatch] = []
    for r in open_records:
        days_held = (as_of - r.holding_start).days
        days_to_lt = _LT_HOLDING_DAYS - days_held
        if 0 < days_to_lt <= _TWELVE_MONTH_WATCH_WINDOW_DAYS:
            watch.append(
                TwelveMonthWatch(
                    lot_id=r.tax_lot.lot_id,
                    ticker=r.tax_lot.ticker,
                    days_to_long_term=days_to_lt,
                )
            )
    return sorted(watch, key=lambda w: w.days_to_long_term)


def build_tax_review(
    conn: duckdb.DuckDBPyConnection,
    *,
    as_of: date,
    tax_rates: TaxRates,
    harvest_min_loss_pct: Decimal = Decimal("0.08"),
    harvest_min_loss_dollars: Decimal = Decimal("150"),
    wanted_tickers: set[str] | None = None,
    price_lookup: object = None,
    sector_lookup: object = None,
    expected_future_st_rate: Decimal | None = None,
) -> TaxReviewReport:
    """Build a full tax-loss-harvest review as of `as_of`.

    Orchestrates, in order, exactly the functions the ticket names: `harvest_opportunity`
    (which itself calls `scan_all_accounts_with_loss` and `replacement_etf`) per taxable
    lot, then `durable.tax.selection.select_after_tax_optimal_harvest_lots` to decide
    which SPECIFIC lots to sell and confirm that selection beats naive HIFO/FIFO.

    Never harvests in Roth or traditional IRA (rule 6) -- `harvest_opportunity` enforces
    this per-lot; taxable-only filtering happens again here for the report's accounting.

    Args:
        conn: An open DuckDB connection (schema already initialized).
        as_of: The proposed sale/review date. Threaded explicitly into every wash-sale
            and holding-period calculation -- never read from the wall clock in here.
        tax_rates: Marginal short-term/long-term rates for after-tax optimization.
        harvest_min_loss_pct: Minimum loss, as a fraction of cost basis, to trigger (docs/11 §4).
        harvest_min_loss_dollars: Minimum absolute-dollar loss to trigger (docs/11 §4).
        wanted_tickers: Tickers the screen wants to buy this quarter (refused, per rule).
        price_lookup: `Callable[[str], Decimal | None]` returning a current price, or None
            if unavailable. Injected so this function stays testable without a live feed.
        sector_lookup: `Callable[[str], str | None]` returning a GICS sector, or None.
        expected_future_st_rate: Assumed future short-term rate for the use-now-vs-carry
            comparison. Defaults to the current short-term rate if not given.

    Returns:
        TaxReviewReport with candidates, wash-sale blocks, the 12-month watchlist, and
        an estimated tax alpha vs. a naive-FIFO lot-selection counterfactual.

    Raises:
        NoTaxLotsError: If `tax_lots` has no rows as of `as_of`.
    """
    from durable.tax import selection  # local import: harvest.py is fully loaded by the
    # time build_tax_review() runs, but selection.py imports names FROM this module at
    # its own module level, so importing it back at harvest.py's module level would be
    # a circular import. Deferring to call time sidesteps that entirely.

    wanted_tickers = wanted_tickers or set()
    records = _load_all_lots_as_of(conn, as_of)
    if not records:
        msg = (
            f"No tax lots found in the `tax_lots` table as of {as_of.isoformat()}. Nothing "
            "to review yet -- populate lots via broker reconciliation / ingest (docs/11 "
            "section 2) before running `make tax-review`."
        )
        raise NoTaxLotsError(msg)

    all_lots = [r.tax_lot for r in records]
    all_transactions = _lots_to_transactions(all_lots)

    n_lots_by_account: dict[str, int] = {}
    for r in records:
        key = r.tax_lot.account_type.value
        n_lots_by_account[key] = n_lots_by_account.get(key, 0) + 1

    open_records = [r for r in records if r.closed_at is None or r.closed_at > as_of]
    taxable_open = [r for r in open_records if r.tax_lot.account_type == AccountType.TAXABLE]

    notes: list[str] = []
    if sector_lookup is None:
        notes.append(
            "No sector data source is wired into this environment yet. "
            "harvest_opportunity() requires a GICS sector to select a replacement sector "
            "ETF (docs/11 section 4 forbids harvesting without a compliant replacement), "
            "so tickers will not appear as candidates until sector data is available -- "
            "this is the harvesting rule working as designed, not a bug."
        )
    notes.append(
        "DRIP purchases are not separately labeled (tax_lots has no is_drip column) but "
        "ARE still caught by the wash-sale scan, since every DRIP purchase creates its own "
        "lot row and is scanned like any other purchase."
    )

    if not taxable_open:
        notes.append(
            "No open TAXABLE lots as of this date -- nothing to harvest. Roth and "
            "traditional IRA lots are never harvested, even at a loss (rule 6)."
        )
        return TaxReviewReport(
            as_of=as_of,
            n_lots_total=len(records),
            n_lots_by_account=n_lots_by_account,
            harvest_candidates=[],
            wash_sale_blocked=[],
            below_threshold=[],
            twelve_month_watch=_twelve_month_watch(open_records, as_of),
            total_tax_alpha_vs_fifo=Decimal("0"),
            use_now_vs_carry=None,
            notes=notes,
        )

    by_ticker: dict[str, list[TaxLot]] = {}
    sleeve_by_ticker: dict[str, str] = {}
    for r in taxable_open:
        by_ticker.setdefault(r.tax_lot.ticker, []).append(r.tax_lot)
        sleeve_by_ticker[r.tax_lot.ticker] = r.sleeve

    candidates: list[HarvestCandidate] = []
    blocked: list[HarvestCandidate] = []
    below: list[HarvestCandidate] = []
    total_alpha = Decimal("0")

    for ticker, ticker_lots in sorted(by_ticker.items()):
        price = price_lookup(ticker) if price_lookup is not None else None
        if price is None:
            notes.append(f"{ticker}: no current price available -- skipped.")
            continue

        sector = sector_lookup(ticker) if sector_lookup is not None else None

        opportunities = [
            opp
            for lot in ticker_lots
            if (
                opp := harvest_opportunity(
                    lot=lot,
                    current_price=price,
                    ticker_sector=sector or "",
                    wanted_tickers=wanted_tickers,
                    all_transactions=all_transactions,
                    sale_date=as_of,
                )
            )
            is not None
        ]
        if not opportunities:
            if ticker in wanted_tickers:
                notes.append(
                    f"{ticker}: the screen wants to buy this name this quarter -- harvest "
                    "refused (never harvest a name we'd otherwise buy)."
                )
            continue

        loss_lots = [opp.lot for opp in opportunities]
        total_shares = sum((lot.shares for lot in loss_lots), Decimal("0"))
        total_cost_basis = sum((lot.cost_basis for lot in loss_lots), Decimal("0"))
        total_unrealized_loss = sum((opp.unrealized_loss for opp in opportunities), Decimal("0"))
        loss_pct = (
            (total_unrealized_loss / total_cost_basis)
            if total_cost_basis > Decimal("0")
            else Decimal("0")
        )
        meets_threshold = (
            loss_pct >= harvest_min_loss_pct and total_unrealized_loss >= harvest_min_loss_dollars
        )
        any_wash_sale = any(opp.wash_sale_risk is not None for opp in opportunities)
        wash_result = next(
            (opp.wash_sale_risk for opp in opportunities if opp.wash_sale_risk is not None),
            WashSaleResult(
                is_wash_sale=False,
                loss_type=None,
                disallowed_amount=Decimal("0"),
                triggering_purchase=None,
                explanation=f"No wash sale: no purchases of {ticker} within 61-day window.",
            ),
        )

        comparison = selection.select_after_tax_optimal_harvest_lots(
            ticker=ticker,
            taxable_lots=loss_lots,
            current_price=price,
            sale_date=as_of,
            tax_rates=tax_rates,
            all_transactions=all_transactions,
            sleeve=sleeve_by_ticker[ticker],
        )

        candidate = HarvestCandidate(
            ticker=ticker,
            sleeve=sleeve_by_ticker[ticker],
            lots_considered=loss_lots,
            current_price=price,
            total_shares=total_shares,
            total_cost_basis=total_cost_basis,
            unrealized_loss=total_unrealized_loss,
            loss_pct=loss_pct,
            meets_threshold=meets_threshold,
            wash_sale=wash_result,
            replacement_etf=opportunities[0].replacement_etf,
            sector=sector,
            comparison=comparison,
        )

        if not meets_threshold:
            below.append(candidate)
            continue
        if any_wash_sale:
            blocked.append(candidate)
            continue

        candidates.append(candidate)
        total_alpha += comparison.tax_alpha_vs_fifo

    use_now_vs_carry = None
    total_harvestable = sum((c.unrealized_loss for c in candidates), Decimal("0"))
    if total_harvestable > Decimal("0"):
        from durable.tax import after_tax

        use_now_vs_carry = after_tax.model_use_now_vs_carry(
            available_loss=total_harvestable,
            current_gains=Decimal("0"),
            current_st_rate=tax_rates.effective_st_rate,
            current_lt_rate=tax_rates.effective_lt_rate,
            expected_future_rate=expected_future_st_rate or tax_rates.effective_st_rate,
            gains_are_short_term=True,
        )
        notes.append(
            "use-now-vs-carry-forward assumes $0 other current-year realized gains (no "
            "realized-gains feed is wired into this review yet) -- illustrative, not final."
        )

    return TaxReviewReport(
        as_of=as_of,
        n_lots_total=len(records),
        n_lots_by_account=n_lots_by_account,
        harvest_candidates=candidates,
        wash_sale_blocked=blocked,
        below_threshold=below,
        twelve_month_watch=_twelve_month_watch(open_records, as_of),
        total_tax_alpha_vs_fifo=total_alpha,
        use_now_vs_carry=use_now_vs_carry,
        notes=notes,
    )


def _fmt_money(value: Decimal) -> str:
    return f"${value:,.2f}"


def render_markdown(report: TaxReviewReport) -> str:
    """Render a `TaxReviewReport` as a human-readable Markdown report.

    Written for a 19-year-old retail investor reading this directly, not a CPA --
    plain language first, numbers and lot IDs second, mechanics never advice.
    """
    lines: list[str] = []
    lines.append(f"# Tax Review — {report.as_of.isoformat()}")
    lines.append("")
    lines.append(
        "**Not tax advice.** This report encodes mechanics (wash-sale rules, lot "
        "selection, loss carryforward) as arithmetic, not recommendations. Confirm "
        "anything material with a CPA before you act on it."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Tax lots on record as of this date: **{report.n_lots_total}**")
    for account, n in sorted(report.n_lots_by_account.items()):
        lines.append(f"  - `{account}`: {n}")
    lines.append(
        f"- Harvest candidates (loss, above threshold, no wash-sale block): "
        f"**{len(report.harvest_candidates)}**"
    )
    lines.append(f"- Blocked by a wash sale: **{len(report.wash_sale_blocked)}**")
    lines.append(
        f"- Below the harvest threshold (loss too small to bother): "
        f"**{len(report.below_threshold)}**"
    )
    lines.append(
        f"- Positions approaching the 12-month long-term threshold: "
        f"**{len(report.twelve_month_watch)}**"
    )
    lines.append("")

    lines.append("## The honest counterfactual")
    lines.append(
        "If you sold these positions with a naive broker default (FIFO -- oldest shares "
        "first, no tax awareness) instead of the after-tax-optimal lot selection below, "
        "you would keep less. That difference, summed across every candidate below, is "
        "the honest measure of this review's tax alpha: "
        f"**{_fmt_money(report.total_tax_alpha_vs_fifo)}**."
    )
    lines.append(
        "Tax alpha from lot selection decays as unrealized losses get used up and "
        "replacement basis resets closer to market price -- it is largest in the early "
        "years of a taxable account and should not be assumed to repeat every year."
    )
    lines.append("")

    if report.harvest_candidates:
        lines.append("## Harvest candidates")
        for c in report.harvest_candidates:
            lines.append(f"### {c.ticker} (sleeve {c.sleeve})")
            lines.append(
                f"- Unrealized loss: **{_fmt_money(c.unrealized_loss)}** "
                f"({c.loss_pct:.1%} of {_fmt_money(c.total_cost_basis)} cost basis), "
                f"current price {_fmt_money(c.current_price)}"
            )
            lines.append(
                f"- Replacement: **{c.replacement_etf or '(unknown -- sector data unavailable)'}**"
            )
            if c.comparison is not None:
                lines.append("- Specific lots to sell (after-tax-optimal):")
                for r in c.comparison.tax_optimal:
                    lines.append(
                        f"  - `{r.lot.lot_id}`: sell {r.shares_to_sell} shares — {r.reason}"
                    )
                lines.append(
                    "- After-tax proceeds: optimal "
                    f"{_fmt_money(c.comparison.after_tax_proceeds_optimal)} "
                    f"vs naive FIFO {_fmt_money(c.comparison.after_tax_proceeds_fifo)} "
                    f"(alpha {_fmt_money(c.comparison.tax_alpha_vs_fifo)}) vs naive HIFO "
                    f"{_fmt_money(c.comparison.after_tax_proceeds_hifo)} "
                    f"(alpha {_fmt_money(c.comparison.tax_alpha_vs_hifo)})"
                )
            lines.append("")

    if report.wash_sale_blocked:
        lines.append("## Blocked by a wash sale")
        for c in report.wash_sale_blocked:
            lines.append(f"### {c.ticker}")
            lines.append(f"- {c.wash_sale.explanation}")
            lines.append("")

    if report.below_threshold:
        lines.append("## Below the harvest threshold (monitor, don't act)")
        for c in report.below_threshold:
            lines.append(
                f"- {c.ticker}: loss {_fmt_money(c.unrealized_loss)} ({c.loss_pct:.1%}) -- "
                f"below the 8%/$150 trigger (docs/11 section 4)"
            )
        lines.append("")

    if report.twelve_month_watch:
        lines.append("## Approaching the 12-month long-term threshold")
        for w in report.twelve_month_watch:
            lines.append(
                f"- `{w.lot_id}` ({w.ticker}): "
                f"wait **{w.days_to_long_term} days** for long-term rates"
            )
        lines.append("")

    if report.use_now_vs_carry is not None:
        u = report.use_now_vs_carry
        lines.append("## Use the losses now, or carry them forward?")
        lines.append(
            f"- Using now (against this year's gains, then up to $3,000 of ordinary income): "
            f"**{_fmt_money(u.use_now_benefit)}**"
        )
        lines.append(
            "- Carrying forward at an assumed future rate: "
            f"**{_fmt_money(u.carry_forward_benefit)}**"
        )
        lines.append(f"- Arithmetic favors: **{u.recommendation}**")
        lines.append(
            "- As a 19-year-old with modest income, the $3,000 ordinary-income offset is "
            "worth less to you now than it will be at a higher future income -- carrying "
            "losses forward is often the better plan even when 'use now' shows a larger "
            "number today. This is arithmetic under an assumed future rate, not advice; "
            "confirm with a CPA before deciding."
        )
        lines.append("")

    if report.notes:
        lines.append("## Notes and known limitations")
        for n in report.notes:
            lines.append(f"- {n}")
        lines.append("")

    return "\n".join(lines)


def write_tax_review_report(report: TaxReviewReport, *, output_dir: Path | None = None) -> Path:
    """Render and write the report to `reports/tax_review_<as_of>.md`. Returns the path."""
    output_dir = output_dir or REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"tax_review_{report.as_of.isoformat()}.md"
    path.write_text(render_markdown(report))
    return path


def _latest_price(conn: duckdb.DuckDBPyConnection, ticker: str, as_of: date) -> Decimal | None:
    """Best-effort latest close for `ticker` on or before `as_of`.

    Uses `store.as_of()` (unlike `tax_lots`, `bars_daily` IS a proper append-only
    point-in-time snapshot table), so this respects the same no-look-ahead guarantee as
    every other price read in this codebase. Converts float -> str -> Decimal at the
    read boundary, never `Decimal(float)` directly.
    """
    from durable.data import store

    df = store.as_of(conn, "bars_daily", as_of, tickers=[ticker])
    if df.empty:
        return None
    row = df.sort_values("dt").iloc[-1]
    close = row["close"]
    if close is None or close != close:  # NaN guard (NaN != NaN)
        return None
    return Decimal(str(close))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: `python -m durable.tax.harvest --review [--as-of DATE]`."""
    from durable.config import ConfigError, load_config
    from durable.data import store
    from durable.tax.lots import TaxRates

    parser = argparse.ArgumentParser(
        prog="python -m durable.tax.harvest",
        description="Tax-loss-harvest review: candidates, wash-sale blocks, tax alpha.",
    )
    parser.add_argument("--review", action="store_true", help="Run the tax review.")
    parser.add_argument(
        "--as-of",
        default=None,
        help="Proposed sale/review date, YYYY-MM-DD. Defaults to today.",
    )
    args = parser.parse_args(argv)

    if not args.review:
        parser.print_help()
        return 1

    # The one and only wall-clock read in this module, and only when the user didn't
    # supply an explicit date.
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    tax_cfg = config.get("tax", {}) or {}
    tax_rates = TaxRates(
        short_term_rate=Decimal(str(tax_cfg.get("marginal_rate_ordinary", "0.22"))),
        long_term_rate=Decimal(str(tax_cfg.get("rate_long_term", "0.15"))),
    )
    min_loss_pct = Decimal(str(tax_cfg.get("harvest_min_loss_pct", "0.08")))
    min_loss_dollars = Decimal(str(tax_cfg.get("harvest_min_loss_dollars", "150")))

    db_path = (config.get("data", {}) or {}).get("duckdb_path", "data/durable.duckdb")
    conn = store.get_conn(PROJECT_ROOT / db_path)
    store.init_schema(conn)

    try:
        try:
            review = build_tax_review(
                conn,
                as_of=as_of,
                tax_rates=tax_rates,
                harvest_min_loss_pct=min_loss_pct,
                harvest_min_loss_dollars=min_loss_dollars,
                price_lookup=lambda t: _latest_price(conn, t, as_of),
                sector_lookup=None,
            )
        except NoTaxLotsError as exc:
            print(str(exc))
            return 1
    finally:
        conn.close()

    output_path = write_tax_review_report(review)
    print(
        f"Tax review as of {as_of.isoformat()}: {len(review.harvest_candidates)} candidate(s), "
        f"{len(review.wash_sale_blocked)} wash-sale block(s). Wrote {output_path}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
