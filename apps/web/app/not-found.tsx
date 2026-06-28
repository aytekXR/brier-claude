import Link from "next/link";

/**
 * 404 page (App Router). Neutral copy (AC-7); routes back to the leaderboard.
 */
export default function NotFound() {
  return (
    <div className="mx-auto max-w-[640px] py-16 text-center">
      <h1 className="font-serif text-2xl font-semibold text-ink">Page not found</h1>
      <p className="mt-3 text-ink-3">This page doesn&rsquo;t exist or has moved.</p>
      <Link
        href="/"
        className="mt-6 inline-block text-[var(--color-brier-blue)] hover:underline"
      >
        Back to the leaderboard
      </Link>
    </div>
  );
}
