"""Narrative generator + honesty validator. TICKET-021.

Data source: performance metrics, attribution results, contribution data.
available_at logic: N/A (reporting artifact).
Spec section: docs/07, SPEC §9.

The part most likely to drift into marketing copy, so constraints are enforced in code.
The writer RAISES if validation fails — a narrative that fails validation does not get
written to disk.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

import re


class NarrativeValidationError(ValueError):
    """Raised when a narrative fails validation.

    The writer raises rather than writing a failing narrative.
    """


# Promotional / forward-looking phrases that must never appear.
BANNED_PHRASES: tuple[str, ...] = (
    "positioned to benefit",
    "expected to",
    "should continue",
    "poised for",
    "we believe",
    "looking ahead",
    "going forward",
    "strong conviction",
    "compelling opportunity",
    "proven track record",
    "multi-bagger",
    "next big thing",
    "significant upside",
    "substantial growth",
    "tremendous potential",
    "market-beating",
    "best-in-class",
    "world-class",
    "industry-leading",
)


def _check_banned_phrases(text: str) -> list[str]:
    """Check for banned promotional/forward-looking phrases."""
    violations = []
    text_lower = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in text_lower:
            violations.append(f"Banned phrase: '{phrase}'")
    return violations


def _check_outperformed_without_ci(text: str) -> list[str]:
    """'outperformed' must appear with a confidence interval nearby.

    A confidence interval is indicated by patterns like:
    - [X%, Y%]
    - (X% to Y%)
    - CI: ...
    - confidence interval
    - +/- or ±
    """
    violations = []
    # Find all occurrences of 'outperformed' (case-insensitive)
    pattern = re.compile(r"outperformed", re.IGNORECASE)
    ci_patterns = re.compile(
        r"(\[[-\d.]+%?\s*,\s*[-\d.]+%?\]"  # [X%, Y%]
        r"|\([-\d.]+%?\s*to\s*[-\d.]+%?\)"  # (X% to Y%)
        r"|CI\s*[:\(]"  # CI: or CI(
        r"|confidence\s+interval"  # confidence interval
        r"|\+/-"  # +/-
        r"|±"  # plus-minus symbol
        r"|p\s*[<>=]\s*0\.\d+"  # p < 0.05
        r"|\d+%\s*CI)",  # 95% CI
        re.IGNORECASE,
    )

    for match in pattern.finditer(text):
        # Look within a window of 200 characters around the match for CI context
        start = max(0, match.start() - 100)
        end = min(len(text), match.end() + 100)
        window = text[start:end]
        if not ci_patterns.search(window):
            violations.append("'outperformed' used without confidence interval context")
            break  # One violation is enough
    return violations


def _check_unqualified_alpha(text: str) -> list[str]:
    """'alpha' must be qualified with a t-stat, p-value, or significance statement.

    Acceptable qualifications:
    - t-stat, t = X, t-statistic
    - p-value, p < X
    - statistically (in)significant
    - CI or confidence interval
    - annualized alpha of X% (specific number)
    """
    violations = []
    # Match standalone 'alpha' (not part of another word like 'alphabetical')
    alpha_pattern = re.compile(r"\balpha\b", re.IGNORECASE)
    qualification_patterns = re.compile(
        r"(t[\s-]?stat"  # t-stat
        r"|t\s*=\s*[-\d.]+"  # t = 2.1
        r"|\|t\|\s*[>=<]"  # |t| > 2
        r"|p[\s-]?value"  # p-value
        r"|p\s*[<>=]\s*0\.\d+"  # p < 0.05
        r"|statistically"  # statistically (in)significant
        r"|insignificant"  # insignificant
        r"|not\s+significant"  # not significant
        r"|confidence\s+interval"  # confidence interval
        r"|\bCI\b"  # CI
        r"|±"  # plus-minus
        r"|\+/-"  # +/-
        r"|annualized\s+alpha\s+of\s+[-\d.]+%?"  # annualized alpha of X%
        r"|\balpha\s+of\s+[-\d.]+%?\s*\("  # alpha of X% (with CI following)
        r"|\balpha\b[^.]*\[[-\d.]+%?\s*,\s*[-\d.]+%?\])",  # alpha ... [X%, Y%]
        re.IGNORECASE,
    )

    for match in alpha_pattern.finditer(text):
        # Search within a sentence-like window (200 chars) around the match
        start = max(0, match.start() - 100)
        end = min(len(text), match.end() + 150)
        window = text[start:end]
        if not qualification_patterns.search(window):
            violations.append(
                "Unqualified 'alpha' — must include t-stat, p-value, or significance statement"
            )
            break  # One violation is enough
    return violations


def _check_negative_contributor(text: str) -> list[str]:
    """Narrative must name at least one negative contributor.

    Per reporting-honesty rule #5: 'Name losses as specifically as gains.
    Worst contributor by ticker.'
    """
    violations = []
    # Look for patterns indicating a negative contributor is named:
    # "detracted", "worst contributor", "negative contributor", "lost", "declined",
    # "cost the portfolio", "drag", "underperformed"
    negative_patterns = re.compile(
        r"(detract"
        r"|worst\s+contributor"
        r"|negative\s+contribut"
        r"|largest?\s+loss"
        r"|cost\s+the\s+portfolio"
        r"|drag\s+on"
        r"|underperform"
        r"|hurt\s+performance"
        r"|fell\s+\d"
        r"|declined?\s+\d"
        r"|lost\s+\d"
        r"|dropped\s+\d"
        r"|down\s+\d+%)",
        re.IGNORECASE,
    )
    if not negative_patterns.search(text):
        violations.append(
            "No negative contributor mentioned — must name worst contributor by ticker"
        )
    return violations


def validate_narrative(text: str, n_periods: int = 0) -> list[str]:
    """Validate a narrative for honesty and compliance.

    Returns a list of violation strings. Empty list means the narrative is valid.
    The writer RAISES NarrativeValidationError if this returns non-empty.

    Parameters
    ----------
    text : str
        The narrative text to validate.
    n_periods : int, optional
        Number of reporting periods (unused in validation itself, but available
        for context-dependent checks in the future).

    Returns
    -------
    list[str]
        List of violations. Empty means valid.
    """
    if not text or not text.strip():
        return ["Narrative is empty"]

    violations: list[str] = []
    violations.extend(_check_banned_phrases(text))
    violations.extend(_check_outperformed_without_ci(text))
    violations.extend(_check_unqualified_alpha(text))
    violations.extend(_check_negative_contributor(text))
    return violations


def generate_narrative(
    metrics: dict,
    attribution: dict,
    contributions: dict,
    context: dict | None = None,
) -> str:
    """Generate a 4-8 sentence narrative from performance data.

    Sentences:
    1. Result vs benchmark (never standalone)
    2. Brinson driver with sector named
    3. Since-inception excess WITH its CI
    4. Factor verdict with t-stat
    5. PBO
    6. Process health
    7. At least one thing that went wrong — names best AND worst contributor

    RAISES NarrativeValidationError if the generated narrative fails validation.
    A narrative that fails validation does not get written to disk.

    Parameters
    ----------
    metrics : dict
        Keys: total_return, benchmark_return, excess_return, ci_low, ci_high,
        inception_excess, inception_ci_low, inception_ci_high, factor_alpha,
        factor_tstat, pbo, n_periods
    attribution : dict
        Keys: top_sector, top_sector_effect, interaction_note
    contributions : dict
        Keys: best_ticker, best_contrib, worst_ticker, worst_contrib
    context : dict, optional
        Keys: process_health, kill_criteria_status

    Returns
    -------
    str
        Validated narrative text.

    Raises
    ------
    NarrativeValidationError
        If the generated text fails validation checks.
    """
    context = context or {}
    sentences = []

    # 1. Result vs benchmark
    total_ret = metrics["total_return"]
    bench_ret = metrics["benchmark_return"]
    excess = metrics.get("excess_return", total_ret - bench_ret)
    ci_low = metrics.get("ci_low")
    ci_high = metrics.get("ci_high")

    direction = "above" if excess > 0 else "below"
    if ci_low is not None and ci_high is not None:
        sentences.append(
            f"The portfolio returned {total_ret:+.2%} vs the benchmark's {bench_ret:+.2%}, "
            f"{abs(excess):.2%} {direction} "
            f"[{ci_low:+.2%}, {ci_high:+.2%}] 95% CI."
        )
    else:
        sentences.append(
            f"The portfolio returned {total_ret:+.2%} vs the benchmark's {bench_ret:+.2%} "
            f"(CI unavailable: N < 8 periods)."
        )

    # 2. Brinson driver
    top_sector = attribution["top_sector"]
    top_effect = attribution["top_sector_effect"]
    sentences.append(
        f"The primary Brinson driver was {top_sector} (selection effect {top_effect:+.2%})."
    )

    # 3. Since-inception excess with CI
    inc_excess = metrics.get("inception_excess")
    inc_ci_low = metrics.get("inception_ci_low")
    inc_ci_high = metrics.get("inception_ci_high")
    if inc_excess is not None and inc_ci_low is not None:
        sig = "significant" if (inc_ci_low > 0 or inc_ci_high < 0) else "not significant"
        sentences.append(
            f"Since inception, annualized excess is {inc_excess:+.2%} "
            f"[{inc_ci_low:+.2%}, {inc_ci_high:+.2%}] — statistically {sig}."
        )
    elif inc_excess is not None:
        sentences.append(
            f"Since inception, annualized excess is {inc_excess:+.2%} "
            f"(CI unavailable: N < 8 periods)."
        )

    # 4. Factor verdict with t-stat
    factor_alpha = metrics.get("factor_alpha")
    factor_tstat = metrics.get("factor_tstat")
    if factor_alpha is not None and factor_tstat is not None:
        sig_label = "|t| > 2" if abs(factor_tstat) > 2 else "|t| < 2"
        sentences.append(
            f"Factor-model alpha of {factor_alpha:+.2%} "
            f"(t-stat = {factor_tstat:.2f}, {sig_label})."
        )

    # 5. PBO
    pbo = metrics.get("pbo")
    if pbo is not None:
        sentences.append(f"PBO is {pbo:.2f}.")

    # 6. Process health
    process_health = context.get("process_health", "No process violations this period.")
    sentences.append(process_health)

    # 7. Best and worst contributor — must name both
    best = contributions["best_ticker"]
    best_c = contributions["best_contrib"]
    worst = contributions["worst_ticker"]
    worst_c = contributions["worst_contrib"]
    sentences.append(
        f"Best contributor: {best} ({best_c:+.2%}). "
        f"Worst contributor {worst} detracted {abs(worst_c):.2%} from returns."
    )

    narrative = " ".join(sentences)

    # Validate — RAISE if violations found
    violations = validate_narrative(narrative)
    if violations:
        raise NarrativeValidationError(f"Generated narrative failed validation: {violations}")

    return narrative
