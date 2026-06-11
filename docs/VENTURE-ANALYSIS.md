# The Prediction Track-Record Engine: Full Venture Analysis

**Working name:** Receipts (placeholder) **Prepared:** 10 June 2026 \|
**Status:** Internal strategy document, pre-build **Companion
document:** MVP PRD (separate file, Jira/Linear/Notion importable)
**Verdict up front:** BUILD, modified. Crypto plus YouTube only,
analytics-only, media-first GTM. Conviction 7/10 at venture scale (the
early study's 8/10 is too generous on consumer monetization and silent
on team commitment). Hard kill/scale gate at day 90.

## 1. Problem Validation

**The exact pain point.** Millions of retail investors allocate real
money based on the public predictions of analysts, YouTubers, and X
personalities who carry zero verifiable track record. Confidence is the
product; accuracy is unmeasured. No currently operating, independent,
non-opt-in scoreboard scores this universe's resolved predictions with
statistical honesty: existing analogs cover sell-side analysts
(TipRanks, StarMine), rank influence rather than accuracy (LunarCrush,
listicles), score only opt-in forecasters (Metaculus, Good Judgment), or
are defunct (CXO Guru Grades, PunditTracker). The result is a market for
financial information where the loudest, not the most accurate, voices
win.

**The evidence that this is real, not assumed.** The academic record is
unusually strong for a consumer idea:

- The Swiss Finance Institute "Finfluencers" study (Kakhbod, Kazempour,
  Livdan, Schuerhoff, WP 23-30) analyzed 29,000 StockTwits accounts and
  found only 28% of finfluencers are skilled (+2.6% monthly abnormal
  returns), 16% are unskilled, and 56% are "antiskilled" (minus 2.3%
  monthly). Worse: antiskilled finfluencers have MORE followers and more
  influence on retail trading than skilled ones. Betting against them
  yields +1.2% monthly.

- CXO Advisory's "Guru Grades" project (2005 to 2012) graded roughly
  6,600 forecasts from 68 named market gurus and found average accuracy
  of about 47%, worse than a coin flip, with a spread from roughly 20%
  to high-60s percent.

So the market systematically rewards the wrong people, and the
dispersion is wide enough that a ranking is genuinely informative. That
is the business.

**Who feels it most.** (a) Active retail traders who already follow 5 to
20 creators and have been burned at least once. (b) Honest, genuinely
skilled creators who cannot prove they are different from the noise. (c)
Media and research desks who need a citable accountability source. (d)
Brokers and exchanges who need engagement content that is defensible.

**Vitamin or painkiller. Be honest.** For the retail consumer this is a
vitamin most days (curiosity, entertainment, vindication) that becomes a
painkiller only at the moment of loss. Vitamins monetize like media: low
ARPU, advertising, affiliate. For the honest creator it is a painkiller
(differentiation credential). For brokers it is a procurement line item
(engagement content with compliance cover). Plan revenue around the
painkiller buyers, plan distribution around the vitamin audience.

**Why now.** Four forces converged in the last 24 months:

1.  LLMs made extraction of structured, falsifiable claims from hours of
    rambling video economically trivial. Two years ago this product cost
    millions in NLP engineering; today extraction is cents per video.

2.  The finfluencer economy exploded post-2020 and regulators followed:
    FCA charges against finfluencers, SEC actions on touting, ASIC
    guidance, SPK enforcement against social-media stock promotion in
    Turkey. Accountability is in the zeitgeist.

3.  Prediction markets (Polymarket, Kalshi) normalized the idea that
    forecasts have scoreboards.

4.  Adjacent companies proved the category monetizes: TipRanks was
    acquired by Prytek at a \$200M valuation (Aug 2024) on an estimated
    \$20 to 30M revenue, claiming ~50M monthly users and enterprise
    clients including Nasdaq, Robinhood, and Morgan Stanley. Dub raised
    a \$30M Series A (May 2025, \$54.5M total) for influencer
    copy-trading. Autopilot reports over \$1B AUM. Money is flowing into
    "whose calls do I follow."

**How large is the opportunity. Honest sizing.** This is not
self-evidently a \$10B market.

- Bottom-up consumer: perhaps 100M+ people globally consume finfluencer
  content; the monetizable core (active traders who pay for tools) is
  maybe 5 to 15M; at media-grade conversion (1 to 3%) and \$8 to 12/mo,
  consumer subs cap out around \$50 to 300M ARR for the whole category,
  of which a winner takes a fraction.

- B2B2C and data: TipRanks demonstrates \$20 to 30M revenue is
  achievable selling analyst-accuracy content to brokers. The
  social-creator layer is whitespace TipRanks does not cover.

- Realistic ceiling for this company in finance only: a \$10 to 50M ARR
  data/media business. The \$100M+ case requires becoming the
  cross-domain accountability layer (macro pundits, sports tipsters,
  political forecasters, AI predictions) or the broker-distribution
  winner.

Conclusion: real pain, strong evidence, good timing, honest TAM that
supports a venture outcome only via the B2B2C and platform-expansion
paths.

## 2. Customer Segmentation

Scores 1 (low) to 5 (high). Acquisition = ease of acquisition.

| **\#** | **Segment** | **Pain** | **Budget** | **Urgency** | **Market size** | **Acquisition** | **Composite** |
|----|----|----|----|----|----|----|----|
| 1 | Active crypto retail traders (consume 3h+/wk of analyst content) | 4 | 2 | 3 | 5 | 5 | **19** |
| 2 | Brokers / exchanges (engagement widgets, content) | 3 | 5 | 2 | 3 | 2 | **15** |
| 3 | Skilled mid-tier creators (need differentiation credential) | 4 | 3 | 4 | 2 | 4 | **17** |
| 4 | Brands / marketing teams vetting finfluencer partnerships (compliance exposure) | 4 | 4 | 3 | 2 | 3 | **16** |
| 5 | Quant funds / prop desks (skill-weighted sentiment signal) | 2 | 5 | 1 | 2 | 1 | **11** |
| 6 | Financial media / newsrooms (citable rankings, data journalism) | 3 | 2 | 2 | 2 | 4 | **13** |
| 7 | Equity retail traders (US) | 3 | 3 | 2 | 5 | 3 | **16** |
| 8 | Prediction-market traders (calibration shoppers) | 3 | 3 | 3 | 1 | 4 | **14** |
| 9 | Academics / regulators (dataset users) | 2 | 1 | 1 | 1 | 3 | **8** |
| 10 | Discord/Telegram paid-group operators (want verified badge to sell access) | 4 | 3 | 4 | 1 | 3 | **15** |

**Ranked priority:** 1) Crypto retail (distribution engine, not the
revenue engine). 2) Skilled creators (first dollars: badges,
dashboards). 3) Brands/compliance vetting (quiet B2B wedge with real
budgets, almost zero competition). 4) Brokers/exchanges (the
TipRanks-proven path to \$10M+, long sales cycle). 5) Equity retail (V2
expansion). Quant funds are seductive and slow: park until the dataset
has 18+ months of depth.

## 3. ICP Analysis

**Best early-adopter ICP: the Burned Crypto Power-Consumer.**

| **Dimension** | **Profile** |
|----|----|
| Demographics | Male-skewing, 22 to 40, global English-speaking (US, UK, SEA, MENA, Turkey diaspora), \$5k to \$250k portfolio, trades on Binance/Coinbase/Bybit |
| Psychographics | Skeptical-but-addicted; values "receipts" culture; status from being early and being right; resentment toward grifters is an active identity |
| Behavior | Watches 3 to 10 hrs/wk of crypto YouTube; follows 10 to 30 accounts on X; in 2+ Discords/Telegrams; has paid for TradingView, a paid group, or a newsletter before; screenshots predictions to dunk later |
| Current alternatives | Memory and vibes; manual screenshot folders; community callout threads; "is X legit" Reddit searches; nothing systematic |
| Willingness to pay | \$0 for accountability alone; \$10 to 20/mo if bundled with utility (alerts when a high-scoring analyst posts, consensus stats, deleted-prediction archive) |
| Acquisition channels | X threads and quote-RTs, r/CryptoCurrency and r/CryptoMarkets, YouTube collabs and react videos, crypto newsletters, SEO on "\[analyst name\] track record" |

**Top 5 ICPs ranked:**

1.  **Burned crypto power-consumer** (above): cheapest to reach, fuels
    virality, low direct revenue.

2.  **Mid-tier honest crypto YouTuber** (20k to 300k subs, actually
    decent record, drowned out by hype channels): pays \$49 to 199/mo
    for a verified badge plus calibration dashboard; each badge embedded
    in their channel is free distribution.

3.  **Influencer-marketing or compliance manager at an exchange/fintech
    brand**: personally liable for promo blowups post-FCA/SEC
    enforcement; pays \$500 to 2,000 per vetting report or \$1k+/mo
    monitoring; reachable via LinkedIn and conference sponsors lists.

4.  **Content/growth lead at a mid-size broker or exchange**: wants
    differentiated, defensible engagement content; \$3k to 30k/mo
    licensing; 6 to 9 month cycle.

5.  **Data-journalist / finance editor**: pays little but launders
    credibility; one Bloomberg/FT citation is worth more than \$50k of
    ads.

## 4. Competitive Landscape

| **Competitor** | **Type** | **Model** | **Funding/Status** | **Strengths** | **Weaknesses** | **Our differentiation** |
|----|----|----|----|----|----|----|
| **TipRanks** | Direct (closest analog) | B2B2C widgets to brokers (Nasdaq, Robinhood, Morgan Stanley) + consumer premium | Acquired by Prytek at \$200M valuation, Aug 2024; est. \$20-30M rev; ~50M MAU claimed | Distribution, brand, 10+ yrs of analyst data, profitable | Covers sell-side analysts and bloggers, not YouTube/podcast/Telegram creators; structured-source dependent; not extraction-native | We score the unstructured creator economy they cannot parse; LLM-native extraction from video/audio |
| **Dub** | Indirect, dangerous | Regulated copy-trading app, \$10/mo, creator royalties; SEC-registered adviser + broker-dealer | \$30M Series A (May 2025), \$54.5M total, 1M+ downloads | Verified real-money track records (stronger truth signal than extracted claims); monetization solved; VC fuel | Only covers people who port portfolios into Dub; ignores the 99% of influencers who never will; regulated cost base | We cover everyone's PUBLIC claims without their consent; we are the accountability layer, they are the execution layer |
| **Autopilot (Iris)** | Indirect | Copy politician/fund portfolios via linked brokerages | ~\$7.5M raised; \$1B+ AUM reported; Public partnership | Viral hooks (Pelosi tracker), AUM scale | Disclosure-based (13F/PTR lags), not prediction-based | Same as Dub: we score speech, not portfolios |
| **eToro CopyTrader** | Indirect incumbent | Brokerage; copy verified traders | Public co | Massive, verified, real money | Closed garden; no coverage of external influencers | Neutral referee across all platforms |
| **Polymarket / Kalshi** | Adjacent | Prediction markets; accuracy via skin in the game | Heavily funded | Gold-standard incentive design; cultural momentum | Score markets, not pundits; influencers do not bet there | We can map influencer claims TO market odds (great content + affiliate) |
| **Metaculus / Good Judgment** | Adjacent | Forecasting platforms, Brier-scored communities | Niche | Methodological credibility | Opt-in forecasters only; zero coverage of finfluencers | We score the unwilling; borrow their scoring science |
| **StockTwits / sentiment vendors** | Indirect | Sentiment aggregation | Mature | Volume of signal | Sentiment is not accuracy; no individual accountability | Skill-weighting beats raw sentiment |
| **HypeAuditor / Modash / Favikon** | Creator-ranking | Influencer analytics for marketers (audience quality, fraud) | Funded SaaS | Own the brand-vetting budget line | Measure engagement authenticity, NOT prediction accuracy | Accuracy vetting is a new column they do not have; partner or out-position |
| **LSEG StarMine / Institutional Investor rankings** | Financial intelligence | Sell-side analyst accuracy scoring for institutions | Incumbent | Decades of methodology credibility | Institutional only, sell-side only, expensive | Consumer-facing, creator-economy coverage |
| **Quiver Quantitative / Unusual Whales** | Indirect | Alt-data for retail (congress trades, flow) | Bootstrapped/small | Proven retail willingness to pay for accountability-flavored data | No prediction extraction or scoring | Direct overlap is small; possible acquirers or partners |
| **AI-native upstarts (LLM "scorecard" projects, X bots grading callers)** | Emerging | Mostly free bots/sites, ad-hoc | Pre-seed noise | Fast, viral-native | No methodology rigor, no resolution infrastructure, die fast | Statistical honesty + longitudinal infrastructure is the bar they cannot clear casually |
| **X/Grok or YouTube native** | Platform risk | Could auto-grade creators natively | n/a | Distribution monopoly, free data | Conflict of interest (creators are their customers); accountability hurts engagement | Neutrality is structurally impossible for platforms; our independence IS the product |

**Most dangerous competitors, ranked:**

1.  **TipRanks/Prytek moving downmarket into social creators**: they
    have the brand, broker pipes, and now M&A appetite. Mitigation: move
    fast in crypto-creator whitespace; become the obvious acquisition
    rather than the roadkill.

2.  **Dub-style regulated copy-trading**: they own the monetizable
    end-state (execution). Mitigation: stay the neutral referee they
    cannot be (Dub scoring non-Dub influencers is conflicted); sell them
    data.

3.  **Platform-native grading (Grok)**: existential if it happens,
    unlikely to be rigorous or neutral. Mitigation: methodology
    credibility and cross-platform coverage.

4.  **A well-funded clone post-virality**: extraction is replicable.
    Mitigation: see Defensibility; speed plus ephemeral-data capture
    plus creator lock-in.

## 5. Defensibility

Brutal truth first: **the "proprietary longitudinal dataset" moat in the
early study is weaker than claimed for archived media.** YouTube
archives are public; a funded competitor can backfill three years of
history with the same LLMs in a quarter. The dataset is only
irreplicable where the source is ephemeral. Rank the real moats:

1.  **Referee brand + methodology credibility (strongest).**
    Accountability businesses are winner-take-most because a scoreboard
    is only valuable if it is THE scoreboard (FICO, Nielsen, Michelin,
    ELO). Credibility compounds: every survived dispute, every published
    methodology version, every academic citation raises the replication
    bar from "run the pipeline" to "earn a decade of trust." Invest
    here: public methodology, versioned scoring, an academic advisory
    reviewer, a visible dispute process.

2.  **Ephemeral capture (genuinely irreplicable data).** Live streams,
    deleted videos, edited posts, Telegram calls captured before
    deletion. A "Deleted Predictions Archive" cannot be backfilled by
    anyone who starts later, and it is also the most viral content
    category. This converts the weak archive moat into a real one, but
    only for data captured from day one. Start recording immediately,
    even before launch.

3.  **Creator-embedded distribution (network effect, moderate).** Once
    top-ranked creators display badges and cite their rank, the scored
    do the marketing, and switching scoreboards costs them their
    accumulated standing. Two-sided lock-in grows with every badge.

4.  **B2B integration moat (TipRanks playbook).** Broker widget
    contracts have 12-month-plus switching inertia and compliance review
    sunk costs.

5.  **Extraction-model advantage (weakest, temporary).** Frontier models
    improve for everyone. The durable residue is the labeled golden set,
    edge-case taxonomy, and resolution-rule library, which raise
    quality, not exclusivity.

**Strongest moat: referee brand, compounded by ephemeral capture.**
Treat the scoring methodology like a ratings agency treats its criteria:
public, versioned, defended, boring, unimpeachable.

## 6. Monetization: 22 Models, Ranked

Scales: Scalability and Complexity 1 (low) to 5 (high). ARR potential =
realistic steady-state for this company, not TAM.

| **\#** | **Model** | **Customer** | **Pricing** | **Scal.** | **Compl.** | **ARR potential** |
|----|----|----|----|----|----|----|
| 1 | Verified Track Record badge (pay to display, never pay to improve) | Creators | \$49-199/mo | 4 | 2 | \$0.5-3M |
| 2 | Creator calibration dashboard (private analytics on own claims) | Creators | \$29-99/mo | 4 | 2 | \$0.3-1.5M |
| 3 | Broker/exchange content widget (scores + receipts embedded in trading apps) | Brokers, exchanges | \$3k-30k/mo per client | 4 | 3 | \$2-15M |
| 4 | Consumer premium (alerts on high-scorers, deleted-prediction archive, full history) | Retail | \$8-15/mo | 5 | 2 | \$0.5-5M |
| 5 | Affiliate/CPA to exchanges and brokers from free tier | Retail (indirect) | \$50-300/funded acct | 5 | 1 | \$0.2-2M |
| 6 | Finfluencer vetting reports for brand/compliance teams | Brands, fintech marketers | \$500-2k/report or \$1-3k/mo | 3 | 2 | \$0.5-3M |
| 7 | Skill-weighted sentiment API (claims + scores, machine-readable) | Quant funds, prop desks | \$2-10k/mo | 4 | 3 | \$1-8M |
| 8 | Media data licensing + syndicated rankings | Newsrooms | \$1-5k/mo | 3 | 1 | \$0.1-0.5M |
| 9 | Annual "State of Finfluencer Accuracy" report | Institutions, brands | \$500-5k/copy + sponsor | 3 | 1 | \$0.1-0.5M |
| 10 | Newsletter + site advertising (the scorecard is media) | Advertisers | \$25-60 CPM | 4 | 1 | \$0.2-1.5M |
| 11 | Awards program ("The Calibration Awards") sponsorships | Sponsors | \$10-100k/yr | 2 | 1 | \$0.1-0.5M |
| 12 | White-label scoring engine (sports tipsters, fantasy, betting media) | Platforms | \$50-250k/yr | 4 | 4 | \$1-5M |
| 13 | Prediction-market affiliate ("disagree? trade it") | Polymarket/Kalshi users | rev-share | 3 | 1 | \$0.1-1M |
| 14 | Compliance monitoring of firms' own public-facing analysts | Banks, brokerages | \$20-100k/yr | 3 | 3 | \$0.5-3M |
| 15 | Pro terminal for desks (screeners, claim feeds, consensus stats) | Prop/retail pros | \$100-300/seat/mo | 4 | 3 | \$0.5-3M |
| 16 | Pay-per-audit ("score any influencer") one-off reports | Retail, journalists | \$5-29 each | 4 | 1 | \$0.05-0.3M |
| 17 | Calibration training course/simulator for traders | Retail learners | \$99-299 one-off | 3 | 2 | \$0.1-0.5M |
| 18 | LLM grounding-data licensing (claims corpus) | AI labs | \$100k-1M one-off | 2 | 2 | lumpy |
| 19 | Recruiting/scouting fees (funds finding skilled unknowns) | Funds | finder fees | 1 | 1 | \$0.05-0.2M |
| 20 | Sponsorship marketplace matching brands to high-integrity creators | Brands + creators | 10-15% take | 3 | 4 | \$0.3-2M |
| 21 | Talent representation of top-scoring analysts | Creators | take rate | 1 | 3 | conflict, reject |
| 22 | Token / on-chain reputation | Crypto natives | n/a | n/a | n/a | reject: regulatory + credibility suicide |

**Ranking logic.** Sequencing beats cherry-picking. Conflicts of
interest are the existential constraint: NEVER sell anything that lets a
scored party influence their score (kills \#21, constrains \#1 and \#20
to display-only and disclosure-heavy).

- **Fastest to \$100k ARR (months 4-9):** \#1 + \#2 (creator badge +
  dashboard). 80 creators at ~\$99/mo average gets there. Creators have
  urgent differentiation pain, are individually reachable, and every
  sale doubles as distribution. Supplement with \#5 affiliate and \#8
  media licensing.

- **Fastest to \$1M ARR (months 12-24):** add \#3 (two to four
  broker/exchange widget deals at \$10-25k/mo) + \#6 vetting + consumer
  premium \#4 at modest conversion. One mid-size exchange deal equals
  800 badge subscribers.

- **Fastest to \$10M ARR (years 3-4):** \#3 at scale (10-20 broker
  integrations, the TipRanks playbook), \#7 quant API once the dataset
  has 24+ months of depth, \#12 white-label into sports/betting
  verticals, consumer premium riding free-tier scale.

- **Fastest to \$100M ARR (year 6+, low probability):** cross-domain
  accountability layer (finance + macro + sports + politics + AI
  forecasts) with broker-grade distribution in each, plus the quant data
  business. Alternatively, abandon neutrality and become a regulated
  copy-trading allocator (Dub path): a different, capital-hungry
  company. Do not plan for this; preserve optionality.

## 7. Product Strategy

| **Phase** | **Features** | **Eng. complexity** | **Key risks** | **Timeline** |
|----|----|----|----|----|
| **MVP** | 50 crypto YouTube analysts; 24-month archive backfill; extraction + resolution + scoring v1; public leaderboard; analyst pages with timestamped receipt clips (embedded official player); methodology page; weekly "Receipts" email; dispute form | Medium. One pipeline, one platform, one asset class | Extraction precision below 95% destroys credibility on day one; scoring methodology attacked by quants | 12 weeks (see Section 19) |
| **V1** | X/Twitter ingestion for the same roster (pay-per-use API); user accounts, follows, alerts; creator dispute/appeal workflow with SLA; badge program + embeds; deleted-prediction archive; consensus statistics (descriptive only, never signals) | Medium-high | Dispute volume; X data cost discipline; badge conflict-of-interest optics | Months 4-7 |
| **V2** | US equities vertical (benchmark-relative scoring, corporate-action handling); podcast + newsletter ingestion; public API beta; first broker widget pilot; macro-pundit vertical (huge mainstream press surface) | High: equities resolution is 3x harder than crypto | Equity scoring disputes; broker compliance review cycles | Months 8-16 |
| **Long-term** | The accountability layer for public prediction: sports tipsters, political forecasters, AI-progress predictions; white-label engine; quant data products; multilingual (Turkish market only after legal review) | High | Regulatory drift, defamation exposure scaling with coverage of mainstream figures | Year 2+ |

Non-negotiable product principles: every score links to receipts (clip +
timestamp + price chart); every methodology change is versioned and
public; the product never says buy or sell, ever.

## 8. Technical Architecture (summary; full design in Section 18)

**Pipeline:** Channel registry → ingestion pollers → media/transcript
acquisition → transcription (faster-whisper self-hosted or Deepgram/Groq
API) → speaker diarization → two-pass LLM extraction (pass 1: candidate
claim spans; pass 2: structuring into asset, direction, magnitude,
horizon, confidence, conditionality) → human QA queue for low-confidence
extractions → claims store → resolution engine (scheduled jobs joining
claims against the price warehouse) → scoring engine → leaderboard/API →
web app + receipts bot.

**Per-source ingestion:**

- **YouTube (MVP):** Data API for channel/video metadata (free quota);
  captions where available; yt-dlp audio fallback transcribed in-house.
  Receipts playback via official embedded player at timestamp (no
  hosting of copies).

- **X (V1):** pay-per-use API at \$0.005/read; a 50-account roster is
  roughly \$50-150/mo, trivial at MVP scale; full-firehose ambitions hit
  the 2M-read cap (~\$10k/mo) then Enterprise at \$42-50k+/mo, so stay
  roster-scoped.

- **Podcasts (V2):** open RSS, same transcription path; diarization
  mandatory to attribute claims to host vs guest.

- **Newsletters (V2):** dedicated subscriber inboxes per analyst, parse
  on receipt; cleanest legal posture of all sources.

**Recommended stack:** LLMs: Haiku-class for extraction at volume,
Sonnet-class for QA arbitration and resolution-rule edge cases, behind a
provider-agnostic router (LiteLLM) with a frozen golden-set eval harness
gating any model/prompt change. Vector layer: pgvector for claim dedup
and semantic search (no dedicated vector DB until clearly needed; Qdrant
if outgrown). Warehouse: none at MVP; DuckDB for analytics, ClickHouse
at 10k+ analysts. Orchestration: Postgres-backed job queue or
Inngest/Temporal-lite patterns; do NOT install Airflow for an MVP moving
thousands, not millions, of events per day. Prices: CCXT + CoinGecko
(crypto), Polygon.io (equities later), official sources for macro claims
(FOMC statements).

## 9. Accuracy Score Framework

This is the intellectual core and the credibility moat. A naive
percent-correct rewards vague, frequent, hedged bull calls in bull
markets. The framework below is designed so that being vague, being
lucky, and being loud all fail to pay.

### 9.1 Claim record

Each scored claim i is a tuple: asset A, direction or target, horizon T
(deadline date), stated confidence c (imputed from language when absent:
"will" 0.85, "likely" 0.7, "could" excluded as non-falsifiable unless
paired with conditions), price at utterance P0, timestamp t0,
specificity class, source pointer (video ID + second offset).

**Default-horizon convention (published):** "soon" = 30 days; "this
year" = Dec 31; no horizon stated = 90 days. Conventions are part of the
public methodology; consistency beats cleverness.

### 9.2 Resolution

Outcome y ∈ {0, 0.5, 1}. Price basis: daily UTC close from a published
composite source (prevents wick-gaming disputes). "Hits \$X by D"
resolves 1 if any daily close meets X before D. Directional claims
resolve against the close at T. Partial credit 0.5 when direction is
right but stated magnitude is under half achieved. Conditional claims
("buy below \$250") activate only if the condition triggers, then score
over the default horizon. Macro claims resolve against official records.

### 9.3 Base rates: the honesty mechanism

For every claim, compute the base rate b = empirical probability that a
naive position matching the claim's direction succeeded over horizon T
on that asset, using trailing 5-year history. A 30-day bullish BTC call
in a trending regime can carry b ≈ 0.60. Skill is what remains after
subtracting b. This single device deletes the
perma-bull-in-a-bull-market illusion that destroys every naive
leaderboard.

### 9.4 Weights

- Specificity v: direction-only 1.0; direction + magnitude 1.5; explicit
  target + deadline 2.0; conditional 0.75. Non-falsifiable statements
  score nothing but are counted (see Falsifiability).

- Difficulty d = clamp( \|ln(Ptarget / P0)\| / (sigma_annual ×
  sqrt(T_years)), 0.25, 2.0 ); direction-only claims take d = 0.5. Bold,
  precise calls earn more; trivial calls earn little.

- Claim weight w = v × d, with diminishing weight (divide by sqrt of
  count) for more than 3 claims per asset per week, neutralizing spam
  strategies.

### 9.5 Component scores

- **Directional Skill:** DS = Σ w_i (y_i − b_i) / Σ w_i. Typically lands
  in −0.15 to +0.25.

- **Calibration:** Brier B = mean (c_i − y_i)^2 over claims with
  confidence; Calibration score C = clamp(1 − B / 0.25, 0, 1),
  normalized so that coin-flip-quality confidence scores zero.
  Overconfident wrong calls are punished hardest, which is exactly the
  failure mode of hype channels.

- **Consistency K:** 1 minus normalized dispersion of rolling 10-claim
  DS windows. Punishes one-hot-streak wonders.

- **Falsifiability F:** scored claims ÷ total extracted prediction-like
  statements. Hedging is not misscored; it is exposed as a published
  ratio. This metric alone is viral ("Analyst X: 8% of statements are
  checkable").

### 9.6 Composite and shrinkage

Raw composite R = 0.45·norm(DS) + 0.25·C + 0.15·K + 0.15·F, each
component mapped to \[0,1\]. Final score: **FAS = 100 × ( n·R +
k·R_prior ) / ( n + k )**, with shrinkage constant k = 25 and R_prior =
population median. Bayesian shrinkage (the IMDb-rating device) prevents
a 3-for-3 newcomer from topping the board. Ranking eligibility requires
n ≥ 20 resolved claims; below that, status is "provisional."

### 9.7 Anti-gaming inventory

1.  All-claims coverage: WE extract everything; no self-submission, no
    cherry-picking.

2.  Deletion persistence: claims survive source deletion and the
    deletion itself is flagged publicly ("the tape does not forget").

3.  Contradiction detection: opposite-direction claims on the same asset
    with overlapping horizons void both and raise a hedging flag.

4.  Base-rate correction (9.3) kills regime-riding.

5.  Brier penalty (9.5) kills confidence inflation.

6.  Frequency damping (9.4) kills spray-and-pray.

7.  Shrinkage + minimum n (9.6) kills small-sample flukes.

8.  Versioned methodology with public changelog; full-history
    recomputation on every version; no silent retro-edits. Credibility
    is the moat; this is its maintenance schedule.

### 9.8 Worked examples

**Analyst A, "Hype Caller":** 60 resolved claims, raw hit rate 68%. But
80% are direction-only bullish BTC/ETH calls with average b = 0.61 → DS
≈ +0.07 at low weights. Stated confidence averages 0.9 → Brier ≈ 0.27 →
C ≈ 0. Falsifiability 25%. **FAS ≈ 54.** Headline raw accuracy collapses
under the lens. **Analyst B, "Precision Caller":** 24 resolved claims,
raw hit rate 58%. Claims are target-plus-deadline (v = 2.0, avg b =
0.34, d ≈ 1.2) → DS ≈ +0.24 weighted. Confidence ≈ 0.6, well calibrated
→ C ≈ 0.7. Falsifiability 70%. Shrinkage (n = 24, k = 25) pulls it
halfway to prior, **FAS ≈ 71, flagged provisional until n ≥ 30.** Lower
raw accuracy, far higher score: the system is doing its job, and
explaining exactly this example publicly is the methodology marketing.

## 10. Regulatory Analysis

**The governing principle: publish statistics about other people's
public statements; never produce instrument-level guidance.** The early
study's analytics/advice line is correct; here is the jurisdictional
detail and the second-order traps.

**United States.** The Investment Advisers Act exempts bona fide
publications of general and regular circulation that are impersonal (the
publisher's exclusion, Lowe v. SEC, 1985). Leaderboards, scores, and
receipts are impersonal statistics about public speech, additionally
protected as opinion and truthful reporting. Danger zones that forfeit
the exclusion: personalized recommendations ("you should follow these
five"), aggregated consensus presented as a buy/sell signal,
auto-trading, or any per-user portfolio output. Their monetization idea
\#1 ("following top-ranked analysts for personal investing") must remain
a user behavior, never a product feature that selects instruments for a
user.

**European Union.** MiFID II investment-advice licensing plus the Market
Abuse Regulation Article 20 regime on producing or disseminating
investment recommendations (Delegated Regulation 2016/958). Scoring
third parties' recommendations is analytics; repackaging them into "top
analysts say buy BTC" digests can itself constitute a disseminated
recommendation. Keep aggregate outputs strictly descriptive (counts,
distributions, calibration), with no instrument-level directional
framing.

**Turkey (founder-specific, important).** Investment advisory under CML
No. 6362 is a licensed activity, and SPK has actively pursued
social-media stock promotion and manipulation cases. Two implications:
(1) do NOT cover BIST-focused Turkish influencers at launch; the
combination of SPK sensitivity and criminal defamation exposure under
TCK Art. 125 (insult, criminally actionable, frequently used) makes
Turkish public figures the worst possible first targets while the
founders reside in Ankara. (2) Incorporate the operating entity outside
Turkey (Delaware C-corp is the default for the planned investor base),
serve global English-language crypto creators first, and add Turkey only
after dedicated local counsel review.

**Defamation, all jurisdictions.** The defense architecture: publish
only what is verifiable (the clip, the timestamp, the price series),
label scores explicitly as opinion derived from a published methodology,
use clinically neutral language ("FAS 41, n = 37," never "fraud,"
"scammer," "grifter"), run a dispute process with a stated SLA and
public correction log, and carry media-liability/E&O insurance once
revenue exists. UK libel risk is plaintiff-friendly; consider deferring
UK-domiciled mainstream figures or ensuring airtight
truth-plus-methodology defense first. Expect legal threats as a
operating cost; they are also press.

**Platform terms and copyright.** YouTube: use the official Data API for
metadata, embed the official player for receipt playback (no hosted
copies, no copyright exposure for clips), keep raw audio transient,
store derived structured claims plus quotes under 15 words. yt-dlp
transcription of public videos is a ToS gray zone; the mitigation is
architectural (derived data, transient media) and behavioral (no
redistribution). X: stay inside the paid API. Expect DMCA takedown
harassment from low-scoring creators; budget for counter-notice
handling, since receipts are core criticism/commentary fair use.

**Privacy (GDPR/KVKK).** Scoring named individuals' public professional
statements rests on legitimate interest plus journalistic/academic
framing; honor erasure requests narrowly (account data yes,
public-interest scores of public statements defensibly no), document the
balancing test now, not after the first complaint.

**Mitigation summary:** foreign entity, crypto-first, English-first,
receipts-everything, neutral language, public methodology, dispute SLA,
insurance, and a standing relationship with one media-law firm before
the first viral leaderboard, not after.

## 11. Go-To-Market Strategy

**Core thesis: the product is media.** Every resolved prediction is a
content event; the dataset generates its own news daily. The founder's
professional background in journalism and editorial graphics is the
team's single biggest unfair advantage and should be treated as the GTM
engine, not a side skill.

**Launch (the set-piece).** Do not launch a website; launch a finding.
Backfill 24 months for 50 to 100 named crypto YouTubers, then publish
"The Receipts Report": *we scored N analysts' M predictions; K beat a
coin flip after base-rate correction.* Components: interactive
leaderboard, downloadable dataset summary, methodology page, one
ruthless data-visual thread, and pre-briefed journalists (founder's own
network). The Swiss Finance Institute and CXO Guru Grades findings are
the academic framing that makes coverage easy.

**First 100 users.** Hand-recruited: 60 power-consumers from crypto X
and two subreddits via DM with private beta access; 30 mid-tier honest
creators offered early badge waitlist and their own private scorecard
before publication (this converts potential enemies into launch allies);
10 journalists/researchers.

**First 1,000.** The launch report drops simultaneously as: X
mega-thread, r/CryptoCurrency + r/CryptoMarkets posts, Show HN ("we
scored 2,000 crypto predictions with an LLM pipeline": HN loves the
methodology angle), and the first issue of the weekly Receipts
newsletter. The scored analysts respond, angrily or proudly; every
response links the site.

**First 10,000.** Three repeatable engines: (1) **the Receipts bot** on
X auto-posting resolutions ("365 days ago, X said BTC \$150k by today.
Close: \$.. . Score updated."), (2) **SEO analyst pages**: every
"\[name\] track record" and "is \[name\] legit" query is high-intent,
zero-competition, and we own it permanently, (3) **monthly leaderboard
drop** as a recurring event with winners amplifying their rank (badge
embeds) and losers generating beef (design for the beef; keep language
clinical so the beef stays safe).

**First 100,000.** (4) Broker/exchange widget distribution (each
integration is a user firehose), (5) vertical expansion to macro pundits
(mainstream press magnet: "we graded the TV economists"), (6)
auto-generated Shorts/TikTok receipt clips, (7) affiliate loops with
exchanges.

**Channel-specific notes.** YouTube: collaborate with high-FAS creators
(they have every incentive); supply low-FAS react material to commentary
channels rather than making attack content ourselves. Reddit:
methodology AMAs; transparency is the brand. Influencer strategy: the
scored ARE the influencer strategy. Affiliate: exchanges and prediction
markets ("disagree with this analyst? the market is quoting 34%").

## 12. Distribution Analysis

A world-class founder would run this as a data-journalism operation with
a SaaS attached, not the reverse. Dominant channels in order of
compounding value:

1.  **SEO on analyst names**: durable, intent-perfect, structurally
    uncontested (nobody else has the data to rank for "X track record").

2.  **Creator-embedded badges**: the scored advertise the scoreboard;
    classic two-sided flywheel where status display does the marketing
    (the ELO/Michelin dynamic).

3.  **The Receipts bot + leaderboard-drop events on X**: predictions
    resolve daily, so the content calendar writes itself; controversy is
    a channel, and the leaderboard mechanic (rank changes, streaks,
    falsifiability ratios) is natively screenshot-able.

4.  **Press**: a neutral referee with receipts is endlessly citable; one
    wire-service citation seeds hundreds of backlinks.

5.  **B2B2C embeds**: slow to land, dominant once landed (TipRanks built
    a \$200M company substantially on this channel). Virality source,
    precisely: vindication ("I knew he was full of it") and status
    ("ranked \#3"). Both emotions screenshot well. Organic growth
    source: resolution events + name-search SEO. Paid acquisition: do
    not; if this needs paid CAC, the thesis is wrong.

## 13. Team Planning

| **Stage** | **Roles** | **Headcount** | **Cost assumptions (monthly)** | **Outsourcing** |
|----|----|----|----|----|
| **MVP (months 0-3)** | Founding CTO (full-time, non-negotiable); 1 senior full-stack (contract or co-founder); 3 part-time eng students (ingestion scripts, QA labeling, ops tooling); founder doubles as head of content; fractional media-law counsel | 2 FTE + 3 PT | Ankara cost base: students \$500-900 each; senior contract \$3-5k; counsel retainer \$1-3k. Total burn \$8-14k/mo | Labeling, design assets, transcription via API |
| **Seed (post \$1.5-2.5M)** | \+ ML engineer (extraction quality), + data engineer (resolution/warehouse), + growth/content lead (this is a media company; hire accordingly), + quant methodology lead (part-time academic acceptable, credibility hire), + ops/QA lead | 7-8 | Blended \$5-9k/role Ankara-weighted, or \$10-18k US-remote; burn \$60-100k/mo | Legal, design, video editing |
| **Series A (post \$8-15M)** | Eng 8 (platform, pipelines, API), Data/ML 4, Content/Growth 3, BD 2 (broker deals), Compliance counsel in-house 1, Ops 2 | 18-20 | Burn \$250-400k/mo mixed geo | Regional legal, localization |

**The honest line investors will draw immediately:** a founder holding
two jobs plus three part-time students is a fine exploration squad and
an unfundable company. The 90-day MVP can be built by this squad;
everything after the gate requires at least one full-time founder. Price
this into the decision now.

## 14. Financial Model

**MVP build cost (12 weeks, Ankara base):** team \$24-42k; transcription
backfill (50 analysts × 24 months ≈ 9,000 audio hours: ~\$3.5k via API,
~\$600 self-hosted GPU); LLM extraction \$0.5-1.5k; price data free
tiers; hosting/tools \$0.5k; legal setup + counsel \$4-8k. **Total:
roughly \$35-55k all-in, under \$15k if founder labor is unpriced.**

**Steady-state infrastructure (50-analyst roster):** transcription
~\$130/wk ongoing, LLM under \$300/mo, X pay-per-use \$50-150/mo,
hosting + DB \$150/mo, monitoring \$50/mo. **Under \$1.2k/mo.** AI cost
is no longer a primary bottleneck at this scale (an update to the early
study's amber flag); it becomes material only at 10k+ analyst coverage
(Section 18).

**Year-one scenarios (12 months post-MVP):**

| **Scenario** | **Setup** | **Annual burn** | **Exit-rate revenue** | **Outcome** |
|----|----|----|----|----|
| Conservative | Bootstrapped, part-time, Ankara | \$100-140k | \$0-25k (ads, affiliate, a few badges) | Dataset + audience asset; no fundability; likely slow death by attention |
| Realistic | \$300-500k pre-seed, founder full-time, 3-4 heads | \$300-420k | \$60-180k ARR (60-120 badges, newsletter/affiliate, 1 vetting client, 1 pilot) | Seed-ready if MAU and virality co-deliver |
| Aggressive | \$1.5M seed, 7 heads, equities V2 in-year | \$900k-1.2M | \$300-600k ARR (badges at scale + 1-2 broker pilots at \$60-150k + API pilots) | Series A trajectory; execution risk on broker cycles |

Unit economics worth stating: gross margin is software-like (85%+) since
COGS is pennies of inference per analyst per week; the real costs are
people and legal.

## 15. Investment Attractiveness

**Would YC invest?** The idea pattern-matches to current YC taste: LLMs
converting unstructured public data into a proprietary structured asset,
consumer virality built in, a clear B2B follow-on. They funded the
adjacent category (copy-trading, finfluencer tooling). What kills the
application as it stands: founder commitment (two jobs), no full-time
technical co-founder on paper, and a fuzzy first-revenue wedge. With a
full-time founder, a live leaderboard, and one viral moment, it is a
credible YC application. Without commitment, it is an automatic no
regardless of idea quality.

**Would top-tier VCs invest?** Not pre-traction; the category scars
(media-like consumer revenue, legal surface) demand proof. They engage
at roughly: \$1M ARR run-rate or two signed broker pilots, 200k+ MAU
with organic concentration, and the TipRanks comp narrative (acquired at
\$200M on \$20-30M revenue: a believable 7-10x revenue outcome) plus
Dub/Autopilot as category-heat evidence.

**Metrics that convince, in order:** extraction precision ≥95% / recall
≥80% on an audited golden set (the product works); 20k+ resolved claims
(the dataset exists); monthly leaderboard-drop traffic with screenshot
virality (distribution works); badge attach rate among the top-50 ranked
creators (the flywheel works); one paying B2B logo (the money works).

**Concerns investors will raise, pre-answered:** platform dependence
(answer: multi-source roadmap, derived-data architecture); lawsuit
magnetism (answer: Section 10 architecture, insurance, counsel on
retainer); "TipRanks does this" (answer: they cannot parse creators, and
their acquirer is our most natural exit); "scores converge to 'nobody is
skilled'" (answer: that finding is itself the viral product, and the 28%
who are skilled per the academic record are the badge market).

## 16. Final Verdict

| **Milestone** | **Probability, funded + full-time** | **Probability, current part-time setup** |
|----|----|----|
| \$1M ARR within 3 years | 25-30% | 5-8% |
| \$10M ARR within 5 years | 7-10% | under 3% |
| \$100M ARR | 2-3% | ~0% |

**Biggest opportunity.** Becoming the neutral rating agency for public
prediction: the FICO/Nielsen position in an information market that
academically, demonstrably misprices trust, monetized through creator
credentials and broker distribution, with cross-domain expansion as the
venture-scale kicker.

**Biggest risk.** A three-way braid: monetization gravity (consumer
accountability is media, not SaaS), regulatory/defamation drag that
taxes exactly the content that drives growth, and the team-commitment
gap, which is currently the binding constraint and the only one of the
three that is fully in your control.

**Pivot options, ranked by adjacency:** (1) finfluencer
vetting/compliance B2B for brands and exchanges (same pipeline, boring,
paid, near-zero legal surface); (2) skill-weighted social sentiment feed
for funds (same dataset, different buyer, slower); (3) white-label
scoring engine for copy-trading and betting platforms (sell the referee
tech to Dub-likes); (4) regulated copy-trading itself (abandons
neutrality, needs licenses and capital: effectively a different company,
listed only for completeness).

**Recommendation: BUILD, modified. Conviction 7/10 at venture scale;
8/10 as a bootstrapped media-plus-data business.** Modifications to the
early study's thesis: (a) downgrade the consumer-subscription pillar to
a distribution layer and promote badges plus B2B2C to primary revenue;
(b) treat the archive-data moat as partially replicable and invest in
referee-brand plus ephemeral capture instead; (c) add the commitment
precondition explicitly. The crypto-first, YouTube-first, analytics-only
scoping is correct and survives scrutiny. **The 90-day gate (decide, do
not drift):** ship the launch report and hit at least three of: 25k
unique visitors in launch month, 1,500 newsletter subscribers, 50
creators on the badge waitlist, one press citation, one B2B inbound.
Pass: someone goes full-time and a pre-seed is raised. Fail: park the
dataset (keep the recorder running; ephemeral capture compounds even
while parked) and redirect the squad to the customs-classification
wedge, which fits a part-time team's risk profile far better.

## 17. PRD

Delivered as a separate, import-ready file:
**prediction-track-record-engine_PRD.md** (Markdown headings and tables
import cleanly into Notion, Linear, Jira, and ClickUp).

## 18. System Architecture (Production-Grade Design)

### 18.1 High-level diagram (textual)

┌────────────────────────────────────────────┐

│ ANALYST REGISTRY (PG) │

└──────┬─────────────────────────────────────┘

┌──────────────────────┼──────────────────────┬──────────────────────┐

YouTube Poller X Poller (PPU API) Podcast RSS Poller Newsletter Inbox

(Data API + yt-dlp) │ │ (IMAP parser)

│ │ │ │

└────────────► MEDIA ACQUISITION ──► Object Storage (R2/S3: audio\*,
transcripts)

│ \*audio transient, 30-day TTL

TRANSCRIPTION + DIARIZATION

(faster-whisper GPU / Deepgram)

│

PREDICTION EXTRACTION SERVICE

pass 1: claim-span detection (Haiku-class)

pass 2: structuring + confidence (Haiku-class)

arbitration on disagreement (Sonnet-class)

│

┌──────────────┴──────────────┐

auto-accept (high conf) HUMAN QA QUEUE (Label Studio)

└──────────────┬──────────────┘

CLAIMS STORE (PG + pgvector dedup)

│

PRICE WAREHOUSE (CCXT/CoinGecko → PG/TimescaleDB)

│

RESOLUTION ENGINE (scheduled jobs)

│

ACCURACY SCORE ENGINE (versioned methodology)

│

┌─────────┬───────┴────────┬───────────────┬─────────────┐

RANKING ENGINE FEED/RECEIPTS SEARCH (PG FTS) NOTIFICATIONS PUBLIC API

│ BOT SERVICE │ (email/push) (read-only)

└───────────────► WEB APP (Next.js) + Receipts pages (embedded YT
player)

### 18.2 Component responsibilities

- **Data Collection Service:** per-source pollers writing immutable
  ingestion events; idempotent, replayable.

- **YouTube Ingestion:** metadata via Data API quota; captions when
  present; yt-dlp audio fallback; new-upload latency target under 2
  hours.

- **X Ingestion:** roster-scoped reads on pay-per-use pricing
  (\$0.005/read; ~\$50-150/mo for 50 accounts); hard monthly budget
  guard well below the 2M-read cap.

- **Podcast Ingestion:** RSS diff polling; diarization to attribute host
  vs guest (MVP scores channel owners only).

- **Newsletter Ingestion:** dedicated subscription inboxes;
  HTML-to-text; cleanest source legally.

- **Prediction Extraction Service:** two-pass LLM with structured-output
  schemas; every extraction stores model version, prompt version, and
  confidence; sub-threshold items route to QA.

- **Verification (Resolution) Engine:** cron-driven joins of open claims
  against the price warehouse; resolution rules as versioned code with
  golden tests.

- **Accuracy Score Engine:** implements Section 9; full-history
  recompute on methodology version bump; append-only score ledger.

- **Ranking / Feed / Search / Notification:** thin reads over
  materialized views; Redis cache for leaderboards.

### 18.3 Database choices and why

- **OLTP: Postgres** (Supabase or RDS). Claims, analysts, resolutions,
  users: relational integrity, row-level audit, one engine to operate.
  Boring on purpose.

- **Analytics: DuckDB on Parquet exports at MVP → ClickHouse at 10k+
  analysts.** Columnar wins only at scale; do not pay its operational
  tax early.

- **Vector: pgvector** inside Postgres for claim dedup and semantic
  search; **Qdrant** only if recall/latency demands outgrow it.

- **Object storage: Cloudflare R2** (zero egress) for transcripts and
  transient audio; S3 acceptable.

- **Time-series prices: Postgres/TimescaleDB.** Daily closes for a few
  hundred assets is small data; resist exotic stores.

### 18.4 Infrastructure

Cloud: start on managed PaaS (Vercel front, Fly.io/Railway workers,
Supabase PG), AWS later only if B2B compliance demands. Containers:
Docker everywhere from day one. Orchestration: none beyond a job queue
at MVP; ECS or lightweight K8s post-Series-A. CI/CD: GitHub Actions with
the extraction golden-set eval as a merge gate (a prompt change that
drops precision fails CI: this is the most important test in the
company). Monitoring: Sentry + Grafana Cloud; pipeline freshness alerts
(any analyst stale \> 48h pages someone). Logging: structured JSON to
Axiom/Loki.

### 18.5 Scalability and cost model

| **Scale** | **Volume** | **Architecture posture** | **Est. infra cost** |
|----|----|----|----|
| 1,000 analysts | ~12k videos/mo, ~7k audio hrs/mo | API transcription still viable; single PG; queue workers x3 | \$2.5-5k/mo (transcription-dominated) |
| 10,000 analysts | ~70k audio hrs/mo | Switch to self-hosted faster-whisper on spot GPUs (~10x cheaper than APIs); ClickHouse for analytics; sharded workers | \$12-25k/mo |
| 100,000 "analysts" | ~700k audio hrs/mo | Batch GPU fleet, Kafka-grade event bus, enterprise price-data contracts (Kaiko/Polygon), multi-region | \$80-150k/mo |

Honesty note: 100k finance analysts worth scoring do not exist; that
tier is reached only via cross-domain expansion (sports, politics),
which is exactly when the white-label engine (#12) should be paying for
it.

## 19. Engineering Execution Plan

**Phase 1 (weeks 1-4): Ingestion + Extraction Foundation.** Tasks:
analyst registry + roster curation (50 channels); YouTube poller +
backfill crawler; transcription pipeline; object storage + schemas;
extraction prompts v1 with structured outputs; **golden set: 200
hand-labeled claims from 40 videos** (the most valuable artifact of the
quarter); eval harness; price warehouse for top-100 crypto assets.
Skills: Python data eng, prompt/eval engineering. Dependencies: none
external. Effort: ~6 engineer-weeks.

**Phase 2 (weeks 5-8): Resolution + Scoring + QA.** Tasks: resolution
engine with rule library + golden tests; Section 9 scoring engine with
versioning; Label Studio QA loop + reviewer playbook (students staff
this); full 24-month backfill run + spot audit (sample 300 claims,
measure precision); contradiction/dedup pass; methodology document
drafted for publication. Skills: backend, light statistics.
Dependencies: Phase 1 golden set. Effort: ~7 engineer-weeks.

**Phase 3 (weeks 9-12): Public Surface + Launch.** Tasks: Next.js site
(leaderboard, analyst pages with embedded-player receipts, methodology
page); SEO architecture for name queries; weekly newsletter pipeline;
dispute form + internal triage; Receipts bot v0; launch report
production (founder-led); legal review pass on copy and claims display.
Skills: full-stack, content. Effort: ~6 engineer-weeks.

**Timeline by team shape:** 1 founder alone: 5-6 months (content
production is the bottleneck, not code). 2 engineers: ~3 months (the
canonical plan above). 5 engineers: 2-2.5 months, not faster
(coordination overhead plus a single-threaded dependency: golden set →
extraction quality → everything). **Current actual squad (1 senior + 3
part-time students) ≈ the 2-engineer track stretched to ~14-16 weeks**,
viable if the senior is genuinely full-time.

## 20. Founder Mode Recommendation

**With \$25k.** Build: 30-50 crypto YouTubers, yt-dlp + faster-whisper
on one rented GPU (or Deepgram credits), Haiku-class extraction,
Postgres, a fast static-ish Next.js site, Google-Sheets-grade QA run by
the students, the launch report, the newsletter, and the X receipts bot.
Deliberately NOT build: user accounts, X ingestion beyond a token roster
read, equities, API, mobile, consensus features, any auto-anything.
Shortcuts accepted: single price source, hardcoded horizon defaults,
cron instead of orchestration, prompts-plus-human-catch instead of
fine-tuning. Technical debt accepted knowingly: schema migrations later,
no multi-tenancy, manual dispute handling. **First milestone before any
fundraising conversation: the launch report makes contact with reality:
25k unique visitors, 1,000+ newsletter subs, 50-creator badge waitlist,
one press pickup.** Everything else is decoration.

**With \$100k.** Add one contract engineer for six months and paid
labelers; expand to 150 analysts; turn on roster-scoped X ingestion;
ship the dispute workflow and badge program v1 at \$49-99/mo; commission
a short methodology review by a finance academic (cheap,
disproportionate credibility). Still not building: equities, API,
mobile. Milestone: **\$5k MRR or one signed B2B letter of intent, plus
50k monthly visitors.**

**With \$500k.** Three to four FTEs for 12-14 months; equities vertical
with benchmark-relative scoring; public API beta; two broker/exchange
pilot conversations started in month 1 (the cycle is long, so the clock
starts immediately); media-law retainer and E&O insurance; methodology
advisory board named on the site. Milestone for the seed/A raise:
**\$25-40k MRR or two paid pilots, 150k+ MAU, and 30k+ resolved claims**
with audited extraction precision ≥95%.

Across all three budgets the same rule holds: the recorder runs from day
one (ephemeral capture is the only moat money cannot backfill), the
methodology is public from day one, and nothing the product ships ever
tells a user what to buy.

*End of analysis. Companion PRD in
prediction-track-record-engine_PRD.md.*
