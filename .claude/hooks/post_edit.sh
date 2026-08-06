#!/usr/bin/env bash
# PostToolUse: format and lint what was just written. Deterministic, every time.
set -uo pipefail
INPUT=$(cat)
FILE=$(printf '%s' "$INPUT" | grep -oE '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\(.*\)"$/\1/')
case "$FILE" in
  *.py)
    cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || true
    command -v uv >/dev/null 2>&1 && { uv run ruff format "$FILE" >/dev/null 2>&1; uv run ruff check --fix "$FILE" >/dev/null 2>&1; }
    ;;
esac
exit 0
