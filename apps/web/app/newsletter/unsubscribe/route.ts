/**
 * GET /newsletter/unsubscribe — one-click unsubscribe (E5-T6, FR-406).
 *
 * A single GET from the email link (no further interaction required) reads the
 * ?email= query parameter and calls subscriber.unsubscribe(). Returns a neutral
 * HTML confirmation page.
 *
 * One-click unsubscribe: the user is unsubscribed on the first GET; no
 * confirmation step is needed. This matches RFC 8058 (List-Unsubscribe-Post)
 * semantics and satisfies FR-406.
 *
 * This route handler executes at request time only, never at build or CI, so
 * the mock-first seam invariant holds (ADR-0013).
 */

import { type NextRequest, NextResponse } from "next/server";

import { getSubscriber, validateEmail } from "@/lib/subscriber";

// Token-less limitation (MVP, accepted): any caller who knows the address can
// trigger unsubscribe via this route — see ADR-0013 Consequences for the
// accepted-risk rationale. Buttondown's own email links carry per-subscriber
// tokens, so the primary unsubscribe flow is token-protected at the provider.
export async function GET(req: NextRequest): Promise<NextResponse> {
  const { searchParams } = req.nextUrl;
  const email = searchParams.get("email") ?? "";

  if (!validateEmail(email)) {
    return new NextResponse(unsubscribePage("invalid-email"), {
      status: 400,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  }

  try {
    const subscriber = getSubscriber();
    await subscriber.unsubscribe({ email });
    return new NextResponse(unsubscribePage("success", email), {
      status: 200,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  } catch {
    return new NextResponse(unsubscribePage("error"), {
      status: 500,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  }
}

/** Minimal neutral HTML confirmation page. No hype, no emoji (BRANDKIT §7). */
function unsubscribePage(
  state: "success" | "invalid-email" | "error",
  email?: string,
): string {
  const message =
    state === "success"
      ? `The address ${email ? `<strong>${escapeHtml(email)}</strong> has` : "you provided has"} been unsubscribed. No further messages will be sent.`
      : state === "invalid-email"
        ? "The unsubscribe link did not contain a valid email address. If you received this link from a Brier email, please contact us directly."
        : "The unsubscribe request could not be completed. Please try again or contact us directly.";

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Unsubscribe — Brier</title>
<style>
  body{font-family:system-ui,sans-serif;background:#F4F2EC;color:#16191D;margin:0;padding:2rem 1rem;}
  .card{background:#FCFBF8;border:1px solid rgba(21,25,29,0.2);border-radius:6px;max-width:480px;margin:4rem auto;padding:2rem;}
  h1{font-size:1.25rem;font-weight:600;margin:0 0 1rem;}
  p{margin:0;line-height:1.6;font-size:0.9375rem;}
  a{color:#2D54CE;}
</style>
</head>
<body>
<div class="card">
  <h1>Brier — Unsubscribe</h1>
  <p>${message}</p>
  <p style="margin-top:1rem;font-size:0.8125rem;color:#565C64;">
    <a href="/">Return to Brier</a>
  </p>
</div>
</body>
</html>`;
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;"); // future-proof: single-quote escape for attribute contexts
}
