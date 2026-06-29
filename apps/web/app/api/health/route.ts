/**
 * GET /api/health — liveness + database-readiness probe (production monitoring).
 *
 * Returns 200 { status: "ok" } when a trivial `select 1` round-trips through the
 * read layer (lib/db.ts), or 503 { status: "error" } when the database is
 * unreachable. Wired to an uptime monitor (BRIER_BETTER_STACK_TOKEN). This route
 * executes at request time only — `export const dynamic = "force-dynamic"` keeps
 * it out of the static build so the probe always reflects live DB state.
 */

import { NextResponse } from "next/server";

import { pingDb } from "@/lib/db";

export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  try {
    await pingDb();
    return NextResponse.json({ status: "ok" }, { status: 200 });
  } catch (err) {
    // Log the cause so a 503 is self-diagnosing from `journalctl -u brier-web`.
    console.error("health: db ping failed", err);
    return NextResponse.json({ status: "error" }, { status: 503 });
  }
}
