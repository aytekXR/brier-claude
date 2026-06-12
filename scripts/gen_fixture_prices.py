#!/usr/bin/env python3
"""Generate deterministic fixture price series for BTC, ETH, SOL.

Output: data/fixtures/prices/{BTC,ETH,SOL}.json
Run once; the output is what is committed. This script is seeded for
determinism — the same script always produces the same output.

Constraints (from TASKS.md E1-T1 / HP-2):
- Date range: 2024-12-01 through 2026-06-11 inclusive (558 days).
- BTC daily closes stay BELOW 80000 from 2025-05-01 through 2025-07-13.
- BTC close on 2025-07-14 is exactly 80140 (the HP-2 canonical citation).
- Series must be smooth-ish and realistic-looking.
- Claim set consistency: specific p0/target checks below.

BTC narrative:
  2024-12-01: ~97000 (post-election rally)
  2024-12-31: ~107000 (year-end peak)
  2025-01-15: ~102000
  2025-02-28: ~86000 (correction)
  2025-03-31: ~83000
  2025-04-30: ~79500 (below 80k)
  2025-05-01 to 2025-07-13: dip/consolidation 65000-79500 (must stay below 80000)
  2025-07-14: 80140 (HP-2 HIT)
  2025-07-31: ~82000
  2025-12-31: ~91000
  2026-06-11: ~87000

ETH narrative:
  2024-12-01: ~3650
  2024-12-15: ~3900
  2025-01-31: ~3200
  2025-06-30: ~2600
  2025-12-31: ~3100
  2026-06-11: ~2900

SOL narrative:
  2024-12-01: ~230
  2024-12-31: ~240
  2025-06-30: ~155
  2025-12-31: ~185
  2026-06-11: ~178
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import TypedDict


class PriceRow(TypedDict):
    asset: str
    day: str
    close_usd: float
    source: str


REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "fixtures" / "prices"
OUT_DIR.mkdir(parents=True, exist_ok=True)

START = date(2024, 12, 1)
END = date(2026, 6, 11)


def all_days() -> list[date]:
    days = []
    d = START
    while d <= END:
        days.append(d)
        d += timedelta(days=1)
    return days


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def smooth_series(
    anchors: list[tuple[date, float]], days: list[date], seed: int, noise: float
) -> list[float]:
    """Interpolate between anchors with smooth noise."""
    rng = random.Random(seed)

    def anchor_value(d: date) -> float | None:
        for anchor_date, val in anchors:
            if anchor_date == d:
                return val
        return None

    # Build interpolated baseline
    values: list[float] = []
    anchor_dates = [a[0] for a in anchors]
    anchor_values = [a[1] for a in anchors]

    for d in days:
        # Find surrounding anchors
        idx = 0
        for i, ad in enumerate(anchor_dates):
            if ad <= d:
                idx = i
        if idx == len(anchor_dates) - 1:
            base = anchor_values[-1]
        else:
            t0, t1 = anchor_dates[idx], anchor_dates[idx + 1]
            v0, v1 = anchor_values[idx], anchor_values[idx + 1]
            span = (t1 - t0).days
            frac = (d - t0).days / span if span > 0 else 0.0
            # Smooth step
            t_smooth = frac * frac * (3 - 2 * frac)
            base = lerp(v0, v1, t_smooth)
        values.append(base)

    # Add smooth noise (low-frequency random walk)
    walk = 0.0
    alpha = 0.08  # persistence
    for i in range(len(values)):
        shock = rng.gauss(0, noise)
        walk = alpha * shock + (1 - alpha) * walk
        values[i] = values[i] * (1 + walk)

    return values


def generate_btc(days: list[date]) -> list[PriceRow]:
    anchors = [
        (date(2024, 12, 1), 97000.0),
        (date(2024, 12, 20), 106000.0),
        (date(2024, 12, 31), 107000.0),
        (date(2025, 1, 15), 102000.0),
        (date(2025, 2, 1), 95000.0),
        (date(2025, 2, 28), 86000.0),
        (date(2025, 3, 31), 83000.0),
        (date(2025, 4, 15), 80500.0),
        # Must stay below 80000 from 2025-05-01 through 2025-07-13
        (date(2025, 4, 30), 79800.0),
        (date(2025, 5, 15), 72000.0),
        (date(2025, 6, 1), 68000.0),
        (date(2025, 6, 30), 70000.0),
        (date(2025, 7, 13), 76000.0),
        (date(2025, 7, 14), 80140.0),  # HP-2 exact
        (date(2025, 7, 31), 82000.0),
        (date(2025, 8, 31), 85000.0),
        (date(2025, 9, 30), 88000.0),
        (date(2025, 10, 31), 91000.0),
        (date(2025, 11, 30), 93000.0),
        (date(2025, 12, 31), 91000.0),
        (date(2026, 1, 31), 88000.0),
        (date(2026, 2, 28), 85000.0),
        (date(2026, 3, 31), 84000.0),
        (date(2026, 4, 30), 85500.0),
        (date(2026, 5, 31), 87000.0),
        (date(2026, 6, 11), 87000.0),
    ]

    values = smooth_series(anchors, days, seed=42, noise=0.012)

    # Enforce the hard constraints: HP-2 days
    # Find day indices for the constraint window
    day_index = {d: i for i, d in enumerate(days)}
    may1 = date(2025, 5, 1)
    jul13 = date(2025, 7, 13)
    jul14 = date(2025, 7, 14)

    # Pin HP-2 date exactly
    values[day_index[jul14]] = 80140.0

    # Clamp 2025-05-01 through 2025-07-13 below 80000
    for d in days:
        if may1 <= d <= jul13:
            i = day_index[d]
            if values[i] >= 80000.0:
                values[i] = min(values[i], 79800.0)

    # Also clamp 2025-04-30 below 80000 to be safe
    d_apr30 = date(2025, 4, 30)
    if d_apr30 in day_index:
        values[day_index[d_apr30]] = min(values[day_index[d_apr30]], 79800.0)

    rows: list[PriceRow] = []
    for d, v in zip(days, values):
        rows.append(
            {
                "asset": "BTC",
                "day": d.isoformat(),
                "close_usd": round(v, 2),
                "source": "fixture-composite",
            }
        )
    return rows


def generate_eth(days: list[date]) -> list[PriceRow]:
    anchors = [
        (date(2024, 12, 1), 3650.0),
        (date(2024, 12, 15), 3900.0),
        (date(2024, 12, 31), 3750.0),
        (date(2025, 1, 15), 3500.0),
        (date(2025, 1, 31), 3200.0),
        (date(2025, 2, 28), 2900.0),
        (date(2025, 3, 31), 2700.0),
        (date(2025, 4, 30), 2500.0),
        (date(2025, 5, 31), 2400.0),
        (date(2025, 6, 30), 2600.0),
        (date(2025, 7, 31), 2750.0),
        (date(2025, 8, 31), 2850.0),
        (date(2025, 9, 30), 2950.0),
        (date(2025, 10, 31), 3050.0),
        (date(2025, 11, 30), 3100.0),
        (date(2025, 12, 31), 3100.0),
        (date(2026, 1, 31), 2980.0),
        (date(2026, 2, 28), 2900.0),
        (date(2026, 3, 31), 2850.0),
        (date(2026, 4, 30), 2920.0),
        (date(2026, 5, 31), 2950.0),
        (date(2026, 6, 11), 2900.0),
    ]
    return [
        {
            "asset": "ETH",
            "day": d.isoformat(),
            "close_usd": round(v, 2),
            "source": "fixture-composite",
        }
        for d, v in zip(days, smooth_series(anchors, days, seed=137, noise=0.015))
    ]


def generate_sol(days: list[date]) -> list[PriceRow]:
    anchors = [
        (date(2024, 12, 1), 230.0),
        (date(2024, 12, 31), 240.0),
        (date(2025, 1, 31), 215.0),
        (date(2025, 2, 28), 190.0),
        (date(2025, 3, 31), 175.0),
        (date(2025, 4, 30), 155.0),
        (date(2025, 5, 31), 145.0),
        (date(2025, 6, 30), 155.0),
        (date(2025, 7, 31), 165.0),
        (date(2025, 8, 31), 170.0),
        (date(2025, 9, 30), 178.0),
        (date(2025, 10, 31), 182.0),
        (date(2025, 11, 30), 185.0),
        (date(2025, 12, 31), 185.0),
        (date(2026, 1, 31), 178.0),
        (date(2026, 2, 28), 172.0),
        (date(2026, 3, 31), 170.0),
        (date(2026, 4, 30), 174.0),
        (date(2026, 5, 31), 178.0),
        (date(2026, 6, 11), 178.0),
    ]
    return [
        {
            "asset": "SOL",
            "day": d.isoformat(),
            "close_usd": round(v, 2),
            "source": "fixture-composite",
        }
        for d, v in zip(days, smooth_series(anchors, days, seed=271, noise=0.018))
    ]


def main() -> None:
    days = all_days()
    print(f"Generating {len(days)} days from {START} to {END}")

    btc = generate_btc(days)
    eth = generate_eth(days)
    sol = generate_sol(days)

    for asset, rows in [("BTC", btc), ("ETH", eth), ("SOL", sol)]:
        path = OUT_DIR / f"{asset}.json"
        path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        print(f"  Wrote {len(rows)} rows to {path.relative_to(REPO_ROOT)}")

    # Verify HP-2 constraint
    btc_by_day = {r["day"]: r["close_usd"] for r in btc}
    hp2_val = btc_by_day.get("2025-07-14")
    assert hp2_val == 80140.0, f"HP-2 violation: 2025-07-14 BTC close = {hp2_val}"
    print(f"  HP-2 verified: BTC 2025-07-14 close = {hp2_val}")

    # Verify sub-80k window
    violations = []
    from datetime import date as date_t

    d = date_t(2025, 5, 1)
    end_d = date_t(2025, 7, 13)
    while d <= end_d:
        v = btc_by_day.get(d.isoformat(), 0)
        if v >= 80000.0:
            violations.append((d.isoformat(), v))
        d += timedelta(days=1)
    if violations:
        print(f"  WARNING: sub-80k constraint violated: {violations[:5]}")
    else:
        print("  Sub-80k window (2025-05-01 to 2025-07-13) verified clean.")

    # Print some sample prices for claim design
    print("\nSample BTC prices for claim design:")
    for d_str in [
        "2024-12-15",
        "2025-01-15",
        "2025-02-15",
        "2025-03-15",
        "2025-04-15",
        "2025-05-15",
        "2025-06-15",
        "2025-07-14",
        "2025-08-15",
        "2025-10-15",
        "2026-01-15",
    ]:
        print(f"  BTC {d_str}: {btc_by_day.get(d_str, 'N/A')}")

    print("\nSample ETH prices:")
    eth_by_day = {r["day"]: r["close_usd"] for r in eth}
    for d_str in [
        "2024-12-15",
        "2025-01-15",
        "2025-03-15",
        "2025-06-30",
        "2025-09-30",
        "2025-12-31",
    ]:
        print(f"  ETH {d_str}: {eth_by_day.get(d_str, 'N/A')}")

    print("\nSample SOL prices:")
    sol_by_day = {r["day"]: r["close_usd"] for r in sol}
    for d_str in [
        "2024-12-15",
        "2025-01-15",
        "2025-03-31",
        "2025-06-30",
        "2025-09-30",
        "2025-12-31",
    ]:
        print(f"  SOL {d_str}: {sol_by_day.get(d_str, 'N/A')}")


if __name__ == "__main__":
    main()
