"""Golden-set extraction eval harness — PRD AC-1, G2, §18.

Reads a JSONL file of hand-labeled extraction records and computes
precision / recall for the ``is_prediction`` detection task, plus
secondary accuracy metrics on true-positive records.

No LLM, no network, no database access: pure file reading. The
``predicted`` field in each record is a static snapshot of the model's
output and is never recomputed here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvalResult:
    """Aggregate metrics for a golden-set evaluation run.

    ``asset_accuracy``, ``direction_accuracy``, and ``specificity_accuracy``
    are computed only on true-positive records (where both gold and predicted
    ``is_prediction`` are True).  They are ``None`` when ``tp == 0``.
    """

    tp: int
    fp: int
    fn: int
    tn: int
    # Empty-denominator convention: when TP+FP==0 precision=1.0 (no false
    # alarms means the model never fired, which is trivially "perfect" at
    # avoiding false positives).  When TP+FN==0 recall=1.0 (no positives to
    # miss).  Both cases are documented here because they affect the gate.
    precision: float
    recall: float
    asset_accuracy: float | None
    direction_accuracy: float | None
    specificity_accuracy: float | None


def evaluate_golden_set(path: str | Path) -> EvalResult:
    """Read *path* (JSONL), validate records, accumulate metrics, return EvalResult.

    Args:
        path: Path to the JSONL file.  Each non-empty line must be a JSON
              object with at least the keys ``gold.is_prediction`` and
              ``predicted.is_prediction``.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the file contains zero parseable records (an empty
                    file must not silently return precision=recall=1.0), or
                    if any record is missing ``gold.is_prediction`` or
                    ``predicted.is_prediction``.

    Returns:
        An :class:`EvalResult` populated with detection counts and metrics.
    """
    resolved = Path(path)
    if not resolved.exists():
        raise FileNotFoundError(f"Golden set not found: {resolved}")

    tp = fp = fn = tn = 0
    tp_asset_hits = tp_direction_hits = tp_spec_hits = 0
    tp_asset_total = tp_direction_total = tp_spec_total = 0
    records_seen = 0

    with resolved.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            records_seen += 1

            record: dict[str, Any] = json.loads(line)

            gold = record.get("gold", {})
            predicted = record.get("predicted", {})

            # Strict validation: missing keys are an error, not a silent skip.
            if "is_prediction" not in gold:
                raise ValueError(
                    f"Line {lineno}: record is missing gold.is_prediction — "
                    f"id={record.get('id', '<unknown>')}"
                )
            if "is_prediction" not in predicted:
                raise ValueError(
                    f"Line {lineno}: record is missing predicted.is_prediction — "
                    f"id={record.get('id', '<unknown>')}"
                )

            gold_pos: bool = bool(gold["is_prediction"])
            pred_pos: bool = bool(predicted["is_prediction"])

            if gold_pos and pred_pos:
                tp += 1
                # Secondary accuracy on TP records (informational only).
                g_asset = gold.get("asset")
                p_asset = predicted.get("asset")
                if g_asset is not None:
                    tp_asset_total += 1
                    if g_asset == p_asset:
                        tp_asset_hits += 1

                g_dir = gold.get("direction")
                p_dir = predicted.get("direction")
                if g_dir is not None:
                    tp_direction_total += 1
                    if g_dir == p_dir:
                        tp_direction_hits += 1

                g_sc = gold.get("specificity_class")
                p_sc = predicted.get("specificity_class")
                if g_sc is not None:
                    tp_spec_total += 1
                    if g_sc == p_sc:
                        tp_spec_hits += 1

            elif not gold_pos and pred_pos:
                fp += 1
            elif gold_pos and not pred_pos:
                fn += 1
            else:
                tn += 1

    if records_seen == 0:
        raise ValueError(
            f"Golden set at {resolved} contains zero records; "
            "an empty file must not silently return precision=recall=1.0."
        )

    # Empty-denominator convention = 1.0 (documented above).
    # NOTE: this convention applies only to per-metric edge cases (e.g. a
    # set where the predictor never fires).  A wholly empty file is an error
    # (raised above) and never reaches these lines.
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0

    asset_accuracy: float | None = tp_asset_hits / tp_asset_total if tp_asset_total > 0 else None
    direction_accuracy: float | None = (
        tp_direction_hits / tp_direction_total if tp_direction_total > 0 else None
    )
    specificity_accuracy: float | None = tp_spec_hits / tp_spec_total if tp_spec_total > 0 else None

    result = EvalResult(
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        precision=precision,
        recall=recall,
        asset_accuracy=asset_accuracy,
        direction_accuracy=direction_accuracy,
        specificity_accuracy=specificity_accuracy,
    )

    _print_summary(result)
    return result


def _print_summary(r: EvalResult) -> None:
    total = r.tp + r.fp + r.fn + r.tn
    print(f"Golden-set eval: {total} records — TP={r.tp} FP={r.fp} FN={r.fn} TN={r.tn}")
    print(
        f"  precision={r.precision:.4f} ({'PASS' if r.precision >= 0.95 else 'FAIL'} ≥0.95)  "
        f"recall={r.recall:.4f} ({'PASS' if r.recall >= 0.80 else 'FAIL'} ≥0.80)"
    )
    if r.asset_accuracy is not None:
        print(f"  asset_accuracy (TP only)={r.asset_accuracy:.4f}")
    if r.direction_accuracy is not None:
        print(f"  direction_accuracy (TP only)={r.direction_accuracy:.4f}")
    if r.specificity_accuracy is not None:
        print(f"  specificity_accuracy (TP only)={r.specificity_accuracy:.4f}")
