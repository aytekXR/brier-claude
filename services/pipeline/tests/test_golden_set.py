"""AC-1 gate: extraction precision >= 95%, recall >= 80% on the golden set.

Three tests:
1. test_golden_set_meets_ac1_gate — runs evaluate_golden_set on the real
   golden_set.jsonl and asserts the PRD gate thresholds.  This is a
   *required* CI check (make check); a failure blocks the build.
2. test_golden_set_gate_fails_on_degraded_set — proves the recall branch is
   not vacuous: zeroing all predicted detections causes recall to fall below
   0.80.
3. test_golden_set_gate_fails_on_low_precision — proves the precision branch
   is not vacuous: setting every record's predicted.is_prediction=True (all-
   positive predictor) yields precision 115/200 = 0.575, below 0.95.
"""

from __future__ import annotations

import json
from pathlib import Path

from brier_pipeline.qa.golden_eval import evaluate_golden_set

# Absolute path to the real golden set so the test is path-independent.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_GOLDEN_SET = _REPO_ROOT / "data" / "fixtures" / "golden_set.jsonl"


def test_golden_set_meets_ac1_gate() -> None:
    """PRD AC-1 / G2: precision >= 95%, recall >= 80% on the 200-record golden set."""
    result = evaluate_golden_set(_GOLDEN_SET)

    # Anti-vacuousness guards: reject a truncated or all-negative golden set
    # before checking thresholds.  PRD AC-1 requires the full 200-claim set,
    # and at least 100 gold-positives must be present so recall is non-trivial.
    assert (result.tp + result.fp + result.fn + result.tn) == 200, (
        f"Golden set must contain exactly 200 records; "
        f"got {result.tp + result.fp + result.fn + result.tn}."
    )
    assert (result.tp + result.fn) >= 100, (
        f"At least 100 gold-positive records are required so recall is non-trivial; "
        f"got {result.tp + result.fn}."
    )

    assert result.precision >= 0.95, (
        f"Precision {result.precision:.4f} is below the AC-1 gate of 0.95. "
        f"Counts: TP={result.tp} FP={result.fp} FN={result.fn} TN={result.tn}"
    )
    assert result.recall >= 0.80, (
        f"Recall {result.recall:.4f} is below the AC-1 gate of 0.80. "
        f"Counts: TP={result.tp} FP={result.fp} FN={result.fn} TN={result.tn}"
    )


def test_golden_set_gate_fails_on_degraded_set(tmp_path: Path) -> None:
    """Proves the recall branch is not vacuous: setting all predicted.is_prediction=False
    causes recall to fall below 0.80 (all true positives become false negatives)."""
    degraded: list[dict] = []
    with _GOLDEN_SET.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            record["predicted"]["is_prediction"] = False
            degraded.append(record)

    degraded_path = tmp_path / "degraded_golden_set.jsonl"
    with degraded_path.open("w", encoding="utf-8") as fh:
        for record in degraded:
            fh.write(json.dumps(record) + "\n")

    result = evaluate_golden_set(degraded_path)

    assert result.recall < 0.80, (
        f"Expected recall < 0.80 on degraded set (all predicted=False), "
        f"but got recall={result.recall:.4f}. The gate is not detecting failures."
    )


def test_golden_set_gate_fails_on_low_precision(tmp_path: Path) -> None:
    """Proves the precision branch is not vacuous: setting every record's
    predicted.is_prediction=True (all-positive predictor) yields
    TP=115, FP=85, precision=115/200=0.575, which must be below 0.95."""
    all_positive: list[dict] = []
    with _GOLDEN_SET.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            record["predicted"]["is_prediction"] = True
            all_positive.append(record)

    all_pos_path = tmp_path / "all_positive_golden_set.jsonl"
    with all_pos_path.open("w", encoding="utf-8") as fh:
        for record in all_positive:
            fh.write(json.dumps(record) + "\n")

    result = evaluate_golden_set(all_pos_path)

    assert result.precision < 0.95, (
        f"Expected precision < 0.95 on all-positive predictor set, "
        f"but got precision={result.precision:.4f}. "
        f"Counts: TP={result.tp} FP={result.fp} FN={result.fn} TN={result.tn}"
    )
