"""Staged entry. docs/08 section 6. TICKET-029.

"Little amounts while they're cheap" -- gated on BUSINESS CONFIRMATION, never price decline.

TRANCHE_FRACTIONS=(0.40,0.30,0.30) · MIN_DAYS_BETWEEN_TRANCHES=90
MAX_POSITION_PCT_TOTAL=0.0025 · MAX_SLEEVE_E_PCT_TOTAL=0.02 · MAX_POSITIONS=8
CANCEL_SCORE_THRESHOLD=60 · MAX_PCT_OF_ADV=0.01

next_tranche_gate(state, facts, as_of) -> (eligible, explanation)
    T2 requires TWO ADDITIONAL QUARTERS FILED with durability held >= 30. NOT "price fell 20%".
    Adding because it fell is averaging down into a deteriorating thesis; no config flag
    enables it.
size_tranche(state, total_portfolio_value, adv_60d) -> the MINIMUM of all four constraints.
    Below the broker's fractional minimum => 0.0 with a logged reason. Never round up.
exit_rules(state, facts, flags, as_of) -> (should_exit, rule). E1 GRADUATION is the SUCCESS
    case and is reported as such. E4 (manipulation) exits regardless of P&L.

Data source: portfolio state, fundamentals, manipulation flags from PIT store.
available_at logic: all data filtered via store.as_of(as_of) upstream.
Spec section: docs/08 §6.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

TRANCHE_FRACTIONS = (0.40, 0.30, 0.30)
MIN_DAYS_BETWEEN_TRANCHES = 90
MAX_POSITION_PCT_TOTAL = 0.0025
MAX_SLEEVE_E_PCT_TOTAL = 0.02
MAX_POSITIONS = 8
CANCEL_SCORE_THRESHOLD = 60
MAX_PCT_OF_ADV = 0.01
BROKER_FRACTIONAL_MINIMUM = 1.00

SCORE_OPEN = 75
SCORE_WATCHLIST = 65
DURABILITY_GATE_MIN = 30


class ExitRule(Enum):
    E1_GRADUATION = "graduation"
    E2_THESIS_BREAK = "thesis_break"
    E3_SCORE_BELOW_55_TWICE = "score_below_55_twice"
    E4_MANIPULATION = "manipulation"
    E5_LIQUIDITY = "liquidity"
    E6_CORPORATE_ACTION = "corporate_action"


class TrancheStatus(Enum):
    T1_OPEN = "T1"
    T2_OPEN = "T2"
    T3_OPEN = "T3"
    FULLY_DEPLOYED = "fully_deployed"
    CANCELLED = "cancelled"


@dataclass
class TrancheState:
    """Current tranche state for a position."""

    ticker: str
    current_tranche: int  # 1, 2, or 3
    last_tranche_date: date
    quarters_filed_at_entry: int
    current_quarters_filed: int
    durability_at_entry: float
    current_durability: float
    current_score: float
    score_below_55_count: int = 0
    cancelled: bool = False
    cancel_reason: str = ""


@dataclass
class TrancheFacts:
    """Business facts for gate decisions."""

    quarters_filed: int
    durability: float
    score: float
    market_cap: float | None = None
    analyst_count: int | None = None
    roic: float | None = None
    fcf_trend_positive: bool = False


@dataclass
class ExitFacts:
    """Facts for exit rule evaluation."""

    market_cap: float | None = None
    analyst_count: int | None = None
    score: float = 0
    durability: float = 0
    score_below_55_count: int = 0
    adv_60d: float | None = None
    has_corporate_action: bool = False
    pnl_pct: float = 0.0


@dataclass(frozen=True)
class TrancheGateResult:
    eligible: bool
    explanation: str


@dataclass(frozen=True)
class ExitResult:
    should_exit: bool
    rule: ExitRule | None
    explanation: str
    is_success: bool = False


@dataclass(frozen=True)
class SizeResult:
    amount: float
    constraint_binding: str
    all_constraints: dict[str, float] = field(default_factory=dict)


def next_tranche_gate(
    state: TrancheState,
    facts: TrancheFacts,
    as_of: date,
) -> TrancheGateResult:
    """Check if next tranche is eligible.

    T1: score >= 75, all screens passed.
    T2: TWO ADDITIONAL QUARTERS filed with durability >= 30.
    T3: FOUR total quarters with ROIC and FCF trend confirmed.

    NEVER gated on price decline. A 50% drop does not unlock T2.
    Score < 60 => cancel permanently.
    """
    if state.cancelled:
        return TrancheGateResult(False, f"cancelled: {state.cancel_reason}")

    if facts.score < CANCEL_SCORE_THRESHOLD:
        state.cancelled = True
        state.cancel_reason = f"score {facts.score:.0f} < {CANCEL_SCORE_THRESHOLD}"
        return TrancheGateResult(False, state.cancel_reason)

    days_elapsed = (as_of - state.last_tranche_date).days
    if days_elapsed < MIN_DAYS_BETWEEN_TRANCHES:
        return TrancheGateResult(
            False,
            f"only {days_elapsed} days since last tranche (min {MIN_DAYS_BETWEEN_TRANCHES})",
        )

    if facts.durability < DURABILITY_GATE_MIN:
        return TrancheGateResult(
            False,
            f"durability {facts.durability:.1f} < {DURABILITY_GATE_MIN}",
        )

    if state.current_tranche == 1:
        additional_quarters = facts.quarters_filed - state.quarters_filed_at_entry
        if additional_quarters < 2:
            return TrancheGateResult(
                False,
                f"T2 requires 2 additional quarters filed, have {additional_quarters}",
            )
        return TrancheGateResult(
            True, "T2 gate passed: 2 additional quarters with durability held"
        )

    if state.current_tranche == 2:
        additional_quarters = facts.quarters_filed - state.quarters_filed_at_entry
        if additional_quarters < 4:
            return TrancheGateResult(
                False,
                f"T3 requires 4 total additional quarters, have {additional_quarters}",
            )
        if not facts.fcf_trend_positive:
            return TrancheGateResult(False, "T3 requires positive FCF trend")
        return TrancheGateResult(True, "T3 gate passed: 4 quarters, ROIC+FCF confirmed")

    return TrancheGateResult(False, "fully deployed")


def size_tranche(
    tranche_number: int,
    total_portfolio_value: float,
    adv_60d: float,
    current_sleeve_e_value: float = 0.0,
    current_position_count: int = 0,
) -> SizeResult:
    """Return the MINIMUM of four constraints. Sub-minimum returns 0.0.

    Constraints:
    1. Tranche fraction * max position size (0.25% of total)
    2. Max 1% of 60-day ADV
    3. Sleeve E total <= 2% of portfolio
    4. Max 8 positions
    """
    if tranche_number < 1 or tranche_number > 3:
        return SizeResult(0.0, "invalid_tranche", {})

    if current_position_count >= MAX_POSITIONS and tranche_number == 1:
        return SizeResult(0.0, "max_positions_reached", {"max_positions": 0.0})

    fraction = TRANCHE_FRACTIONS[tranche_number - 1]
    max_position = total_portfolio_value * MAX_POSITION_PCT_TOTAL

    constraint_1 = fraction * max_position
    constraint_2 = adv_60d * MAX_PCT_OF_ADV
    sleeve_e_remaining = (total_portfolio_value * MAX_SLEEVE_E_PCT_TOTAL) - current_sleeve_e_value
    constraint_3 = max(sleeve_e_remaining, 0.0)

    constraints = {
        "tranche_fraction": constraint_1,
        "adv_limit": constraint_2,
        "sleeve_remaining": constraint_3,
    }

    amount = min(constraint_1, constraint_2, constraint_3)

    if amount < BROKER_FRACTIONAL_MINIMUM:
        return SizeResult(0.0, "below_broker_minimum", constraints)

    binding = min(constraints, key=constraints.get)
    return SizeResult(amount, binding, constraints)


def exit_rules(
    state: TrancheState,
    facts: ExitFacts,
    manipulation_flags_triggered: list[str] | None = None,
) -> ExitResult:
    """Evaluate exit rules. E1 graduation is the SUCCESS case.

    E1: cap > $3B, analysts >= 6, score >= 70 => graduate to Sleeve C.
    E2: thesis break (durability collapsed).
    E3: score < 55 twice.
    E4: manipulation flag triggered => exit REGARDLESS of P&L.
    E5: liquidity dried up.
    E6: corporate action.
    """
    if manipulation_flags_triggered:
        return ExitResult(
            should_exit=True,
            rule=ExitRule.E4_MANIPULATION,
            explanation=f"manipulation flags: {', '.join(manipulation_flags_triggered)}",
            is_success=False,
        )

    if (
        facts.market_cap is not None
        and facts.market_cap > 3e9
        and (facts.analyst_count or 0) >= 6
        and facts.score >= 70
    ):
        return ExitResult(
            should_exit=True,
            rule=ExitRule.E1_GRADUATION,
            explanation="graduated to Sleeve C: cap > $3B, analysts >= 6, score >= 70",
            is_success=True,
        )

    if facts.durability < 20:
        return ExitResult(
            should_exit=True,
            rule=ExitRule.E2_THESIS_BREAK,
            explanation=f"durability collapsed to {facts.durability:.1f}",
            is_success=False,
        )

    if facts.score_below_55_count >= 2:
        return ExitResult(
            should_exit=True,
            rule=ExitRule.E3_SCORE_BELOW_55_TWICE,
            explanation=f"score below 55 on {facts.score_below_55_count} occasions",
            is_success=False,
        )

    if facts.adv_60d is not None and facts.adv_60d < 500_000:
        return ExitResult(
            should_exit=True,
            rule=ExitRule.E5_LIQUIDITY,
            explanation=f"ADV dried up to ${facts.adv_60d:,.0f}",
            is_success=False,
        )

    if facts.has_corporate_action:
        return ExitResult(
            should_exit=True,
            rule=ExitRule.E6_CORPORATE_ACTION,
            explanation="corporate action requires exit",
            is_success=False,
        )

    return ExitResult(should_exit=False, rule=None, explanation="no exit rule triggered")


DOSSIER_SECTIONS = [
    "business_description",
    "neglect_reason",
    "sub_scores",
    "reverse_dcf",
    "dd_and_short_interest",
    "manipulation_checks",
    "bear_case",
    "biggest_risks",
    "mistake_blank",
]


@dataclass
class Dossier:
    """Discovery dossier with all nine sections."""

    ticker: str
    sections: dict[str, str]

    @property
    def is_complete(self) -> bool:
        return all(s in self.sections for s in DOSSIER_SECTIONS)

    @property
    def missing_sections(self) -> list[str]:
        return [s for s in DOSSIER_SECTIONS if s not in self.sections]
