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

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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

        in_bin = [p for p in predictions if lower <= p.confidence < upper or (i == n_bins - 1 and p.confidence == 99)]
        count = len(in_bin)

        if count == 0:
            bins.append(CalibrationBin(
                bin_lower=lower, bin_upper=upper,
                mean_confidence=0.0, hit_rate=0.0,
                count=0, sparse=True,
            ))
        else:
            mean_conf = sum(p.confidence for p in in_bin) / count
            hit_rate = sum(1 for p in in_bin if p.outcome) / count
            bins.append(CalibrationBin(
                bin_lower=lower, bin_upper=upper,
                mean_confidence=mean_conf / 100.0,
                hit_rate=hit_rate,
                count=count,
                sparse=count < SPARSE_BIN_THRESHOLD,
            ))

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
