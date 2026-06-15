"""Base rates: the honesty mechanism (FR-303, METHODOLOGY.md §3).

Empirical base rate b for a claim: the probability that a naive position
matching the claim's DIRECTION succeeded over the claim's horizon T on that
asset, computed from the trailing 5-year history of daily closes ending
strictly before the claim's utterance date.

This is the PRIOR known at utterance time — it is computed from information
available before the claim was made, not from hindsight.

Published conventions (ADR-0009, METHODOLOGY.md §3):

  Trailing window:
    [uttered_at - 5 years, uttered_at), strictly before the utterance date.
    Uses daily UTC closes from the supplied PriceSource.

  Horizon T:
    T = (effective_deadline - uttered_at.date()).days
    Computed via materialise_horizon_deadline from resolution/rules.py.
    If T <= 0 or no horizon is computable, T falls back to 90 days (the
    default-horizon convention from METHODOLOGY.md §1).

  Rolling-window empirical probability:
    For each start day d in the trailing window such that a close at d+T
    also exists, score the naive direction-matching position:
      - bullish: close[d+T] > close[d]  → success
      - bearish: close[d+T] < close[d]  → success
      - exact tie: not a success for either direction
    base_rate = successes / total_windows

  Minimum-windows convention (published, ADR-0009):
    If fewer than MIN_BASE_RATE_WINDOWS (20) T-day windows exist in the
    trailing history, there is insufficient evidence to estimate a meaningful
    base rate.  In that case, return 0.5 (neutral prior — no evidence).
    This convention is reproducible: same inputs always produce the same result.

  Clamping:
    The result is clamped to [0.0, 1.0] (a probability cannot exceed those
    bounds; the empirical count ensures it cannot, but clamping is defensive).

  FakePriceSource is the CI path: the fixtures hold ~18 months of BTC/ETH/SOL
  closes (2024-12-01 .. 2026-06-11, ~558 days), fewer than the 5-year ideal.
  For a claim uttered WITHIN that window (2025+), the trailing slice still yields
  >= 20 overlapping T-day windows for T up to ~538 days, so a REAL empirical base
  rate is returned (often an extreme 0.0/1.0, because a few months of trending
  fixture data has no counter-examples). The 0.5 fallback triggers only when the
  trailing window is too thin: a claim uttered before the fixture starts (e.g. a
  2024-01-01 seed) has an entirely pre-fixture window -> 0.5; and very long
  horizons (T >= ~539 days) leave < 20 windows -> 0.5. With real 5-year
  production history every reasonable T has hundreds of windows, so base rates are
  stable and non-degenerate.
"""

from __future__ import annotations

from datetime import date, timedelta

from brier_pipeline.models import Claim
from brier_pipeline.resolution.prices import PriceSource

# Published constant: minimum number of (overlapping) T-day windows required to
# compute a meaningful empirical base rate. Fewer than this → return 0.5 (neutral).
# NOTE on the rationale: the code counts OVERLAPPING windows (every start day
# with a d+T close), so 5-year history at T=90 yields ~1825-90 ≈ 1735 windows,
# not 20. The "~1825/T ≈ 20" figure describes NON-overlapping blocks — the
# statistically meaningful sample count. The threshold is intentionally
# conservative: it only protects against very thin history (a few hundred days),
# where overlapping windows are highly correlated; real 5-year data always far
# exceeds it for any reasonable T. Documented in ADR-0009 and METHODOLOGY.md §3.
MIN_BASE_RATE_WINDOWS = 20

# Maximum trailing history length in years (METHODOLOGY.md §3: "trailing 5-year
# history"). This is a published constant.
TRAILING_YEARS = 5


def base_rate(claim: Claim, prices: PriceSource) -> float:
    """Empirical probability that a naive direction-matching position succeeded
    over the claim's horizon T on that asset, from trailing history.

    Pure function: no DB access, no network. Takes a PriceSource and reads
    closes via prices.daily_closes(asset, start, end).

    See module docstring for full convention specification.

    Args:
        claim: The claim to compute the base rate for.
        prices: A PriceSource instance (FakePriceSource in CI/tests;
            CoinGeckoPriceSource in production).

    Returns:
        float in [0.0, 1.0] — empirical base rate, or 0.5 if insufficient data.
    """
    from brier_pipeline.resolution.rules import materialise_horizon_deadline

    asset = claim.asset
    if asset is None:
        return 0.5

    direction = claim.direction
    if direction not in ("bullish", "bearish"):
        return 0.5

    # Compute horizon T in days.
    uttered_day: date = claim.uttered_at.date()

    effective_deadline = materialise_horizon_deadline(claim)
    if effective_deadline is not None:
        t_days = (effective_deadline - uttered_day).days
    else:
        t_days = 0

    # Fallback: T <= 0 means the horizon is degenerate or unknown; use 90d.
    if t_days <= 0:
        t_days = 90

    # Trailing window: [uttered_day - 5 years, uttered_day).
    # End is strictly before utterance so the base rate is a fair prior.
    window_end = uttered_day - timedelta(days=1)
    window_start = uttered_day - timedelta(days=365 * TRAILING_YEARS)

    closes_raw = prices.daily_closes(asset, window_start, window_end)
    if not closes_raw:
        return 0.5

    # Build a dict day -> close_usd for O(1) lookup.
    close_map: dict[date, float] = {}
    for p in closes_raw:
        if not p.data_gap:
            close_map[p.day] = p.close_usd

    if len(close_map) < 2:
        return 0.5

    # Rolling-window: for each start day d in the window, check if d+T exists.
    successes = 0
    total_windows = 0

    for d in sorted(close_map.keys()):
        d_plus_t = d + timedelta(days=t_days)
        if d_plus_t not in close_map:
            continue  # no T-day close available for this start
        c0 = close_map[d]
        ct = close_map[d_plus_t]
        total_windows += 1
        if direction == "bullish" and ct > c0:
            successes += 1
        elif direction == "bearish" and ct < c0:
            successes += 1
        # Exact ties count as not a success for either direction.

    # Minimum-windows convention (ADR-0009): insufficient history → 0.5.
    if total_windows < MIN_BASE_RATE_WINDOWS:
        return 0.5

    result = successes / total_windows
    # Clamp to [0, 1] — defensive; empirical ratio is always in range.
    return max(0.0, min(1.0, result))
