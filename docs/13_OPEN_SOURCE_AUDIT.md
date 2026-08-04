# 13 — Open-Source Tooling Audit

A survey of what the open-source community has built for LLM-driven and quantitative trading,
what we adopted, and — more importantly — **what we rejected and why.**

Reviewed August 2026. This document is itself a research artifact: the rejections are
defensible findings about method, not just build decisions.

---

## 0. Plain-English version

Lots of people have built AI trading systems and put them on GitHub. Some have tens of
thousands of stars. It would be easy to just grab the most popular one and use it.

But when you read the research carefully, most of the flashy LLM trading frameworks have a
fatal problem: **the AI already knows what happened.** It was trained on news articles and
market commentary from the period you're testing on. So when it "predicts" that a stock went
up in 2023, it might just be remembering. Their impressive backtests are largely measuring
memory, not skill.

So we took the boring, careful parts — the leakage detection, the factor validation math, the
safety enforcement — and left the exciting parts alone.

---

## 1. The finding that shaped every decision here

**LLM trading agents cannot be honestly backtested on periods before their training cutoff.**

This is not a minor caveat. FINSABER, a rigorous evaluation framework, ran systematic backtests
over **two decades and 100+ symbols** and found that "previously reported LLM advantages
deteriorate significantly under broader cross-section and over a longer-term evaluation."
Their regime analysis found LLM strategies are **overly conservative in bull markets,
underperforming passive benchmarks, and overly aggressive in bear markets, incurring heavy
losses** <cite>turn7search301</cite>.

The mechanism is structural, not fixable with better prompting. LLMs are pretrained on corpora
containing post-hoc explanations of market events. Asked about "NVIDIA's performance in 2023,"
a model may have been trained on text stating "NVIDIA surged 190% in 2023 on AI boom" — it does
not learn a predictive relationship, it memorizes the outcome and recites it
<cite>turn7search304</cite>. Backtested returns then collapse once the model's knowledge window
ends and trading enters genuinely unknown territory <cite>turn7search304</cite>.

A widely-shared critique of the most popular framework puts it bluntly: with standard models
you can freeze data, control features, and do proper walk-forward validation. With LLMs you do
not control the training corpus, do not know which market narratives were absorbed, and
**cannot "untrain" future knowledge** — which makes historical evaluation structurally
ill-posed <cite>turn7search302</cite>. That same critique notes the flagship paper's backtest
window was roughly three months, which "cannot cover different regimes, cannot reveal drawdown
behavior, cannot estimate tail risk" <cite>turn7search302</cite>.

**Consequence for us:** our design decision to use LLMs for *citation-backed extraction* rather
than prediction was correct, and `docs/10 §1` should be read as validated by this literature
rather than merely cautious. `.claude/rules/llm-extraction.md` rule 7 (contamination guard) is
the operational expression of it.

---

## 2. Adopted

### 2.1 Hooks for deterministic safety — **adopted, high value**
Claude Code hooks are shell commands, prompts, or subagents that fire at lifecycle points, and
the key property is determinism: **"CLAUDE.md is a suggestion. Claude Code usually follows it,
but it's not guaranteed. Hooks are deterministic — they always run"**
<cite>turn7search288</cite>. `PreToolUse` can block a tool call outright; exit code 2 blocks and
returns the reason to Claude <cite>turn7search289</cite><cite>turn7search290</cite>.

Implemented in `.claude/hooks/`: blocks `.env` edits, blocks flipping `live_trading_approved`,
blocks weakening Sleeve E caps, blocks `reporting/research/tax` importing `execution`, blocks
order submission from an agent session, blocks deleting the audit trail, auto-formats Python,
and surfaces KILL / RECONCILE_FAILED at end of turn.

This is the single highest-value addition from the survey. Our repo's most dangerous failure
modes are silent config drift and leaked secrets — precisely the cases where "the model usually
remembers" is insufficient.

### 2.2 Leakage firewall — **adopted from `agent-backtest-lab`**
This project exists to audit LLM trading agents rather than to be one, and its component list
maps almost exactly onto our protocol: walk-forward with purged CV and embargo, combinatorial
purged K-fold, a **hard leakage firewall that refuses any date > as_of**, a **raw-only price
loader that refuses `Adj Close`**, reward-hacking detection via in-sample/out-of-sample Sharpe
drop, and Almgren-Chriss transaction-cost modeling <cite>turn7search303</cite>.

Two ideas we did not have and have now taken:

**a) A firewall as a separate assertion layer.** We enforce point-in-time via `store.as_of()`,
which is good, but a dedicated firewall that any data-returning function must pass through is
strictly stronger — it catches paths that bypass the store. See `src/durable/data/firewall.py`
and TICKET-042.

**b) Refusing adjusted-close-only loaders.** Adjusted series are *retroactively restated* every
time a split or dividend occurs, so a series downloaded today does not equal the series that
existed at the historical date. Using them silently leaks future corporate actions. We now
require raw OHLCV plus an explicit corporate-action table. A hook warns on `auto_adjust=True`.

### 2.3 Factor IC analysis — **adopted, genuine gap**
Alphalens surfaces the core statistics for judging a predictive factor: **information
coefficient analysis, quantile-based returns, turnover, and alpha decay**
<cite>turn7search286</cite><cite>turn7search282</cite>. Modern alternatives such as
`alphapurify` add 40+ preprocessing methods (winsorization, neutralization, standardization) and
factor-return attribution on a Polars core <cite>turn7search283</cite>.

**Why this was a real hole:** our backtest answered *"does this portfolio work?"* It never
answered *"is this factor actually predictive, and how fast does the signal decay?"* Those are
different questions, and the second is much harder to fool yourself about. A portfolio can look
fine because of construction (equal weighting, sector caps) while every underlying factor has
zero information content — our own randomization test in `docs/03 §6` was designed to detect
exactly that, and IC analysis is the direct measurement.

Implemented as `src/durable/factors/ic.py` (TICKET-043): Spearman rank IC, IC mean/std/IR,
t-stat, IC decay across horizons, quantile spreads, and factor autocorrelation for turnover
estimation. Note that Quantopian's original Alphalens is unmaintained since the company closed
<cite>turn7search284</cite>, so we implement the math ourselves rather than depend on a fork.

### 2.4 Almgren-Chriss market impact — **adopted, small upgrade**
Our cost model used flat slippage tiers. `agent-backtest-lab` models transaction cost plus
Almgren-style impact <cite>turn7search303</cite>. Adding a square-root impact term makes cost
scale with participation rate, which matters for Sleeve E where ADV is thin. TICKET-044.

### 2.5 Bull/Bear adversarial research — **adopted as a *technique*, not a framework**
TradingAgents' one genuinely transferable idea is the **structured dialectic**: Bull and Bear
researchers present competing theses and challenge each other's assumptions before a decision
is made <cite>turn7search277</cite>.

We take the structure and discard the autonomy. Implemented as the `adversarial-review` skill
and the `bear-analyst` subagent: before any buy, an agent argues the *short* case using only
filing evidence, and the memo must record it. This directly strengthens the existing
`disconfirming_evidence` requirement in the decision journal — which previously relied on the
user generating the counter-case unaided.

### 2.6 OpenBB as an optional data layer — **adopted with a licensing caveat**
OpenBB is a mature open data platform (71.4k stars) with free connectors for **SEC, FRED, BLS,
CFTC, IMF, OECD, and — notably — `openbb-congress-gov`**, plus an official
`openbb-mcp-server` package <cite>turn7search269</cite><cite>turn7search270</cite>.

Useful as a *convenience layer* for exploratory research and as an MCP server in Claude Code.
**But:** it is AGPL-3.0, described in one review as "a viral copyleft risk" if you modify it and
offer it as a service <cite>turn7search274</cite>. For a personal research project that is
fine; if this ever becomes something you distribute, that changes. Flagged in
`docs/02` and left as an optional dependency, never a required one — our production path stays
on `edgartools` where we control `available_at` precisely.

---

## 3. Rejected, with reasons

| Tool | Stars | Why we're not using it |
|---|---|---|
| **TradingAgents** | ~95k <cite>turn7search279</cite> | Multi-agent LLM trading firm simulation. Structurally unbacktestable per §1. Its own changelog documents shipping a look-ahead bug where "the dict-only guard skipped filtering and **future-dated reports leaked into historical runs**" <cite>turn7search280</cite> — in a framework whose entire value proposition is backtested performance. We take the bull/bear structure and nothing else. |
| **RD-Agent** (factor mining) | ~14k <cite>turn7search293</cite> | LLM-driven autonomous factor discovery: "automatically discover valuable factors... then automatically write code to validate" with "evolutionary" self-optimization until "a satisfactory result is achieved" <cite>turn7search298</cite>. That last clause is a p-hacking machine by construction. It directly violates the Second Law in `docs/09 §4` — never research under the influence of a backtest — and would make our Deflated Sharpe trial count unknowable. **Rejecting this is a methodological position, not a capacity limit.** |
| **Qlib** | ~47k <cite>turn7search295</cite> | Genuinely serious: MIT-licensed, full pipeline, and strict about eliminating look-ahead bias <cite>turn7search298</cite>. But it requires its own binary data format, the official data source has been offline at times, and "the data step is the real onboarding hurdle" <cite>turn7search296</cite>. We already have a DuckDB point-in-time store we control and understand. Adopting Qlib would mean re-solving the one problem we've already solved, in someone else's format. Revisit only if we ever need its ML model zoo. |
| **FinRobot / FinGPT** | ~7.7k <cite>turn7search257</cite> | Multi-agent equity research with LLM-driven forecasting and "market forecasting agents." Same contamination problem as §1. Its deterministic valuation engines (DCF, WACC, Monte Carlo) <cite>turn7search259</cite> are things we already implement ourselves and can therefore audit. |
| **FinRL** (reinforcement learning) | — <cite>turn7search262</cite> | RL for trading needs enormous sample counts on a non-stationary process. We have ~112 quarterly rebalances. This is the clearest possible case of a method-to-data mismatch. |
| **openbb-agents** | 1.3k <cite>turn7search272</cite> | Explicitly a "work-in-progress" R&D playground, last meaningful commits ~2 years ago <cite>turn7search272</cite>. The underlying OpenBB Platform is the useful part; the agent layer is not maintained. |
| **Alphalens (original)** | — | Unmaintained since Quantopian closed <cite>turn7search284</cite>. We implement the IC math directly (~200 lines) rather than depend on an abandoned package or a language-specific fork. |
| **Automated strategy generation of any kind** | — | Every "AI writes the strategy" tool shares one flaw: it decouples the hypothesis from the human who must live with it. `docs/12` requires preregistration and a falsifiable prediction with a stated confidence *before* testing. A generator that proposes ten thousand factors makes that impossible in principle. |

---

## 4. The pattern worth internalizing

Sorting the survey by star count gives almost exactly the inverse of sorting by usefulness to
this project. The 95k-star repo is unbacktestable. The 14k-star repo is a p-hacking engine. The
most valuable things found were an audit library with no stars to speak of
<cite>turn7search303</cite>, a benchmark paper measuring alpha decay across a training cutoff
<cite>turn7search304</cite>, and a shell-script hook system <cite>turn7search288</cite>.

**Popularity in this space tracks excitement, not evidentiary standards.** That is itself worth
a paragraph in the paper's discussion section.

---

## 5. What we now measure that we didn't before

| New capability | Ticket | Answers |
|---|---|---|
| Leakage firewall | 042 | "Did any data path bypass the point-in-time guard?" |
| Factor IC + decay | 043 | "Is this factor predictive at all, and for how long?" |
| Almgren-Chriss impact | 044 | "Does the edge survive realistic participation costs in thin names?" |
| Alpha-decay contamination test | 045 | "Does our LLM feature perform suspiciously better before its training cutoff?" |
| Bear-case requirement | 046 | "What is the strongest argument against this position?" |

The fourth is the one to watch. It is a direct adaptation of the Look-Ahead-Bench methodology —
analyzing **performance decay across temporally distinct regimes** to distinguish genuine
predictive capability from memorization <cite>turn7search304</cite>. If our extraction-based
features show a sharp performance drop after the model's training cutoff, we have measured our
own contamination rather than assumed it away.
