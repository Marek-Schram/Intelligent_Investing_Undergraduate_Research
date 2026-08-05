"""Portfolio reconciliation. TICKET-016.

Compares internal position records against broker account state.
A mismatch blocks submit (creates RECONCILE_FAILED file).

PURE FUNCTIONS ONLY (except file I/O for the RECONCILE_FAILED flag).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


class ReconciliationMismatchError(RuntimeError):
    """Positions do not reconcile between internal and broker."""


@dataclass
class ReconciliationResult:
    """Result of a reconciliation check."""

    matches: bool
    mismatches: list[dict]
    internal_only: list[str]  # Tickers we have but broker doesn't
    broker_only: list[str]  # Tickers broker has but we don't
    share_diffs: list[dict]  # Tickers with different share counts


def reconcile(
    internal_positions: pd.DataFrame,
    broker_positions: pd.DataFrame,
    tolerance: float = 0.001,
) -> ReconciliationResult:
    """Compare internal vs broker positions.

    Parameters
    ----------
    internal_positions : DataFrame with [ticker, shares]
    broker_positions : DataFrame with [ticker, shares]
    tolerance : acceptable fractional share difference (default 0.001)

    Returns ReconciliationResult.
    """
    mismatches = []
    share_diffs = []

    internal_tickers = set(
        internal_positions["ticker"].tolist()
    ) if not internal_positions.empty else set()
    broker_tickers = set(
        broker_positions["ticker"].tolist()
    ) if not broker_positions.empty else set()

    internal_only = sorted(internal_tickers - broker_tickers)
    broker_only = sorted(broker_tickers - internal_tickers)

    for ticker in internal_only:
        mismatches.append({"ticker": ticker, "type": "internal_only"})
    for ticker in broker_only:
        mismatches.append({"ticker": ticker, "type": "broker_only"})

    # Check share counts for tickers in both
    common = internal_tickers & broker_tickers
    for ticker in sorted(common):
        int_shares = float(
            internal_positions[internal_positions["ticker"] == ticker]["shares"].iloc[0]
        )
        brk_shares = float(
            broker_positions[broker_positions["ticker"] == ticker]["shares"].iloc[0]
        )
        diff = abs(int_shares - brk_shares)
        if diff > tolerance:
            share_diffs.append({
                "ticker": ticker,
                "internal_shares": int_shares,
                "broker_shares": brk_shares,
                "diff": diff,
            })
            mismatches.append({"ticker": ticker, "type": "share_mismatch", "diff": diff})

    matches = len(mismatches) == 0

    return ReconciliationResult(
        matches=matches,
        mismatches=mismatches,
        internal_only=internal_only,
        broker_only=broker_only,
        share_diffs=share_diffs,
    )


def assert_reconciled(
    internal_positions: pd.DataFrame,
    broker_positions: pd.DataFrame,
    reconcile_failed_path: str | Path = "RECONCILE_FAILED",
    tolerance: float = 0.001,
) -> ReconciliationResult:
    """Reconcile and block submit on mismatch.

    Creates RECONCILE_FAILED file if mismatch detected.
    Raises ReconciliationMismatchError on mismatch.
    """
    result = reconcile(internal_positions, broker_positions, tolerance)

    if not result.matches:
        Path(reconcile_failed_path).write_text(
            f"Mismatch detected: {len(result.mismatches)} issues\n"
            + "\n".join(str(m) for m in result.mismatches)
        )
        raise ReconciliationMismatchError(
            f"Reconciliation failed: {len(result.mismatches)} mismatches. "
            f"RECONCILE_FAILED written. Resolve before trading."
        )

    # Remove stale RECONCILE_FAILED if reconciliation passes
    p = Path(reconcile_failed_path)
    if p.exists():
        p.unlink()

    return result
