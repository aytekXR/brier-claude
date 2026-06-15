# Brier Scoring Methodology

**Methodology version:** v1.1
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

### 2.1 Default-horizon materialisation (published table)

When an analyst does not state an explicit deadline, the horizon is computed at
resolution time from the utterance date using this table:

| `horizon_basis`  | Effective deadline                          |
|------------------|---------------------------------------------|
| `default_30d`    | utterance date + 30 days                   |
| `default_90d`    | utterance date + 90 days                   |
| `default_eoy`    | December 31 of the utterance year          |
| `stated`         | the stated deadline; if absent, deferred   |

The materialised deadline is written back to the claim record so receipts
display it consistently. Rule library entry: `directional_at_horizon.v0` /
`target_by_deadline.v0` (same rules, applied to the computed deadline).

### 2.2 Conditional activation (rule: `conditional_at_horizon.v0`)

A conditional claim ("if BTC closes below $75 000, further decline follows")
activates only when its trigger fires. The trigger is structured as:

| Field               | Meaning                                         |
|---------------------|-------------------------------------------------|
| `trigger_asset`     | Asset to watch for the trigger (own-asset only) |
| `trigger_price`     | Price level that trips the trigger              |
| `trigger_direction` | `above` or `below`                             |

**The trigger observation window** is the claim's own default horizon: it runs
from the utterance date to the effective deadline computed in §2.1 (for a
`stated` claim, to the stated deadline). The trigger must fire within that
window. The first daily UTC close inside the window that satisfies the trigger
is the **activation date**.

Once the trigger fires, the claim is scored over a **fresh** default horizon
measured from the activation date — applying the §2.1 table to the activation
date, not the utterance date. Because the scoring horizon is anchored on
activation, a trigger that fires late in the observation window pushes the
scoring window past the original observation window; that is intended.

**Never-fires conventions (published):**

- Trigger has not fired and the observation window is still open → the claim
  remains open (deferred; not yet scored).
- Trigger has not fired and the full observation window has elapsed → the claim
  is **void** and not scored. This is not a miss; the underlying event the
  analyst conditioned on simply did not occur. Status `void` is recorded with
  rule `conditional_void.v0`.

Cross-asset triggers (trigger on a different asset than the claim) are outside
MVP scope and are routed to QA for manual review.

The resolution rationale records the activation date, the trigger that fired,
and the resulting horizon window for full auditability (NFR-2).

### 2.3 Explicit reversal (rule: `reversal_close.v0`, EC-11)

When an analyst explicitly reverses a prior position in a later video, the
original claim is closed at the reversal date and scored to that date; the new
(post-reversal) position opens as a fresh claim.

Representation: the new claim carries `flags["reverses_claim_id"]` pointing to
the original claim's ID. The resolution engine closes the original as follows:

1. The original claim's effective deadline is clamped to the reversal date.
2. The applicable rule (`target_by_deadline.v0`, `directional_at_horizon.v0`,
   or `conditional_at_horizon.v0` for a conditional original) is applied over
   the clamped window (score-to-date). A conditional original whose trigger has
   not fired by the reversal date cannot be scored-to-date; it is left for the
   normal conditional path (§2.2), which defers or voids it.
3. A resolution with `rule_id = "reversal_close.v0"` is appended to the
   original claim (append-only; NFR-3 preserved).
4. The original claim's status is set to `resolved`.
5. The new claim is resolved independently via the normal pipeline.

### 2.4 Hedging contradictions (rule: `contradiction_void.v0`, EC-6)

When an analyst publishes two or more claims on the **same asset** with **opposite
directions** (one bullish, one bearish) whose **horizon windows overlap**, all
such claims are voided and a hedging flag is raised.

A horizon window is `[utterance date, materialised deadline]` (using the §2.1
table to compute the effective deadline for default-horizon claims).  Two windows
overlap when neither ends before the other begins.  A claim with no computable
deadline (a `stated` claim whose deadline was never captured) has no resolvable
horizon, so overlap cannot be established — it is **not** voided as a hedge (it is
left to the normal defer path).  Such a claim never resolves and so is not a
functional hedge; excluding it opens no scoring dodge.

**Why this rule exists:** an analyst who publishes simultaneous opposite-direction
claims on the same asset over the same period cannot be wrong — whichever
direction wins, one of their claims will look correct.  This "both-bets dodge"
must not earn scoring credit.  Voiding both removes the incentive entirely.

**Effect on scoring:**

- All claims in a contradicting set are set to `status = void` with
  `rule_id = "contradiction_void.v0"`.
- Voided claims receive **no resolution row** and are **not scored**.
- They enter the falsifiability denominator as non-scored prediction-like
  statements (consistent with how other void claims are treated — they are
  extracted statements the analyst made, just not scorable ones).
- The hedging flag is recorded in `claims.flags`:
  `{"hedging_contradiction": true, "void_rule_id": "contradiction_void.v0",
  "contradicts_claim_ids": [<id>, ...]}`.
  This provides a clear audit trail (NFR-2) so receipts can explain exactly
  which claims were contradicted and by which rule.

**Three-claim case:** if an analyst publishes two bullish claims and one
bearish claim on the same asset with overlapping horizons, the bearish claim
contradicts both bullish claims (pairwise).  All three are voided.  The most
conservative precedent (analyst cannot cherry-pick any winner) is applied.

**Precedence vs EC-11 reversal:** contradiction detection runs first.  A
contradicted claim is voided before the reversal pre-pass runs, so it will
not be reversal-closed as well.

## 3. Base rates: the honesty mechanism

For every claim, compute the base rate **b** = the empirical probability that a naive position matching the claim's direction succeeded over horizon T on that asset, using trailing 5-year history.

Example: a 30-day bullish BTC call in a trending regime can carry b ≈ 0.60. Skill is what remains after subtracting b. This single device deletes the perma-bull-in-a-bull-market illusion that destroys every naive leaderboard.

**Published computation conventions (v1.1 pins, ADR-0009):**

- **Trailing window:** daily UTC closes in [uttered_at − 5 years, uttered_at), strictly before the utterance date.  This ensures the base rate is a fair prior known at the time the claim was made, not hindsight.
- **Horizon T:** T = (effective_deadline − uttered_at.date()).days, computed via the §2.1 default-horizon table.  If T ≤ 0 or no horizon is computable, T falls back to 90 days.
- **Rolling-window empirical probability:** for each start day d in the trailing window where a close at d+T also exists: success = close[d+T] > close[d] for bullish; close[d+T] < close[d] for bearish.  Exact ties are not successes.  b = successes / total\_windows.
- **Minimum-windows convention:** if fewer than 20 T-day windows exist in the trailing history, return **0.5** (neutral prior — insufficient evidence).  This threshold is published and reproducible: the same inputs always produce the same result.
- **Clamped to [0, 1].**
- **Price source:** CoinGecko composite daily UTC closes (FR-301) via stdlib REST (no SDK, ADR-0009); FakePriceSource (fixture-backed) is the CI/demo path.

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
| v1.0 | 2026-06-15 | Full resolution rule library (E4-T1): §2.1 default-horizon materialisation table (30d/90d/eoy); §2.2 conditional activation — trigger observation window = the claim's own default horizon, scoring horizon anchored on the activation date, never-fires conventions (defer vs void), cross-asset out-of-scope note; §2.3 explicit reversal (EC-11) close-at-reversal-date convention (incl. conditional originals). rule_ids: conditional_at_horizon.v0, conditional_void.v0, reversal_close.v0. No formula change; version remains v1.0. |
| v1.0 | 2026-06-15 | Contradiction detection (E4-T4, EC-6): §2.4 hedging contradictions — opposite-direction claims on the same asset with overlapping horizons void both (not scored, not a miss); hedging flag recorded in claims.flags for auditability. rule_id: contradiction_void.v0. No formula change; version remains v1.0. |
| v1.1 | 2026-06-15 | Base rates from trailing history (E4-T2, FR-303, ADR-0009): §3 pins replace E1 fixture placeholders with real empirical base rates. Rolling T-day windows in trailing 5-year history; minimum 20 windows required, else 0.5 neutral prior. CoinGecko stdlib-REST (no SDK, ADR-0005 precedent) as the composite source; FakePriceSource stays CI/demo path. CCXT cross-check as an ADR-gated seam. PriceSource threaded into _load_resolved_claims / _execute_scoring_pass / run_score_pass / recompute_all. Full-history recompute required (FR-304, AC-4). |
