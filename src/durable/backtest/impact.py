"""Almgren-Chriss market impact. TICKET-044.

Our previous cost model used flat slippage tiers, which understates cost precisely where it
matters most: thin Sleeve E names where a position can be a meaningful fraction of daily volume.

Almgren-Chriss decomposes execution cost into a TEMPORARY component (the price you push while
trading, which reverts) and a PERMANENT component (the information your trading reveals, which
does not). See docs/13 section 2.4.

Data source: prices, volume from PIT store.
available_at logic: N/A (cost model assumption).
Spec section: docs/13 §2.4.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

import math

# Calibration constants — conservative retail-scale defaults, deliberately pessimistic.
# Published in methodology.md. An impact model is an assumption, not a measurement.
ETA = 2.5e-6      # temporary impact coefficient
GAMMA = 2.5e-7    # permanent impact coefficient
ALPHA = 0.5       # power on participation rate; 0.5 = square-root law


def participation_rate(shares: float, adv_shares: float) -> float:
    """Order size as fraction of average daily volume."""
    if adv_shares <= 0:
        return 1.0
    return shares / adv_shares


def temporary_impact(
    participation: float,
    volatility: float,
    eta: float = ETA,
    alpha: float = ALPHA,
) -> float:
    """Temporary impact in bps: eta * sigma * participation**alpha.

    Square-root scaling: doubling size raises cost ~1.41x, not 2x.
    """
    return eta * volatility * (participation ** alpha) * 10_000


def permanent_impact(
    participation: float,
    volatility: float,
    gamma: float = GAMMA,
) -> float:
    """Permanent impact in bps: linear in participation. Does NOT revert."""
    return gamma * volatility * participation * 10_000


def total_cost_bps(
    shares: float,
    price: float,
    adv_shares: float,
    volatility: float,
    half_spread_bps: float,
    multiplier: float = 1.0,
) -> float:
    """Half-spread + temporary + permanent, in basis points.

    multiplier drives 1x/2x/3x sensitivity runs.
    """
    part = participation_rate(shares, adv_shares)
    temp = temporary_impact(part, volatility)
    perm = permanent_impact(part, volatility)
    total = half_spread_bps + temp + perm
    return total * multiplier
