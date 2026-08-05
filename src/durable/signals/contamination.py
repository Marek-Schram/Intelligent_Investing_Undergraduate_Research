"""LLM contamination measurement. TICKET-045.

Adapted from the Look-Ahead-Bench methodology: distinguish genuine predictive capability from
memorization by analyzing **performance decay across temporally distinct regimes** -- in our
case, across the model's training cutoff.

The premise (docs/13 section 1): an LLM pretrained on financial commentary has read what
happened. Asked about a pre-cutoff period it may recite a memorized outcome rather than infer.
If our extraction-derived features are contaminated, they will perform conspicuously better
before the cutoff than after it.

We cannot prevent this. We CAN measure it, and reporting a measured contamination estimate is
far more honest than asserting the features are clean.

Data source: feature IC timeseries.
available_at logic: N/A (validation artifact).
Spec section: docs/13 §1.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, mannwhitneyu


@dataclass(frozen=True)
class ContaminationResult:
    model_version: str
    training_cutoff: pd.Timestamp
    pre_cutoff_ic: float
    post_cutoff_ic: float
    ic_decay: float              # pre - post
    decay_pvalue: float
    n_pre: int
    n_post: int
    verdict: str                 # "clean" | "suspected" | "contaminated" | "insufficient_data"


def _compute_ic_series(
    feature: pd.DataFrame,
    forward_returns: pd.DataFrame,
) -> pd.Series:
    """Compute cross-sectional Spearman IC per date."""
    dates = feature.index.intersection(forward_returns.index)
    ics = {}
    for dt in dates:
        f_row = feature.loc[dt].dropna()
        r_row = forward_returns.loc[dt].dropna()
        common = f_row.index.intersection(r_row.index)
        if len(common) >= 5:
            corr, _ = spearmanr(f_row[common], r_row[common])
            if not np.isnan(corr):
                ics[dt] = corr
    return pd.Series(ics, dtype=float)


def alpha_decay_test(
    feature: pd.DataFrame,
    forward_returns: pd.DataFrame,
    training_cutoff: pd.Timestamp,
    model_version: str,
) -> ContaminationResult:
    """Compare feature IC before vs after the model's training cutoff.

    Verdicts:
      - `insufficient_data` if either side has < 8 periods.
      - `contaminated` if pre-cutoff IC exceeds post-cutoff IC by more than 50% AND
        the difference is significant at p < 0.05.
      - `suspected` if the gap is large but not significant.
      - `clean` otherwise -- "we looked and found no evidence", NOT "proven clean".
    """
    ic_series = _compute_ic_series(feature, forward_returns)

    pre = ic_series[ic_series.index <= training_cutoff]
    post = ic_series[ic_series.index > training_cutoff]

    if len(pre) < 8 or len(post) < 8:
        return ContaminationResult(
            model_version=model_version,
            training_cutoff=training_cutoff,
            pre_cutoff_ic=float(pre.mean()) if len(pre) > 0 else 0.0,
            post_cutoff_ic=float(post.mean()) if len(post) > 0 else 0.0,
            ic_decay=0.0,
            decay_pvalue=1.0,
            n_pre=len(pre),
            n_post=len(post),
            verdict="insufficient_data",
        )

    pre_mean = float(pre.mean())
    post_mean = float(post.mean())
    ic_decay_val = pre_mean - post_mean

    _, pvalue = mannwhitneyu(pre.values, post.values, alternative="greater")
    pvalue = float(pvalue)

    if post_mean > 0 and pre_mean > post_mean * 1.5 and pvalue < 0.05:
        verdict = "contaminated"
    elif post_mean > 0 and pre_mean > post_mean * 1.5:
        verdict = "suspected"
    elif pre_mean > 0 and post_mean <= 0 and pvalue < 0.05:
        verdict = "contaminated"
    else:
        verdict = "clean"

    return ContaminationResult(
        model_version=model_version,
        training_cutoff=training_cutoff,
        pre_cutoff_ic=pre_mean,
        post_cutoff_ic=post_mean,
        ic_decay=ic_decay_val,
        decay_pvalue=pvalue,
        n_pre=len(pre),
        n_post=len(post),
        verdict=verdict,
    )


def placebo_test(
    feature: pd.DataFrame,
    forward_returns: pd.DataFrame,
    n_shuffles: int = 1000,
    seed: int = 42,
) -> dict:
    """Shuffle ticker labels within each date and recompute IC.

    If shuffled IC is comparable to real IC, the signal is a panel artifact.
    Seeds pinned for reproducibility.
    """
    real_ic = _compute_ic_series(feature, forward_returns)
    real_mean = float(real_ic.mean()) if len(real_ic) > 0 else 0.0

    rng = np.random.default_rng(seed)
    shuffled_means = []

    for _ in range(n_shuffles):
        shuffled = feature.copy()
        for dt in shuffled.index:
            row = shuffled.loc[dt].dropna()
            vals = row.values.copy()
            rng.shuffle(vals)
            shuffled.loc[dt, row.index] = vals

        shuffled_ic = _compute_ic_series(shuffled, forward_returns)
        if len(shuffled_ic) > 0:
            shuffled_means.append(float(shuffled_ic.mean()))

    if not shuffled_means:
        return {"real_ic": real_mean, "shuffled_mean": 0.0, "pvalue": 1.0, "is_artifact": False}

    shuffled_arr = np.array(shuffled_means)
    pvalue = float(np.mean(shuffled_arr >= real_mean))

    return {
        "real_ic": real_mean,
        "shuffled_mean": float(shuffled_arr.mean()),
        "shuffled_std": float(shuffled_arr.std()),
        "pvalue": pvalue,
        "is_artifact": pvalue > 0.05,
    }


IDENTITY_MARKERS = [
    "ticker", "symbol", "company name", "NYSE:", "NASDAQ:",
    "Inc.", "Corp.", "Ltd.", "LLC",
]


def entity_anonymization_check(prompt: str) -> tuple[bool, str]:
    """Does the extraction prompt leak the company identity?

    Returns (is_anonymous, explanation).
    """
    prompt_lower = prompt.lower()
    found = []
    for marker in IDENTITY_MARKERS:
        if marker.lower() in prompt_lower:
            found.append(marker)

    if found:
        return False, f"identity markers found: {', '.join(found)}"
    return True, "no identity markers detected"
