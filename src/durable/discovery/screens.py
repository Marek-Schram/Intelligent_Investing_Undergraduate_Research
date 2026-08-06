"""Seven discovery screens for Sleeve E. docs/08 section 8. TICKET-027.

Screens:
  1. Coverage-gap — profitable, $300M-$3B, 0-2 analysts, institutional < 40%
  2. Boring-industry — high durability in unglamorous SIC groups
  3. Insider-cluster — >= 2 officers/directors, Form 4 code 'P', 90 days, < 3 analysts
  4. Spin-off — 12-36 months post-spin
  5. Filing-language — EDGAR full-text keywords
  6. Quiet-compounder — 5y revenue AND FCF CAGR > 8%, flat/shrink shares, ROIC > 12%, < 4 analysts
  7. Institutional-conviction — top-10 for >= 2 tracked managers, < 4 analysts

EDGAR discipline:
  - User-Agent with name and email on every request (missing => 403)
  - Max 10 req/sec
  - CIKs zero-padded to 10 digits
  - Form 4 code 'P' only (purchases, not awards/grants)

Multi-screen hits add NO points — a candidate found by 3 screens gets the same score
as one found by 1. The screens discover; the scoring system scores.

Empty result is valid (no candidates pass a given screen in a given period).

Data source: EDGAR filings, fundamentals, 13F, analyst coverage from PIT store.
available_at logic: all data filtered via store.as_of(as_of) upstream.
Spec section: docs/08 §8.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
Screen functions receive pre-fetched data and return qualifying tickers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ScreenType(Enum):
    COVERAGE_GAP = "coverage_gap"
    BORING_INDUSTRY = "boring_industry"
    INSIDER_CLUSTER = "insider_cluster"
    SPINOFF = "spinoff"
    FILING_LANGUAGE = "filing_language"
    QUIET_COMPOUNDER = "quiet_compounder"
    INSTITUTIONAL_CONVICTION = "institutional_conviction"


ALL_SCREENS = list(ScreenType)

BORING_SIC_GROUPS = {
    "5080",  # Industrial distribution
    "5084",
    "5085",
    "2810",  # Specialty chemicals
    "2820",
    "2860",
    "2890",
    "4400",  # Marine/logistics
    "4410",
    "4412",
    "4731",
    "4950",  # Waste
    "4953",
    "8711",  # Testing labs
    "8712",
    "8734",
    "3490",  # Niche manufacturing
    "3559",
    "3599",
    "4911",  # Regional utilities
    "4924",
    "4931",
    "5030",  # Building products
    "5031",
    "5211",
    "7380",  # Commercial services
    "7389",
}

FILING_LANGUAGE_KEYWORDS = (
    "long-term supply agreement",
    "multi-year contract",
    "recurring revenue",
    "sole-source supplier",
    "switching costs",
)

MIN_EDGAR_USER_AGENT_LENGTH = 10
MAX_REQUESTS_PER_SECOND = 10
CIK_PAD_WIDTH = 10


def pad_cik(cik: int | str) -> str:
    """Zero-pad CIK to 10 digits per SEC EDGAR requirements."""
    return str(int(cik)).zfill(CIK_PAD_WIDTH)


def validate_user_agent(user_agent: str | None) -> None:
    """Raise if User-Agent is missing or too short (SEC requirement)."""
    if user_agent is None or len(user_agent.strip()) < MIN_EDGAR_USER_AGENT_LENGTH:
        raise ValueError(
            "EDGAR requests require a User-Agent with name and email. "
            "Missing User-Agent results in 403 and IP block."
        )


@dataclass(frozen=True)
class ScreenHit:
    """A candidate discovered by a screen."""

    ticker: str
    screen: ScreenType
    detail: str = ""


@dataclass
class ScreenResult:
    """Results from running all seven screens."""

    hits: list[ScreenHit] = field(default_factory=list)
    screens_run: list[ScreenType] = field(default_factory=list)

    @property
    def unique_tickers(self) -> set[str]:
        """Multi-screen hits add NO extra points — just unique tickers."""
        return {h.ticker for h in self.hits}

    @property
    def hits_by_ticker(self) -> dict[str, list[ScreenHit]]:
        result: dict[str, list[ScreenHit]] = {}
        for h in self.hits:
            result.setdefault(h.ticker, []).append(h)
        return result


def screen_coverage_gap(
    candidates: list[dict],
) -> list[ScreenHit]:
    """Screen 1: profitable, $300M-$3B, 0-2 analysts, institutional < 40%."""
    hits = []
    for c in candidates:
        analyst_count = c.get("analyst_count")
        if analyst_count is None:
            analyst_count = 99
        inst_pct = c.get("institutional_pct")
        if inst_pct is None:
            inst_pct = 1.0
        if (
            c.get("profitable", False)
            and 300e6 <= (c.get("market_cap") or 0) <= 3e9
            and analyst_count <= 2
            and inst_pct < 0.40
        ):
            hits.append(
                ScreenHit(
                    ticker=c["ticker"],
                    screen=ScreenType.COVERAGE_GAP,
                    detail=f"analysts={c.get('analyst_count')}, inst={c.get('institutional_pct'):.0%}",
                )
            )
    return hits


def screen_boring_industry(
    candidates: list[dict],
) -> list[ScreenHit]:
    """Screen 2: high durability in unglamorous SIC groups."""
    hits = []
    for c in candidates:
        sic = str(c.get("sic_code", ""))
        if sic in BORING_SIC_GROUPS and (c.get("durability_score") or 0) >= 30:
            hits.append(
                ScreenHit(
                    ticker=c["ticker"],
                    screen=ScreenType.BORING_INDUSTRY,
                    detail=f"SIC={sic}, durability={c.get('durability_score')}",
                )
            )
    return hits


def screen_insider_cluster(
    candidates: list[dict],
) -> list[ScreenHit]:
    """Screen 3: >= 2 officers/directors, Form 4 code 'P', 90 days, < 3 analysts.

    Only code 'P' (open-market purchases). Not awards, grants, or gifts.
    """
    hits = []
    for c in candidates:
        purchases = [t for t in c.get("form4_transactions", []) if t.get("code") == "P"]
        unique_insiders = {t.get("insider_name") for t in purchases}
        if len(unique_insiders) >= 2 and (c.get("analyst_count") or 99) < 3:
            hits.append(
                ScreenHit(
                    ticker=c["ticker"],
                    screen=ScreenType.INSIDER_CLUSTER,
                    detail=f"{len(unique_insiders)} insiders, code P only",
                )
            )
    return hits


def screen_spinoff(
    candidates: list[dict],
) -> list[ScreenHit]:
    """Screen 4: 12-36 months post-spin."""
    hits = []
    for c in candidates:
        months_since_spin = c.get("months_since_spinoff")
        if months_since_spin is not None and 12 <= months_since_spin <= 36:
            hits.append(
                ScreenHit(
                    ticker=c["ticker"],
                    screen=ScreenType.SPINOFF,
                    detail=f"{months_since_spin} months post-spin",
                )
            )
    return hits


def screen_filing_language(
    candidates: list[dict],
) -> list[ScreenHit]:
    """Screen 5: EDGAR full-text keywords indicating durable business."""
    hits = []
    for c in candidates:
        text = (c.get("filing_text") or "").lower()
        found = [kw for kw in FILING_LANGUAGE_KEYWORDS if kw in text]
        if found:
            hits.append(
                ScreenHit(
                    ticker=c["ticker"],
                    screen=ScreenType.FILING_LANGUAGE,
                    detail=f"keywords: {', '.join(found)}",
                )
            )
    return hits


def screen_quiet_compounder(
    candidates: list[dict],
) -> list[ScreenHit]:
    """Screen 6: 5y rev+FCF CAGR>8%, flat/shrink shares, ROIC>12%, <4 analysts."""
    hits = []
    for c in candidates:
        rev_cagr = c.get("revenue_cagr_5y") or 0
        fcf_cagr = c.get("fcf_cagr_5y") or 0
        shares_growth = c.get("shares_growth_5y") or 0.01
        roic = c.get("roic") or 0
        analysts = c.get("analyst_count") or 99

        if (
            rev_cagr > 0.08
            and fcf_cagr > 0.08
            and shares_growth <= 0
            and roic > 0.12
            and analysts < 4
        ):
            hits.append(
                ScreenHit(
                    ticker=c["ticker"],
                    screen=ScreenType.QUIET_COMPOUNDER,
                    detail=f"rev_cagr={rev_cagr:.1%}, fcf_cagr={fcf_cagr:.1%}, roic={roic:.1%}",
                )
            )
    return hits


def screen_institutional_conviction(
    candidates: list[dict],
) -> list[ScreenHit]:
    """Screen 7: top-10 for >= 2 tracked concentrated managers, < 4 analysts."""
    hits = []
    for c in candidates:
        managers = c.get("conviction_managers") or []
        analysts = c.get("analyst_count") or 99

        if len(managers) >= 2 and analysts < 4:
            hits.append(
                ScreenHit(
                    ticker=c["ticker"],
                    screen=ScreenType.INSTITUTIONAL_CONVICTION,
                    detail=f"managers: {', '.join(managers[:3])}",
                )
            )
    return hits


def run_all_screens(
    candidates: list[dict],
    user_agent: str | None = None,
) -> ScreenResult:
    """Run all seven screens. User-Agent required for EDGAR compliance.

    Multi-screen hits add NO extra points to scoring.
    Empty result is valid (no candidates may pass in a given period).
    """
    validate_user_agent(user_agent)

    result = ScreenResult()

    screen_funcs = [
        (ScreenType.COVERAGE_GAP, screen_coverage_gap),
        (ScreenType.BORING_INDUSTRY, screen_boring_industry),
        (ScreenType.INSIDER_CLUSTER, screen_insider_cluster),
        (ScreenType.SPINOFF, screen_spinoff),
        (ScreenType.FILING_LANGUAGE, screen_filing_language),
        (ScreenType.QUIET_COMPOUNDER, screen_quiet_compounder),
        (ScreenType.INSTITUTIONAL_CONVICTION, screen_institutional_conviction),
    ]

    for screen_type, func in screen_funcs:
        hits = func(candidates)
        result.hits.extend(hits)
        result.screens_run.append(screen_type)

    return result
