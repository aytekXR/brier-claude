# ADR-0006: EC-3 exclusion vs falsifiability denominator

- **Status:** proposed (pending human approval)
- **Date:** 2026-06-14
- **Deciders:** human owner (approval pending) + scoring-quant (ratify) + pipeline-engineer (proposing, E3-T2)

## Context

PRD EC-3 states that sarcasm, hypotheticals, and paraphrases of others ("some say BTC
will…") are excluded by the pass-2 classifier, and that "excluded items do not count
against falsifiability."

METHODOLOGY §6 pin 6 defines the F denominator as "all extracted prediction-like
statements (including non-falsifiable and void)." A plain reading of pin 6 — without
distinguishing EC-3 exclusions from the analyst's own vague or void statements — would
cause EC-3-excluded spans to enter the F denominator and incorrectly dilute the
analyst's falsifiability score.

`fas.py:_load_prediction_like_counts` counts every row in the `claims` table
(`select analyst_id, count(*) from claims group by analyst_id`). If EC-3 VOIDs were
inserted into `claims`, they would enter the denominator in contradiction of PRD EC-3.

The tension is:
- EC-3 excluded spans are **not the analyst's own predictions** — they are other
  people's statements, sarcastic remarks, or hypotheticals that the analyst is
  voicing or quoting, not asserting.
- EC-7 voids (unresolvable asset) and non_falsifiable claims ("could" without a
  condition) **are** the analyst's own statements and correctly belong in the F
  denominator, penalising vagueness (METHODOLOGY §6 pin 6).

## Decision (proposed)

Reconcile the PRD EC-3 vs METHODOLOGY §6 tension at the **extraction/persistence
boundary**, without changing `fas.py` or any scoring formula:

1. **EC-3-excluded claims are not inserted into the `claims` table.** The
   `is_excluded_span(claim)` predicate in `extraction/extractor.py` returns `True`
   when `claim.flags["excluded_reason"]` is set (indicating EC-3 exclusion). The
   claim-insert loop in `demo.py` (and the future `extract` job handler) calls this
   predicate before `_insert_claim` and skips any claim where it is `True`.

2. **EC-7 voids are inserted.** An unresolvable asset is the analyst's own failure to
   be specific about what they are predicting; these claims are persisted and correctly
   enter the F denominator.

3. **non_falsifiable claims are inserted.** "Could" without a condition (METHODOLOGY §1),
   and any other non-falsifiable class, represents the analyst's own vague prediction;
   these are persisted and enter the F denominator.

4. **`fas.py` is unchanged.** The reconciliation is enforced entirely at the persistence
   boundary. The scoring formula, `_load_prediction_like_counts`, and all score-ledger
   rows are unaffected.

5. **METHODOLOGY §6 pin 6 reading:** The phrase "all extracted prediction-like
   statements" in pin 6 is interpreted as "all extracted prediction-like statements by
   the analyst" — a reading consistent with the purpose of the falsifiability ratio (to
   penalise the analyst for vagueness and hedging). EC-3 spans are statements by others
   or non-genuine assertions; they are not "by the analyst" and are therefore not
   prediction-like statements in the sense of pin 6.

## Consequences

- **No scoring-math change.** `fas.py` is untouched; the F formula is unchanged.
- **The contract is the persistence filter.** `is_excluded_span` is the single choke
  point; it must be applied in every claim-insert path (`demo.py` and the future
  `extract` job handler in E4-T3).
- **E4-T3 (EC-3 residue) and E4-T5 (full-history recompute)** must honor this contract:
  EC-3-excluded claims are not inserted, so they cannot appear in F's denominator.
- **scoring-quant must confirm** that the METHODOLOGY §6 pin 6 reading ("analyst's own
  extracted statements") is correct and that no formula change is required. Until
  confirmed, status remains `proposed`.
- **FakeExtractor produces no EC-3 items** from the current fixture corpus, so the
  demo's behaviour with the fixture pipeline is unchanged. Only real LLM output that
  triggers EC-3 exclusion is filtered.
- **This ADR is not yet accepted.** Until the human owner and scoring-quant approve,
  the persistence filter is in place but the denominator contract should be validated
  against the METHODOLOGY §6 reading. Changing this requires the owners' approval
  recorded here (status → accepted) per ADR-0001 and CLAUDE.md.
