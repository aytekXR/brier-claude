"use client";

import { useEffect } from "react";

/**
 * Global error boundary (App Router). Catches unhandled exceptions in a route
 * segment so a runtime failure degrades to a neutral, on-brand page instead of
 * a raw 500. Copy is strictly neutral (AC-7) and makes no claim about any
 * instrument or action.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surfaced to the server logs / monitoring; no sensitive detail is shown.
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto max-w-[640px] py-16 text-center">
      <h1 className="font-serif text-2xl font-semibold text-ink">Something went wrong</h1>
      <p className="mt-3 text-ink-3">
        An unexpected error occurred while loading this page. The track record itself is unaffected.
      </p>
      <button
        type="button"
        onClick={reset}
        className="mt-6 rounded-[3px] border border-line px-4 py-2 text-sm text-ink hover:bg-paper-2"
      >
        Try again
      </button>
    </div>
  );
}
