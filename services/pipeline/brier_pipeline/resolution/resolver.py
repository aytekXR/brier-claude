"""Nightly resolution job: open claims x prices -> appended outcomes (data flow 4)."""

from __future__ import annotations

from brier_pipeline.models import Resolution
from brier_pipeline.resolution.prices import PriceSource


def resolve_open_claims(prices: PriceSource) -> list[Resolution]:
    """Join open claims against daily closes and append resolutions.

    Append-only: corrections never mutate; they append a superseding row
    (NFR-3). Stale or gapped price data defers resolution, never improvises
    (EC-8). Returns the resolutions appended in this run.
    """
    # TASK: E1-T3 (v0: target-by-deadline + directional), E4-T1 (full library)
    raise NotImplementedError
