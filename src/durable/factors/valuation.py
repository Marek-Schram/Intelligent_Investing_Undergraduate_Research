"""Valuation score including reverse-DCF. SPEC section 3. TICKET-007.

Data source: facts_fundamentals + bars_daily (via pre-filtered DataFrames).
available_at logic: receives only PIT-filtered data from the caller.
Spec section: SPEC §3.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq


def implied_growth(
    ev: float,
    fcf_0: float,
    wacc: float,
    terminal_growth: float = 0.025,
    years: int = 10,
) -> float:
    """Solve for the growth rate the current price implies. SPEC §3.1.

    Uses Brent's method on [-0.20, 0.50].
    Returns NaN on non-convergence. Never returns 0.0 for a failed solve.
    """
    if ev <= 0 or fcf_0 <= 0 or wacc <= terminal_growth:
        return float("nan")

    def _dcf_error(g: float) -> float:
        pv_fcf = sum(fcf_0 * (1 + g) ** t / (1 + wacc) ** t for t in range(1, years + 1))
        fcf_terminal = fcf_0 * (1 + g) ** years
        tv = fcf_terminal * (1 + terminal_growth) / (wacc - terminal_growth)
        pv_tv = tv / (1 + wacc) ** years
        return pv_fcf + pv_tv - ev

    try:
        result = brentq(_dcf_error, -0.20, 0.50, xtol=1e-6, maxiter=100)
        return float(result)
    except (ValueError, RuntimeError):
        return float("nan")


def reverse_dcf_gap(
    ev: float,
    fcf_0: float,
    fcf_5y_cagr: float,
    wacc: float,
    terminal_growth: float = 0.025,
) -> float | None:
    """Gap between delivered growth and implied growth. SPEC §3.1.

    Positive gap = market demands less growth than the company has delivered.
    Returns None if implied_growth fails to converge.
    """
    g_implied = implied_growth(ev, fcf_0, wacc, terminal_growth)
    if np.isnan(g_implied):
        return None
    return fcf_5y_cagr - g_implied


def ev_ebit_score(ev_ebit: float, sector_ev_ebits: list[float] | None = None) -> float:
    """EV/EBIT inverted, sector percentile (0-10). SPEC §3."""
    if ev_ebit <= 0:
        return 0.0

    if sector_ev_ebits and len(sector_ev_ebits) > 1:
        # Lower EV/EBIT is better (inverted)
        percentile = sum(1 for x in sector_ev_ebits if x > ev_ebit) / len(sector_ev_ebits)
        return percentile * 10.0

    # Absolute scale fallback
    if ev_ebit <= 10:
        return 10.0
    elif ev_ebit >= 40:
        return 0.0
    return 10.0 * (40 - ev_ebit) / 30.0


def fcf_yield_score(fcf_yield: float, sector_yields: list[float] | None = None) -> float:
    """FCF/EV yield score (0-10). SPEC §3."""
    if sector_yields and len(sector_yields) > 1:
        percentile = sum(1 for x in sector_yields if x < fcf_yield) / len(sector_yields)
        return percentile * 10.0

    # Absolute fallback
    if fcf_yield >= 0.10:
        return 10.0
    elif fcf_yield <= 0.0:
        return 0.0
    return fcf_yield / 0.10 * 10.0


def shareholder_yield_score(
    dividend_yield: float, buyback_yield: float, debt_paydown_yield: float
) -> float:
    """Shareholder yield score (0-5). SPEC §3."""
    total_yield = dividend_yield + buyback_yield + debt_paydown_yield
    if total_yield >= 0.08:
        return 5.0
    elif total_yield <= 0.0:
        return 0.0
    return total_yield / 0.08 * 5.0


def reverse_dcf_score(gap: float | None, sector_gaps: list[float] | None = None) -> float:
    """Reverse-DCF implied growth gap score (0-10). SPEC §3.1."""
    if gap is None:
        return 0.0

    if sector_gaps and len(sector_gaps) > 1:
        percentile = sum(1 for x in sector_gaps if x < gap) / len(sector_gaps)
        return percentile * 10.0

    # Absolute fallback: positive gap is good
    if gap >= 0.10:
        return 10.0
    elif gap <= -0.10:
        return 0.0
    return (gap + 0.10) / 0.20 * 10.0


def valuation_score(
    ev: float,
    ebit: float,
    fcf: float,
    fcf_5y_cagr: float,
    market_cap: float,
    dividend_yield: float,
    buyback_yield: float,
    debt_paydown_yield: float,
    risk_free_rate: float,
    fcf_5y_median: float,
    sector_ev_ebits: list[float] | None = None,
    sector_fcf_yields: list[float] | None = None,
    sector_gaps: list[float] | None = None,
    erp: float = 0.05,
    wacc_floor: float = 0.08,
    terminal_growth: float = 0.025,
    max_ev_ebit: float = 45.0,
    max_implied_growth: float = 0.25,
) -> tuple[float | None, dict]:
    """Complete valuation score (0-35). SPEC §3.

    Applies hard floors (§3.2) BEFORE scoring. Returns None if excluded.
    Returns (score, breakdown) or (None, breakdown) if excluded.
    """
    breakdown: dict = {}

    # Hard floors (SPEC §3.2)
    if ebit <= 0:
        breakdown["excluded"] = "ebit_negative"
        return None, breakdown

    ev_ebit_ratio = ev / ebit
    if ev_ebit_ratio > max_ev_ebit:
        breakdown["excluded"] = f"ev_ebit_{ev_ebit_ratio:.1f}_exceeds_{max_ev_ebit}"
        return None, breakdown

    if fcf_5y_median <= 0:
        breakdown["excluded"] = "fcf_5y_median_negative"
        return None, breakdown

    # WACC calculation
    wacc = max(risk_free_rate + erp, wacc_floor)
    breakdown["wacc"] = round(wacc, 4)

    # Implied growth check
    g_implied = implied_growth(ev, fcf, wacc, terminal_growth)
    breakdown["implied_growth"] = round(g_implied, 4) if not np.isnan(g_implied) else None

    if not np.isnan(g_implied) and g_implied > max_implied_growth:
        breakdown["excluded"] = f"implied_growth_{g_implied:.3f}_exceeds_{max_implied_growth}"
        return None, breakdown

    # Component scores
    ev_ebit_pts = ev_ebit_score(ev_ebit_ratio, sector_ev_ebits)
    fcf_yield = fcf / ev if ev > 0 else 0.0
    fcf_pts = fcf_yield_score(fcf_yield, sector_fcf_yields)
    sh_yield_pts = shareholder_yield_score(dividend_yield, buyback_yield, debt_paydown_yield)

    gap = reverse_dcf_gap(ev, fcf, fcf_5y_cagr, wacc, terminal_growth)
    rdcf_pts = reverse_dcf_score(gap, sector_gaps)

    total = ev_ebit_pts + fcf_pts + sh_yield_pts + rdcf_pts
    total = min(35.0, max(0.0, total))

    breakdown.update(
        {
            "ev_ebit_ratio": round(ev_ebit_ratio, 2),
            "ev_ebit_points": round(ev_ebit_pts, 2),
            "fcf_yield": round(fcf_yield, 4),
            "fcf_yield_points": round(fcf_pts, 2),
            "shareholder_yield_points": round(sh_yield_pts, 2),
            "reverse_dcf_gap": round(gap, 4) if gap is not None else None,
            "reverse_dcf_points": round(rdcf_pts, 2),
            "total": round(total, 2),
        }
    )

    return total, breakdown
