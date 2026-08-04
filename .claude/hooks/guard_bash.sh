#!/usr/bin/env bash
# PreToolUse guard for shell commands.
set -uo pipefail
INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | grep -oE '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\(.*\)"$/\1/')

block() { echo "BLOCKED by .claude/hooks/guard_bash.sh: $1" >&2; exit 2; }

# Never run live submission from an agent session
if printf '%s' "$CMD" | grep -qE 'execution\.submit|--i-have-read-the-proposal'; then
  block "Order submission is human-only (CLAUDE.md rule 4). Run it yourself, after reading the memo."
fi

# Never delete the audit trail
if printf '%s' "$CMD" | grep -qE 'rm .*(experiment_log|overrides\.md|decisions\.csv|snapshots)'; then
  block "That file is the audit trail. Deleting it invalidates Deflated Sharpe, PBO, and calibration."
fi

# Never print secrets
if printf '%s' "$CMD" | grep -qE '(cat|less|head|tail|echo).*\.env([^.]|$)'; then
  block "Printing .env would leak keys into the transcript."
fi

exit 0
