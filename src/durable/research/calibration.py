"""Calibration scoring. TICKET-039.

docs/12 section 2. Returns take a decade to become significant; calibration takes about a year.

brier_score(predictions) -> float. 0.25 = always saying 50%.
calibration_curve(predictions, bins=5) -> return bin COUNTS and flag sparse bins. Never smooth
    a sparse bin away -- that hides exactly the uncertainty this analysis exists to expose.
overconfidence_ratio(predictions) -> mean confidence / hit rate. >1.0 is the common result.
    Report it plainly and without softening. That is the point.
discrimination(predictions) -> do high-confidence calls beat low-confidence ones? A
    well-calibrated person who cannot discriminate is just accurately uncertain.
by_emotional_state(predictions) -> the finding that actually changes behavior.
override_performance(predictions, overrides_md) -> do overrides beat the system? If not after
    a meaningful sample, the recommendation is to stop overriding, stated directly.

Data source: journal entries with resolution.
available_at logic: N/A (research artifact).
Spec section: docs/12 §2.

PURE FUNCTIONS ONLY (up to the CLI section at the bottom): no I/O, network, wall-clock, or
config lookups. The CLI section reads research/journal/decisions.csv (durable.research.journal's
CSV serialization) and writes research/journal/calibration_<date>.md.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

SPARSE_BIN_THRESHOLD = 5


@dataclass(frozen=True)
class Prediction:
    """One resolved prediction for calibration."""

    confidence: int  # [50, 99]
    outcome: bool  # True = correct
    emotional_state: str = ""
    is_override: bool = False


@dataclass(frozen=True)
class CalibrationBin:
    """One bin of the calibration curve."""

    bin_lower: float
    bin_upper: float
    mean_confidence: float
    hit_rate: float
    count: int
    sparse: bool


@dataclass(frozen=True)
class CalibrationResult:
    """Full calibration analysis."""

    brier: float
    overconfidence_ratio: float
    discrimination: float
    bins: list[CalibrationBin]
    by_emotion: dict[str, float]
    override_hit_rate: float | None
    system_hit_rate: float | None
    n_predictions: int


def brier_score(predictions: list[Prediction]) -> float:
    """Brier score. 0 = perfect, 0.25 = always 50%, 1 = always wrong.

    BS = (1/N) * sum((confidence/100 - outcome)^2)
    """
    if not predictions:
        return 0.25
    total = 0.0
    for p in predictions:
        prob = p.confidence / 100.0
        total += (prob - float(p.outcome)) ** 2
    return total / len(predictions)


def calibration_curve(
    predictions: list[Prediction],
    n_bins: int = 5,
) -> list[CalibrationBin]:
    """Calibration curve with bin counts. Sparse bins flagged, never smoothed."""
    if not predictions:
        return []

    bin_width = (99 - 50) / n_bins
    bins: list[CalibrationBin] = []

    for i in range(n_bins):
        lower = 50 + i * bin_width
        upper = 50 + (i + 1) * bin_width if i < n_bins - 1 else 100

        in_bin = [
            p
            for p in predictions
            if lower <= p.confidence < upper or (i == n_bins - 1 and p.confidence == 99)
        ]
        count = len(in_bin)

        if count == 0:
            bins.append(
                CalibrationBin(
                    bin_lower=lower,
                    bin_upper=upper,
                    mean_confidence=0.0,
                    hit_rate=0.0,
                    count=0,
                    sparse=True,
                )
            )
        else:
            mean_conf = sum(p.confidence for p in in_bin) / count
            hit_rate = sum(1 for p in in_bin if p.outcome) / count
            bins.append(
                CalibrationBin(
                    bin_lower=lower,
                    bin_upper=upper,
                    mean_confidence=mean_conf / 100.0,
                    hit_rate=hit_rate,
                    count=count,
                    sparse=count < SPARSE_BIN_THRESHOLD,
                )
            )

    return bins


def overconfidence_ratio(predictions: list[Prediction]) -> float:
    """Mean confidence / hit rate. >1.0 = overconfident (the common result)."""
    if not predictions:
        return 1.0
    mean_conf = sum(p.confidence for p in predictions) / len(predictions) / 100.0
    hit_rate = sum(1 for p in predictions if p.outcome) / len(predictions)
    if hit_rate == 0:
        return float("inf")
    return mean_conf / hit_rate


def discrimination(predictions: list[Prediction]) -> float:
    """Do high-confidence calls beat low-confidence ones?

    Returns hit rate difference: high_conf_hit_rate - low_conf_hit_rate.
    Positive = discriminating. Zero = accurately uncertain but can't tell easy from hard.
    """
    if len(predictions) < 4:
        return 0.0

    median_conf = sorted(p.confidence for p in predictions)[len(predictions) // 2]
    high = [p for p in predictions if p.confidence >= median_conf]
    low = [p for p in predictions if p.confidence < median_conf]

    if not high or not low:
        return 0.0

    high_hit = sum(1 for p in high if p.outcome) / len(high)
    low_hit = sum(1 for p in low if p.outcome) / len(low)
    return high_hit - low_hit


def by_emotional_state(predictions: list[Prediction]) -> dict[str, float]:
    """Hit rate breakdown by emotional state. The finding that changes behavior."""
    states: dict[str, list[Prediction]] = {}
    for p in predictions:
        state = p.emotional_state or "unrecorded"
        states.setdefault(state, []).append(p)

    result = {}
    for state, preds in states.items():
        result[state] = sum(1 for p in preds if p.outcome) / len(preds)
    return result


def override_performance(predictions: list[Prediction]) -> tuple[float | None, float | None, str]:
    """Do overrides beat the system?

    Returns (override_hit_rate, system_hit_rate, recommendation).
    """
    overrides = [p for p in predictions if p.is_override]
    system = [p for p in predictions if not p.is_override]

    override_hr = sum(1 for p in overrides if p.outcome) / len(overrides) if overrides else None
    system_hr = sum(1 for p in system if p.outcome) / len(system) if system else None

    if override_hr is None or system_hr is None or len(overrides) < 10:
        recommendation = "insufficient sample to evaluate overrides"
    elif override_hr < system_hr:
        recommendation = "overrides underperform the system; consider stopping"
    elif override_hr > system_hr:
        recommendation = "overrides add value"
    else:
        recommendation = "no difference detected"

    return override_hr, system_hr, recommendation


def _parse_bool_outcome(raw: str) -> bool | None:
    """Map research/journal/decisions.csv's `resolved_correct` column to a strict bool.

    Returns None for values that are NOT binary (empty/unresolved, expired,
    partially_correct) -- those are excluded from Brier/calibration scoring rather than
    coerced into True or False, because a coerced "partially correct" would misrepresent
    the calibration data it's supposed to be measuring honestly.
    """
    value = (raw or "").strip().lower()
    if value in {"true", "correct", "1", "yes"}:
        return True
    if value in {"false", "incorrect", "0", "no"}:
        return False
    return None  # "", "unresolved", "expired", "partially_correct", or anything else


def _parse_bool_flag(raw: str) -> bool:
    return (raw or "").strip().lower() in {"true", "1", "yes"}


@dataclass(frozen=True)
class LoadedPredictions:
    """Result of loading research/journal/decisions.csv for calibration scoring."""

    predictions: list[Prediction]
    n_total_rows: int
    n_unresolved: int
    n_partially_correct: int
    n_expired: int


def load_predictions_from_journal(csv_path: str | Path) -> LoadedPredictions:
    """Load resolved decision-journal entries as calibration Predictions.

    Raises FileNotFoundError if the journal CSV doesn't exist -- "no journal yet" must be a
    clear, distinct message, not an empty result indistinguishable from "zero decisions
    logged so far in an existing, working journal."
    """
    csv_path = Path(csv_path)
    if not csv_path.is_file():
        raise FileNotFoundError(f"{csv_path} does not exist")

    with csv_path.open(newline="") as f:
        rows = list(csv.DictReader(f))

    predictions: list[Prediction] = []
    n_unresolved = 0
    n_partially_correct = 0
    n_expired = 0

    for row in rows:
        resolution_date = (row.get("resolution_date") or "").strip()
        raw_outcome = (row.get("resolved_correct") or "").strip()
        confidence_raw = (row.get("confidence") or "").strip()

        if not resolution_date or not raw_outcome:
            n_unresolved += 1
            continue
        if raw_outcome.strip().lower() == "expired":
            n_expired += 1
            continue
        if raw_outcome.strip().lower() == "partially_correct":
            n_partially_correct += 1
            continue

        outcome = _parse_bool_outcome(raw_outcome)
        if outcome is None:
            n_unresolved += 1
            continue
        if not confidence_raw:
            n_unresolved += 1
            continue

        try:
            confidence = int(float(confidence_raw))
        except ValueError:
            n_unresolved += 1
            continue
        if not (50 <= confidence <= 99):
            n_unresolved += 1
            continue

        predictions.append(
            Prediction(
                confidence=confidence,
                outcome=outcome,
                emotional_state=(row.get("emotional_state") or "").strip(),
                is_override=_parse_bool_flag(row.get("overrode_system", "")),
            )
        )

    return LoadedPredictions(
        predictions=predictions,
        n_total_rows=len(rows),
        n_unresolved=n_unresolved,
        n_partially_correct=n_partially_correct,
        n_expired=n_expired,
    )


def compute_calibration(predictions: list[Prediction]) -> CalibrationResult:
    """Full calibration analysis."""
    bs = brier_score(predictions)
    bins = calibration_curve(predictions)
    oc_ratio = overconfidence_ratio(predictions)
    disc = discrimination(predictions)
    by_emotion = by_emotional_state(predictions)
    override_hr, system_hr, _ = override_performance(predictions)

    return CalibrationResult(
        brier=bs,
        overconfidence_ratio=oc_ratio,
        discrimination=disc,
        bins=bins,
        by_emotion=by_emotion,
        override_hit_rate=override_hr,
        system_hit_rate=system_hr,
        n_predictions=len(predictions),
    )


# ---------------------------------------------------------------------------
# CLI entry point (impure). `python -m durable.research.calibration --score`
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# docs/12 §0: "Your returns won't be statistically meaningful for a decade. Your calibration
# will be measurable in about a year" — but even a year of ~20 decisions/year is a small
# sample. Below this many scored predictions, the summary must say so plainly rather than
# stating a verdict as if it were settled.
SMALL_SAMPLE_THRESHOLD = 20

# Overconfidence-ratio verdict bands. 1.0 is perfect calibration; docs/12 §2 and this
# module's own docstring say >1.0 (overconfident) is "the overwhelmingly common result" — the
# 0.05 band width is a plain-language rounding choice, not a statistical test.
_OVERCONFIDENT_ABOVE = 1.05
_UNDERCONFIDENT_BELOW = 0.95


def _overconfidence_verdict(ratio: float) -> str:
    if ratio == float("inf"):
        return "overconfident (0% hit rate recorded — every scored prediction was wrong)"
    if ratio > _OVERCONFIDENT_ABOVE:
        return f"overconfident (mean confidence exceeds hit rate by a factor of {ratio:.2f})"
    if ratio < _UNDERCONFIDENT_BELOW:
        return f"underconfident (hit rate exceeds mean confidence by a factor of {1 / ratio:.2f})"
    return f"well-calibrated (ratio {ratio:.2f}, within +/-{1 - _UNDERCONFIDENT_BELOW:.2f} of 1.0)"


def render_calibration_markdown(loaded: LoadedPredictions, as_of: date) -> str:
    """research/journal/calibration_<date>.md. Never uses 'proves'/'confirms'/'demonstrates'
    for the small samples this journal will have for years (research-integrity.md #9)."""
    result = compute_calibration(loaded.predictions)
    lines: list[str] = []
    lines.append(f"# Calibration — {as_of.isoformat()}")
    lines.append("")
    lines.append(
        f"Scored predictions: {result.n_predictions} (of {loaded.n_total_rows} journal rows). "
        f"Excluded: {loaded.n_unresolved} unresolved/unscoreable, "
        f"{loaded.n_partially_correct} partially correct, {loaded.n_expired} expired."
    )
    lines.append("")

    if result.n_predictions == 0:
        lines.append(
            "**No resolved, binary-scoreable predictions yet.** Nothing below is a finding — "
            "it is what zero data points looks like. Score predictions in "
            "`research/journal/decisions.csv` (see `durable.research.journal`) and re-run "
            "`make journal` once some have a `resolution_date` and a binary `resolved_correct`."
        )
        return "\n".join(lines) + "\n"

    if result.n_predictions < SMALL_SAMPLE_THRESHOLD:
        lines.append(
            f"**Small-sample banner.** {result.n_predictions} scored prediction(s) is well "
            f"below the ~{SMALL_SAMPLE_THRESHOLD}/year docs/12 §2 uses as a rough one-year "
            "mark. Nothing below should be read as a settled verdict on calibration."
        )
        lines.append("")

    lines.append("## Brier score")
    lines.append(
        f"{result.brier:.4f} (0 = perfect, 0.25 = always saying 50%, "
        "1 = always confidently wrong)."
    )
    lines.append("")

    lines.append("## Overconfidence ratio")
    lines.append(
        f"{result.overconfidence_ratio:.2f} — "
        f"{_overconfidence_verdict(result.overconfidence_ratio)}."
    )
    lines.append("")

    lines.append("## Discrimination")
    lines.append(
        f"{result.discrimination:.2f} (high-confidence hit rate minus low-confidence hit "
        "rate; positive = can tell easy calls from hard ones, ~0 = accurately uncertain but "
        "not discriminating, negative = high-confidence calls actually do worse)."
    )
    lines.append("")

    lines.append("## Calibration curve (sparse bins flagged, never smoothed)")
    lines.append("| bin | mean confidence | hit rate | count | sparse |")
    lines.append("|---|---|---|---|---|")
    for b in result.bins:
        sparse_flag = f"YES (< {SPARSE_BIN_THRESHOLD})" if b.sparse else "no"
        lines.append(
            f"| [{b.bin_lower:.0f}, {b.bin_upper:.0f}) | {b.mean_confidence:.2f} | "
            f"{b.hit_rate:.2f} | {b.count} | {sparse_flag} |"
        )
    lines.append("")

    lines.append("## By emotional state")
    if result.by_emotion:
        lines.append("| state | hit rate |")
        lines.append("|---|---|")
        for state, hr in sorted(result.by_emotion.items()):
            lines.append(f"| {state} | {hr:.2f} |")
    else:
        lines.append("No entries.")
    lines.append("")

    lines.append("## Override performance")
    _, _, recommendation = override_performance(loaded.predictions)
    override_hr = (
        f"{result.override_hit_rate:.2f}" if result.override_hit_rate is not None else "n/a"
    )
    system_hr = f"{result.system_hit_rate:.2f}" if result.system_hit_rate is not None else "n/a"
    lines.append(f"Override hit rate: {override_hr}. System hit rate: {system_hr}.")
    lines.append(f"Recommendation: {recommendation}.")
    lines.append("")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Score the decision journal for calibration (docs/12 §2) and write "
        "research/journal/calibration_<date>.md."
    )
    parser.add_argument(
        "--score", action="store_true", help="Run calibration scoring against the journal"
    )
    parser.add_argument(
        "--journal-csv",
        default=None,
        help="Override research/journal/decisions.csv path",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Override research/journal/ output directory",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="ISO date for the output filename (default: today)",
    )
    args = parser.parse_args(argv)

    if not args.score:
        parser.error("Specify --score to run calibration scoring.")

    journal_csv = (
        Path(args.journal_csv)
        if args.journal_csv
        else PROJECT_ROOT / "research" / "journal" / "decisions.csv"
    )
    out_dir = Path(args.out_dir) if args.out_dir else PROJECT_ROOT / "research" / "journal"
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    try:
        loaded = load_predictions_from_journal(journal_csv)
    except FileNotFoundError:
        print(
            f"{journal_csv} does not exist yet. Nothing has been logged to the decision "
            "journal — see durable.research.journal and docs/12 §2 to start recording "
            "decisions before calibration can be scored."
        )
        return 1

    if loaded.n_total_rows == 0:
        print(
            f"{journal_csv} exists but has no rows yet. Log at least one decision before "
            "scoring calibration."
        )
        return 1

    markdown = render_calibration_markdown(loaded, as_of)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"calibration_{as_of.isoformat()}.md"
    out_path.write_text(markdown)
    print(f"Wrote {out_path}")
    if loaded.predictions:
        result = compute_calibration(loaded.predictions)
        print(
            f"{result.n_predictions} scored predictions. Brier={result.brier:.4f}. "
            f"Overconfidence ratio={result.overconfidence_ratio:.2f} "
            f"({_overconfidence_verdict(result.overconfidence_ratio)})."
        )
    else:
        print("0 resolved, binary-scoreable predictions — see the written file for detail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
