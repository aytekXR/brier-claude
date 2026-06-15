/**
 * Dispute intake seam for the web layer (E5-T3, FR-405, US-006, AC-5, UF-3).
 *
 * Architecture notes:
 *   - This module handles the WRITE side of dispute intake. It is invoked only
 *     from the /api/disputes route handler at request time; it is never called
 *     at build time or in server components. (mock-first holds: the build/CI
 *     never execute the handler.)
 *   - Reads (getDisputesForClaim, getReceipt) live in lib/db.ts per convention.
 *   - The EMAIL external dependency is behind the Notifier seam defined here.
 *     FakeNotifier is the CI/dev default; ResendNotifier is ADR-0010-gated and
 *     requires BRIER_RESEND_API_KEY. No new npm dependency is used.
 *
 * Column names match 0006_ops.sql exactly:
 *   disputes: ticket_code, claim_id, submitted_by, rationale, state,
 *             sla_deadline, submitted_at, methodology_version_at_publication
 *
 * The `postgres` client (already a project dependency) is used for the INSERT.
 */

// TASK: E5-T3

import crypto from "node:crypto";

import postgres from "postgres";

// ---------------------------------------------------------------------------
// Module-level singleton SQL client (same pattern as lib/db.ts:27).
// A single pool is shared across all requests in the same process.
// ---------------------------------------------------------------------------
const _sql = postgres(
  process.env.BRIER_DATABASE_URL ?? "postgresql://brier:brier@localhost:5432/brier",
  { connect_timeout: 3 },
);

// ---------------------------------------------------------------------------
// Notifier seam (mock-first, ADR-0010-gated for the real path)
// ---------------------------------------------------------------------------

/** Minimal notification seam for dispute ticket confirmations. */
export interface Notifier {
  send(opts: { to: string; subject: string; body: string }): void | Promise<void>;
}

/** Sent-message record for FakeNotifier assertions. */
export type SentMessage = { to: string; subject: string; body: string };

/**
 * In-memory notifier — the CI/dev default (mock-first convention).
 * Records every send() call in .sent so callers can assert on them.
 * Never touches the network.
 */
export class FakeNotifier implements Notifier {
  readonly sent: SentMessage[] = [];

  send(opts: { to: string; subject: string; body: string }): void {
    this.sent.push(opts);
  }
}

/**
 * Resend transactional email via stdlib fetch (ADR-0010).
 * No 'resend' SDK; uses the native fetch available in Node 18+.
 * Raises a clear error when BRIER_RESEND_API_KEY is absent so CI fails
 * loudly rather than silently dropping messages. The FakeNotifier is the
 * CI path; this class is never instantiated without the key.
 */
export class ResendNotifier implements Notifier {
  private static readonly RESEND_URL = "https://api.resend.com/emails";
  private static readonly FROM_ADDRESS = "disputes@brier.app";

  async send(opts: { to: string; subject: string; body: string }): Promise<void> {
    const key = process.env.BRIER_RESEND_API_KEY ?? "";
    if (!key) {
      throw new Error(
        "ResendNotifier requires BRIER_RESEND_API_KEY to be set. " +
          "In CI and tests, use FakeNotifier instead " +
          "(see docs/adr/0010-resend-transactional-email-via-stdlib-rest.md).",
      );
    }
    const payload = {
      from: ResendNotifier.FROM_ADDRESS,
      to: [opts.to],
      subject: opts.subject,
      text: opts.body,
    };
    const resp = await fetch(ResendNotifier.RESEND_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${key}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      throw new Error(`Resend API returned ${resp.status}: ${await resp.text()}`);
    }
  }
}

// ---------------------------------------------------------------------------
// DisputeIntake interface + implementation
// ---------------------------------------------------------------------------

export interface DisputeIntakeInput {
  claimId: number;
  rationale: string;
  submittedBy?: string;
}

export interface DisputeIntakeResult {
  ticketRef: string;
  slaDueAt: string; // ISO-8601 UTC string
  methodologyVersion: string;
}

/** Contract for dispute intake implementations. */
export interface DisputeIntake {
  submit(input: DisputeIntakeInput): Promise<DisputeIntakeResult>;
}

/** Error returned when the claim does not exist or is not publishable. */
export class ClaimNotFoundError extends Error {
  constructor(claimId: number) {
    super(`Claim ${claimId} not found or not publishable.`);
    this.name = "ClaimNotFoundError";
  }
}

/**
 * Generate a dispute ticket code: DSP-<8 lowercase hex chars>.
 * Uses Node's crypto.randomUUID() and slices the hex portion, giving
 * 32 random hex chars from which we take the first 8.
 */
function generateTicketCode(): string {
  const uuid = crypto.randomUUID(); // e.g. "550e8400-e29b-41d4-a716-446655440000"
  const hex = uuid.replace(/-/g, "").slice(0, 8);
  return `DSP-${hex}`;
}

/**
 * Default DisputeIntake implementation backed by Postgres.
 *
 * At request time (never at build/CI):
 *   1. Validates that the claim exists and is publishable.
 *   2. Pins the methodology version from the claim's most-recent non-superseded
 *      resolution (EC-12), falling back to the current live version.
 *   3. Generates a unique ticket_code = "DSP-" + 8 hex chars.
 *   4. Sets sla_deadline = NOW + 7 days (AC-5).
 *   5. INSERTs into disputes (0006_ops.sql column names).
 *   6. Notifies the submitter via the Notifier seam (FakeNotifier by default).
 *
 * The notifier parameter defaults to a FakeNotifier so that no network call
 * is made in CI/dev unless an explicit ResendNotifier is injected.
 */
export class PostgresDisputeIntake implements DisputeIntake {
  private readonly sql: ReturnType<typeof postgres>;
  private readonly notifier: Notifier;

  /**
   * @param opts.sql      — injectable SQL client; defaults to the module-level
   *                        singleton so no new pool is created per request.
   * @param opts.notifier — injectable Notifier; defaults to FakeNotifier in CI/dev.
   */
  constructor(opts?: { notifier?: Notifier; sql?: ReturnType<typeof postgres> }) {
    this.sql = opts?.sql ?? _sql;
    this.notifier = opts?.notifier ?? new FakeNotifier();
  }

  async submit(input: DisputeIntakeInput): Promise<DisputeIntakeResult> {
    const { claimId, rationale, submittedBy } = input;

    // Validate claim exists and is publishable.
    const claimRows = await this.sql<{ id: number }[]>`
      select id from claims where id = ${claimId} and publishable = true limit 1
    `;
    if (claimRows.length === 0) {
      throw new ClaimNotFoundError(claimId);
    }

    // EC-12: pin the methodology version from the claim's current resolution.
    const methodologyVersion = await this.getPinnedMethodologyVersion(claimId);

    // Generate a unique ticket code (collision guard, max 10 attempts).
    const MAX_TICKET_ATTEMPTS = 10;
    let ticketCode = generateTicketCode();
    for (let attempt = 1; ; attempt++) {
      const existing = await this.sql<{ ticket_code: string }[]>`
        select ticket_code from disputes where ticket_code = ${ticketCode} limit 1
      `;
      if (existing.length === 0) break;
      if (attempt >= MAX_TICKET_ATTEMPTS) {
        throw new Error(
          `Unable to generate a unique ticket code after ${MAX_TICKET_ATTEMPTS} attempts.`,
        );
      }
      ticketCode = generateTicketCode();
    }

    // sla_deadline = now + 7 days (AC-5).
    const now = new Date();
    const slaDueAt = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);

    // INSERT the dispute row (0006_ops.sql column names).
    await this.sql`
      insert into disputes (
        ticket_code, claim_id, submitted_by, rationale, state,
        sla_deadline, submitted_at, methodology_version_at_publication
      ) values (
        ${ticketCode},
        ${claimId},
        ${submittedBy ?? null},
        ${rationale},
        'open',
        ${slaDueAt.toISOString()},
        ${now.toISOString()},
        ${methodologyVersion}
      )
    `;

    // Notify the submitter via the seam (FakeNotifier in CI/dev).
    const to = submittedBy ?? "disputes@brier.app";
    const slaStr = slaDueAt.toISOString().replace("T", " ").slice(0, 16) + " UTC";
    await this.notifier.send({
      to,
      subject: `Dispute received: ${ticketCode}`,
      body:
        `Your dispute has been received.\n\n` +
        `Ticket reference: ${ticketCode}\n` +
        `Review target: ${slaStr} (7-day SLA)\n\n` +
        `The reviewer will examine the claim and rationale. ` +
        `You will be notified of the adjudication outcome.`,
    });

    return {
      ticketRef: ticketCode,
      slaDueAt: slaDueAt.toISOString(),
      methodologyVersion,
    };
  }

  /**
   * EC-12: Return the methodology_version from the claim's most recent
   * non-superseded resolution, or the current live version as fallback.
   */
  private async getPinnedMethodologyVersion(claimId: number): Promise<string> {
    const rows = await this.sql<{ methodology_version: string }[]>`
      select methodology_version
      from resolutions
      where claim_id = ${claimId}
        and id not in (
          select supersedes_resolution_id
          from resolutions
          where supersedes_resolution_id is not null
            and claim_id = ${claimId}
        )
      order by id desc
      limit 1
    `;
    if (rows.length > 0 && rows[0]) {
      return rows[0].methodology_version;
    }
    // No resolution yet — fall back to the current live methodology version.
    const versionRows = await this.sql<{ methodology_version: string }[]>`
      select methodology_version
      from score_runs
      where id = (select max(id) from score_runs)
      limit 1
    `;
    return versionRows[0]?.methodology_version ?? "v1.1";
  }
}
