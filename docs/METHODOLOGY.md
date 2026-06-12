# Brier Scoring Methodology

**Methodology version:** v1.0 (pre-launch draft)
**Source of truth:** distilled from `docs/VENTURE-ANALYSIS.md` Section 9 (Accuracy Score Framework). Where this document and Section 9 disagree, file an ADR and bump the methodology version; never silently edit.
**Status:** specification only. The implementation lands with epic E1 (see `TASKS.md`) and must match this document exactly.

The framework is designed so that being vague, being lucky, and being loud all fail to pay. A naive percent-correct rewards vague, frequent, hedged bull calls in bull markets; every device below exists to remove one of those escape hatches.

---

## 1. Claim record

Each scored claim *i* is a tuple:

| Field | Meaning |
|---|---|
| `asset` (A) | Crypto asset, from a controlled vocabulary with an alias table |
| direction or target | Bullish/bearish direction, or an explicit price target |
| `horizon` (T) | Deadline date |
| `stated_confidence` (c) | As stated, else imputed from language (table below) |
| `p0` | Price at utterance |
| `t0` | Utterance timestamp |
| `specificity_class` | See weights, Section 4 |
| source pointer | Video ID + second offset |

**Imputed confidence conventions (published):**

| Language | c |
|---|---|
| "will" | 0.85 |
| "likely" | 0.70 |
| "could" | excluded as non-falsifiable, unless paired with conditions |

**Default-horizon conventions (published):**

| Stated horizon | T |
|---|---|
| "soon" | 30 days |
| "this year" | December 31 |
| none stated | 90 days |

Conventions are part of the public methodology; consistency beats cleverness.

## 2. Resolution

Outcome y ∈ {0, 0.5, 1}.

- **Price basis:** daily UTC close from a published composite source. Close basis, never wicks — this prevents wick-gaming disputes.
- **Target claims:** "hits $X by D" resolves 1 if any daily close meets X before D.
- **Directional claims:** resolve against the close at T.
- **Partial credit:** 0.5 when direction is right but stated magnitude is under half achieved.
- **Conditional claims** ("if it dips below $250…"): activate only if the condition triggers, then score over the default horizon.
- **Macro claims:** resolve against official records.

## 3. Base rates: the honesty mechanism

For every claim, compute the base rate **b** = the empirical probability that a naive position matching the claim's direction succeeded over horizon T on that asset, using trailing 5-year history.

Example: a 30-day bullish BTC call in a trending regime can carry b ≈ 0.60. Skill is what remains after subtracting b. This single device deletes the perma-bull-in-a-bull-market illusion that destroys every naive leaderboard.

## 4. Weights

**Specificity v:**

| Specificity class | v |
|---|---|
| direction-only | 1.0 |
| direction + magnitude | 1.5 |
| explicit target + deadline | 2.0 |
| conditional | 0.75 |
| non-falsifiable | scores nothing; counted in the falsifiability ratio (Section 5) |

**Difficulty d:**

```
d = clamp( |ln(P_target / P0)| / (sigma_annual × sqrt(T_years)), 0.25, 2.0 )
```

Direction-only claims take d = 0.5. Bold, precise calls earn more; trivial calls earn little.

**Claim weight:**

```
w = v × d
```

with diminishing weight (divide by sqrt of count) for more than 3 claims per asset per week, neutralizing spam strategies.

## 5. Component scores

- **Directional Skill:**

  ```
  DS = Σ w_i (y_i − b_i) / Σ w_i
  ```

  Typically lands in −0.15 to +0.25.

- **Calibration:** Brier score B = mean (c_i − y_i)² over claims with confidence;

  ```
  C = clamp(1 − B / 0.25, 0, 1)
  ```

  normalized so that coin-flip-quality confidence scores zero. Overconfident wrong calls are punished hardest — exactly the failure mode of hype channels.

- **Consistency K:** 1 minus normalized dispersion of rolling 10-claim DS windows. Punishes one-hot-streak wonders.

- **Falsifiability F:** scored claims ÷ total extracted prediction-like statements. Hedging is not misscored; it is exposed as a published ratio.

## 6. Composite and shrinkage

Raw composite, each component mapped to [0, 1]:

```
R = 0.45·norm(DS) + 0.25·C + 0.15·K + 0.15·F
```

Final score — Bayesian shrinkage, the IMDb-rating device:

```
FAS = 100 × ( n·R + k·R_prior ) / ( n + k )
```

with shrinkage constant **k = 25** and **R_prior = population median**. Shrinkage prevents a 3-for-3 newcomer from topping the board.

**Eligibility and the provisional flag (two tiers):**

- **n < 20:** not ranked; status "provisional" (PRD FR-305: excluded from the ranked board).
- **20 ≤ n < 30:** ranked, but flagged **provisional** (per the Analyst B worked example below, "provisional until n ≥ 30").
- **n ≥ 30:** flag clears.

> Reconciliation note: Section 9.6 of the venture analysis sets ranking eligibility at n ≥ 20; the Section 9.8 worked example flags Analyst B (n = 24) provisional until n ≥ 30. The two-tier reading above is the only one consistent with both texts and is the binding convention for implementation and tests.

### Published computation conventions (v1.0 pins)

The formula above leaves certain details unspecified. The following pins are
approved by the project owner (2026-06-12) and recorded in ADR-0002. They are
definitional clarifications of unspecified details — not formula changes — so
the methodology version remains v1.0.

1. **norm(DS):** `clamp((DS + 0.25) / 0.5, 0, 1)`. Zero skill maps to 0.5.
   A DS of −0.25 maps to 0; a DS of +0.25 maps to 1.

2. **Consistency K:** Chronological rolling 10-claim windows (stride 1) over the
   analyst's resolved claims; each window computes its weighted DS; K is then
   `clamp(1 − stdev(window DS values) / 0.25, 0, 1)` using population standard
   deviation. Analysts with fewer than 2 windows (n < 11) receive K = 0.5
   (neutral — not enough data to judge consistency).

3. **R_prior:** Median of pre-shrinkage R across all analysts scored in the
   current score run (any n ≥ 1). If fewer than 3 analysts are in the run,
   R_prior = 0.5 (fallback to avoid a biased estimate from a tiny sample).

4. **direction_magnitude claims:** Implied P_target = P0 × (1 ± magnitude_pct / 100),
   sign positive for bullish and negative for bearish, then fed into the deadline
   difficulty formula. sigma_annual is the standard deviation of the trailing
   365 daily log-returns at t0, annualized by sqrt(365).

5. **Spam damping:** Claims are grouped per (analyst, asset, ISO week). If a
   group has m > 3 claims, every claim in that group takes w / sqrt(m).

6. **Falsifiability F:** The numerator is resolved-and-scored claims; the
   denominator is all extracted prediction-like statements (including
   non-falsifiable and void). Example: Analyst A with 60 scored claims out of
   240 total prediction-like statements → F = 60 / 240 = 25%.

7. **Zero-confidence analysts:** If an analyst has zero claims with a recorded
   stated_confidence, C = 0. No calibration evidence earns no calibration
   credit.

## 7. Anti-gaming inventory

1. **All-claims coverage:** we extract everything; no self-submission, no cherry-picking.
2. **Deletion persistence:** claims survive source deletion and the deletion itself is flagged publicly ("the tape does not forget").
3. **Contradiction detection:** opposite-direction claims on the same asset with overlapping horizons void both and raise a hedging flag.
4. **Base-rate correction** (Section 3) kills regime-riding.
5. **Brier penalty** (Section 5) kills confidence inflation.
6. **Frequency damping** (Section 4) kills spray-and-pray.
7. **Shrinkage + minimum n** (Section 6) kills small-sample flukes.
8. **Versioned methodology** with public changelog; full-history recomputation on every version; no silent retro-edits.

## 8. Worked examples (binding test cases)

These two examples are the acceptance fixture for the scoring engine (task E1-T2). The unit tests must encode both, including the ordering inversion: **B outranks A despite a lower raw hit rate.**

### Analyst A, "Hype Caller"

- 60 resolved claims, raw hit rate 68%.
- But 80% are direction-only bullish BTC/ETH calls with average b = 0.61 → **DS ≈ +0.07** at low weights.
- Stated confidence averages 0.9 → Brier ≈ 0.27 → **C ≈ 0**.
- Falsifiability **25%**.
- **FAS ≈ 54** — lands in the 45–60 band. Headline raw accuracy collapses under the lens.

### Analyst B, "Precision Caller"

- 24 resolved claims, raw hit rate 58%.
- Claims are target-plus-deadline (v = 2.0, avg b = 0.34, d ≈ 1.2) → **DS ≈ +0.24** weighted.
- Confidence ≈ 0.6, well calibrated → **C ≈ 0.7**.
- Falsifiability **70%**.
- Shrinkage (n = 24, k = 25) pulls it halfway to prior → **FAS ≈ 71** — lands in the 60–80 band, **flagged provisional until n ≥ 30**.

Lower raw accuracy, far higher score: the system is doing its job, and explaining exactly this example publicly is the methodology marketing.

---

## Changelog

| Version | Date | Change |
|---|---|---|
| v1.0 | 2026-06-11 | Initial distillation from venture analysis Section 9. Two-tier provisional convention recorded. |
| v1.0 | 2026-06-12 | Convention pins recorded (ADR-0002): norm(DS), K windows, R_prior, direction_magnitude d, sigma_annual, spam damping, falsifiability denominator, zero-confidence C. No formula change; version remains v1.0. |
