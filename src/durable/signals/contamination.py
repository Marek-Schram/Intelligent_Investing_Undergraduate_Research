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
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


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


def alpha_decay_test(
    feature: pd.DataFrame,
    forward_returns: pd.DataFrame,
    training_cutoff: pd.Timestamp,
    model_version: str,
) -> ContaminationResult:
    """Compare feature IC before vs after the model's training cutoff.

    Verdict thresholds:
      - `insufficient_data` if either side has < 8 periods. Say so; do not guess.
      - `contaminated` if pre-cutoff IC exceeds post-cutoff IC by more than 50% AND the
        difference is significant at p < 0.05.
      - `suspected` if the gap is large but not significant.
      - `clean` otherwise -- meaning "we looked and found no evidence", NOT "proven clean".

    Report the verdict verbatim in every research artifact that uses the feature. A `clean`
    verdict on a short post-cutoff sample is weak evidence and the report must say so.
    """
    raise NotImplementedError("TICKET-045")


def placebo_test(
    feature: pd.DataFrame,
    forward_returns: pd.DataFrame,
    n_shuffles: int = 1000,
    seed: int = 42,
) -> dict:
    """Shuffle the feature's ticker labels within each date and recompute IC.

    If shuffled IC is comparable to real IC, the "signal" is an artifact of the panel
    structure rather than anything about the companies. Cheap, and it catches a class of
    bug that survives every other check.
    """
    raise NotImplementedError("TICKET-045")


def entity_anonymization_check(prompt: str) -> tuple[bool, str]:
    """Does the extraction prompt leak the company identity?

    The Chicago Booth result that motivates our LLM use held with ANONYMIZED statements --
    no names, no narrative. Anonymity is what makes it analysis rather than recall.

    Where a task can be run anonymized, it should be: strip ticker, company name, and
    obvious identifiers from the prompt. Where it cannot -- risk-factor deltas need the
    prior year's filing -- record that the task is identity-dependent so the contamination
    verdict is interpreted accordingly.
    """
    raise NotImplementedError("TICKET-045")
