# ADR-0002: Scoring computation convention pins (v1.0)

- **Status:** accepted
- **Date:** 2026-06-12
- **Deciders:** human owner (session approval) + scoring-quant

## Context

`docs/METHODOLOGY.md` v1.0 specifies the FAS formula but leaves several
computational details unspecified. During task E1-T2 (FAS scoring engine
implementation), the project owner approved the following pins in session.
These are definitional clarifications of unspecified details, not formula
changes. The methodology version therefore remains v1.0; no full-history
recompute is triggered.

## Decision

The following computation conventions are pinned and are now binding:

1. **norm(DS):** `clamp((DS + 0.25) / 0.5, 0, 1)`. Zero skill maps to 0.5.

2. **Consistency K:** Chronological rolling 10-claim windows (stride 1) over
   the analyst's resolved claims; each window scores its weighted DS;
   `K = clamp(1 - stdev(window DS values) / 0.25, 0, 1)` using population
   stdev. With fewer than 2 windows (n < 11), K = 0.5 (neutral).

3. **R_prior:** Median of pre-shrinkage R across all analysts scored in the
   current score_run (any n >= 1). If fewer than 3 analysts are in the run,
   R_prior = 0.5 (fallback to avoid a biased median from a tiny sample).

4. **direction_magnitude claims:** Implied P_target = P0 * (1 +/- magnitude_pct / 100)
   using the claim's direction (bullish = +, bearish = −), then feed into the
   deadline difficulty formula.

5. **sigma_annual:** Standard deviation of the trailing 365 daily log-returns
   at t0, annualized by sqrt(365), computed from the claim's price source.
   When not provided to a computation function, a reasonable default is used.

6. **Spam damping:** Group claims per (analyst, asset, ISO week). If a group
   has m > 3 claims, every claim in that group takes w / sqrt(m).

7. **Falsifiability F:** `F = resolved-and-scored claims / all extracted
   prediction-like statements`. The numerator is resolved non-void, non-non-
   falsifiable claims; the denominator is all extracted prediction-like
   statements for the analyst (including non-falsifiable and void). This
   matches worked example A: 60 scored / 240 total = 25%.

8. **Zero-confidence analysts:** If an analyst has zero claims with
   stated_confidence, C = 0. No calibration evidence earns no calibration
   credit.

## Consequences

- These pins are implemented in `services/pipeline/brier_pipeline/scoring/fas.py`
  and recorded in the "Published computation conventions (v1.0 pins)" subsection
  of `docs/METHODOLOGY.md` section 6.
- The methodology version stays v1.0; no full-history recompute is triggered.
- Future sessions and subagents must treat these pins as binding. Changing any
  pin requires a new ADR and a methodology version bump with full-history
  recompute (per ADR-0001 and FR-304, AC-4).
- Worked examples in METHODOLOGY.md §8 remain the binding unit tests.
