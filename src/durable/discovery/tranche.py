"""Staged entry. docs/08 section 6. TICKET-029.

"Little amounts while they're cheap" -- gated on BUSINESS CONFIRMATION, never price decline.

TRANCHE_FRACTIONS=(0.40,0.30,0.30) · MIN_DAYS_BETWEEN_TRANCHES=90
MAX_POSITION_PCT_TOTAL=0.0025 · MAX_SLEEVE_E_PCT_TOTAL=0.02 · MAX_POSITIONS=8
CANCEL_SCORE_THRESHOLD=60 · MAX_PCT_OF_ADV=0.01

next_tranche_gate(state, facts, as_of) -> (eligible, explanation)
    T2 requires TWO ADDITIONAL QUARTERS FILED with durability held >= 30. NOT "price fell 20%".
    Adding because it fell is averaging down into a deteriorating thesis; no config flag enables it.
size_tranche(state, total_portfolio_value, adv_60d) -> the MINIMUM of all four constraints.
    Below the broker's fractional minimum => 0.0 with a logged reason. Never round up.
exit_rules(state, facts, flags, as_of) -> (should_exit, rule). E1 GRADUATION is the SUCCESS
    case and is reported as such. E4 (manipulation) exits regardless of P&L.
"""

from __future__ import annotations
