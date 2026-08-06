"""Distance-to-default (Merton model). docs/10 section 3. TICKET-033.

Solves the two-equation Merton system for asset value and asset volatility:
  E = V*N(d1) - D*exp(-rT)*N(d2)
  sigma_E * E = sigma_V * V * N(d1)

where:
  d1 = (ln(V/D) + (r + sigma_V^2/2)*T) / (sigma_V * sqrt(T))
  d2 = d1 - sigma_V * sqrt(T)

Distance-to-default = (ln(V/D) + (mu - sigma_V^2/2)*T) / (sigma_V * sqrt(T))

NOT applied to financials (banks, insurance, REITs) — their capital structure
makes the model meaningless.

Non-convergence returns NaN and flags the ticker for manual review.
Uses NO new data source — equity price, volatility, debt from existing PIT store.

Data source: equity prices, balance sheet debt from PIT store.
available_at logic: all data filtered via store.as_of(as_of) upstream.
Spec section: docs/10 §3.

PURE FUNCTIONS ONLY: no I/O, network, wall-clock, or config lookups.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from scipy.optimize import fsolve
from scipy.stats import norm

FINANCIAL_SIC_RANGES = [
    (6000, 6999),  # Finance, Insurance, Real Estate
]

DD_THRESHOLD_EXCLUSION = 1.5
MAX_ITERATIONS = 200
CONVERGENCE_TOL = 1e-8


class DDFlag(Enum):
    OK = "ok"
    NON_CONVERGENCE = "non_convergence"
    FINANCIAL_EXCLUDED = "financial_excluded"
    MISSING_DATA = "missing_data"


@dataclass(frozen=True)
class DistanceToDefaultResult:
    """Distance-to-default result."""

    ticker: str
    dd: float  # NaN if non-convergence or excluded
    asset_value: float
    asset_volatility: float
    flag: DDFlag
    below_threshold: bool
    sic_code: int | None = None

    @property
    def is_valid(self) -> bool:
        return self.flag == DDFlag.OK and not math.isnan(self.dd)


def is_financial(sic_code: int | None) -> bool:
    """Check if SIC code is in the financials range (6000-6999)."""
    if sic_code is None:
        return False
    return any(lo <= sic_code <= hi for lo, hi in FINANCIAL_SIC_RANGES)


def _merton_system(
    params: tuple[float, float],
    equity_value: float,
    equity_volatility: float,
    debt: float,
    risk_free_rate: float,
    time_horizon: float,
) -> tuple[float, float]:
    """Two-equation Merton system.

    Unknowns: (V, sigma_V) — asset value and asset volatility.
    """
    V, sigma_V = params

    if V <= 0 or sigma_V <= 0:
        return (1e10, 1e10)

    d1 = (math.log(V / debt) + (risk_free_rate + sigma_V**2 / 2) * time_horizon) / (
        sigma_V * math.sqrt(time_horizon)
    )
    d2 = d1 - sigma_V * math.sqrt(time_horizon)

    # Equation 1: E = V*N(d1) - D*exp(-rT)*N(d2)
    eq1 = (
        V * norm.cdf(d1)
        - debt * math.exp(-risk_free_rate * time_horizon) * norm.cdf(d2)
        - equity_value
    )

    # Equation 2: sigma_E * E = sigma_V * V * N(d1)
    eq2 = sigma_V * V * norm.cdf(d1) - equity_volatility * equity_value

    return (eq1, eq2)


def solve_merton(
    equity_value: float,
    equity_volatility: float,
    debt: float,
    risk_free_rate: float = 0.05,
    time_horizon: float = 1.0,
    drift: float | None = None,
) -> tuple[float, float, bool]:
    """Solve the two-equation Merton system for (asset_value, asset_volatility).

    Returns (V, sigma_V, converged).
    """
    V_init = equity_value + debt
    sigma_V_init = equity_volatility * equity_value / V_init

    solution, info, ier, msg = fsolve(
        _merton_system,
        x0=(V_init, sigma_V_init),
        args=(equity_value, equity_volatility, debt, risk_free_rate, time_horizon),
        full_output=True,
        maxfev=MAX_ITERATIONS,
        xtol=CONVERGENCE_TOL,
    )

    V_sol, sigma_V_sol = solution
    converged = bool(ier == 1 and V_sol > 0 and sigma_V_sol > 0)

    return float(V_sol), float(sigma_V_sol), converged


def compute_distance_to_default(
    ticker: str,
    equity_value: float | None,
    equity_volatility: float | None,
    debt: float | None,
    sic_code: int | None = None,
    risk_free_rate: float = 0.05,
    time_horizon: float = 1.0,
    drift: float | None = None,
) -> DistanceToDefaultResult:
    """Compute distance-to-default using the Merton model.

    NOT applied to financials. Non-convergence returns NaN and flags.
    """
    if is_financial(sic_code):
        return DistanceToDefaultResult(
            ticker=ticker,
            dd=float("nan"),
            asset_value=0.0,
            asset_volatility=0.0,
            flag=DDFlag.FINANCIAL_EXCLUDED,
            below_threshold=False,
            sic_code=sic_code,
        )

    if equity_value is None or equity_volatility is None or debt is None:
        return DistanceToDefaultResult(
            ticker=ticker,
            dd=float("nan"),
            asset_value=0.0,
            asset_volatility=0.0,
            flag=DDFlag.MISSING_DATA,
            below_threshold=False,
            sic_code=sic_code,
        )

    if debt <= 0:
        return DistanceToDefaultResult(
            ticker=ticker,
            dd=float("inf"),
            asset_value=equity_value,
            asset_volatility=equity_volatility,
            flag=DDFlag.OK,
            below_threshold=False,
            sic_code=sic_code,
        )

    V, sigma_V, converged = solve_merton(
        equity_value, equity_volatility, debt, risk_free_rate, time_horizon, drift
    )

    if not converged:
        return DistanceToDefaultResult(
            ticker=ticker,
            dd=float("nan"),
            asset_value=V,
            asset_volatility=sigma_V,
            flag=DDFlag.NON_CONVERGENCE,
            below_threshold=False,
            sic_code=sic_code,
        )

    mu = drift if drift is not None else risk_free_rate
    dd = (math.log(V / debt) + (mu - sigma_V**2 / 2) * time_horizon) / (
        sigma_V * math.sqrt(time_horizon)
    )

    return DistanceToDefaultResult(
        ticker=ticker,
        dd=dd,
        asset_value=V,
        asset_volatility=sigma_V,
        flag=DDFlag.OK,
        below_threshold=dd < DD_THRESHOLD_EXCLUSION,
        sic_code=sic_code,
    )
