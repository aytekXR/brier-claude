# ADR-0009: Base rates from trailing 5-year history

- **Status:** proposed (pending human approval)
- **Date:** 2026-06-15
- **Deciders:** human owner (approval pending) + scoring-quant (proposing, E4-T2)

## Context

Task E4-T2 (FR-303) implements real empirical base rates to replace the E1
fixture placeholders stored in `claims.flags['fixture_base_rate']`. METHODOLOGY
§3 defines the base rate as:

> "the empirical probability that a naive position matching the claim's
> direction succeeded over horizon T on that asset, using trailing 5-year
> history."

The fixture placeholder (defaulting to 0.5) was used during E1 to bootstrap the
scoring engine. Using a fixed 0.5 for all claims understates the base-rate
correction for assets with persistent directional regimes (e.g. BTC in a
multi-year bull run where a naive bullish position wins > 60% of 30-day
windows). This is the primary motivation for the version bump: the formula is
unchanged, but the data powering `b_i` is now real.

### Methodology change

Because `b_i` is part of the DS formula (`DS = Σ w_i (y_i − b_i) / Σ w_i`),
changing how `b_i` is computed changes every analyst's DS and therefore their
FAS. This is a **methodology version bump** (FR-304, AC-4): v1.0 → v1.1.
Per CLAUDE.md and FR-304, a version bump requires:
- An ADR (this document).
- A full-history recompute via `recompute_all("v1.1")`.
- The prior v1.0 ledger archived and queryable (append-only; DB triggers).
- A changelog row in METHODOLOGY.md.

### Dependency discipline

The stack is locked. No new runtime dependency may be added without human
approval. Two price-source paths are needed:

1. **FakePriceSource** — fixture-backed, already implemented (E1-T1). Reads
   `data/fixtures/prices/{asset}.json`. Always the CI/demo path.
2. **CoinGecko** — the published composite source (FR-301). Its API is a plain
   JSON REST endpoint. Following the same precedent as ADR-0005 (Anthropic LLM)
   and the Deepgram adapter (E2-T4), this is implemented via stdlib
   `urllib.request` + `json` — **no coingecko SDK**, no new package. An
   injectable `http_get` callable boundary allows tests to inject recorded
   responses without network access.
3. **CCXT cross-check** (EC-8 outage/divergence detection) — a heavy package
   with many exchange adapters. Per the ADR-gate convention, this is landed as
   a **seam only** (option b): lazy `import ccxt` inside the method body raises
   `RuntimeError` when absent; a `[[tool.mypy.overrides]]` stanza in
   `pyproject.toml` suppresses the missing-import mypy error (same pattern as
   `faster_whisper`, `boto3`, `sentence_transformers`). The CCXT cross-check is
   NOT part of the base-rate computation; it is for outage detection. It is
   blocked-by-design pending a separate ADR for its approval.

## Decision (proposed)

### `base_rate(claim, prices)` in `resolution/base_rates.py`

Empirical probability that a naive direction-matching position succeeded over
the claim's horizon T on that asset, from daily closes in the trailing 5-year
window ending strictly before the claim's utterance date.

**Trailing window:** `[uttered_at − 5 years, uttered_at)` — strictly before
utterance, so the base rate is a fair prior known at the time the claim was
made. Uses `prices.daily_closes(asset, start, end)`.

**Horizon T:** `(effective_deadline − uttered_at.date()).days`, computed via
`materialise_horizon_deadline` from `resolution/rules.py`. Fallback: T = 90
days when T ≤ 0 or no horizon is computable (the §1 default-horizon
convention).

**Rolling-window empirical probability:**
For each start day d in the trailing window such that a close at d+T exists:
- bullish: `close[d+T] > close[d]` → success
- bearish: `close[d+T] < close[d]` → success
- exact ties are not successes for either direction.
`base_rate = successes / total_windows`

**Minimum-windows convention (published, reproducible):**
If fewer than `MIN_BASE_RATE_WINDOWS = 20` (overlapping) T-day windows exist in
the trailing history, return **0.5** (neutral prior — insufficient evidence).
This threshold protects against estimates dominated by a handful of noisy
observations from very thin history. Value rationale: the code counts
*overlapping* windows (one per start day with a d+T close), so 5-year history at
T = 90 yields ~1825 − 90 ≈ 1735 windows — far above the floor. The "~1825/90 ≈
20" figure describes *non-overlapping* 90-day blocks, the statistically
meaningful sample count; 20 is set conservatively against the non-overlapping
count so the floor only trips on genuinely short history (a few hundred days).

**Clamped to [0.0, 1.0].**

**Data-gap handling:** days flagged `data_gap = True` in the PriceSource are
excluded from `close_map`. If fewer than 2 closes remain after gap exclusion,
return 0.5.

### `CoinGeckoPriceSource.daily_closes` in `resolution/prices.py`

Modeled on ADR-0005 (stdlib-REST seam):
- `urllib.request` + `json` only. No coingecko SDK, no new package.
- Accepts an injected `http_get(url, headers) -> dict` callable (default = real
  urllib call). Tests inject recorded responses from
  `data/fixtures/coingecko/btc_market_chart_range.json`.
- Raises `RuntimeError` referencing ADR-0009 when `BRIER_COINGECKO_API_KEY` is
  absent and no `http_get` is injected.
- Maps asset tickers to CoinGecko coin IDs via `_COINGECKO_ASSET_ID`.
- Calls `/coins/{id}/market_chart/range?vs_currency=usd&from=…&to=…`.
- Parses `[[timestamp_ms, price], ...]` response format.

### `CcxtCrossCheckSource` in `resolution/prices.py` — seam only

- Lazy `import ccxt` inside `_get_exchange()`. Raises `RuntimeError` when ccxt
  is absent.
- Injected `exchange_factory` is the test path.
- `[[tool.mypy.overrides]]` stanza in `pyproject.toml` for `ccxt` (same
  mechanism as faster_whisper, boto3, sentence_transformers).
- ccxt is NOT added to `[project.dependencies]` or any optional extra.
- **BLOCKED-by-design:** installing ccxt requires a separate ADR and human
  approval. The CCXT cross-check sub-item is recorded in `EX-dept.md`.

### Scoring wiring

`PriceSource` is threaded through the scoring pass:
- `_load_resolved_claims(cur, prices)` — calls `base_rate(claim, prices)` for
  each claim.
- `_execute_scoring_pass(..., prices=prices)` — passes prices to
  `_load_resolved_claims`.
- `run_score_pass(..., prices=None)` — defaults to
  `FakePriceSource(fixtures_dir)` so CI/demo keep working with no network.
- `recompute_all(..., prices=None)` — same default.

The pure `score_analyst_pure` function and the worked examples in
`test_fas.py` are unaffected: they pass explicit base rates and do not use the
`PriceSource` at all.

### Version bump

`config.METHODOLOGY_VERSION` is bumped from `"v1.0"` to `"v1.1"`. The
full-history recompute is demonstrated in `tests/test_recompute.py`
(`test_recompute_all_writes_new_score_run`): `recompute_all("v1.1", ...)` writes
a new `methodology_bump` score_run under v1.1 while the prior v1.0 runs survive
queryable (append-only).

### CI / no-network guarantee

`FakePriceSource` is the only PriceSource exercised by `make check`. The
CoinGecko seam is tested only with injected recorded fixtures. No test hits the
network, touches a live API, or requires any credential. The `ccxt` seam raises
`RuntimeError` (not a test failure) when the package is absent.

## Consequences

- **Methodology version bump to v1.1.** All score runs from this point forward
  are stamped v1.1. Prior v1.0 runs are archived and queryable (append-only
  ledger, DB triggers).
- **Full-history recompute required** on deployment: `recompute_all("v1.1")`.
- **Fixture-analyst FAS values DO change, and the demo inversion shifts.** The
  fixture corpus (~558 daily closes, 2024-12-01 .. 2026-06-11) returns a REAL
  (often extreme 0.0/1.0) empirical base rate for claims uttered within the
  window (2025+) at horizons up to ~538 days; only pre-fixture utterances or very
  long horizons fall back to 0.5. Concretely, under v1.1 the illustrative HP-1
  inversion moves from NorthChain-vs-Aylin to VectorEdge-vs-Aylin (see
  `tests/test_demo_e2e.py`): NorthChain's Apr-2025 bullish calls get real_b=0.000
  (a thin, trending fixture slice with no counter-examples) and Aylin's Mar-2025
  bearish hits get real_b=1.000, while VectorEdge's Dec-2024 calls fall under the
  20-window floor and keep b=0.5. **This shift is fixture-data-driven, not a
  formula change**; with real 5-year history base rates would be non-degenerate.
  The thin demo fixture is flagged as a follow-up (extend the price fixtures to a
  multi-year span for a fully measured demo). The binding pure worked examples in
  `tests/test_fas.py` use explicit base rates and are unaffected.
- **No new runtime dependency.** CoinGecko uses stdlib; CCXT is a lazy-import
  seam blocked-by-design.
- **Scope:** `resolution/base_rates.py`, `resolution/prices.py`,
  `scoring/fas.py`, `config.py`, `demo.py`, `docs/METHODOLOGY.md`,
  `pyproject.toml` (mypy override only), `tests/test_base_rates.py`,
  `tests/test_prices.py`, `tests/test_fas.py` (version assertions).
- **This ADR is not yet accepted.** Until the human owner approves, the
  implementation is in place but the conventions are provisional. Changing the
  minimum-windows threshold, the rolling-window definition, or the trailing-
  history length requires the owner's approval, a new ADR (or amendment per
  ADR-0001), and a methodology version bump (FR-304).
