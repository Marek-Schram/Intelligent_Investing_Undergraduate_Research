"""Durability score. SPEC section 2. TICKET-006.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.

piotroski_f_score(facts) -> 0-9.  SPEC 2.1
roic_points(facts, sectors) -> 0-14.  SPEC 2.2. 5-year MEDIAN ROIC, sector-ranked. Median not
    latest: consistency is the durable signal; one year is noisy and gameable.
cash_and_safety_points(facts) -> 0-12.  SPEC 2.3
growth_durability_points(facts, sectors) -> 0-10.  SPEC 2.4. Stability, not rate.
red_flags(facts, extractions, distance_to_default, short_interest) -> penalty/flags/excluded.
    Twelve flags per SPEC 2.5, including DD and short interest.
durability_score(facts, sectors, as_of) -> 0-50. Routes SIC 6000-6499 to the 2.6 variant.
"""

from __future__ import annotations
