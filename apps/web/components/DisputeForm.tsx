"use client";

/**
 * DisputeForm — client component for submitting a dispute ticket (E5-T3).
 *
 * FR-405, US-006, AC-5, UF-3.
 *
 * On submit: POST /api/disputes with { claimId, rationale, submittedBy? }.
 * On success: displays ticket reference + 7-day SLA countdown (AC-5/UF-3).
 * On error: displays a neutral error message.
 *
 * Accessible: labels, focus management, disabled-while-submitting.
 * Copy is strictly neutral (AC-7 firewall). No recommendation language.
 */

import { useEffect, useRef, useState } from "react";

/** Response from POST /api/disputes on success. */
type DisputeApiResponse = {
  ticketRef: string;
  slaDueAt: string; // ISO-8601 UTC string
  methodologyVersion: string;
};

type FormState =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "success"; data: DisputeApiResponse }
  | { kind: "error"; message: string };

const MAX_RATIONALE = 4000;

export function DisputeForm({ claimId }: { claimId: number }) {
  const [rationale, setRationale] = useState("");
  const [contact, setContact] = useState("");
  const [formState, setFormState] = useState<FormState>({ kind: "idle" });

  const rationaleRef = useRef<HTMLTextAreaElement>(null);
  const successRef = useRef<HTMLDivElement>(null);

  // Focus the success panel when it appears (UF-3, a11y).
  useEffect(() => {
    if (formState.kind === "success" && successRef.current) {
      successRef.current.focus();
    }
  }, [formState.kind]);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();

    const trimmedRationale = rationale.trim();
    if (!trimmedRationale) {
      rationaleRef.current?.focus();
      return;
    }

    setFormState({ kind: "submitting" });

    try {
      const body: Record<string, unknown> = {
        claimId,
        rationale: trimmedRationale,
      };
      const trimmedContact = contact.trim();
      if (trimmedContact) {
        body["submittedBy"] = trimmedContact;
      }

      const resp = await fetch("/api/disputes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (resp.ok) {
        const data = (await resp.json()) as DisputeApiResponse;
        setFormState({ kind: "success", data });
      } else {
        let message = "Unable to process the dispute. Please try again later.";
        try {
          const errBody = (await resp.json()) as { error?: string };
          if (typeof errBody.error === "string" && errBody.error.length > 0) {
            message = errBody.error;
          }
        } catch {
          // Keep the default message.
        }
        setFormState({ kind: "error", message });
      }
    } catch {
      setFormState({
        kind: "error",
        message: "Unable to reach the server. Please try again later.",
      });
    }
  }

  if (formState.kind === "success") {
    return (
      <SuccessPanel
        data={formState.data}
        ref={successRef}
      />
    );
  }

  const isSubmitting = formState.kind === "submitting";
  const rationaleLen = rationale.length;
  const rationaleOver = rationaleLen > MAX_RATIONALE;

  return (
    <form onSubmit={handleSubmit} noValidate className="px-5 py-5 space-y-5">
      {/* Rationale */}
      <div>
        <label
          htmlFor="dispute-rationale"
          className="block font-mono text-[11px] uppercase tracking-[0.1em] text-ink-3"
        >
          Rationale
          <span className="ml-1 text-[var(--color-error)]" aria-label="required">
            *
          </span>
        </label>
        <textarea
          id="dispute-rationale"
          ref={rationaleRef}
          name="rationale"
          rows={6}
          required
          disabled={isSubmitting}
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          placeholder="Describe the specific element of the claim or resolution that is contested, with supporting references where available."
          className="mt-2 w-full rounded-[3px] border border-line-2 bg-paper px-3 py-2.5 font-sans text-[13px] text-ink-2 placeholder:text-ink-4 focus:border-[var(--color-brier-blue)] focus:outline-none disabled:opacity-60 resize-y"
          aria-describedby={rationaleOver ? "rationale-limit-error" : "rationale-hint"}
        />
        <div className="mt-1 flex items-center justify-between gap-2">
          {rationaleOver ? (
            <p
              id="rationale-limit-error"
              className="font-mono text-[10.5px] text-[var(--color-error)]"
              role="alert"
            >
              Rationale exceeds {MAX_RATIONALE.toLocaleString()} characters.
            </p>
          ) : (
            <p id="rationale-hint" className="font-mono text-[10.5px] text-ink-4">
              State the factual basis for the dispute. No recommendation language.
            </p>
          )}
          <span className="num font-mono text-[10.5px] text-ink-4 tabular-nums">
            {rationaleLen}/{MAX_RATIONALE}
          </span>
        </div>
      </div>

      {/* Contact (optional) */}
      <div>
        <label
          htmlFor="dispute-contact"
          className="block font-mono text-[11px] uppercase tracking-[0.1em] text-ink-3"
        >
          Contact (optional)
        </label>
        <input
          id="dispute-contact"
          name="submittedBy"
          type="email"
          disabled={isSubmitting}
          value={contact}
          onChange={(e) => setContact(e.target.value)}
          placeholder="your@email.com"
          className="mt-2 w-full rounded-[3px] border border-line-2 bg-paper px-3 py-2 font-mono text-[12px] text-ink-2 placeholder:text-ink-4 focus:border-[var(--color-brier-blue)] focus:outline-none disabled:opacity-60"
          aria-describedby="contact-hint"
        />
        <p id="contact-hint" className="mt-1 font-mono text-[10.5px] text-ink-4">
          The ticket reference is returned in the response. Provide a contact to
          receive it by email (reviewed within 7 days).
        </p>
      </div>

      {/* Error message */}
      {formState.kind === "error" && (
        <div
          role="alert"
          className="rounded-[3px] border border-line-2 bg-surface-2 px-4 py-3 font-mono text-[12px] text-ink-3"
        >
          {formState.message}
        </div>
      )}

      {/* Submit */}
      <button
        type="submit"
        disabled={isSubmitting || rationaleOver || rationale.trim().length === 0}
        className="rounded-[3px] bg-[var(--color-navy)] px-5 py-2.5 font-sans text-[13px] font-medium text-white transition-opacity duration-150 hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isSubmitting ? "Submitting..." : "Submit dispute"}
      </button>
    </form>
  );
}

/**
 * Success panel shown after a dispute is accepted.
 * Displays the ticket reference and a client-side SLA countdown (AC-5/UF-3).
 */
const SuccessPanel = function SuccessPanelInner(
  {
    data,
    ref,
  }: {
    data: DisputeApiResponse;
    ref: React.Ref<HTMLDivElement>;
  },
) {
  const [daysRemaining, setDaysRemaining] = useState<number | null>(null);

  useEffect(() => {
    function computeDays() {
      const ms = new Date(data.slaDueAt).getTime() - Date.now();
      setDaysRemaining(Math.max(0, Math.ceil(ms / (1000 * 60 * 60 * 24))));
    }
    computeDays();
    // Refresh every minute so the countdown stays current on long-open tabs.
    const id = setInterval(computeDays, 60_000);
    return () => clearInterval(id);
  }, [data.slaDueAt]);

  const slaDateLabel = data.slaDueAt.slice(0, 10);

  return (
    <div
      ref={ref}
      tabIndex={-1}
      className="px-5 py-5 focus:outline-none"
      aria-live="polite"
    >
      <div className="rounded-[6px] border border-line-2 bg-surface-2 px-5 py-5">
        <div className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
          Dispute received
        </div>
        <div className="mt-3 space-y-3">
          <Row label="Ticket reference" value={data.ticketRef} />
          <Row
            label="Review target (SLA)"
            value={
              daysRemaining !== null
                ? `${slaDateLabel} · ${daysRemaining} day${daysRemaining === 1 ? "" : "s"} remaining`
                : slaDateLabel
            }
          />
          <Row label="Methodology at submission" value={data.methodologyVersion} />
        </div>
        <p className="mt-4 font-mono text-[11px] text-ink-4">
          The reviewer will examine the claim and rationale. The record will be updated
          when adjudication is complete.
        </p>
      </div>
    </div>
  );
};

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">{label}</dt>
      <dd className="num mt-0.5 font-mono text-[13px] text-ink-2">{value}</dd>
    </div>
  );
}
