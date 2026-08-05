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

Data source: fundamentals, prices, corporate actions from the PIT store.
available_at logic: all data filtered via store.as_of(as_of) upstream.
Spec section: docs/08 §3.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass


# Safety constants — NOT config-readable by design
MIN_MARKET_CAP = 300e6
MAX_MARKET_CAP = 3e9
MIN_PRICE = 5.00
MIN_ADV_60D = 1.5e6
MIN_FLOAT_VALUE = 150e6
MIN_FLOAT_SHARES = 8e6
MIN_QUARTERS_FILED = 12
MIN_MONTHS_SINCE_IPO = 36
MIN_PROFITABLE_YEARS_OF_4 = 3
MAX_SHORT_INTEREST_PCT_FLOAT = 0.10
MIN_DISTANCE_TO_DEFAULT = 1.5
ALLOWED_EXCHANGES = {"NYSE", "NASDAQ", "NYSEAMERICAN"}


@dataclass
class ExclusionReason:
    """Why a ticker was excluded from Sleeve E."""

    ticker: str
    reason: str
    value: float | str | None = None


def check_exchange(exchange: str | None) -> str | None:
    """Reject OTC/Pink/Expert. Only NYSE/NASDAQ/NYSEAMERICAN allowed."""
    if exchange is None:
        return "missing_exchange"
    if exchange.upper() not in ALLOWED_EXCHANGES:
        return f"exchange_{exchange}_not_allowed"
    return None


def check_price(price: float | None) -> str | None:
    """Price >= $5.00."""
    if price is None:
        return "missing_price"
    if price < MIN_PRICE:
        return f"price_{price:.2f}_below_{MIN_PRICE}"
    return None


def check_market_cap(market_cap: float | None) -> str | None:
    """Cap $300M–$3.0B."""
    if market_cap is None:
        return "missing_market_cap"
    if market_cap < MIN_MARKET_CAP:
        return f"market_cap_below_{MIN_MARKET_CAP/1e6:.0f}M"
    if market_cap > MAX_MARKET_CAP:
        return f"market_cap_above_{MAX_MARKET_CAP/1e9:.0f}B"
    return None


def check_adv(adv_60d: float | None) -> str | None:
    """ADV >= $1.5M."""
    if adv_60d is None:
        return "missing_adv"
    if adv_60d < MIN_ADV_60D:
        return f"adv_{adv_60d/1e6:.2f}M_below_{MIN_ADV_60D/1e6:.1f}M"
    return None


def check_float(float_value: float | None, float_shares: float | None) -> str | None:
    """Float >= $150M and >= 8M shares."""
    if float_value is None or float_shares is None:
        return "missing_float_data"
    if float_value < MIN_FLOAT_VALUE:
        return f"float_value_below_{MIN_FLOAT_VALUE/1e6:.0f}M"
    if float_shares < MIN_FLOAT_SHARES:
        return f"float_shares_below_{MIN_FLOAT_SHARES/1e6:.0f}M"
    return None


def check_history(quarters_filed: int | None, months_since_ipo: int | None) -> str | None:
    """>=12 quarters filed, >= 36 months since IPO."""
    if quarters_filed is None:
        return "missing_quarters_filed"
    if quarters_filed < MIN_QUARTERS_FILED:
        return f"quarters_filed_{quarters_filed}_below_{MIN_QUARTERS_FILED}"
    if months_since_ipo is None:
        return "missing_ipo_date"
    if months_since_ipo < MIN_MONTHS_SINCE_IPO:
        return f"months_since_ipo_{months_since_ipo}_below_{MIN_MONTHS_SINCE_IPO}"
    return None


def check_profitability(profitable_years: int | None) -> str | None:
    """Profitable in >= 3 of last 4 years."""
    if profitable_years is None:
        return "missing_profitability_data"
    if profitable_years < MIN_PROFITABLE_YEARS_OF_4:
        return f"profitable_years_{profitable_years}_below_{MIN_PROFITABLE_YEARS_OF_4}"
    return None


def check_short_interest(si_pct_float: float | None) -> str | None:
    """Short interest > 10% of float => exclusion."""
    if si_pct_float is None:
        return None  # Missing SI is not exclusionary (absence is not a signal)
    if si_pct_float > MAX_SHORT_INTEREST_PCT_FLOAT:
        return f"short_interest_{si_pct_float:.1%}_exceeds_{MAX_SHORT_INTEREST_PCT_FLOAT:.0%}"
    return None


def check_distance_to_default(dd: float | None) -> str | None:
    """Distance-to-default < 1.5 => exclusion."""
    if dd is None:
        return None  # Missing DD not exclusionary
    if dd < MIN_DISTANCE_TO_DEFAULT:
        return f"distance_to_default_{dd:.2f}_below_{MIN_DISTANCE_TO_DEFAULT}"
    return None


AUTO_DISQUALIFIERS = [
    "reverse_split_within_24m",
    "multiple_name_changes_5y",
    "reverse_merger_within_5y",
    "sec_trading_suspension",
    "repeated_late_filings",
    "auditor_resignation_24m",
    "restatement_within_24m",
    "share_dilution_25pct_1y",
    "detected_paid_promotion",
    "otc_history_within_24m",
    "unsolicited_source",
]


def check_auto_disqualifiers(flags: dict[str, bool]) -> list[str]:
    """Check all 11 automatic permanent exclusions. Non-empty => permanent exclusion."""
    triggered = []
    for flag in AUTO_DISQUALIFIERS:
        if flags.get(flag, False):
            triggered.append(flag)
    return triggered


def screen_candidate(
    ticker: str,
    exchange: str | None,
    price: float | None,
    market_cap: float | None,
    adv_60d: float | None,
    float_value: float | None,
    float_shares: float | None,
    quarters_filed: int | None,
    months_since_ipo: int | None,
    profitable_years: int | None,
    si_pct_float: float | None = None,
    distance_to_default: float | None = None,
    auto_disqualifier_flags: dict[str, bool] | None = None,
) -> tuple[bool, list[ExclusionReason]]:
    """Screen a single candidate for Sleeve E eligibility.

    Missing data => excluded with reason='insufficient_data'. Never impute.

    Returns (eligible, exclusion_reasons).
    """
    exclusions: list[ExclusionReason] = []

    checks = [
        ("exchange", check_exchange(exchange)),
        ("price", check_price(price)),
        ("market_cap", check_market_cap(market_cap)),
        ("adv", check_adv(adv_60d)),
        ("float", check_float(float_value, float_shares)),
        ("history", check_history(quarters_filed, months_since_ipo)),
        ("profitability", check_profitability(profitable_years)),
        ("short_interest", check_short_interest(si_pct_float)),
        ("distance_to_default", check_distance_to_default(distance_to_default)),
    ]

    for check_name, result in checks:
        if result is not None:
            exclusions.append(ExclusionReason(ticker=ticker, reason=result))

    # Auto-disqualifiers
    if auto_disqualifier_flags:
        triggered = check_auto_disqualifiers(auto_disqualifier_flags)
        for flag in triggered:
            exclusions.append(ExclusionReason(ticker=ticker, reason=f"auto_disqualifier:{flag}"))

    eligible = len(exclusions) == 0
    return eligible, exclusions
