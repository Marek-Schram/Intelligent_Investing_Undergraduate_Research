# 04 — Risk, Safety, and Behavioral Guardrails

Three risks, ordered by likelihood of actually hurting you:
1. **Behavioral** — you override the system at the worst moment. (Most likely.)
2. **Software** — a bug submits an order you didn't intend.
3. **Market** — the strategy underperforms. (Least dangerous, most obsessed over.)

## 1. Software safety
```yaml
live_trading_approved: false   # human-only; a hook blocks Claude from setting it
max_order_notional: 500
max_daily_notional: 2000
allowed_order_types: [limit]
```
**Control flow:** score → construct → tax pass → adversarial review → propose (writes files,
sends nothing) → **HUMAN READS THE MEMO** → `submit --i-have-read-the-proposal` → submit
re-validates independently → orders.

**Kill switch:** a `KILL` file makes every execution path exit non-zero before authentication.

**Hooks (deterministic, `.claude/hooks/`):** block `.env` edits · block flipping
`live_trading_approved` · block weakening Sleeve E caps · block `reporting/research/tax`
importing `execution` · block order submission from an agent session · block deleting the audit
trail · auto-format Python · surface KILL/RECONCILE_FAILED at end of turn.

**Secrets:** `.env` only, gitignored, never logged. Paper and live keys under distinct variable
names so a typo cannot silently promote you to production.

**Reconciliation:** nightly broker-vs-local compare. Mismatch sets `RECONCILE_FAILED` and blocks
submit until a human clears it.

**Testing gates:** no merge with failing tests · `execution/` >= 90% coverage, elsewhere >= 70%
· chaos tests for timeout mid-order, partial fill, duplicate submission, rejection — all four
must end reconcilable.

## 2. Portfolio limits
Max position 6% of sleeve at purchase, trim above 12% · max GICS sector 25% · 15-25 positions ·
Sleeve C 8% of total · **Sleeve E 2% of total, 8 positions, 0.25% each** · no leverage.

**Sleeves C+E are capped at 10% of your total portfolio for a reason.** If everything here is
wrong, you lose ~10% relative to holding the index. That is a tuition bill, not a catastrophe.
Do not raise the cap after a good first year — one good year is roughly zero evidence.

## 3. Behavioral guardrails — these matter most
1. **Pre-commitment memo** before any buy: scores, implied growth, red flags, **the bear case
   and its three falsifiers**, and in your own words *what would have to be true for this to be
   a mistake.* You may not buy without writing that sentence.
2. **Decision journal entry** with a falsifiable prediction and confidence, stated before the
   outcome is known. `disconfirming_evidence` may not be empty — use `adversarial-review`.
3. **The 48-hour rule.** Proposals generated >= 48 hours before submission. In a quarterly
   strategy there is no situation where 48 hours matters.
4. **No override log = no override.** Deviating requires a committed entry in
   `reports/overrides.md` *before* trading. Override count is a headline report metric.
5. **No performance checking between quarters.** The weekly pulse is your one sanctioned
   channel. Daily P&L watching is how good strategies get abandoned in month seven.
6. **Drawdown pre-commitment.** Write down now: *"I will not abandon this strategy during a
   drawdown of less than 35% unless a kill criterion fires."*
7. **Index comparison first, always.** Every report leads with Sleeve C+E vs VTI.
8. **Annual calibration review.** If your overrides are systematically worse, stop overriding.

## 4. Legal and compliance
Trading on **public** disclosures (STOCK Act, Form 4, 13F) is legal; material non-public
information is not. Never add a source you cannot point to a public URL for. Your own money,
your own account — no client money, no pooled funds, no selling signals. **Never claim
"GIPS-compliant."** Encode tax mechanics, confirm with a CPA. **Check your employer's
personal-trading policy before the first trade and on any employer change** — many financial
firms require pre-clearance and minimum holding periods.

## 5. Things that would make this dangerous
Leverage or margin · options "just for hedging" · Sleeve E above 2% · removing the
human-in-the-loop · shortening the rebalance cycle · an ML return predictor on ~112 quarterly
observations · **automated factor mining** · trading a strategy whose backtest you cannot
reproduce · publishing a number without its confidence interval · **acting on an LLM extraction
with no filing citation** · **harvesting a loss without checking every account** · **using
adjusted-close price series**.

Every one is a documented failure mode. Adding any requires a dated spec change-log entry and a
fresh backtest under this protocol.
