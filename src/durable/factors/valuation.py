"""Valuation incl. reverse-DCF. SPEC section 3. TICKET-007.

implied_growth(ev, fcf_0, wacc, terminal_growth=0.025, years=10) -> float
    Solve for the growth the CURRENT PRICE already implies. Brent's method on [-0.20, 0.50].
    Returns NaN on non-convergence. DO NOT return 0.0 -- a failure to converge and a
    zero-growth expectation are completely different claims.
valuation_score(facts, prices, sectors, risk_free_rate, as_of) -> 0-35.
    Applies the SPEC 3.2 hard floors BEFORE scoring.
"""

from __future__ import annotations
