/**
 * Subscriber seam — newsletter and badge waitlist capture (E5-T6).
 *
 * ADR-0013: Buttondown is behind a mock-first seam; FakeSubscriber is the
 * CI/build/dev default (no network); ButtondownSubscriber is the production
 * adapter, gated on BRIER_BUTTONDOWN_API_KEY + ADR-0013 approval.
 *
 * No SDK, no new npm dependency. Uses native fetch only.
 *
 * Double opt-in + one-click unsubscribe are provided by Buttondown natively;
 * our app initiates subscribe (returns pending = double opt-in initiated) and
 * calls unsubscribe on the one-click unsubscribe route.
 */

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

export type SubscribeKind = "newsletter" | "waitlist";

export type SubscribeParams = {
  email: string;
  kind: SubscribeKind;
  analystSlug?: string;
};

export type UnsubscribeParams = {
  email: string;
};

export type SubscribeResult = { status: "pending" };
export type UnsubscribeResult = { status: "unsubscribed" };

// ---------------------------------------------------------------------------
// Subscriber interface
// ---------------------------------------------------------------------------

export interface Subscriber {
  subscribe(params: SubscribeParams): Promise<SubscribeResult>;
  unsubscribe(params: UnsubscribeParams): Promise<UnsubscribeResult>;
}

// ---------------------------------------------------------------------------
// Shared email validation helper
// ---------------------------------------------------------------------------

/**
 * Validates an email address using a simple but robust regex.
 * Rejects empty strings and addresses without a domain part.
 */
export function validateEmail(email: string): boolean {
  if (!email || typeof email !== "string") return false;
  // RFC 5321 simplified: local@domain.tld; no spaces; domain has at least one dot.
  const pattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return pattern.test(email.trim()) && email.trim().length <= 254;
}

// ---------------------------------------------------------------------------
// FakeSubscriber — CI/build/dev default (no network)
// ---------------------------------------------------------------------------

export type FakeLogEntry =
  | { action: "subscribe"; email: string; kind: SubscribeKind; analystSlug?: string }
  | { action: "unsubscribe"; email: string };

/** Module-level log for FakeSubscriber — inspectable in tests and dev. */
const _fakeLog: FakeLogEntry[] = [];

export const FakeSubscriber: Subscriber = {
  async subscribe({ email, kind, analystSlug }: SubscribeParams): Promise<SubscribeResult> {
    if (!validateEmail(email)) {
      throw new Error(`Invalid email address: ${JSON.stringify(email)}`);
    }
    _fakeLog.push({ action: "subscribe", email: email.trim(), kind, analystSlug });
    return { status: "pending" };
  },

  async unsubscribe({ email }: UnsubscribeParams): Promise<UnsubscribeResult> {
    if (!validateEmail(email)) {
      throw new Error(`Invalid email address: ${JSON.stringify(email)}`);
    }
    _fakeLog.push({ action: "unsubscribe", email: email.trim() });
    return { status: "unsubscribed" };
  },
};

/** Read the FakeSubscriber log (for tests and dev introspection). */
export function getFakeLog(): ReadonlyArray<FakeLogEntry> {
  return _fakeLog;
}

/** Clear the FakeSubscriber log (for test isolation). */
export function clearFakeLog(): void {
  _fakeLog.splice(0);
}

// ---------------------------------------------------------------------------
// ButtondownSubscriber — production adapter (ADR-0013-gated)
// ---------------------------------------------------------------------------

type FetchFn = typeof fetch;

/** Buttondown Subscribers API base URL. */
const BUTTONDOWN_API = "https://api.buttondown.email/v1";

/**
 * ButtondownSubscriber — calls the Buttondown Subscribers REST API via native
 * fetch. The fetch callable is injected (defaults to global fetch) so tests can
 * supply a recorded-fixture fake without touching the network.
 *
 * Raises a clear Error referencing BRIER_BUTTONDOWN_API_KEY + ADR-0013 when the
 * key is absent, so CI fails loudly if misconfigured rather than silently.
 *
 * Double opt-in: subscribe sets type="regular" which triggers Buttondown's
 * built-in confirmation email. The subscriber is not enrolled until they click
 * the confirmation link. Our API returns { status: "pending" } immediately.
 *
 * One-click unsubscribe: unsubscribe PATCHes the subscriber's status to
 * "unsubscribed" so the change is immediate and idempotent.
 */
export function createButtondownSubscriber(fetchFn: FetchFn = fetch): Subscriber {
  function getApiKey(): string {
    const key = process.env.BRIER_BUTTONDOWN_API_KEY;
    if (!key) {
      throw new Error(
        "BRIER_BUTTONDOWN_API_KEY is not set. " +
          "Set this environment variable to enable the Buttondown newsletter integration. " +
          "See docs/adr/0013-newsletter-waitlist-via-buttondown-seam.md for the approval gate.",
      );
    }
    return key;
  }

  return {
    async subscribe({ email, kind, analystSlug }: SubscribeParams): Promise<SubscribeResult> {
      if (!validateEmail(email)) {
        throw new Error(`Invalid email address: ${JSON.stringify(email)}`);
      }
      const key = getApiKey();

      // Build tags: always include the kind; add analyst slug for waitlist.
      const tags: string[] = [kind];
      if (analystSlug) {
        tags.push(`waitlist:${analystSlug}`);
      }

      const body: Record<string, unknown> = {
        email_address: email.trim(),
        type: "regular", // triggers Buttondown double opt-in confirmation email
        tags,
      };

      const res = await fetchFn(`${BUTTONDOWN_API}/subscribers`, {
        method: "POST",
        headers: {
          Authorization: `Token ${key}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
      });

      // 201 = new subscriber created; double opt-in confirmation email sent.
      // 200 = Buttondown returned the existing subscriber record without error
      //       (address was already confirmed). We still return "pending" here
      //       because our API contract only promises that a confirmation was
      //       initiated — the caller should not infer confirmed status from this
      //       route (N-1: returning "pending" even for an already-confirmed
      //       address is intentional; it is neutral and avoids leaking state).
      if (res.ok) {
        return { status: "pending" };
      }

      // 400: only treat as idempotent success when Buttondown signals that this
      // address already exists as a subscriber. Any other 400 (banned domain,
      // malformed address, policy rejection) is a genuine error that must be
      // surfaced so the API route can return a useful response to the client.
      if (res.status === 400) {
        const body = await res.json().catch(() => null) as Record<string, unknown> | null;
        const code = typeof body?.code === "string" ? body.code : "";
        const message = typeof body?.message === "string" ? body.message : "";
        const isAlreadySubscribed =
          code === "email_already_exists" ||
          /already/i.test(message) ||
          /exists/i.test(message);
        if (isAlreadySubscribed) {
          return { status: "pending" };
        }
        const detail = body !== null ? JSON.stringify(body) : "(unreadable)";
        throw new Error(`Buttondown subscribe rejected (400): ${detail}`);
      }

      const text = await res.text().catch(() => "(unreadable)");
      throw new Error(`Buttondown subscribe failed (${res.status}): ${text}`);
    },

    async unsubscribe({ email }: UnsubscribeParams): Promise<UnsubscribeResult> {
      if (!validateEmail(email)) {
        throw new Error(`Invalid email address: ${JSON.stringify(email)}`);
      }
      const key = getApiKey();

      // First, look up the subscriber by email to get their id.
      const listRes = await fetchFn(
        `${BUTTONDOWN_API}/subscribers?email=${encodeURIComponent(email.trim())}`,
        {
          method: "GET",
          headers: { Authorization: `Token ${key}` },
        },
      );

      if (!listRes.ok) {
        const text = await listRes.text().catch(() => "(unreadable)");
        throw new Error(`Buttondown subscriber lookup failed (${listRes.status}): ${text}`);
      }

      const data = (await listRes.json()) as {
        results?: { id: string }[];
        count?: number;
      };

      const results = data.results ?? [];
      if (results.length === 0) {
        // Already not subscribed — return success (idempotent).
        return { status: "unsubscribed" };
      }

      const subscriberId = results[0]?.id;
      if (!subscriberId) {
        return { status: "unsubscribed" };
      }

      // PATCH to mark as unsubscribed.
      const patchRes = await fetchFn(`${BUTTONDOWN_API}/subscribers/${subscriberId}`, {
        method: "PATCH",
        headers: {
          Authorization: `Token ${key}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ subscriber_type: "unsubscribed" }),
      });

      if (!patchRes.ok) {
        const text = await patchRes.text().catch(() => "(unreadable)");
        throw new Error(`Buttondown unsubscribe failed (${patchRes.status}): ${text}`);
      }

      return { status: "unsubscribed" };
    },
  };
}

// ---------------------------------------------------------------------------
// Factory — returns FakeSubscriber unless BRIER_BUTTONDOWN_API_KEY is set
// ---------------------------------------------------------------------------

/**
 * Returns the appropriate Subscriber implementation based on environment.
 *
 * - FakeSubscriber (no network) when BRIER_BUTTONDOWN_API_KEY is absent.
 *   This is the CI/build/dev path.
 * - ButtondownSubscriber (real API) when BRIER_BUTTONDOWN_API_KEY is set.
 *   Gated on ADR-0013 approval.
 *
 * This factory must only be called at request time (inside route handlers),
 * never at module evaluation time during build, to preserve mock-first semantics.
 */
export function getSubscriber(): Subscriber {
  if (process.env.BRIER_BUTTONDOWN_API_KEY) {
    return createButtondownSubscriber();
  }
  return FakeSubscriber;
}
