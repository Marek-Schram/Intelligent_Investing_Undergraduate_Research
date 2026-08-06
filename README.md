# Durable Alpha

A rules-based, long-horizon equity system **and a research study**. It ranks US companies on
**business durability** and **valuation**, holds 15–25 names for years, hunts for under-followed
small caps in a tightly-capped side sleeve, optimizes after-tax returns, and — critically —
measures whether any of it actually works.

Built for **Claude Code**. Everything the agent needs is in `CLAUDE.md`, `.claude/`, `docs/`,
and `specs/`.

**✅ Status: 787 tests passing · 35 expected failures · ~10.8k lines of code**

---

## Three Ways to Read This

1. **[README_SIMPLE.md](README_SIMPLE.md)** - Start here if you're new to investing or quantitative strategies (written for a 12-year-old)
2. **This README** - Technical overview for developers and quant-curious folks
3. **[HOW_IT_WORKS.md](HOW_IT_WORKS.md)** - Deep dive into the algorithms, validation methods, and design decisions

Prefer clicking buttons to typing commands? Run `make gui` and see **[GUI_GUIDE.md](GUI_GUIDE.md)**
— a browser front end for every command below, with a guided step order and no command-line
knowledge required.

---

## The idea in one paragraph

Buy about 20 financially strong, reasonably priced businesses and hold them for years. A
checklist picks them: *is this a good business* (Piotroski F-Score, ROIC consistency, cash
conversion, twelve forensic red flags including Merton distance-to-default and crowded short
interest), *is the price sane* (EV/EBIT, FCF yield to EV, shareholder yield, and a reverse-DCF
solving for the growth the price already implies), and *is the market agreeing yet* (12-1
momentum, 200-day trend). Insider purchases, congressional disclosures, and concentrated 13F
holdings act as capped tie-breakers, each logged separately so the backtest can prove whether
they add anything.

**Sleeves C and E together manage 10% of the portfolio.** The rest is index funds, a factor-ETF
tilt, and short bonds. If every idea here is wrong, you lose a tuition bill.

---

## Quick start

```bash
uv sync
cp .env.example .env                          # SEC identity + Alpaca PAPER + FRED
cp config/config.example.yaml config/config.yaml
claude                                        # open Claude Code here
```
Then: `Read specs/BUILD_TICKETS.md and start TICKET-001. Plan before you write code.`

Verify the agent surfaces loaded — expect **8 rules, 11 skills, 9 subagents, 4 hooks**.

Want a GUI instead of the command line? `make gui` opens a browser interface with every command
above as a guided, numbered step — see [GUI_GUIDE.md](GUI_GUIDE.md).

---

## What's in here

| Path | Contents |
|---|---|
| `CLAUDE.md` | Always-on context, under 200 lines on purpose |
| **`.claude/hooks/`** | **Deterministic enforcement** — blocks `.env` edits, config flips, cap weakening, forbidden imports, order submission |
| `.claude/rules/` | 8 path-scoped hard constraints |
| `.claude/agents/` | 9 subagents — three adversarial: **backtest-validator**, **bear-analyst**, **research-methodologist** |
| `.claude/skills/` | 11 workflows including `validate-strategy` (CPCV), `factor-ic`, `adversarial-review` |
| `docs/00–08` | Spec · architecture · data · protocol · risk · roadmap · playbook · reporting · discovery |
| `docs/09–14` | CPCV & IC · signals · tax · research workflow · open-source audit · **simulation findings** |
| `specs/BUILD_TICKETS.md` | **49 tickets** with acceptance criteria |
| `research/` | Preregistration (7 hypotheses), claims ledger, decision journal, paper outline |

---

## Six capabilities

**1. Durability engine (Sleeve C, 8%)** — a 0–100 composite with buffer-zone selection at rank
60 and five written sell rules. Price decline is not one of them.

**2. Discovery (Sleeve E, 2%)** — good businesses nobody covers, in industries nobody writes
about. Seven free screens, then a manipulation gate that runs *before* scoring where a single
flag is fatal. Staged 40/30/30 tranches gated on **business confirmation, never price decline**.

**3. Validation** — walk-forward **plus CPCV**: 120 purged, embargoed combinations producing a
**probability of backtest overfitting**. PBO > 0.50 is kill criterion #6. Plus **factor IC**,
which answers what the portfolio backtest cannot: *is the signal itself any good, or does the
portfolio only look fine because of construction?*

**4. Signals** — LLM filing extraction where **every claim needs a citation to score**, plus a
**contamination test** measuring performance decay across the model's training cutoff · 13F
conviction · Merton distance-to-default (zero marginal data cost) · short interest and credit
spreads as risk flags.

**5. Reporting and tax** — block-bootstrap confidence intervals, a banned-phrase validator that
*raises* rather than writing promotional prose, and a tax-lot engine with cross-account
wash-sale detection.

**6. Research** — preregistered hypotheses, a claims ledger with a `contradicted_by` column, and
a decision journal that scores your **calibration**.

---

## Four rules that make this different

1. **Two independent leakage guards.** `store.as_of()` filters; **`firewall.py` asserts**. The
   second catches paths that bypass the first. Lagged disclosures use filing dates — 13F (45d),
   STOCK Act (45d), short interest (11+ business days). **Adjusted-close price series are
   rejected outright** — they're retroactively restated and silently leak corporate actions.
2. **Dead companies stay in the universe.** Lehman, WaMu, and Bear Stearns must appear in the
   2008 universe, or every value screen is quietly reading the future.
3. **Hooks, not hope.** CLAUDE.md is a suggestion; hooks always run. Flipping
   `live_trading_approved`, editing `.env`, weakening a Sleeve E cap, or importing `execution`
   into `reporting` are all *blocked*, not discouraged.
4. **We do not use LLMs to predict.** A model trained after your test window has read the
   future — the literature shows reported LLM trading advantages deteriorate sharply under
   longer, broader evaluation. Extraction with citations, never forecasting. See `docs/13`.

---

## The open-source audit (`docs/13`)

We surveyed the LLM-trading and quant tooling ecosystem and **rejected most of it, with reasons**:
the 95k-star multi-agent framework (structurally unbacktestable, and its own changelog documents
shipping a look-ahead bug), the 14k-star autonomous factor miner (a p-hacking machine that makes
trial counts unknowable), Qlib (excellent, but we'd re-solve the one problem we've already
solved, in someone else's data format).

What we took instead: **hooks** for deterministic safety, a **leakage firewall**, **factor IC
analysis**, **Almgren-Chriss market impact**, an **alpha-decay contamination test**, and the
**bull/bear dialectic** repurposed as a research technique rather than an autonomous trader.

> Sorting that survey by GitHub stars gives almost exactly the inverse of sorting by evidentiary
> standards. That's a finding, and it has a paragraph in the paper.

---

## Honest expectations

The base rate for retail systematic equity strategies beating a low-cost index after costs and
taxes is low. The neglect premium is contested. The small-cap premium is largely a 1975–1983
artifact. **Tax alpha of 0.5–1.5%/yr may well exceed any selection alpha this produces** — that's
preregistered hypothesis H4, not a disappointment.

A genuinely good outcome: matching the index with a portfolio you understand completely, while
building a point-in-time database with an independent leakage firewall, a CPCV validation
framework, factor IC analysis, a citation-enforced LLM pipeline with a contamination test, a
tax-lot engine, and a calibration study. That skill set transfers directly to actuarial and
quant work.

**Your calibration will be measurable in about a year. Your returns won't be for a decade.**

---

*Not investment advice. Educational and personal-research project. Do not claim "GIPS-compliant"
— reports use GIPS-style time-weighted return methodology, which is a calculation, not a
verification regime. Encode tax mechanics; confirm with a CPA. Verify any employer
personal-trading policy before trading.*
