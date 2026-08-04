# 06 — Claude Code Playbook

## 1. First session
```bash
cd durable-alpha && git init && git add -A && git commit -m "scaffold"
claude
```
`/init` — then prune what it generates. `CLAUDE.md` is already written and must stay under ~200
lines; past that, content is silently dropped and Claude starts improvising.

Verify: `What rules, skills, subagents, and hooks are available?`
Expect **8 rules, 11 skills, 9 subagents, 4 hooks.** Check hooks with `/hooks`.

### MCP servers (5-6, not 15)
```bash
claude mcp add filesystem --scope project -- npx -y @modelcontextprotocol/server-filesystem .
claude mcp add financial-datasets --scope user -- npx -y financial-datasets-mcp
claude mcp add fred --scope user -- npx -y @modelcontextprotocol/server-fred
```
Add Zotero when you start the literature work. `openbb-mcp-server` is optional — see the AGPL
note in docs/02 §7. Prune anything unused for two weeks.

## 2. The working loop
```
Read specs/BUILD_TICKETS.md TICKET-002 and docs/00_STRATEGY_SPEC.md §2.
Plan before writing code — files, signatures, tests. Don't write code yet.
```
Review, then: *"Implement the plan. Write the test first with the hand-computed fixture from the
ticket. Run `make test`. Stop after this ticket."*

Commit. **Fresh session per ticket.** Long sessions degrade as context fills.

Plan mode (`Shift+Tab`) before any work in `execution/`, `data/`, or `tax/`.

## 3. Subagents
| Subagent | Invoke when |
|---|---|
| `data-engineer` | ingestion, schema, PIT joins, the firewall |
| `factor-researcher` | implementing a score; IC analysis; evidence questions |
| `backtest-validator` | **adversarial** — look-ahead, survivorship, overfitting, contamination |
| `filing-analyst` | reading a 10-K, red flags, risk-factor deltas |
| `bear-analyst` | **adversarial** — the strongest case against a position |
| `performance-analyst` | interpreting results, attribution, uncertainty, narrative |
| `discovery-scout` | Sleeve E hunting and fraud screening |
| `research-methodologist` | study design, preregistration, CPCV/PBO, write-up |
| `tax-strategist` | lots, harvesting, wash sales, after-tax |

**The three adversarial ones carry most of the value.** Use them at every phase boundary:
```
Use the backtest-validator subagent. Its job is to break my backtest. Look for look-ahead,
survivorship bias, unlogged tuning, adjusted-close prices, and LLM contamination. Assume I
made mistakes. Rank findings by severity. Do not fix.
```
```
Use the bear-analyst subagent on TICKER. You are a short-seller. Make the strongest honest
case this position is a mistake. Cite filings. End with three falsifiers.
```
```
Use the research-methodologist subagent. Review preregistration.md against what I actually
tested. Did I HARK? Are all runs logged? Tell me where I'm overclaiming.
```

## 4. Skills
`durability-score` · `run-backtest` · `validate-strategy` (CPCV/PBO) · **`factor-ic`** ·
`quarterly-rebalance` · `performance-report` · `discover-candidates` · **`adversarial-review`** ·
`extract-filing` · `tax-review` · `decision-journal`

Invoke naturally: *"Run IC analysis on the ROIC factor."* · *"Run an adversarial review on
TICKER before I buy."*

## 5. Hooks — the deterministic layer
CLAUDE.md is a suggestion; hooks always run. See `.claude/hooks/README.md`. If a hook blocks
you, it returns the reason — read it rather than working around it. If a block is genuinely
wrong, fix the hook in a separate commit with a written justification, never inline.

## 6. Prompts that work
**Too-good result:**
```
My backtest shows 19% CAGR vs 10% for SPY. Before I believe this, audit for look-ahead:
fundamentals join keys, firewall coverage on every path, 13F/STOCK Act/short interest using
filing dates, adjusted-close prices anywhere, delisting returns, per-date universe rebuild,
and whether any LLM feature predates the model's training cutoff. List findings; don't fix.
```
**Weekly Routine (cloud, laptop closed):**
```
/schedule weekly Monday 7am: run `make report TYPE=pulse` and `make leakage-audit`, commit
output to reports/, open a PR if any kill criterion moved to WARN or FAIL or any firewall
violation appeared. Do not modify code outside reports/.
```
**Never a Routine:** anything that submits orders.

## 7. Anti-patterns
| Anti-pattern | Why it hurts here |
|---|---|
| "Build the whole system" in one prompt | 3,000 unauditable lines where silent bugs look like profits |
| Letting Claude pick metric definitions | The same company has ~8 published P/E values on one day |
| Accepting a result without an ablation | You'll credit the political overlay for factor returns |
| Judging a factor by portfolio return | Construction can rescue a factor with zero IC |
| Backtesting while still designing | Violates the Second Law; guarantees overfitting |
| Trusting an LLM extraction without a citation | That's how a hallucination becomes a position |
| Adopting a popular agent framework wholesale | See docs/13 — popularity tracks excitement, not evidentiary standards |

## 8. Git discipline
One ticket per branch, one PR, squash-merge · commit snapshot IDs for any reported backtest ·
tag phases `v0.1-data` → `v0.6-paper` · `reports/experiment_log.csv` committed forever,
including failures · research bulletins committed and never edited — a correction gets a new
dated bulletin rather than rewriting history.
