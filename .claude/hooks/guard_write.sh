#!/usr/bin/env bash
# PreToolUse guard. Blocks edits that would violate a hard safety rule.
# Hooks are DETERMINISTIC. CLAUDE.md is a suggestion; this is not.
# Exit 2 = block the tool call and tell Claude why.
set -uo pipefail
INPUT=$(cat)
FILE=$(printf '%s' "$INPUT" | grep -oE '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\(.*\)"$/\1/')
CONTENT=$(printf '%s' "$INPUT")

block() { echo "BLOCKED by .claude/hooks/guard_write.sh: $1" >&2; exit 2; }

# 1. Never touch secrets
case "$FILE" in
  *.env|*/.env|*.env.local|*/secrets*|*credentials*)
    block "Editing secrets files is forbidden. Use .env.example instead." ;;
esac

# 2. Never flip the live-trading flag
if printf '%s' "$CONTENT" | grep -qiE 'live_trading_approved[[:space:]]*:[[:space:]]*true'; then
  block "live_trading_approved is a HUMAN-ONLY flag (CLAUDE.md rule 1). Refusing."
fi

# 3. Never weaken Sleeve E safety constants
case "$FILE" in
  *discovery/universe.py|*discovery/tranche.py)
    if printf '%s' "$CONTENT" | grep -qE 'MAX_SLEEVE_E_PCT_TOTAL[[:space:]]*=[[:space:]]*0\.0[3-9]|MAX_POSITIONS[[:space:]]*=[[:space:]]*(9|[1-9][0-9])'; then
      block "Sleeve E caps are safety limits, not tunables (.claude/rules/speculation-limits.md)."
    fi ;;
esac

# 4. Reporting/research/tax must never import execution
case "$FILE" in
  *src/durable/reporting/*|*src/durable/research/*|*src/durable/tax/*)
    if printf '%s' "$CONTENT" | grep -qE 'from[[:space:]]+durable\.execution|import[[:space:]]+durable\.execution'; then
      block "This module must never import durable.execution — that guarantee is what makes scheduling safe."
    fi ;;
esac

# 5. Adjusted-close-only loaders are a silent leakage vector
if printf '%s' "$CONTENT" | grep -qE "Adj Close|adj_close_only|auto_adjust[[:space:]]*=[[:space:]]*True"; then
  echo "WARNING: adjusted-close series are retroactively restated. Use raw OHLCV plus an explicit corporate-action table. See docs/13." >&2
fi

# 6. Never disable the accounting invariants or execution sequencing (PROTOCOL 4.1)
if printf '%s' "$CONTENT" | grep -qiE 'assert_no_negative_cash[[:space:]]*:[[:space:]]*false|sequenced_execution[[:space:]]*:[[:space:]]*false|assert_nav_reconciles[[:space:]]*:[[:space:]]*false'; then
  block "Accounting invariants and sequenced execution are not optional. A simulation measured 11/54 negative-cash quarters without them (docs/01)."
fi

# 7. Never widen the turnover ceiling past kill criterion #4
if printf '%s' "$CONTENT" | grep -qE 'max_turnover_annual[[:space:]]*:[[:space:]]*(0\.[7-9]|1\.)'; then
  block "max_turnover_annual > 0.60 contradicts kill criterion #4 (PROTOCOL 7)."
fi

exit 0
