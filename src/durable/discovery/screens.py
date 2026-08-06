"""Seven discovery screens for Sleeve E. docs/08 section 8. TICKET-027.

CLI (`make discover AS_OF=YYYY-MM-DD` / `python -m durable.discovery.screens --as-of ...`):
builds candidates from the PIT store (`store.as_of()` via `discovery/pit_data.py`), filters
them through the Sleeve E universe rule (`discovery/universe.py:screen_candidate`, STRICTER
than the main portfolio universe — see .claude/rules/speculation-limits.md "Universe — never
relax"), runs the seven screens below on the survivors, and writes a watchlist CSV to
`data/processed/discovery/watchlist_<as_of>.csv`. The CLI is itself one of the "systematic
screens" permitted by speculation-limits.md rule 17 — it adds no other sourcing path.

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
                    detail=(
                        f"analysts={c.get('analyst_count')}, inst={c.get('institutional_pct'):.0%}"
                    ),
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


# ==============================================================================================
# CLI — everything above this line is pure (no I/O, network, wall-clock, or config lookups).
# Everything below does real I/O and is only ever reached via `if __name__ == "__main__"`.
# ==============================================================================================

import argparse  # noqa: E402
import csv  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from datetime import date as _date  # noqa: E402
from pathlib import Path  # noqa: E402


def _resolve_user_agent(explicit: str | None, config: dict) -> str:
    """User-Agent precedence: --user-agent flag > EDGAR_IDENTITY env var > config's
    data.sec_identity."""
    if explicit:
        return explicit
    env_identity = os.environ.get("EDGAR_IDENTITY")
    if env_identity:
        return env_identity
    return str(config.get("data", {}).get("sec_identity", ""))


def _watchlist_rows(candidates: list[dict], result: ScreenResult) -> list[dict]:
    """One CSV row per unique ticker: which screens hit and why."""
    by_ticker = result.hits_by_ticker
    rows = []
    for c in candidates:
        ticker = c["ticker"]
        hits = by_ticker.get(ticker, [])
        if not hits:
            continue
        rows.append(
            {
                "ticker": ticker,
                "n_screens_hit": len(hits),
                "screens": ";".join(h.screen.value for h in hits),
                "details": " | ".join(f"{h.screen.value}: {h.detail}" for h in hits),
            }
        )
    rows.sort(key=lambda r: (-r["n_screens_hit"], r["ticker"]))
    return rows


_EXCLUSION_CATEGORY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("auto_disqualifier:", "auto_disqualifier"),
    ("exchange", "exchange"),
    ("missing_price", "price"),
    ("price_", "price"),
    ("missing_market_cap", "market_cap"),
    ("market_cap_", "market_cap"),
    ("missing_adv", "adv"),
    ("adv_", "adv"),
    ("missing_float_data", "float"),
    ("float_", "float"),
    ("missing_quarters_filed", "quarters_filed"),
    ("quarters_filed_", "quarters_filed"),
    ("missing_ipo_date", "months_since_ipo"),
    ("months_since_ipo_", "months_since_ipo"),
    ("missing_profitability_data", "profitability"),
    ("profitable_years_", "profitability"),
    ("short_interest_", "short_interest"),
    ("distance_to_default_", "distance_to_default"),
)


def _categorize_exclusion(reason: str) -> str:
    """Bucket a formatted exclusion-reason string (which embeds the actual value, e.g.
    'price_4.99_below_5.0') into a stable category for the CLI's summary counts."""
    for prefix, category in _EXCLUSION_CATEGORY_PREFIXES:
        if reason.startswith(prefix):
            return category
    return reason


def _write_watchlist_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["ticker", "n_screens_hit", "screens", "details"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    """Entry point for `make discover` / `python -m durable.discovery.screens --as-of DATE`."""
    from durable.config import ConfigError, load_config
    from durable.data.store import get_conn, init_schema
    from durable.discovery import pit_data
    from durable.discovery.universe import screen_candidate

    parser = argparse.ArgumentParser(description="Run the Sleeve E discovery screens.")
    parser.add_argument("--as-of", required=True, help="Point-in-time date, YYYY-MM-DD.")
    parser.add_argument("--db", default=None, help="Override the DuckDB path from config.yaml.")
    parser.add_argument("--user-agent", default=None, help="EDGAR User-Agent override.")
    parser.add_argument("--out", default=None, help="Override the watchlist CSV output path.")
    args = parser.parse_args(argv)

    try:
        as_of_date = _date.fromisoformat(args.as_of)
    except ValueError:
        print(f"--as-of must be YYYY-MM-DD, got {args.as_of!r}", file=sys.stderr)
        return 1

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Cannot run discover: {exc}", file=sys.stderr)
        return 1

    from durable.config import PROJECT_ROOT

    db_path = Path(args.db) if args.db else PROJECT_ROOT / config["data"]["duckdb_path"]
    if not db_path.is_file():
        print(
            f"No data store found at {db_path}. Run `make ingest` first "
            "(this CLI never fabricates data for a missing store).",
            file=sys.stderr,
        )
        return 1

    try:
        user_agent = _resolve_user_agent(args.user_agent, config)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Could not resolve an EDGAR User-Agent: {exc}", file=sys.stderr)
        return 1

    conn = get_conn(db_path)
    init_schema(conn)

    tickers = pit_data.list_tickers_with_fundamentals(conn, as_of_date)
    if not tickers:
        print(
            f"No fundamentals available as of {as_of_date} in {db_path}. "
            "The store exists but has no data yet — run `make ingest` first.",
            file=sys.stderr,
        )
        return 1

    managers_path = PROJECT_ROOT / config.get("signals", {}).get("institutional", {}).get(
        "managers_file", "config/managers.yaml"
    )
    tracked_managers = pit_data.load_tracked_managers(managers_path)

    eligible_screen_fields: list[dict] = []
    exclusion_reason_counts: dict[str, int] = {}
    data_gap_examples: set[str] = set()

    for ticker in tickers:
        candidate = pit_data.build_candidate(conn, as_of_date, ticker, tracked_managers)
        data_gap_examples.update(candidate.data_gaps)
        eligible, exclusions = screen_candidate(ticker=ticker, **candidate.universe_kwargs)
        if not eligible:
            for reason in exclusions:
                key = _categorize_exclusion(reason.reason)
                exclusion_reason_counts[key] = exclusion_reason_counts.get(key, 0) + 1
            continue
        eligible_screen_fields.append(candidate.screen_fields)

    try:
        result = run_all_screens(eligible_screen_fields, user_agent=user_agent)
    except ValueError as exc:
        print(f"Cannot run discover: {exc}", file=sys.stderr)
        return 1

    rows = _watchlist_rows(eligible_screen_fields, result)

    out_path = (
        Path(args.out)
        if args.out
        else PROJECT_ROOT / "data" / "processed" / "discovery" / f"watchlist_{as_of_date}.csv"
    )
    _write_watchlist_csv(out_path, rows)

    print(f"As of {as_of_date}: {len(tickers)} tickers with fundamentals in the store.")
    print(
        f"{len(eligible_screen_fields)} passed the Sleeve E universe filter "
        f"({len(tickers) - len(eligible_screen_fields)} excluded)."
    )
    if exclusion_reason_counts:
        print("Exclusion reasons:")
        for reason, count in sorted(exclusion_reason_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {reason}: {count}")
    print(f"{len(result.unique_tickers)} unique candidates hit at least one screen.")
    for screen_type in ALL_SCREENS:
        n = sum(1 for h in result.hits if h.screen == screen_type)
        print(f"  {screen_type.value}: {n} hits")
    if data_gap_examples:
        print(
            "Data gaps encountered (see discovery/pit_data.py module docstring for the full "
            "list) — these suppress real candidates until upstream ingestion tickets land:"
        )
        for gap in sorted(data_gap_examples):
            print(f"  - {gap}")
    print(f"Watchlist written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
