# 08 — Discovery Engine (Sleeve E)

Finding good businesses Wall Street isn't watching, buying small staged positions — **without**
wandering into the part of the market where retail investors reliably get destroyed.

## 0. Plain-English
Some good companies are ignored: small, boring industry, no analyst coverage. Ignored can mean
mispriced. **The catch is enormous: the same corner of the market is where almost all stock
fraud happens.** So this is a research and watchlist tool, not a lottery machine. Real companies
on real exchanges filing real financials. Tiny amounts, slowly, after passing the same durability
checks as everything else. Capped at **2% of total portfolio** — if every pick is wrong, it
changes nothing about your life.

## 1. What the evidence says
**Neglected firm effect — real, weaker than folklore.** Arbel & Strebel (1982) found low-coverage
firms earned higher risk-adjusted returns *after* controlling for size; Carvell & Strebel (1985)
measured up to **1.1% monthly** excess on NYSE stocks 1976-1981. Mechanism: analyst coverage is
information production; zero analysts means the 10-K gets filed and almost nobody reads it.
**But** Beard & Sias (1997), 7,000+ firms 1982-1995, found **no premium** after adjusting for
market cap, and a 2022 global study found it weakened or vanished in developed markets.
**Consequence: neglect is a place to look, never a reason to buy.**

**Small-cap premium — mostly a 1970s artifact.** 1926-2021 small beat large 11.99% vs 10.35%,
but **essentially all of it came in 1975-1983** (35.3%/yr vs 15.7%). Since 1979: Russell 2000
10.9% vs S&P 500 12.0%. **Nearly half of Russell 2000 constituents are now unprofitable**, up
from ~1 in 4 pre-GFC; private equity and VC keep the best companies private and buy out good
ones that list. **The decisive finding:** AQR research indicates the premium **holds controlling
for quality but disappears when low-quality companies are included.** The S&P 600 (screens for
profitability) matched the S&P 500 since 1995; the Russell 2000 didn't.
**Consequence: the durability score is the entire reason this can work.**

**The danger zone.** Microcap fraud runs into **billions annually**. CHOW sold 2.6M shares in
its IPO, raising $10.4M; that float created a liquidity vacuum, and on 2025-12-10 it fell
**84.3% in one session** — halted twice — after a promotion campaign run through WhatsApp
groups promising "120%-150%." Regulators responded: microcap IPOs on Nasdaq and NYSE fell from
~80 in H1 2025 to **13 in H1 2026**.

## 2. Placement
Carved **out of** Sleeve C: A 70% · B 15% · **C 8%** · **E 2%** · D 5%.
Max 8 positions, 0.25% of total each, <= 1% of 60-day ADV, min 12-month hold.
**Never increased on good performance.** A 2% sleeve that doubles gets trimmed back to 2%.

## 3. Universe — looser on size, far stricter on structure
| Filter | Sleeve C | **Sleeve E** |
|---|---|---|
| Market cap | >= $2.0B | **$300M-$3.0B** |
| Exchange | NYSE/NASDAQ/AMEX | **same — hard exclusion of OTC, now or within 24m** |
| Price | >= $5.00 | **>= $5.00, no exceptions** |
| ADV | >= $10M | **>= $1.5M** |
| Public float | — | **>= $150M and >= 8M shares** |
| Filings | >= 8 quarters | **>= 12 quarters** |
| Auditor | — | **PCAOB-registered, not on the SEC HFCAA list** |
| IPO recency | >= 24 months | **>= 36 months** |
| Profitability | — | **positive operating income in >= 3 of last 4 years** |
| Short interest | > 25% excludes | **> 10% of float excludes** |
| Distance-to-default | < 1.0 excludes | **< 1.5 excludes** |

**Automatic permanent exclusions:** OTC-quoted within 24 months · reverse split within 24
months · >1 name/ticker change in 5 years · reverse-merger within 5 years · SEC trading
suspension ever · repeated late filings · auditor resignation or restatement within 24 months ·
share count +25% in one year · paid promotion detected.

## 4. Discovery Score (0-100)
**Durability gate (0-40)** — the same `durability_score()`, but must reach **>= 30/50** to
proceed. Stricter than Sleeve C on purpose: less coverage means less external verification.
**Neglect (0-25)** — analyst count · institutional ownership · media mentions normalized by cap
· no sell-side initiation in 24 months.
**Valuation (0-25)** — SPEC §3 metrics ranked against **small-cap peers**. **EV/EBIT > 30
excluded** (vs 45 for Sleeve C) — margin of safety must be wider where information is thinner.
**Quality evidence (0-10)** — filing-cited: recurring revenue (3) · top customer < 20% (2) ·
insider ownership 5-40% (3) · sustained R&D/capex (2).
**Overlays (±5)** — insider purchases matter **more** here; institutional conviction applies.

Watchlist at **65**, position-eligible at **75**.

## 5. Manipulation detection — runs BEFORE scoring
Paid promotion (Section 17(b) disclosures) · social velocity >5x with no 8-K within 3 days ·
>30% move on >5x volume with no filing · toxic financing (variable-conversion converts, equity
lines) · promotional 8-K language · litigation and SEC enforcement · **distance-to-default <
1.5** · **short interest > 10% of float**.

Any hit is a permanent exclusion with a logged reason. **Never let fundamentals override.**

> **The rule that matters most:** a candidate learned from any unsolicited source — Reddit, DMs,
> YouTube, Discord, WhatsApp, newsletters — is **permanently excluded** regardless of the
> numbers. That is exactly the vector the CHOW promoters used.

## 6. Staged entry
T1 40% (max 0.10% of total) at score >= 75 with all screens passed, memo and **bear case**
written · T2 30% after **two more quarters filed** with durability held >= 30 · T3 30% after
four quarters with ROIC and FCF trend confirmed.

**Gated on business confirmation, never price decline.** Score < 60 cancels remaining tranches
permanently. Min 90 days between tranches.

## 7. Exits
**E1 Graduation** (cap > $3B, analysts >= 6, score >= 70) → Sleeve C. **The success case.**
E2 thesis break · E3 score < 55 twice · E4 manipulation (exit regardless of P&L) · E5 liquidity
· E6 corporate action. Not exits: price decline, one bad quarter, boredom.

## 8. Seven screens (all free, quarterly)
1. **Coverage-gap** — profitable, $300M-$3B, 0-2 analysts, institutional < 40%
2. **Boring-industry** — high durability in unglamorous SIC groups (industrial distribution,
   specialty chemicals, marine/logistics, waste, testing labs, niche manufacturing, regional
   utilities, building products, commercial services). *The "industry that's not very public"
   case, directly.*
3. **Insider-cluster** — >= 2 officers/directors, Form 4 code `P`, 90 days, < 3 analysts
4. **Spin-off** — 12-36 months post-spin; index funds sell mechanically, no analyst inherits
5. **Filing-language** — EDGAR full-text for "long-term supply agreement", "multi-year
   contract", "recurring revenue", "sole-source supplier", "switching costs"
6. **Quiet-compounder** — 5y revenue AND FCF CAGR > 8%, share count flat/shrinking, ROIC > 12%,
   < 4 analysts
7. **Institutional-conviction** — top-10 for >= 2 tracked concentrated managers, < 4 analysts

**EDGAR discipline:** User-Agent with name and email on every request (missing => 403 and a
~10-minute IP block) · max 10 req/sec · CIKs zero-padded to 10 digits · nightly bulk files for
wide scans.

## 9. Discovery Dossier
What the company does in two sentences from the 10-K · why it is neglected, with sources · all
sub-scores with raw inputs · reverse-DCF implied growth · DD and short interest · **every
manipulation check with its result, including the ones that passed** · **the bear case and its
three falsifiers** · the three biggest ways this could be wrong · **"What would have to be true
for this to be a mistake:" left blank for the human** · tranche status and next gate · the
evidence caveat.

## 10. Honest expectations
The neglect premium is **contested** · the small-cap premium is largely a 1975-1983 artifact
surviving mainly in quality-filtered form · private markets are draining quality from public
small caps · liquidity costs can erode the theoretical edge entirely · **with 8 positions in a
2% sleeve you will never have enough observations to distinguish skill from luck**, and every
report says so.

Realistic good outcome: one or two names graduate to Sleeve C over several years, you learn to
read filings deeply, and you find out empirically whether you can do this — at a cost capped at
2% of your portfolio.
