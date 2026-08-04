"""Portfolio construction. SPEC sections 6-7.

select_holdings(scores, current_holdings, target=20, buffer_rank=60) -> list[str]
    Buffer-zone selection. The buffer is the single biggest turnover reducer in the design --
    a strict top-20 rule churns far more than it earns after costs and taxes.
target_weights(selected, sectors, max_position=0.06, max_sector=0.25) -> Series
    Equal weight, caps, renormalize. Fewer than 15 qualifying names => weights sum to < 1.0
    and hold cash. An empty screen is information, not a problem to engineer around.
"""

from __future__ import annotations
