# Paper outline

1. Abstract · 2. Introduction (framed as a question) · 3. Literature review (from claims.csv,
**including `contradicted_by`**) · 4. Data (sources, PIT construction, survivorship, exclusions,
**firewall design**) · 5. Methodology (score, protocol, CPCV, IC, Almgren-Chriss costs, tax) ·
6. Results (walk-forward, CPCV distribution, PBO, ablations, factor attribution, **factor IC**,
**contamination verdict**, after-tax, calibration) · 7. Discussion · 8. **Limitations** ·
9. Conclusion

## Limitations (draft NOW, before results exist — may grow, never shrink)
- Single realized path of one strategy on one universe
- Small live sample; returns not statistically distinguishable for years
- LLM features contaminated for any window before the model's training cutoff
- Neglect premium empirically contested (Beard & Sias 1997)
- Small-cap premium largely a 1975-1983 artifact, quality-dependent
- 13F covers long US equity only, 45-day lag
- Survivorship handling validated but imperfect for pre-2000 delistings
- Costs and taxes modeled, not observed
- Author is a single non-professional investor with a small account

## Two discussion points worth their own paragraphs
1. **The open-source audit finding** (docs/13 §4): sorting the surveyed tooling by GitHub
   popularity gives almost exactly the inverse of sorting by evidentiary standards. Popularity
   in this space tracks excitement, not method.
2. **Calibration may be the strongest chapter.** Returns need a decade to become significant;
   calibration converges in about a year, and almost nobody publishes it on themselves.
