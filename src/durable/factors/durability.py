"""Durability score. SPEC section 2. TICKET-006.

Data source: facts_fundamentals (via pre-filtered DataFrame, never direct DB).
available_at logic: receives only PIT-filtered data from the caller.
Spec section: SPEC §2.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def piotroski_f_score(facts: pd.DataFrame) -> int:
    """Piotroski F-Score (0-9). SPEC §2.1.

    Nine binary signals of financial strength.
    """

    def _get(field: str, offset: int = 0) -> float | None:
        series = facts[facts["field"] == field].sort_values("period_end")
        if len(series) <= offset:
            return None
        return series.iloc[-(1 + offset)]["value"]

    score = 0

    ni = _get("net_income")
    cfo = _get("operating_cash_flow")
    total_assets = _get("total_assets")
    total_assets_prev = _get("total_assets", 1)

    # 1. Net income > 0
    if ni is not None and ni > 0:
        score += 1

    # 2. CFO > 0
    if cfo is not None and cfo > 0:
        score += 1

    # 3. ROA improving (NI/TA this year > last year)
    if ni is not None and total_assets and total_assets_prev:
        ni_prev = _get("net_income", 1)
        if ni_prev is not None and total_assets > 0 and total_assets_prev > 0:
            roa_curr = ni / total_assets
            roa_prev = ni_prev / total_assets_prev
            if roa_curr > roa_prev:
                score += 1

    # 4. CFO > Net Income (accrual quality)
    if cfo is not None and ni is not None and cfo > ni:
        score += 1

    # 5. Long-term debt / assets decreasing
    ltd = _get("long_term_debt")
    ltd_prev = _get("long_term_debt", 1)
    if ltd is not None and ltd_prev is not None and total_assets and total_assets_prev:
        if total_assets > 0 and total_assets_prev > 0:
            if (ltd / total_assets) < (ltd_prev / total_assets_prev):
                score += 1

    # 6. Current ratio improving
    ca = _get("current_assets")
    cl = _get("current_liabilities")
    ca_prev = _get("current_assets", 1)
    cl_prev = _get("current_liabilities", 1)
    if ca and cl and ca_prev and cl_prev and cl > 0 and cl_prev > 0:
        if (ca / cl) > (ca_prev / cl_prev):
            score += 1

    # 7. Shares not diluted (>1% tolerance)
    shares = _get("shares_outstanding")
    shares_prev = _get("shares_outstanding", 1)
    if shares is not None and shares_prev is not None and shares_prev > 0:
        if shares <= shares_prev * 1.01:
            score += 1

    # 8. Gross margin improving
    gp = _get("gross_profit")
    rev = _get("revenue")
    gp_prev = _get("gross_profit", 1)
    rev_prev = _get("revenue", 1)
    if gp and rev and gp_prev and rev_prev and rev > 0 and rev_prev > 0:
        if (gp / rev) > (gp_prev / rev_prev):
            score += 1

    # 9. Asset turnover improving
    if rev and total_assets and total_assets_prev:
        rev_prev_val = _get("revenue", 1)
        if rev_prev_val and total_assets > 0 and total_assets_prev > 0:
            if (rev / total_assets) > (rev_prev_val / total_assets_prev):
                score += 1

    return score


def piotroski_points(f_score: int) -> float:
    """Convert F-Score (0-9) to points (0-14). SPEC §2.1."""
    return f_score / 9.0 * 14.0


def roic_points(facts: pd.DataFrame, sector_roics: pd.Series | None = None) -> float:
    """ROIC consistency score (0-14). SPEC §2.2.

    5-year median ROIC, sector-percentile ranked. Median not latest.
    """
    ebit_series = facts[facts["field"] == "ebit"].sort_values("period_end")
    equity_series = facts[facts["field"] == "stockholders_equity"].sort_values("period_end")
    debt_series = facts[facts["field"] == "long_term_debt"].sort_values("period_end")
    cash_series = facts[facts["field"] == "cash_and_equivalents"].sort_values("period_end")

    if len(ebit_series) < 5:
        return 0.0

    roics = []
    for i in range(min(5, len(ebit_series))):
        idx = -(i + 1)
        ebit = ebit_series.iloc[idx]["value"]
        period = ebit_series.iloc[idx]["period_end"]

        equity = _get_nearest(equity_series, period)
        debt = _get_nearest(debt_series, period)
        cash = _get_nearest(cash_series, period)

        if equity is None or debt is None:
            continue

        cash_val = cash if cash is not None else 0.0
        tax_rate = 0.21
        nopat = ebit * (1 - tax_rate)
        inv_capital = debt + equity - cash_val

        if inv_capital <= 0:
            continue

        roics.append(nopat / inv_capital)

    if not roics:
        return 0.0

    median_roic = float(np.median(roics))

    if sector_roics is not None and len(sector_roics) > 0:
        percentile = (sector_roics < median_roic).mean()
        return percentile * 14.0
    else:
        # Without sector context, use absolute thresholds
        if median_roic >= 0.25:
            return 14.0
        elif median_roic <= 0.0:
            return 0.0
        else:
            return (median_roic / 0.25) * 14.0


def cash_and_safety_points(facts: pd.DataFrame) -> float:
    """Cash & balance sheet score (0-12). SPEC §2.3.

    Three sub-scores of 4 each: FCF conversion, net debt/EBITDA, interest coverage.
    """
    # FCF conversion: 5y median FCF/NI, clipped [0, 2]
    ni_series = facts[facts["field"] == "net_income"].sort_values("period_end").tail(5)
    cfo_series = facts[facts["field"] == "operating_cash_flow"].sort_values("period_end").tail(5)
    capex_series = facts[facts["field"] == "capex"].sort_values("period_end").tail(5)

    fcf_conv_score = 0.0
    if len(ni_series) >= 3 and len(cfo_series) >= 3:
        fcf_values = []
        for i in range(min(len(cfo_series), len(capex_series))):
            cfo = cfo_series.iloc[i]["value"]
            capex = capex_series.iloc[i]["value"] if i < len(capex_series) else 0
            fcf_values.append(cfo - abs(capex))

        ni_values = ni_series["value"].tolist()[: len(fcf_values)]
        ratios = []
        for fcf, ni in zip(fcf_values, ni_values):
            if ni != 0:
                ratios.append(np.clip(fcf / ni, 0, 2))

        if ratios:
            median_conv = float(np.median(ratios))
            fcf_conv_score = (median_conv / 2.0) * 4.0

    # Net debt/EBITDA
    debt = _latest_value(facts, "long_term_debt")
    cash = _latest_value(facts, "cash_and_equivalents")
    ebit = _latest_value(facts, "ebit")
    da = _latest_value(facts, "depreciation_amortization")

    debt_score = 0.0
    if debt is not None and cash is not None and ebit is not None:
        ebitda = ebit + (da if da is not None else 0)
        if ebitda > 0:
            net_debt_ebitda = (debt - (cash or 0)) / ebitda
            if net_debt_ebitda <= 1.0:
                debt_score = 4.0
            elif net_debt_ebitda >= 4.0:
                debt_score = 0.0
            else:
                debt_score = 4.0 * (1 - (net_debt_ebitda - 1.0) / 3.0)

    # Interest coverage
    interest = _latest_value(facts, "interest_expense")
    coverage_score = 0.0
    if ebit is not None and interest is not None and interest > 0:
        coverage = ebit / interest
        if coverage >= 10:
            coverage_score = 4.0
        elif coverage <= 2:
            coverage_score = 0.0
        else:
            coverage_score = 4.0 * (coverage - 2) / 8.0

    return fcf_conv_score + debt_score + coverage_score


def growth_durability_points(facts: pd.DataFrame, sector_gm_rank: float | None = None) -> float:
    """Growth durability score (0-10). SPEC §2.4.

    Stability beats fast. Revenue growth stability + gross margin trend + share count.
    """
    # Revenue growth stability: 4 × (1 - normalized_stdev)
    rev_series = facts[facts["field"] == "revenue"].sort_values("period_end").tail(8)
    stability_score = 0.0
    if len(rev_series) >= 4:
        values = rev_series["value"].values
        growth_rates = np.diff(values) / values[:-1]
        growth_rates = growth_rates[np.isfinite(growth_rates)]
        if len(growth_rates) >= 3:
            stdev = np.std(growth_rates)
            mean_abs = max(abs(np.mean(growth_rates)), 0.01)
            norm_stdev = np.clip(stdev / mean_abs, 0.05, 0.95)
            stability_score = 4.0 * (1 - norm_stdev)

    # Gross margin trend, sector-ranked (max 3)
    gm_score = 0.0
    if sector_gm_rank is not None:
        gm_score = sector_gm_rank * 3.0
    else:
        gp_series = facts[facts["field"] == "gross_profit"].sort_values("period_end").tail(5)
        rev_for_gm = facts[facts["field"] == "revenue"].sort_values("period_end").tail(5)
        if len(gp_series) >= 3 and len(rev_for_gm) >= 3:
            margins = []
            for i in range(min(len(gp_series), len(rev_for_gm))):
                gp = gp_series.iloc[i]["value"]
                r = rev_for_gm.iloc[i]["value"]
                if r > 0:
                    margins.append(gp / r)
            if len(margins) >= 3 and margins[-1] > margins[0]:
                gm_score = 2.0  # Improving trend

    # Share count change (3 if shrinking, 0 if diluting >3%/yr)
    shares_series = facts[facts["field"] == "shares_outstanding"].sort_values("period_end")
    share_score = 0.0
    if len(shares_series) >= 2:
        first = shares_series.iloc[0]["value"]
        last = shares_series.iloc[-1]["value"]
        years = max(
            (shares_series.iloc[-1]["period_end"] - shares_series.iloc[0]["period_end"]).days
            / 365.25,
            1,
        )
        annual_change = (last / first) ** (1 / years) - 1

        if annual_change < -0.005:
            share_score = 3.0
        elif annual_change > 0.03:
            share_score = 0.0
        else:
            share_score = 3.0 * (1 - annual_change / 0.03)
            share_score = max(0.0, min(3.0, share_score))

    return stability_score + gm_score + share_score


def red_flags(
    facts: pd.DataFrame,
    distance_to_default: float | None = None,
    short_interest_pct: float | None = None,
) -> tuple[float, list[str], bool]:
    """Red flags check (0 to -18, or excluded). SPEC §2.5.

    Returns (penalty, flag_list, is_excluded).
    Three triggers => excluded regardless of individual severity.
    """
    penalty = 0.0
    flags: list[str] = []
    excludes: list[str] = []

    # Accrual bloat: (NI - CFO) / assets > 10%
    ni = _latest_value(facts, "net_income")
    cfo = _latest_value(facts, "operating_cash_flow")
    assets = _latest_value(facts, "total_assets")
    if ni is not None and cfo is not None and assets and assets > 0:
        accrual = (ni - cfo) / assets
        if accrual > 0.10:
            penalty -= 5
            flags.append("accrual_bloat")

    # Receivables blowout: AR growth > 1.5x revenue growth, 2 yrs
    ar_series = facts[facts["field"] == "accounts_receivable"].sort_values("period_end")
    rev_series = facts[facts["field"] == "revenue"].sort_values("period_end")
    if len(ar_series) >= 3 and len(rev_series) >= 3:
        ar_growth = (
            (ar_series.iloc[-1]["value"] / ar_series.iloc[-3]["value"]) - 1
            if ar_series.iloc[-3]["value"] > 0
            else 0
        )
        rev_growth = (
            (rev_series.iloc[-1]["value"] / rev_series.iloc[-3]["value"]) - 1
            if rev_series.iloc[-3]["value"] > 0
            else 0
        )
        if rev_growth > 0 and ar_growth > 1.5 * rev_growth:
            penalty -= 4
            flags.append("receivables_blowout")

    # Inventory blowout
    inv_series = facts[facts["field"] == "inventory"].sort_values("period_end")
    if len(inv_series) >= 3 and len(rev_series) >= 3:
        inv_growth = (
            (inv_series.iloc[-1]["value"] / inv_series.iloc[-3]["value"]) - 1
            if inv_series.iloc[-3]["value"] > 0
            else 0
        )
        if rev_growth > 0 and inv_growth > 1.5 * rev_growth:
            penalty -= 3
            flags.append("inventory_blowout")

    # Goodwill heavy: goodwill/assets > 40%
    gw = _latest_value(facts, "goodwill")
    if gw is not None and assets and assets > 0:
        if gw / assets > 0.40:
            penalty -= 3
            flags.append("goodwill_heavy")

    # Serial dilution: shares +>5%/yr for 3 yrs
    shares_series = facts[facts["field"] == "shares_outstanding"].sort_values("period_end")
    if len(shares_series) >= 4:
        diluting_years = 0
        for i in range(1, min(4, len(shares_series))):
            prev = shares_series.iloc[-(i + 1)]["value"]
            curr = shares_series.iloc[-i]["value"]
            if prev > 0 and (curr / prev - 1) > 0.05:
                diluting_years += 1
        if diluting_years >= 3:
            penalty -= 5
            flags.append("serial_dilution")

    # Altman Z < 1.8
    z = _altman_z(facts)
    if z is not None and z < 1.8:
        penalty -= 5
        flags.append("altman_z_distress")

    # Distance-to-default
    if distance_to_default is not None:
        if distance_to_default < 1.0:
            excludes.append("distance_to_default_critical")
        elif distance_to_default < 2.0:
            penalty -= 5
            flags.append("distance_to_default_warning")

    # Short interest
    if short_interest_pct is not None:
        if short_interest_pct > 0.25:
            excludes.append("short_interest_extreme")
        elif short_interest_pct > 0.15:
            penalty -= 3
            flags.append("short_interest_elevated")

    # Three flags => excluded
    is_excluded = len(excludes) > 0 or len(flags) >= 3
    return penalty, flags + excludes, is_excluded


def durability_score(
    facts: pd.DataFrame,
    sector_roics: pd.Series | None = None,
    sector_gm_rank: float | None = None,
    distance_to_default: float | None = None,
    short_interest_pct: float | None = None,
    is_financial: bool = False,
) -> tuple[float, dict]:
    """Compute complete durability score (0-50). SPEC §2.

    Routes financials (SIC 6000-6499) to variant §2.6.
    Returns (score, breakdown_dict).
    """
    f_score = piotroski_f_score(facts)
    f_points = piotroski_points(f_score)

    if is_financial:
        roic_pts = _financial_roic_points(facts, sector_roics)
        cash_pts = _financial_safety_points(facts)
    else:
        roic_pts = roic_points(facts, sector_roics)
        cash_pts = cash_and_safety_points(facts)

    growth_pts = growth_durability_points(facts, sector_gm_rank)
    penalty, flags, excluded = red_flags(facts, distance_to_default, short_interest_pct)

    raw_score = f_points + roic_pts + cash_pts + growth_pts + penalty
    final_score = max(0.0, min(50.0, raw_score))

    breakdown = {
        "piotroski_f_score": f_score,
        "piotroski_points": round(f_points, 2),
        "roic_points": round(roic_pts, 2),
        "cash_safety_points": round(cash_pts, 2),
        "growth_durability_points": round(growth_pts, 2),
        "red_flag_penalty": penalty,
        "red_flags": flags,
        "excluded": excluded,
        "raw_score": round(raw_score, 2),
        "final_score": round(final_score, 2),
        "is_financial": is_financial,
    }

    return final_score, breakdown


def _financial_roic_points(facts: pd.DataFrame, sector_roics: pd.Series | None = None) -> float:
    """Financials variant: ROE instead of ROIC. SPEC §2.6."""
    ni_series = facts[facts["field"] == "net_income"].sort_values("period_end").tail(5)
    eq_series = facts[facts["field"] == "stockholders_equity"].sort_values("period_end").tail(5)

    if len(ni_series) < 3 or len(eq_series) < 3:
        return 0.0

    roes = []
    for i in range(min(len(ni_series), len(eq_series))):
        ni = ni_series.iloc[i]["value"]
        eq = eq_series.iloc[i]["value"]
        if eq > 0:
            roes.append(ni / eq)

    if not roes:
        return 0.0

    median_roe = float(np.median(roes))

    if sector_roics is not None and len(sector_roics) > 0:
        percentile = (sector_roics < median_roe).mean()
        return percentile * 14.0

    if median_roe >= 0.15:
        return 14.0
    elif median_roe <= 0.0:
        return 0.0
    return (median_roe / 0.15) * 14.0


def _financial_safety_points(facts: pd.DataFrame) -> float:
    """Financials variant: no FCF conversion, redistribute to ROE. SPEC §2.6."""
    # Simplified: just use interest coverage and debt ratio
    return cash_and_safety_points(facts) * (12.0 / 8.0)


def _latest_value(facts: pd.DataFrame, field: str) -> float | None:
    """Get the most recent value for a field."""
    series = facts[facts["field"] == field].sort_values("period_end")
    if series.empty:
        return None
    return series.iloc[-1]["value"]


def _get_nearest(series: pd.DataFrame, target_period) -> float | None:
    """Get value nearest to a target period."""
    if series.empty:
        return None
    idx = (series["period_end"] - target_period).abs().idxmin()
    return series.loc[idx, "value"]


def _altman_z(facts: pd.DataFrame) -> float | None:
    """Calculate Altman Z-Score."""
    assets = _latest_value(facts, "total_assets")
    if not assets or assets <= 0:
        return None

    ca = _latest_value(facts, "current_assets") or 0
    cl = _latest_value(facts, "current_liabilities") or 0
    retained = _latest_value(facts, "stockholders_equity") or 0
    ebit = _latest_value(facts, "ebit") or 0
    equity = _latest_value(facts, "stockholders_equity") or 0
    liabilities = _latest_value(facts, "total_liabilities") or 0
    revenue = _latest_value(facts, "revenue") or 0

    working_capital = ca - cl

    if liabilities <= 0:
        return None

    z = (
        1.2 * (working_capital / assets)
        + 1.4 * (retained / assets)
        + 3.3 * (ebit / assets)
        + 0.6 * (equity / liabilities)
        + 1.0 * (revenue / assets)
    )
    return z
