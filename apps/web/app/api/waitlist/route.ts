/**
 * POST /api/waitlist — badge waitlist subscription (E5-T6, US-008, FR-408).
 *
 * Accepts { email, analystSlug } and initiates double opt-in via the Subscriber
 * seam with kind="waitlist". Returns { status: "pending" } on success.
 *
 * This route handler executes at request time only, never at build or CI, so
 * the mock-first seam invariant holds: getSubscriber() returns FakeSubscriber
 * when BRIER_BUTTONDOWN_API_KEY is absent (ADR-0013).
 */

import { type NextRequest, NextResponse } from "next/server";

import { getSubscriber, validateEmail } from "@/lib/subscriber";

export async function POST(req: NextRequest): Promise<NextResponse> {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  if (typeof body !== "object" || body === null) {
    return NextResponse.json({ error: "Request body must be a JSON object." }, { status: 400 });
  }

  const { email, analystSlug } = body as Record<string, unknown>;

  if (typeof email !== "string" || !validateEmail(email)) {
    return NextResponse.json({ error: "A valid email address is required." }, { status: 400 });
  }

  if (typeof analystSlug !== "string" || analystSlug.trim().length === 0) {
    return NextResponse.json({ error: "analystSlug is required." }, { status: 400 });
  }

  try {
    const subscriber = getSubscriber();
    const result = await subscriber.subscribe({
      email,
      kind: "waitlist",
      analystSlug: analystSlug.trim(),
    });
    return NextResponse.json(
      {
        status: result.status,
        message: "Check your inbox to confirm your place on the waitlist (double opt-in).",
      },
      { status: 200 },
    );
  } catch (err) {
    const message = err instanceof Error ? err.message : "Waitlist submission could not be processed.";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
