# PRD: Prediction Track-Record Engine, MVP

**Version:** 1.1 \| **Date:** 11 June 2026 \| **Owner:** Founding team
\| **Status:** Draft for build **Format note:** Markdown headings, ID'd
requirements (FR-xxx), and Gherkin acceptance criteria; imports directly
into Notion, Linear, Jira, and ClickUp. Each US/FR line can be created
as a ticket. **v1.1 changelog:** Section 2 rewritten as a date-stamped
prior-art survey claim; new build-spec sections 18-22 added (technical
stack, web UI spec, external resources, tooling, happy paths).

## 1. Executive Summary

An analytics platform that extracts falsifiable predictions from the
public content of crypto YouTube analysts, resolves each prediction
against subsequent market prices, and publishes a rigorous,
base-rate-corrected accuracy score per analyst with clip-level receipts.
MVP scope: 50 analysts, YouTube only, crypto assets only, 24-month
historical backfill, public leaderboard, analyst pages, methodology
page, weekly email, dispute intake. The product publishes statistics
about public statements; it never recommends instruments or actions.

## 2. Problem Statement

Retail investors allocate money based on public predictions from
analysts with no verifiable track record. Academic evidence (Swiss
Finance Institute "Finfluencers," 2023) shows the majority of
finfluencers destroy value while attracting the largest followings. A
documented prior-art search (June 2026) found no currently operating
service that combines independent, non-opt-in coverage of named
creator-economy finance figures with statistically honest scoring of
resolved predictions (base-rate correction, calibration); the nearest
analogs each fail at least one of these tests (see venture analysis,
Sections 1 and 4). Audiences cannot distinguish skill from confidence;
skilled creators cannot prove their difference.

## 3. Goals

- G1: Publish credible, receipt-backed accuracy scores for 50 named
  crypto YouTube analysts at launch.

- G2: Achieve extraction precision ≥ 95% and recall ≥ 80% against a
  hand-labeled golden set.

- G3: Resolve and score ≥ 10,000 historical claims from the 24-month
  backfill before launch.

- G4: Generate a launch moment: 25k unique visitors and 1,000 newsletter
  subscribers in the first 30 days.

- G5: Withstand the first wave of disputes with zero retractions caused
  by extraction error.

## 4. Non-Goals (MVP)

- No buy/sell/hold outputs, consensus signals, alerts framed as
  actionable, or auto-trading. Ever.

- No user accounts, comments, or social features.

- No equities, forex, or macro claims; crypto assets only.

- No X/Twitter, podcast, or newsletter ingestion.

- No mobile app, no public API, no creator badge sales (waitlist only).

- No coverage of Turkey-domiciled or BIST-focused influencers (legal
  posture, see Risks).

## 5. User Personas

- **P1 Berk, the Burned Power-Consumer.** 29, trades on Binance, watches
  6 hrs/wk of crypto YouTube, lost money on a hyped call, screenshots
  predictions to settle arguments. Wants receipts and rankings; pays
  nothing yet; supplies virality.

- **P2 Aylin, the Honest Analyst.** 80k-subscriber YouTuber with a
  genuinely decent record, drowned out by hype channels. Wants proof of
  skill she can display; future badge customer; potential launch ally.

- **P3 Jale, the Skeptical Journalist.** Finance reporter needing a
  citable, methodologically defensible source on finfluencer accuracy.
  Wants transparent methodology and a downloadable summary; supplies
  credibility.

## 6. User Stories

- US-001 (P1): As a viewer, I can see a ranked leaderboard of analysts
  by accuracy score so I know whose content to weight.

- US-002 (P1): As a viewer, I can open an analyst page and see every
  scored claim with its outcome, so the score is not a black box.

- US-003 (P1): As a viewer, I can play the exact clip moment of any
  claim via the embedded official player, so I can verify the extraction
  myself.

- US-004 (P1): As a viewer, I can read the price chart from utterance to
  resolution for any claim.

- US-005 (P3): As a journalist, I can read a public methodology page
  versioned with a changelog, so I can cite the score responsibly.

- US-006 (P2): As a scored analyst, I can submit a dispute on a specific
  claim and receive a tracked response, so errors are correctable.

- US-007 (P1): As a viewer, I can subscribe to a weekly email of notable
  resolutions and rank changes.

- US-008 (P2): As an analyst, I can join a badge waitlist from my own
  page.

- US-009 (internal): As a reviewer, I can approve, correct, or void
  low-confidence extractions in a QA queue before they publish.

- US-010 (internal): As an operator, I can re-run scoring across all
  history when the methodology version changes, with the prior version
  archived.

## 7. Success Metrics

| **Metric** | **Target** | **Type** |
|----|----|----|
| Extraction precision on golden set | ≥ 95% | Quality gate (blocks launch) |
| Extraction recall on golden set | ≥ 80% | Quality gate |
| Resolved claims at launch | ≥ 10,000 | Dataset |
| Analysts ranked (n ≥ 20 resolved) | ≥ 40 of 50 | Dataset |
| Unique visitors, first 30 days | ≥ 25,000 | Growth |
| Newsletter subscribers, first 30 days | ≥ 1,000 | Growth |
| Badge waitlist signups | ≥ 50 | Demand signal |
| Disputes resolved within SLA (7 days) | 100% | Trust |
| Retractions due to extraction error | 0 | Trust |
| Leaderboard p95 load time | \< 2s | Performance |

## 8. Functional Requirements

**Ingestion**

- FR-101: Maintain an analyst registry (channel ID, display name,
  status, jurisdiction flag).

- FR-102: Poll registered channels for new uploads at ≤ 2h latency;
  fetch metadata via official API.

- FR-103: Acquire transcript via captions when available, else
  transcribe audio; store transcript with second-level offsets; audio is
  transient (30-day TTL).

- FR-104: Backfill all public uploads from the trailing 24 months per
  analyst.

**Extraction**

- FR-201: Detect candidate prediction spans in transcripts (pass 1).

- FR-202: Structure each span into {asset, direction or target,
  magnitude, horizon, stated confidence, conditionality, specificity
  class, source offset} (pass 2), with model and prompt versions
  recorded.

- FR-203: Route extractions below the confidence threshold to the human
  QA queue; nothing below threshold publishes unreviewed.

- FR-204: Classify non-falsifiable prediction-like statements and count
  them toward the falsifiability ratio without scoring them.

- FR-205: Deduplicate repeated claims (same analyst, asset, direction,
  overlapping horizon) via semantic similarity; repeats reinforce, not
  multiply.

**Resolution and scoring**

- FR-301: Maintain daily UTC close prices for the top 100 crypto assets
  from a published composite source.

- FR-302: Resolve claims per the published rule library (close-basis
  hits, default horizons, conditional activation, partial credit at
  0.5).

- FR-303: Compute base rates per claim from trailing 5-year asset
  history.

- FR-304: Compute component scores (directional skill, calibration,
  consistency, falsifiability) and the shrunk composite FAS per Section
  9 of the venture analysis; methodology is versioned; version bumps
  trigger full recomputation with the prior ledger archived.

- FR-305: Mark analysts with fewer than 20 resolved claims as
  "provisional" and exclude them from the ranked board.

**Public surface**

- FR-401: Leaderboard page: rank, FAS, n, falsifiability ratio, 90-day
  trend.

- FR-402: Analyst page: score breakdown, full claim table (filterable),
  each claim linking a receipt.

- FR-403: Receipt view: embedded official YouTube player seeked to the
  claim offset, claim card, price chart from t0 to resolution,
  resolution rationale.

- FR-404: Methodology page with versioned changelog and worked examples.

- FR-405: Dispute form per claim; intake creates a tracked ticket;
  public corrections log.

- FR-406: Weekly email digest; double opt-in; one-click unsubscribe.

- FR-407: SEO: every analyst page server-rendered with name-query
  metadata.

- FR-408: Badge waitlist capture on analyst pages.

## 9. Non-Functional Requirements

- NFR-1: Availability 99.5% for public pages; pipeline freshness alert
  if any analyst is stale \> 48h.

- NFR-2: Every published claim is reproducible: stored source pointer,
  transcript span, model/prompt versions, reviewer ID if QA-touched.

- NFR-3: Append-only audit ledger for scores; no silent edits;
  corrections are public events.

- NFR-4: No raw video hosting; clips play via official embeds only;
  quotes stored ≤ 15 words.

- NFR-5: Cost guardrails: hard monthly budget caps on transcription and
  LLM spend with alerts at 70%.

- NFR-6: GDPR/KVKK posture documented: legitimate-interest balancing
  test on file; erasure requests handled per policy within 30 days.

- NFR-7: All public copy uses neutral, non-pejorative language enforced
  by a reviewed style guide.

## 10. User Flows

- **UF-1 Browse:** Land on leaderboard → sort/filter → open analyst →
  scan claim table → open receipt → play clip → view price chart → back.

- **UF-2 Verify a viral screenshot:** Arrive via shared link to a
  receipt → watch clip → see resolution → explore analyst page →
  subscribe to email.

- **UF-3 Analyst dispute:** Analyst finds own page → opens claim →
  submits dispute with rationale → receives ticket ID → reviewer
  adjudicates within 7 days → claim corrected/upheld → public log
  updated → analyst notified.

- **UF-4 Internal QA:** Reviewer opens queue → sees transcript span +
  structured claim side by side → approve / correct / void → decision
  recorded with reviewer ID.

## 11. Data Flows

1.  Poller emits ingestion event → media/transcript stored (object
    storage) → transcript row (PG).

2.  Extraction service consumes transcript → claim candidates →
    structured claims (PG) → low-confidence subset → QA queue → approved
    claims flagged publishable.

3.  Price collector writes daily closes (PG/Timescale).

4.  Resolution job joins open claims × prices → outcomes appended.

5.  Scoring job recomputes affected analyst scores → materialized
    leaderboard views → cache invalidation.

6.  Web app reads materialized views; receipt pages resolve source
    pointers to embeds.

7.  Weekly digest job queries notable resolutions → email service.

## 12. Edge Cases

- EC-1 Deleted/privated video after claim capture: claim persists,
  source marked deleted, deletion flagged on receipt.

- EC-2 Re-uploads/edited re-posts: dedup via channel + transcript
  similarity; original timestamp governs.

- EC-3 Sarcasm, hypotheticals, paraphrasing others ("some say BTC
  will..."): pass-2 classifier excludes; QA catches residue; excluded
  items do not count against falsifiability.

- EC-4 Sponsored segments: claims inside detected sponsor reads are
  flagged and excluded from scoring (perverse incentives).

- EC-5 Guest speakers: MVP scores channel owner only; diarization
  uncertainty routes to QA.

- EC-6 Both-direction hedging: contradiction detector voids both claims,
  raises hedging flag.

- EC-7 Asset ambiguity (tickers, slang, "alts"): controlled vocabulary +
  alias table; unresolvable asset → void.

- EC-8 Exchange outage / stale price data: resolution deferred, never
  improvised; data-gap noted.

- EC-9 Stablecoin depegs and delisted tokens: resolve against last
  published composite close; token death resolves bearish claims true /
  bullish false at deadline.

- EC-10 Analyst legal threat: claim review fast-tracked; content stays
  up unless an extraction error is found; counsel notified per playbook.

- EC-11 Claim revised by analyst in later video: explicit reversal
  closes the original claim at the reversal date, scored to date; new
  claim opens.

- EC-12 Methodology version bump mid-dispute: dispute adjudicated under
  the version in force at publication; both ledgers retained.

## 13. Risk Analysis

| **Risk** | **Likelihood** | **Impact** | **Mitigation** |
|----|----|----|----|
| Extraction errors damage credibility at launch | Medium | Critical | Golden-set gate ≥95% precision; QA queue on low confidence; soft-launch audit of 300 random claims |
| Defamation claim from a scored analyst | Medium | High | Receipts-everything; neutral language; dispute SLA; opinion/methodology framing; counsel retainer; no Turkey-domiciled subjects |
| Platform/ToS friction (YouTube) | Medium | Medium | Official API for metadata; embeds for playback; transient audio; derived data only |
| Methodology attacked by quants | High | Medium | Publish formulas, base rates, worked examples; invite critique; academic reviewer pre-launch |
| Regulatory misclassification as advice | Low | Critical | No instrument-level outputs; non-goals enforced in code review; jurisdiction notes in copy |
| Backfill cost/time overrun | Medium | Low | Caption-first strategy; GPU batch transcription; cap at 24 months |
| Team bandwidth (part-time squad) | High | High | Scope locked to this PRD; weekly cut-line review; 90-day gate decision pre-scheduled |

## 14. Acceptance Criteria (launch gate, Gherkin)

- AC-1: Given the golden set of 200 labeled claims, when the current
  pipeline runs, then precision ≥ 95% and recall ≥ 80%.

- AC-2: Given any published claim, when a visitor opens its receipt,
  then the embedded player starts within 3 seconds of the claim offset
  and the price chart renders t0 → resolution.

- AC-3: Given an analyst with ≥ 20 resolved claims, when the leaderboard
  renders, then FAS, n, falsifiability, and trend display and match the
  score ledger exactly.

- AC-4: Given a methodology version bump, when recomputation completes,
  then every analyst's prior score remains queryable in the archived
  ledger.

- AC-5: Given a dispute submission, when 7 days elapse, then the ticket
  has an adjudication recorded and, if corrective, a public log entry.

- AC-6: Given a deleted source video, when its receipt is viewed, then
  the claim, deletion flag, and resolution remain visible.

- AC-7: Given the public site, when scanned, then zero instances of
  buy/sell/hold recommendation language exist (automated copy lint +
  manual review).

## 15. MVP Scope (in)

50 crypto YouTube analysts; 24-month backfill; ingestion, extraction,
QA, resolution, scoring v1; leaderboard; analyst pages; receipts;
methodology page; dispute intake; weekly email; badge waitlist;
corrections log.

## 16. Out of Scope (MVP)

Accounts/auth, X/podcast/newsletter ingestion, equities, alerts, public
API, badge billing, consensus features, mobile apps, multilingual UI,
Turkish-market coverage, any portfolio or recommendation feature.

## 17. Future Roadmap (post-MVP, indicative)

- V1 (months 4-7): X ingestion (roster-scoped), accounts + follows +
  alerts, dispute workflow v2, badge program live, deleted-prediction
  archive, Receipts bot.

- V2 (months 8-16): US equities with benchmark-relative scoring,
  podcasts + newsletters, public API beta, first broker widget pilot,
  macro-pundit vertical.

- Later: cross-domain scoring (sports, politics, AI forecasts),
  white-label engine, quant data feed, localization after per-market
  legal review.

## 18. Technical Stack and Infrastructure (MVP)

Principle: boring, managed, cheap. Every choice is optimized for a
2-engineer-equivalent team, replaceability, and the sub-\$500/mo
steady-state cost envelope in the financial model.

| **Layer** | **Choice** | **Why** |
|----|----|----|
| Frontend | Next.js (App Router) + TypeScript + Tailwind, deployed on Vercel | Server-rendered analyst pages for name-query SEO (core channel); zero-ops deploys |
| Charts | TradingView Lightweight Charts | Free, fast, the visual idiom this audience already trusts |
| Backend workers | Python 3.12 services in Docker on Fly.io or Railway | Ingestion, extraction, resolution, scoring as separate workers in one repo |
| Orchestration | Postgres-backed job queue + cron | Thousands of events/day at MVP; Airflow and Kafka explicitly rejected |
| OLTP database | Postgres 16 (Supabase) + pgvector | One engine for claims, prices, score ledger, dedup vectors; row-level audit |
| Leaderboard reads | Materialized views + Upstash Redis cache | Meets the p95 \< 2s requirement |
| Object storage | Cloudflare R2 | Zero egress; transcripts persistent, audio on a 30-day TTL lifecycle rule (NFR) |
| Transcription | faster-whisper large-v3 on one rented GPU (RunPod/Vast) for the backfill; Deepgram or Groq API for incremental | Backfill ~9,000 hrs one-off ~\$500-700 self-hosted; incremental ~\$130/wk via API |
| LLM | Haiku-class for both extraction passes with structured outputs; Sonnet-class for arbitration; LiteLLM router | Under \$300/mo at 50 analysts; provider-swappable in config |
| Eval harness | Golden-set tests in CI (promptfoo or pytest) | The AC-1 merge gate: a prompt or model change that drops precision fails the build |
| Email | Resend (transactional) + Buttondown (newsletter) | Minimal ops |
| Analytics | Plausible + Google Search Console | Privacy-clean; SEO is a measured channel, not a hope |
| Monitoring | Sentry + Axiom logs + Better Stack uptime; 48h staleness alert per NFR-1 |  |
| Auth | None on the public site (read-only); admin behind Supabase auth | Accounts are a V1 item by design |

## 19. Web UI Specification (responsive web; native apps remain out of scope)

Design stance: rating-agency aesthetic. Clinical, typographic,
data-forward, neutral palette with a single accent scale for FAS bands.
No meme styling; the legal posture depends on the site never looking
like a callout account.

**Pages (all P0):**

1.  **Leaderboard (home):** ranked table with rank, name + avatar, FAS
    badge, n, falsifiability %, 90-day trend sparkline; sort, minimum-n
    filter, search; provisional analysts in a collapsed secondary list;
    methodology version pinned in the footer.

2.  **Analyst profile:** score header (FAS plus four component bars:
    directional skill, calibration, consistency, falsifiability),
    outcome chip summary (hit/miss/partial/open/void counts), filterable
    claim table (asset, status, date), badge waitlist CTA.

3.  **Receipt (the viral unit):** claim card with structured fields and
    a quote of at most 15 words, embedded YouTube player auto-seeked to
    the claim offset, price chart from t0 to resolution with
    utterance/target/resolution markers, resolution rationale, dispute
    link, share button.

4.  **Methodology:** formulas, worked examples, versioned changelog.

5.  **Corrections log.** 6. **Dispute form** (per claim). 7. **About +
    Legal** (terms, privacy, GDPR/KVKK notice). 8. **Newsletter signup**
    embedded site-wide.

**Component inventory:** FASBadge (score, color band, provisional tag),
TrendSparkline, ClaimStatusChip, ReceiptPlayer, PriceChart, ClaimTable,
DisputeForm, ShareCard.

**Social/OG layer (P0, not polish):** auto-generated share cards per
receipt and per analyst (score, claim, outcome) via Vercel OG.
Screenshots are the growth loop; the share card is the product's ad
unit.

**Responsive behavior:** mobile-first breakpoints; tables collapse to
stacked cards under 640px; player full-width on mobile; sticky compact
nav; Lighthouse mobile score ≥ 90. No native app, no push notifications
(V1+).

**Accessibility:** WCAG AA contrast, full keyboard navigation on tables,
alt text on all generated cards.

## 20. External Resources and Data Sources

| **Resource** | **Use** | **Quota / cost / risk notes** |
|----|----|----|
| YouTube Data API v3 | Channel and video metadata, new-upload polling | Default 10k units/day; use playlistItems (1 unit) not search (100 units); request a quota raise before the backfill run |
| YouTube captions | Primary transcript source where present | Free; uneven quality, treat as draft and verify offsets |
| yt-dlp audio fallback | When captions are absent | ToS-gray; mitigations per venture analysis Section 10: transient audio, derived data only, no redistribution |
| YouTube IFrame Player | Receipt playback | No hosted copies; removes clip copyright exposure |
| CoinGecko API | Composite daily UTC closes, top 100 assets | Free tier is tight; Analyst tier ~\$129/mo if quota requires |
| CCXT (Binance, Coinbase) | Cross-check price source; outage detection feeding EC-8 | Free |
| Golden set (internal) | 200 hand-labeled claims from 40 videos | Produced in weeks 1-2; the most valuable artifact of the quarter |
| Media-law counsel | Pre-launch copy review, dispute playbook, takedown response templates | Retainer per the financial model |

## 21. Tooling

Mapped onto the stack the team already runs, so day-one setup cost is
near zero:

- **Source and CI:** GitHub Team; GitHub Actions with the golden-set
  eval as a required status check.

- **IDE and codegen:** Cursor / Copilot student tiers; Claude (Pro for
  design sessions, API key for the pipeline itself).

- **Tickets:** Linear. Import this PRD: Section 6 becomes stories,
  Section 8 becomes scoped tasks, Section 14 becomes the QA test suite,
  Section 22 becomes the demo script.

- **Docs and ops:** Google Workspace (analyst roster sheet, QA rota,
  dispute inbox as a shared mailbox).

- **Labeling/QA:** Label Studio, self-hosted; implements the FR-203
  review queue; staffed by the part-time team on a rota.

- **LLM ops:** LiteLLM config in-repo; promptfoo eval suite; Langfuse
  tracing optional.

- **Design:** one shared Figma file holding the Section 19 component
  inventory.

- **Newsletter/transactional:** Buttondown, Resend.

- **Analytics/SEO:** Plausible, Search Console.

- **Monitoring:** Sentry, Axiom, Better Stack.

- **Secrets:** platform environment vaults plus a shared 1Password
  vault.

## 22. Happy Paths

The expected, branch-free success scenario for each core flow; the
mirror image of Section 12's edge cases. QA scripts these first; the
investor demo runs HP-2 and HP-3 live.

- **HP-1 Ingest to publish:** analyst uploads at 14:00 → poller detects
  by 16:00 → captions retrieved → pass 1 flags 3 candidate spans → pass
  2 structures all 3 above the confidence threshold → auto-published →
  claims visible on the analyst page by 20:00 (six-hour budget end to
  end).

- **HP-2 Resolution to leaderboard:** open claim "BTC daily close above
  \$80k by Jul 31" → nightly job finds a qualifying close on Jul 14 →
  outcome HIT recorded with the price citation → scoring job recomputes
  the analyst → materialized leaderboard refreshes → claim queued for
  the Friday digest.

- **HP-3 Visitor verification loop:** visitor taps a shared receipt card
  on X → receipt loads, player starts at the claim offset within 3
  seconds (AC-2) → price chart confirms the outcome → visitor opens the
  analyst profile → browses the leaderboard → subscribes to the
  newsletter and confirms double opt-in.

- **HP-4 QA review:** pass 2 emits a claim at 0.62 confidence → routed
  to the Label Studio queue → reviewer compares transcript span against
  structured fields → corrects the horizon from the 90-day default to
  the "end of year" stated in the video → approves → published with
  reviewer ID logged (NFR-2).

- **HP-5 Corrective dispute:** analyst disputes a claim's asset
  attribution → ticket ID auto-emailed → reviewer re-checks clip and
  transcript, confirms an extraction error → claim corrected and
  re-resolved → public corrections log entry created → analyst notified,
  all inside the 7-day SLA (AC-5).

- **HP-6 Methodology bump:** scoring v1.1 merged → CI golden tests pass
  → full-history recompute completes → the v1.0 ledger stays archived
  and queryable (AC-4) → changelog entry published → scores display the
  new version tag.

- **HP-7 Weekly digest:** Friday 09:00 job compiles the week's notable
  resolutions and rank moves → founder edits the draft in Buttondown →
  send at 14:00 → opens and clicks tracked.
