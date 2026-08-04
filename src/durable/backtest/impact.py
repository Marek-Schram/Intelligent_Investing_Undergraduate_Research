"""Almgren-Chriss market impact. TICKET-044.

Our previous cost model used flat slippage tiers, which understates cost precisely where it
matters most: thin Sleeve E names where a position can be a meaningful fraction of daily volume.

Almgren-Chriss decomposes execution cost into a TEMPORARY component (the price you push while
trading, which reverts) and a PERMANENT component (the information your trading reveals, which
does not). See docs/13 section 2.4.
"""

from __future__ import annotations

# Calibration constants. These are conservative retail-scale defaults, deliberately
# pessimistic. Publish the values used in methodology.md -- an impact model is an
# assumption, not a measurement, and the reader must be able to re-run with their own.
ETA = 2.5e-6      # temporary impact coefficient
GAMMA = 2.5e-7    # permanent impact coefficient
ALPHA = 0.5       # power on participation rate; 0.5 = the classic square-root law


def participation_rate(shares: float, adv_shares: float) -> float:
    """Order size as a fraction of average daily volume.

    Sizing rules keep Sleeve C under ~1% and Sleeve E under 1% of ADV, so impact should be
    small -- but "should be" is a hypothesis the cost model exists to test.
    """
    raise NotImplementedError("TICKET-044")


def temporary_impact(participation: float, volatility: float, eta: float = ETA) -> float:
    """Temporary impact in basis points: eta * sigma * participation**alpha.

    Square-root scaling means doubling order size raises cost ~1.41x, not 2x. This is why
    splitting a Sleeve E tranche across sessions genuinely helps, and why the staged
    40/30/30 entry has an execution benefit on top of its behavioral one.
    """
    raise NotImplementedError("TICKET-044")


def permanent_impact(participation: float, volatility: float, gamma: float = GAMMA) -> float:
    """Permanent impact: linear in participation. This portion does NOT revert."""
    raise NotImplementedError("TICKET-044")


def total_cost_bps(
    shares: float,
    price: float,
    adv_shares: float,
    volatility: float,
    half_spread_bps: float,
    multiplier: float = 1.0,
) -> float:
    """Half-spread + temporary + permanent impact, in basis points.

    `multiplier` drives the 1x / 2x / 3x sensitivity runs required by PROTOCOL section 4.
    If the edge disappears at 2x, it was never an edge.
    """
    raise NotImplementedError("TICKET-044")
