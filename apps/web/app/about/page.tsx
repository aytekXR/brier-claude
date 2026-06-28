import { promises as fs } from "node:fs";
import path from "node:path";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export const dynamic = "force-dynamic";

/**
 * NFR-6: the public legitimate-interest and data-requests page.
 * Renders docs/LEGITIMATE_INTEREST.md verbatim — the published document IS
 * the balancing-test artifact, so the page can never drift from the policy.
 */
export default async function AboutPage() {
  let markdown: string;
  try {
    const file = path.join(process.cwd(), "..", "..", "docs", "LEGITIMATE_INTEREST.md");
    markdown = await fs.readFile(file, "utf-8");
  } catch {
    // Missing file or unexpected working directory: degrade gracefully rather
    // than 500, matching the fallback discipline of the DB-reading routes.
    return (
      <article className="methodology">
        <p>This document is temporarily unavailable. Please check back shortly.</p>
      </article>
    );
  }

  return (
    <article className="methodology">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </article>
  );
}
