#!/usr/bin/env bash
# Stop hook: end-of-turn reminders that are easy to forget and expensive to skip.
set -uo pipefail
MSG=""
[ -f KILL ] && MSG="${MSG}KILL file present — execution paths are disabled. "
[ -f RECONCILE_FAILED ] && MSG="${MSG}RECONCILE_FAILED is set — submit is blocked until a human clears it. "
if [ -f reports/experiment_log.csv ]; then
  LINES=$(wc -l < reports/experiment_log.csv)
  [ "$LINES" -le 1 ] && MSG="${MSG}experiment_log.csv is empty — Deflated Sharpe and PBO are meaningless without logged trials. "
fi
[ -n "$MSG" ] && echo "NOTE: $MSG" >&2
exit 0
