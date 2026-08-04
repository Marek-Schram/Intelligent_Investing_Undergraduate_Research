# Hooks

**CLAUDE.md is a suggestion. Hooks are deterministic — they always run.** Use CLAUDE.md for
guidance ("prefer boring pandas"). Use hooks for rules that must never be broken.

| Hook | Event | Enforces |
|---|---|---|
| `guard_write.sh` | PreToolUse (Write/Edit) | blocks `.env` edits · blocks `live_trading_approved: true` · blocks weakening Sleeve E caps · blocks `reporting/research/tax` importing `execution` · warns on adjusted-close loaders |
| `guard_bash.sh` | PreToolUse (Bash) | blocks order submission · blocks deleting the audit trail · blocks printing secrets |
| `post_edit.sh` | PostToolUse | ruff format + fix on every Python write |
| `session_check.sh` | Stop | surfaces KILL / RECONCILE_FAILED / empty experiment log |

Exit code `2` blocks the tool call and returns the message to Claude. Exit `0` allows it.

Install: hooks in `.claude/hooks/hooks.json` are picked up automatically for this project.
Verify with `/hooks` in a Claude Code session.

> Why this matters here: this repo has rules whose violation is silent and expensive — a
> flipped config flag, a leaked key, a widened position cap after a good quarter. Those are
> exactly the cases where "the model usually remembers" is not good enough.
