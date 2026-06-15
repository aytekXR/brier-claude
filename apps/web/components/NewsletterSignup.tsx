"use client";

/**
 * NewsletterSignup — compact site-wide footer form (E5-T6, US-007, FR-406).
 *
 * Posts to POST /api/newsletter. On success shows a neutral double-opt-in
 * confirmation message. On error shows a neutral error message.
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

export function NewsletterSignup() {
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
      const res = await fetch("/api/newsletter", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
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

  if (state === "success") {
    return (
      <p className="font-mono text-[10.5px] text-ink-3">
        Check your inbox to confirm your subscription (double opt-in).
      </p>
    );
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <label htmlFor="newsletter-email" className="sr-only">
        Email address
      </label>
      <input
        id="newsletter-email"
        type="email"
        name="email"
        autoComplete="email"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        disabled={state === "submitting"}
        placeholder="your@email.com"
        className={[
          "h-8 w-full rounded-[3px] border border-line-2 bg-surface px-2.5 font-mono text-[11px]",
          "text-ink placeholder:text-ink-4",
          "focus:outline-none focus:ring-[3px] focus:ring-[var(--color-brier-blue)] focus:ring-offset-0",
          "disabled:opacity-50 sm:w-52",
        ].join(" ")}
        aria-label="Email address for weekly digest"
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
        aria-label={state === "submitting" ? "Subscribing" : "Subscribe to weekly digest"}
      >
        {state === "submitting" ? "Subscribing" : "Subscribe"}
      </button>
      {state === "error" && (
        <p className="w-full font-mono text-[10px] text-[var(--color-error)] sm:w-auto" role="alert">
          {errorMsg}
        </p>
      )}
    </form>
  );
}
