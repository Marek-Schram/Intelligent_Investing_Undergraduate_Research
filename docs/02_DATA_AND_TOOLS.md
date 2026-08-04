# 02 — Data Sources, APIs, and Tools

## 1. Stack
| Layer | Free (months 1-6) | Paid upgrade |
|---|---|---|
| Fundamentals | **edgartools** (SEC EDGAR, no key) | Sharadar Core US Equities |
| Prices | Alpaca free IEX (**raw OHLCV, never adjusted-only**) | Alpaca Algo Trader Plus, Norgate |
| PIT index membership | build from EDGAR | Norgate Platinum |
| Macro | FRED | same |
| Factor benchmarks | Ken French Data Library | same |
| Insider / 13F | **edgartools** | Sharadar |
| Short interest | **FINRA / NYSE / Nasdaq** | — |
| Credit spreads | **FINRA TRACE** | — |
| Congressional | House/Senate Stock Watcher · **openbb-congress-gov** | Quiver, FMP |
| Broker | **Alpaca paper** | Alpaca live, IBKR |
| Backtest | custom pandas + vectorbt | zipline-reloaded Pipeline |
| Validation | **custom CPCV + firewall** | — |
| Factor analysis | **custom IC module** | — |
| Analytics | quantstats · statsmodels · arch · pybrinson | same |
| Literature | Zotero + pyzotero + Better BibTeX | — |
| Optional platform | **OpenBB** (AGPL — see §7) | — |

**Spend $0 for at least six months.** Free EDGAR is enough to build and validate everything.

## 2. Broker
**Alpaca** — API-first, key-pair auth, no gateway process, free paper environment mirroring
production, commission-free US equities, fractional to $1. `alpaca-py`,
`TradingClient(..., paper=True)`. Limits: US equities/options/crypto, PFOF routing.

**IBKR** — global, nine asset classes, SmartRouting, at the cost of a TWS/Gateway process that
re-authenticates and drops. Start with Alpaca; move only when its limits actually bind.

## 3. Fundamentals
**edgartools** — free, no key, `set_identity("you@email.com")`. Financial statements, Form 4,
13F, 8-K, EDGAR full-text search. **Gives filing acceptance timestamps — exactly what
`available_at` needs.** This is why free EDGAR beats many paid aggregators for backtest
integrity; aggregators often serve today's restated number for a 2019 date.

**Sharadar** — the paid upgrade that matters: 150+ indicators, 16,000+ tickers back to 1997
covering 6,000 active and **10,000 delisted**, point-in-time with and without restatements.
Free tier covers the Dow 30 — enough to build and test your loader.

## 4. The price-data rule
**Never build on adjusted-close-only series.** Adjusted prices are retroactively restated on
every split and dividend, so a series downloaded today is not the series that existed at the
historical date — using one silently leaks future corporate actions. Load raw OHLCV plus an
explicit corporate-action table. `firewall.assert_raw_prices()` enforces it; a hook warns on
`auto_adjust=True`.

## 5. Lagged sources — use FILING dates
| Source | Access | Lag | Field |
|---|---|---|---|
| 13F | edgartools, free | **45 days** | `filed_at` |
| STOCK Act PTR | Stock Watcher, free | **45 days** | `filed_at` |
| Short interest | FINRA, free | **11+ business days** | `publication_date` |
| Credit spreads | TRACE, free | ~T+1 | trade date |
| Distance-to-default | computed | none | — (zero marginal data cost) |

## 6. Backtesting and validation
Custom pandas engine (primary) · **custom CPCV** (docs/09) · **custom IC** (docs/13 §2.3) ·
vectorbt for parameter sweeps · zipline-reloaded for phase-2 Pipeline research.
Analytics: quantstats · statsmodels (FF5+MOM, Newey-West) · arch.bootstrap (block bootstrap) ·
pybrinson (allocation/selection, cited formulas).

> **Ken French gotcha:** returns are **percent, not decimal** · multi-line header · monthly and
> annual tables stacked in one file · dates as `YYYYMM` integers. `pandas-datareader` returns a
> dict: `[0]` monthly, `[1]` annual.

## 7. OpenBB — optional, with a licence caveat
Mature open data platform with free connectors for SEC, FRED, BLS, CFTC, IMF, OECD, and
**congress-gov**, plus an official `openbb-mcp-server`. Genuinely useful for exploratory
research and as an MCP server in Claude Code.

**But it is AGPL-3.0**, described in review as a viral copyleft risk if you modify it and offer
it as a service. Fine for a personal research project; relevant if you ever distribute this.
Kept as an **optional** dependency — the production path stays on edgartools, where we control
`available_at` precisely. See docs/13 §2.6.

## 8. Claude Code surfaces
| Surface | Loads | Use for |
|---|---|---|
| `CLAUDE.md` | session start, cached | always-on context (keep under ~200 lines) |
| `.claude/rules/` | session start or on path match | hard constraints (8 files) |
| `.claude/skills/` | ~100 tokens; body on invoke | workflows (11 skills) |
| `.claude/agents/` | only when called, isolated context | delegated work (9 agents) |
| **`.claude/hooks/`** | **lifecycle events, deterministic** | **safety enforcement (4 hooks)** |

**MCP servers — 5-6, not 15:** Filesystem · edgartools built-in · Financial Datasets ·
Alpaca (paper) · FRED · Zotero. Optionally `openbb-mcp-server`.

**Scheduling:** Routines run on Anthropic's cloud with the laptop closed, minimum 1-hour
interval. Good: weekly pulse, weekly filing scan, quarterly literature sweep. **Never: orders.**

## 9. Tax plumbing
Wash sale: 61-day window, **across all accounts including IRAs and a spouse's**; disallowed loss
added to the replacement's basis, not lost. Losses offset gains dollar-for-dollar, then up to
**$3,000** of ordinary income, remainder carrying forward indefinitely. DRIP counts as a
purchase. *Not tax advice — encode mechanics, confirm with a CPA.*
