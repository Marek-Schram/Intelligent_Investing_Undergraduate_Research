"""SEC EDGAR fundamentals ingestion. TICKET-002.

Data source: SEC EDGAR via edgartools (free, no key).
available_at logic: filing_date + 1 trading day (conservative proxy for
    acceptance_datetime + 1 trading day when exact acceptance is unavailable).
Spec section: docs/02 §3, SPEC §2.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd
from edgar import Company, get_company_facts, set_identity

if TYPE_CHECKING:
    import duckdb

from durable.data.store import write_snapshot

logger = logging.getLogger(__name__)

FUNDAMENTAL_CONCEPTS: dict[str, list[str]] = {
    "revenue": [
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:Revenues",
        "us-gaap:SalesRevenueNet",
        "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "net_income": [
        "us-gaap:NetIncomeLoss",
        "us-gaap:ProfitLoss",
    ],
    "operating_cash_flow": [
        "us-gaap:NetCashProvidedByUsedInOperatingActivities",
    ],
    "capex": [
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
        "us-gaap:PaymentsToAcquireProductiveAssets",
    ],
    "total_assets": [
        "us-gaap:Assets",
    ],
    "total_liabilities": [
        "us-gaap:Liabilities",
    ],
    "stockholders_equity": [
        "us-gaap:StockholdersEquity",
        "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "long_term_debt": [
        "us-gaap:LongTermDebt",
        "us-gaap:LongTermDebtNoncurrent",
    ],
    "short_term_debt": [
        "us-gaap:DebtCurrent",
        "us-gaap:ShortTermBorrowings",
    ],
    "cash_and_equivalents": [
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        "us-gaap:CashCashEquivalentsAndShortTermInvestments",
    ],
    "current_assets": [
        "us-gaap:AssetsCurrent",
    ],
    "current_liabilities": [
        "us-gaap:LiabilitiesCurrent",
    ],
    "gross_profit": [
        "us-gaap:GrossProfit",
    ],
    "cost_of_revenue": [
        "us-gaap:CostOfGoodsAndServicesSold",
        "us-gaap:CostOfRevenue",
        "us-gaap:CostOfGoodsSold",
    ],
    "ebit": [
        "us-gaap:OperatingIncomeLoss",
    ],
    "interest_expense": [
        "us-gaap:InterestExpense",
        "us-gaap:InterestExpenseDebt",
    ],
    "shares_outstanding": [
        "dei:EntityCommonStockSharesOutstanding",
        "us-gaap:CommonStockSharesOutstanding",
        "us-gaap:WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
        "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
    ],
    "accounts_receivable": [
        "us-gaap:AccountsReceivableNetCurrent",
        "us-gaap:AccountsReceivableNet",
    ],
    "inventory": [
        "us-gaap:InventoryNet",
    ],
    "goodwill": [
        "us-gaap:Goodwill",
    ],
    "dividends_paid": [
        "us-gaap:PaymentsOfDividends",
        "us-gaap:PaymentsOfDividendsCommonStock",
    ],
    "share_repurchases": [
        "us-gaap:PaymentsForRepurchaseOfCommonStock",
    ],
    "income_tax_expense": [
        "us-gaap:IncomeTaxExpenseBenefit",
    ],
    "depreciation_amortization": [
        "us-gaap:DepreciationDepletionAndAmortization",
        "us-gaap:DepreciationAndAmortization",
    ],
}

_FINANCIALS_REVENUE = [
    "us-gaap:InterestAndDividendIncomeOperating",
    "us-gaap:InterestIncomeExpenseNet",
    "us-gaap:Revenues",
]
_FINANCIALS_EXTRA = {
    "tier1_capital_ratio": ["us-gaap:Tier1CapitalToRiskWeightedAssets"],
    "combined_ratio": [],
}


def _next_trading_day(d: date) -> datetime:
    """Return the next trading day after date d as a datetime.

    Simplified: skip weekends. For production, use exchange_calendars.
    """
    next_d = d + timedelta(days=1)
    while next_d.weekday() >= 5:
        next_d += timedelta(days=1)
    return datetime(next_d.year, next_d.month, next_d.day, 9, 30, 0)


def fetch_fundamentals(
    ticker: str,
    identity: str,
    form_types: tuple[str, ...] = ("10-K", "10-Q"),
) -> pd.DataFrame:
    """Fetch fundamental facts from SEC EDGAR for a ticker.

    Returns a DataFrame with columns matching the facts_fundamentals schema:
    ticker, field, period_end, value, filed_at, available_at, accession, restated
    """
    set_identity(identity)

    company = Company(ticker)
    facts = get_company_facts(company.cik)
    all_facts = facts.get_all_facts()

    rows: list[dict] = []
    for fact in all_facts:
        if fact.form_type not in form_types:
            continue
        if fact.numeric_value is None:
            continue
        if fact.period_end is None:
            continue

        field_name = _resolve_field_name(fact.concept)
        if field_name is None:
            continue

        filed_at = datetime(
            fact.filing_date.year, fact.filing_date.month, fact.filing_date.day
        )
        available_at = _next_trading_day(fact.filing_date)

        rows.append(
            {
                "ticker": ticker,
                "field": field_name,
                "period_end": fact.period_end,
                "value": float(fact.numeric_value),
                "filed_at": filed_at,
                "available_at": available_at,
                "accession": fact.accession,
                "restated": fact.is_restated,
            }
        )

    if not rows:
        raise ValueError(f"No fundamental facts found for {ticker}")

    df = pd.DataFrame(rows)
    df = _deduplicate_facts(df)
    return df


def _resolve_field_name(concept: str) -> str | None:
    """Map a full concept (taxonomy:tag) to our canonical field name."""
    for field_name, candidates in FUNDAMENTAL_CONCEPTS.items():
        if concept in candidates:
            return field_name
    return None


def _deduplicate_facts(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the first (original) filing for each (ticker, field, period_end, accession).

    When a fact is restated, the original is kept with restated=False.
    The restated version is also kept but flagged.
    """
    df = df.sort_values(["ticker", "field", "period_end", "restated", "filed_at"])
    return df.drop_duplicates(
        subset=["ticker", "field", "period_end", "accession"], keep="first"
    ).reset_index(drop=True)


def ingest_fundamentals(
    conn: "duckdb.DuckDBPyConnection",
    ticker: str,
    identity: str,
    snapshot_id: str | None = None,
) -> str:
    """Fetch and write fundamentals for a ticker into the store.

    Returns the snapshot_id used.
    """
    df = fetch_fundamentals(ticker, identity)

    if snapshot_id is None:
        snapshot_id = f"sec-{ticker.lower()}-{date.today().isoformat()}"

    write_snapshot(conn, "facts_fundamentals", df, snapshot_id)
    logger.info(f"Ingested {len(df)} facts for {ticker} as {snapshot_id}")
    return snapshot_id


def get_quarterly_field(
    conn: "duckdb.DuckDBPyConnection",
    ticker: str,
    field: str,
    as_of_date: date | datetime,
) -> pd.DataFrame:
    """Convenience: get a single field's quarterly history, point-in-time filtered."""
    from durable.data.store import as_of

    df = as_of(conn, "facts_fundamentals", as_of_date, tickers=ticker)
    df = df[df["field"] == field].copy()
    df = df.sort_values("period_end").drop_duplicates(subset=["period_end"], keep="last")
    return df.reset_index(drop=True)
