# Brier Brand Reference

**Canonical source:** extracted from `brandkit/` (`assets/brier.css`, `visual-identity.html`, `design-system.html`, `brand-strategy.html`). This document is the binding brand reference for all product UI. Where any other token list (including older scaffold notes) conflicts with this document, **this document wins**.

Brand essence: **proof, not opinion.** Rating-agency aesthetic: clinical, typographic, data-forward. The legal posture depends on the site never looking like a callout account.

---

## 1. Color

Color is information, not decoration. Saturation is reserved almost entirely for the FAS scale, where it signals an earned result.

### Neutral paper/ink ramp (warm-cool, low chroma)

| Token | Hex | Role |
|---|---|---|
| `--paper` | `#F4F2EC` | Background, the page (editorial off-white, warm) |
| `--paper-2` | `#ECE9E1` | Recessed panel |
| `--surface` | `#FCFBF8` | Card white |
| `--surface-2` | `#F8F6F1` | Subtle surface |
| `--ink` | `#16191D` | Headlines, primary text (near-black, cool) |
| `--ink-2` | `#2C3036` | Strong body |
| `--ink-3` | `#565C64` | Secondary text |
| `--ink-4` | `#8A8F96` | Tertiary / captions |
| `--line` | `#15191D1A` | Hairline (ink @ ~10%) |
| `--line-2` | `#15191D33` | Stronger hairline |
| `--line-strong` | `#15191D` | Full ink rule |

Full grayscale ramp: `#FCFBF8 · #F4F2EC · #ECE9E1 · #C9CBC8 · #8A8F96 · #565C64 · #2C3036 · #16191D`. These carry 90% of every surface; the discipline of the grayscale is what lets the FAS color land.

### Brand

| Token | Hex | Role |
|---|---|---|
| `--navy` | `#16233A` | Ink Navy — institutional primary, masthead, sidebar |
| `--navy-2` | `#22324F` | Lifted navy panel |
| `--brier-blue` | `#2D54CE` | Brier Blue — verification, links, focus, the mark's dot. The single accent: it always means "verified / interactive" |
| `--brier-blue-d` | `#21409E` | Hover/darkened blue |
| `--brier-blue-t` | `#2D54CE14` | Blue tint (focus halo) |

### FAS scale (the only multi-hue ramp in the system)

Equal-chroma steps from a neutral "no-signal" ochre up to a confident teal-green. Low scores use a **restrained clay, never a fire-red** — Brier reports, it does not condemn.

| Band | Range | Token | Hex |
|---|---|---|---|
| Elite | 75–100 | `--fas-elite` | `#0E7C66` |
| Skilled | 60–74 | `--fas-skilled` | `#3E7A78` |
| Coin-flip | 40–59 | `--fas-flip` | `#A8995F` |
| Anti-skilled | 0–39 | `--fas-anti` | `#B06043` |
| Provisional tag | n-based, see METHODOLOGY.md §6 | rendered as a neutral label, not a band color | — |

**Band colors appear ONLY on FAS badges and chart annotations — never as decoration.**

### Semantic and status

| Token | Hex |
|---|---|
| `--success` | `#0E7C66` |
| `--warning` | `#BC8A2C` |
| `--error` | `#B23A2E` |

Claim-status chips (muted and bordered, never filled-loud — a ledger annotation, not an alarm):

| Status | Token | Hex |
|---|---|---|
| Hit | `--hit` | `#0E7C66` |
| Miss | `--miss` | `#B23A2E` |
| Partial (0.5 credit) | `--partial` | `#BC8A2C` |
| Open | `--open` | `#4A6CC7` |
| Void | `--void` | `#8A8F96` |

## 2. Typography

Three voices: authority, surface, data.

| Token | Stack | Weights | Role |
|---|---|---|---|
| `--serif` | "Source Serif 4", Georgia, serif | 600/700 | Display, wordmark, editorial headlines — the institution voice |
| `--sans` | "IBM Plex Sans", system-ui, sans-serif | 400/500/600 | All product UI, body, labels, navigation |
| `--mono` | "IBM Plex Mono", ui-monospace, monospace | 400/500 | Every score, ticker, timestamp, offset, n-count, methodology version |

**Pairing rule:** serif sets the institution; sans runs the product; mono carries every datum. Never set body copy in the serif; never set a score in anything but the mono. `font-variant-numeric: tabular-nums` on everything numeric.

Type scale: Display 52 (serif 600), H2 36 (serif 600), H3 20 (sans 600), Body 16 (sans), Label 11 (mono, uppercase, letter-spacing .13em).

## 3. Geometry and surfaces

- Radius: `--radius: 3px` (tight, instrument-grade); `--radius-lg: 6px`.
- Hairlines, not boxes: structure with thin rules and whitespace like a financial broadsheet. Heavy containers and drop-shadows are rare; shadow only on overlays, never on resting cards.
- Content max width 940px; data-dense tables with generous surrounding whitespace.
- Tables: mono uppercase micro-cap headers, 44px comfortable-dense rows, tabular numerals, right-aligned numerics, sticky header. Below 640px, rows collapse to stacked cards. Full keyboard navigation (WCAG AA).
- Buttons: navy = primary action, Brier Blue = verify/interactive, ghost = secondary. 3px radius, ~130ms transitions, no gradient fills. One primary action per view. Destructive (void) actions use the error color and require confirmation.
- Focus rings: 3px Brier-Blue halo; the same blue means "interactive" everywhere.

## 4. Logo

The Register Mark: a registration-target crosshair inside a scorecard frame — one prediction, resolved and placed on the record. The dot is the only point of color (Brier Blue). Wordmark "Brier" in Source Serif 4 SemiBold; always capital "B", never all-caps, never italic. Never reproduce below 20px digital. Don't: gradients, neon, rotation, glows, busy photos, emoji-grade decoration.

## 5. Charts

- Built on TradingView Lightweight Charts.
- One ink line per series; the dataset is the hero, not the chrome.
- Three canonical markers: **utterance** (Brier Blue dot), **target** (dashed ochre `#BC8A2C` line), **resolution** (band-colored dot).
- No 3-D, no area-fill gradients, no dual axes. Tabular tooltips with sourced values.

## 6. Motion

- Instrument, not toy: 120–200ms, ease-out, small distances. Motion confirms state; it never performs.
- Numbers count up to a settled value — never bounce.
- Respect `prefers-reduced-motion`; end-states are always the base style.
- Quiet check on confirmations, never confetti.

## 7. Voice

Register: wire service meets ratings methodology. Behaves like a courtroom expert witness — precise, unhurried, impossible to rattle.

Rules:

1. Declarative and plain. Short sentences. Tabular numbers.
2. **Cite, don't characterize:** "HIT on 14 Jul at $80,140," not "nailed it."
3. Never advise, hype, or imply action. No recommendation language, ever (enforced by `scripts/copy_lint.py`).
4. Name the method and the version when stating a score.
5. Concede uncertainty openly — "provisional," "n below threshold," "disputed."
6. Institutional "we"; the analyst is named, never insulted. No exclamation marks, no emoji, no hype vocabulary anywhere in product copy.

Vocabulary: "score", "resolved", "receipt", "provisional", "corrections log".

| We say | We never say |
|---|---|
| "FAS 71 · n=84 resolved · falsifiability 0.62." | "This guy is a genius / a fraud." |
| "Resolved HIT against the daily UTC close." | "Called it perfectly — don't miss the next one." |
| "Below skill threshold once corrected for base rate." | "Another clueless shill exposed." |
| "Disputed; under review, adjudication within 7 days." | "We stand by it, end of story." |
| "We publish statistics about public statements." | "Here's who to follow / what to act on." |

Empty states state the rule honestly, never apologize, and never fabricate a number to fill space.

## 8. Design principles

- **P-01 Evidence on the surface.** Never make a claim the interface can't immediately back. A score is always one click from its receipt.
- **P-02 Boring on purpose.** Restraint is the strategy. No drama, no meme styling.
- **P-03 Data is the ornament.** Tables, sparklines, and tabular numbers are the decoration.
- **P-04 Hairlines, not boxes.**
