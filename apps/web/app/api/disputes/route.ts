/**
 * POST /api/disputes — dispute submission endpoint (E5-T3, FR-405, US-006, AC-5).
 *
 * Parses and validates the JSON body, delegates to PostgresDisputeIntake,
 * and returns the ticket reference with the 7-day SLA deadline.
 *
 * This route handler is the ONLY place in apps/web that writes to the disputes
 * table. It runs at request time — never at build/CI — so the DB write is not
 * executed during static analysis or the build step (mock-first holds).
 *
 * Copy is strictly neutral throughout (AC-7 firewall).
 */


import { NextResponse } from "next/server";

import { ClaimNotFoundError, getNotifier, PostgresDisputeIntake } from "@/lib/dispute-intake";

/** Maximum rationale length accepted (characters). Reasonable cap; not a DB constraint. */
const MAX_RATIONALE_LEN = 4000;

/** Maximum submittedBy length accepted (characters). Matches typical email address limits. */
const MAX_SUBMITTED_BY_LEN = 254;

export async function POST(request: Request): Promise<NextResponse> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Request body must be valid JSON." },
      { status: 400 },
    );
  }

  // Validate shape.
  if (typeof body !== "object" || body === null) {
    return NextResponse.json({ error: "Invalid request body." }, { status: 400 });
  }

  const raw = body as Record<string, unknown>;

  const claimId = raw["claimId"];
  const rationale = raw["rationale"];
  const submittedBy = raw["submittedBy"];

  if (typeof claimId !== "number" || !Number.isInteger(claimId) || claimId <= 0) {
    return NextResponse.json(
      { error: "claimId must be a positive integer." },
      { status: 400 },
    );
  }

  if (typeof rationale !== "string" || rationale.trim().length === 0) {
    return NextResponse.json(
      { error: "rationale is required and must be a non-empty string." },
      { status: 400 },
    );
  }

  if (rationale.length > MAX_RATIONALE_LEN) {
    return NextResponse.json(
      { error: `rationale must be ${MAX_RATIONALE_LEN} characters or fewer.` },
      { status: 400 },
    );
  }

  if (submittedBy !== undefined && typeof submittedBy !== "string") {
    return NextResponse.json(
      { error: "submittedBy must be a string when provided." },
      { status: 400 },
    );
  }

  if (typeof submittedBy === "string" && submittedBy.length > MAX_SUBMITTED_BY_LEN) {
    return NextResponse.json(
      { error: `submittedBy must be ${MAX_SUBMITTED_BY_LEN} characters or fewer.` },
      { status: 400 },
    );
  }

  // Delegate to the intake seam. getNotifier() returns ResendNotifier in
  // production (BRIER_RESEND_API_KEY set + ADR-0010) and FakeNotifier in
  // CI/dev, so the ticket-id confirmation email actually sends in prod
  // (US-006/UF-3) without any network call in CI.
  const intake = new PostgresDisputeIntake({ notifier: getNotifier() });

  try {
    const result = await intake.submit({
      claimId,
      rationale: rationale.trim(),
      submittedBy: typeof submittedBy === "string" ? submittedBy.trim() || undefined : undefined,
    });

    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    if (err instanceof ClaimNotFoundError) {
      return NextResponse.json({ error: err.message }, { status: 400 });
    }
    // Generic server error — do not leak internal details.
    console.error("dispute intake error:", err);
    return NextResponse.json(
      { error: "Unable to process the dispute. Please try again later." },
      { status: 500 },
    );
  }
}
