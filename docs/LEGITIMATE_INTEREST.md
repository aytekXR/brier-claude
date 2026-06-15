# Legitimate Interest and Data Retention

**Version 1.0 · Effective date: 2026-06-16**

This document describes the legal basis on which Brier processes and retains personal data, the balancing test applied to erasure requests, and the process for submitting a request. It is the artifact required by NFR-6 of the Product Requirements Document.

---

## Purpose

Brier is a prediction track-record engine. It collects, structures, and publishes accuracy statistics derived from public statements made by public figures on publicly accessible platforms. The product exists to provide the public with verifiable, source-linked records of those statements and their factual outcomes.

This document addresses data subjects and regulators under the General Data Protection Regulation (GDPR) and the Kişisel Verilerin Korunması Kanunu (KVKK).

---

## Legitimate Interest

Brier's legal basis for processing data that relates to public figures and their public statements is **legitimate interest** (GDPR Art. 6(1)(f); KVKK Art. 5(2)(f)).

The legitimate interest is:

1. **Accuracy of the public record.** The public has a legitimate interest in knowing whether claims made in public—particularly claims that may influence financial decisions—are accurate. Brier quantifies and verifies those claims using a documented methodology.
2. **Accountability for public statements.** Public figures who publish predictions on public platforms accept that those statements may be subject to public scrutiny and factual verification.
3. **Transparency about prediction quality.** Brier's scores enable audiences to assess the historical accuracy of an analyst before placing weight on that analyst's current statements.

Brier processes only:
- Publicly available statements (transcribed from public YouTube videos).
- Publicly available price data (used to resolve predictions factually).
- Structural metadata about public channels (channel identifier, display name, publication date).

Brier does not process: private communications, financial account data, government identifiers, health data, or sensitive categories under GDPR Art. 9.

---

## The Balancing Test

Before relying on legitimate interest, Brier applies a three-part balancing test.

### 1. Purpose

The purpose of processing is to produce and publish an accurate statistical record of public predictions. The purpose is specific, documented in the methodology, and does not extend to profiling for advertising, credit scoring, or any other commercial purpose beyond the track-record product itself.

### 2. Necessity

Processing is limited to what is necessary for the documented purpose:
- Only statements that constitute a verifiable prediction are extracted and structured.
- Audio files are retained for no more than 30 days (technical transient; NFR-4).
- Transcripts are retained as the durable source of record, replacing the audio.
- No contact data, private messages, or off-platform data is collected.

### 3. Proportionality and Data Subject Rights

The impact on data subjects is assessed as follows:

| Factor | Assessment |
|--------|------------|
| Nature of the data | Public statements made in a public forum by a public figure in a professional capacity |
| Reasonable expectation | Public figures publishing predictions on YouTube have a reasonable expectation that those predictions may be subject to public scrutiny |
| Impact on the data subject | The record documents factual accuracy of public claims; it does not expose private life, health, location, or identity beyond the public persona |
| Safeguards | Scores are methodology-versioned and publicly auditable; corrections are documented and published; disputes are adjudicated within 7 days; erasure requests are reviewed within 30 days |

**Conclusion of the balancing test:** Brier's legitimate interest in maintaining an accurate public record of verifiable public predictions is not overridden by the fundamental rights and freedoms of the data subject in the standard case. The data subject is a public figure; the data is a public statement; the purpose is factual verification, not harm.

---

## What Is Retained vs Erasable

| Data type | Basis | Retained or erasable |
|-----------|-------|----------------------|
| Published prediction (claim, asset, direction, target, deadline) | Legitimate interest — public statement, public figure | **Retained** |
| Resolution (factual outcome, price citation, date) | Legitimate interest — verifiable public fact | **Retained** |
| Accuracy score | Legitimate interest — derived statistic from retained data | **Retained** |
| Display name and channel identifier | Legitimate interest — publicly known identity of the public figure | **Retained** |
| Verbatim quote (up to 15 words, source offset) | Legitimate interest — receipt linking score to source | **Retained** |
| Audio file (transient, ≤30 days) | Technical processing necessity only | **Erasable** (auto-deleted at 30 days; may be expedited on request) |
| Contact data submitted in a dispute or erasure request | Contractual necessity / legal obligation | **Erasable** after the relevant retention period |
| Newsletter subscriber data | Consent (separate basis) | **Erasable** on request or on unsubscribe |

### Correction vs erasure

If a published statistic contains a factual error, the correct remedy is a **correction**, not an erasure. Corrections are documented in the public corrections log (/corrections) with the superseded and superseding records published side by side. The append-only ledger (NFR-3) ensures that the history of corrections is itself an auditable public record.

---

## Erasure Requests and the 30-Day Process

Data subjects may submit an erasure request at any time. All requests are processed as follows:

1. **Receipt (day 0):** The request is logged with a unique identifier and a 30-day response deadline. An acknowledgement is sent to the contact address provided.
2. **Review (days 1–28):** A reviewer applies the balancing test documented above. Requests that touch published claims require documented manual review before any action.
3. **Decision (by day 30):** One of three outcomes is recorded:
   - **Retain under legitimate interest:** The data falls within the scope of the published-statistics record. No erasure is performed. The requester is notified of the decision and the basis for it, and informed of their right to complain to the relevant supervisory authority.
   - **Erase:** The data is outside the legitimate-interest scope and will be erased. Completion is confirmed to the requester.
   - **Partial:** Part of the data is retained under legitimate interest; ancillary personal data outside that scope is erased. Both parts are documented in the decision record.
4. **Overdue notices:** Requests that exceed the 30-day deadline without a decision trigger an internal alert. No request is silently abandoned.

**Important:** Erasure of a published claim, resolution, or score row is a documented exception that requires explicit manual review and approval. It is never performed automatically or silently. NFR-3 (append-only ledger discipline) applies: corrections supersede prior records rather than deleting them.

---

## Contact

To submit an erasure request, a correction request, or a general data inquiry, use the dispute form linked from the relevant receipt page (/r/[claim-id]), or contact us directly at the address published on the site.

Supervisory authority contacts:
- **EU/EEA:** The data protection authority in your country of residence.
- **Turkey (KVKK):** Kişisel Verileri Koruma Kurumu (kvkk.gov.tr).

---

*This document is reviewed when the product's data practices change materially. The version and effective date at the top of this page identify the current revision.*
