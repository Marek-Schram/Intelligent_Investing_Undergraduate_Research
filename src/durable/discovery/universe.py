"""Sleeve E universe. docs/08 section 3. TICKET-024.

LOOSER than Sleeve C on size, TIGHTER on market structure. That asymmetry is the safety design.
Constants below are NOT config-readable, by design (.claude/hooks/guard_write.sh blocks edits).

MIN_MARKET_CAP=300e6 · MAX_MARKET_CAP=3e9 · MIN_PRICE=5.00 · MIN_ADV_60D=1.5e6
MIN_FLOAT_VALUE=150e6 · MIN_FLOAT_SHARES=8e6 · MIN_QUARTERS_FILED=12
MIN_MONTHS_SINCE_IPO=36 · MIN_PROFITABLE_YEARS_OF_4=3
MAX_SHORT_INTEREST_PCT_FLOAT=0.10 · MIN_DISTANCE_TO_DEFAULT=1.5
ALLOWED_EXCHANGES = {NYSE, NASDAQ, NYSEAMERICAN}

build_universe(conn, as_of) -> DataFrame with eligible/reason.
    Missing data => EXCLUDED with reason='insufficient_data'. Never impute. Missing data in a
    low-coverage name is itself informative.
check_auto_disqualifiers(conn, ticker, as_of) -> list[str]. Non-empty => permanent exclusion.
"""

from __future__ import annotations
