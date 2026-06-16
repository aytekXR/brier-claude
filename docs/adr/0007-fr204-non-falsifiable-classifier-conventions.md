# ADR-0007: FR-204 non-falsifiable classifier conventions

- **Status:** accepted (ratified 2026-06-15, E4 methodology gate)
- **Date:** 2026-06-15 (proposed and accepted)
- **Deciders:** scoring-quant (ratified) + the E4-T5 adversarial panel (confirmed `classify_non_falsifiable` implements Rule 0/3/1/2 in the specified order, consistent with METHODOLOGY §1/§5/§6 — no formula change) + pipeline-engineer (E3-T4)

## Context

Task E3-T4 implements the full FR-204 non-falsifiable classifier in
`brier_pipeline/extraction/extractor.py`. METHODOLOGY §1 states:

> "could excluded as non-falsifiable, unless paired with conditions."

And:

> "Conventions are part of the public methodology; consistency beats cleverness."

An adversarial review found a scoring-integrity BLOCKER in the E3-T4 classifier:
a concrete, hedged prediction such as "BTC might hit $100k by Dec 31" (with
`target_price=100000` and `horizon_deadline="2025-12-31"` present in the parsed
tuple) was being classified as non-falsifiable because the hedge-word rule (Rule 1)
fired before checking whether the claim had a concrete, resolvable structure. This
would allow analysts to dodge scoring on concrete predictions by prepending a hedge
word — a direct gaming vector that undermines the product's purpose.

A second gap was that Rule 2's open-ended-horizon detection required
`horizon_basis == "default_90d"` explicitly, so when the model returned
`horizon_basis=null` the rule did not fire even with a clearly open-ended phrase
like "eventually" in the quote.

A third gap was that Rule 3 (sentiment/commentary) required `asset is None`, so
a statement like "BTC is the future" (named asset, no direction, no target) was
not caught.

Finally, the classifier only applied a one-way override (model says falsifiable
but classifier disagrees → force NON_FALSIFIABLE). The reverse case — model
mislabels a concrete tuple as `non_falsifiable` — was not corrected, leaving a
wrongly scored claim stuck in the non-falsifiable bucket.

## Decision (proposed)

Implement `classify_non_falsifiable` with the following PUBLISHED evaluation
order. These conventions REFINE FR-204 detection only; they do NOT change
METHODOLOGY §1's confidence-imputation table, the scoring formula in `fas.py`,
any specificity weights, or any component score (DS, C, K, F). `fas.py` is
unchanged.

### Rule 0 — Concrete override (the blocker fix)

A claim with a concrete, resolvable commitment is ALWAYS falsifiable, regardless
of hedge language:

```
has_concrete = target_price is not None or magnitude_pct is not None
has_stated_deadline = bool(horizon_deadline)
if has_concrete or has_stated_deadline:
    return False
```

Rationale: "BTC might hit $100k by Dec 31" resolves on December 31 regardless of
the word "might." The hedge is a confidence signal (imputed c), not a falsifiability
disqualifier. Rule 0 fires before any hedge-word or sentiment rule.

### Rule 3 — No directional signal (fires before Rule 1)

A statement with `direction is None` has no outcome to resolve against, regardless
of whether a named asset appears:

```
if direction is None:
    return True
```

Examples: "BTC is the future" (direction=None, asset="BTC") and "blockchain changes
everything" (direction=None, asset=None) are both non-falsifiable under this rule.
The asset name alone provides no resolvable commitment.

### Rule 1 — Bare vague-hedge (METHODOLOGY §1 extended)

METHODOLOGY §1's "could" exclusion is extended to its epistemic synonyms:

```
_VAGUE_HEDGE_WORDS = {"could", "might", "maybe"}
if confidence_language in _VAGUE_HEDGE_WORDS and not conditionality:
    return True
```

A bare "BTC could go higher" or "ETH might drop" carries no resolvable commitment
when unaccompanied by a condition. Paired with a condition clause ("if it breaks
$X"), the condition provides an activation criterion and the claim is falsifiable
(METHODOLOGY §1 "unless paired with conditions").

The extension to "might" and "maybe" is grounded in epistemic equivalence: all three
words signal the same epistemic register (extreme uncertainty, no commitment) that
METHODOLOGY §1 identified for "could." The published methodology table only names
"will" (c=0.85) and "likely" (c=0.70); neither "could," "might," nor "maybe" appear
in the imputation table — consistent with their treatment here as non-falsifiable
hedges rather than confidence signals.

### Rule 2 — Open-ended horizon phrase

An explicit open-ended time phrase in the quote disclaims any bounded deadline,
making the claim unresolvable even when a default horizon would otherwise apply:

```
_OPEN_ENDED_HORIZON_PHRASES = {
    "eventually", "at some point", "long term", "long-term",
    "someday", "in the future", "one day", "sometime", "sooner or later"
}

no_bounded_horizon = horizon_basis is None or horizon_basis == "default_90d"
if no_bounded_horizon and any(phrase in quote.lower() for phrase in phrases):
    return True
```

This fires when `horizon_basis` is `None` (model could not identify any horizon)
OR `"default_90d"` (the "no horizon mentioned" fallback). Both signal the absence
of any analyst-stated time commitment. Rule 2 must fire for both values because a
model returning `null` versus `"default_90d"` for the same vague quote is a
model-output variation, not a meaningful semantic difference.

### Two-way specificity_class authority

`classify_non_falsifiable` is the authoritative arbiter, applied both directions in
`_build_claim_from_pass2`:

- If classifier returns `True` → override model's class to `NON_FALSIFIABLE`.
- If classifier returns `False` AND model returned `NON_FALSIFIABLE` → recompute a
  falsifiable class deterministically from the tuple:
  - `conditionality` present → `CONDITIONAL`
  - `target_price` and `horizon_deadline` both present → `TARGET_DEADLINE`
  - `direction` and `magnitude_pct` both present → `DIRECTION_MAGNITUDE`
  - otherwise → `DIRECTION_ONLY`
- Otherwise → keep the model's class.

This prevents a falsifiable claim from being permanently mislabeled
`non_falsifiable` due to a model error, which would incorrectly exclude it from
scoring and miscount it in the falsifiability denominator.

## Scope boundary

This ADR governs `classify_non_falsifiable` in
`brier_pipeline/extraction/extractor.py` and the two-way override in
`_build_claim_from_pass2`. It explicitly does NOT change:

- METHODOLOGY §1 confidence-imputation table (`will`→0.85, `likely`→0.70)
- Any scoring formula in `fas.py` (DS, C, K, F, R, FAS, shrinkage)
- The specificity weights in `fas.py:_SPECIFICITY_WEIGHT`
- The FR-204 denominator counting in `fas.py:_load_prediction_like_counts`
- Any migration or schema

## Consequences

- **Scoring integrity restored:** analysts cannot dodge scoring on concrete
  predictions by prepending "might" or "could" — Rule 0 detects the concrete
  tuple first.
- **Methodological consistency:** the open-ended phrase set and the vague-hedge
  set are published here as part of the public methodology (METHODOLOGY §1:
  "Conventions are part of the public methodology"). Any future change to either
  set requires a new ADR and a methodology version bump.
- **`fas.py` unchanged:** all three of DS, C, K, F formulas, the shrinkage
  constant, and the specificity weights are untouched.
- **Ratified 2026-06-15** (E4 methodology gate) by the human owner and
  scoring-quant: the extension of Rule 1 to "might"/"maybe" and the Rule 0/3/2
  evaluation order are accepted. A subsequent change to the vague-hedge set,
  open-ended phrase set, or rule order requires the owner's approval, a new ADR
  entry (or amendment per ADR-0001), and a methodology version bump (FR-304).
