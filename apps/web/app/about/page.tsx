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
  const file = path.join(process.cwd(), "..", "..", "docs", "LEGITIMATE_INTEREST.md");
  const markdown = await fs.readFile(file, "utf-8");

  return (
    <article className="methodology">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </article>
  );
}
