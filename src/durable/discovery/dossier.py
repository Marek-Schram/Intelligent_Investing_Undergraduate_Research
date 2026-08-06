"""Discovery Dossier for one Sleeve E candidate. docs/08 section 9, TICKET-029, TICKET-046.

CLI: `make dossier TICKER=XYZ` / `python -m durable.discovery.dossier --ticker XYZ`.
Writes a markdown dossier to `research/discovery/<ticker>_dossier.md`.

Composes the already-tested pure modules for the quantitative sections —
`discovery.score`, `discovery.manipulation`, `discovery.neglect`, `discovery.tranche` — and
`reporting.memo` (`validate_narrative`, `BearCase`, `validate_bear_case`) for the qualitative
bear-case section, per docs/13 §2.5. Data assembly (facts_fundamentals, bars_daily, 13F,
insider transactions, short interest, corporate actions -> plain dicts) is shared with
`discovery/screens.py` via `discovery/pit_data.py` — see that module's docstring for the full
list of fields the current ingestion schema does not yet provide.

The nine required sections (`discovery.tranche.DOSSIER_SECTIONS`):
  business_description · neglect_reason · sub_scores · reverse_dcf · dd_and_short_interest ·
  manipulation_checks · bear_case · biggest_risks · mistake_blank

Per .claude/rules/speculation-limits.md rule 19 ("Never suppress a manipulation flag because
fundamentals look good. The flags win"), a triggered manipulation flag is rendered as an
unmissable banner at the very top AND bottom of the document, and every discovery-score number
in between is explicitly labeled "informational only — this ticker is permanently excluded
regardless of score" rather than left to imply the fundamentals could override the flag.

Per rule 20 ("Every Sleeve E buy requires a written bear case"), the bear case is never
fabricated here — it is supplied by the human/`bear-analyst` subagent via `--bear-case PATH`
(the `adversarial-review` skill's output, saved to a JSON/YAML file matching
`reporting.memo.BearCase`'s fields). Without it, the dossier renders a loud, unambiguous
"NOT YET WRITTEN" placeholder rather than silently proceeding as if the requirement were met.

Data source: PIT store via `discovery/pit_data.py`; FRED 10Y Treasury via `data/macro.py` for
    the reverse-DCF discount rate.
available_at logic: all data filtered via `store.as_of(as_of)` upstream (in `pit_data.py`); see
    that module's docstring for the one exception (a raw restated-facts query).
Spec section: docs/08 §9, docs/13 §2.5, specs/BUILD_TICKETS.md T-029 and TICKET-046.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from durable.discovery import pit_data
from durable.discovery.manipulation import ManipulationResult, run_manipulation_screen
from durable.discovery.neglect import NeglectResult, compute_neglect_score
from durable.discovery.score import DiscoveryScore, compute_discovery_score
from durable.discovery.tranche import (
    DOSSIER_SECTIONS,
    MAX_PCT_OF_ADV,
    SCORE_OPEN,
    SCORE_WATCHLIST,
    Dossier,
)
from durable.factors.valuation import implied_growth, reverse_dcf_gap
from durable.reporting.memo import BearCase, validate_bear_case, validate_narrative

MANIPULATION_BANNER = (
    "MANIPULATION FLAG(S) TRIGGERED. PERMANENT EXCLUSION (speculation-limits.md rule 19: "
    "the flags win — fundamentals never override a triggered flag). "
    "This ticker MUST NOT be opened as a Sleeve E position regardless of any score below."
)

BEAR_CASE_MISSING = (
    "NOT YET WRITTEN. Every Sleeve E buy requires a written bear case "
    "(speculation-limits.md rule 20). Run the `adversarial-review` skill "
    "(invokes the `bear-analyst` subagent in its own context, per docs/13 §2.5), save its "
    "output to a JSON/YAML file matching reporting.memo.BearCase's fields "
    "(ticker, bear_text, falsifiers [exactly 3], citations, sleeve='E'), and re-run this "
    "dossier with --bear-case PATH. This ticker is NOT buy-eligible until this section is "
    "filled in and passes validation."
)


@dataclass
class ReverseDCFResult:
    """Reverse-DCF inputs and result, or the reason it could not be computed."""

    computable: bool
    reason: str = ""
    wacc: float | None = None
    risk_free_rate: float | None = None
    implied_growth_rate: float | None = None
    delivered_fcf_cagr_5y: float | None = None
    gap: float | None = None


def compute_reverse_dcf(
    ev: float | None,
    fcf_0: float | None,
    fcf_5y_cagr: float | None,
    risk_free_rate: float | None,
    equity_risk_premium: float,
    wacc_floor: float,
    terminal_growth: float,
) -> ReverseDCFResult:
    """Reverse-DCF implied growth + gap vs delivered growth. docs/08 §9, factors/valuation.py.

    Returns `computable=False` with a reason instead of fabricating a number when an input
    (most commonly the risk-free rate, which requires ingested macro data) is missing.
    """
    if risk_free_rate is None:
        return ReverseDCFResult(
            computable=False, reason="no risk-free rate (macro data not ingested for this date)"
        )
    if ev is None or ev <= 0:
        return ReverseDCFResult(
            computable=False, reason="no enterprise value (missing market cap or debt)"
        )
    if fcf_0 is None or fcf_0 <= 0:
        return ReverseDCFResult(
            computable=False, reason="latest free cash flow is missing or non-positive"
        )

    wacc = max(risk_free_rate + equity_risk_premium, wacc_floor)
    g_implied = implied_growth(ev, fcf_0, wacc, terminal_growth)
    if g_implied != g_implied:  # NaN check without importing numpy/math here
        return ReverseDCFResult(
            computable=False,
            reason="reverse-DCF solve did not converge",
            wacc=wacc,
            risk_free_rate=risk_free_rate,
        )

    gap = None
    if fcf_5y_cagr is not None:
        gap = reverse_dcf_gap(ev, fcf_0, fcf_5y_cagr, wacc, terminal_growth)

    return ReverseDCFResult(
        computable=True,
        wacc=wacc,
        risk_free_rate=risk_free_rate,
        implied_growth_rate=g_implied,
        delivered_fcf_cagr_5y=fcf_5y_cagr,
        gap=gap,
    )


def load_bear_case(path: str, ticker: str) -> BearCase:
    """Load a bear case from a JSON/YAML file (the adversarial-review skill's saved output).

    Expected keys: bear_text, falsifiers (list, exactly 3), citations (list),
    checked_sources (optional list, only needed if bear_text starts with
    "No bear case could be constructed"). `ticker` and `sleeve="E"` are set by this loader.
    """
    from pathlib import Path

    import yaml

    with Path(path).open() as f:
        raw = yaml.safe_load(f) or {}

    return BearCase(
        ticker=ticker,
        bear_text=raw.get("bear_text", ""),
        falsifiers=list(raw.get("falsifiers", [])),
        citations=list(raw.get("citations", [])),
        sleeve="E",
        checked_sources=raw.get("checked_sources"),
    )


def _fmt(value: float | None, pct: bool = False, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if pct:
        return f"{value:.1%}"
    return f"{value:.{digits}f}"


def _business_description_section(candidate: pit_data.CandidateData) -> str:
    return (
        "**Not available from the PIT store.** No raw 10-K full-text or business-description "
        "extraction field exists in the current ingestion schema "
        "(`signals/extract.py:ExtractionField` has no business-description field, and "
        "`filing_extractions` only carries the structured numeric fields listed there). "
        "**A human must read the 10-K Item 1 and fill this in before this dossier is "
        "buy-ready** — do not infer this from the ticker or sector alone."
    )


def _neglect_section(neglect: NeglectResult) -> str:
    lines = [
        "**The neglect premium is contested** (Arbel & Strebel 1982 found excess returns for "
        "low-coverage firms after controlling for size; Beard & Sias 1997 found none after "
        "size adjustment, in 7,000+ firms 1982-1995 — docs/08 §1). Neglect is a place to "
        "look, never a reason to buy.",
        "",
        f"Neglect sub-score: {neglect.capped_score}/25 (raw {neglect.score}).",
        "",
        "| Component | Sub-score | Raw input |",
        "|---|---|---|",
        f"| Analyst count | {neglect.analyst_sub}/8 | {neglect.inputs.analyst_count!r} |",
        (
            f"| Institutional ownership | {neglect.institutional_sub}/7 | "
            f"{_fmt(neglect.inputs.institutional_ownership_pct, pct=True)} |"
        ),
        (
            f"| Media mentions decile | {neglect.media_sub}/5 | "
            f"{neglect.inputs.media_mentions_decile!r} |"
        ),
        (
            f"| No sell-side initiation (24m) | {neglect.initiation_sub}/5 | "
            f"{neglect.inputs.has_sell_side_initiation_24m!r} |"
        ),
    ]
    if neglect.inputs.analyst_count is None:
        lines.append(
            "\n*Analyst count is not ingested (no sell-side coverage data source exists yet "
            "— `data/coverage.py` is an unbuilt scaffold). This component reads 0, not a "
            "true zero-analyst reading.*"
        )
    return "\n".join(lines)


def _sub_scores_section(
    discovery_score: DiscoveryScore,
    peer_group_note: str,
    manipulation_clean: bool,
) -> str:
    header = (
        "**Informational only — this ticker is permanently excluded regardless of score.**\n\n"
        if not manipulation_clean
        else ""
    )
    peer_group_kind = (
        "used broader cap-range fallback, <5 same-SIC peers"
        if discovery_score.used_fallback_peers
        else "same 2-digit SIC group"
    )
    lines = [
        header,
        f"Total: {discovery_score.total}/100 "
        f"(gate: {discovery_score.gate_result.value}; "
        f"watchlist-eligible >= {SCORE_WATCHLIST}: {discovery_score.eligible_watchlist}; "
        f"position-eligible >= {SCORE_OPEN}: {discovery_score.eligible_position}).",
        "",
        "| Component | Score | Max |",
        "|---|---|---|",
        f"| Durability gate | {discovery_score.durability_sub} | 40 |",
        f"| Neglect | {discovery_score.neglect_sub} | 25 |",
        f"| Valuation (EV/EBIT peer rank) | {discovery_score.valuation_sub} | 25 |",
        f"| Quality evidence (filing-cited) | {discovery_score.quality_sub} | 10 |",
        f"| Overlays (insider/institutional) | {discovery_score.overlay_sub} | +-5 |",
        "",
        f"EV/EBIT: {_fmt(discovery_score.ev_ebit)} "
        f"(excluded if > 30 — Sleeve E is stricter than Sleeve C's 45).",
        f"Peer group size: {discovery_score.peer_group_size} ({peer_group_kind}).",
        peer_group_note,
        "",
        "Quality claims (filing-cited only — uncited claims score 0):",
    ]
    if discovery_score.quality_claims:
        for c in discovery_score.quality_claims:
            lines.append(f"  - {c.claim}: {c.points} pts (cited={c.cited})")
    else:
        lines.append(
            "  - none scored (either the LLM-extraction pipeline (TICKET-031) has not run "
            "for this filing, or no claim met its threshold)"
        )
    return "\n".join(lines)


def _reverse_dcf_section(dcf: ReverseDCFResult) -> str:
    if not dcf.computable:
        return f"**Not computable:** {dcf.reason}."
    lines = [
        f"WACC: {_fmt(dcf.wacc, pct=True)} "
        f"(risk-free {_fmt(dcf.risk_free_rate, pct=True)} + ERP, floored).",
        f"Market-implied growth (reverse-DCF, 10y + terminal): "
        f"{_fmt(dcf.implied_growth_rate, pct=True)}.",
        f"Delivered 5y FCF CAGR: {_fmt(dcf.delivered_fcf_cagr_5y, pct=True)}.",
    ]
    if dcf.gap is not None:
        direction = (
            "market demands LESS growth than delivered (favorable)"
            if dcf.gap > 0
            else "market demands MORE growth than delivered (unfavorable)"
        )
        lines.append(f"Gap (delivered - implied): {_fmt(dcf.gap, pct=True)} — {direction}.")
    else:
        lines.append("Gap: n/a (delivered FCF CAGR not computable).")
    return "\n".join(lines)


def _dd_and_short_interest_section(candidate: pit_data.CandidateData) -> str:
    dd = candidate.dd_result
    si = candidate.manipulation_kwargs.get("si_pct_float")
    lines = []
    if dd is None:
        lines.append("Distance-to-default: not computable (missing market cap or long-term debt).")
    else:
        lines.append(
            f"Distance-to-default: {_fmt(dd.dd) if dd.is_valid else dd.flag.value} "
            f"(exclusion threshold < 1.5; below_threshold={dd.below_threshold})."
        )
    if si is None:
        lines.append(
            "Short interest: not available (no short-interest publication for this date)."
        )
    else:
        lines.append(f"Short interest: {_fmt(si, pct=True)} of float (exclusion threshold > 10%).")
    return "\n".join(lines)


def _manipulation_section(manipulation: ManipulationResult) -> str:
    lines = [
        f"**is_clean = {manipulation.is_clean}**",
        "",
        "Every check, including the ones that passed (rule 19 — this section is never "
        "trimmed to only the hits):",
        "",
        "| Check | Triggered | Detail |",
        "|---|---|---|",
    ]
    for flag in manipulation.flags:
        marker = "**TRIGGERED**" if flag.triggered else "clean"
        lines.append(f"| {flag.check} | {marker} | {flag.detail} |")
    return "\n".join(lines)


def _bear_case_section(bear_case: BearCase | None, issues: list[str]) -> str:
    if bear_case is None:
        return BEAR_CASE_MISSING
    lines = [
        f"**{bear_case.bear_text}**" if not issues else bear_case.bear_text,
        "",
        "Falsifiers:",
    ]
    for i, f in enumerate(bear_case.falsifiers, 1):
        lines.append(f"  {i}. {f}")
    lines.append("")
    lines.append(f"Citations: {'; '.join(bear_case.citations) if bear_case.citations else 'NONE'}")
    if issues:
        lines.append("")
        lines.append("**VALIDATION FAILED — this bear case does not satisfy rule 20/TICKET-046:**")
        for issue in issues:
            lines.append(f"  - {issue}")
    return "\n".join(lines)


def _biggest_risks_section(
    bear_case: BearCase | None, durability_breakdown: dict, manipulation: ManipulationResult
) -> str:
    lines = ["The three biggest ways this thesis could be wrong:"]
    risks: list[str] = []
    if bear_case is not None and bear_case.falsifiers:
        risks = list(bear_case.falsifiers[:3])
    elif durability_breakdown.get("red_flags"):
        risks = [f"Durability red flag: {f}" for f in durability_breakdown["red_flags"][:3]]
    if manipulation.triggered_flags and len(risks) < 3:
        risks.append(
            f"Manipulation flag(s) triggered: "
            f"{', '.join(f.check for f in manipulation.triggered_flags)}"
        )
    if not risks:
        risks = [
            "Not yet identified — run the adversarial-review skill (bear-analyst subagent) "
            "to generate the falsifiers this section should list."
        ]
    for i, r in enumerate(risks[:3], 1):
        lines.append(f"  {i}. {r}")
    return "\n".join(lines)


def _mistake_blank_section() -> str:
    return "What would have to be true for this to be a mistake:\n\n_(left blank for the human)_"


def _tranche_preview(candidate: pit_data.CandidateData, discovery_score: DiscoveryScore) -> str:
    adv_60d = candidate.universe_kwargs.get("adv_60d")
    adv_cap = adv_60d * MAX_PCT_OF_ADV if adv_60d else None
    lines = [
        "This ticker is not currently a Sleeve E position (this dossier is pre-entry "
        "research). If opened, entry is staged 40/30/30 with a minimum 90 days between "
        "tranches, gated on business confirmation (more quarters filed, durability held), "
        "NEVER on price decline (docs/08 §6).",
        f"T1 requires discovery score >= {SCORE_OPEN} with all screens passed. "
        f"Current score {discovery_score.total} "
        f"{'MEETS' if discovery_score.total >= SCORE_OPEN else 'does NOT meet'} that bar "
        f"(watchlist bar is {SCORE_WATCHLIST}).",
    ]
    if adv_cap is not None:
        lines.append(
            f"1% of 60-day ADV = ${adv_cap:,.0f} (one of the four constraints `size_tranche` "
            f"would apply; the others — 0.25%-of-total-portfolio and remaining Sleeve E "
            f"budget — need current portfolio NAV, which this research CLI does not track)."
        )
    return "\n".join(lines)


def build_dossier_sections(
    candidate: pit_data.CandidateData,
    neglect: NeglectResult,
    discovery_score: DiscoveryScore,
    manipulation: ManipulationResult,
    dcf: ReverseDCFResult,
    durability_breakdown: dict,
    peer_group_note: str,
    bear_case: BearCase | None,
    bear_case_issues: list[str],
) -> dict[str, str]:
    """Build the nine required dossier sections (`discovery.tranche.DOSSIER_SECTIONS`)."""
    return {
        "business_description": _business_description_section(candidate),
        "neglect_reason": _neglect_section(neglect),
        "sub_scores": _sub_scores_section(discovery_score, peer_group_note, manipulation.is_clean),
        "reverse_dcf": _reverse_dcf_section(dcf),
        "dd_and_short_interest": _dd_and_short_interest_section(candidate),
        "manipulation_checks": _manipulation_section(manipulation),
        "bear_case": _bear_case_section(bear_case, bear_case_issues),
        "biggest_risks": _biggest_risks_section(bear_case, durability_breakdown, manipulation),
        "mistake_blank": _mistake_blank_section(),
    }


_SECTION_TITLES = {
    "business_description": "1. Business Description",
    "neglect_reason": "2. Why Is This Neglected",
    "sub_scores": "3. Discovery Score",
    "reverse_dcf": "4. Reverse-DCF Implied Growth",
    "dd_and_short_interest": "5. Distance-to-Default and Short Interest",
    "manipulation_checks": "6. Manipulation Checks",
    "bear_case": "7. Bear Case",
    "biggest_risks": "8. Three Biggest Risks",
    "mistake_blank": "9. Mistake Line",
}


def render_markdown(
    ticker: str,
    as_of: date,
    sections: dict[str, str],
    manipulation: ManipulationResult,
    tranche_preview: str,
    data_gaps: list[str],
) -> str:
    """Assemble the full markdown dossier. The nine required sections plus informational
    tranche-status and data-gap blocks (docs/08 §9 also asks for these, though they are not
    among the nine keys `discovery.tranche.Dossier.is_complete` checks)."""
    lines = [f"# Discovery Dossier: {ticker}", f"As of: {as_of.isoformat()}", ""]

    if not manipulation.is_clean:
        lines += ["```", MANIPULATION_BANNER, "```", ""]

    for key in DOSSIER_SECTIONS:
        lines.append(f"## {_SECTION_TITLES[key]}")
        lines.append(sections[key])
        lines.append("")

    lines.append("## Tranche Status and Next Gate")
    lines.append(tranche_preview)
    lines.append("")

    lines.append("## Data Gaps (Not Verified)")
    if data_gaps:
        lines.append(
            "The following inputs could not be verified from the current PIT store and were "
            "treated as missing (never imputed) — see `discovery/pit_data.py` module "
            "docstring for the full, general list:"
        )
        for gap in data_gaps:
            lines.append(f"  - {gap}")
    else:
        lines.append("None flagged for this ticker beyond the general gaps in pit_data.py.")
    lines.append("")

    lines.append("## Evidence Caveat")
    lines.append(
        "This dossier is a research artifact, not a recommendation. The neglect premium is "
        "contested (docs/08 §1), the small-cap premium is largely a 1975-1983 artifact "
        "surviving mainly in quality-filtered form, and with 8 positions in a 2%-of-total "
        "sleeve there will never be enough observations to distinguish skill from luck "
        "(docs/08 §10)."
    )
    lines.append("")

    if not manipulation.is_clean:
        lines += ["```", MANIPULATION_BANNER, "```"]

    return "\n".join(lines)


def _load_and_validate_bear_case(
    bear_case_path: str | None, ticker: str
) -> tuple[BearCase | None, list[str]]:
    if bear_case_path is None:
        return None, []
    bear_case = load_bear_case(bear_case_path, ticker)
    issues = validate_bear_case(bear_case, sleeve="E")
    is_valid, explanation = validate_narrative(bear_case.bear_text)
    if not is_valid and explanation not in issues:
        issues.append(explanation)
    return bear_case, issues


def main(argv: list[str] | None = None) -> int:
    """Entry point for `make dossier TICKER=` / `python -m durable.discovery.dossier --ticker`."""
    import argparse
    import sys
    from pathlib import Path

    from durable.config import ConfigError, load_config
    from durable.data.macro import get_risk_free_rate
    from durable.data.store import get_conn, init_schema

    parser = argparse.ArgumentParser(description="Build a Discovery Dossier for one ticker.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument(
        "--as-of",
        default=None,
        help="Point-in-time date, YYYY-MM-DD. Defaults to today (this is a live research "
        "CLI, not a backtest — the default lives in this CLI layer only).",
    )
    parser.add_argument("--db", default=None, help="Override the DuckDB path from config.yaml.")
    parser.add_argument(
        "--bear-case",
        default=None,
        help="Path to a JSON/YAML file with the adversarial-review skill's bear-case output.",
    )
    parser.add_argument("--out", default=None, help="Override the dossier output path.")
    args = parser.parse_args(argv)

    ticker = args.ticker.upper()
    as_of_date = date.fromisoformat(args.as_of) if args.as_of else date.today()

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Cannot build dossier: {exc}", file=sys.stderr)
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

    conn = get_conn(db_path)
    init_schema(conn)

    tickers = pit_data.list_tickers_with_fundamentals(conn, as_of_date)
    if ticker not in tickers:
        print(
            f"No fundamentals for {ticker} as of {as_of_date} in {db_path}. "
            "Either the ticker has not been ingested, or there is no data for this date yet.",
            file=sys.stderr,
        )
        return 1

    managers_path = PROJECT_ROOT / config.get("signals", {}).get("institutional", {}).get(
        "managers_file", "config/managers.yaml"
    )
    tracked_managers = pit_data.load_tracked_managers(managers_path)

    candidate = pit_data.build_candidate(conn, as_of_date, ticker, tracked_managers)

    peer_ev_ebits, used_fallback = pit_data.peer_ev_ebit_group(
        conn, as_of_date, tickers, candidate.screen_fields["sic_code"], ticker, tracked_managers
    )
    peer_group_note = (
        f"({len(peer_ev_ebits)} peer EV/EBIT values, "
        f"{'cap-range fallback' if used_fallback else 'same-SIC group'})."
    )

    neglect_result = compute_neglect_score(ticker, **candidate.neglect_kwargs)

    discovery_score = compute_discovery_score(
        ticker,
        durability_raw=candidate.score_kwargs["durability_raw"],
        neglect_sub=neglect_result.capped_score,
        ev_ebit=candidate.score_kwargs["ev_ebit"],
        peer_ev_ebits=peer_ev_ebits,
        quality_claims=candidate.score_kwargs["quality_claims"],
        insider_purchases_90d=candidate.score_kwargs["insider_purchases_90d"],
        institutional_conviction_count=candidate.score_kwargs["institutional_conviction_count"],
    )

    manipulation_result = run_manipulation_screen(
        ticker, as_of_date, **candidate.manipulation_kwargs
    )

    valuation_cfg = config.get("valuation", {})
    risk_free_rate = get_risk_free_rate(conn, as_of_date)
    dcf = compute_reverse_dcf(
        ev=candidate.ev,
        fcf_0=candidate.fcf_0,
        fcf_5y_cagr=candidate.screen_fields.get("fcf_cagr_5y"),
        risk_free_rate=risk_free_rate,
        equity_risk_premium=valuation_cfg.get("equity_risk_premium", 0.05),
        wacc_floor=valuation_cfg.get("wacc_floor", 0.08),
        terminal_growth=valuation_cfg.get("terminal_growth", 0.025),
    )

    bear_case, bear_case_issues = _load_and_validate_bear_case(args.bear_case, ticker)

    from durable.factors.durability import durability_score as _durability

    facts = pit_data.store_as_of(conn, "facts_fundamentals", as_of_date, tickers=ticker)
    _, durability_breakdown = _durability(facts) if not facts.empty else (None, {})

    sections = build_dossier_sections(
        candidate=candidate,
        neglect=neglect_result,
        discovery_score=discovery_score,
        manipulation=manipulation_result,
        dcf=dcf,
        durability_breakdown=durability_breakdown,
        peer_group_note=peer_group_note,
        bear_case=bear_case,
        bear_case_issues=bear_case_issues,
    )

    dossier = Dossier(ticker=ticker, sections=sections)
    assert dossier.is_complete, f"missing sections: {dossier.missing_sections}"

    tranche_preview = _tranche_preview(candidate, discovery_score)
    markdown = render_markdown(
        ticker, as_of_date, sections, manipulation_result, tranche_preview, candidate.data_gaps
    )

    out_path = (
        Path(args.out)
        if args.out
        else PROJECT_ROOT / "research" / "discovery" / f"{ticker}_dossier.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown)

    print(f"Dossier written to {out_path}")
    print(
        f"Discovery score: {discovery_score.total}/100 (gate: {discovery_score.gate_result.value})"
    )
    if not manipulation_result.is_clean:
        print(f"WARNING: {MANIPULATION_BANNER}", file=sys.stderr)
    if bear_case is None:
        print(
            "WARNING: no bear case provided (--bear-case). This ticker is NOT buy-eligible "
            "until one is written and validated.",
            file=sys.stderr,
        )
    elif bear_case_issues:
        print(f"WARNING: bear case failed validation: {bear_case_issues}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
