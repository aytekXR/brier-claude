"use client";

/**
 * WaitlistCta — badge waitlist CTA on analyst pages (E5-T6, US-008, FR-408, PRD §19.2).
 *
 * Posts to POST /api/waitlist with the analyst slug. On success shows a neutral
 * double-opt-in confirmation message. On error shows a neutral error message.
 * Accessible: label + focus ring, disabled-while-submitting.
 *
 * Voice (BRANDKIT §7): declarative, no hype, no exclamation marks.
 * Copy complies with AC-7 (no buy/sell/hold/recommendation language).
 */

import { useState } from "react";

type FormState = "idle" | "submitting" | "success" | "error";

/**
 * Minimal client-side email pre-check — mirrors the pattern in lib/subscriber.ts
 * validateEmail. Server-side validation remains the source of truth; this only
 * avoids a wasted round-trip on obviously-invalid input (N-3).
 * Not imported from lib/subscriber.ts to keep this file free of any server-only
 * module references (lib/subscriber.ts also exports ButtondownSubscriber which
 * references process.env and the Buttondown API).
 */
function isLikelyValidEmail(email: string): boolean {
  if (!email || typeof email !== "string") return false;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim()) && email.trim().length <= 254;
}

type Props = {
  analystSlug: string;
};

export function WaitlistCta({ analystSlug }: Props) {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<FormState>("idle");
  const [errorMsg, setErrorMsg] = useState("");

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (state === "submitting") return;

    // Client-side pre-check: short-circuit on empty/obviously-invalid input
    // before making a network round-trip. Server validation remains authoritative.
    if (!isLikelyValidEmail(email)) {
      setErrorMsg("Enter a valid email address.");
      setState("error");
      return;
    }

    setState("submitting");
    setErrorMsg("");

    try {
      const res = await fetch("/api/waitlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, analystSlug }),
      });
      if (res.ok) {
        setState("success");
        setEmail("");
      } else {
        const data = (await res.json().catch(() => ({}))) as { error?: string };
        setErrorMsg(data.error ?? "The request could not be completed.");
        setState("error");
      }
    } catch {
      setErrorMsg("The request could not be completed. Please try again.");
      setState("error");
    }
  }

  return (
    <div className="mt-8 rounded-[6px] border border-line-2 bg-surface px-5 py-4">
      <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
        Badge waitlist
      </p>
      {state === "success" ? (
        <p className="mt-2 font-mono text-[12px] text-ink-3">
          Check your inbox to confirm your place on the waitlist (double opt-in).
        </p>
      ) : (
        <>
          <p className="mt-1 text-[13px] text-ink-3">
            Join the waitlist for the public accuracy badge — displayed on this profile when the
            feature launches.
          </p>
          <form
            onSubmit={handleSubmit}
            noValidate
            className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center"
          >
            <label htmlFor={`waitlist-email-${analystSlug}`} className="sr-only">
              Email address
            </label>
            <input
              id={`waitlist-email-${analystSlug}`}
              type="email"
              name="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={state === "submitting"}
              placeholder="your@email.com"
              className={[
                "h-8 w-full rounded-[3px] border border-line-2 bg-surface-2 px-2.5 font-mono text-[11px]",
                "text-ink placeholder:text-ink-4",
                "focus:outline-none focus:ring-[3px] focus:ring-[var(--color-brier-blue)] focus:ring-offset-0",
                "disabled:opacity-50 sm:w-56",
              ].join(" ")}
              aria-label="Email address for badge waitlist"
            />
            <button
              type="submit"
              disabled={state === "submitting"}
              className={[
                "h-8 shrink-0 rounded-[3px] bg-[var(--color-navy)] px-3 font-mono text-[11px] text-white",
                "hover:bg-[var(--color-navy-2)] focus:outline-none focus:ring-[3px]",
                "focus:ring-[var(--color-brier-blue)] focus:ring-offset-0",
                "disabled:opacity-50",
                "transition-colors duration-[130ms] ease-out",
              ].join(" ")}
              aria-label={state === "submitting" ? "Joining waitlist" : "Join the badge waitlist"}
            >
              {state === "submitting" ? "Joining" : "Join waitlist"}
            </button>
          </form>
          {state === "error" && (
            <p className="mt-1.5 font-mono text-[10px] text-[var(--color-error)]" role="alert">
              {errorMsg}
            </p>
          )}
        </>
      )}
    </div>
  );
}
