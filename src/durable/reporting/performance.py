"""Performance measurement and inference. TICKET-018/019.

Pure functions of committed data. No network at report time. Never imports execution/.

time_weighted_return(values, cash_flows) -> Series. GIPS-STYLE chain-linking. Measures the
    STRATEGY. Say "GIPS-style", never "GIPS-compliant".
money_weighted_return(values, cash_flows) -> float. IRR. Measures the INVESTOR's experience.
    Report both; the gap tells you whether your cash-flow timing helped.
bootstrap_ci(returns, statistic, n_boot=10000, block_size=None) -> (point, lo, hi)
    STATIONARY BLOCK bootstrap, not IID -- squared returns are highly persistent. Returns NaNs
    below 8 periods; callers print "(CI unavailable: N < 8 periods)".
sharpe_difference_test(returns, benchmark) -> Ledoit-Wolf. Jobson-Korkie/Memmel is invalid
    under fat tails. Different only if zero is outside the studentized bootstrap interval.
deflated_sharpe_ratio(returns, n_trials) -> float. n_trials from experiment_log.csv. RAISES if
    the log is missing -- defaulting to 1 silently inflates every result.
kill_criteria_status(ctx, metrics) -> all SIX criteria, PASS/WARN/FAIL. Every report.
"""

from __future__ import annotations
