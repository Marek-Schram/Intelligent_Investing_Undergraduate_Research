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
"""

from __future__ import annotations
